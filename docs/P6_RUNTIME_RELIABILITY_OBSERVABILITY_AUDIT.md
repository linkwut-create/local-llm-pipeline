# P6 Runtime Reliability / Observability — Audit

**Status:** P6-A (read-only audit) + P6-A.1 (docs-only boundary lock-in).
Implementation slice P6-B1 has **not** been approved.

**Baseline at audit time:** HEAD `563e284` (`docs: record P5-D closeout
commit`), `git describe v0.9.7-34-g563e284`, VERSION `0.9.7`, no tag at
HEAD, working tree clean. P3 chain closed; P4 chain closed; P5 chain
frozen (P5-C deferred).

---

## 1. P6 in one sentence

P6 audits runtime reliability / observability surfaces across the
worker, MCP server, hook/gate, and telemetry layers, then delivers the
smallest safe slice to fix error-signal propagation so that failures
are correctly classified and observable — **not** a model/provider/
profile/feature expansion.

---

## 2. Hard boundary

P6 is a **runtime observability correction**, not a feature expansion.
Do not add new capabilities; fix the signal chain so existing failures
are correctly reported, classified, and acted upon.

### 2.1 Explicit non-goals

- No model / provider / profile / `_env` work.
- No P5-C revival.
- No router changes.
- No new MCP tool or MCP parameter.
- No ledger schema change.
- No streaming-path redesign.
- No gate state persistence rewrite.
- No auto-worker lifecycle changes.
- No audit event persistence rewrite.
- No VERSION bump, no tag, no release.

### 2.2 Explicitly in scope for P6-B1

1. Fix subprocess timeout propagation in `_wrap_worker_call`
   so `error_type="timeout"` reaches the caller (not
   `worker_failed_no_output`).
2. Ensure timeout reaches `health_store.record_invocation()`
   correctly so profiles are penalized for repeated timeouts.
3. Clear stale `last_timeout` after a subsequent successful
   invocation.
4. Focused regression tests only.

---

## 3. Audit scope

Read-only inspection of 17 files across 4 layers:

| Layer | Files inspected |
|-------|----------------|
| Worker | `tools/local_llm_worker.py` |
| MCP server | `tools/local_llm_mcp_server.py` |
| Hook/Gate | `tools/claude_hooks/mcp_gate.py`, `mcp_auto_worker.py`, `mcp_doctor.py` |
| Observability | `tools/call_ledger.py`, `tools/call_ledger_cli.py`, `tools/health_store.py`, `tools/local_llm_check.py` |
| Supporting | `tools/profile_policy.py`, `tools/local_llm_router.py`, `tools/local_llm_profiles.json`, `tools/local_llm_tasks.json`, `tools/validate_configs.py`, `tools/model_call_result.py`, `tools/call_ledger.py` |

---

## 4. Findings by severity

### 4.1 CRITICAL (6 items)

| ID | Component | Finding | Location |
|----|-----------|---------|----------|
| C1 | `_wrap_worker_call` | Subprocess timeout misreported as `worker_failed_no_output` instead of `timeout`. Defeats quality-escalation downgrade branch and health-store penalty. | `mcp_server.py:1686→1798` |
| C2 | `_wrap_worker_call` | Streaming path: `run_subprocess_streaming` returns `json.dumps(output)` as stdout, then `load_worker_output` searches for `JSON:` markers inside the serialized JSON — never found. The streaming success branch is effectively dead code. | `mcp_server.py:1669,1405,1459` |
| C3 | `mcp_gate.save_state` | Silently swallows all write failures. State changes silently roll back — approval recorded in memory, save fails, next hook event sees "not reviewed." | `mcp_gate.py:569-574` |
| C4 | `mcp_gate.load_state` | Corrupt `state.json` silently returns pristine defaults. All review approvals, dirty-file tracking, per-repo state lost. Doctor `--fix` archives the corrupt file (destructive). | `mcp_gate.py:556-566` |
| C5 | `mcp_auto_worker` | Background worker stdout/stderr piped to DEVNULL. Crash output permanently lost; no component detects "expected output never arrived." | `mcp_auto_worker.py:97-98` |
| C6 | `mcp_gate` | Audit events silently dropped in `_try_audit_event` / `_try_audit_failure`. Commit-gate blocks, bypasses, emergency releases produce zero audit record on write failure. | `mcp_gate.py:678-693` |

