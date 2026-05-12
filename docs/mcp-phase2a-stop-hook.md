# MCP Phase 2A: Stop Hook Session Summary

- **Date**: 2026-05-12 (updated 2A.1)
- **Repo module**: `tools/claude_hooks/mcp_gate.py` (source of truth)
- **User wrapper**: `~/.claude/hooks/mcp_gate.py` (thin import wrapper)
- **Type**: Stop hook — advisory only, never blocks

## Architecture

```
~/.claude/settings.json
  → Stop hook: python ~/.claude/hooks/mcp_gate.py
    → imports tools/claude_hooks/mcp_gate.py (repo module)
      → main(CONFIG_DIR)
```

The repo module (`tools/claude_hooks/mcp_gate.py`) contains all core logic.
The user-level hook is a thin 10-line wrapper that sets up the import path and config directory.

Tests import from the repo module directly — no dependency on `~/.claude/hooks/`.

## Session Boundary

SessionStart creates a fresh session with a new `session_id` and clears per-session MCP tracking (`mcp_calls`). Commit gate state (`diff_reviewed`, `reviewed_repo`, etc.) persists across sessions because review validity depends on repo state, not session lifetime.

**This prevents**: previous session's `local_check` from making the current session appear to have called MCP.

## Purpose

Give the controller a session-end reminder of:

1. Whether MCP tools were called (local_check, summarize, review_diff)
2. Whether any MCP call failed
3. Whether the working tree is dirty
4. Whether staged changes need re-review
5. Whether the commit gate requirements are met

It is a **feedback entry point**, not a new enforcement mechanism.

## What it does

| Check | Output |
|-------|--------|
| `local_check` not called | Reminder |
| No `local_review_diff` called | Reminder |
| No `local_summarize_file/tree` called | Reminder |
| MCP call failed (ok=false, timeout, error) | Warning |
| Working tree dirty without review | Reminder + file list |
| Files modified after last review | Reminder to re-review |
| Staged changes exist | Reminder to re-review staged |

## What it does NOT do

- Does NOT block session exit (always `continue: true`)
- Does NOT block git commit (PreToolUse commit gate handles that)
- Does NOT modify files
- Does NOT automatically run MCP tools
- Does NOT enforce routing policy
- Does NOT assign fixed roles to models

## Relationship to Commit Gate

The commit gate (PreToolUse on git commit) is **unchanged**. It still:

- Blocks commits without prior successful local_review_diff
- Validates repo/HEAD/diff_hash match
- Prevents cross-repo review leakage
- Prevents review-before-commit race conditions

The Stop hook is a **complement**, not a replacement.

## Testing

Tests live in `tests/test_stop_hook.py`. They import from `tools.claude_hooks.mcp_gate` — no user-level path dependency.

Run: `python -m pytest tests/test_stop_hook.py -v`

## Setup

1. The repo module `tools/claude_hooks/mcp_gate.py` is self-contained.
2. The user-level wrapper at `~/.claude/hooks/mcp_gate.py` imports it.
3. `~/.claude/settings.json` registers the wrapper as a Stop hook.
4. No other configuration needed.
