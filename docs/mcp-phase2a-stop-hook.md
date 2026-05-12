# MCP Phase 2A: Stop Hook Session Summary

- **Date**: 2026-05-12
- **Hook file**: `~/.claude/hooks/mcp_gate.py`
- **Type**: Stop hook — advisory only, never blocks

## Purpose

Give the controller a session-end reminder of:

1. Whether MCP tools were called (local_check, summarize, review_diff)
2. Whether any MCP call failed
3. Whether the working tree is dirty
4. Whether staged changes need re-review
5. Whether the commit gate requirements are met

It is a **feedback entry point**, not a new enforcement mechanism.

## Design

### What it does

| Check | Output |
|-------|--------|
| `local_check` not called | Reminder |
| No `local_review_diff` called | Reminder |
| MCP call failed (ok=false, timeout, error) | Warning |
| Working tree dirty without review | Reminder + file list |
| Files modified after last review | Reminder to re-review |
| Staged changes exist | Reminder to re-review staged |

### What it does NOT do

- Does NOT block session exit (always `continue: true`)
- Does NOT block git commit (PreToolUse commit gate handles that)
- Does NOT modify files
- Does NOT automatically run MCP tools
- Does NOT enforce any routing policy
- Does NOT assign fixed roles to models

### Why Stop hook and not PreToolUse on Edit/Write

- Edit/Write PreToolUse would fire on every keystroke-level edit → too noisy
- Stop hook fires once per task/response cycle → right granularity
- Reminding after the fact teaches the controller to form better habits
- Graduated approach: reveal gaps before enforcing them

## State Tracking

The hook tracks MCP usage in the state file (`%LOCALAPPDATA%/mcp-gate/state.json`):

```json
{
  "mcp_calls": {
    "mcp__local-llm__local_check": true,
    "mcp__local-llm__local_review_diff": true,
    "_last_mcp_ts": "2026-05-12T...",
    "_last_mcp_failed": false
  }
}
```

This is written in PostToolUse for all MCP tool calls. The Stop hook reads it to produce the summary.

## Relationship to Commit Gate

The commit gate (PreToolUse on git commit) is **unchanged**. It still:

- Blocks commits without prior successful local_review_diff
- Validates repo/HEAD/diff_hash match
- Prevents cross-repo review leakage
- Prevents review-before-commit race conditions

The Stop hook is a **complement**, not a replacement. It provides situational awareness before the commit gate fires.

## Verification

1. Empty session (no edits, no MCP) → Stop hook shows "no local_check, no review_diff" reminders
2. Session with edits and review → Stop hook shows no dirty reminders
3. Session with failed MCP → Stop hook shows warning
4. Session with staged diff and no staged review → Stop hook shows staged review reminder
5. git commit still blocked without review → PreToolUse commit gate unchanged
