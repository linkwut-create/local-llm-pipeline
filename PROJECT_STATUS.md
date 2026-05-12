# Project Status

## Final state

**MCP Goal Complete** — `3a2fdaf`, branch `master`

The MCP system has reached its project-defined completion target:
a default-participation development infrastructure where local models
participate, review, warn, block, recommend, diagnose, and can migrate
across projects — without the user repeatedly reminding Claude to use MCP.

## Complete Commit Chain

| Phase | Commit | Feature |
|-------|--------|---------|
| 2A | `46a32c7` | Stop hook session summary |
| 2B | `05f9df8` | PreToolUse dangerous command blocking |
| 2B.1 | `7fb9961` | False positive fix + review state sync fix |
| 2C | `4b27d37` | Release / tag / push guard |
| 2C.1 | `6f53418` | PowerShell here-string false positive fix |
| 2D | `cc8ec0d` | Hook doctor diagnostic tool |
| 2E | `3aa3dc1` | Freeze readiness docs |
| 2F | `29b74ec` | Post-freeze hardening (state fix, log diagnostics) |
| 3A | `99f12f7` | Default MCP participation reminders |
| 3B | `99f12f7` | Minimal risk/profile routing |
| 3C | `99f12f7` | Cross-project setup readiness |
| 3D | `99f12f7` | Final completion audit |
| 3E | `89eaed3` | Real-time default participation hooks |
| 3E.1 | `5927796` | Participation detection hardening |
| 3F | `3a2fdaf` | Cross-project dry-run verification |

## Final Capability Matrix

### A. Safety / Guard Layer
- commit gate — enforces local review before git commit
- dangerous guard — blocks destructive commands (reset --hard, rm -rf, del /s, Remove-Item -Recurse -Force)
- release guard — blocks external publication (git push, git tag, npm publish, twine upload)
- PowerShell here-string false positive fix
- Unicode / GBK diff hash fix

### B. Diagnostic Layer
- mcp_doctor — 24 checks across 7 categories
- Human-readable and JSON output modes
- Custom --repo-root and --config-dir
- External git repo cwd fix
- State readability / 21 expected keys
- Log readability / size warning (OK<5MB, WARN≥5MB)
- MCP server / config checks

### C. Default Participation Layer
- SessionStart: session_needs_local_check flag
- PostToolUse Read: large file (>300 lines) triggers needs_summarize
- PostToolUse Edit/Write/MultiEdit: records touched_files, sets needs_review
- Hook/gate files: triggers needs_debate
- Test files: triggers needs_test_plan
- diff_line_count: real-time calculation via git diff --numstat (>100 triggers debate)
- MCP success: clears corresponding needs_* flags; failure does not clear
- Stop hook: summarizes session recommendations, ACTIVE needs_* flags
- Session accumulator: session_recommendations, session_touched_files, session_large_reads

### D. Routing Layer
- classify_diff_risk(): low/medium/high based on diff size and file paths
- recommend_mcp_action(): always includes at least local_review_diff
- Debate for high-risk/hook files, test_plan for test files, summarize for docs
- Commit gate: lists pending MCP recommendations when blocking

### E. Cross-project Layer
- External repo doctor (verified via dry-run)
- Custom --repo-root / --config-dir
- Windows path normalization (backslash → forward slash)
- Verified with non-local-llm-pipeline repo
- local-translator-agent preflight path documented

## Validation

| Check | Result |
|-------|--------|
| `git status --short` | `_handoff_local_state.txt` only |
| `git log --oneline -12` | Clean history, 16 MCP commits |
| `python tools/claude_hooks/mcp_doctor.py` | 23 OK, 1 WARN, 0 FAIL |
| `python tools/claude_hooks/mcp_doctor.py --json` | Valid JSON, all checks |
| `python -m pytest tests/test_stop_hook.py -v` | 131 passed |
| `python -m pytest tests/test_mcp_doctor.py -v` | 12 passed |
| `python -m pytest tests/test_cross_project_dry_run.py -v` | 11 passed |
| `python -m pytest tests/ -q` | **442 passed** |
| `git diff --check` | clean |

## Goal Judgment

**MCP has reached the project-defined completion target.**

It provides: default state tracking, default recommendation emission,
enforced commit review, dangerous/release command blocking,
risk-based action routing, diagnostic tooling, and cross-project
verification — all without the user repeatedly reminding Claude to use MCP.

### Included
- Default detection, marking, and recommendation
- Default commit gate enforcement
- Default safety guard enforcement
- Default diagnostic and recovery tooling
- Session-level accumulation and Stop-hook summarization
- Cross-project readiness

### Explicitly NOT included (by design)
- Auto-invocation of MCP tools inside hooks (prevents recursion)
- Auto-push/tag/release
- Full automated agent behavior
- Replacement of human judgment
- Auto-fix (doctor --fix)
- Real-time UI popups (hook protocol limitation)
- Per-user guard allowlists
- Dashboard / analytics

### The participation model
The system does not auto-call MCP tools. Instead:
1. **Detect** — SessionStart, PostToolUse Read, PostToolUse Edit/Write
2. **Mark** — needs_* flags in session state
3. **Recommend** — classified routing suggestions
4. **Remind** — Stop hook summary, commit gate pending list
5. **Enforce** — commit gate, dangerous guard, release guard

This is the intended design: hooks cannot safely auto-invoke MCP tools
without risking recursion and latency. The user sees the recommendations
and decides when to invoke.

## Known Limitations

| Limitation | Impact |
|-----------|--------|
| Hooks do not auto-call MCP tools | User must act on recommendations |
| PostToolUse cannot display live messages | Recommendations visible only at Stop |
| hook-events.jsonl grows unbounded | Manual archival needed (~8MB currently) |
| Doctor is read-only (no --fix) | Recovery requires manual steps |
| No per-user guard allowlist | All blocks require terminal override |
| True automatic model routing not implemented | User selects MCP tool manually |
| local-translator-agent not yet connected | Path documented, not executed |
| Release scripts not exhaustively detected | Only common patterns covered |

## Future (Phase 4, not scheduled)

- Automated log rotation
- Guard allowlist per user/project
- Pre-commit git hook integration
- Doctor auto-repair (--fix)
- MCP usage analytics dashboard
- True auto model routing

## Freeze status

**MCP is frozen.** Only bugfixes and hardening permitted.
Development focus returns to local-translator-agent.