### 4.2 HIGH (6 items)

| ID | Component | Finding | Location |
|----|-----------|---------|----------|
| H1 | `mcp_gate` | `run_git()` returns None on any failure with zero diagnostic context. | `mcp_gate.py:374-386` |
| H2 | `health_store` | `last_timeout` is never cleared on subsequent success — stale timeout dates persist indefinitely. | `health_store.py:127-131` |
| H3 | `mcp_auto_worker` | `collect_auto_results()` silently skips corrupt JSON; no skipped-file count exposed. | `mcp_auto_worker.py:256-257` |
| H4 | `mcp_auto_worker` | TOCTOU race on partial write from background worker — read of in-progress write produces silently truncated JSON. | `mcp_auto_worker.py:246-258` |
| H5 | `local_llm_check` | `_MTP_ENDPOINTS` hardcoded — false negatives on any machine other than the designated GPU server. | `local_llm_check.py:29-33` |
| H6 | `classify_error` | Brittle string-substring matching — unrelated exception messages containing `"empty"` / `"json"` / `"connection"` are misclassified. | `worker.py:557-592` |

### 4.3 MEDIUM (8 items)

| ID | Component | Finding |
|----|-----------|---------|
| M1 | `call_ledger` | `record_call()` returns False on failure; all callers ignore the return value. |
| M2 | `call_ledger` | `read_records()` silently skips corrupt JSONL lines; no skip count exposed. |
| M3 | `call_ledger` | No ledger file size management — grows unbounded, no rotation. |
| M4 | `mcp_doctor` | No auto-worker diagnostics — does not check `.local_llm_out/auto/` health or orphaned processes. |
| M5 | `mcp_gate` | `_extract_read_info()` fragile to new MCP response formats — silent false negatives on large-file detection. |
| M6 | `mcp_gate` | `review_tool_succeeded()` false-negative risk on format changes — commits blocked without warning. |
| M7 | `call_ledger` | `estimate_cost_cny()` returns 0.0 for all local providers — paid API proxies on LAN classified as free. |
| M8 | `local_llm_check` | `run_ollama_list()` subprocess has no timeout — hangs indefinitely if ollama CLI blocks. **CLOSED (P6-B3-A):** bounded to 30s via `subprocess.run(..., timeout=30)`; timeout, missing binary, and nonzero-exit each return a failed `CheckResult` instead of hanging or raising. |

### 4.4 LOW (5 items)

| ID | Component | Finding |
|----|-----------|---------|
| L1 | Cross-component | Three-layer silent failure cascade on disk-full: ledger, gate state, health store all degrade silently with zero aggregate diagnostic. |
| L2 | `call_ledger` | `tokens_estimated` flag ambiguous when only one side (input vs output) is estimated. |
| L3 | `call_ledger_cli` | Table formatter truncates fields without indicator (`"..."` not appended). |
| L4 | `health_store` | No validation on `elapsed_s` — negative or absurd values corrupt rolling average. |
| L5 | `mcp_server` | Malformed JSON-RPC receives no error response — MCP client hangs on dropped messages. |

---

## 5. Cross-component themes

1. **Silent failure is the default.** Three independent layers (ledger →
   gate state → health store) all silently degrade on disk-full with zero
   diagnostic signal reaching the operator.

2. **Error classification is brittle and colliding.** `classify_error()`
   uses substring heuristics. `"timeout"` and `"empty_input"` exist in
   both MCP-side and worker-side namespaces with different semantics but
   no disambiguation.

