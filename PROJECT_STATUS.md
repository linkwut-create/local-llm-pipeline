# Project Status

## Public Release (Post-v0.11.0, GH-chain)

| Phase | Status | Notes |
|-------|--------|-------|
| GH-D | Done (no code) | Repository visibility changed to **Public**. Anonymous browser access + anonymous release zip download verified. |
| GH-E | Done (no code) | GitHub Release publication prep: local/remote git state verified, source zip located (628,754 bytes), .mcp.json audited, forbidden artifact scan clean. Manual browser publication. |
| GH-F | Done (no code) | Post-release verification: Release published (not draft, not pre-release), SHA256 three-way match, downloaded zip VERSION=0.11.0, forbidden artifact scan clean. **PASS.** |
| GH-G | Done (this commit) | Docs/status closeout for public v0.11.0 release. RELEASE_NOTES.md release gate updated. Advisory-only status unchanged. Next: J-A Productivity Advisor Planning Audit. |

## Codex Adaptation (Post-v0.11.0, I-chain)

| Phase | Status | Notes |
|-------|--------|-------|
| I-A | Done (`429ed29`) | Read-only audit: AGENTS.md missing task_bootstrap, outdated MCP count, no safety boundaries. `.codex/` config clean. |
| I-B | Done (`429ed29`) | AGENTS.md rewritten as primary Codex instruction file. `.codex/local-llm-worker.md` updated with task_bootstrap, MCP 9→11, `py -3` commands. Cross-reference in CLAUDE.md. No code/test/VERSION/tag changes. |
| I-C | Done | Smoke test passed: AGENTS.md instruction coverage 6/6, task_bootstrap exit 0 with 3/3 summaries, 82/82 tests passed, git diff --check clean, working tree clean. |
| I-D | Done (`9d91c7b`) | Docs/status closeout. Codex adaptation functionally closed. Remaining gaps require real Codex environment: MCP invocation, PowerShell quoting, `.codex/config.toml` `python`→`py -3`. |

## Backend Governance (Post-v0.11.0, J-chain, 2026-05-26)

