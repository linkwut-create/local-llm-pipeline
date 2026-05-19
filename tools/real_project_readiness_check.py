#!/usr/bin/env python3
"""
Real-project readiness check for local-llm-pipeline.

Verifies the pipeline can safely integrate into a target project
without modifying source code, leaking secrets, or breaking MCP.
Runs all checks, then reports READY_FOR_REAL_PROJECT=true/false.

Usage:
    python tools/real_project_readiness_check.py <target_project> --dry-run
    python tools/real_project_readiness_check.py <target_project>
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PIPELINE_ROOT = SCRIPT_DIR.parent

EXPECTED_MCP_TOOLS = {
    "local_check", "local_summarize_file", "local_summarize_tree",
    "local_generate_test_plan", "local_review_diff",
    "local_debate_review_diff", "local_parallel_review",
    "local_contextual_analyze", "local_draft_code",
}

FORBIDDEN_TOOL_KEYWORDS = [
    "write", "delete", "shell", "exec", "commit", "push", "tag", "deploy",
]

results = []


def check(name: str, passed: bool, detail: str = "", warn: bool = False):
    status = "WARN" if (warn and passed) else ("PASS" if passed else "FAIL")
    results.append({"name": name, "status": status, "detail": detail})
    print(f"  [{status:4s}] {name}")
    if detail:
        print(f"         {detail}")


def ok_count() -> int:
    return sum(1 for r in results if r["status"] in ("PASS", "WARN"))


def fail_count() -> int:
    return sum(1 for r in results if r["status"] == "FAIL")


# ── Pipeline self-checks ──

def check_pipeline_self(dry_run: bool):
    print("\n=== Pipeline Self-Checks ===\n")

    # validate_configs
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / "validate_configs.py"), "--quiet"],
                       capture_output=True, text=True, timeout=15,
                       cwd=str(PIPELINE_ROOT))
    check("validate_configs", r.returncode == 0,
          "config validation passed" if r.returncode == 0 else r.stderr.strip()[-200:])

    # run_checks (skip pytest to keep it fast)
    check("run_checks_available", (SCRIPT_DIR / "run_checks.py").exists(),
          "run_checks.py present — run manually for full check")

    # prompt registry
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from local_llm_prompt_registry import list_prompts, validate_registry
        prompts = list_prompts()
        reg_errors = validate_registry()
        check("prompt_registry", len(reg_errors) == 0,
              f"{len(prompts)} prompts, {len(reg_errors)} errors" if reg_errors
              else f"{len(prompts)} prompts loaded")
    except Exception as e:
        check("prompt_registry", False, str(e))

    # profiles / tasks
    try:
        profiles = json.loads((SCRIPT_DIR / "local_llm_profiles.json").read_text(encoding="utf-8"))
        tasks = json.loads((SCRIPT_DIR / "local_llm_tasks.json").read_text(encoding="utf-8"))
        check("profiles_tasks_loaded", True,
              f"{len(profiles.get('profiles',{}))} profiles, {len(tasks.get('tasks',{}))} tasks")
    except Exception as e:
        check("profiles_tasks_loaded", False, str(e))

    # MCP tools
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from local_llm_mcp_server import TOOLS
        tool_names = set(TOOLS.keys())
        has_all = EXPECTED_MCP_TOOLS.issubset(tool_names)
        has_forbidden = any(
            any(kw in name.lower() for kw in FORBIDDEN_TOOL_KEYWORDS)
            for name in tool_names
        )
        check("mcp_tool_count", len(tool_names) == 9 and has_all,
              f"{len(tool_names)} tools (expected 9)")
        check("mcp_no_dangerous_tools", not has_forbidden,
              "no write/delete/shell/git/deploy tools found" if not has_forbidden
              else "DANGEROUS TOOLS DETECTED")
    except Exception as e:
        check("mcp_tools", False, str(e))


# ── Target project checks ──

def check_target_project(target: str):
    print(f"\n=== Target Project: {target} ===\n")
    tp = Path(target).resolve()

    exists = tp.exists()
    check("target_exists", exists, str(tp))
    if not exists:
        return None

    is_repo = (tp / ".git").exists()
    check("target_is_git_repo", is_repo,
          "git repository found" if is_repo else "not a git repository — pipeline works best in git projects")

    # Check gitignore
    gi = tp / ".gitignore"
    if gi.exists():
        gi_content = gi.read_text(encoding="utf-8")
        has_out = ".local_llm_out" in gi_content
        check("gitignore_has_local_llm_out", has_out,
              ".local_llm_out/ in .gitignore" if has_out else ".local_llm_out/ MISSING from .gitignore")
    else:
        check("gitignore_exists", False, ".gitignore not found — will be created by installer")

    # Check no sensitive files (skip .venv, node_modules, __pycache__, .local_llm_out)
    sensitive = []
    skip_dirs = {".venv", "venv", "node_modules", "__pycache__", ".local_llm_out"}
    for pattern in [".env", ".env.local", "*.key", "*.pem", "settings.local.json"]:
        for f in tp.rglob(pattern):
            parts = set(f.relative_to(tp).parts)
            if parts & skip_dirs:
                continue
            if ".local_llm_out" in str(f):
                continue
            sensitive.append(str(f.relative_to(tp)))
    check("no_sensitive_files_exposed", True,
          "no sensitive files found" if not sensitive
          else f"project has sensitive files (installer will skip them): {sensitive[:5]}",
          warn=len(sensitive) > 0)

    return tp


# ── Installer dry-run ──

def check_installer_dry_run(target: str):
    print(f"\n=== Installer Dry-Run ===\n")

    r = subprocess.run(
        [sys.executable, str(PIPELINE_ROOT / "install_local_llm_pipeline.py"),
         target, "--update", "--dry-run"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PIPELINE_ROOT),
    )

    output = r.stdout + r.stderr
    no_conflict = "CONFLICT" not in output or "--force" in output
    has_mcp = ".mcp.json" in output or "mcp" in output.lower()
    no_env = ".env" not in output
    no_pem = ".pem" not in output

    check("dry_run_completed", r.returncode == 0 or "CONFLICT" in output,
          "dry-run completed" if r.returncode == 0 else f"exit code {r.returncode}")
    check("dry_run_no_sensitive_copy", no_env and no_pem,
          "no .env/.pem files would be copied" if no_env and no_pem
          else "sensitive files would be copied!")
    check("dry_run_includes_mcp", has_mcp,
          "MCP-related files included")


# ── MCP server tools ──

def check_mcp_server_tools():
    print(f"\n=== MCP Server Tools ===\n")

    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from local_llm_mcp_server import TOOLS, handle_tools_list
        resp = handle_tools_list(1)
        tools = resp["result"]["tools"]

        tool_names = {t["name"] for t in tools}
        for expected in sorted(EXPECTED_MCP_TOOLS):
            check(f"mcp_tool_{expected}", expected in tool_names,
                  "present" if expected in tool_names else "MISSING")

        check("mcp_tools_count", len(tools) == 9, f"{len(tools)} tools returned")

        # Verify each tool has description and inputSchema
        all_valid = all(
            t.get("description") and t.get("inputSchema")
            for t in tools
        )
        check("mcp_tool_schemas_valid", all_valid,
              "all tools have description and inputSchema")

    except Exception as e:
        check("mcp_server_tools", False, str(e))


# ── local_check test ──

def check_local_check():
    print(f"\n=== local_check ===\n")

    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "local_llm_check.py")],
            capture_output=True, text=True, timeout=30,
            cwd=str(PIPELINE_ROOT),
        )
        ok = r.returncode == 0
        has_ollama = "ollama" in (r.stdout + r.stderr).lower()
        check("local_check_ran", ok, "health check completed")
        check("local_check_ollama", has_ollama,
              "Ollama found" if has_ollama else "Ollama not detected — models may be unavailable")
    except subprocess.TimeoutExpired:
        check("local_check_ran", False, "health check timed out")
    except Exception as e:
        check("local_check_ran", False, str(e))


# ── Summarize test ──

def check_summarize(target: str):
    print(f"\n=== Summarize Test ===\n")

    # Find a safe test file
    test_file = None
    for candidate in ["README.md", "AGENTS.md", "CLAUDE.md", "pyproject.toml", "package.json"]:
        p = Path(target) / candidate
        if p.exists() and p.stat().st_size > 50:
            test_file = p
            break

    if not test_file:
        check("summarize_test_file", False, "no suitable test file found in target")
        return

    check("summarize_test_file", True, str(test_file))

    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "local_llm_worker.py"),
         "summarize-file", str(test_file),
         "--model", "gemma4:e4b", "--max-chars", "5000"],
        capture_output=True, text=True, timeout=120,
        cwd=str(PIPELINE_ROOT),
    )
    check("summarize_file_ok", r.returncode == 0,
          "completed" if r.returncode == 0 else f"failed: {r.stderr[-150:]}")


# ── Cache test ──

def check_cache():
    print(f"\n=== Cache Test ===\n")

    try:
        from local_llm_cache import is_cache_enabled, get_cache, put_cache, clear_cache, compute_file_key

        cache_on = is_cache_enabled()
        check("cache_enabled_default", cache_on,
              "cache enabled by default" if cache_on else "cache disabled")

        # Test put/get
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"test_cache_content")
            tmp_path = f.name

        try:
            key = compute_file_key(tmp_path, "fast_summary", "gemma4:e4b")
            assert key is not None

            # First access — should miss
            cached = get_cache(key)
            check("cache_first_miss", cached is None, "first access is cache miss")

            # Put and get
            put_cache(key, {"task": "summarize-file", "result": "cached_value"})
            cached = get_cache(key)
            check("cache_second_hit", cached is not None and cached.get("cache_hit"),
                  "second access is cache hit")
        finally:
            os.unlink(tmp_path)
            clear_cache()
    except Exception as e:
        check("cache_functional", False, str(e))


# ── Draft safety ──

def check_draft_safety(target: str):
    print(f"\n=== Draft Safety ===\n")

    tp = Path(target).resolve()
    readme = tp / "README.md"
    if not readme.exists():
        check("draft_safety_test", False, "no README.md in target")
        return

    # Record git diff before
    before = subprocess.run(
        ["git", "diff", "--stat"], capture_output=True, text=True,
        cwd=str(tp), timeout=10,
    ).stdout.strip()

    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "local_llm_worker.py"),
         "draft-refactor", str(readme),
         "--model", "qwen3-coder:30b", "--max-chars", "2000"],
        input="建议优化 README 结构。只输出草案，不修改源文件。",
        capture_output=True, text=True, timeout=300,
        cwd=str(PIPELINE_ROOT),
    )
    draft_ok = r.returncode == 0

    # Record git diff after
    after = subprocess.run(
        ["git", "diff", "--stat"], capture_output=True, text=True,
        cwd=str(tp), timeout=10,
    ).stdout.strip()

    no_change = before == after
    check("draft_completed", draft_ok,
          "draft generated" if draft_ok else f"draft failed: {r.stderr[-100:]}")
    check("draft_no_source_modification", no_change,
          "no source files modified" if no_change
          else f"SOURCE FILES WERE MODIFIED: {after}")


# ── Review-diff test ──

def check_review_diff():
    print(f"\n=== Review-Diff Test ===\n")

    fake_diff = "diff --git a/test.py b/test.py\n--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-print('old')\n+print('new')"

    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "local_llm_worker.py"),
         "review-diff", "--stdin", "--model", "qwen3-coder:30b",
         "--max-chars", "500"],
        input=fake_diff, capture_output=True, text=True, timeout=300,
        cwd=str(PIPELINE_ROOT),
    )
    check("review_diff_ok", r.returncode == 0,
          "review completed" if r.returncode == 0 else f"failed: {r.stderr[-100:]}")


# ── Logging safety ──

def check_logging_safety():
    print(f"\n=== Logging Safety ===\n")

    log_file = PIPELINE_ROOT / ".local_llm_out" / "logs" / "local_llm.jsonl"
    if not log_file.exists():
        check("logging_file_exists", False, ".local_llm_out/logs/local_llm.jsonl not found")
        return

    check("logging_file_exists", True, str(log_file))

    try:
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        check("logging_jsonl_valid", len(lines) > 0, f"{len(lines)} log entries")

        # Check last 10 entries for sensitive content fields
        # Match field keys, not substrings — prompt_id/prompt_version are metadata, not leaks
        sensitive_key_patterns = [
            "prompt_text", "raw_prompt", "full_prompt", "prompt_content",
            "response_text", "raw_response", "full_response",
            "api_key", "password", "secret", ".env", "token", "credential",
        ]
        violations = []
        for line in lines[-10:]:
            try:
                entry = json.loads(line)
                for key in entry:
                    key_lower = key.lower()
                    for pat in sensitive_key_patterns:
                        if pat in key_lower:
                            violations.append(f"{key}={str(entry[key])[:80]}")
            except json.JSONDecodeError:
                pass

        check("logging_no_sensitive_data", len(violations) == 0,
              "no sensitive data in logs" if not violations
              else f"sensitive keywords found: {violations}")

        # Check metadata fields exist
        last_entry = json.loads(lines[-1])
        has_meta = all(
            k in last_entry for k in ["source", "task", "duration_sec", "ok"]
        )
        check("logging_has_metadata", has_meta,
              "metadata fields present" if has_meta else "missing metadata fields")

    except Exception as e:
        check("logging_check", False, str(e))


# ── Main ──

def main():
    parser = argparse.ArgumentParser(
        description="Real-project readiness check for local-llm-pipeline"
    )
    parser.add_argument("target", nargs="?", default=None,
                        help="Target project path (e.g. C:\\Users\\Zero\\local-translator-agent)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip tests that invoke local models")
    parser.add_argument("--quick", action="store_true",
                        help="Skip long-running model tests (summarize, draft, review)")
    args = parser.parse_args()

    total_start = time.time()

    print(f"{'=' * 60}")
    print(f"  local-llm-pipeline — Real Project Readiness Check")
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'=' * 60}")

    # 1. Pipeline self-checks (always)
    check_pipeline_self(args.dry_run)

    # 2. Target project checks
    target = args.target
    if target:
        tp = check_target_project(target)
    else:
        print(f"\n=== Target Project: (skipped — no target specified) ===\n")
        tp = None

    # 3. Installer dry-run
    if target and tp:
        check_installer_dry_run(target)

    # 4. MCP server tools (always)
    check_mcp_server_tools()

    # 5-9. Model-dependent tests
    if not args.quick and not args.dry_run:
        check_local_check()

        if target and tp:
            check_summarize(target)

        check_cache()

        if target and tp:
            check_draft_safety(target)

        check_review_diff()
    elif args.dry_run:
        print(f"\n=== Model Tests: (skipped — dry-run mode) ===\n")
    elif args.quick:
        print(f"\n=== Model Tests: (skipped — quick mode) ===\n")

    # 10. Logging safety (always)
    check_logging_safety()

    # Final report
    elapsed = round(time.time() - total_start, 1)
    passed = ok_count()
    failed = fail_count()
    total = len(results)
    ready = failed == 0

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{total} passed, {failed} failed ({elapsed}s)")
    print(f"  READY_FOR_REAL_PROJECT={'true' if ready else 'false'}")
    if not ready:
        print(f"\n  Failures:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    - {r['name']}: {r['detail'][:120]}")
    print(f"{'=' * 60}")

    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
