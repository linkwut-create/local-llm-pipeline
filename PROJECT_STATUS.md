# Project Status

## Final state

**MCP Goal Complete** — `c05ee7f`, branch `master`

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
| 3G | `c05ee7f` | Final goal completion and freeze readiness |
| 4 | `39c2da4` | Task-level auto-invocation (hooks spawn background workers) |
| 4.1 | `cf8d9f5` | Gemma 4 31B profile |

## Final Capability Matrix

### A. Safety / Guard Layer
- commit gate — enforces local review before git commit
- dangerous guard — blocks destructive commands (reset --hard, rm -rf, del /s, Remove-Item -Recurse -Force)
- release guard — blocks external publication (git push, git tag, npm publish, twine upload)
- PowerShell here-string false positive fix
- Unicode / GBK diff hash fix

### B. Diagnostic Layer
- mcp_doctor — 30 checks across 8 categories
- Human-readable and JSON output modes
- Custom --repo-root and --config-dir
- External git repo cwd fix
- State readability / 24 expected keys + field type validation
- Log readability / size warning (OK<5MB, WARN≥5MB) + content integrity
- Disk space monitoring
- Wrapper syntax validation + settings structure validation
- .mcp.json schema validation
- 6 auto-fixes (corrupt state, large log, missing .mcp.json, missing wrapper,
  missing hook registration, stale session)
- Doctor lite: rate-limited self-diagnostic at SessionStart (once per hour)

### C. Default Participation Layer
**Auto-invocation (Phase 2.0):**
- SessionStart: fire-and-forget `local_check` in background
- PostToolUse Read >300 lines: fire-and-forget `summarize-file` in background
- PostToolUse Edit (diff >50 lines): fire-and-forget `review-diff` in background
- Stop: collects and reports auto-worker results from `.local_llm_out/auto/`
- Dedup: 60s window (summarize), 120s window (review), max 10 workers/session
- Cleanup: auto-results older than 24h removed at Stop

**Detection & Recommendation (Phase 3E):**
- SessionStart: session_needs_local_check flag
- PostToolUse Read: large file (>300 lines) triggers needs_summarize
- PostToolUse Edit/Write/MultiEdit: records touched_files, sets needs_review
- Hook/gate files: triggers needs_debate
- Test files: triggers needs_test_plan
- diff_line_count: real-time calculation via git diff --numstat (>100 triggers debate)
- MCP success: clears corresponding needs_* flags; failure does not clear
- Stop hook: summarizes session recommendations, ACTIVE needs_* flags
- Session accumulator: session_recommendations, session_touched_files, session_large_reads
- PreToolUse advisory: warns when editing un-summarized large files (non-blocking)

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
| `git log --oneline -5` | Clean history, 18 MCP commits |
| `python tools/claude_hooks/mcp_doctor.py` | 30 OK, 0 WARN, 0 FAIL |
| `python tools/claude_hooks/mcp_doctor.py --json` | Valid JSON, all checks |
| `python -m pytest tests/test_stop_hook.py -v` | 131 passed |
| `python -m pytest tests/test_mcp_doctor.py -v` | 26 passed |
| `python -m pytest tests/test_mcp_auto_worker.py -v` | 35 passed |
| `python -m pytest tests/ -q` | **192+ passed** |
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
- Auto-push/tag/release
- Full automated agent behavior
- Replacement of human judgment
- Real-time UI popups (hook protocol limitation)
- Per-user guard allowlists
- Dashboard / analytics

### The participation model
The system now has two participation paths:

**Auto-invocation (Phase 2.0):** Hooks spawn fire-and-forget background workers:
1. SessionStart → `local_check` in background
2. PostToolUse Read >300 lines → `summarize-file` in background
3. PostToolUse Edit (diff >50 lines) → `review-diff` in background
4. Stop → collects and reports auto-worker results

**Manual participation (original):** User or controller invokes MCP tools directly.
Hooks detect participation gaps and remind at Stop / commit gate.

Background workers use `subprocess.Popen` (non-blocking), with dedup (60-120s window)
and per-session cap (max 10). Results land in `.local_llm_out/auto/`.

## Known Limitations

| Limitation | Impact |
|-----------|--------|
| PostToolUse cannot display live messages | Recommendations visible only at Stop |
| hook-events.jsonl grows unbounded | Manual archival needed (~8MB currently) |
| No per-user guard allowlist | All blocks require terminal override |
| local-translator-agent not yet connected | Path documented, not executed |
| Release scripts not exhaustively detected | Only common patterns covered |

## Future (Phase 4, not scheduled)

- Automated log rotation
- Guard allowlist per user/project
- Pre-commit git hook integration
- MCP usage analytics dashboard

## Freeze status

**MCP is frozen.** Only bugfixes and hardening permitted.
Development focus returns to local-translator-agent.
