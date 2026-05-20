# MCP Health Telemetry Isolation — Plan (P1-H)

**Status**: planning only. No implementation yet. Gated on user approval.

---

## 1. Problem Statement

`tools/local_llm_profiles.json` is the project's source-of-truth profile
configuration: model assignments, temperatures, `use_for` lists,
`candidates`, `_constraints`, and the static `risk_level` and
`_commit_gate_allowed` fields read by the router, the MCP server, and
the new `profile_policy` helper (P1-A, `b8f681e`).

But the same file also carries dynamic per-call telemetry under each
profile's `_health` block:

```json
"_health": {
  "success_rate": 1.0,
  "avg_latency_s": 3.3,
  "last_timeout": null,
  "consecutive_failures": 0,
  "_updated": "2026-05-19"
}
```

Every non-streaming MCP tool call rewrites these values via
`_update_model_health()` in `tools/local_llm_mcp_server.py`. The
result is that `tools/local_llm_profiles.json` becomes dirty in the
working tree on essentially every Claude Code session — driven by the
auto session-start `local_check`, the PostToolUse summarize/review
auto-hooks, and any manual MCP tool invocation.

Observed consequence during the P1-A commit sequence: we had to
`git checkout -- tools/local_llm_profiles.json` three times to keep
the staged set clean. Every commit going forward will hit the same
friction unless storage is split.

The configuration file should be static; runtime telemetry should
live in a runtime location.

---

## 2. Current Writer / Trigger

| Item | Value |
|------|-------|
| Writer | `tools/local_llm_mcp_server.py::_update_model_health(profile_name, ok, elapsed_s, error_type="")` |
| Writer line range | 550–596 |
| Trigger | `_wrap_worker_call` at line 1539-1545, after worker subprocess returns with `payload` |
| Write mechanism | `json.dump` → `.tmp` → `os.replace` (atomic) |
| Fields written | `success_rate`, `avg_latency_s`, `last_timeout`, `consecutive_failures`, `_updated` |
| Formulas | `success_rate = old*0.9 + (1.0 if ok else 0.0)*0.1`; `avg_latency_s = old*0.9 + elapsed*0.1` |

**Paths that DO NOT write:**

- Streaming `_wrap_worker_call` path (lines 1515-1534) — exits before
  the update.
- Commit-gate fast path in `call_review_diff` (lines 2013-2015) —
  calls `run_subprocess` directly, bypasses `_wrap_worker_call`.
- All non-MCP CLI invocations of `local_llm_worker.py` —
  `_update_model_health` lives only in the MCP server module.

---

## 3. Current Readers

| File | Function | Use |
|------|----------|-----|
| `tools/local_llm_router.py:85` | `is_profile_healthy(name, profiles_data)` | Router skips profile when `consecutive_failures>=2` or `success_rate<0.5` |
| `tools/local_llm_mcp_server.py:428` | `_profile_is_healthy(name)` | MCP-side health gate + llama.cpp endpoint probe |
| `tools/local_llm_router.py:168` | `cmd_health_report()` | CLI `health-report` command |
| `tools/update_profiles_from_ollama.py:179` | `auto_tune_recommendations(...)` | `--auto-tune` candidate latency comparison |
| `tests/test_layer4_quality.py` | five `test_is_profile_healthy_*` cases | Use synthetic in-memory profile dicts — NOT dependent on the JSON file's `_health` |

Health thresholds (`consecutive_failures>=2`, `success_rate<0.5`) and
the 90/10 weighted average formula must be preserved exactly.

---

## 4. Target Design

`tools/local_llm_profiles.json` becomes **static configuration only**.
The `_health` block is removed from every profile (one-time cleanup).

Runtime telemetry moves to a single file:

```
.local_llm_out/local_llm_health.json
```

`.local_llm_out/` is already gitignored (`.gitignore:2`). No new
gitignore entry needed.

**File shape:**

```json
{
  "schema_version": 1,
  "_updated": "2026-05-20",
  "profiles": {
    "<profile_name>": {
      "success_rate": 1.0,
      "avg_latency_s": 3.3,
      "last_timeout": null,
      "consecutive_failures": 0,
      "_updated": "2026-05-20"
    }
  }
}
```

Same field names and types as the current `_health` block — a reader
written against the new file looks structurally identical to a reader
against the current `profile["_health"]`.

**Helper module:** `tools/health_store.py` (new, read-only/write-only
to the runtime file, never touches `local_llm_profiles.json`).

Public surface (locked at plan time):

```python
HEALTH_PATH: Path                                  # .local_llm_out/local_llm_health.json
load_health() -> dict                              # returns full document, {} if file absent
load_profile_health(profile_name: str) -> dict     # convenience accessor; {} if absent
record_invocation(
    profile_name: str,
    ok: bool,
    elapsed_s: float,
    error_type: str = "",
) -> None                                          # the new write path (replaces _update_model_health body)
```

Behavior guarantees:
- `record_invocation` never raises, mirrors current best-effort
  semantics of `_update_model_health`.
- Atomic write via `.tmp` + `os.replace`.
- Reads tolerate missing file (returns `{}`).
- Health document carries `schema_version=1` for forward-compatible
  migration.

---

## 5. Non-Goals

This plan does NOT address:

