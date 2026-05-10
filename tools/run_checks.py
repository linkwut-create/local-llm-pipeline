#!/usr/bin/env python3
"""
One-shot local check: runs all non-LLM verifications.

Does NOT call Ollama or any local model.
Exit code 0 = all checks pass, 1 = at least one failure.

Usage:
    python tools/run_checks.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
TOOLS_DIR = SCRIPT_DIR

REQUIRED_PYTHON = (3, 10)

POLICY_MARKER = "## Local Multi-Model Worker Policy"


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def check_python_version() -> bool:
    ok = sys.version_info >= REQUIRED_PYTHON
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"  [{_status(ok)}] Python >= {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}: {v}")
    return ok


def check_requests_installed() -> bool:
    try:
        import requests  # noqa: F401
        print(f"  [{_status(True)}] requests installed: {requests.__version__}")
        return True
    except ImportError:
        print(f"  [{_status(False)}] requests not installed")
        return False


def check_pytest_available() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        ok = result.returncode == 0
        version_line = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
        print(f"  [{_status(ok)}] pytest: {version_line}")
        return ok
    except Exception as e:
        print(f"  [{_status(False)}] pytest: {e}")
        return False


def _is_source_repo_mode() -> bool:
    """Return True when run_checks runs inside the local-llm-pipeline source repo.

    Detected by presence of .git, VERSION, and full tests/ directory with
    pipeline-specific test files.
    """
    return (
        (PROJECT_ROOT / ".git").exists()
        and (PROJECT_ROOT / "VERSION").exists()
        and (PROJECT_ROOT / "tests" / "test_mcp_server.py").exists()
    )


def run_pytest() -> bool:
    """Run pytest for the current mode.

    source_repo_mode:  run full pytest on all tests.
    installed-project mode: run only pipeline-scoped subset tests.

    Set RUN_CHECKS_SKIP_PYTEST=1 to skip (useful for testing run_checks itself).
    """
    if os.environ.get("RUN_CHECKS_SKIP_PYTEST") == "1":
        print(f"  [SKIP] pytest (RUN_CHECKS_SKIP_PYTEST=1)")
        return True

    source_repo = _is_source_repo_mode()
    mode_label = "source_repo_mode=true" if source_repo else "source_repo_mode=false"

    if source_repo:
        # Full pytest — every test must pass for a release gate
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=short"],
                capture_output=True, text=True, timeout=600,
                cwd=str(PROJECT_ROOT),
                encoding="utf-8", errors="replace",
            )
            ok = result.returncode == 0
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout else ""
            print(f"  [{_status(ok)}] pytest ({mode_label}): {last_line}")
            if not ok and result.stdout:
                for line in result.stdout.strip().split("\n")[-5:]:
                    print(f"         {line}")
            return ok
        except Exception as e:
            print(f"  [{_status(False)}] pytest ({mode_label}): {e}")
            return False
    else:
        # Installed-project mode: only pipeline-scoped subset
        tests_dir = PROJECT_ROOT / "tests"
        pipeline_tests = sorted(tests_dir.glob("test_local_llm_*.py"))
        if not pipeline_tests:
            print(f"  [SKIP] No pipeline test files found (tests/test_local_llm_*.py)")
            return True
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *(str(p) for p in pipeline_tests),
                 "-q", "--tb=short"],
                capture_output=True, text=True, timeout=180,
                cwd=str(PROJECT_ROOT),
                encoding="utf-8", errors="replace",
            )
            ok = result.returncode == 0
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout else ""
            print(f"  [{_status(ok)}] pytest ({mode_label}, {len(pipeline_tests)} file(s)): {last_line}")
            if not ok and result.stdout:
                for line in result.stdout.strip().split("\n")[-5:]:
                    print(f"         {line}")
            return ok
        except Exception as e:
            print(f"  [{_status(False)}] pytest ({mode_label}): {e}")
            return False


def check_json_schema(name: str, path: Path, required_keys: list[str]) -> bool:
    if not path.exists():
        print(f"  [{_status(False)}] {name}: file not found at {path}")
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in required_keys if k not in data]
        if missing:
            print(f"  [{_status(False)}] {name}: missing top-level keys: {missing}")
            return False
        print(f"  [{_status(True)}] {name}: valid ({len(data.get('tasks', data.get('profiles', {})))} entries)")
        return True
    except json.JSONDecodeError as e:
        print(f"  [{_status(False)}] {name}: invalid JSON: {e}")
        return False


def check_policy_marker(path: Path) -> bool:
    if not path.exists():
        print(f"  [SKIP] {path.name}: file does not exist")
        return True
    content = path.read_text(encoding="utf-8")
    ok = POLICY_MARKER in content
    print(f"  [{_status(ok)}] {path.name}: policy marker {'present' if ok else 'MISSING'}")
    return ok


def check_gitignore() -> bool:
    gi = PROJECT_ROOT / ".gitignore"
    if not gi.exists():
        print(f"  [{_status(False)}] .gitignore: file not found")
        return False
    content = gi.read_text(encoding="utf-8")
    ok = ".local_llm_out" in content
    print(f"  [{_status(ok)}] .gitignore: .local_llm_out/ {'present' if ok else 'MISSING'}")
    return ok


def check_tool_files_exist() -> bool:
    required = ["local_llm_worker.py", "local_llm_router.py", "local_llm_check.py",
                 "local_llm_profiles.json", "local_llm_tasks.json",
                 "local_llm_debate.py", "local_llm_mcp_server.py"]
    missing = [f for f in required if not (TOOLS_DIR / f).exists()]
    ok = len(missing) == 0
    if ok:
        print(f"  [{_status(True)}] Core tool files: all {len(required)} present")
    else:
        print(f"  [{_status(False)}] Core tool files missing: {missing}")
    return ok


def check_config_schema() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "validate_configs.py"), "--quiet"],
            capture_output=True, text=True, timeout=15,
            cwd=str(PROJECT_ROOT),
        )
        ok = result.returncode == 0
        print(f"  [{_status(ok)}] profiles.json + tasks.json: {'valid' if ok else 'has errors'}")
        if not ok and result.stderr:
            for line in result.stderr.strip().split("\n")[-3:]:
                print(f"         {line.strip()}")
        return ok
    except Exception as e:
        print(f"  [{_status(False)}] config schema check failed: {e}")
        return False


def check_mcp_docs_exist() -> bool:
    doc = PROJECT_ROOT / "docs" / "local-llm-mcp.md"
    ok = doc.exists()
    print(f"  [{_status(ok)}] docs/local-llm-mcp.md: {'present' if ok else 'MISSING'}")
    return ok


def check_mcp_no_dangerous_tools() -> bool:
    """Verify MCP server does not expose dangerous tool names."""
    tool_file = TOOLS_DIR / "local_llm_mcp_server.py"
    if not tool_file.exists():
        print(f"  [SKIP] MCP server file not found")
        return True
    forbidden = ["write", "delete", "shell", "exec", "commit", "push", "tag", "deploy"]
    content = tool_file.read_text(encoding="utf-8")
    found = []
    for kw in forbidden:
        if re.search(r'"local_' + kw, content, re.IGNORECASE):
            found.append(kw)
    ok = len(found) == 0
    if ok:
        print(f"  [{_status(True)}] MCP: no dangerous tool names exposed")
    else:
        print(f"  [{_status(False)}] MCP: dangerous tool names found: {found}")
    return ok


def main() -> int:
    print("=" * 60)
    print("  Local LLM Pipeline — Non-LLM Checks")
    print(f"  source_repo_mode={_is_source_repo_mode()}")
    print("=" * 60)

    results = []

    print("\n[Environment]")
    results.append(check_python_version())
    results.append(check_requests_installed())
    results.append(check_pytest_available())

    print("\n[Tests]")
    results.append(run_pytest())

    print("\n[Tool Files]")
    results.append(check_tool_files_exist())

    print("\n[Config Schema]")
    results.append(check_config_schema())

    print("\n[MCP]")
    results.append(check_mcp_docs_exist())
    results.append(check_mcp_no_dangerous_tools())

    print("\n[JSON Config]")
    results.append(check_json_schema(
        "profiles.json", TOOLS_DIR / "local_llm_profiles.json",
        ["profiles", "default_profile"],
    ))
    results.append(check_json_schema(
        "tasks.json", TOOLS_DIR / "local_llm_tasks.json",
        ["tasks"],
    ))

    print("\n[Policy & Gitignore]")
    results.append(check_policy_marker(PROJECT_ROOT / "AGENTS.md"))
    results.append(check_policy_marker(PROJECT_ROOT / "CLAUDE.md"))
    results.append(check_gitignore())

    passed = sum(results)
    total = len(results)
    all_ok = all(results)

    print(f"\n{'=' * 60}")
    print(f"  Result: {passed}/{total} checks passed")
    if all_ok:
        print("  ALL CHECKS PASSED")
    else:
        print("  SOME CHECKS FAILED — review above")
    print(f"{'=' * 60}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