3. **Timeout is systematically mishandled.** Subprocess timeout in all 6
   tools routed through `_wrap_worker_call` is reported as the generic
   `worker_failed_no_output`. This defeats health-store penalty, quality
   downgrade, and operator diagnosis.

4. **State persistence is best-effort and unauditable.** `save_state()`
   and `load_state()` both silently swallow exceptions. No component knows
   whether a state change was actually persisted.

5. **Audit observability has three independent silent-failure paths.**
   `_try_audit_event`, `log_event`, and `record_call` all fail
   independently with zero diagnostics.

---

## 6. P6-B1: Smallest viable implementation slice

P6-B1 fixes the **timeout observability chain** only:

1. **Fix timeout propagation in `_wrap_worker_call`** — subprocess timeout
   must produce `error_type="timeout"`, not `worker_failed_no_output`.

2. **Connect timeout to health store** — `_update_model_health()` must be
   called even when the worker produces no output payload.

3. **Clear stale `last_timeout` on subsequent success** — a successful
   invocation after a timeout must clear the `last_timeout` field so
   callers are not misled by a stale date.

4. **Focused regression tests** — verify timeout signal chain end-to-end
   without changing any other behavior.

### 6.1 Explicitly deferred (not in P6-B1)

| Item | Reason |
|------|--------|
| C2 — streaming double-serialization | Requires redesign of `run_subprocess_streaming` return contract; separate slice |
| C3/C4 — gate state persistence | Hook protocol limitation; requires broader design discussion |
| C5/C6 — auto-worker / audit events | Separate sub-system; not timeout-observability |
| H1 — `run_git()` diagnostics | Separate concern |
| H3/H4 — auto-worker collect/results | Separate sub-system |
| H5 — MTP endpoint config | Separate feature |
| H6 — `classify_error` broad rewrite | Out of scope for P6-B1; C1 fix only needs timeout-path correction, not full reclassification |
| M1–M8 — ledger/local_check/doctor | Separate concerns |
| Error-origin contract field | P6-B1 stays within existing error_type namespace |

### 6.2 Allowed files (P6-B1)

- `tools/local_llm_mcp_server.py` — timeout propagation fix
- `tools/health_store.py` — stale `last_timeout` fix
- `tests/test_p6_timeout_observability.py` — focused tests
- Existing test files if minimally needed

### 6.3 Forbidden files (P6-B1)

`tools/local_llm_worker.py`, `tools/local_llm_router.py`,
`tools/local_llm_check.py`, `tools/call_ledger.py`,
`tools/call_ledger_cli.py`, `tools/local_llm_tasks.json`,
`tools/local_llm_profiles.json`, `tools/profile_policy.py`,
`tools/claude_hooks/`, `CLAUDE.md`, `docs/mcp-task-policy.md`,
`VERSION`, `pyproject.toml`

### 6.4 Behavioral guarantees

- All 9 MCP tools continue to function.
- Non-timeout subprocess failures unchanged.
- P3 escalation chain unchanged.
- Ledger schema unchanged.
- MCP tool count remains 9.
- P4 probe invariants unchanged.

---

## 7. Test plan (P6-B1)

1. Subprocess timeout produces `error_type="timeout"` (not
   `worker_failed_no_output`).
2. Timeout triggers health-store penalty (`consecutive_failures++`,
   `last_timeout` set).
3. Subsequent success after timeout clears `last_timeout`.
4. Non-timeout subprocess failures unchanged (regression).
5. Worker-detected API timeouts (payload with `error_type="timeout"`)
   still propagate correctly (regression).
6. All 9 MCP tools route through `_wrap_worker_call` without
   regression on the non-timeout path.
7. P3 escalation chain: timeout downgrade fires when
   `error_type="timeout"` is correctly propagated.
8. Health-store `record_invocation()` is called even when worker
   produces no output payload.

---

## 8. Risk list

