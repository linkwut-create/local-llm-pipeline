# P4 Worker Pool Dry-Run — Plan

**Status:** P4-A (read-only audit + boundary lock-in). Implementation
slice P4-B has **not** been approved.

**Baseline at audit time:** HEAD `f896555` (`docs: close out P3 cost
discipline chain`), `git describe v0.9.7-27-gf896555`, VERSION
`0.9.7`, no tag at HEAD, working tree clean. P3 chain closed; P3-C3
skipped/deferred.

---

## 1. P4 in one sentence

P4 adds a **dry-run / probe-only** worker-pool readiness path so the
operator can see whether an additional worker host (e.g. AI Max 2) is
reachable, without changing routing, dispatching real tasks, or
introducing background/daemon behavior.

## 2. Hard boundary (frozen by P4-A)

P4 is a **diagnostic capability**, not a distributed scheduler. The
following are out of scope for the entire P4 chain (P4-A through any
P4-N) and may only be revived under a separately approved plan:

- Changing routing decisions or profile selection (Path A in
  `docs/MCP_COST_DISCIPLINE_PLAN.md` §4.3 stays untouched).
- Adding automatic multi-host execution / cross-machine task dispatch.
- Running a scheduler, queue, daemon, persistent background worker, or
  any process not bound to a single foreground invocation.
- Subprocess-based remote execution against the second host.
- Adding ledger schema fields (the `worker_id` slot already lives in
  `KNOWN_EXTRA_KEYS` and stays unused for P4).
- Persisting worker-pool state beyond an in-memory probe response.
- Mutating `tools/local_llm_profiles.json`, `tools/local_llm_router.py`,
  `tools/local_llm_mcp_server.py` routing helpers, or the call ledger.
- Cross-machine tensor parallelism / unified VRAM (already non-goal in
  `docs/MCP_COST_DISCIPLINE_PLAN.md` §2.1).
- V4-Flash local runtime provisioning (already non-goal in §2.2).
- Any tag / release / `VERSION` bump.

If P4 implementation work starts trending toward any of these, the
work must stop and be re-planned.

## 3. Current architecture findings (read-only audit)

### 3.1 Health-check surface

- `tools/local_llm_check.py` (394 lines) — CLI entry point. Already
  probes Ollama (`check_ollama`, default `http://localhost:11434`),
  the OpenAI-compatible server (`check_openai_compat`,
  `http://localhost:8080`), and three llama.cpp MTP endpoints on
  zero12 via a hardcoded list:
  - `tools/local_llm_check.py:28` `_MTP_ENDPOINTS` (zero12 Gemma4-26B-MTP,
    Qwen3.6-27B-MTP, Qwen3.6-35B-MoE-MTP).
- `check_mtp_endpoints()` (`tools/local_llm_check.py:162`) already
  returns per-endpoint reachability records with a 5s timeout.
- Output is pretty-printed for humans only — no JSON / structured-data
  surface today.

### 3.2 MCP `local_check` wrapper

- `call_local_check` (`tools/local_llm_mcp_server.py:1926`) shells out
  to `local_llm_check.py` and returns `{stdout, stderr}` truncated to
  10 000 / 5 000 chars. There is **no structured `probe_result` shape**
  surfaced through MCP today.
- Registered in `tools/local_llm_mcp_server.py:769` (TOOLS) and
  `:2463` (dispatch table); tested by
  `tests/test_mcp_server.py:125 test_call_local_check_no_models` and
  `:432 / :442` (handler dispatch).

### 3.3 Profiles, router, base-URL resolution

- `tools/local_llm_profiles.json` defines per-profile `model`,
  `candidates`, `temperature`, etc. — **no per-profile `host` /
  `worker_id` / `base_url` field**.
- Endpoint resolution is a single global URL chain:
  `LOCAL_LLM_BASE_URL` → `OLLAMA_HOST` → `http://localhost:11434`
  (`tools/local_llm_check.py:35 resolve_ollama_base_url`,
  `tools/local_llm_worker.py:854-857`).
