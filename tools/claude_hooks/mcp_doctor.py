#!/usr/bin/env python3
"""MCP Hook Doctor — diagnostic and auto-recovery tool for the MCP gate hook system.

Usage:
    python tools/claude_hooks/mcp_doctor.py              # diagnose only
    python tools/claude_hooks/mcp_doctor.py --fix        # diagnose + auto-repair
    python tools/claude_hooks/mcp_doctor.py --json       # machine-readable output
    python tools/claude_hooks/mcp_doctor.py --repo-root /path/to/repo
    python tools/claude_hooks/mcp_doctor.py --config-dir /path/to/config
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
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
        git_root = run_git(["rev-parse", "--show-toplevel"], cwd=repo_root)
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

    # Wrapper content validation
    if wrapper.is_file():
        wrapper_text = wrapper.read_text(encoding="utf-8", errors="replace")
        try:
            compile(wrapper_text, str(wrapper), "exec")
            ok("wrapper_syntax", "Hook wrapper has valid Python syntax")
        except SyntaxError as e:
            fail("wrapper_syntax", f"Hook wrapper has syntax error: {e}",
                 f"Fix the wrapper file at {wrapper}")
        if "sys.path.insert" not in wrapper_text:
            warn("wrapper_path_config",
                 "Wrapper lacks sys.path.insert — may not find repo module",
                 "Ensure wrapper imports from tools.claude_hooks.mcp_gate")

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

    # settings.json structure validation
    if isinstance(settings, dict):
        hooks_config = settings.get("hooks", {})
        struct_issues = []
        for hook_name in expected_hooks:
            entries = hooks_config.get(hook_name, [])
            if isinstance(entries, list):
                for i, entry in enumerate(entries):
                    if isinstance(entry, str):
                        pass  # string format is valid
                    elif isinstance(entry, dict):
                        # Support both flat {command: ...} and nested
                        # {hooks: [{command: ...}]} formats
                        if "command" in entry:
                            pass  # flat format
                        elif "hooks" in entry:
                            nested = entry["hooks"]
                            if isinstance(nested, list):
                                for j, nh in enumerate(nested):
                                    if isinstance(nh, dict) and "command" not in nh:
                                        struct_issues.append(
                                            f"hooks.{hook_name}[{i}].hooks[{j}] "
                                            f"missing 'command'")
                            else:
                                struct_issues.append(
                                    f"hooks.{hook_name}[{i}].hooks is not a list")
                        else:
                            struct_issues.append(
                                f"hooks.{hook_name}[{i}] missing 'command'")
                    else:
                        struct_issues.append(
                            f"hooks.{hook_name}[{i}] is "
                            f"{type(entry).__name__}, expected dict or str")
        if struct_issues:
            warn("settings_structure",
                 f"settings.json has {len(struct_issues)} structure issue(s)",
                 "; ".join(struct_issues[:3]))
        else:
            ok("settings_structure", "settings.json hook entries well-formed")

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

    # State field type validation (schema check)
    if isinstance(state, dict):
        _FIELD_TYPES = {
            "diff_reviewed": bool, "dirty_since_review": bool,
            "needs_summarize": list, "needs_review": bool,
            "needs_debate": bool, "needs_test_plan": bool,
            "session_recommendations": list,
            "session_large_reads": list,
            "mcp_calls": dict,
            "session_id": (str, type(None)),
            "reviewed_at": (str, type(None)),
            "_auto_worker_count": (int, type(None)),
            "_auto_spawned": (dict, type(None)),
        }
        type_mismatches = []
        for key, expected_type in _FIELD_TYPES.items():
            val = state.get(key)
            if val is not None and not isinstance(val, expected_type):
                type_mismatches.append(
                    f"{key}: got {type(val).__name__}, "
                    f"expected {getattr(expected_type, '__name__', str(expected_type))}"
                )
        if type_mismatches:
            warn("state_field_types",
                 f"State field type mismatches: {len(type_mismatches)} issues",
                 "; ".join(type_mismatches[:5]))
        else:
            ok("state_field_types", "All tracked state fields have valid types")

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
        warn("log_size", f"hook-events.jsonl size: {mb:.1f} MB — archive strongly recommended",
             "The log is very large but this is a maintenance issue, not a hook failure. "
             f"Archive or delete it: {log_file}")

    # hook-events.jsonl content integrity
    if log_file.is_file() and log_file.stat().st_size > 0:
        line_count = 0
        bad_lines = 0
        sample = ""
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_count += 1
                    if line.strip():
                        try:
                            json.loads(line.strip())
                        except json.JSONDecodeError:
                            bad_lines += 1
                            if bad_lines <= 3:
                                sample = line[:200]
            if bad_lines == 0:
                ok("log_content_integrity",
                   f"hook-events.jsonl: {line_count} valid JSON lines")
            else:
                warn("log_content_integrity",
                     f"hook-events.jsonl: {bad_lines}/{line_count} lines are "
                     f"invalid JSON",
                     f"Sample corrupted line: {sample}")
        except Exception as e:
            fail("log_content_integrity",
                 f"Cannot scan hook-events.jsonl: {e}")

    # Disk space check
    try:
        check_path = config if config.exists() else Path.home()
        usage = shutil.disk_usage(str(check_path))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 0.5:
            fail("disk_space", f"Only {free_gb:.1f} GB free — dangerously low",
                 "Free up disk space immediately. Hook state/log writes may fail.")
        elif free_gb < 2:
            warn("disk_space", f"Only {free_gb:.1f} GB free — consider cleanup",
                 "Free up disk space to prevent hook failures.")
        else:
            ok("disk_space", f"{free_gb:.1f} GB free disk space")
    except Exception as e:
        warn("disk_space", f"Could not check disk space: {e}")

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

    # .mcp.json content validation
    if mcp_json.is_file():
        try:
            mcp_config = json.loads(mcp_json.read_text(encoding="utf-8"))
            servers = mcp_config.get("mcpServers", {})
            schema_issues = []
            for srv_name, cfg in servers.items():
                if not isinstance(cfg, dict):
                    schema_issues.append(
                        f"Server '{srv_name}' config is not a dict")
                    continue
                if "command" not in cfg:
                    schema_issues.append(
                        f"Server '{srv_name}' missing 'command' field")
            if schema_issues:
                warn("mcp_json_schema",
                     f".mcp.json has {len(schema_issues)} schema issue(s)",
                     "; ".join(schema_issues[:3]))
            else:
                ok("mcp_json_schema",
                   ".mcp.json has valid server configurations")
        except Exception as e:
            fail("mcp_json_schema",
                 f".mcp.json content validation failed: {e}")

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
    parser.add_argument("--fix", action="store_true", dest="fix_mode",
                        help="Apply automatic fixes for failed/warned checks")
    args = parser.parse_args()

    results = run_checks(args.repo_root, args.config_dir)

    if args.fix_mode:
        fixes = run_fixes(results, args.repo_root, args.config_dir)
        if fixes:
            print("=== Fixes Applied ===")
            for f in fixes:
                print(f"  [FIX] {f}")
        else:
            print("=== No fixes needed ===")
        # Re-run checks after fixes to verify
        print("\n=== Post-Fix Verification ===")
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


def run_fixes(results: list[dict], repo_root: str, config_dir: str) -> list[str]:
    """Apply automatic fixes for FAIL and WARN items. Returns list of fix descriptions."""
    fixes_applied = []
    repo = Path(repo_root)
    config = Path(config_dir)

    status = {r["check"]: r["status"] for r in results}

    # --- Fix 1: corrupt state.json → delete ---
    if status.get("state_readable") == "FAIL" or status.get("state_keys") == "FAIL":
        sf = config / "state.json"
        if sf.exists():
            archive_path = config / f"state.json.corrupt.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
            try:
                shutil.move(str(sf), str(archive_path))
                fixes_applied.append(f"state.json: archived corrupt state to {archive_path}. Hook will recreate on next run.")
            except Exception as e:
                fixes_applied.append(f"state.json: FAILED to archive ({e}). Delete manually: {sf}")

    # --- Fix 2: large hook-events.jsonl → archive ---
    if status.get("log_size") == "WARN":
        lf = config / "hook-events.jsonl"
        if lf.is_file() and lf.stat().st_size > 5 * 1024 * 1024:
            archive_dir = repo / ".mcp_audit" / "archive"
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / f"hook-events-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.jsonl"
                shutil.move(str(lf), str(dest))
                fixes_applied.append(f"hook-events.jsonl: archived ({lf.stat().st_size / 1048576:.1f}MB) to {dest}")
            except Exception as e:
                fixes_applied.append(f"hook-events.jsonl: FAILED to archive ({e}). Archive manually: {lf}")

    # --- Fix 3: missing .mcp.json → generate template ---
    if status.get("mcp_json") == "FAIL":
        mcp_json = repo / ".mcp.json"
        if not mcp_json.exists():
            template = {
                "mcpServers": {
                    "local-llm": {
                        "command": "python",
                        "args": ["tools/local_llm_mcp_server.py"],
                        "cwd": str(repo),
                    }
                }
            }
            try:
                mcp_json.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8")
                fixes_applied.append(f".mcp.json: created template at {mcp_json}")
            except Exception as e:
                fixes_applied.append(f".mcp.json: FAILED to create ({e}). Create manually: {mcp_json}")

    # --- Fix 4: missing hook wrapper → generate ---
    if status.get("wrapper_exists") == "FAIL":
        wrapper = Path.home() / ".claude" / "hooks" / "mcp_gate.py"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper_content = (
            '"""Thin wrapper that imports the repo-resident mcp_gate module."""\n'
            'import sys\n'
            f'sys.path.insert(0, r"{repo_root}")\n'
            'from tools.claude_hooks.mcp_gate import main\n'
            '\n'
            'if __name__ == "__main__":\n'
            f'    main(config_dir=r"{config_dir}")\n'
        )
        try:
            wrapper.write_text(wrapper_content, encoding="utf-8")
            fixes_applied.append(f"hook wrapper: created {wrapper}")
        except Exception as e:
            fixes_applied.append(f"hook wrapper: FAILED to create ({e}). Create manually: {wrapper}")

    # --- Fix 5: missing hook registration → print snippet ---
    hook_failures = [k for k in status if k.startswith("hook_") and status[k] == "FAIL"]
    if hook_failures:
        wrapper_path = Path.home() / ".claude" / "hooks" / "mcp_gate.py"
        hook_snippet = {
            "hooks": {
                "SessionStart": [{
                    "matcher": "",
                    "command": f'"{sys.executable}" "{wrapper_path}"'
                }],
                "PreToolUse": [{
                    "matcher": "",
                    "command": f'"{sys.executable}" "{wrapper_path}"'
                }],
                "PostToolUse": [{
                    "matcher": "",
                    "command": f'"{sys.executable}" "{wrapper_path}"'
                }],
                "Stop": [{
                    "matcher": "",
                    "command": f'"{sys.executable}" "{wrapper_path}"'
                }],
            }
        }
        snippet_str = json.dumps(hook_snippet, indent=2, ensure_ascii=False)
        fixes_applied.append(
            f"hook registration: Add the following to ~/.claude/settings.json "
            f"under 'hooks':\n{snippet_str}"
        )

    # --- Fix 6: stale session state → reset ---
    if status.get("session_id") == "WARN":
        sf = config / "state.json"
        if sf.exists():
            try:
                state = json.loads(sf.read_text(encoding="utf-8"))
                if isinstance(state, dict) and state.get("session_started_at"):
                    import uuid
                    state["session_id"] = uuid.uuid4().hex[:12]
                    state["session_started_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    state["mcp_calls"] = {"_last_mcp_failed": False}
                    state["_auto_spawned"] = {}
                    state["_auto_worker_count"] = 0
                    sf.write_text(
                        json.dumps(state, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    fixes_applied.append(
                        "Stale session state reset (cleared session, "
                        "preserved persistent fields)"
                    )
            except Exception as e:
                fixes_applied.append(
                    f"Stale session repair FAILED: {e}"
                )

    return fixes_applied


if __name__ == "__main__":
    main()