| Risk | Mitigation |
|------|-----------|
| Timeout fix accidentally changes non-timeout error paths | Focused code change + regression tests for `worker_failed_no_output` on genuine non-timeout subprocess failures |
| Health-store `last_timeout` fix breaks existing callers that depend on stale timeout dates | Audit all callers of `get_profile_health()` — expected to be zero stale-timeout callers |
| Scope creep into C2/C3/hook changes | Forbidden-files gate + explicit deferral list |
| Timeout signal now triggers escalation where it previously did not | P3 timeout-downgrade is an unconditional downgrade (lighter model) — safe; the branch was dead code before, now correctly activates |

---

## 9. Task delegation / model allocation

- **Claude Code / Codex**: inspect source files, implement the
  timeout-propagation fix in `_wrap_worker_call`, implement the
  `last_timeout` fix in `health_store.py`, write focused tests,
  run full regression, commit if clean.
- **local-llm-pipeline MCP**: `local_summarize_file` on
  `mcp_server.py` (>200 lines, mandatory before edit);
  `local_generate_test_plan` for timeout-observability changes;
  `local_review_diff(commit_gate=true)` on the full diff;
  `local_debate_review_diff(fast=true)` only if reviewer reports
  blocker or scope creeps into forbidden files.

---

## 10. Stop conditions

1. Scope creeps beyond the three P6-B1 items.
2. Diff touches any forbidden file.
3. `len(mcp.TOOLS)` drifts away from 9.
4. P3 escalation behavior changes (beyond the already-dead timeout
   branch becoming correctly active).
5. Ledger schema changes.
6. Anyone proposes making timeout fix a general error rewrite.

---

*P6-A audit conducted at HEAD `563e284`. P6-A.1 docs-only lock-in.*

---

## 11. Resolution / Closeout (recorded at P6-B1.2)

P6-B1 (`4fcd83a`) implemented the timeout observability slice:

- **C1 fixed**: `_wrap_worker_call` (both streaming and non-streaming paths)
  detects subprocess timeout before `coerce_failure_response` via
  `"timed out" in result["stderr"].lower()` and returns
  `error_type="timeout"` instead of `worker_failed_no_output`.
- **Health-store penalty connected**: `_update_model_health` is called
  with `error_type="timeout"` even when the worker produces no payload.
  Profile name is extracted from the worker command line via new
  `_extract_profile_from_cmd` helper.
- **H2 fixed**: `tools/health_store.py` now clears `last_timeout` on
  subsequent success (`ok=True`). Previously `setdefault` locked the
  stale value indefinitely. Non-timeout failure preserves `last_timeout`.
- **Tests**: `tests/test_p6_timeout_observability.py` (15 tests) +
  updated `tests/test_health_store.py` (split obsolete test into two).
  Full regression: 354 passed across 7 suites.

P6-B1.1 (`a5637ee`) test hygiene:
- Removed fragile working-tree-diff boundary test and broad
  `_P6_B1_ALLOWED` exemption from `tests/test_p5_v4_flash_experimental.py`.
- 15 static P5 invariant tests retained.

### Remaining P6 findings — explicitly deferred

| ID | Finding | Reason |
|----|---------|--------|
| C2 | Streaming JSON double-serialization | Requires redesign of `run_subprocess_streaming` return contract |
| C3/C4 | Gate state save/load silent failure | Hook protocol limitation; broader design needed |
| C5/C6 | Auto-worker / audit event observability | Separate sub-systems; not timeout-observability |
| H1 | `run_git()` no diagnostic context | Separate concern |
| H3/H4 | Auto-worker collect/results TOCTOU | Separate sub-system |
| H5 | `_MTP_ENDPOINTS` hardcoded | Separate feature |
| H6 | `classify_error` string heuristic brittleness | Broader rewrite; C1 fix addressed only timeout path |
| M1–M8 | Ledger/local_check/doctor items | Separate concerns |

### P6-B2 — recommended but NOT authorized

Recommended next slice: **call_ledger observability** — corrupt JSONL
line count/reporting (M1/M2 from P6-A). Smallest viable change:
`read_records()` exposes skip count; `call_ledger_cli.py` reports it.
Requires separate approval.

