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
| P2-B | Done (`285279c`) | Call ledger schema/helper extension only. Top-level `profile` field and `KNOWN_EXTRA_KEYS` allowlist added to `tools/call_ledger.py`. No call sites wired. |
| P2-C1.0 | Done (`3abe46e`) | Worker ledger env plumbing only. Worker reads `LOCAL_LLM_LEDGER_EXTRA`, filters via `KNOWN_EXTRA_KEYS`, folds into ledger `extra`; `_emit_ledger` populates the P2-B top-level `profile` slot from `config.profile`. No MCP server / hook / router / debate wiring. |
| P2-C1.1 | Done (`cc1bcbf`) | MCP server per-tool stamps via `LOCAL_LLM_LEDGER_EXTRA`. `_build_ledger_extra_env` helper; `extra_env` parameter on `run_subprocess` / `run_subprocess_streaming` / `_wrap_worker_call`. Every worker-backed MCP tool stamps the child env with the real `mcp_tool_name` + `source="manual-mcp"`; `local_review_diff` stamps `commit_gate`; `local_parallel_review` stamps each parallel worker. `local_check` and `local_debate_review_diff` left unstamped by design. |
| P2-C1.2 | Done (`3fff081`) | Auto-hook env replacement. `tools/claude_hooks/mcp_auto_worker.py` gains a self-contained `_build_ledger_extra_env` helper (decoupled from MCP server) and `spawn_review_diff` drops the broken `--commit_gate true` CLI passthrough, stamping the subprocess env with `{mcp_tool_name=local_review_diff, commit_gate=true, source=auto-hook}` instead. Fire-and-forget behaviour preserved; no worker / MCP server / router / debate changes. |
| P2-C2.0 | Done (`034bedb`) | Schema allowlist extension: add `escalation_trigger` to `KNOWN_EXTRA_KEYS` in `tools/call_ledger.py`; update tests. No worker / MCP server / router / debate / hook behavior changes. |
| P2-C2.1 | Done (`a2a5547`) | Escalation context: `_wrap_worker_call` injects `escalation_*` fields and `parent_request_id` into the escalated child invocation via `_merge_escalation_ledger_extra_env` + `_derive_escalation_trigger` helpers. |
| P2-C3.1 | Done (`9bfbb6d`) | Debate round ledger emission. |
| P2-D1 | Done (`afca643`) | Reporting/CLI: `call_ledger_cli.py` adds `by-profile`, `by-mcp-tool`, `escalations`, `debates` subcommands over P2 cost-discipline fields. Includes `group_by_extra`, `filter_escalations`, `filter_debates` library helpers. Old records (missing `extra`/`profile`) bucket into `<none>`. |
| P2-E | Done (`e8a5315`) | Docs closeout for P2-A → P2-D1. `PROJECT_STATUS.md`, `CHANGELOG.md`, `README.md`, and `docs/MCP_COST_DISCIPLINE_PLAN.md` §13 updated to reflect the completed cost-discipline ledger chain. No runtime / test / VERSION changes. |
| P3-A | Done (audit, no code) | Read-only audit of auto-escalation runtime. Found four escalation-shaped paths (A starting-profile routing, B volume-based auto-debate, C `_check_quality_escalation` quality signals, D hook-layer advisory) and three spec/runtime mismatches in `docs/MCP_COST_DISCIPLINE_PLAN.md` §4 (`confidence=medium` vs `low`, `≥ 3` vs `> 3`, the never-implemented `escalation_reason` enum). Decision: WARN — docs reconciliation required before P3-B. |
| P3-A.1 | Done (`3dde552`) | Docs-only reconciliation of `docs/MCP_COST_DISCIPLINE_PLAN.md` §1.1, §4 (rewritten as §4.1–§4.5), §10 P3 row, and §13.5 to match runtime at HEAD `e8a5315`. Narrowed P3 scope: P3 modifies Path C only; `structural_risk` runtime trigger and `user_requested` MCP parameter both deferred outside P3. No runtime / test / VERSION changes. |
| P3-B | Done (`8fa0904`) | Env knob helper + constants in `tools/local_llm_mcp_server.py`: `_ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE`, `_ENV_AUTO_ESCALATE_ON_UNCERTAIN`, `_parse_env_flag(name, default=False)`. Plumbing only — no behavioral wiring. New `tests/test_p3_env_knobs.py` (49 tests) covered parser semantics and runtime-invariance. |
| P3-C1 | Done (`8b85a88`) | First behavioral flip: `confidence=="low"` auto-escalation default OFF; legacy restorable via `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true`. `_derive_escalation_trigger` gated in lock-step. `uncertain_points > 3` and `timeout` untouched. |
| P3-C2 | Done (`6669bae`) | Second behavioral flip: `len(uncertain_points) > 3` auto-escalation default OFF in `_check_quality_escalation`; legacy restorable via `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN=true`. `_derive_escalation_trigger` gated in lock-step. With both knobs OFF, dual-signal payload (`confidence=="low"` AND `uncertain_points > 3`) yields `result=None` and `trigger="unknown"`. **P3 core objective complete: neither quality signal auto-triggers strong-model invocation by default.** `timeout` downgrade unchanged; Path A / Path B / Path D unchanged; ledger schema and CLI unchanged. `tests/test_p3_env_knobs.py` 72 → 104 tests. No `call_ledger.py` / `call_ledger_cli.py` / `local_llm_profiles.json` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes. |
| P3-C2.1 | Done (this entry) | Docs/status closeout. `PROJECT_STATUS.md` flip of P3-C2 from In review → Done. No code / test / `VERSION` / tag changes. VERSION remains `0.9.7`, HEAD carries no tag, no release cut. |
| P3-C3 | Not started (optional) | Stamp `review_necessity="user-forced"` when MCP call carries explicit `profile` override. Additive only. Decision deferred: P3 core objective is already met without P3-C3; it remains optional, not blocking P3-D / P3-E. |
| P3-D | Done (this entry) | Policy-doc final alignment with the narrowed P3 runtime. `CLAUDE.md` Escalation Rules table and `docs/mcp-task-policy.md` §Escalation Rules rewritten: `confidence=="low"` and `uncertain_points > 3` no longer auto-escalate by default; legacy behavior is opt-in via `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE` / `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN` (truthy `true`/`1`/`yes`/`on`, case-insensitive); `timeout` clarified as a downgrade (not strong-model escalation); explicit non-claims that `structural_risk` runtime trigger, `escalate=true` / `user_requested` MCP parameter, and a strict `escalation_reason` enum exist. Ledger `escalation_trigger` value space (`timeout` / `low_confidence` / `uncertain_points` / `unknown`) reaffirmed. No runtime / test / `tools/**` / profile / ledger / `VERSION` / tag changes. P3-C3 remains optional/deferred. |
| P3-E | Done (this entry) | Docs closeout for the P3 cost-discipline chain. **P3 chain closed** (P3-A → P3-A.1 → P3-B → P3-C1 → P3-C2 → P3-C2.1 → P3-D → P3-E). P3 core objective met: `confidence=="low"` and `len(uncertain_points) > 3` no longer auto-escalate by default; both legacy behaviors restorable via `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE` / `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN` (truthy `true`/`1`/`yes`/`on`, case-insensitive). `timeout` downgrade remains unconditional (a *downgrade*, not strong-model escalation). Path A / Path B / Path D unchanged; ledger schema and CLI surface unchanged; `escalation_trigger` value space (`timeout` / `low_confidence` / `uncertain_points` / `unknown`) unchanged; `escalation_reason` remains free-form string. P3-C3 (`review_necessity="user-forced"` ledger stamp) explicitly **skipped / deferred** — optional, additive, not required for the P3 core objective; may be revived as a separately approved phase. No `structural_risk` runtime trigger and no `escalate=true` / `user_requested` MCP parameter were introduced. **Next runway: P4 (worker pool dry-run)** or, if explicitly approved, P3-C3. No `tools/**` / `tests/**` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `tools/local_llm_profiles.json` / `VERSION` / tag changes. VERSION remains `0.9.7`. HEAD carries no tag. No release. |
| P4-A | Done (this entry) | Read-only audit + boundary lock-in for the worker pool dry-run. Adds `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` recording: (a) hard boundary — P4 is a probe-only diagnostic, not a scheduler / daemon / multi-host dispatcher; (b) current architecture findings — `tools/local_llm_check.py:28` already probes three llama.cpp MTP endpoints on zero12, `call_local_check` (`tools/local_llm_mcp_server.py:1926`) shells out and returns stdout/stderr only, profiles carry no per-profile host, `worker_id` / `host` are allowlisted in `KNOWN_EXTRA_KEYS` but never stamped today; (c) explicit non-goals (no routing change, no ledger schema change, no MCP tool-count change, no background process, no profile mutation); (d) smallest viable P4-B slice — CLI-opt-in `--probe-workers --json` flag in `tools/local_llm_check.py`, default path byte-identical, no MCP / router / ledger / profile touches; (e) risk list and stop conditions. **P4-B is NOT authorized by P4-A** and requires separate approval. No `tools/**` / `tests/**` / `tools/local_llm_profiles.json` / `tools/call_ledger*.py` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes. |
| P4-B | Done (this entry) | Smallest viable implementation slice per `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` §5. Adds `--probe-workers` and `--json` CLI flags + a `build_probe_report()` helper + a `PROBE_REPORT_SCHEMA_VERSION = 1` constant to `tools/local_llm_check.py`. When both flags are passed, emits a single JSON probe report to stdout and exits (no human-readable workflow); when `--probe-workers` is passed alone, appends a human-readable probe section after the existing health check; `--json` alone is a no-op for probing (default flow runs). Probe reuses existing endpoint sources only — resolved Ollama URL, `OPENAI_COMPAT_BASE`, `_MTP_ENDPOINTS` — and returns 5 configured workers in the current environment. `routing_changed` and `ledger_stamped` are baked in as literal `False` in both the helper and the JSON payload. 32 new tests in `tests/test_p4_worker_pool_dry_run.py` cover shape, invariants, configured-workers derivation, reachable/unreachable bucketing, probe-on-network-error survival, missing-`requests` graceful handling, CLI flag combinations (4 cases), and "no side effects on router/profile/ledger" source-level assertions. Regression: `tests/test_mcp_server.py` 68/68, `tests/test_router_profiles.py` + `tests/test_call_ledger.py` 130/130. No changes to `tools/local_llm_mcp_server.py`, `tools/local_llm_router.py`, `tools/call_ledger.py`, `tools/call_ledger_cli.py`, `tools/local_llm_profiles.json`, `tools/local_llm_worker.py`, `tools/health_store.py`, `CLAUDE.md`, `docs/mcp-task-policy.md`, `docs/MCP_COST_DISCIPLINE_PLAN.md`, `VERSION`, or tags. MCP `call_local_check` contract unchanged (still returns stdout/stderr; the structured probe surface is CLI-only). |
| P4-C | Skipped / deferred (optional) | Configurable worker list (env var / JSON). Not required for the P4 core objective ("probe-only diagnostic, no scheduling"). May be revived only under a separately approved plan that re-cites `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` §2 / §4 / §6 / §8. |
| P4-D | Done (this entry) | Docs/status closeout for the P4 chain. **P4 chain closed** (P4-A → P4-B → P4-D; P4-C explicitly skipped/deferred). P4 core objective met: `tools/local_llm_check.py --probe-workers --json` emits a structured diagnostic report (`PROBE_REPORT_SCHEMA_VERSION = 1`) reusing existing endpoint sources only (resolved Ollama URL, `OPENAI_COMPAT_BASE`, `_MTP_ENDPOINTS`); default invocation behavior preserved; MCP `call_local_check` contract unchanged; `routing_changed` / `ledger_stamped` baked in as literal `False`. No `tools/local_llm_mcp_server.py` / `tools/local_llm_router.py` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `tools/local_llm_profiles.json` / `tools/local_llm_worker.py` / `tools/health_store.py` / `tools/claude_hooks/` changes were introduced anywhere in the P4 chain. P4-C remains optional and may be revived only under a separately approved plan that re-cites the boundary contract. **Next runway: P5 (V4-Flash local experimental profile)** with a P5-A read-only audit first (mirrors the P3-A / P4-A pattern). No `tools/**` / `tests/**` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `docs/MCP_COST_DISCIPLINE_PLAN.md` / `VERSION` / tag changes in P4-D. VERSION remains `0.9.7`. HEAD carries no tag. No release. |
| P5-A | Done (this entry) | Read-only audit + boundary lock-in for the V4-Flash local experimental profile. Adds `docs/P5_V4_FLASH_EXPERIMENTAL_PROFILE_PLAN.md` recording: (a) hard boundary — P5 is a single profile-entry change, **not** a routing/escalation/worker-pool change; (b) current architecture findings — `tools/validate_configs.py:22` and `tools/profile_policy.py:33` disagree on whether `"experimental"` is a valid `risk_level`, profile schema requires `model`/`risk_level`/`use_for`, policy derivation in `_derive_experimental` / `_derive_auto_allowed` / `_derive_default_review_necessity` already covers experimental profiles correctly, router accepts `--profile` override, all 8 worker-backed MCP tools already accept a `profile` parameter, worker only knows `"ollama"` / `"openai-compatible"` providers (no `"tongyi"`); (c) explicit non-goals (no routing change, no new MCP tool/parameter, no new provider, no `tasks.json` default change, no P3 escalation wiring, no P4 probe wiring, no ledger schema change, no worker pool, no model provisioning); (d) smallest viable P5-B slice — one profile entry in `tools/local_llm_profiles.json` (`v4_flash_local_experimental`), one-line `validate_configs.py` allowlist alignment (Option A) **or** name-based experimental detection without `validate_configs.py` change (Option B), focused tests in a new `tests/test_p5_v4_flash_experimental.py`, plus a stale-doc reconciliation of `docs/MCP_COST_DISCIPLINE_PLAN.md:367`'s `provider=tongyi` reference; (e) 11-item test plan, 9-row risk list, 8-item stop conditions. **P5-B is NOT authorized by P5-A** and requires separate approval. No `tools/**` / `tests/**` / `tools/local_llm_profiles.json` / `tools/validate_configs.py` / `tools/local_llm_router.py` / `tools/local_llm_mcp_server.py` / `tools/local_llm_worker.py` / `tools/local_llm_check.py` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `tools/local_llm_tasks.json` / `tools/profile_policy.py` / `tools/health_store.py` / `tools/claude_hooks/` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes in P5-A. VERSION remains `0.9.7`. HEAD carries no tag. No release. |
| P5-B | Done (this entry) | Smallest viable implementation slice per `docs/P5_V4_FLASH_EXPERIMENTAL_PROFILE_PLAN.md` §5. Adds the `v4_flash_local_experimental` profile entry (`risk_level="experimental"`, manual-only) to `tools/local_llm_profiles.json`, adds `"experimental"` to `tools/validate_configs.py::VALID_RISK_LEVELS` (Option A, aligning with `profile_policy.py` which already accepted it), updates `tests/test_profile_policy.py::test_no_profile_marked_experimental_yet` → `test_exactly_one_experimental_profile`, creates `tests/test_p5_v4_flash_experimental.py` (16 tests covering profile existence, required fields, manual-only constraints, validate_configs acceptance, policy derivation, no-task-default, router non-auto-selection, explicit-override routing, MCP server v4-flash-reference absence, MCP tool-count=9, P4 probe invariants, ledger schema compatibility, and no-provider=tongyi), and reconciles the stale `provider=tongyi` reference in `docs/MCP_COST_DISCIPLINE_PLAN.md:367`. No `tools/local_llm_router.py` / `tools/local_llm_mcp_server.py` / `tools/local_llm_worker.py` / `tools/local_llm_check.py` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `tools/local_llm_tasks.json` / `tools/profile_policy.py` / `tools/health_store.py` / `tools/claude_hooks/` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes. VERSION remains `0.9.7`; HEAD carries no tag; no release. |
| P5-C | Not started, optional | `_env` wiring, model warmup helper, or per-profile `_provider` hint — **only if** real operational usage reveals a need. Each requires a separate plan re-citing the P5-A boundary contract. |
| P5-D | Done (this entry) | Docs/status closeout for the P5 chain. **P5 chain closed** (P5-A → P5-B → P5-D; P5-C explicitly deferred / not authorized). P5 core objective met: `v4_flash_local_experimental` profile exists in `tools/local_llm_profiles.json` (`risk_level="experimental"`, `_local_only=true`, manual invocation only); `"experimental"` accepted by `tools/validate_configs.py::VALID_RISK_LEVELS` (now aligned with `profile_policy.py` which already accepted it); policy derivation confirmed (experimental=true, auto_allowed=false, requires_escalation_reason=true, debate_allowed=true, default_review_necessity="recommended", commit_gate_allowed=false, local_only=true); no task default points to it; router does not auto-select it; MCP tool count remains 9; P4 probe invariants unchanged; `provider=tongyi` stale reference removed from `docs/MCP_COST_DISCIPLINE_PLAN.md`; 16 focused tests in `tests/test_p5_v4_flash_experimental.py`. P5-C (`_env` wiring, model warmup, provider hint) remains **deferred / not authorized** — these would require a separately approved plan re-citing the P5-A boundary contract (§2/§4/§6). No `tools/**` / `tests/**` / `tools/local_llm_router.py` / `tools/local_llm_mcp_server.py` / `tools/local_llm_worker.py` / `tools/local_llm_check.py` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `tools/local_llm_tasks.json` / `tools/profile_policy.py` / `tools/health_store.py` / `tools/claude_hooks/` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes in P5-D. VERSION remains `0.9.7`. HEAD carries no tag. No release. |
| P6-A | Done (this entry) | Read-only audit of runtime reliability / observability across 17 files in 4 layers (worker, MCP server, hook/gate, observability). Identifies 6 CRITICAL (C1–C6), 6 HIGH (H1–H6), 8 MEDIUM (M1–M8), and 5 LOW (L1–L5) findings. Key themes: silent failure is the default behavior across ledger/gate-state/health-store; error classification is brittle and colliding (substring heuristics, no origin disambiguation); subprocess timeout is systematically misreported as `worker_failed_no_output` in all 6 `_wrap_worker_call`-routed tools; state persistence is best-effort and unauditable; audit observability has three independent silent-failure paths. Selects P6-B1 as the smallest next implementation slice: fix timeout propagation in `_wrap_worker_call` (C1), connect timeout to health-store penalty, clear stale `last_timeout` after later success (H2), plus focused regression tests. Explicitly defers C2–C6, H1–H6 (except H2), and all MEDIUM items. No `tools/**` / `tests/**` / `VERSION` / tag changes. |
| P6-A.1 | Done (this entry) | Docs-only boundary lock-in. Adds `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md` recording the full P6-A audit: hard boundary (§2), full findings table (§4), cross-component themes (§5), P6-B1 smallest viable slice (§6), test plan (§7), risk list (§8), task delegation (§9), and stop conditions (§10). P6-B1 scope narrowed to timeout observability fix only (C1 + H2): (1) subprocess timeout must produce `error_type="timeout"` not `worker_failed_no_output`; (2) timeout must reach health-store penalty; (3) later success must clear stale `last_timeout`; (4) focused regression tests. Explicitly defers C2 (streaming double-serialization), C3/C4 (gate state persistence), C5/C6 (auto-worker/audit events), H1/H3/H4/H5/H6, all MEDIUM items. **P6-B1 is NOT authorized by P6-A.1** and requires separate approval. No `tools/**` / `tests/**` / `VERSION` / tag changes. |
| P6-B1 | Done (`4fcd83a`) | Timeout observability fix. `_wrap_worker_call` (both streaming and non-streaming paths) now detects subprocess timeout before `coerce_failure_response` and returns `error_type="timeout"` instead of `worker_failed_no_output`. New `_extract_profile_from_cmd` helper extracts profile name from worker command line for health-store attribution. `tools/health_store.py`: `last_timeout` is now cleared on subsequent success (was `setdefault`-locked, never cleared). Non-timeout failure preserves `last_timeout`. 15 focused tests in `tests/test_p6_timeout_observability.py`. Regression: 354 passed across 7 suites. No `VERSION` / tag / router / worker / ledger / hooks changes. |
| P6-B1.1 | Done (`a5637ee`) | Test hygiene cleanup. Removes the fragile working-tree-diff boundary test (`test_forbidden_files_not_in_diff`) and the broad `_P6_B1_ALLOWED` exemption from `tests/test_p5_v4_flash_experimental.py`. The 15 static P5 invariant tests (profile existence, policy derivation, router non-auto-select, MCP tool count, P4 probe invariants, no provider=tongyi) are retained. Boundary enforcement moves to per-phase docs/status audits. |
| P6-B1.2 | Done (this entry) | Docs/status closeout. Records P6-B1 at `4fcd83a` and P6-B1.1 at `a5637ee`. Remaining P6 findings (C2–C6, H3–H6, M1–M8) explicitly deferred. P6-B2 (call_ledger observability: corrupt JSONL line count/reporting) noted as recommended next slice but **not authorized**. No `tools/**` / `tests/**` / `VERSION` / tag changes. |
| P6-B2 | Not started | Recommended: call_ledger observability — corrupt JSONL line count/reporting (M1/M2 from P6-A). Not authorized. |

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

