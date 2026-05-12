#!/usr/bin/env python3
"""MCP Hook Doctor — diagnostic tool for the MCP gate hook system.

Read-only. Reports OK/WARN/FAIL for each subsystem. No automatic fixes.

Usage:
    python tools/claude_hooks/mcp_doctor.py
    python tools/claude_hooks/mcp_doctor.py --json
    python tools/claude_hooks/mcp_doctor.py --repo-root /path/to/repo
    python tools/claude_hooks/mcp_doctor.py --config-dir /path/to/config
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _default_config_dir() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        return str(Path(local_app_data) / "mcp-gate")
    return str(Path.home() / ".config" / "mcp-gate")


def run_checks(repo_root: str, config_dir: str) -> list[dict]:
    """Run all checks. Returns list of {check, status, message, detail}."""
    results = []

    # -- helpers --
    def ok(check, msg, detail=None):
        results.append({"check": check, "status": "OK", "message": msg, "detail": detail})

    def warn(check, msg, detail=None):
        results.append({"check": check, "status": "WARN", "message": msg, "detail": detail})

    def fail(check, msg, detail=None):
        results.append({"check": check, "status": "FAIL", "message": msg, "detail": detail})

    repo = Path(repo_root)
    config = Path(config_dir)

    # =================================================================
    # 1. Environment
    # =================================================================
    if repo.is_dir():
        ok("repo_root_exists", f"Repo root exists: {repo}")
    else:
        fail("repo_root_exists", f"Repo root not found: {repo}",
             "Verify the path or use --repo-root to point to the correct location.")

    ok("python_exe", f"Python: {sys.executable}")

    encoding = sys.getdefaultencoding()
    if encoding.lower() in ("utf-8", "utf8"):
        ok("platform_encoding", f"Default encoding: {encoding}")
    else:
        warn("platform_encoding", f"Default encoding is {encoding}, not UTF-8",
             "Non-UTF-8 encoding can cause UnicodeDecodeError in git diff output. "
             "The hook's run_git() uses encoding='utf-8' as a workaround.")

    try:
        from tools.claude_hooks.mcp_gate import run_git
        git_root = run_git(["rev-parse", "--show-toplevel"])
        if git_root:
            ok("git_repo", f"Git repo detected: {git_root}")
        else:
            warn("git_repo", "Not in a git repository",
                 "Many hook features (commit gate, fingerprint) require a git repo.")
    except Exception as e:
        warn("git_repo", f"Could not check git repo: {e}")

    # =================================================================
    # 2. Module health
    # =================================================================
    gate_module = repo / "tools" / "claude_hooks" / "mcp_gate.py"
    if gate_module.is_file():
        ok("mcp_gate_module_exists", f"Module found: {gate_module}")
    else:
        fail("mcp_gate_module_exists", f"Module not found: {gate_module}",
             "Run: git clone or restore tools/claude_hooks/mcp_gate.py")

    try:
        import tools.claude_hooks.mcp_gate as mg
        ok("mcp_gate_importable", "Module imports successfully")
    except Exception as e:
        fail("mcp_gate_importable", f"Cannot import module: {e}",
             f"Check sys.path includes the repo root: {repo_root}")
        # Can't continue without the module — skip remaining checks
        results.append({"check": "_early_return", "status": "FAIL",
                        "message": "Cannot continue without mcp_gate module"})
        return results

    required_funcs = ["main", "load_state", "save_state", "run_git",
                      "get_repo_fingerprint", "get_diff_hash",
                      "handle_pre_tooluse", "handle_post_tooluse",
                      "handle_stop", "handle_session_start",
                      "is_dangerous_command", "is_release_command",
                      "review_tool_succeeded"]
    missing = [f for f in required_funcs if not hasattr(mg, f)]
    if missing:
        fail("key_functions", f"Missing functions: {', '.join(missing)}",
             "The module may be outdated or corrupt. Reinstall from source.")
    else:
        ok("key_functions", f"All {len(required_funcs)} required functions present")

    # =================================================================
    # 3. Hook installation
    # =================================================================
    claude_dir = Path.home() / ".claude"
    wrapper = claude_dir / "hooks" / "mcp_gate.py"
    settings_file = claude_dir / "settings.json"

    if wrapper.is_file():
        wrapper_text = wrapper.read_text(encoding="utf-8", errors="replace")
        if "tools.claude_hooks.mcp_gate" in wrapper_text:
            ok("wrapper_exists", f"Wrapper found and references repo module: {wrapper}")
        else:
            warn("wrapper_exists", f"Wrapper found but may not reference repo module: {wrapper}",
                 "Wrapper should import from tools.claude_hooks.mcp_gate, not a stale copy.")
    else:
        fail("wrapper_exists", f"Wrapper not found: {wrapper}",
             "Create ~/.claude/hooks/mcp_gate.py that imports from tools.claude_hooks.mcp_gate")

    if settings_file.is_file():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
            ok("settings_json_valid", "settings.json exists and is valid JSON")
        except Exception as e:
            fail("settings_json_valid", f"settings.json parse error: {e}",
                 "Fix or regenerate ~/.claude/settings.json")
            settings = {}
    else:
        fail("settings_json_valid", f"settings.json not found: {settings_file}",
             "Create ~/.claude/settings.json with hook registrations")
        settings = {}

    expected_hooks = ["SessionStart", "PreToolUse", "PostToolUse", "Stop"]
    hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
    for hook_name in expected_hooks:
        if hook_name in hooks:
            entries = hooks[hook_name]
            if isinstance(entries, list) and len(entries) > 0:
                cmd = entries[0].get("command", "") if isinstance(entries[0], dict) else str(entries[0])
                ok(f"hook_{hook_name}", f"{hook_name} registered: {cmd[:80]}")
            else:
                fail(f"hook_{hook_name}", f"{hook_name} has no matchers",
                     f"Add a matcher entry under hooks.{hook_name} in settings.json")
        else:
            fail(f"hook_{hook_name}", f"{hook_name} not registered",
                 f"Add hooks.{hook_name} to settings.json with the wrapper command.")

    # =================================================================
    # 4. State health
    # =================================================================
    if config.is_dir():
        ok("config_dir_exists", f"Config dir exists: {config}")
    else:
        fail("config_dir_exists", f"Config dir not found: {config}",
             "The hook will attempt to create it on first run. Run any hook event to initialize.")

    state = {}
    try:
        state = mg.load_state(str(config))
        if isinstance(state, dict):
            ok("state_readable", "state.json loaded successfully")
        else:
            fail("state_readable", "state.json loaded but is not a dict",
                 f"Delete {config / 'state.json'} and let the hook recreate it.")
            state = {}
    except Exception as e:
        fail("state_readable", f"Cannot read state.json: {e}",
             f"Check permissions or delete {config / 'state.json'}")

    expected_keys = list(mg._STATE_DEFAULTS.keys()) if hasattr(mg, '_STATE_DEFAULTS') else []
    if expected_keys and isinstance(state, dict):
        missing_keys = [k for k in expected_keys if k not in state]
        if missing_keys:
            warn("state_keys", f"Missing expected keys: {', '.join(missing_keys)}",
                 "Old state file? It will be auto-healed on next hook run.")
        else:
            ok("state_keys", f"All {len(expected_keys)} expected keys present")

    try:
        diff_hash = mg.get_diff_hash()
        if diff_hash is not None:
            ok("diff_hash_valid", f"Diff hash: {diff_hash[:16]}...")
        else:
            warn("diff_hash_valid", "get_diff_hash() returned None",
                 "Possible causes: not in a git repo, or encoding error. "
                 "The hook uses UTF-8 encoding; check git diff output for non-UTF-8 content.")
    except Exception as e:
        fail("diff_hash_valid", f"get_diff_hash() raised: {e}",
             "This is a critical bug — the commit gate cannot validate reviews without a hash.")

    # =================================================================
    # 5. Log health
    # =================================================================
    log_file = config / "hook-events.jsonl"
    try:
        if log_file.is_file():
            log_file.read_text(encoding="utf-8")
        ok("log_readable", f"hook-events.jsonl readable ({log_file.stat().st_size if log_file.is_file() else 0} bytes)")
    except Exception as e:
        fail("log_readable", f"Cannot read hook-events.jsonl: {e}",
             f"Check permissions on {log_file}")

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            pass
        ok("log_writable", "hook-events.jsonl writable")
    except Exception as e:
        fail("log_writable", f"Cannot write to hook-events.jsonl: {e}",
             f"Check disk space and permissions on {log_file}")

    log_size = log_file.stat().st_size if log_file.is_file() else 0
    mb = log_size / (1024 * 1024)
    if mb < 5:
        ok("log_size", f"hook-events.jsonl size: {mb:.1f} MB")
    elif mb < 20:
        warn("log_size", f"hook-events.jsonl size: {mb:.1f} MB — consider manual archival",
             "The log will continue to grow. Periodically archive or delete it "
             f"({log_file}). No automatic rotation is performed.")
    else:
        fail("log_size", f"hook-events.jsonl size: {mb:.1f} MB — archive recommended",
             f"The log is very large. Archive or delete it: {log_file}")

    # =================================================================
    # 6. Session health
    # =================================================================
    if isinstance(state, dict):
        session_id = state.get("session_id")
        if session_id:
            ok("session_id", f"Session active: {session_id}")
        else:
            warn("session_id", "No session_id — session not initialized",
                 "The next hook event (e.g. any tool call) will auto-create a session.")

        mcp_calls = state.get("mcp_calls")
        if isinstance(mcp_calls, dict):
            call_count = sum(1 for k, v in mcp_calls.items() if not k.startswith("_") and v)
            ok("mcp_calls", f"mcp_calls is a dict ({call_count} tools called this session)")
        else:
            fail("mcp_calls", f"mcp_calls is {type(mcp_calls).__name__}, not a dict",
                 "State corruption. Delete state.json to reset.")
    else:
        warn("session_id", "Cannot check session — state not loaded")
        warn("mcp_calls", "Cannot check mcp_calls — state not loaded")

    # =================================================================
    # 7. MCP server health
    # =================================================================
    mcp_json = repo / ".mcp.json"
    if mcp_json.is_file():
        try:
            mcp_config = json.loads(mcp_json.read_text(encoding="utf-8"))
            servers = mcp_config.get("mcpServers", {})
            if "local-llm" in servers:
                ok("mcp_json", ".mcp.json exists with local-llm server entry")
            else:
                warn("mcp_json", ".mcp.json exists but no local-llm server entry",
                     "Add local-llm entry to mcpServers in .mcp.json")
        except Exception as e:
            fail("mcp_json", f".mcp.json parse error: {e}")
    else:
        fail("mcp_json", f".mcp.json not found: {mcp_json}",
             "Create .mcp.json with local-llm MCP server configuration")

    try:
        import tools.local_llm_mcp_server as _  # noqa: F401
        ok("mcp_server_importable", "MCP server module importable")
    except Exception as e:
        fail("mcp_server_importable", f"Cannot import MCP server: {e}",
             "Check that tools/local_llm_mcp_server.py and its dependencies exist.")

    return results


def format_human(results: list[dict], repo_root: str, config_dir: str) -> str:
    lines = [
        "=== MCP Hook Doctor ===",
        f"Repo: {repo_root}",
        f"Config: {config_dir}",
        "",
    ]
    for r in results:
        if r.get("_early_return"):
            lines.append(f"[FAIL] {r['check']}: {r['message']}")
            break
        status = r["status"]
        tag = f"[{status}]".ljust(8)
        lines.append(f"{tag}{r['message']}")
        if r.get("detail") and status != "OK":
            lines.append(f"        Fix: {r['detail']}")

    ok_count = sum(1 for r in results if r["status"] == "OK")
    warn_count = sum(1 for r in results if r["status"] == "WARN")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    lines.append("")
    lines.append(f"Summary: {ok_count} OK, {warn_count} WARN, {fail_count} FAIL")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MCP Hook Doctor")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output machine-readable JSON")
    parser.add_argument("--repo-root", default=str(REPO_ROOT),
                        help=f"Path to the pipeline repo (default: {REPO_ROOT})")
    parser.add_argument("--config-dir", default=_default_config_dir(),
                        help="Path to hook config directory (state.json, hook-events.jsonl)")
    args = parser.parse_args()

    results = run_checks(args.repo_root, args.config_dir)

    if args.json_out:
        output = [r for r in results if not r.get("_early_return") or r["status"] == "FAIL"]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(format_human(results, args.repo_root, args.config_dir))

    # Exit 1 if any FAIL
    if any(r["status"] == "FAIL" for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
