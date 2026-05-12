# MCP Phase 2B: Dangerous Command Guard

- **Date**: 2026-05-12
- **Module**: `tools/claude_hooks/mcp_gate.py` (PreToolUse)
- **Type**: PreToolUse block — irreversible commands are stopped

## Purpose

Block destructive shell commands that could cause data loss or corrupt the repository. This is a **safety net**, not a developer replacement.

## Blocked Commands

| Category | Pattern | Example |
|----------|---------|---------|
| Git reset | `git reset ... --hard` | `git reset --hard HEAD~1` |
| Git clean | `git clean -fd` / `-xdf` | `git clean -xdf` |
| Git force push | `git push --force` / `-f` | `git push -f origin main` |
| Unix rm | `rm -rf` | `rm -rf build/` |
| Windows del | `del /s /q` | `del /s /q *.tmp` |
| Windows rmdir | `rmdir /s` | `rmdir /s build` |
| PowerShell | `Remove-Item -Recurse -Force` | `Remove-Item -Recurse -Force build/` |
| PowerShell alias | `rm -r -fo`, `ri -r -fo` | `rm -r -fo build/` |

## NOT Blocked (Safe)

- `git status`, `git diff`, `git log`, `git branch`
- `pytest`, `python -m pytest`, `npm test`
- `echo`, `ls`, `dir`, `cat`, `type`
- Comments or echo strings mentioning dangerous commands (e.g., `echo "rm -rf is dangerous"`)
- Non-Bash/PowerShell tools (Edit, Write, Read, etc.)

## NOT Blocked (Phase 2C Candidates)

These are deferred to Phase 2C:
- `git tag`, `git push --tags`
- `npm publish`, `twine upload`
- Release scripts
- `git push` (without --force)

## Design

The guard runs at the start of PreToolUse, before the commit gate check. If a command matches, it's blocked immediately with a clear reason. The user can re-run the command manually in a terminal if they intentionally need it.

### Why PreToolUse and not PostToolUse

PostToolUse would be too late — the command already executed. PreToolUse blocks before execution.

### Why block and not just warn

Destructive commands are irreversible. A warning that can be ignored provides no real protection.

## Relationship to Other Guards

| Guard | When | Action |
|-------|------|--------|
| Dangerous command (Phase 2B) | PreToolUse | Block |
| Commit gate (Phase 2A) | PreToolUse | Block without review |
| Stop hook summary (Phase 2A) | Stop | Warn only |

The dangerous command guard runs **first**. A dangerous git commit takes priority over the commit gate review check.

## Testing

Tests in `tests/test_stop_hook.py`:
- 8 tests for blocked dangerous commands
- 7 tests for safe commands that pass through
- 2 tests for guard ordering (dangerous before commit gate)

Run: `python -m pytest tests/test_stop_hook.py -v -k "Dangerous or Safe or TestDangerousCommandDoesNot"`
