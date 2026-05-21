# MCP Cost Discipline / Model Allocation Policy — Plan

**Status**: planning only. No implementation yet. Gated on user approval.

---

## 1. Current Problem

local-llm-pipeline has grown a rich MCP infrastructure — review, debate, commit
gate, auto-invocation — plus Call Ledger v2-A for token tracking. But cost
discipline has not kept pace with capability.

### 1.1 Observed issues

| Issue | Symptom |
|-------|---------|
| **Auto-upgrade inflation** | CLAUDE.md escalation rule triggers `deep_reviewer` whenever `confidence=medium` or `uncertain_points ≥ 3`. A medium-confidence review on a small docs diff can escalate to a 35B+ model for no gain. |
| **Debate over-provisioning** | Debate is recommended for large diffs (>100 lines, 3+ files, logic changes) but the triggers are broad. Every multi-file diff that touches worker code can theoretically trigger debate. |
| **No per-phase cost cap** | Nothing limits how many strong-model reviews can fire in one phase. A phase with many small commits could burn deep-review tokens at scale. |
| **Hardware role confusion** | Profiles, health fields, and backend notes describe models on specific hosts (zero12, laptop) but there is no policy-level statement of which machine does what. |
| **Local heavy model profiles undefined** | The project has no policy distinction between default local worker profiles and heavy-audit profiles (e.g. future V4-Flash local). |
| **External strong models out of scope** | Optional external cloud model usage (e.g. DeepSeek API) is separate and out of this plan unless explicitly configured. |
| **Call Ledger tracking gaps** | Ledger records model/tokens but not escalation reason, review necessity level, or whether a call was user-forced versus automatic. |

### 1.2 Why this matters now

v2-A gave us real provider usage passthrough for non-stream calls. We can now
see *exactly* how many tokens each model uses per call. But without cost
discipline, we're tracking waste without preventing it.

---

## 2. Hardware Assumptions

These are fixed for the current planning window. They may be updated when
hardware changes.

| Machine | Role | Notes |
|---------|------|-------|
| **R9000P** | Control workstation only | Runs Claude Code / Codex. Does **not** run local models. Never a worker target. |
| **AI Max 1 (zero12)** | Primary local model worker | Ollama + llama.cpp MTP. Runs all profiles. Hosts 59 Ollama models. |
| **AI Max 2** | Future second worker | Optional. Expected to extend capacity, not replace AI Max 1. |
| **Thunderbolt 5 80Gbps** | Worker-pool interconnect | High-speed link between workers for task dispatch and result transfer. Not unified VRAM — each worker has independent GPU memory. |
| **V4-Flash local** | Experimental heavy audit | Local compute-pool driven heavy audit profile. Low-frequency only. Not a default daily worker. No API assumption in this plan. Call Ledger must record provider/model/tokens per normal flow. |

### 2.1 Non-goal: unified VRAM pool

Thunderbolt 5 provides fast networking, not shared GPU memory. Cross-machine
model sharding (tensor parallelism across hosts) is explicitly out of scope.

### 2.2 Local V4-Flash Boundary

- V4-Flash local is **not API by default** — it is a future local compute-pool
  driven heavy audit profile, not an external cloud model.
- **Not a daily worker** — only triggered by release/freeze, high-risk audit,
  local reviewer disagreement, or explicit user request.
- **No model-level cross-machine sharding** in this phase — V4-Flash runs on a
  single worker, not split across AI Max 1 + AI Max 2.
- May be represented as a `v4_flash_local_experimental` profile later.
- All calls must enter Call Ledger with `worker_id` and `escalation_reason`.

---

## 3. Model Allocation Rules

Every task type has a default profile assignment. Deviations must be recorded
with an escalation reason.

### 3.1 Task-to-model mapping