- Model selection semantics (profile chains, fallback order)
- Health thresholds (`consecutive_failures>=2`, `success_rate<0.5`)
- Weighted-average formula
- Commit gate behavior
- Profile policy helper (`tools/profile_policy.py`) — orthogonal
- SQLite-backed health storage — JSONL/JSON is fine at this scale
- Worker pool (separate plan)
- P2 ledger escalation fields — separate scope
- Cross-host health aggregation — single-host, single-file for now
- Backfill from existing `_health` data — current values are 90/10
  weighted, they re-converge within a handful of calls; not worth the
  migration complexity
- Concurrency safety beyond `.tmp` + `os.replace` — health writes are
  rare enough that a last-writer-wins on the rename is acceptable

---

## 6. Implementation Phases

| Phase | Scope | Risk | Approx. files |
|-------|-------|------|---------------|
| **P1-H.0** | This document. Approve. | none | 1 (this file) |
| **P1-H.1** | `tools/health_store.py` (new helper, no call sites yet). Tests. | low | `tools/health_store.py`, `tests/test_health_store.py` |
| **P1-H.2** | Switch writer + readers to runtime file. One-time `_health` cleanup in `local_llm_profiles.json`. **Behavioral change — requires debate review.** | **medium** | `tools/local_llm_mcp_server.py`, `tools/local_llm_router.py`, `tools/local_llm_profiles.json`, `tests/test_health_telemetry.py` |
| **P1-H.3** | `cmd_health_report` and `auto_tune_recommendations` switched to runtime file. | low | `tools/local_llm_router.py`, `tools/update_profiles_from_ollama.py` |
| **P1-H.4** | Docs closeout. P1-H Completion Notes in this file. CHANGELOG / PROJECT_STATUS. | none | docs only |

Each phase is its own commit. P1-H.2 is the only phase that changes
behavior; all others are additive (P1-H.1) or follow-up (P1-H.3,
P1-H.4).

---

## 7. Tests

New file: `tests/test_health_store.py`.

| Test | Asserts |
|------|---------|
| `test_load_health_missing_file_returns_empty` | Reading without file present returns `{}` |
| `test_record_invocation_creates_file` | First `record_invocation` writes the file |
| `test_record_invocation_round_trip` | Write then `load_profile_health` returns the recorded shape |
| `test_record_invocation_weighted_success_rate` | 90/10 weighting matches the formula from `_update_model_health` |
| `test_record_invocation_weighted_latency` | 90/10 weighting on `avg_latency_s` |
| `test_record_invocation_consecutive_failures_increment` | `ok=False` increments, `ok=True` resets to 0 |
| `test_record_invocation_timeout_marks_last_timeout` | `error_type="timeout"` sets `last_timeout` to today |
| `test_record_invocation_never_raises_on_io_error` | Best-effort contract |
| **`test_record_invocation_does_not_modify_profiles_json`** | **Critical regression test.** Hash `local_llm_profiles.json` before/after; bytes identical. |
| `test_schema_version_is_one` | Document version field present |

P1-H.2 adds `tests/test_health_telemetry.py` for the switched
readers/writer (router and MCP server health functions consuming the
runtime file via injected health_data).

Existing `tests/test_layer4_quality.py` is unchanged — its synthetic
dicts already simulate the same shape and continue to work because
the helper signature `is_profile_healthy(name, profiles_data, ...)`
keeps its current parameters.

---

## 8. Rollback Plan

- **P1-H.1 revert**: `git revert` the helper-only commit. No call sites
  changed, so the helper is orphaned and harmless. Runtime file is
  never written.
- **P1-H.2 revert**: `git revert` the switch commit. After revert:
  - The `_health` block is missing from profiles JSON (we cleaned it up
    in that same commit).
  - Reverted readers (`is_profile_healthy`, `_profile_is_healthy`,
    `cmd_health_report`, `auto_tune_recommendations`) would look for
    `_health` and find nothing.
  - `is_profile_healthy` returns True when `_health` is missing
    (line 93-94), so all profiles are treated as healthy.
  - This is the safe-by-default state; routing falls back to candidate
    chains as if telemetry never existed.
- **P1-H.3 revert**: trivial; affects only the `health-report` CLI and
  `--auto-tune` recommendation output.

Optional safety net: a one-shot `tools/migrate_health_to_runtime.py`
script that copies the current `_health` data from profiles JSON to
the runtime file before P1-H.2 lands. **Off by default.** Only useful
if a P1-H.2 issue is found during the same session in which it lands;
otherwise the 90/10 weighted average reconverges within a few calls.

---

## 9. Commit / Review Policy

| Phase | Commit gate | Debate review | Other |
|-------|-------------|---------------|-------|
| P1-H.0 (this doc) | yes | no | docs-only; same policy as P0 |
| P1-H.1 (helper) | yes | no | low risk; no call sites changed |
| P1-H.2 (switch) | yes | **yes — fast mode 2-round** | touches router health logic + MCP server write path; matches §5 debate-trigger category "hook/gate/security boundary" by analogy (router health affects routing decisions) |
| P1-H.3 (reporting) | yes | no | report-only changes |
| P1-H.4 (docs) | yes | no | docs-only |

No release. No tag. No VERSION bump. All phases land between v0.9.7
and the next planned release.

---

## 10. One-line summary

Move per-call `_health` telemetry out of `tools/local_llm_profiles.json`
into a gitignored `.local_llm_out/local_llm_health.json` so the
configuration file stops getting dirtied by background MCP work —
without changing routing semantics, health thresholds, or the 90/10
weighted-average formula.