### P6-B2-A (completed `ec74898`): read diagnostics signal source

Added `read_records_with_diagnostics()` to `tools/call_ledger.py`. Returns
`{records, total_lines, empty_lines, malformed_json_lines, non_dict_lines,
skipped_lines, errors}`. Errors bounded to 20 entries.
`read_records()` unchanged. 8 focused tests. 217 passed regression.

### P6-B2-B (completed `63693c7`): CLI operator-visible reporting

Added `--diagnostics` flag to `call_ledger_cli.py`. `summary` command
displays skipped/corrupt line counts and error examples. JSON output
wraps summary + diagnostics in combined object with `_diagnostics`
sub-key. Default output unchanged without flag. 5 CLI tests. 222 passed.

### P6-B2-C (deferred / not authorized)

Write-failure propagation: `record_call()` return value ignored by
worker (`_emit_ledger`) and debate (`_emit_debate_round_ledger`).
Requires separate design. Not authorized.

### P6-B3 — read-only audit of `local_llm_check` (baseline `3680464`)

Audit re-scoped `tools/local_llm_check.py` for blocking subprocess
calls. Re-confirmed M8: `run_ollama_list()` uses
`subprocess.check_output(["ollama", "list"], …)` with no `timeout=`
kwarg, so if the ollama CLI hangs (network stall, broken pipe,
upstream daemon deadlock) the health check itself wedges, and any
caller — including `build_probe_report()` and the auto-invocation
SessionStart `local_check` — blocks indefinitely.

Recommended smallest viable slice: **P6-B3-A — timeout-only fix on
`run_ollama_list()`**, with explicit deferral of MTP endpoint
hardcoding, `all_ok` semantics, P4 probe contract changes, and
`recommend_profiles()` silent-failure cleanup.

### P6-B3-A (completed `bfe537e`): bounded `ollama list` subprocess

- `tools/local_llm_check.py::run_ollama_list()` signature changes from
  `()` to `(timeout: int = 30)`.
- Replaces `subprocess.check_output(["ollama", "list"], text=True,
  stderr=subprocess.DEVNULL)` with
  `subprocess.run(["ollama", "list"], capture_output=True, text=True,
  timeout=timeout)`.
- `TimeoutExpired` → `CheckResult("ollama_list", False,
  "ollama list timed out after 30s")`.
- `FileNotFoundError` → `CheckResult("ollama_list", False,
  "ollama binary not found")`.
- Nonzero exit → `CheckResult("ollama_list", False,
  "ollama list failed: <stderr or exit code>")`.
- Existing parse path (skip header, take first whitespace token per
  line) and the trailing `except Exception` fallback are preserved.
- Sole caller (`build_probe_report()` at `local_llm_check.py:447`)
  uses no argument — default 30s applies, fully backward compatible.
- 4 new tests in `tests/test_check.py` (ok / timeout / missing binary /
  nonzero exit) → 10 passed for the file.
- Regression: 180 passed across `tests/test_p4_worker_pool_dry_run.py`,
  `tests/test_p5_v4_flash_experimental.py`,
  `tests/test_p6_timeout_observability.py`, `tests/test_call_ledger.py`.
- M8 row above marked **CLOSED (P6-B3-A)**.

### P6-B3-B (deferred / not authorized)

MTP endpoint hardcoding / false-positive risk
(`tools/local_llm_check.py::_MTP_ENDPOINTS` pinned to one host).
Unreachable endpoints inflate failure counts for environments that do
not run MTP. Out of scope for P6-B3. Requires a separate design
covering: configuration surface (env var? CLI flag? auto-detection?),
interaction with `build_probe_report()` schema and `all_ok` semantics,
and the boundary against turning a reliability fix into a
configuration-system expansion. Specifically excluded from this slice:

- No `LOCAL_LLM_MTP_ENDPOINTS` environment variable.
- No `--skip-mtp` CLI flag.
- No host auto-detection.