- `tools/local_llm_router.py` does **not** know about a worker pool;
  routing keys are `(task, profile, health)` only. `is_profile_healthy`
  reads `health_store` (P1-H runtime store).
- `_resolve_starting_profile` (`tools/local_llm_mcp_server.py:224`) is
  the Path A pre-call routing helper. **P4 must not touch it.**

### 3.4 Ledger fields

- `tools/call_ledger.py:74-75` `KNOWN_EXTRA_KEYS` already lists
  `worker_id` and `host`. They are allowlisted but **no current call
  site stamps them**. Re-confirmed by grep: only the test fixtures
  and the plan doc reference `worker_id`.
- Decision: P4 should **not** start populating `worker_id` /
  `host` in the ledger. That stamping is part of a future,
  separately approved phase. Adding it now would silently couple
  probe results to the ledger and create the "scheduler" footprint we
  want to avoid.

### 3.5 Existing tests around the surface P4 would touch

- `tests/test_mcp_server.py` — tools list, dispatch, `call_local_check`
  smoke (no live process).
- `tests/test_router_profiles.py` — routing/profile resolution.
- `tests/test_call_ledger.py` — `worker_id` / `host` already covered
  in `KNOWN_EXTRA_KEYS` round-trip (lines 295, 332).
- **Gap:** `_MTP_ENDPOINTS` reachability and `check_mtp_endpoints`
  have no dedicated unit test today.

### 3.6 Stale wording inventory

The following references should be re-read at P4-B time but are
**not** edited in P4-A:

