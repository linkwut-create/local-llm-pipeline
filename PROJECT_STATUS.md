# Project Status

## MCP Cost Discipline

| Phase | Status | Notes |
|-------|--------|-------|
| P0 | Done (`a499dba`) | Policy doc landed (`docs/MCP_COST_DISCIPLINE_PLAN.md`) |
| P1-A | Done (`b8f681e`) | Derivation-only helper `tools/profile_policy.py`. No JSON or runtime change. See plan §12. |
| P1-H.0 | Done (`6968406`) | Health telemetry isolation plan (`docs/MCP_HEALTH_TELEMETRY_ISOLATION_PLAN.md`). Blocks P2 until working-tree pollution from auto health-check is removed. |
| P1-H.1 | Done (`3ff9ea4`) | `tools/health_store.py` helper-only; no call sites switched. |
| P1-H.2 | Done (`f8b15c1`) | Writer/readers switched + `_health` cleaned from profiles JSON. Debate review passed (fast mode). |
| P1-H.3 | Done (`14b84b0`) | `cmd_health_report` and `auto_tune_recommendations` switched to runtime health store. |
| P1-H.4 | Done (`ca2211d`) | Docs closeout for P1-H. |
| P2-A | Done | Read-only audit of current call ledger coverage. Identifies the three highest-risk gaps (debate bypass, lost escalation context, missing commit-gate marker) and locks the P2-B field model. No code changes. |
| P2-B | In review | Call ledger schema/helper extension only. Adds top-level `profile` field and `KNOWN_EXTRA_KEYS` allowlist to `tools/call_ledger.py`. No MCP/debate/router/worker/hook call sites wired. |
| P2-C1 | Not started | MCP write-path integration: `mcp_tool_name`, `commit_gate`, `source` propagated from MCP server through worker into ledger extras. |
| P2-C2 | Not started | Escalation context: `_wrap_worker_call` injects `escalation_*` fields and `parent_request_id` into the escalated child invocation. Requires debate review (touches routing pivot). |
| P2-C3 | Not started | Debate ledger emission: `local_llm_debate.run_round` emits one ledger record per round with `debate_mode` / `debate_rounds` / `debate_round_index` / `debate_trigger`. Requires debate review (previously-silent path becomes writing). |
| P2-D | Not started | Reporting/CLI: `call_ledger_cli.py` gains `by-profile`, `by-mcp-tool`, `escalations`, `debates` subcommands over the new fields. |
| P2-E | Not started | Docs closeout for P2. |
| P3 | Not started | Auto-upgrade restriction (behavioral). |
| P4 | Not started | Worker pool dry-run. |
| P5 | Not started | V4-Flash local experimental profile. |

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

## Call Ledger

**Status**: v2-A complete (`5ddca41`, 2026-05-20). v2-B and v2-C deferred.

### v1 (baseline)

- Commit: `bf83f11 feat: add call ledger audit for local LLM invocations`
- Per-call JSONL ledger with `chars // 4` token estimation (`tokens_estimated: True`)
- CLI: `call_ledger_cli.py` (summary, group-by, filter-failures, recent)
- `LOCAL_LLM_COST_TABLE` env var for provider cost lookup
- Project/phase auto-detection via git

### v2-A (current)

- Commit: `5ddca41 feat: add real provider usage passthrough for call ledger`
- `ModelCallResult` dataclass — non-stream return type for `call_ollama` /
  `call_openai_compat` / `call_model` (non-stream branch)
- `normalize_usage(provider, data)` — maps Ollama (`prompt_eval_count` /
  `eval_count`) and OpenAI-compatible (`prompt_tokens` / `completion_tokens`)
  responses to a unified normalized usage shape
- DeepSeek `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` pass-through
  into `cached_tokens` / `cache_miss_tokens`
- Worker `_run_inner`:
  - Non-stream: extracts `result.content` and `result.usage` from
    `call_model_with_retry` return; forwards usage to ledger
  - Stream: unchanged — emits `usage=None`, ledger falls back to `chars//4`
- `tools/local_llm_debate.py` adapts: `call_model(...).content` (one-line change)
- `call_model_with_retry` returns `(ModelCallResult | None, error_info)`;
  on success the ledger records `tokens_estimated=False` when real provider
  usage is present; falls back to `chars//4` estimation when usage is None
- New file: `tools/model_call_result.py` (149 lines)
- New tests: `tests/test_model_call_result.py` (370 lines, 20 tests)

### Tests

| Suite | Result |
|-------|--------|
| Targeted (test_model_call_result + test_call_ledger + test_local_llm_v093) | 90 passed |
| Full suite | 763 passed |

### v2-B (deferred)

- Streaming usage passthrough (Ollama NDJSON final-frame `done` usage,
  OpenAI-compatible `stream_options={"include_usage": true}`)
- Separate plan: `docs/CALL_LEDGER_V2B_PLAN.md` (not yet written)

### v2-C (deferred)

- Cache-tier cost estimation: extend `LOCAL_LLM_COST_TABLE` with optional
  `cached_in_per_1k`, compute `(cached × cached_rate + miss × standard_rate) / 1000`
- Separate plan: `docs/CALL_LEDGER_V2C_PLAN.md` (not yet written)

### Explicitly NOT in scope

- SQLite-backed ledger
- Context Budget
- Codex / Claude / external direct API call recording
- Cross-project ledger aggregation tooling