## P3-C2 Handoff / Next Window Notes

### Clean baseline at handoff

- HEAD = `6669bae` (P3-C2 source commit) + this docs/status closeout
- `git describe --tags --dirty` = `v0.9.7-24-g6669bae` at the source commit
- VERSION = `0.9.7` (unchanged across the entire P3 chain)
- No tag at HEAD
- No release cut
- Working tree clean after this docs commit

### P3 progress summary

| Phase | Commit | Outcome |
|-------|--------|---------|
| P3-A | (audit, no code) | Identified four escalation-shaped paths (A/B/C/D) and three spec/runtime mismatches in `docs/MCP_COST_DISCIPLINE_PLAN.md` §4. |
| P3-A.1 | `3dde552` | Docs-only reconciliation. Narrowed P3 scope: P3 modifies Path C only. `structural_risk` and `user_requested` deferred outside P3. |
| P3-B | `8fa0904` | Plumbing only: `_ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE`, `_ENV_AUTO_ESCALATE_ON_UNCERTAIN`, `_parse_env_flag(name, default=False)`. No behavioral wiring. |
| P3-C1 | `8b85a88` | First behavioral flip: `confidence=="low"` default OFF; legacy restorable via `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true`. `_derive_escalation_trigger` gated in lock-step. |
| P3-C2 | `6669bae` | Second behavioral flip: `uncertain_points > 3` default OFF; legacy restorable via `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN=true`. `_derive_escalation_trigger` gated in lock-step. |