| Task | Default Profile | Model | Risk | Notes |
|------|-----------------|-------|------|-------|
| grep / file listing / git status | *(none)* | — | — | No model call |
| log compression | `fast_summary` | gemma4:e4b | low | Small model, local only |
| summarize_file | `fast_summary` | gemma4:e4b | low | Auto-upgrade to `smart_summary` only if `confidence=low` |
| summarize_tree | `fast_summary` | gemma4:e4b | low | Same upgrade rule |
| extract_todos | `code_worker` | qwen3-coder:30b | medium | — |
| find_related_files | `code_worker` | qwen3-coder:30b | medium | — |
| test_plan (new API/schema) | `code_worker` | qwen3-coder:30b | medium | Mandatory before implementation |
| draft_code | `code_worker` | qwen3-coder:30b | medium | Output to `.local_llm_out/` only |
| **ordinary diff review** | `diff_reviewer` | nemotron-nano-omni-30b | medium | Non-commit-gate review |
| **commit gate** | `commit_reviewer` | qwen3-coder:30b | medium | Strict constraint: <30s, never >30B, never reasoning |
| risk_analysis | `reasoning_checker` | nemotron-nano-omni-30b | medium-high | — |
| deep_code_review | `deep_reviewer` | qwen3.6:35b | high | Must have documented reason |
| architecture_review | `deep_reviewer` | qwen3.6:35b | high | Must have documented reason |
| **hook/gate/security/release** | `deep_reviewer` or `release_auditor` | qwen3.6:35b or mistral-medium-3.5-128b | high | Debate review mandatory |
| release_freeze audit | `release_auditor` + debate | mistral-medium-3.5-128b | high | Full 3-round debate |
| **V4-Flash local audit** | *(experimental)* | V4-Flash (local compute-pool) | high | Manual only, user-explicit, ledger must record |

### 3.2 User override

User may override any default profile by explicit request. The override must be
recorded in the commit message, the Call Ledger `extra.escalation_reason` field,
or both. Override does not exempt the call from commit gate or dangerous-command
guards.

---

## 4. Escalation Rules

### 4.1 Default: no auto-upgrade

The current CLAUDE.md auto-upgrade rule (**`confidence=medium` triggers deep
reviewer**) is too aggressive. It must be replaced with a narrower trigger set.

### 4.2 Upgrade only when

| # | Condition | Rationale |
|---|-----------|-----------|
| a | Tests fail after review | Reviewer missed a real bug |
| b | Working tree dirty after review | Diff changed, re-review needed |
| c | Diff touches hook/gate/security/release/schema/destructive-mutation | Structural risk |
| d | Two local reviewers from different model families disagree | Debate needed to resolve |
| e | User explicitly requests | Override, must be recorded |

`confidence=medium` alone does **not** trigger upgrade. If the only signal is
`confidence=medium` with `uncertain_points < 3` and none of conditions a-e,
accept the review result.

### 4.3 Every escalation must record reason

The Call Ledger `extra` dict must include:

```json
{
  "escalation_reason": "<one of: test-failure | dirty-after-review | structural-risk | reviewer-disagreement | user-requested>",
  "escalation_from_profile": "commit_reviewer",
  "escalation_to_profile": "deep_reviewer"
}
```

### 4.4 Maximum review passes per diff

| Context | Max passes |
|---------|-----------|
| Ordinary change | 1 review pass (commit_gate) |
| Change with debate trigger | 1 review + 1 debate (fast 2-round) |
| Release/freeze | 1 review + 1 debate (full 3-round) + 1 release_auditor |
| Repeated failure (3+ failures) | Controller stops and diagnoses; no auto-retry loop |

---

## 5. Debate Review Rules

### 5.1 Default: disabled for ordinary changes

`local_debate_review_diff` is NOT a default review path. It consumes 2-3 model
calls per round and should fire only when specifically justified.

### 5.2 Allowed triggers

| Trigger | Debate mode | Notes |
|---------|-------------|-------|
| release / freeze | Full 3-round | Release auditor also required |
| hook / gate / security boundary | Fast 2-round minimum | Full 3-round for architecture changes |
| destructive mutation (DB schema, data migration) | Fast 2-round minimum | — |
| cross-project boundary | Fast 2-round | e.g. MCP server protocol changes |
| repeated failure (same diff, 2+ reviews disagree) | Full 3-round | Controller-initiated only |
| user explicit request | As specified | Must be recorded |

### 5.3 Per-phase debate cap

| Phase scope | Max debate invocations |
|-------------|------------------------|
| Single-feature phase (≤ 3 commits) | 1 |
| Multi-feature phase (4-10 commits) | 2 |
| Release phase | 3 (including release debate) |

Exceeding the cap requires user approval and must be recorded in the phase
completion report.

---

## 6. Cost Budget Rules

### 6.1 Per-phase strong-model limit

A "strong model" is any model with risk_level `high` (deep_reviewer,
release_auditor, deep_reasoning, heavy_reviewer, deepseek_r1_70b,
nemotron_super, V4-Flash).