### Remaining P6 findings — explicitly deferred (reaffirmed at P6-B3-A.1)

- P6-B2-C — write-failure propagation (`record_call()` return ignored).
- C2 — streaming JSON double-serialization.
- C3 / C4 — gate state save/load silent failure.
- C5 / C6 — auto-worker and audit event observability.
- H1 — `run_git()` no diagnostic context.
- H3 / H4 — auto-worker collect/results TOCTOU.
- H6 — `classify_error` string heuristic brittleness.
- M3 — `call_ledger` file size management / rotation.
- M4 — `mcp_doctor` auto-worker diagnostics.
- M5 — `mcp_gate::_extract_read_info` MCP-format fragility.
- M6 — `mcp_gate::review_tool_succeeded` format-change false negatives.
- M7 — `call_ledger::estimate_cost_cny` LAN-proxy classification.
- P5-C — `_env` wiring / model warmup / per-profile provider hint.

H5 (MTP endpoint hardcoding) is **the same item as P6-B3-B** above —
explicitly deferred under that name from the P6-B3 audit.

### Boundaries reaffirmed

- No router / worker / ledger schema / hooks changes in any P6-B slice.
- No MTP endpoint configuration surface anywhere in P6-B3.
- MCP tool count = 9. P4 probe invariants unchanged.
- VERSION = `0.9.7`. No tag, no release.

---

## 12. P6 phase closeout (recorded at P6-C)

**P6 chain closed.** Sequence:
P6-A → P6-A.1 → P6-B1 → P6-B1.1 → P6-B1.2 → P6-B2-A → P6-B2-B →
P6-B2-D → P6-B3 → P6-B3-A → P6-B3-A.1 → P6-C.

### 12.1 Phase result — what P6 actually fixed

| Finding | Status | Slice | Commit |
|---------|--------|-------|--------|
| C1 — subprocess timeout misclassified as `worker_failed_no_output` in `_wrap_worker_call` (streaming + non-streaming) | Fixed | P6-B1 | `4fcd83a` |
| H2 — `health_store.last_timeout` never cleared after later success | Fixed | P6-B1 | `4fcd83a` |
| M1 — `read_records()` silently skips corrupt JSONL lines, no count exposed | Fixed (signal source) | P6-B2-A | `ec74898` |
| M2 — operator has no visibility into ledger read skips | Fixed (CLI surface) | P6-B2-B | `63693c7` |
| M8 — `run_ollama_list()` subprocess unbounded, health check can wedge | Fixed | P6-B3-A | `bfe537e` |

Plus three docs/status closeouts (P6-B1.2 / P6-B2-D / P6-B3-A.1) and
one test hygiene cleanup (P6-B1.1, `a5637ee`).

### 12.2 Explicitly frozen / deferred at P6-C

| Item | Reason for deferral |
|------|---------------------|
| P6-B2-C | Write-failure propagation — `record_call()` return ignored by `_emit_ledger` and `_emit_debate_round_ledger`. Requires separate caller-side propagation design. |
| P6-B3-B (= H5) | MTP endpoint hardcoding — would introduce a configuration surface (env var? CLI flag? auto-detection?). Out of scope for reliability fixes. |
| C2 | Streaming JSON double-serialization — requires `run_subprocess_streaming` return contract redesign. |
| C3 / C4 | Gate state save/load silent failure — hook protocol limitation; broader design needed. |
| C5 / C6 | Auto-worker and audit event observability — separate sub-systems. |
| H1 | `run_git()` has no diagnostic context — separate concern. |
| H3 / H4 | Auto-worker collect/results TOCTOU — separate sub-system. |
| H6 | `classify_error` string-heuristic brittleness — broader rewrite; C1 fix only addressed the timeout path. |
| M3 | `call_ledger` file size management / rotation. |
| M4 | `mcp_doctor` auto-worker diagnostics. |
| M5 | `mcp_gate::_extract_read_info` MCP-format fragility. |
| M6 | `mcp_gate::review_tool_succeeded` format-change false negatives. |
| M7 | `call_ledger::estimate_cost_cny` LAN-proxy classification. |
| P5-C | `_env` wiring / model warmup / per-profile provider hint. |