| Phase | Status | Notes |
|-------|--------|-------|
| J-C1a | Done (`28b96c2`) | Fix debate error capture (`_format_call_error()`) and ledger accounting (success True/False/unknown, UNKN column). |
| J-C1 | Done (audit, no code) | llama.cpp backend manager planning audit. All 4 endpoints offline. Ollama-first strategy confirmed. |
| J-C2 | Done (audit, no code) | Hybrid backend planning audit. 23/24 profiles have models in Ollama. Recommended profile backend classification before ledger/router changes. |
| J-C3 | Done (`3b2b660`) | Add explicit `_backend_class` to 23 profiles (12 ollama, 5 ollama_heavy_manual, 2 ollama_mtp_pending, 2 unavailable, 1 llamacpp_unconfigured, 1 placeholder). Metadata-only. Tests validate class presence, allowed values, and safety invariants. |
| J-C3.5 | Done (`1ad1571`) | Register draft-commit-message in prompt registry. Fixes `validate_configs.py` failure from J-B. |
| J-C4 | Done (`a052ed5`) | Add `backend` and `failure_type` fields to call ledger. `resolve_backend()` + `classify_failure_type()`. New `by-backend` CLI command. 16 targeted + 254 regression tests passed. |
| J-C5 | Done (`558804c`) | **Router enforces `_backend_class` for eligibility.** `ollama` and `ollama_mtp_pending` remain auto-eligible. `ollama_heavy_manual` requires explicit `--profile` or task risk ≥ medium-high. `llamacpp_unconfigured`, `unavailable`, and `placeholder` are not auto-eligible. Explicit `--profile` override remains allowed. Also fixes J-B `draft-commit-message` missing from `code_worker.use_for`. `validate_configs.py` PASS, 296 tests passed. **Backend governance main chain J-C3 → J-C4 → J-C5 now closed.** |
| J-C5.5 | Done (this commit) | Docs/status closeout. No runtime/test/VERSION/tag changes. Next: J-D draft-pr-summary productivity advisor. |

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
| P6-B2-A | Done (`ec74898`) | Call ledger read diagnostics signal source. Adds `read_records_with_diagnostics()` to `tools/call_ledger.py` returning `{records, total_lines, empty_lines, malformed_json_lines, non_dict_lines, skipped_lines, errors}` with errors bounded to 20. `read_records()` unchanged (backward compatible). 8 focused tests in `tests/test_call_ledger.py`. Regression: 217 passed. No `VERSION` / CLI / worker / MCP server / router changes. |
| P6-B2-B | Done (`63693c7`) | CLI operator-visible reporting. Adds `--diagnostics` flag to `tools/call_ledger_cli.py`. `cmd_summary` uses `read_records_with_diagnostics()` when flag is set; JSON output wraps summary + diagnostics in combined object with `_diagnostics` sub-key. Default output unchanged without `--diagnostics`. 5 CLI tests. Regression: 222 passed. No `call_ledger.py` / `VERSION` / worker / MCP server / router changes. |
| P6-B2-C | Not started / deferred | Write-failure propagation: `record_call()` return value currently ignored by worker (`_emit_ledger`) and debate (`_emit_debate_round_ledger`). Requires separate design for caller-side propagation strategy. Not authorized. |
| P6-B2-D | Done (this entry) | Docs/status closeout. Records P6-B2-A at `ec74898` and P6-B2-B at `63693c7`. P6-B2-C explicitly deferred. Remaining deferred P6 items: C2–C6, H3–H6, M3–M8, P5-C. No `tools/**` / `tests/**` / `VERSION` / tag changes. |
| P6-B3 | Done (audit, no code) | Read-only audit of `tools/local_llm_check.py` runtime reliability at baseline `3680464` (`docs: close out P6 call ledger read diagnostics`). Identified unbounded `subprocess.check_output(["ollama", "list"])` in `run_ollama_list()` (M8 in `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md`): if the ollama CLI blocks, the health check itself hangs indefinitely. Recommended smallest viable slice as **P6-B3-A: timeout-only fix on `run_ollama_list()`**. Deferred from P6-B3 scope: MTP endpoint hardcoding / false-positive risk (H5 / "B3-B"), `all_ok` semantics, P4 probe contract changes, `recommend_profiles()` silent failure cleanup. **P6-B3-A is the only slice authorized by P6-B3.** No `tools/**` / `tests/**` / `VERSION` / tag changes. |
| P6-B3-A | Done (`bfe537e`) | Bound `ollama list` subprocess in local check. `tools/local_llm_check.py::run_ollama_list()` signature changes from `()` to `(timeout: int = 30)`; replaces `subprocess.check_output(["ollama", "list"], …)` with `subprocess.run([...], capture_output=True, text=True, timeout=timeout)`. `TimeoutExpired` returns a failed `CheckResult("ollama_list", False, "ollama list timed out after 30s")`; `FileNotFoundError` returns `"ollama binary not found"`; nonzero exit surfaces stderr in the detail message; the broad `except Exception` fallback is preserved. Sole caller (`local_llm_check.py:447` via `build_probe_report()`) invokes with no argument — default 30s applies, fully backward compatible. 4 new tests in `tests/test_check.py` (ok, timeout, missing binary, nonzero exit), bringing the file to 10 passed; P4/P5/P6/call_ledger regression 180 passed. `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md` M8 row marked CLOSED. No MTP endpoint config (no `LOCAL_LLM_MTP_ENDPOINTS`, no `--skip-mtp`), no `all_ok` change, no P4 probe contract change, no `recommend_profiles()` change, no `tools/local_llm_worker.py` / `tools/local_llm_mcp_server.py` / `tools/local_llm_router.py` / `tools/call_ledger*.py` / `tools/health_store.py` / `tools/local_llm_profiles.json` / `tools/local_llm_tasks.json` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes. |
| P6-B3-A.1 | Done (this entry) | Docs/status closeout. Records P6-B3 audit baseline `3680464`, P6-B3-A landing at `bfe537e`, and explicit deferral of P6-B3-B (MTP endpoint hardcoding / false-positive risk — no `LOCAL_LLM_MTP_ENDPOINTS`, no `--skip-mtp`, no host auto-detection; requires separate design before implementation). Reaffirms deferred items from prior P6 phases: P6-B2-C (write-failure propagation), C2 (streaming double-serialization), C3/C4 (gate state persistence), C5/C6 (auto-worker/audit observability), H1/H3/H4/H6 (M8-style local_check timeout now fixed), M3–M7, P5-C. No `tools/**` / `tests/**` / `VERSION` / tag / release changes. VERSION remains `0.9.7`; HEAD carries no tag; no release. |
| P6-B3-B | Not started / deferred / not authorized | MTP endpoint hardcoding / false-positive risk. `tools/local_llm_check.py::_MTP_ENDPOINTS` is a fixed list pinned to one host; unreachable endpoints inflate failure counts for environments that do not run MTP. Out of scope for any current slice. Requires a separate design covering: configuration surface (`LOCAL_LLM_MTP_ENDPOINTS` env var? `--skip-mtp` CLI flag? host auto-detection?), interaction with `build_probe_report()` schema, `all_ok` semantics, and the boundary against turning a reliability fix into a configuration-system expansion. **Not authorized.** |
| P6-C | Done (`9d8af1d`) | Docs/status phase closeout for the P6 runtime reliability / observability chain. **P6 chain closed** (P6-A → P6-A.1 → P6-B1 → P6-B1.1 → P6-B1.2 → P6-B2-A → P6-B2-B → P6-B2-D → P6-B3 → P6-B3-A → P6-B3-A.1 → P6-C). P6 phase result: (a) subprocess timeout in `_wrap_worker_call` (both streaming and non-streaming) now produces `error_type="timeout"` instead of `worker_failed_no_output` and reaches the health-store penalty path (C1 + H2); (b) `health_store.last_timeout` is now cleared on subsequent success (was `setdefault`-locked); (c) `tools/call_ledger.py::read_records_with_diagnostics()` exposes corrupt/skipped JSONL line counts (M1/M2); (d) `tools/call_ledger_cli.py --diagnostics` makes the read diagnostics operator-visible; (e) `tools/local_llm_check.py::run_ollama_list()` is bounded by a 30s subprocess timeout (M8) — health check can no longer wedge on a stalled ollama CLI. **Explicitly frozen / deferred at P6-C:** P6-B2-C (write-failure propagation), P6-B3-B (MTP endpoint hardcoding / configuration surface), C2 (streaming double-serialization), C3/C4 (gate state persistence), C5/C6 (auto-worker / audit event observability), H1 (`run_git()` diagnostic context), H3/H4 (auto-worker collect/results TOCTOU), H6 (`classify_error` heuristic brittleness), M3 (ledger size/rotation), M4 (`mcp_doctor` auto-worker diagnostics), M5/M6 (`mcp_gate` MCP-format fragility), M7 (`call_ledger::estimate_cost_cny` LAN-proxy classification), and P5-C (`_env` wiring / warmup / per-profile provider hint). H5 (MTP endpoint hardcoding) is the same item as P6-B3-B. **No release at P6-C**: VERSION remains `0.9.7`; HEAD carries no tag; no release; no zip. **Possible future directions, none authorized by P6-C:** P7 read-only audit of remaining hook/gate observability; P6-B2-C design-only planning; P6-B3-B design-only planning; release prep — each requires a separately approved plan. No `tools/**` / `tests/**` / `VERSION` / `CLAUDE.md` / `docs/mcp-task-policy.md` / tag / release changes in P6-C. |
| P7-A | Done (audit, no code) | Read-only grouped audit of remaining P6 deferred items at baseline `9d8af1d`. Inspected 8 source files (`tools/claude_hooks/{mcp_gate,mcp_auto_worker,mcp_doctor}.py`, `tools/local_llm_mcp_server.py`, `tools/local_llm_check.py`, `tools/call_ledger.py`, `tools/local_llm_worker.py`, `tools/local_llm_debate.py`). Confirmed: C3/C4 `load_state`/`save_state` swallow exceptions silently; C5/C6 4 spawn paths in `mcp_auto_worker.py` swallow exceptions silently; M4 doctor never inspects `.local_llm_out/auto/`; M5/M6 `_extract_read_info`/`review_tool_succeeded` silently return defaults on unknown shapes; C2 streaming double-serializes JSON at `local_llm_mcp_server.py:1417`; H6 `classify_error` substring matching is order-sensitive; P6-B2-C 2 callsites discard `record_call()` return AND wrap in `except: pass`; M3 zero rotation in call_ledger; M7 LAN proxies on `193.168.2.2` classified as free; P6-B3-B/H5 `_MTP_ENDPOINTS` hardcoded but **MTP results are display-only (NOT folded into `all_ok`)**. Grouping verdict: Group A (C3+C4+C5+C6) and M4 are diagnostics-friendly with no behavior change → safe to bundle; Group B (M5+M6) is bundle-able as warning-only without widening parsing; Group C (C2 streaming) and Group D (H6 classify_error) require contract/order changes → isolate; Group E (P6-B2-C), Group F (M3 rotation), Group G (M7 cost), Group H (P6-B3-B/H5 MTP config) are design-surface items → postpone; Group I (P5-C) is feature carryover. Recommended **P7-B bundled slice: items 1–5 (C3/C4, C5/C6, M4, M5/M6)** — all diagnostics-only, same return values as before. **P7-B is NOT authorized by P7-A** and requires separate approval. No `tools/**` / `tests/**` / `VERSION` / tag changes. |
| P7-B | Done (`d0ae7fd`) | Hook silent-failure diagnostics bundle. **All five P7-A core items implemented as diagnostics-only — no business behavior change anywhere.** (1) **C3** — `tools/claude_hooks/mcp_gate.py::load_state` emits `state_load_failed` event via existing `log_event(config_dir, …)` on `JSONDecodeError` / read failure, then returns the same defaults dict as before. (2) **C4** — `save_state` emits `state_save_failed` on write failure, then returns unchanged. (3) **C5/C6** — `tools/claude_hooks/mcp_auto_worker.py` adds bounded `_record_spawn_failure()` helper (1 MB self-truncating, JSONL, fire-and-forget) and wires it into all 4 spawn paths (`spawn_background`, `spawn_local_check` log + Popen, `spawn_summarize_file` log, `spawn_review_diff` stdin + log). Failures land in `.local_llm_out/auto/_spawn_failures.log`. Fire-and-forget semantics preserved; nested `except: pass` inside the helper. (4) **M4** — `tools/claude_hooks/mcp_doctor.py::run_checks` adds 3 additive checks (`auto_dir_present` — WARN on missing, OK on present; `auto_results_count` — OK/WARN at >50; `spawn_failures_log` — OK absent/empty, WARN non-empty, FAIL >1 MB). No existing-check semantics changed. (5) **M5/M6** — `_extract_read_info` and `review_tool_succeeded` accept an optional `config_dir` parameter; on unrecognized non-empty `tool_response` shape, log `mcp_shape_unknown` event (reason: `no_known_read_shape` / `empty_text_from_nonempty_response` / `text_not_json` / `result_not_dict`); return value preserved bit-for-bit. Legacy callers without `config_dir` continue to work (purely passive). New helper `_log_mcp_shape_unknown` swallows its own failures. Tests: 20 new tests across `tests/test_mcp_gate_boundary.py` (12 tests covering C3/C4/M5/M6), `tests/test_mcp_auto_worker.py` (4 tests for spawn failure + helper truncation + helper robustness), `tests/test_mcp_doctor.py` (7 tests covering all M4 severities). Regression: 115 passed in hook suite; 321 passed across `tests/test_p4_worker_pool_dry_run.py` + `tests/test_p5_v4_flash_experimental.py` + `tests/test_p6_timeout_observability.py` + `tests/test_call_ledger.py` + `tests/test_check.py` + `tests/test_stop_hook.py`. **Explicitly NOT in this slice:** C2 (streaming), H6 (classify_error), P6-B2-C (record_call propagation), M3 (rotation), M7 (cost), P6-B3-B/H5 (MTP config), P5-C. No `tools/local_llm_mcp_server.py` / `tools/local_llm_worker.py` / `tools/local_llm_debate.py` / `tools/local_llm_router.py` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `tools/health_store.py` / `tools/local_llm_check.py` / `tools/local_llm_profiles.json` / `tools/local_llm_tasks.json` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag / release changes. |
| P7-B.1 | Done (no commit) | Read-only post-commit verification of P7-B at `d0ae7fd`. Verified: (a) HEAD commit touched only 9 allowed files (3 `claude_hooks/`, 3 hook tests, 3 docs/status); zero diff against the forbidden-files guard (`tools/local_llm_mcp_server.py`, `tools/local_llm_worker.py`, `tools/local_llm_debate.py`, `tools/local_llm_router.py`, `tools/call_ledger*.py`, `tools/health_store.py`, `tools/local_llm_check.py`, `tools/local_llm_profiles.json`, `tools/local_llm_tasks.json`, `CLAUDE.md`, `docs/mcp-task-policy.md`, `VERSION`). (b) All five P7-B items (C3, C4, C5/C6, M4, M5/M6) substantively recorded in PROJECT_STATUS.md row 56, CHANGELOG.md Unreleased entry, and `docs/P6_RUNTIME_RELIABILITY_OBSERVABILITY_AUDIT.md` §13.2. (c) Diagnostics-only contract recorded in all three docs (audit doc §13.3 explicitly lists the bit-for-bit return-value invariants). (d) Deferred items (C2, H6, P6-B2-C, M3, M7, P6-B3-B/H5, P5-C) reaffirmed in all three docs and audit doc §13.5. (e) No release: VERSION `0.9.7`, no tag, no zip. Only cosmetic gap observed: audit doc footer (line 577) said `HEAD pending commit` — accurate when written pre-commit, stale post-commit. Per user instruction this footer is back-filled by P7-C below rather than via a standalone docs-only churn commit. **P7-B.1 itself did not need a commit and did not produce one.** No `tools/**` / `tests/**` / docs / `VERSION` / tag changes during P7-B.1. |
| P7-C | Done (this entry) | Docs/status phase closeout for the P7 chain. **P7 chain closed** (P7-A → P7-B → P7-B.1 → P7-C). P7 phase result: five previously-silent failure modes are now structured-event observable without any change to caller-visible behavior — (1) corrupt/unreadable `state.json` emits `state_load_failed` to `hook-events.jsonl`; (2) `save_state` write/encoding/permission failure emits `state_save_failed`; (3) auto-worker spawn and log-write failures emit bounded JSONL entries to `.local_llm_out/auto/_spawn_failures.log` (self-truncating at 1 MB); (4) `mcp_doctor` surfaces three new auto-worker checks (`auto_dir_present`, `auto_results_count`, `spawn_failures_log`); (5) unrecognized MCP `tool_response` shapes emit `mcp_shape_unknown` with one of four reasons. **Behavior invariants preserved:** `load_state` returns the same `_STATE_DEFAULTS` dict; `save_state` has no return value; all four spawn paths remain fire-and-forget; `_extract_read_info` and `review_tool_succeeded` return identical values for identical inputs; `mcp_doctor` existing checks unchanged in count, name, and severity semantics. **Explicitly frozen / deferred at P7-C** (none authorized): C2 streaming double-serialization (high blast radius — changes `stdout` contract for all 8 worker-backed MCP tools), H6 `classify_error` substring-matching rewrite (shifts ledger `error_type` distribution), P6-B2-C `record_call()` write-failure propagation (explicit "must never crash the call" design intent), M3 ledger rotation (no archive layout decided), M7 cost-estimate LAN-vs-local distinguisher, P6-B3-B/H5 MTP endpoint hardcoding (would introduce config surface), P5-C `_env`/warmup/per-profile provider hint. **No release at P7-C:** VERSION remains `0.9.7`; HEAD carries no tag; no release; no zip. **Possible future directions, none authorized by P7-C:** P6-B2-C design-only planning; P6-B3-B design-only planning; P7-D streaming contract correction (C2) — only with explicit approval; release prep — only with explicit approval. **Backfill:** audit doc §13 footer's "HEAD pending commit" string is replaced with the P7-B commit `d0ae7fd`, eliminating the post-commit staleness flagged by P7-B.1. No `tools/**` / `tests/**` / `VERSION` / `CLAUDE.md` / `docs/mcp-task-policy.md` / tag / release changes in P7-C. |
| C3-B | Done (this entry) | Real MCP dogfood verification of `local_generate_test_plan` repo map advisory opt-in.  Claude Code / MCP server restarted, new C3-B schema loaded (`repo_map_context_used` field present in response — confirmed not stale process).  8-step verification all passed via real MCP calls: default mode (`repo_map_context_used=false`, no injection, ledger clean); opt-in mode (`use_repo_map=true` → `repo_map_context_used=true`, `related_tests=1`, `subsystems=["mcp"]`); explicit `repo_map_path`; missing path fallback (in-memory build succeeded); corrupt path (`repo_map_context_warning="repo_map_corrupt"`, no failure, graceful degrade); ledger verification (all states correctly recorded); boundary integrity (MCP tool count 10, no hooks/review/debate/gate changes, git clean).  `C3B_REAL_MCP_DOGFOOD_VERIFIED=yes`.  VERSION remains `0.10.0`, no tag.  **C3-B implementation line closed — both direct Python and real MCP paths verified.**  C3-C docs/policy sync completed (this commit). |
| C3-C | Done (this entry) | Policy/docs sync for test-plan repo-map advisory.  Documented `local_generate_test_plan` repo-map advisory behavior in `docs/mcp-task-policy.md` (new "Repo Map Advisory (C3-B)" subsection under Test Planning: default-off behavior, opt-in params, advisory-only nature, fallback/warning semantics, safety boundaries, examples) and `CLAUDE.md` (tool count 9→10, `local_repo_map` added to enumeration, Task → MCP Tool Mapping table updated with opt-in row, manual invocation list updated).  No code / test / MCP schema / worker / ledger / hook / VERSION / tag changes.  Docs-only.  **C3 chain complete** (C0 audit → C1 generator → C2 MCP tool → C3-A context helper → C3-B implementation + real MCP dogfood → C3-C docs/policy sync).  C3 final closeout completed (this commit). |
| C3 final | Done (this entry) | Phase closeout for the C3 repo/codebase map chain.  **C3 chain complete** (C0 audit → C1 generator → C1 dogfood closeout → C2 MCP tool → C2 dogfood closeout → C3-A context helper → C3-A dogfood closeout → C3-B implementation → C3-B real MCP dogfood → C3-B closeout → C3-C policy/docs sync → C3-C typo fix).  Capabilities delivered: repo map heuristically generable; `local_repo_map` exposed as 10th manual MCP tool (manual-only, heuristic); context helper extracts target role / subsystem / risk_tags / related_tests / subsystem_peers; `local_generate_test_plan` supports `use_repo_map=true` opt-in with advisory-only context injection; missing/corrupt repo map never fails test-plan; default behavior unchanged (`use_repo_map=false`).  Boundaries held: no commit gate / release guard / dangerous command guard / hook auto-trigger / review_diff / debate change; no automatic `local_repo_map` invocation; no VERSION bump (`0.10.0`); no tag; no zip; no push.  Validation: 1633/1633 full suite, 13/13 run_checks, commit-gate reviews passed, real MCP dogfood verified for C2 and C3-B.  Next: v0.11.0-D read-only planning audit for test failure classifier (D NOT started; no implementation authorized). |
| D-A | Done (audit, no code) | Read-only planning audit for test failure classifier.  Reviewed 11 source files (`tools/local_llm_mcp_server.py`, `tools/local_llm_worker.py`, `tools/call_ledger.py`, `tools/call_ledger_cli.py`, tests, docs).  Recommended new 11th MCP tool `local_classify_test_failure` (synchronous, independent of E/queue).  Rejected extending `local_generate_test_plan` or `local_review_diff`.  Defined minimal input (stderr required, stdout/exit_code/test_command/changed_files optional), output schema (8 fields, fixed enums), 8 failure classes, confidence caps, hard safety boundaries, 3 recommended ledger keys, repo-map opt-in mirroring C3-B, and 5-slice implementation plan (D-A → D-B → D-C → D-D → D-E).  No code changes.  `D_READONLY_PLANNING_AUDIT_COMPLETE=yes`.  Next: D-B worker prompt + schema. |
| D-B | Done (this entry) | Worker prompt + response schema for `classify-test-failure`.  Added `classify-test-failure` task prompt to `tools/local_llm_worker.py::TASK_PROMPTS` — advisory-only classifier with 8 output fields, 8 failure classes, confidence caps, secret-safety rules, and boundary wording.  52 focused tests in `tests/test_classify_test_failure_prompt.py`.  Helper-only — no MCP tool, handler, ledger, or hook integration yet.  MCP tool count remains 10.  No `tools/local_llm_mcp_server.py` / `tools/call_ledger.py` / `tools/call_ledger_cli.py` / `CLAUDE.md` / `docs/mcp-task-policy.md` / `VERSION` / tag changes.  Next: D-C MCP tool implementation (11th tool). |
| D-C | Done (this entry) | MCP tool `local_classify_test_failure` implemented as 11th tool.  Added to TOOLS, TOOL_HANDLERS, `_ESCALATION_CHAIN`.  New handler `call_classify_test_failure()` validates input, truncates oversized payloads, builds JSON for the D-B worker, parses classification result (validates enums, falls back to `unknown`/`low`/`classification_parse_warning="invalid_json"` on bad JSON).  3 ledger keys added: `test_failure_class`, `test_failure_confidence`, `test_failure_exit_code`.  28 focused tests in `tests/test_classify_test_failure_mcp.py`.  8 existing tests updated for tool count 10→11 across 6 test suites.  No hooks/gates/guards/debate/queue/VERSION/tag changes.  VERSION remains `0.10.0`, no tag.  Next: D-D real MCP dogfood (requires MCP server restart). |
| D-C.1 | Done (this entry) | Hotfix for two blocking bugs found during D-D real MCP dogfood.  **Bug 1** (`test_failure_exit_code` (int) as raw `extra_env` key crashed subprocess with `environment can only contain strings`); fixed by passing it through `_build_ledger_extra_env` kwargs → `LOCAL_LLM_LEDGER_EXTRA` JSON.  **Bug 2** (handler used `build_router_cmd(...)` without `--stdin`; worker received no payload and returned `empty_input`); fixed by explicit command construction with `--stdin` (same pattern as `call_review_diff:2634`).  Tests: 7 new + 3 updated = 34/34 classify_test_failure_mcp, 1719/1719 full suite, 13/13 run_checks, commit-gate review passed.  No hooks/gates/guards/debate/queue/VERSION/tag changes.  VERSION remains `0.10.0`, no tag.  Next: re-run D-D real MCP dogfood after MCP server restart. |
| D-D | Done (no commit) | Initial real MCP dogfood of `local_classify_test_failure` at `dcd68d7`.  MCP server restarted, `tools/list` confirmed 11 tools including `local_classify_test_failure`.  Real MCP calls worked end-to-end (worker invoked, classification returned), but discovered **stale envelope**: top-level `failure_class`/`confidence` returned `unknown`/`medium` (handler fallback defaults) while the worker's nested `result.result` JSON contained the correct classification.  Root cause: handler parsed worker output at the wrong JSON level, reading top-level summary wrapper instead of the nested structured result.  `D_D_MCP_DOGFOOD_STALE_ENVELOPE=yes`.  No code changes during D-D — deferred to D-D.1 hotfix. |
| D-D.1 | Done (`f354d32`) | Response envelope propagation hotfix.  Fixed `call_classify_test_failure()` in `tools/local_llm_mcp_server.py` to parse the nested worker result JSON correctly so top-level `failure_class`/`confidence`/`advisory_only` fields match the worker's structured classification.  Tests updated: 41 passed in `tests/test_classify_test_failure_mcp.py`, 68 passed in `tests/test_mcp_server.py`.  `run_checks`: 13/13 passed, 1726 tests recorded.  Commit gate `local_review_diff` passed.  Working tree clean.  No VERSION/tag/zip/push/background queue/release changes.  Next: D-D.2 re-dogfood with real MCP calls after MCP server restart. |
| D-D.2 | Done (no commit) | Real MCP envelope re-dogfood at `f354d32`.  MCP server restarted, 8 test cases run via real MCP calls: assertion (`failure_class=assertion, confidence=high`), import_error (`import_error, high`), dependency (`dependency, high`), syntax_error (`syntax_error, high`), timeout (`timeout, high`), invalid input (`ok=false`, no worker), secret redaction (no token/API key in output), huge output (>50KB, no crash, degraded to `unknown/low` — expected).  All valid inputs now propagate correct top-level envelope — no more stale `unknown/medium`.  Ledger privacy verified (char counts only, no full stderr/stdout/tokens).  `D_D2_REAL_MCP_ENVELOPE_RE_DOGFOOD_VERIFIED=yes`.  Working tree clean; no code/doc/test changes. |
| D-E | Done (audit, no code) | Read-only integration boundary audit at `f354d32`.  Confirmed: `local_classify_test_failure` is only an advisory-only MCP tool — NOT consumed by hooks (`tools/claude_hooks/` zero matches), commit gate, release guard, dangerous command guard, background queue, `local_review_diff`, or `local_debate_review_diff`.  Ledger privacy validated, version/release boundary clean (VERSION `0.10.0`, no tag/zip/push).  `D_E_READ_ONLY_CLOSEOUT_AUDIT_PASS=yes`.  Recommended docs-only closeout commit for D-D through D-E chain. |
| E-A | Done (audit, no code) | Read-only planning audit for classifier automation integration at `6af247d`.  Confirmed `local_classify_test_failure` remains advisory-only MCP tool with zero automation consumers.  Evaluated 8 candidate integration points: CLI helper wrapper (approved), run_checks suggestion (approved), Stop hook reminder (deferred), status quo MCP-only (approved).  Rejected 8 automatic paths: commit gate, release guard, dangerous command guard, background queue, auto-fix, auto-skip hooks/gates, hook-driven auto-trigger, review/debate integration.  `E_A_READ_ONLY_PLANNING_AUDIT_PASS=yes`.  No code changes.  VERSION remains `0.10.0`. |
| E-B | Done (`9168c19`) | Manual test-failure CLI helper implemented.  New `tools/classify_failure_helper.py` — thin CLI wrapper calling the same `classify-test-failure` worker via router, with same truncation caps (50KB stderr, 20KB stdout, 1KB test_command, 50 changed_files).  Supports `--stderr`/`--stdout`/`--exit-code`/`--test-command`/`--changed-file`/`--profile`/`--model`/`--json`/`--stderr-file`/`--stdout-file`/`--stdin-json`.  Exit code policy: 0=helper completed, 2=invalid input, 3=worker/router failure — classification lives only in output, never in exit code.  `tools/run_checks.py` failure-path tips after pytest failure (tips only, no auto-call).  42 focused tests in `tests/test_classify_failure_helper.py`.  Existing classifier MCP tests (41) and run_checks (13/13, 1768 tests) unchanged.  No hooks/gates/guards/queue/VERSION/tag changes.  No changes to MCP server, worker, router, ledger, CLAUDE.md, or mcp-task-policy.md.  VERSION remains `0.10.0`. |
| E-C | Done (dogfood, no code) | Real CLI dogfood of `tools/classify_failure_helper.py` at `9168c19`.  4 valid cases (assertion/import_error/dependency/syntax_error) all returned exit 3: `worker_failure — could not parse classification from worker output`.  Invalid input correctly returned exit 2.  Root cause: worker output wraps classification in markdown code fence (` ```json\n{...}\n``` `) but `parse_worker_result` only handled pure JSON strings and dicts.  Working tree clean; no tracked file changes.  `E_C_MANUAL_HELPER_DOGFOOD_PASS=no`. |
| E-C.1 | Done (`29cface`) | Markdown-fenced JSON parser hotfix.  Added `_strip_json_code_fence()` in `tools/classify_failure_helper.py` and wired into three `json.loads` sites in `parse_worker_result`.  Supports ` ```json `, ` ```JSON `, bare ` ``` ` fence, and pure JSON (backward-compatible).  Malformed fenced JSON safely returns `None`.  Tests: 48 passed (6 new fenced JSON).  MCP classifier tests: 41 passed.  run_checks: 13/13, 1774 tests.  No VERSION/hook/gate/queue changes.  No changes to MCP server, worker, router, ledger or prompt.  `E_C1_FENCED_JSON_PARSER_FIX_COMMITTED=yes`. |
| E-C.2 | Done (dogfood, no code) | Real CLI dogfood rerun at `29cface`.  All 4 valid cases passed: assertion (`exit 0, ok=true, failure_class=assertion`), import_error (`exit 0, import_error, high`), dependency (`exit 0, dependency, high`), syntax_error (`exit 0, syntax_error, medium`).  Invalid input: `exit 2`.  Secret redaction: `exit 0`, no token/API key in output.  Huge stderr (>55KB via `--stderr-file`): `exit 0`, no crash, no full stderr leak.  All outputs include `advisory_only=true`, `input_lengths`, `.local_llm_out/` `output_path`.  Working tree clean; VERSION `0.10.0` unchanged.  `E_C2_MANUAL_HELPER_DOGFOOD_PASS=yes`.  E-C chain closed. |

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

## v0.11.0-A — Summary Cache Authority (closed)

- **A1** (`dc4f2e7`): removed redundant MCP-layer summarize-file cache.
  Worker cache (`local_llm_cache.py`) is now authoritative for both
  summarize-file and summarize-tree.  Fixed three MCP cache bugs:
  cache key lacked model/prompt_hash/size; hardcoded 1h TTL; cache
  hits bypassed worker entirely (no ledger record).  16 new tests.
  1316/1316 passed, 13/13 run_checks.
- **A2** (dogfood, no commit): end-to-end verification via real MCP
  `local_summarize_tree` calls.  First call: `cache_hit=false`,
  `dur=104527ms`.  Second call (same params): `cache_hit=true`,
  `dur=0ms` in ledger, observed elapsed ~0.89s.  `local_summarize_file`
  invalidation confirmed after file content change.  Caveat: Claude
  Code MCP client may cache identical `local_summarize_file` tool
  calls, polluting direct same-file A/B tests — this is a Claude Code
  behavior, not a pipeline bug.
- **Line closed**.  Summary cache is operational and measurable:
  worker cache writes correct cache-hit ledger records with
  `duration_ms=0`; file-change invalidation works.  No VERSION bump,
  no tag.
- **Next**: v0.11.0-B0 diff risk preclassifier contract audit.
- **B1-A** (this step): diff preclassifier safety core (`tools/local_llm_preclassifier.py`).
  Heuristic-only — no model calls, no debate integration, no debate skipping.
  All outputs default to `escalate_to_debate=true` and `skip_debate_allowed=false`.
  58 focused tests in `tests/test_preclassifier.py`. B1-A iron rule: escalate always
  true, skip_allow always false. This is a safety classifier, not a debate bypass
  engine.
- **Next**: B1-B ledger contract or B1-C advisory integration, pending review.
- **B1-B** (this step): preclassifier ledger reporting contract.
  Extended `KNOWN_EXTRA_KEYS` (+12 fields: `diff_risk_level`, `diff_risk_confidence`,
  `debate_skipped`, `debate_skip_reason`, `preclassifier_profile`, `preclassifier_model`,
  `preclassifier_request_id`, `safety_blockers`, `debate_skip_allowed`,
  `skip_debate_recommended`, `preclassifier_method`, `changed_files_count`).
  Added `filter_debate_skips()` + `summarize_debate_skips()` to `tools/call_ledger.py`.
  Added `debate-skips` CLI subcommand with JSON/text output, per-risk/confidence/profile
  breakdowns, and estimated seconds/tokens saved. 24 new tests in
  `tests/test_preclassifier_ledger.py`. No debate integration; debate-skips shows zero
  until B1-C/B1-D starts writing records. Old records unaffected — fields are additive.
- **Next**: B1-C advisory integration in non-commit/non-release debate path.
- **B1-C** (this step): advisory preclassifier integration in debate path.
  `call_debate_review_diff()` runs preclassifier before debate, injects
  `preclassifier_advisory` into response, stamps `LOCAL_LLM_LEDGER_EXTRA`.
  Debate always executes regardless — `debate_skipped` and `debate_skip_allowed`
  always false. 18 new tests + 6 updated mocks. `call_review_diff` auto-debate
  path not integrated (safer). Preclassifier crash is non-fatal.
- **B1-C3** (this step): fixed debate ledger propagation. `local_llm_debate.py` reads
  `LOCAL_LLM_LEDGER_EXTRA` via `_load_ledger_env_extra_for_debate()`, merges B1-B
  fields into per-round ledger records. Debate-authoritative fields can't be overridden;
  `debate_skipped`/`debate_skip_allowed` forced false. 15 new tests. 1431/1431 passed.
- **B1-C4** (dogfood, no commit): re-verification passed. Real MCP
	  `local_debate_review_diff` executed on docs-only diff (elapsed ~80s,
	  2-round fast mode, models `qwen3.6:27b-q8-ud` + `reasoning_checker`).
	  MCP response: `preclassifier_advisory` present — `ok=true`, `risk_level=low`,
	  `confidence=high`, `skip_debate_recommended=true`, `debate_skipped=false`,
	  `debate_skip_allowed=false`, `changed_files_count=1`, `safety_blockers=[]`.
	  Ledger round records: `call_89b33304629d` (round 1) and `call_96224f4e6b01`
	  (round 2) both carry all 12 B1-B preclassifier fields. `debate-skips` CLI
	  returns `total_skipped=0`. Working tree clean — no files changed.
	- **v0.11.0-B1 closed — diff preclassifier advisory line.**
	  B1-A: heuristic-only safety core (58 tests). B1-B: ledger contract with
	  12 preclassifier/debate-skip fields and `debate-skips` CLI (24 tests).
	  B1-C: advisory integration in `call_debate_review_diff` — response gets
	  `preclassifier_advisory`, debate always executes, `debate_skipped=false` /
	  `debate_skip_allowed=false` (18 tests). B1-C1: regression reconciled.
	  B1-C2: first dogfood partial. B1-C3: debate ledger propagation fixed
	  (`local_llm_debate.py` reads `LOCAL_LLM_LEDGER_EXTRA`, merges allowlisted
	  B1-B fields, forces `debate_skipped=false` / `debate_skip_allowed=false`;
	  15 tests; 1431/1431 passed). B1-C4: dogfood re-verified — response advisory
	  present, both round ledger records carry B1-B fields, `debate-skips=0`,
	  working tree clean.
	  **B1 state at closeout** (HEAD `dc8fb8e`, `v0.10.0-6-gdc8fb8e`):
	  Fully observable advisory preclassifier line — classifies, responds, and
	  records without ever skipping debate. `preclassifier_advisory` is now
	  visible in both MCP response and per-round debate ledger records. Debate
	  skip remains disabled (`debate_skipped=false`, `debate_skip_allowed=false`).
	  Commit gate, release guard, and dangerous command guard unchanged. VERSION
	  remains `0.10.0`. No tag. No release.
	- **B1-D** (audit, no code): controlled skip policy audit passed.
	  Read-only inspection confirmed no skip branches exist.  Designed
	  minimal opt-in docs-only auto-debate skip: integration point =
	  `call_review_diff` auto-escalation only, two env knobs
	  (`LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP` default off,
	  `LOCAL_LLM_FORCE_DEBATE_REVIEW` circuit breaker), docs-only files
	  only (no tests-only), non-skippable conditions enumerated.
	  Verdict: PROCEED.
	- **v0.11.0-B1-E**: controlled low-risk auto-debate skip implemented.
	  `_should_skip_auto_debate_for_low_risk_docs()` in MCP server gates
	  skip behind env opt-in, preclassifier, and docs-only check.  Wired
	  into `call_review_diff()` auto-debate escalation only — manual
	  `local_debate_review_diff` never skipped.  Skip response injects
	  `debate_auto_escalation_skipped` with `safe_to_commit=false` and
	  `requires_commit_gate_review=true`.  Ledger skip record written
	  (`debate_skip_policy=b1-d-v1`, `debate_mode=false`).  3 new
	  `KNOWN_EXTRA_KEYS`.  37 new tests.  Commit/release/dangerous
	  guards unchanged.  VERSION remains `0.10.0`.  No tag.
	- **B1-E dogfood** (direct Python, no commit): verified.
	  `B1E_DOGFOOD_DIRECT_VERIFIED=yes`,
	  `B1E_REAL_MCP_ENV_ON_PENDING=yes`.  Direct Python all 8 steps
	  passed: env-off preserves auto-debate; env-on docs-only skips
	  auto-debate (single-model review still runs); `safe_to_commit=false`;
	  skip ledger record written; `debate-skips` CLI counts skips
	  (`total_skipped=40`); force debate override works; manual
	  `local_debate_review_diff` never skipped; sensitive files never
	  skipped.  Caveat: true MCP-process env-on verification pending
	  Claude Code / MCP server restart with
	  `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP=true`.  HEAD `a8fe5aa`,
	  `v0.10.0-8-ga8fe5aa`, VERSION `0.10.0`, working tree clean.
	  **Next**: B1-E2 real MCP env-on verification after MCP restart.
	- **B1-E2 real MCP env-on verification** (no commit): passed.
	  `B1E_DOGFOOD_DIRECT_VERIFIED=yes`,
	  `B1E_REAL_MCP_ENV_ON_VERIFIED=yes`,
	  `B1E_REAL_MCP_ENV_ON_PENDING=no`.
	  Baseline: HEAD `2ce8080`, `v0.10.0-9-g2ce8080`, VERSION `0.10.0`.
	  Claude Code / MCP server restarted with
	  `LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP=true` and
	  `LOCAL_LLM_FORCE_DEBATE_REVIEW` not set.
	  Real MCP `local_review_diff` on docs-only heavy diff
	  (163 lines, 6,868 chars, `PROJECT_STATUS.md` only):
	  auto-debate successfully skipped; single-model review
	  (`commit_reviewer` / `qwen3-coder:30b`) still ran (~15s).
	  Response: `debate_auto_escalation_skipped.skipped=true`,
	  `safe_to_commit=false`, `requires_commit_gate_review=true`,
	  `manual_debate_still_available=true`, `policy=b1-d-v1`,
	  `policy_version=1`, `preclassifier_advisory.risk_level=low`,
	  `preclassifier_advisory.confidence=high`.
	  Ledger: skip record `call_06dfa216bc1d` written with all
	  17 expected fields; `debate-skips` CLI reports
	  `total_skipped=49` (includes this skip).
	  Manual `local_debate_review_diff` verified still executes
	  full debate (~127s, 2 models): `debate_skipped=false`,
	  `debate_skip_allowed=false`, no `debate_auto_escalation_skipped`.
	  Boundaries preserved: manual debate never skipped; commit gate
	  unchanged; release guard unchanged; dangerous command guard
	  unchanged; skip default remains off unless env knob is set.
	  VERSION remains `0.10.0`.  No tag.  Working tree clean.
	  **B1-E line closed**: both direct Python and real MCP env-on
	  paths verified.
	- **B1 final closeout** (this entry): diff preclassifier +
	  controlled auto-debate skip chain closed.
	  `B1_FINAL_CLOSED=yes`.
	  `B1E_REAL_MCP_ENV_ON_VERIFIED=yes`.
	  Pre-closeout HEAD: `54d3c69`, `v0.10.0-10-g54d3c69`,
	  VERSION `0.10.0`.
	  What B1 provides:
	  - preclassifier risk advisory in debate response and ledger
	  - `debate-skips` CLI reporting
	  - controlled env-gated auto-debate skip for docs-only diffs
	    (single-model review still runs, `safe_to_commit=false`,
	    `requires_commit_gate_review=true`)
	  What B1 does NOT do:
	  - does not skip manual `local_debate_review_diff`
	  - does not bypass commit gate
	  - does not bypass release guard
	  - does not mark `safe_to_commit=true` on skip
	  - does not enable skip by default
	  - does not skip tests-only / runtime / security / sensitive files
	  **B1 chain closed.**
	- **v0.11.0-C0 audit** (read-only, no commit): completed.
	  Audited 14 files.  Found no existing persistent repo map,
	  module ownership, test-to-module mapping, or subsystem-aware
	  diff review.  Designed schema v1 and C1→C5 phased integration.
	  Verdict: PROCEED to C1.
	- **v0.11.0-C1 implementation**: repo map generator landed.
	  `tools/local_llm_repo_map.py` — heuristic-only, no model calls,
	  no MCP integration, no ledger writes.  Schema v1: 19 roles,
	  15 risk tags, entrypoint detection, test mapping inference,
	  14 subsystems, deterministic sort.  93 tests.  Dogfood:
	  171 files, 23 test mappings, all roles verified, no sensitive
	  content.  Full suite 1561 passed.  Not yet connected to any
	  MCP tool, review path, test-plan, or hooks.
	- **C1 dogfood** (no commit): verified.
	  `C1_IMPLEMENTED=yes`, `C1_DOGFOOD_VERIFIED=yes`.
	  Implementation commit: `d223063`,
	  `v0.10.0-12-gd223063`, VERSION `0.10.0`.
	  `tools/local_llm_repo_map.py` standalone: `--root . --json`
	  produces valid schema v1.  `total_files=171`,
	  `test_mapping entries=23`.  All key roles verified.
	  `.local_llm_out/` ignored, no sensitive content/body in
	  output.  93/93 repo map tests, 1561/1561 full suite,
	  13/13 run_checks.  Boundaries: no MCP integration yet, no
	  review/test-plan/hooks integration, no gate behavior changed.
	  **C1 line closed.**
	- **v0.11.0-C2 implementation**: MCP tool `local_repo_map`
	  landed.  10th MCP tool, heuristic-only, no model calls,
	  manual invocation only.  `call_repo_map()` calls
	  `local_llm_repo_map.py` directly.  Ledger records written.
	  Response: `advisory_only=true`, `manual_only=true`.
	  33 focused tests, 1594 full suite passed.
	  Not connected to review/test-plan/hooks/auto-invocation.
	  **C2 implementation complete.**
	  **C2 real MCP dogfood verified.**
	  `C2_IMPLEMENTED=yes`, `C2_REAL_MCP_DOGFOOD_VERIFIED=yes`.
	  Real MCP tools/list shows 10 tools; `local_repo_map`
	  present; all 9 original tools intact.  Real MCP call:
	  `ok=true`, `schema_version=1`, `total_files=172`,
	  `cache_hit=false`, `advisory_only=true`, `manual_only=true`.
	  Files sorted deterministically by path, no file body,
	  no `.local_llm_out` files, no `.env` content.  Key roles
	  verified: `mcp_server`, `worker`, `router`, `debate`,
	  `ledger`, `hook`, `project_status`, `test`.
	  `tools/local_llm_repo_map.py` → `role=source` (acceptable
	  for C2).  Parameter behavior: `include_tests=false`
	  (115 files, test_files=0), `include_docs=false` (129 files,
	  docs_files=0), `max_files=5` (exactly 5, deterministic),
	  invalid path (`ok=false`, `error_type=invalid_path`),
	  `write_output=true` (`.local_llm_out/repo_map.json`,
	  48990 bytes, git-clean).  Ledger records confirmed:
	  `mcp_tool_name=local_repo_map`, `source=manual-mcp`,
	  `profile=repo_map`, `model=none`, `provider=heuristic`,
	  `repo_map_schema_version=1`, `repo_map_advisory_only=true`.
	  No auto integration: no hooks reference, no auto-hook
	  trigger, no commit/release/danger guard changes.
	  Working tree clean.  VERSION remains `0.10.0`, no tag.
	  **C2 line closed.**
	  **C3-A implemented and dogfood-verified.**
	  `C3A_HELPER_DOGFOOD_VERIFIED=yes`.
	  Commit `9919b3c`: pure helper `build_repo_map_context_for_path()`
	  in `tools/local_llm_repo_map.py`.  No filesystem I/O, no model
	  calls, no MCP calls.  Extracts target role/subsystem/risk_tags,
	  related_tests, subsystem_peers.  Returns `advisory_only=true`.
	  No MCP schema change, no `local_generate_test_plan` integration.
	  17 new tests.  110 repo map tests, 1611 full suite, 13/13
	  run_checks, commit-gate ok.
	  Dogfood: `tools/local_llm_mcp_server.py` → `role=mcp_server`,
	  `subsystem=mcp`, `risk_tags=["mcp"]`, `entrypoint=true`.
	  `related_tests` → `tests/test_mcp_server.py`.  `tests/
	  test_mcp_repo_map.py` not mapped (known name-based heuristic
	  limitation).  `subsystem_peers` → `.mcp.json` (config).
	  Cap/unknown-path/Windows-path/safety checks all passed.
	  **C3-A line closed.**
	  **C3-B implemented.**
	  `local_generate_test_plan` now accepts `use_repo_map` (default
	  false), `repo_map_path`, `repo_map_max_files`.  When
	  `use_repo_map=true`: loads/builds repo map, extracts context
	  via C3-A helper, injects advisory prompt prefix via
	  `LOCAL_LLM_REPO_MAP_CONTEXT` env var.  Worker `build_prompt`
	  reads env var (best-effort, never crashes).  Response adds
	  `repo_map_context_used` and related additive fields.  Ledger
	  `KNOWN_EXTRA_KEYS` extended with 4 C3-B fields.  Missing/
	  corrupt repo map → warning, not failure.  22 new tests,
	  233 repo-map+MCP, 1633 full suite, 13/13 run_checks.
	  `local_repo_map` remains manual-only.  No hooks/review/debate/
	  gate changes.  VERSION remains `0.10.0`, no tag.
	  **C3-B line closed.**
	  Next: C3-B real MCP dogfood (default + `use_repo_map=true`).

## v0.11.0-FA — Project-Goal Alignment Audit (closed, no commit)

- **F-A** (no commit): read-only project-goal alignment audit at
  `423b632`.  Assessed 11 MCP tools, 12 worker tasks, 59 test files,
  ~1800 tests against the core goal: "small models do heavy lifting,
  large models audit."  Found 3 gaps: (A) no unified task bootstrap,
  (B) zero cross-project dogfood metrics, (C) test failure helper lacks
  convenience layer.  Recommended F-B: local-translator-agent real
  downstream dogfood.
  `F_A_PROJECT_GOAL_ALIGNMENT_AUDIT_PASS=yes`.

## v0.11.0-FB — local-translator-agent Downstream Dogfood (closed, no commit)

- **F-B** (no commit): read-only real downstream dogfood at `423b632`.
  Tested local-llm-pipeline on local-translator-agent (`9f81601`,
  `v0.9.2-129-g9f81601`).  Repo map: 1,244 files / 40 source / 11
  subsystems / 29 entrypoints.  Summaries: tm_service.py (68KB) and
  app.py (105KB) — both correctly identified architecture, key
  functions, dependencies, risks.  Test plan for tm_service.py: 10
  behaviors, 16 boundary conditions, 14 error paths.  Estimated token
  saving: ~117K → ~5.5K (~95%).  Friction confirmed: MCP external path
  blocking, no one-command bootstrap, large-file truncation.
  `F_B_LOCAL_TRANSLATOR_AGENT_DOGFOOD_PASS=yes`.  Top gap: no task bootstrap.

## v0.11.0-FC — Task Bootstrap Read-Only Design (closed, no commit)

- **F-C** (no commit): read-only design audit at `423b632`.  Evaluated
  3 candidates: CLI-only (A), MCP tool (B), docs-only (C).  Recommended
  A (CLI-only): `tools/task_bootstrap.py`, `--project PATH`, thin
  orchestration layer reusing repo_map Python API + router CLI.
  Designed output schema (JSON + markdown), file selection strategy
  (instruction files > entrypoints > largest sources), token budget
  model (default 6,000), and safety boundaries (advisory-only, writes
  `.local_llm_out/` only).  Two narrowing corrections applied:
  instruction files listed but not auto-summarized; test plan deferred
  to `suggested_next_calls`.  `F_C_TASK_BOOTSTRAP_DESIGN_PASS=yes`.

## v0.11.0-FD — Task Bootstrap Implementation (in progress)

- **FD** (pending commit): `tools/task_bootstrap.py` — thin
  orchestration CLI.  Combines repo_map → instruction file detection
  → file selection (entrypoint/size/keyword priority) → optional
  summaries via router → risk hints → suggested next calls → what
  NOT to read.  Outputs `<ts>_bootstrap.{md,json}` to `.local_llm_out/`.
  41 tests.  Read-only, advisory-only.  No MCP/gate/hook/path-policy
  changes.

- **Tests**: 41 passed (`tests/test_task_bootstrap.py`) — instruction
  file selection, summary candidate prioritization, test exclusion,
  keyword matching, risk hints, what-not-to-read, suggested calls,
  budget, CLI exit codes (0/1/2/3), dry-run, no-summaries, JSON/MD
  output schema, advisory boundary, output file writing, git info.

## v0.11.0-FE — Task Bootstrap Re-Dogfood (closed, no commit)

- **F-E** (no commit): re-dogfood of `task_bootstrap.py` on local-translator-agent
  at `4471d1c`.  Confirmed one command replaces F-B's three.  Dry-run exit 0,
  normal mode exit 0.  Found 4 refinement issues: (1) file selection biased
  toward embedded tools — `tools/local_llm_*` entrypoints crowded out `app.py`
  and `services/tm_service.py`; (2) summary extraction stored router stderr
  (112 chars) instead of actual markdown file content (4.5KB); (3) instruction
  files included `models/faster-whisper-*/README.md` dependency noise;
  (4) task keywords "translation memory subtitle" could not influence selection
  because Priority 3 was never reached.  `F_E_TASK_BOOTSTRAP_RE_DOGFOOD_PASS=yes`.

## v0.11.0-FF — Task Bootstrap Refinement Audit (closed, no commit)

- **F-F** (no commit): read-only refinement audit at `4471d1c`.  Pinpointed
  all 4 issues to specific code locations in `tools/task_bootstrap.py`.
  Designed minimal fix plan with no new features, no MCP/path-policy changes.
  `F_F_TASK_BOOTSTRAP_REFINEMENT_AUDIT_PASS=yes`.

## v0.11.0-FG — Task Bootstrap Refinement Implementation (in progress)

- **FG** (pending commit): 4 targeted fixes.
  1) `_VENDOR_PATH_PREFIXES` + `_looks_like_vendor_embedded()` —
  deprioritizes `tools/local_llm_*`, `models/`, `node_modules/`, etc.
  2) `_run_summary()` — reads actual markdown file via candidate path
  resolution; never stores router stderr as summary; returns `ok=false`
  when file not readable.
  3) `_select_instruction_files()` — depth filtering; only root or
  `docs/` level; excludes `models/` and vendor paths.
  4) `_select_summary_candidates()` — restructured: P1 filtered
  entrypoints → P1.5 task keyword boost → P2 largest project sources
  → P3 remaining entrypoints as fallback.  Task keyword synonym
  expansion (translation→tm, subtitle→srt, ocr→paddleocr, etc.).
  71 tests.  No MCP/server/router/worker/path-policy changes.

## v0.11.0-FH — Refined Bootstrap Re-Dogfood (partial, no commit)

- **F-H** (no commit): re-dogfood at `d8dee6b`.  Confirmed Fix 1 (vendor)
  and Fix 3 (instruction files) working.  Found 2 remaining issues:
  (1) 13 non-vendor entrypoints still filled all slots — app.py and
  services/* not reached; (2) summary all failed (exit 3) because
  cache-hit router output lacks "MD:" line.  `F_H_PARTIAL=yes`.

## v0.11.0-FI — Second Refinement Audit (closed, no commit)

- **F-I** (no commit): pinpointed root causes.  Selection: 13 non-vendor
  non-test entrypoints fill P1 before P1.5/P2/P3 are reached.
  Summary: router cache-hit prints only "JSON:" not "MD:".  Designed
  slot allocation + JSON path derivation + application core boost.
  `F_I_SECOND_REFINEMENT_AUDIT_PASS=yes`.

## v0.11.0-FJ — Second Refinement Implementation (in progress)

- **FJ** (pending commit): 3 fixes.
  1) Slot allocation: entrypoint_slots ≤ max_summaries/3, task_kw_slots
  guaranteed, source_slots fill remainder.
  2) JSON path → MD path: parse "JSON:" line, derive .md path when
  "MD:" absent (cache-hit case).  MD still preferred when both present.
  3) Application core boost: app.py/main.py/server.py/services/ paths
  weighted higher within their priority tier.
  80 tests.  No MCP/server/router/worker/path-policy changes.

## v0.11.0-FK — Acceptance Dogfood (no commit)

- **F-K** (no commit): acceptance dogfood at `8b0573e`.  Dry-run selection
  passed — app.py, tm_service, realtime, subtitle all selected.  Normal
  mode still exit 3: `_run_summary()` only checked stderr, but router
  paths are on stdout when called via `subprocess.run(capture_output=True)`.
  `F_K_PASS=yes (1 trivial fix needed)`.

## v0.11.0-FL — Stdout Path Fix (committed)

- **FL** (`487f8af`): one fix — `_run_summary()` now combines stdout+stderr
  before scanning for MD:/JSON: path lines.  82 tests.  `F_L_COMMITTED=yes`.

## v0.11.0-FM — Final Acceptance (no commit)

- **F-M** (no commit): final acceptance dogfood at `487f8af` on
  local-translator-agent (`9f81601`).  **Clean pass.**  Dry-run selection:
  scripts/smoke + tm_service + app.py + realtime + subtitle.  Normal mode
  exit 0, summaries 3/3 OK (4,183 / 3,806 / 3,899 chars real markdown).
  tm_service correctly classified as "TM-1A.1 Translation Memory data
  persistence layer."  app.py as "central backend hub orchestrating
  translation workflows."  `F_M_TASK_BOOTSTRAP_FINAL_ACCEPTANCE_PASS=yes`.

## v0.11.0-FN — Task Bootstrap Chain Closeout (in progress)

- **FN** (pending commit): docs-only closeout.  Task bootstrap workflow
  documented in CLAUDE.md.  Full chain (F-D → F-M) recorded in
  PROJECT_STATUS.md and CHANGELOG.md.
  Next: cross-project validation (local-durable-agent) or
  task_bootstrap MCP tool evaluation — not yet authorized.

### Task Bootstrap Chain Summary

| Phase | Type | Result |
|-------|------|--------|
| F-A | alignment audit | 3 gaps identified |
| F-B | downstream dogfood | 95% token saving estimate |
| F-C | design audit | CLI-only recommended |
| F-D | implementation | v0.1.0 committed (`4471d1c`) |
| F-E | first dogfood | 4 issues found |
| F-F | refinement audit | root causes pinpointed |
| F-G | refinement impl | vendor+instr+kw+summary fixes (`d8dee6b`) |
| F-H | second dogfood | mixed — 2 issues remain |
| F-I | second audit | slot+JSON+core boost plan |
| F-J | second impl | slot alloc+JSON+core boost (`8b0573e`) |
| F-K | acceptance | selection pass, summary stdout gap |
| F-L | stdout fix | combined stdout+stderr (`487f8af`) |
| **F-M** | **final acceptance** | **clean pass** — exit 0, 3/3 OK |
| **F-N** | **docs closeout** | **this commit** |

## v0.11.0-FO — Cross-Project Validation (no commit)

- **F-O** (no commit, corrected path rerun): task_bootstrap cross-project
  validation on local-durable-agent at
  `C:\Users\Zero\Documents\New project 3\local-durable-agent`
  (HEAD `1f81290`, `v0.8.3-39-g1f81290`, clean).  Dry-run selected:
  lda/cli.py, lda/core/task_manager.py, lda/db/sqlite_store.py,
  lda/policy/gate.py, lda/workspace_mutation/readiness.py.
  Normal mode exit 0, summaries 3/3 OK (3,779 / 5,599 / 4,610 chars
  real markdown), context budget 5,997/6,000.  Confirmed:
  task_bootstrap works across both translator-agent (flat app+services)
  and durable-agent (lda/cli+core+db+policy modular) project types.
  `F_O_LOCAL_DURABLE_AGENT_BOOTSTRAP_VALIDATION_PASS=yes`.

## v0.11.0-FP — Cross-Project Validation Record (in progress)

- **FP** (pending commit): docs-only record of F-O validation.
  No code/test/version/MCP changes.

## v0.11.0-GA — Workflow Dogfood Planning (no commit)

- **G-A** (no commit): planning audit at `502b4d7`.  Selected minimal task:
  call ledger model-summary CLI.  Designed full control loop:
  task_bootstrap → implementation → tests → review_diff → commit.
  `G_A_WORKFLOW_DOGFOOD_PLAN_PASS=yes`.

## v0.11.0-GB — Workflow Dogfood Implementation (committed)

- **GB** (`b3e217c`): first end-to-end control loop dogfood.
  task_bootstrap on local-llm-pipeline → 3/3 summaries OK →
  implemented `model-summary` in `call_ledger_cli.py` (+8 lines,
  reuses `group_by`/`_print_groups`) + 2 tests.  162/162 call_ledger,
  1858 full suite, 13/13 run_checks, review_diff gate ok=true.
  `G_B_WORKFLOW_DOGFOOD_IMPLEMENTATION_COMMITTED=yes`.

  Usage:
  - `py -3 tools/call_ledger_cli.py model-summary` (per-model)
  - `py -3 tools/call_ledger_cli.py by-mcp-tool` (per-MCP-tool, existing)

## v0.11.0-GC — Workflow Dogfood Docs Closeout (in progress)

- **GC** (pending commit): docs-only record of G-A/G-B workflow loop.
  No code/test/VERSION changes.

## v0.11.0-HA — Release-Prep Planning Audit (no commit)

- **H-A** (no commit): read-only release-prep planning at `c038528`.
  Confirmed VERSION as sole version source.  Designed H-B/H-C/H-D phases.
  `H_A_RELEASE_PREP_PLANNING_AUDIT_PASS=yes`.

## v0.11.0-HB — Release-Prep Implementation (in progress)

- **HB** (pending commit): VERSION 0.10.0 → 0.11.0.  RELEASE_NOTES,
  CHANGELOG, PROJECT_STATUS updated for v0.11.0.  No tag, no zip,
  no push.  H-C verification pending.

## v0.10.0 Release-Prep Anchor

- VERSION: `0.9.8` → `0.10.0`
- Date: 2026-05-24
- HEAD: `3a704ff` (scope closeout), bumped to commit TBD
- Hard gates: 1300 passed, 13/13 run_checks
- Active v0.10.0 chain complete: C2 (streaming stdout), P6-B2-C (ledger write-failure obs), M3 (manual rotation), H6 (classify_error), M7 (cost credibility), P6-B3-B/H5 (endpoint unification)
- P5-C/V4-Flash deferred indefinitely — not a v0.10.0 blocker
- No tag `v0.10.0` yet — release gate pending (full debate review + release auditor on bumped HEAD)
- No zip, no push

## v0.9.8 Release-Prep Anchor

- VERSION: `0.9.7` → `0.9.8`
- Date: 2026-05-23
- HEAD: `dc253db` (test-only hotfix for stale mock)
- Hard gates at prep: 1196 passed, 13/13 run_checks, installer dry-run OK (both fresh + update)
- Deferred items reaffirmed: P6-B2-C, P6-B3-B/H5, C2, H6, M3, M7, P5-C
- P1-H through P7 chains documented in CHANGELOG v0.9.8 section
- CHANGELOG header changed from "Unreleased (post-v0.9.7)" to "v0.9.8 - 2026-05-23"
- docs/roadmap.md rewritten: v0.6.x → v0.9.8 history, current state, deferred items
- No tools / tests / implementation / tag / zip / push changes

## C2 Streaming Contract Fix — Closeout

- **Chain**: v0.10.0-A → v0.10.0-B → v0.10.0-C → v0.10.0-D.  C2 chain closed.
- **Problem**: streaming path at `run_subprocess_streaming:1417` serialized
  worker output dict into `json.dumps(output)`, while non-streaming path left
  raw stdout with `JSON:` markers.  `load_worker_output(result["stdout"])`
  could not parse the JSON string → `missing_worker_output`.
- **Fix**: `_parse_worker_stdout()` compat parser (5 strategies) at all 4
  consumer call sites; fixed file-path-vs-stdout bug at line 1413; removed
  `json.dumps(output)` at streaming producer → dict pass-through (Strategy 0).
- **Smoke**: `local_check` OK, `local_summarize_file` dict payload, no
  `missing_worker_output`, `local_review_diff` dict payload, call ledger 275
  records / 0 skipped, mcp_doctor 32/1/0, 25 targeted C2 tests, 1221 full
  suite, 13/13 run_checks, working tree clean.
- **v0.10.0-E cleanup**: explicitly deferred / not authorized.  String
  fallback strategies (1-4) are zero-cost insurance against legacy worker
  formats, test stubs, and edge-case callers.
- **Commits**: `b984511` (A design), `6f4a3c1` (B compat parser), `bbed639`
  (C dict hardening), `336274c` (D producer migration).

## P6-B2-C Call Ledger Write-Failure Observability — Closeout

- **Implemented**: v0.10.0-G at `6f644c6`.  Pure additive observability.
- **Problem**: `record_call()` returned `False` on write failure but all 5
  call sites (worker `_emit_ledger` ×3, debate `_emit_debate_round_ledger` ×2)
  discarded the return value and wrapped calls in `except: pass`.  Ledger
  write loss was completely invisible.
- **Fix**: Added `_record_write_failure()` helper — bounded JSONL diagnostic
  log at `.local_llm_out/audit/_ledger_write_failures.log`, self-truncating
  at 1 MB, never raises.  Wired into `record_call()`'s `except` block.
  `mcp_doctor` gained 3 ledger health checks (file size, file presence,
  write-failure log status).
- **Contract preserved**: `record_call()` still returns `bool`, still never
  raises.  Worker and debate call sites unchanged.  Ledger disabled path
  produces no diagnostic.
- **Real-world finding**: Doctor immediately surfaced 2 non-empty entries
  (122 bytes).  Traced to `RuntimeError("nope")` from pre-existing test
  `test_record_call_never_raises` which patches `_resolve_path` but not
  `LEDGER_DIR`.  Benign test artifact — not a production bug.  Confirms
  the diagnostic system detects real write failures.
- **Tests**: 13 targeted tests (6 call_ledger + 7 doctor).  1234 full suite.

## M3 Manual Call Ledger Rotation — Closeout

- **Implemented**: v0.10.0-H at `c975222`.  Manual CLI archive, no auto-rotation.
- **Added**: `rotate_ledger()` in `tools/call_ledger.py` — renames active
  `calls.jsonl` to `calls.<ISO-date>.jsonl`.  Never raises.  Handles
  missing ledger, empty ledger, existing archive target (blocks overwrite),
  OSError.  New `call_ledger_cli.py rotate` subcommand with `--archive-name`,
  `--dry-run`, `--path`, `--format`.  `mcp_doctor` WARN/FAIL updated to
  reference the rotate command.
- **Preserved**: `record_call()` unchanged — still append-only, still
  never-raise, no `stat()` overhead, no automatic truncation.  `read_records()`
  unchanged — reads active `calls.jsonl` only; archived ledgers are readable
  explicitly via `--path`.
- **Tests**: 9 targeted (6 rotate_ledger + 3 CLI).  1243 full suite.
- **Smoke**: `call_ledger_cli.py rotate --dry-run` printed expected archive
  name without mutating files.
- **Next**: H6 classify_error taxonomy read-only audit (affects ledger
  `error_type` distribution — requires design before code).  **Resolved:
  H6 completed v0.10.0-I through v0.10.0-J follow-up; see below.**

## H6 Classify Error Taxonomy — Closeout

- **Chain**: H6-I → H6-J → H6-J follow-up (`b41ec97`).  H6 chain closed.
- **H6-I**: Read-only audit of `classify_error()` substring heuristics.
  Identified colliding substring checks: generic timeout before connection,
  port numbers (e.g. "port 5001") captured as 5xx backend errors, generic
  JSON references flagged as invalid_json.
- **H6-J** (`4f4b648`): Narrowed JSON/parse matches (specific delimiters:
  `jsondecode`, `json decode`, `not json`, `invalid json`, `parse error`,
  `could not parse`, `failed to parse`).  Added word-boundary gating on
  5xx HTTP status codes (space-padded ` 500 `–` 504 ` prevents "port 5001"
  false positive).  Moved 5xx/server-error to Layer 6 (last heuristic
  before unknown).  14 new H6-specific tests in `tests/test_worker_safety.py`.
- **H6-J follow-up** (`b41ec97`): Swapped generic substring order so
  connection-context matching (Layer 2) runs before generic timeout matching
  (Layer 3).  Messages like "connection timed out" now correctly classify as
  `backend_unreachable` instead of `timeout`.  4 new tests.
- **Contract preserved**: `classify_error()` signature unchanged
  (`tuple[str, str]`).  `error_type` value space unchanged (6 values:
  `timeout`, `backend_unreachable`, `empty_response`, `invalid_json`,
  `backend_error`, `unknown_error`).  No `error_subtype` added.  No call
  ledger schema change.  No caller changes.  No migration required for
  historical ledger records.
- **Classification ordering**:
  1. `isinstance(exc, requests.Timeout)` → `timeout`
  2. `isinstance(exc, requests.ConnectionError)` → `backend_unreachable`
  3. Generic connection/refused/unreachable substring → `backend_unreachable`
  4. Generic timeout/timed substring → `timeout`
  5. Empty/no-content → `empty_response`
  6. JSON/parse delimiters → `invalid_json`
  7. Word-boundary 5xx / internal server / bad gateway / service unavailable → `backend_error`
  8. Everything else → `unknown_error`
- **Tests**: 33/33 worker safety.  1261/1261 full suite.  13/13 run_checks.
  Commit-gate ok=true.
- **Deferred**: M7 cost-estimate credibility, P6-B3-B/H5 MTP endpoint config,
  P5-C V4-Flash polish.  Next recommended: M7 cost-estimate credibility
  read-only audit.  **Do not start M7 implementation without separate approval.**  **Resolved:
  M7 completed v0.10.0-L; see below.**

## M7 Cost-Estimate Credibility — Closeout

- **Chain**: M7 read-only audit → v0.10.0-L.  M7 chain closed.
- **Problem**: `_is_local_provider()` treated LAN-proxy Ollama (192.168.x.x,
  10.x.x.x, 172.16-31.x.x) identically to localhost Ollama — all got
  `estimated_cost_cny=0.0` with no indication that the cost was unknown for
  the remote machine.
- **Fix**: Added execution-location classification without changing any cost
  computation.  Two new additive top-level fields in every ledger record:
  `execution_location` (`local`/`lan`/`remote`/`unknown`) and
  `cost_confidence` (`high`/`medium`/`low`/`none`).
- **New functions**:
  - `classify_execution_location(provider, base_url)` — hostname-based
    classification with RFC-1918 private-IP detection
  - `classify_cost_confidence(execution_location, tokens_estimated,
    has_cost_rate)` — confidence derives from location + token source
  - `breakdown_counts(records, key, default)` — lightweight count-only
    grouping for CLI breakdown display
- **CLI**: `summary` now displays execution-location and cost-confidence
  breakdowns (both table and JSON modes).  New `by-location` subcommand
  using `group_by(records, "execution_location")`.  Old records without
  the new fields display as `unknown`/`none` — no crash, no migration.
- **Contract preserved**: `estimated_cost_cny` unchanged.  `_is_local_provider`
  unchanged.  `record_call()` unchanged.  Worker and debate call sites
  unchanged — the new fields flow through `build_record()` automatically.
  No `LOCAL_LLM_COST_TABLE` expansion.  No dollar cost estimation for LAN.
  `base_url` storage unchanged.
- **Tests**: 32 new tests.  1288/1288 full suite.  13/13 run_checks.
  Commit-gate ok=true.
- **Deferred**: exact LAN dollar cost accounting, cost-table expansion UI,
  streaming cost passthrough (v2-B), cache-tier estimation (v2-C).
  Next remaining: P6-B3-B/H5 MTP endpoint config, P5-C V4-Flash polish.
  **Do not start H5/MTP or P5-C without separate approval.**

## P6-B3-B/H5 Endpoint Resolution Unification — Closeout

- **Chain**: P6-B3-B/H5 read-only audit → v0.10.0-M.  Chain closed.
- **Audit finding**: Worker and debate had independent endpoint resolution
  logic with different fallback chains — debate ignored `LOCAL_LLM_PROVIDER`,
  `--base-url`, and auto-detection.  `_MTP_ENDPOINTS` is display-only and
  does not affect routing or `all_ok`.
- **Fix**: Extracted `_resolve_provider(args_provider)` and
  `_resolve_endpoint(provider, args_base_url)` from worker's `resolve_config()`
  as module-level shared helpers.  Debate now imports and delegates to them.
  Worker `resolve_config()` refactored to call the shared helpers — behavior
  byte-identical.  Debate `resolve_base_url()` now delegates to
  `_resolve_endpoint`.  Debate `--provider` default changed from `"ollama"`
  to `None` to allow `LOCAL_LLM_PROVIDER` env fallthrough.  Added `--base-url`
  CLI flag to debate.
- **Preserved**: Default behavior unchanged — no env vars means ollama +
  localhost:11434 (worker and debate agree).  `_MTP_ENDPOINTS` hardcode
  unchanged.  `ALLOWED_ENV_VARS` unchanged.  Profiles JSON schema unchanged.
  Doctor unchanged.  MCP server endpoint queries unchanged.
- **Tests**: 12 new tests (provider/env/default resolution + args override +
  debate delegation + worker/debate agreement).  1300/1300 full suite.
  13/13 run_checks.  Commit-gate ok=true.
- **Remaining**: P5-C V4-Flash polish — deferred indefinitely (not a v0.10.0
  blocker).  **Do not start P5-C without separate re-authorization.**

## v0.10.0 Active Maintenance Chain — Closeout

- **HEAD**: `55a34b8` (`v0.9.8-14-g55a34b8`), working tree clean.
- **Completed v0.10.0 chain**: C2 (streaming stdout contract) → P6-B2-C
  (call ledger write-failure observability) → M3 (manual call ledger
  rotation) → H6 (classify_error disambiguation) → M7 (cost-estimate
  credibility) → P6-B3-B/H5 (endpoint resolution unification).
- **Validation**: 1300/1300 passed, 13/13 run_checks.  All commit-gate
  reviews passed.
- **P5-C / V4-Flash** is **no longer active v0.10.0 scope**.  Deferred
  indefinitely unless explicitly re-authorized.
- **Next recommended step**: v0.10.0 release-prep read-only audit.
- **Release bump**: `3a704ff` → VERSION bumped to `0.10.0`.  Tag `v0.10.0`
  not yet created — pending release gate (full debate review + release
  auditor on current HEAD).