| Phase type | Max strong-model calls |
|------------|------------------------|
| Docs / tooling | 0 |
| Feature (non-structural) | 1 |
| Structural (hook/gate/schema/router) | 3 |
| Release | 5 |

### 6.2 Log compression before strong model

When sending large diffs or logs to a strong model, compress first:
- Truncate unchanged hunks to context lines
- Strip irrelevant file metadata
- Pre-filter with a small local model if the input exceeds 60k chars

### 6.3 Staged diff review before every commit

Already enforced by commit gate. No change needed. The cost budget rule adds:
never re-submit the same diff to the same model twice.

### 6.4 No repeated full-diff reviews

If a commit gate review runs and `diff_reviewed=true` with `dirty_since_review=false`,
a second `local_review_diff` on the same commit gate must be explicitly
justified (e.g., "review timed out but returned ok=true" or "review output was
truncated"). Without justification, skip the re-review and proceed.

---

## 7. Ledger Requirements

Call Ledger already records: `task_type`, `tool_name`, `model`, `provider`,
`tokens`, `cached_tokens`, `cache_miss_tokens`, `duration_ms`, `estimated_cost_cny`,
`success`, `cache_hit`, `failure_reason`, `git_commit_before/after`,
`git_dirty_before/after`, `request_id`, `files_referenced`.

### 7.1 New fields for cost discipline (additive, backward-compatible)

All new fields go into the existing `extra` dict — no JSONL schema migration needed.

| Field | Type | When set |
|-------|------|----------|
| `escalation_reason` | `str \| null` | Set when a review or model call is the result of escalation (per §4.3) |
| `escalation_from_profile` | `str \| null` | Profile that would have been used by default |
| `escalation_to_profile` | `str \| null` | Profile actually used |
| `review_necessity` | `"required" \| "recommended" \| "user-forced" \| null` | Classification of why this review ran |
| `debate_rounds` | `int \| null` | Number of debate rounds actually run (2 or 3) |
| `debate_trigger` | `str \| null` | Which §5.2 trigger fired the debate |
| `cost_budget_remaining` | `int \| null` | Strong-model calls remaining in this phase (informational snapshot) |

### 7.2 Fields that already exist and are sufficient

- `task_type` / `tool_name`: identifies the kind of work
- `project` / `phase`: identifies the context
- `request_id`: correlates retry sequences
- `provider` / `model` / `tokens` / `cached_tokens` / `cache_miss_tokens`: actual spend
- `estimated_cost_cny`: cost in CNY

### 7.3 Worker integration

Worker's `_emit_ledger` closure already passes an `extra` dict built from the
worker run metadata. Cost discipline fields flow through `extra` without
changing any function signature.

---

## 8. Worker Pool Direction (sketch, not for implementation now)

When AI Max 2 joins the pool:

```
R9000P (controller)
  ├─ AI Max 1 (zero12): Ollama + llama.cpp MTP, default worker
  └─ AI Max 2: optional second worker
       Thunderbolt 5 80Gbps interconnect
```

Key design constraints (to be refined in a future worker-pool plan):

- Each worker has a `worker_id`, `host`, `model_profile`, `capacity`, `status`
- Task dispatch is per-task, not per-model-shard
- No cross-machine tensor parallelism
- Ledger records `worker_id` in `extra` for attribution
- Pool routing is controller-side; workers don't route among themselves

---

## 9. Explicit Non-Goals

This plan does **not** address:

- v2-B streaming usage passthrough (separate plan)
- v2-C cache-tier cost table expansion (separate plan)
- SQLite-backed ledger (out of v2 scope)
- Context Budget (separate workstream)
- Cross-project ledger aggregation tooling (separate workstream)
- Hook code changes (this plan only defines policy; implementation follows
  approval)
- Release / tag / version bump
- Tensor parallelism or cross-machine model sharding
- Scheduler / queue implementation
- V4-Flash local runtime provisioning, model acquisition, distributed inference, tensor/model parallel implementation, or API-key management

---

## 10. Proposed Implementation Phases

| Phase | Scope | Approx. files | Risk |
|-------|-------|---------------|------|
| **P0** | Docs policy (this document). Approve. | 1 (this file) | none |
| **P1** | Profile/policy metadata. Add `_cost_discipline` fields to `local_llm_profiles.json` (e.g., `_max_per_phase`, `_allowed_triggers`). Schema-additive only. | `local_llm_profiles.json` | low |
| **P2** | Ledger escalation fields. Worker `_emit_ledger` populates `extra.escalation_reason` etc. **Additive to JSONL schema — no migration.** | `call_ledger.py`, `local_llm_worker.py` | low |
| **P3** | Auto-upgrade restriction. Replace CLAUDE.md escalation rule with §4 logic. Remove `confidence=medium` → auto-deep-reviewer trigger. | `CLAUDE.md` (policy doc) | **medium** — behavioral change |
| **P4** | Worker pool dry-run. `local_check` probes AI Max 2 (when available). No routing changes. | `local_llm_check.py`, profiles | low |
| **P5** | V4-Flash local experimental profile. Add profile entry in `local_llm_profiles.json`. Manual invocation only. Ledger records provider=tongyi, model=v4-flash. | `local_llm_profiles.json` | low |

P0 is the current phase. P1-P5 are not scheduled and each requires a separate
plan before implementation.

---

## 11. One-line summary

Define who runs what model, when escalation is allowed, and how much strong-model
capacity each phase may consume — enforced via Call Ledger fields and CLAUDE.md
policy, not new hook code.

---

## 12. P1-A Completion Notes (helper-first, derivation-only)

P1 was narrowed to **P1-A: derivation helper only**. No JSON files
changed; no runtime behavior changed. The earlier intent of stamping a
`policy` block onto every profile is deferred — P1-A first proves the
derivation rules and downstream consumers (P2+) can read from the helper
without any schema migration.

**What landed**

- New read-only helper `tools/profile_policy.py`. Public surface:
  `load_profiles`, `derive_policy`, `get_policy` (alias),
  `validate_policy`, plus the enum sets `VALID_RISK_LEVELS` /
  `VALID_REVIEW_NECESSITY` and the field tuple `POLICY_FIELDS`.
- `derive_policy(name)` returns the normalized 8-field view derived
  from existing profile fields (`risk_level`, `_commit_gate_allowed`,
  `_provider` / `_local_only`, and profile name). It does **not** read
  a `policy` block — none exists in JSON yet, and none is required.
- `tests/test_profile_policy.py` asserts derivation rules, enum
  validity, invariants (e.g. exactly one `commit_gate_allowed`), and
  two guards: the helper imports no runtime modules and the helper
  never writes any file.

**What did NOT change**

- `tools/local_llm_profiles.json` — unchanged byte-for-byte from
  HEAD `a499dba`.
- No routing logic, hook, commit gate, auto-upgrade rule, debate
  trigger, or release guard touched.
- Existing readers still consult `risk_level` and
  `_commit_gate_allowed` directly. The new helper is purely additive.

**Derivation rules (P1-A locked)**

| Field | Derivation |
|-------|------------|
| `risk_level` | `profile["risk_level"]` if in enum, else `"medium"` |
| `experimental` | `risk_level=="experimental"` OR `"experimental"` substring in profile name |
| `commit_gate_allowed` | `profile["_commit_gate_allowed"] is True` |
| `requires_escalation_reason` | `risk_level in {"high","experimental"}` |
| `debate_allowed` | `risk_level in {"high","experimental"}` |
| `auto_allowed` | `not experimental and risk_level != "high"` |
| `local_only` | `_local_only != False AND _provider not in {external, api, cloud}` |
| `default_review_necessity` | `commit_reviewer→required`, `diff_reviewer→recommended`, `fast/smart_summary→optional`, `high/experimental→recommended`, else `optional` |

**Invariants currently machine-checked**

- Every profile in `local_llm_profiles.json` yields a complete
  8-field policy view.
- Exactly one profile (`commit_reviewer`) derives
  `commit_gate_allowed=true`.
- Every `high`-risk profile derives `auto_allowed=false`,
  `requires_escalation_reason=true`, `commit_gate_allowed=false`.
- No profile derives `experimental=true` (reserved for P5 / V4-Flash;
  triggered automatically when a profile is named `*experimental*`).
- Every profile derives `local_only=true`.

**Scope for P1-B (not yet started)**

If/when downstream code needs to override or pin policy explicitly,
P1-B can introduce an opt-in `policy` block in JSON — but only after
P2 has demonstrated a concrete consumer that needs it. Until then, the
derivation rules above are the single source of truth.

---

## 13. P2 Completion Notes (P2 DONE)

P2 was split into sub-phases P2-A through P2-D1, all additive to the JSONL
ledger schema (no migration). P2-E is the docs closeout (this section plus
`PROJECT_STATUS.md`, `CHANGELOG.md`, `README.md`). The cost-discipline
ledger chain is complete; runtime call sites stamp the new fields and the
CLI surfaces them. No VERSION bump, no tag, no release.

### 13.1 Phase commits

| Phase | Status | Commit | Summary |
|-------|--------|--------|---------|
| P2-A | DONE | (audit, no code) | Read-only audit of call ledger gaps. Locks the P2-B field model: debate calls bypass ledger, escalation context lost, commit-gate flag uncaptured. |
| P2-B | DONE | `285279c` | Schema/helper extension in `tools/call_ledger.py`: top-level `profile` field on `build_record` and `KNOWN_EXTRA_KEYS` allowlist (MCP routing identity, escalation context, debate context, review classification, worker-pool attribution, structured error type). No call sites wired. |
| P2-C1.0 | DONE | `3abe46e` | Worker ledger env plumbing: worker reads `LOCAL_LLM_LEDGER_EXTRA`, filters via `KNOWN_EXTRA_KEYS`, folds into ledger `extra`; `_emit_ledger` populates top-level `profile` from `config.profile`. |
| P2-C1.1 | DONE | `cc1bcbf` | MCP server per-tool stamps. `_build_ledger_extra_env` helper; `extra_env` parameter on `run_subprocess` / `run_subprocess_streaming` / `_wrap_worker_call`. Every worker-backed MCP tool stamps `mcp_tool_name` + `source="manual-mcp"`; `local_review_diff` stamps `commit_gate`; `local_parallel_review` stamps each parallel worker. `local_check` and `local_debate_review_diff` intentionally unstamped here (the latter handled in P2-C3.1). |
| P2-C1.2 | DONE | `3fff081` | Auto-hook env replacement. `tools/claude_hooks/mcp_auto_worker.py` ships a self-contained `_build_ledger_extra_env` helper (decoupled from MCP server) and `spawn_review_diff` drops the broken `--commit_gate true` CLI passthrough, stamping `{mcp_tool_name=local_review_diff, commit_gate=true, source=auto-hook}` via env instead. |
| P2-C2.0 | DONE | `034bedb` | Schema allowlist extension: `escalation_trigger` added to `KNOWN_EXTRA_KEYS`. |
| P2-C2.1 | DONE | `a2a5547` | Escalation context: `_wrap_worker_call` injects `escalation_*` fields and `parent_request_id` into the escalated child via `_merge_escalation_ledger_extra_env` + `_derive_escalation_trigger` helpers. |
| P2-C3.1 | DONE | `9bfbb6d` | Debate round ledger emission: `run_round()` emits one ledger record per round with debate metadata (`debate_mode`, `debate_rounds`, `debate_round_index`, `debate_trigger`); `call_debate_review_diff` MCP handler passes `--debate-trigger manual-mcp`; auto-escalation passes `--debate-trigger auto-escalate`; captures real provider `ModelCallResult.usage` instead of dropping it. |
| P2-D1 | DONE | `afca643` | Reporting/CLI: `tools/call_ledger_cli.py` gains `by-profile`, `by-mcp-tool`, `escalations`, `debates` subcommands. Library helpers `group_by_extra`, `filter_escalations`, `filter_debates` in `tools/call_ledger.py`. Old records (missing `extra`/`profile`) bucket into `<none>`; `by-mcp-tool` falls back to top-level `tool_name`. |
| P2-E | DONE | this commit | Docs closeout: this section + `PROJECT_STATUS.md` + `CHANGELOG.md` + `README.md` "Call ledger reporting". |

### 13.2 Final state of the ledger schema and call sites

- **Top-level fields** (`tools/call_ledger.py::build_record`):
  - `profile` — populated by the worker from `config.profile`. Default
    `None` for synthetic/test callers. Old records (pre-P2-B) bucket into
    `<none>` in the CLI.
- **`extra` dict** — additive, allowlisted via `KNOWN_EXTRA_KEYS`:
  - MCP routing identity: `mcp_tool_name`, `source`, `commit_gate`.
  - Escalation: `auto_escalated`, `escalation_trigger`,
    `escalation_reason`, `escalation_from_profile`,
    `escalation_to_profile`, `escalation_depth`, `parent_request_id`.
  - Debate: `debate_mode`, `debate_rounds`, `debate_round_index`,
    `debate_trigger`.
  - Future-reserved (declared in P2-B, not yet stamped):
    `review_necessity`, `worker_id`, `cost_budget_remaining`,
    `error_type`.
- **Call sites stamping the env**:
  - `tools/local_llm_mcp_server.py`: every worker-backed MCP tool via
    `_build_ledger_extra_env` + `extra_env` parameter. `local_review_diff`
    stamps `commit_gate`; `local_parallel_review` stamps each parallel
    worker. `_wrap_worker_call` stamps escalation context on the
    escalated child.
  - `tools/claude_hooks/mcp_auto_worker.py`: `spawn_review_diff` stamps
    `{mcp_tool_name=local_review_diff, commit_gate=true,
    source=auto-hook}` directly (no MCP server dependency).
  - `tools/local_llm_debate.py`: `run_round()` emits one ledger record
    per round with debate metadata; trigger comes from the
    `--debate-trigger` CLI flag (`manual-mcp` / `auto-escalate`).
- **Reader/reporting** (`tools/call_ledger_cli.py`):
  - `summary`, `by-project`, `by-task`, `failures`, `recent` —
    unchanged.
  - `by-profile`, `by-mcp-tool`, `escalations`, `debates` — new.
- **Backward compatibility**: every change is JSONL-additive. Pre-P2
  records (no `extra`, no `profile`) still parse and aggregate; they
  land in the `<none>` bucket, except `by-mcp-tool` which falls back to
  the top-level `tool_name`.

### 13.3 Review policy actually used

| Phase | Commit gate | Debate review | Notes |
|-------|-------------|---------------|-------|
| P2-A | n/a (audit, no commit) | n/a | Read-only audit, no diff to review. |
| P2-B | yes (`ok=true`) | no | Schema/helper only; no call sites wired. |
| P2-C1.0 | yes (`ok=true`) | yes (fast mode) | Worker behavioral change — touches `_emit_ledger` and worker env. |
| P2-C1.1 | yes (`ok=true`) | yes (fast mode) | MCP server change — matches §5.2 "hook/gate/security boundary" by analogy. |
| P2-C1.2 | yes (`ok=true`) | yes (fast mode) | Hook code change — matches §5.2. |
| P2-C2.0 | yes (`ok=true`) | no | Allowlist constant only; no behavior change. |
| P2-C2.1 | yes (`ok=true`) | yes (fast mode) | `_wrap_worker_call` behavioral change in MCP server. |
| P2-C3.1 | yes (`ok=true`) | yes (fast mode) | Debate runtime change. |
| P2-D1 | yes (`ok=true`, 26.05s, `commit_reviewer` / qwen3-coder:30b) | no | Reporting/CLI read path only; does not touch worker, MCP server, router, debate, or hooks. |
| P2-E | this commit (docs-only) | no | Matches §9 docs-only policy. |

### 13.4 Acceptance evidence

- `tests/test_call_ledger.py` — 106 passed after P2-D1 (`afca643`),
  including:
  - P2-B schema/helper tests (top-level `profile`, `KNOWN_EXTRA_KEYS`).
  - P2-C escalation context tests (`_merge_escalation_ledger_extra_env`,
    `_derive_escalation_trigger`).
  - P2-D1 reporting tests: `group_by_extra` (basic, missing extra,
    missing key, `tool_name` fallback); `filter_escalations` (finds
    auto-escalated, empty when none); `filter_debates` (finds both
    rounds, empty when none); CLI subcommands `by-profile`,
    `by-mcp-tool`, `escalations`, `debates` (table + JSON + limit);
    old-record `<none>` bucket compatibility.
- `py -m compileall -q tools tests` — clean throughout the chain.
- VERSION unchanged at `0.9.7` from P2-B through P2-E.
- No tag created. No release.

### 13.5 Out-of-scope follow-ups (still open after P2)

- **P3** (not started): Auto-upgrade restriction. Replace the CLAUDE.md
  `confidence=medium` → deep-reviewer trigger with the §4 logic. This is
  a behavioral change and requires its own plan + debate review.
- **P4** (not started): Worker pool dry-run. `local_check` probes a
  second worker host (AI Max 2) when available. Ledger already records
  `worker_id` in `extra` for future use.
- **P5** (not started): V4-Flash local experimental profile.
- Cost budget enforcement (§6) is **policy-only** today — the ledger
  records strong-model usage but no hook blocks at the cap. Enforcement
  is deferred to a future phase.
- `review_necessity` and `cost_budget_remaining` are declared in
  `KNOWN_EXTRA_KEYS` but not yet stamped by any call site.
