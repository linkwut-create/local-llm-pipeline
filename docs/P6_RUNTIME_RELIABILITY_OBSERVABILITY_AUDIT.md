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
| M8 | `local_llm_check` | `run_ollama_list()` subprocess has no timeout — hangs indefinitely if ollama CLI blocks. |

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

*P6-A audit conducted at HEAD `563e284`. P6-A.1 docs-only lock-in.
P6-B1 is NOT authorized by this document and requires separate
approval.*