### 12.3 Release status

- VERSION remains `0.9.7`.
- HEAD carries no tag.
- No release. No zip.

### 12.4 Possible future directions (none authorized by P6-C)

- **P7** — read-only audit of remaining hook/gate observability surfaces
  (C3/C4/C5/C6, M4/M5/M6) following the same audit-first / smallest-slice
  pattern used in P3-A / P4-A / P5-A / P6-A.
- **P6-B2-C design-only planning** — propose a caller-side
  write-failure propagation strategy without implementation.
- **P6-B3-B design-only planning** — propose an MTP endpoint
  configuration surface design without implementation.
- **Release prep** — only if explicitly approved; would include
  VERSION bump, tag, and zip.

Each requires a separately approved plan; none are started by P6-C.

*P6 closeout reference; superseded for ongoing work by P7-A audit and P7-B bundle below.*

---

## 13. P7-A grouped audit + P7-B bundled implementation

### 13.1 P7-A audit (baseline `9d8af1d`)

Read-only audit of every P6-deferred item, grouped by risk +
subsystem + compatibility impact. Inspected 8 source files:
`tools/claude_hooks/{mcp_gate,mcp_auto_worker,mcp_doctor}.py`,
`tools/local_llm_mcp_server.py`, `tools/local_llm_check.py`,
`tools/call_ledger.py`, `tools/local_llm_worker.py`,
`tools/local_llm_debate.py`.

**Group A — hook silent persistence (diagnostics-friendly, no behavior change):**
C3 (`load_state` swallow), C4 (`save_state` swallow), C5/C6 (4 spawn
paths in `mcp_auto_worker.py` swallow), M4 (doctor never inspects
`.local_llm_out/auto/`).

**Group B — MCP response parsing visibility (diagnostics-only sliver):**
M5 (`_extract_read_info` silently returns `(None, None)` on unknown
shapes), M6 (`review_tool_succeeded` silently returns False).

**Group C — runtime contract changes (isolated, deferred):**
C2 (`stdout=json.dumps(output, …)` at `mcp_server.py:1417` — fixing
breaks all 8 worker-backed MCP tool callers), H6 (`classify_error`
substring ordering is load-bearing — shifts ledger `error_type`
distribution).

**Group D–H — design-surface items (postponed long-term):**
P6-B2-C (`record_call()` write-failure propagation — explicit design
intent against), M3 (ledger rotation — no `MAX_LEDGER_SIZE` constant
exists), M7 (`estimate_cost_cny` LAN-proxy classification — LAN at
`193.168.2.2` looks "local" by IP), P6-B3-B/H5 (`_MTP_ENDPOINTS`
hardcoded — **note: MTP results are display-only, NOT folded into
`all_ok` at `local_llm_check.py:508`**).

**Group I — feature carryover (on-demand only):** P5-C.

**Verdict:** bundle Group A + Group B sliver + M4 as **P7-B
"Hook silent-failure diagnostics"** — all share the
"log silent failure, return same value" pattern. Reject any bundling
of Groups C/D for this slice.

### 13.2 P7-B bundled implementation

