# Project Status

## Current version

**MCP Phase 2 Complete** — `cc8ec0d`, branch `master`

## Purpose

Local multi-model LLM pipeline for Claude Code integration. Provides:
- MCP tools (8 source-non-mutating: review, summarize, test-plan, draft, debate, check)
- MCP hook gate system (commit gate, dangerous guard, release guard)
- Hook doctor diagnostic tool

## MCP Phase 2 Summary

| Phase | Commit | Feature | Tests |
|-------|--------|---------|-------|
| 2A | `46a32c7` | Stop hook session summary | 51 |
| 2B | `05f9df8` | PreToolUse dangerous command blocking | 51 |
| 2B.1 | `7fb9961` | False positive fix + review state sync fix | 51 |
| 2C | `4b27d37` | Release / tag / push guard | 75 |
| 2C.1 | `6f53418` | PowerShell here-string false positive fix | 87 |
| 2D | `cc8ec0d` | Hook doctor diagnostic tool | 97 |

### Guards (ordered by PreToolUse execution)

1. **Dangerous guard** — blocks destructive local commands (rm -rf, git reset --hard, del /s /q, etc.)
2. **Release guard** — blocks external publication (git push, git tag, npm publish, twine upload, release scripts)
3. **Commit gate** — requires prior MCP review before git commit

### Hook infrastructure

- 4 registered hook events: SessionStart, PreToolUse, PostToolUse, Stop
- State tracking: review fingerprint (repo/head/diff_hash), dirty flag, MCP call log
- Session isolation: per-session MCP tracking cleared on SessionStart
- Encoded-safe: UTF-8 git output, shlex fallback for PowerShell here-strings

### Diagnostic tool

```bash
python tools/claude_hooks/mcp_doctor.py          # human-readable
python tools/claude_hooks/mcp_doctor.py --json   # machine-readable
```

23 checks across 7 categories: environment, module health, hook installation, state health, log health, session health, MCP server health.

## Validation

| Check | Result |
|-------|--------|
| `python tools/claude_hooks/mcp_doctor.py` | 23 OK, 0 WARN, 0 FAIL |
| `python -m pytest tests/test_stop_hook.py -v` | 87 passed |
| `python -m pytest tests/test_mcp_doctor.py -v` | 10 passed |
| `python -m pytest tests/ -q` | 385 passed |
| Phase 2E dogfood (15 scenarios) | 15/15 passed |
| Unstaged + staged MCP review | both passed |

## Freeze Readiness (Phase 2)

**Verdict: MCP Phase 2 is ready to freeze.**

The hook gate system (commit gate, dangerous guard, release guard) has been through:
- 4 phases of development (2A→2D)
- 2 dogfood hardening rounds (2B.1, 2C.1)
- 97 dedicated hook/doctor tests
- 385 total tests
- 6 consecutive successful MCP-reviewed commits

### Known limitations

- Release guard does not detect all release script naming conventions (e.g. `bash deploy.sh` is not blocked)
- Doctor is read-only; no automated repair
- Hook-events.jsonl grows unbounded (currently ~6.5 MB)
- No per-user allowlist for guards (all blocks require manual terminal execution)
- PowerShell here-string fallback uses regex, not a full parser

### Phase 3 candidates (deferred)

- Allow-list for specific users/projects to skip certain guards
- Hook-events.jsonl rotation/compaction
- Pre-commit hook integration (block git commit at git level, not just Claude Code level)
- Guard audit dashboard
- Automated recovery (doctor --fix)
- Cross-repo review state federation

## Policy

MCP Phase 2 is frozen for feature development. Only bug fixes and hardening.
Phase 3 candidates are documented but not scheduled.
