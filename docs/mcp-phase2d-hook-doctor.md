# Phase 2D: Hook Doctor / Install / Recovery

## Goal

Provide a diagnostic tool for the MCP gate hook system. When hooks break
(wrong Python path, missing wrapper, corrupted state, encoding issues),
the doctor diagnoses what's wrong and suggests fixes.

## Quick Start

```bash
# Default: diagnose only
python tools/claude_hooks/mcp_doctor.py

# Diagnose + auto-repair
python tools/claude_hooks/mcp_doctor.py --fix

# Machine-readable output
python tools/claude_hooks/mcp_doctor.py --json

# Custom paths
python tools/claude_hooks/mcp_doctor.py --repo-root /path/to/repo --config-dir /path/to/config
```

30 checks across 8 categories. 6 auto-fixes: corrupt state archive,
large log rotation, .mcp.json template generation, hook wrapper creation,
hook registration snippet, stale session reset.

## Check Categories

| # | Category | Checks |
|---|----------|--------|
| 1 | Environment | Repo root exists, Python exe, platform encoding, git repo detected |
| 2 | Module health | mcp_gate.py exists, module importable, key functions present |
| 3 | Hook installation | Wrapper exists, settings.json valid, 4 hook events registered |
| 4 | State health | Config dir exists, state.json readable, expected keys, diff hash valid |
| 5 | Log health | hook-events.jsonl readable and writable |
| 6 | Session health | session_id exists, mcp_calls is dict, state not corrupted |
| 7 | MCP server | .mcp.json exists, server module importable |

Each check reports one of: **OK**, **WARN**, **FAIL**.
FAIL checks include a suggested fix.

## Common Errors and Fixes

### "Module not found"
The repo root is not on Python's path. The wrapper (`~/.claude/hooks/mcp_gate.py`)
must set `sys.path.insert(0, REPO_ROOT)` before importing.

### "state.json not readable"
- Check file permissions in `%LOCALAPPDATA%\mcp-gate\`
- If the file is corrupt, delete it — the hook will recreate it with defaults

### "hook_SessionStart not registered"
- Open `~/.claude/settings.json`
- Ensure `hooks.SessionStart` (and PreToolUse, PostToolUse, Stop) have matcher entries
- Each should point to the wrapper script

### "Diff hash returned None"
- Usually caused by UnicodeDecodeError on Windows with system encoding != UTF-8
- The hook's `run_git()` uses `encoding="utf-8", errors="replace"` as a workaround
- If the doctor reports this as FAIL, check the hook-events log for tracebacks

### "settings.json parse error"
- The file is not valid JSON. Common causes: trailing commas, unescaped backslashes
- Validate with `python -m json.tool ~/.claude/settings.json`

## Windows / PowerShell / Git Bash Notes

- The hook wrapper uses Unix-style paths (`/c/Users/...`) when invoked from Git Bash
- The config dir is at `%LOCALAPPDATA%\mcp-gate\` (typically `C:\Users\<user>\AppData\Local\mcp-gate\`)
- Python encoding defaults to the system locale (e.g., GBK on Chinese Windows);
  the hook and doctor both use `encoding="utf-8"` to avoid decode errors
- PowerShell here-strings (`@'...'@`) confuse `shlex.split()`; the hook uses a
  regex fallback (`_GIT_SUBCMD_FALLBACK_RE`) since Phase 2C.1

## Recovery Checklist

If the hook system stops working:

1. Run `python tools/claude_hooks/mcp_doctor.py` to identify failures
2. Fix each FAIL in order (environment first, then module, then state)
3. Verify with `python tools/claude_hooks/mcp_doctor.py --json`
4. Restart Claude Code to pick up hook changes
5. Run a test tool call (e.g., `local_check`) to verify hooks fire

## Auto-Fix (`--fix`)

The doctor can repair 6 common issues automatically:

1. **Corrupt state.json** — archives to `state.json.corrupt.<timestamp>`, hook recreates fresh
2. **Oversized hook-events.jsonl (>5MB)** — archives with timestamp
3. **Missing .mcp.json** — generates template with local-llm server entry
4. **Missing hook wrapper** — creates `~/.claude/hooks/mcp_gate.py`
5. **Missing hook registration** — prints JSON snippet for settings.json
6. **Stale session state** — resets session_id, clears mcp_calls and auto-worker tracking

The doctor does NOT auto-edit `~/.claude/settings.json` (Fix 5 prints a snippet).
This is intentional: hook configuration is part of the user's trusted environment.

## Related Docs

- [MCP Gate Architecture](claude-code-mcp-gate.md)
- [Phase 2A Stop Hook](mcp-phase2a-stop-hook.md)
- [Phase 2B Dangerous Command Guard](mcp-phase2b-dangerous-command-guard.md)
- [MCP Task Policy](mcp-task-policy.md)