- `docs/MCP_COST_DISCIPLINE_PLAN.md:42` ("AI Max 2 — Future second
  worker"), `:321-336` ("Worker Pool Direction (sketch...)"),
  `:365` (§10 P4 row), `:551-553` (§13.5 P4 bullet).
- `PROJECT_STATUS.md` line 33 (`P4 | Not started | Worker pool
  dry-run.`).
- `CLAUDE.md` does not mention P4; no edit needed in P4-A.

## 4. Non-goals (restated explicitly)

P4 will **not**:

1. Add a `worker_pool` runtime, queue, or scheduler module.
2. Spawn background processes, daemons, or service loops.
3. Mutate `tools/local_llm_profiles.json` to add per-profile hosts.
4. Touch `tools/local_llm_router.py` routing decisions or
   `_resolve_starting_profile` content-pattern routing.
5. Change `tools/call_ledger.py` schema, `KNOWN_EXTRA_KEYS`, or the
   CLI surface.
6. Add MCP tools beyond extending the existing `local_check`
   contract (the 9-tool count in `tests/test_mcp_server.py` must
   stay at 9 unless a separate plan approves a new tool).
7. Persist any worker-pool state across invocations beyond what
   `health_store` already records for the primary worker.
8. Implement cross-machine sharding or tensor parallelism (§2.1
   non-goal preserved).
9. Bump `VERSION`, create a tag, or cut a release.

## 5. Proposed P4-B implementation slice (smallest viable)

P4-B (still requires separate approval — **do not implement during
P4-A**) should be the narrowest possible change to surface a
structured probe result:

### 5.1 Surface design

Extend `tools/local_llm_check.py` with an **opt-in flag** that emits a
JSON dry-run probe report alongside the existing human-readable
output:

```
python tools/local_llm_check.py --probe-workers --json
```

Reasoning:

- `--probe-workers` is **off by default**. The default path (no flag)
  preserves byte-for-byte current behavior, including all 30
  `mcp_doctor` checks that depend on it.
- `--json` is **also off by default**. Existing callers (MCP
  `call_local_check`, the doctor) keep reading pretty stdout.
- The MCP wrapper `call_local_check` is **not** changed in P4-B; it
  continues to forward stdout/stderr. The structured surface stays
  CLI-only at first so MCP / hook auto-invocation pathways do not
  silently activate probing.

### 5.2 Proposed dry-run probe payload

When `--probe-workers --json` is set, emit (to stdout, single JSON
object, last line):

```json
{
  "schema_version": 1,
  "worker_pool_dry_run_enabled": true,
  "configured_workers": [
    {"id": "ai_max_1_ollama", "host": "...", "endpoint_type": "ollama"},
    {"id": "ai_max_1_mtp_gemma4_26b", "host": "...", "endpoint_type": "llama_cpp_mtp"},
    ...
  ],
  "reachable_workers": ["ai_max_1_ollama", ...],
  "unreachable_workers": [],
  "probe_errors": [{"id": "...", "error": "..."}],
  "routing_changed": false,
  "ledger_stamped": false,
  "probed_at": "2026-05-22T...Z"
}
```

Hard rules baked into the payload:

- `routing_changed` is the literal boolean `false`. It exists in the
  schema so any future "did we route to a different worker?" question
  has a clear, machine-checkable "no" today.
- `ledger_stamped` is the literal boolean `false`. P4 does not write
  to the ledger.
- `configured_workers` is derived from existing config sources
  (`_MTP_ENDPOINTS`, resolved Ollama URL, optional `LOCAL_LLM_WORKERS`
  env if introduced later — but env var introduction itself is a
  separate decision deferred out of P4-A).
- No per-worker model list — probing reachability, not capability.

### 5.3 Configuration source

For the **first** P4-B slice, "configured workers" come from
read-only sources that already exist:

- `_MTP_ENDPOINTS` constant in `local_llm_check.py`.
- Resolved Ollama base URL.
- Resolved OpenAI-compat base URL.

A configurable list (env var or JSON) is **explicitly deferred** to a
later P4 slice. P4-B's job is to surface the existing probe as
structured data, not to add new config surface.

### 5.4 Files touched in P4-B (proposed)

- `tools/local_llm_check.py` — add `--probe-workers` / `--json` flags,
  factor out a `build_probe_report()` helper, emit JSON when both
  flags set. Single file; ~80 lines of net additions.
- `tests/test_local_llm_check.py` (new) — unit tests for
  `build_probe_report()`, `--json` emission, default-path invariance
  (no behavioral change when flags absent), and the
  `routing_changed=false` / `ledger_stamped=false` invariants.
- `docs/P4_WORKER_POOL_DRY_RUN_PLAN.md` — update the §5 slice to
  reflect what shipped.
- `PROJECT_STATUS.md` / `CHANGELOG.md` — record P4-B.

**Files explicitly NOT touched in P4-B:**

- `tools/local_llm_router.py` (routing untouched)
- `tools/local_llm_mcp_server.py` (MCP surface untouched)
- `tools/call_ledger.py` / `tools/call_ledger_cli.py` (ledger
  untouched)
- `tools/local_llm_profiles.json` (profiles untouched)
- `tools/local_llm_worker.py` (worker untouched)
- `tools/health_store.py` (telemetry untouched)
- `CLAUDE.md` (policy untouched; no new participation rules)
- `docs/mcp-task-policy.md` (untouched)
- `VERSION` / tags / release notes (no release)

### 5.5 Test plan for P4-B (proposed; do not write in P4-A)

1. `build_probe_report()` returns a dict with the seven top-level
   keys above, in that exact shape.
2. `routing_changed` is always `False` regardless of probe outcomes.
3. `ledger_stamped` is always `False` regardless of probe outcomes.
4. Unreachable endpoints land in `unreachable_workers` with a matching
   `probe_errors` entry; reachable ones land in `reachable_workers`
   and do not appear under `unreachable_workers`.
5. Default-path invariance: running `local_llm_check.py` with no
   flags produces byte-identical stdout vs the pre-P4-B build (snapshot
   or regex match on the section banners).
6. `--json` without `--probe-workers` does not emit a probe report
   (probe is gated only on the explicit flag).
7. MCP `call_local_check` smoke (`tests/test_mcp_server.py`) still
   passes unchanged — no MCP-side modification.
8. Ledger emission tests
   (`tests/test_call_ledger.py::test_known_extra_keys_roundtrip` etc.)
   still pass — `worker_id` / `host` remain unstamped.
9. Router/profile tests
   (`tests/test_router_profiles.py`) still pass — no routing change.

### 5.6 Review gate

P4-B is a `tools/local_llm_check.py` change. Per CLAUDE.md
MCP-USAGE-RETRO-1 #3, this file is **not** in the must-debate
categories (hook/gate/MCP server/router/safety policy/DB schema/audit
infra/release boundaries). `local_review_diff(commit_gate=true)`
suffices; `local_debate_review_diff(fast=true)` only triggers if a
reviewer reports a blocker or the diff bleeds into router/MCP server
files.

## 6. Risk list

| Risk | Mitigation |
|------|------------|
| Scope creep from "probe" into "schedule" | §2 / §4 non-goals are frozen in this doc and must be cited in P4-B PR description. Any deviation requires a new plan. |
| Adding `worker_id` / `host` stamping by reflex | P4-B test #3 asserts `ledger_stamped=False`. P4 may not introduce any new ledger call site. |
| MCP-side auto-invocation hooks accidentally start probing | P4-B does not modify `tools/claude_hooks/` or auto-worker code. The probe flag is CLI-opt-in. |
| Performance regression in default `local_check` path | P4-B test #5 enforces default-path invariance. The probe is behind a flag. |
| Probe leaks into routing decisions | P4-B does not touch `_resolve_starting_profile` or `is_profile_healthy`. Test #9 keeps router behavior pinned. |
| Doctor (`mcp_doctor.py`) breaks because it relies on current `local_check` stdout shape | P4-B's default path is byte-identical (test #5). Doctor is not retargeted at the JSON surface in this slice. |
| Hardcoded `_MTP_ENDPOINTS` becomes stale | Out of scope for P4-B; addressed only if a later slice introduces a configurable list. |
| Plan grows into V4-Flash provisioning | §2.2 non-goal preserved; V4-Flash is a separate workstream. |

## 7. P4 sub-phase split

| Sub-phase | Status | Scope |
|-----------|--------|-------|
| **P4-A** | Done | Read-only audit + boundary lock-in. Docs-only. No runtime / test / profile / ledger / VERSION / tag changes. |
| **P4-B** | Done | Smallest viable implementation slice per §5 shipped: `--probe-workers` / `--json` flags + `build_probe_report()` + `PROBE_REPORT_SCHEMA_VERSION = 1` in `tools/local_llm_check.py`; 32 new tests in `tests/test_p4_worker_pool_dry_run.py`. Default invocation unchanged. MCP `call_local_check` contract unchanged. `routing_changed` / `ledger_stamped` literal `False`. |
| **P4-C** | **Skipped / deferred (optional)** | Configurable worker list (env var / JSON). Not required for the P4 core objective ("probe-only diagnostic, no scheduling"). May be revived only under a separately approved plan that re-cites §2 / §4 / §6 / §8. |
| **P4-D** | **Done** (this entry) | Docs/status closeout for the P4 chain. See §7.2 below. |

### 7.1 P4-B landed surface (recap)

- New CLI flags on `tools/local_llm_check.py`:
  - `--probe-workers` (off by default) — runs the probe.
  - `--json` (off by default) — switches to JSON output; only honored
    with `--probe-workers`.
- New helper `build_probe_report(probe_timeout: float = 5.0) -> dict`
  with the contract shape recorded in §5.2.
- New module-level constant `PROBE_REPORT_SCHEMA_VERSION = 1` so
  consumers can pin against the schema.
- No changes to `tools/local_llm_mcp_server.py`,
  `tools/local_llm_router.py`, `tools/call_ledger.py`,
  `tools/call_ledger_cli.py`, `tools/local_llm_profiles.json`,
  `tools/local_llm_worker.py`, `tools/health_store.py`, or
  `tools/claude_hooks/`.
- Live probe in the current zero12 environment yields 5 configured
  workers (1 ollama + 1 openai_compat + 3 llama_cpp_mtp), with
  `routing_changed: false` / `ledger_stamped: false` in the JSON
  payload as required.

P4-B did not authorize P4-C. Any P4-C work (env var / JSON
configuration surface) must re-cite this §2 / §4 / §6 set verbatim.

### 7.2 Resolution / Closeout (recorded at P4-D)

**P4 chain is closed.** Final state:

| Sub-phase | Outcome |
|-----------|---------|
| P4-A | Done (`212428e`) — read-only audit and boundary lock-in. |
| P4-B | Done (`1e68dc3`) — CLI-opt-in JSON probe surface in `tools/local_llm_check.py`. |
| P4-C | Skipped / deferred — configurable worker list is **not** required for the P4 core objective. |
| P4-D | Done (this entry) — docs/status closeout. |

What landed (from P4-B, recapped here for the close-out reader):

- `tools/local_llm_check.py --probe-workers --json` emits a single
  JSON object with `PROBE_REPORT_SCHEMA_VERSION = 1` and the
  contract shape from §5.2.
- `--probe-workers` alone appends a human-readable "Worker Pool
  Dry-Run Probe (diagnostic only)" section to the existing health
  check.
- `--json` alone is a no-op for probing.
- Default invocation (no flags) is byte-equivalent (modulo
  timestamps) to the pre-P4-B build.
- 32 tests in `tests/test_p4_worker_pool_dry_run.py` pin the shape,
  the reachability bucketing, the four CLI flag combinations, the
  literal-`False` invariants for `routing_changed` and
  `ledger_stamped`, and source-level "no router / no ledger" guards.

The hard boundary established in §2 and §4 was **not** breached
anywhere in the P4 chain. Throughout P4-A → P4-B → P4-D, none of
the following entered the codebase:

- A worker pool runtime, queue, scheduler, daemon, or persistent
  background worker.
- Any automatic multi-host execution / cross-machine task dispatch.
- Subprocess-based remote execution against a second host.
- New ledger schema fields. `worker_id` / `host` remain allowlisted
  in `KNOWN_EXTRA_KEYS` but are still **not stamped** by any call
  site.
- Routing changes. `_resolve_starting_profile`,
  `is_profile_healthy`, `tools/local_llm_router.py`, and Path A /
  Path B / Path D (from `docs/MCP_COST_DISCIPLINE_PLAN.md` §4.3)
  were not touched.
- MCP `call_local_check` contract changes. It still shells out and
  returns `{stdout, stderr}`. The structured probe surface remains
  CLI-only.
- Profile mutations. `tools/local_llm_profiles.json` is unchanged.
- Cross-machine tensor parallelism or unified VRAM.
- V4-Flash local runtime provisioning.
- `VERSION` bumps, tags, or release cuts.

Why P4-C was skipped: the P4 core deliverable is a structured,
diagnostic-only probe surface that an operator can read. P4-B
already provides this. A configurable worker list would introduce
new config semantics (env var or JSON), worker-identity conventions,
precedence rules vs. existing `LOCAL_LLM_BASE_URL` / `OLLAMA_HOST`
resolution, and a likely pull toward stamping `worker_id` in the
ledger — all of which are exactly the "scheduling footprint"
non-goals §2 forbids. Until a concrete operational need for a
second worker host appears, P4-C remains optional.

**Next runway: P5 (V4-Flash local experimental profile)**, starting
from a P5-A read-only audit (mirroring the P3-A / P4-A pattern). If
a real worker-pool configuration need surfaces before P5, P4-C may
be revived — but it requires a separately approved plan that
re-cites §2 / §4 / §6 / §8 verbatim.

## 8. Stop conditions

If during P4-B or later work any of these occur, **stop and escalate
to the human** instead of routing around them:

1. The probe payload needs a field whose name implies routing
   (`selected_worker`, `dispatch_to`, `target_host`, etc.).
2. A reviewer recommends "while we're here, also stamp `worker_id`
   in the ledger."
3. The default (no-flag) `local_llm_check.py` stdout changes in any
   way that breaks `mcp_doctor.py`.
4. The slice grows beyond the files listed in §5.4.
5. Anyone proposes making the probe automatic at SessionStart or any
   hook event.

---

*Last updated: P4-A, HEAD `f896555` baseline.*