| # | Item | File | Mechanism |
|---|------|------|-----------|
| 1 | C3 — state load failure visible | `tools/claude_hooks/mcp_gate.py::load_state` | On `except`, `log_event(config_dir, {"event":"state_load_failed", "error_type":…, "error":…})`. Return value (`_STATE_DEFAULTS`) unchanged. |
| 2 | C4 — state save failure visible | `tools/claude_hooks/mcp_gate.py::save_state` | On `except`, `log_event(config_dir, {"event":"state_save_failed", …})`. Return value unchanged. |
| 3 | C5/C6 — spawn failure visible | `tools/claude_hooks/mcp_auto_worker.py` (4 spawn paths) | New `_record_spawn_failure(repo_root, fn, cmd, error)` helper writes one JSONL line per failure to `.local_llm_out/auto/_spawn_failures.log`. Self-truncates at 1 MB. Helper itself swallows all exceptions. Fire-and-forget preserved. |
| 4 | M4 — doctor auto-worker checks | `tools/claude_hooks/mcp_doctor.py::run_checks` | 3 additive checks: `auto_dir_present` (WARN on missing, OK on present), `auto_results_count` (OK / WARN at >50), `spawn_failures_log` (OK absent/empty, WARN non-empty, FAIL >1 MB). No existing-check semantics changed. |
| 5 | M5/M6 — unknown MCP shape warning | `tools/claude_hooks/mcp_gate.py::_extract_read_info`, `review_tool_succeeded` | Add optional `config_dir` parameter (default `None`). On unrecognized non-empty `tool_response`, call new `_log_mcp_shape_unknown(config_dir, payload, reason=…)`. Reasons: `no_known_read_shape` / `empty_text_from_nonempty_response` / `text_not_json` / `result_not_dict`. Return values preserved bit-for-bit. Legacy callers (no `config_dir`) remain purely passive. |

### 13.3 Behavior preservation contract (P7-B invariants)

- `load_state(config_dir)` returns the same dict for the same input
  state file content (corrupt → defaults).
- `save_state(config_dir, state)` has no return value and writes the
  same bytes on success; on failure it remains silent to its caller.
- `spawn_background` / `spawn_local_check` / `spawn_summarize_file` /
  `spawn_review_diff` remain fire-and-forget. Failures do not raise.
- `_extract_read_info(payload)` (no `config_dir`) returns the exact
  same `(file_path, num_lines)` tuple as before.
- `review_tool_succeeded(payload)` (no `config_dir`) returns the exact
  same bool as before.
- `mcp_doctor.run_checks` adds three new check entries to the results
  list; existing entries are unmodified in count, name, and status
  semantics.
- No new MCP tool, no new CLI flag, no `VERSION` bump, no tag, no
  release.

### 13.4 Forbidden files (zero diff)

`tools/local_llm_mcp_server.py`, `tools/local_llm_worker.py`,
`tools/local_llm_debate.py`, `tools/local_llm_router.py`,
`tools/call_ledger.py`, `tools/call_ledger_cli.py`,
`tools/health_store.py`, `tools/local_llm_check.py`,
`tools/local_llm_profiles.json`, `tools/local_llm_tasks.json`,
`CLAUDE.md`, `docs/mcp-task-policy.md`, `VERSION`.

### 13.5 Items remaining deferred after P7-B

| Item | Reason |
|------|--------|
| C2 | Streaming double-serialization — fixing changes the `stdout` field's contract for every MCP tool that consumes it. |
| H6 | `classify_error` substring matching — fixing shifts ledger `error_type` distribution. |
| P6-B2-C | Write-failure propagation — has explicit "must never crash the call" design intent. |
| M3 | Ledger rotation — no archive layout decided. |
| M7 | Cost-estimate accuracy — needs LAN-vs-local distinguisher. |
| P6-B3-B / H5 | MTP endpoint hardcoding — pure display-only today; fixing introduces config surface. |
| P5-C | Feature carryover — only on demand. |

### 13.6 Release status

- VERSION remains `0.9.7`.
- HEAD carries no tag.
- No release. No zip.

### 13.7 Possible future directions (none authorized by P7-B)

- **P7-C closeout** — docs-only retrospective entry once P7-B is
  observed in production for some time.
- **P6-B2-C / P6-B3-B design-only planning** — produce a proposal
  document, no code.
- **P7-D streaming contract correction (C2)** — only if explicitly
  approved; high blast radius across all 8 worker-backed MCP tools.

*Last updated: P7-B bundle, HEAD pending commit. P6-A audit baseline `563e284`; P6-B3 audit baseline `3680464`; P7-A audit baseline `9d8af1d`.*