### P3 core objective — complete

- `confidence=="low"` no longer auto-triggers strong-model escalation by default.
- `len(uncertain_points) > 3` no longer auto-triggers strong-model escalation by default.
- Both legacy behaviors are restorable via their respective env knobs (truthy values: `true` / `1` / `yes` / `on`, case-insensitive).
- `timeout` downgrade remains unconditional (it moves to a lighter model, not a heavier one — no cost inflation).
- Path A (`_resolve_starting_profile` content-pattern routing), Path B (volume-based auto-debate in `call_review_diff`), Path D (hook-layer `classify_diff_risk` advisory) all unchanged.
- Call ledger schema and CLI surface unchanged. `escalation_trigger` value space unchanged (`timeout` / `low_confidence` / `uncertain_points` / `unknown`); only the *frequency* of `low_confidence` and `uncertain_points` labels changes.
- Test coverage: `tests/test_p3_env_knobs.py` 49 → 72 → 104 tests across P3-B → P3-C1 → P3-C2.

### Not started

| Item | Status | Description |
|------|--------|-------------|
| P3-C3 | Optional, not started | Stamp `review_necessity="user-forced"` when an MCP call carries an explicit `profile` override. Additive only — does not affect default escalation behavior. |
| P3-D | Not started | CLAUDE.md + `docs/mcp-task-policy.md` final alignment with the narrowed runtime. |
| P3-E | Not started | Docs closeout for the full P3 chain. |

