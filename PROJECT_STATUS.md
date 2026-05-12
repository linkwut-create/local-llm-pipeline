# Project Status

## Current version

**MCP Goal Completion** — `master` branch

The MCP system now meets its original goal: Claude Code development is protected
by local model participation, review, reminders, layered routing, safety gates,
and diagnostic recovery — without requiring the user to repeatedly remind
Claude to use MCP.

## Completion Sprint Summary

| Phase | Feature | Tests |
|-------|---------|-------|
| 2A | Stop hook session summary | 51 |
| 2B | Dangerous command guard | 51 |
| 2B.1 | False positive fix + state sync | 51 |
| 2C | Release / tag / push guard | 75 |
| 2C.1 | PowerShell here-string fix | 87 |
| 2D | Hook doctor diagnostic tool | 97 |
| 2E | Freeze readiness docs | 97 |
| 2F | Post-freeze hardening | 100 |
| 3A | Default MCP participation reminders | 105 |
| 3B | Risk/profile routing | 111 |
| 3C | Cross-project setup | 111 |
| 3D | Final completion audit | 117 |

### Guards (PreToolUse ordering)

1. **Dangerous guard** — destructive local commands
2. **Release guard** — external publication actions
3. **Commit gate** — requires prior MCP review

### Participation (PostToolUse + Stop)

- Touched file tracking (dirty_since_review, touched_files)
- Risk classification (low/medium/high based on diff size and file paths)
- MCP action recommendations (review, debate, test_plan, summarize)
- Session-start hook event initialization

### Routing

- Small diff → local_review_diff
- Large diff (>100 lines) → local_debate_review_diff
- Hook/gate files → local_debate_review_diff (high risk)
- Test files → local_generate_test_plan
- Docs-only → local_summarize_file
- Never empty — always recommends at least review

### Diagnostic

```bash
python tools/claude_hooks/mcp_doctor.py
```
24 checks across 7 categories. Supports --json, --repo-root, --config-dir.

### Cross-project

See [MCP Cross-Project Setup](docs/mcp-cross-project-setup.md).
Ready for local-translator-agent development.

## Validation

| Check | Result |
|-------|--------|
| `python tools/claude_hooks/mcp_doctor.py` | 23 OK, 1 WARN, 0 FAIL |
| `python -m pytest tests/test_stop_hook.py -v` | 105 passed |
| `python -m pytest tests/test_mcp_doctor.py -v` | 12 passed |
| `python -m pytest tests/ -q` | 405 passed |
| `git diff --check` | clean |
| MCP review (unstaged + staged) | both passed |

## Goal Completion Verdict

**MCP original goal: reached.**

The system now provides:
- Default local model participation reminders
- Default review enforcement before commit
- Default dangerous/release command blocking
- Default risk routing recommendations
- Default diagnostic and recovery tooling
- Default cross-project readiness

The user no longer needs to remind Claude to use MCP.
MCP participates, reviews, warns, blocks, and diagnoses by default.

### Known limitations

- No automatic MCP tool invocation (by design — only reminders and gates)
- Hook-events.jsonl grows unbounded (doctor warns at 5MB)
- Release guard doesn't cover all script naming conventions
- No per-user allowlist for guards

### Future candidates (Phase 4, not scheduled)

- Automated log rotation
- Guard allowlist per user/project
- Pre-commit git hook integration
- Doctor auto-repair (--fix)
- MCP usage analytics dashboard

## Freeze status

**MCP is frozen.** Only bugfixes and hardening permitted.
Feature development on the MCP toolchain itself is complete.
Development focus returns to local-translator-agent.