### Recommended next-window paths

**A. Continue with optional feature work:** Evaluate whether P3-C3 (`review_necessity="user-forced"`) is worth shipping. It is additive (ledger-only, no behavioral change) and would close the loop on "user-forced model overrides should be visible in the ledger." If yes, run P3-C3 → P3-D → P3-E. If the value is unclear, skip P3-C3.

**B. Close out P3 without P3-C3:** P3 core objective is met. Skip P3-C3 and run P3-D (policy doc alignment) → P3-E (chain closeout). This is the lower-risk path if you want to free the runway for P4 (worker pool dry-run) or other work.

### Explicit prohibitions for the next window

Do **not** do any of the following without an explicit new plan:

- Introduce a `structural_risk` runtime trigger (deferred outside P3 in P3-A.1).
- Add an `escalate=true` / `user_requested` MCP parameter (deferred outside P3 in P3-A.1).
- Modify `tools/call_ledger.py` or `tools/call_ledger_cli.py` (ledger schema / CLI are frozen for the P3 chain).
- Bump `VERSION` away from `0.9.7`.
- Create a tag at HEAD.
- Cut a release.

### Resolution (recorded at P3-E)

Path **B** of the two recommended next-window paths above was taken:
**P3-C3 skipped**, **P3-D** completed in commit `a2e6daf` (policy-doc
alignment in `CLAUDE.md` and `docs/mcp-task-policy.md`), and **P3-E**
completed in this commit (chain closeout). The "Not started" rows for
P3-D and P3-E in the table above are preserved as a historical
snapshot at P3-C2 handoff; the current state is reflected in the main
MCP Cost Discipline table at the top of this file. None of the
explicit prohibitions above were violated: `VERSION` stayed at
`0.9.7`, no tag was created, no release was cut, ledger code/CLI/
schema were not touched, and no `structural_risk` runtime trigger or
`escalate=true` / `user_requested` MCP parameter was added. P3-C3
remains optional and may be revived only under a separately approved
plan.
