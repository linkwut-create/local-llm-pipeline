# P5 V4-Flash Local Experimental Profile — Plan

**Status:** P5-A (read-only audit + boundary lock-in). Implementation
slice P5-B has **not** been approved.

**Baseline at audit time:** HEAD `533e7b9` (`docs: close out P4 worker
pool dry-run`), `git describe v0.9.7-30-g533e7b9`, VERSION `0.9.7`, no
tag at HEAD, working tree clean. P3 chain closed; P4 chain closed
(P4-C deferred); P5 is the next runway.

---

## 1. P5 in one sentence

P5 adds an **experimental, manual-only** profile entry for a future
local V4-Flash heavy-audit model so that operators can invoke it
explicitly when a release / freeze / disagreement / high-risk audit
warrants it, **without** the profile becoming part of any default
routing, auto-escalation, or worker-pool dispatch.

## 2. Hard boundary (frozen by P5-A)

P5 is a **single JSON profile entry** plus the minimum supporting
machinery already required by the existing policy validator. The
following are out of scope for the entire P5 chain (P5-A through any
P5-N) and may only be revived under a separately approved plan:

- Making V4-Flash a default profile for any task in
  `tools/local_llm_tasks.json`.
- Auto-routing any task to V4-Flash via
  `_resolve_starting_profile` (Path A) or any other router path.
- Wiring V4-Flash into the P3 cost-discipline auto-escalation chain.
  V4-Flash must **not** appear as an escalation target in
  `_check_quality_escalation` or the escalation chains in
  `tools/local_llm_mcp_server.py`.
- Wiring V4-Flash into the P4 worker-pool probe. The probe payload
  shape (`PROBE_REPORT_SCHEMA_VERSION = 1`) stays unchanged in P5.
- Adding new MCP tools. The 9-tool count in
  `tests/test_mcp_server.py::test_tools_count` must stay 9.
- Adding new MCP tool parameters. The existing per-tool `profile`
  override path is enough; no new `provider`, `endpoint`,
  `experimental`, or similar parameter.
- Changing the ledger schema. `call_ledger.py` and
  `call_ledger_cli.py` are not touched.
- Adding a worker pool runtime, scheduler, daemon, queue, or
  background worker (still non-goal from P4).
- Provisioning V4-Flash itself — model acquisition, hardware
  configuration, network routing, or anything that requires the
  binary/weights to be present. P5 ships only the policy entry.
- Adding cross-machine tensor parallelism / unified VRAM.
- Bumping `VERSION`, creating a tag, or cutting a release.

If P5 implementation work starts trending toward any of these, the
work must stop and be re-planned.

## 3. Current architecture findings (read-only audit)

### 3.1 Profile schema

- `tools/local_llm_profiles.json` (568 lines): one entry per profile
  under `"profiles"`. Required fields per
  `tools/validate_configs.py:37` `REQUIRED_PROFILE_FIELDS = {"model",
  "risk_level", "use_for"}`. Common optional fields actually used by
  existing profiles: `temperature`, `max_chars`, `max_output_chars`,
  `candidates`, `_strengths`, `_benchmark`, `_community_reputation`,
  `_commit_gate_allowed`, `_constraints`, `_last_tested`, `_env`,
  `_provider`, `_local_only`, `timeout`.
- No existing profile carries `risk_level: "experimental"`.
- Profiles do **not** declare a per-profile `provider` field — the
  worker auto-detects provider from `LOCAL_LLM_BASE_URL` /
  `LOCAL_LLM_PROVIDER` env vars
  (`tools/local_llm_worker.py:838-845`).

### 3.2 Risk-level allowlist divergence (KEY FINDING)

Two modules disagree on the valid risk-level set:

- `tools/profile_policy.py:33`
  `VALID_RISK_LEVELS = {"low", "medium", "medium-high", "high", "experimental"}`
- `tools/validate_configs.py:22`
  `VALID_RISK_LEVELS = {"low", "medium", "medium-high", "high"}` — **no "experimental"**.

Consequence: dropping a `risk_level: "experimental"` entry into
`tools/local_llm_profiles.json` would **fail**
`validate_configs.validate_profiles()` and
`tests/test_validate_configs.py::test_invalid_risk_level_fails`
(which already asserts unknown values are rejected).

This divergence existed before P5 — it was a latent dead branch
because no profile actually used `risk_level: "experimental"`. P5
forces a decision:

- **Option A (recommended):** add `"experimental"` to
  `validate_configs.py:VALID_RISK_LEVELS` so the two modules agree.
  This is a one-line config alignment, scoped to a single set
  literal, with one new test asserting the value is accepted.
- **Option B:** keep `validate_configs.py` as-is and give V4-Flash
  `risk_level: "high"` + name it `v4_flash_local_experimental`. The
  policy derivation in `_derive_experimental()` already returns
  `True` when the profile name contains `"experimental"`
  (`profile_policy.py:60-63`), so the policy view comes out
  correct. This avoids touching `validate_configs.py` at all but
  leaves the latent divergence in place.

P5-B should pick one and document it; the plan recommends **Option A**
because it removes a known inconsistency for ~5 lines of code (set
member + matching test). If P5-B reviewer disagrees, Option B is a
fallback that keeps the patch narrower.

### 3.3 Policy derivation already covers experimental

`tools/profile_policy.py` (185 lines, no changes needed for P5):

- `_derive_experimental(name, risk_level)` returns `True` if
  `risk_level == "experimental"` **or** profile name contains
  `"experimental"`.
- `_derive_auto_allowed(risk_level, experimental)` returns `False`
  for any experimental profile — this is the **runtime guarantee
  that V4-Flash will never be auto-routed**.
- `_derive_default_review_necessity(...)` returns `"recommended"`
  for experimental.
- `_derive_requires_escalation_reason(...)` returns `True` for
  experimental.
- `_derive_debate_allowed(...)` returns `True` for experimental.

So adding the profile is a pure-data change; the policy derivation
already does the right thing.

### 3.4 Router

- `tools/local_llm_router.py:63 resolve_profile(task,
  profile_override, model_override, ...)` accepts a `profile`
  CLI/env override; otherwise it uses
  `tasks.json::tasks[task].default_profile` or falls back to
  `"fast_summary"`.
- **V4-Flash becomes routable only if a caller explicitly passes
  `--profile v4_flash_local_experimental`** (or the MCP equivalent).
  No task entry should reference it.
- Health gating: `is_profile_healthy(name, profiles_data,
  health_data)` is permissive by default — when no health record
  exists it returns `True`. So a freshly added profile will not be
  blocked by the health gate.

### 3.5 MCP server

- Per `grep "profile"` in `tools/local_llm_mcp_server.py`: 8 of the
  9 MCP tools (`local_summarize_file`, `local_summarize_tree`,
  `local_generate_test_plan`, `local_review_diff`,
  `local_debate_review_diff`, `local_parallel_review`,
  `local_draft_code`, `local_contextual_analyze`) already declare a
  `"profile"` parameter in their input schema. `local_check` is the
  one tool without it.
- Manual invocation example:
  `local_review_diff(diff_text=..., profile="v4_flash_local_experimental")`.
- No new MCP wrapper, schema, or dispatch table entry is required.
  P5-B must not add one.

### 3.6 Worker / provider resolution

- `tools/local_llm_worker.py:838-845` resolves provider via:
  1. CLI flag `--provider` (if given),
  2. env `LOCAL_LLM_PROVIDER` (if set),
  3. auto-detect: `"ollama"` if `LOCAL_LLM_BASE_URL` contains
     `":11434"`, else `"openai-compatible"`.
- **Only two providers exist in the worker:** `"ollama"` and
  `"openai-compatible"`. There is no `"tongyi"`,
  `"openai-compat-tongyi"`, or `"v4flash"` provider, and adding one
  is out of scope for P5.
- The legacy `docs/MCP_COST_DISCIPLINE_PLAN.md:367` reference to
  `provider=tongyi, model=v4-flash` predates the §2.2 reframing of
  V4-Flash as a *local* model. Treat the §2.2 wording as
  authoritative — V4-Flash will be served either by Ollama on a
  zero12 host or by a llama.cpp-style OpenAI-compat endpoint, with
  the provider auto-detected from the URL. P5-B should reconcile
  the stale "tongyi" reference (docs-only).

### 3.7 Ledger

- `tools/call_ledger.py` already records `profile`, `provider`,
  `model`, `model_size_class`, and the existing extra slots
  including `worker_id` / `host` (still unstamped, as confirmed in
  P4). No schema change is needed for V4-Flash; an experimental
  invocation will land in the ledger with `profile =
  "v4_flash_local_experimental"`, `provider` auto-detected, `model`
  from the profile entry. `provider` is **not** going to be
  `"tongyi"` because the worker doesn't know that string.

### 3.8 Tasks file

- `tools/local_llm_tasks.json` (228 lines): one entry per task with
  `default_profile`. **No task entry needs to be modified for P5**;
  adding V4-Flash to any `default_profile` would violate §2 and
  must not happen.

### 3.9 Tests

Tests that touch the relevant surface today:

- `tests/test_validate_configs.py` — schema validation. Will
  reject an `experimental` risk_level until Option A lands.
- `tests/test_profile_policy.py` — policy derivation tests; no
  V4-Flash-specific test exists.
- `tests/test_router_profiles.py` — router profile selection.
- `tests/test_mcp_server.py` — tool count, dispatch, profile
  parameter shape. Asserts `len(mcp.TOOLS) == 9`.
- `tests/test_call_ledger.py` — ledger field coverage.

None of these need to be deleted or restructured. P5-B should add
new tests under one of these files (or a new
`tests/test_p5_v4_flash_experimental.py`) per §5.5.

### 3.10 Hardware non-availability

V4-Flash weights/binary are **not** installed in the current
environment. P5-B is a profile entry; running it requires the
operator to provision the model separately. The test plan must
mock the worker call rather than invoke a live model.

## 4. Non-goals (restated explicitly)

P5 will **not**:

1. Add a new MCP tool or a new MCP parameter.
2. Add a `tongyi` provider or any new provider to
   `tools/local_llm_worker.py`.
3. Add a new ledger field. `worker_id` / `host` remain unstamped.
4. Modify `tools/local_llm_router.py` or
   `tools/local_llm_mcp_server.py` routing/escalation behavior.
5. Modify `tools/local_llm_check.py` or the P4 probe payload shape.
6. Modify `tools/local_llm_tasks.json` to point any default at
   V4-Flash.
7. Provision the V4-Flash model itself (weights, binary, hardware).
8. Wire V4-Flash into the P3 auto-escalation chain.
9. Add cross-machine sharding, scheduler, daemon, or worker pool.
10. Bump `VERSION`, create a tag, or cut a release.

## 5. Proposed P5-B implementation slice (smallest viable)

P5-B (still requires separate approval — **do not implement during
P5-A**) should be the narrowest possible change to land the profile:

### 5.1 Profile entry

Add to `tools/local_llm_profiles.json` under `"profiles"`:

```jsonc
"v4_flash_local_experimental": {
  "model": "v4-flash",
  "_strengths": [
    "heavy-audit",
    "experimental",
    "low-frequency"
  ],
  "temperature": 0.1,
  "max_chars": 160000,
  "max_output_chars": 6000,
  "use_for": [
    "release-risk-review",
    "deep-code-review",
    "architecture-review",
    "debate-architecture-review"
  ],
  "risk_level": "experimental",
  "_local_only": true,
  "_constraints": "Manual invocation only. Not a default for any task. Requires explicit profile override (`--profile v4_flash_local_experimental` or MCP `profile=` parameter). Model weights / binary must be provisioned separately; the profile entry alone does not stand up the model.",
  "_community_reputation": "Reserved entry for a future local V4-Flash heavy-audit model. Provider is auto-detected from `LOCAL_LLM_BASE_URL` (Ollama if `:11434`, otherwise OpenAI-compatible)."
}
```

Notes on the values:

- `"model": "v4-flash"` is the placeholder model identifier. The
  reviewer should confirm whether the actual served name will be
  `v4-flash`, `qwen-v4-flash`, `v4-flash-local`, etc., and adjust
  before merging P5-B. The audit cannot pin the exact string
  because the model is not yet provisioned.
- `"risk_level": "experimental"` (Option A). If Option B is taken,
  switch to `"high"` — the profile name still triggers
  `_derive_experimental == True`.
- `use_for` lists the four heavy-audit tasks where the operator
  might reasonably ask for V4-Flash. **No matching `tasks.json`
  default_profile entry** — `use_for` is informational; the actual
  default routing is in `tasks.json`.
- `_local_only: true` makes the local-only policy derivation
  explicit even though `_derive_local_only` would default to
  `True` anyway.
- No `_commit_gate_allowed` — V4-Flash must never be used at the
  commit gate.
- No `_env` — environment for the worker comes from the operator's
  shell when they invoke the profile explicitly.

### 5.2 Risk-level allowlist alignment (Option A)

Single-line change in `tools/validate_configs.py:22`:

```python
VALID_RISK_LEVELS = {"low", "medium", "medium-high", "high", "experimental"}
```

This brings `validate_configs.py` into agreement with
`profile_policy.py:33`. No other code in `validate_configs.py`
needs to change (the `risk_level` check is the only consumer of
this set inside `validate_profiles()`).

If P5-B reviewer prefers Option B (no `validate_configs.py`
change), drop this hunk and set the profile entry's
`risk_level` to `"high"` instead. The remaining work is identical.

### 5.3 Docs alignment

- `docs/MCP_COST_DISCIPLINE_PLAN.md:367` mentions `provider=tongyi,
  model=v4-flash` — stale per §3.6 above. P5-B should adjust this
  to `provider=` is auto-detected and `model=v4-flash` (placeholder)
  per the actual runtime behavior. This is the only out-of-plan
  stale phrase that must be reconciled.

### 5.4 Files touched in P5-B (proposed)

- `tools/local_llm_profiles.json` — one new profile entry (~25
  lines additive).
- `tools/validate_configs.py` — one-line set literal extension
  (Option A only).
- `tests/test_validate_configs.py` — new test confirming
  `experimental` is accepted (Option A only).
- `tests/test_p5_v4_flash_experimental.py` (new) — focused tests
  per §5.5.
- `docs/MCP_COST_DISCIPLINE_PLAN.md` — minimal `provider=tongyi`
  reconciliation.
- `docs/P5_V4_FLASH_EXPERIMENTAL_PROFILE_PLAN.md` — update §5/§7
  to reflect what shipped.
- `PROJECT_STATUS.md` / `CHANGELOG.md` — record P5-B.

**Files explicitly NOT touched in P5-B:**

- `tools/local_llm_router.py` (routing untouched)
- `tools/local_llm_mcp_server.py` (no new tool, no new parameter)
- `tools/local_llm_worker.py` (no new provider)
- `tools/local_llm_check.py` (P4 probe untouched)
- `tools/call_ledger.py` / `tools/call_ledger_cli.py` (ledger
  untouched)
- `tools/local_llm_tasks.json` (no new default routing)
- `tools/health_store.py` / `tools/profile_policy.py` (telemetry &
  policy derivation untouched)
- `tools/claude_hooks/` (no hook changes)
- `CLAUDE.md` / `docs/mcp-task-policy.md` (no policy doc rewrite
  beyond the §5.3 reconciliation)
- `VERSION` / tags / releases (no release)

### 5.5 Test plan for P5-B (proposed; do not write in P5-A)

1. **Profile load**: the new profile is present in
   `load_profiles()["profiles"]` and has all
   `REQUIRED_PROFILE_FIELDS`.
2. **Schema accepted**: `validate_profiles()` returns no errors
   for the new entry (Option A) — or use `risk_level="high"`
   (Option B).
3. **Risk-level allowlist**: a unit test that
   `validate_configs.VALID_RISK_LEVELS` contains `"experimental"`
   (Option A only).
4. **Policy derivation**:
   `profile_policy.derive_policy("v4_flash_local_experimental")`
   returns `experimental=True`, `auto_allowed=False`,
   `requires_escalation_reason=True`, `debate_allowed=True`,
   `default_review_necessity="recommended"`,
   `commit_gate_allowed=False`, `local_only=True`.
5. **No task points at it**:
   `tasks.json::tasks[t].default_profile != "v4_flash_local_experimental"`
   for every `t`.
6. **Router does not auto-select it**: with the new profile in
   place but no `--profile` override, `resolve_profile(task, None,
   None)` returns its task's existing default profile for every
   task — never V4-Flash.
7. **Router does select it on explicit override**:
   `resolve_profile("deep-code-review", "v4_flash_local_experimental",
   None)` returns `("v4_flash_local_experimental", "v4-flash",
   "experimental")` (or `"high"` under Option B).
8. **No P3 escalation wiring leaked**: grep `local_llm_mcp_server.py`
   for `"v4_flash"`, `"v4-flash"`, `"V4-Flash"`,
   `"v4_flash_local_experimental"` — must find zero matches.
9. **No new MCP tool**: `len(mcp.TOOLS) == 9` is still the
   assertion in `tests/test_mcp_server.py::test_tools_count`.
10. **P4 probe payload unchanged**: rerun
    `tests/test_p4_worker_pool_dry_run.py::TestSchemaInvariants`
    — `PROBE_REPORT_SCHEMA_VERSION == 1`, fields unchanged.
11. **Ledger emission**: mock a worker invocation with profile =
    `v4_flash_local_experimental` and confirm the ledger record
    contains `profile = "v4_flash_local_experimental"` and a valid
    `provider` (either `"ollama"` or `"openai-compatible"`, never
    `"tongyi"`).

### 5.6 Review gate

P5-B touches `tools/local_llm_profiles.json` (data) and
`tools/validate_configs.py` (schema check). Per CLAUDE.md
MCP-USAGE-RETRO-1 #3, neither is in the must-debate categories
(hook/gate/MCP server/router/safety policy/DB schema/audit
infra/release boundaries). `local_review_diff(commit_gate=true)`
suffices; `local_debate_review_diff(fast=true)` triggers only if
a reviewer reports a blocker or the diff bleeds into router/MCP
server/worker files.

## 6. Risk list

| Risk | Mitigation |
|------|------------|
| Scope creep — operator adds V4-Flash to a `tasks.json` default | Test #5 asserts `default_profile != "v4_flash_local_experimental"` for every task. Reviewer must reject any task-default change in P5-B. |
| V4-Flash leaks into P3 auto-escalation | Test #8: grep MCP server for V4-Flash refs, must be zero. |
| V4-Flash leaks into P4 worker-pool probe payload | Test #10: P4 schema invariants re-asserted. Probe code in `tools/local_llm_check.py` not in P5-B's allowed files. |
| MCP tool count drifts off 9 | Test #9. P5-B does not modify `tools/local_llm_mcp_server.py`. |
| Worker grows a new provider | §4 #2 forbids `provider="tongyi"`. Provider stays auto-detected from URL. Test #11 verifies. |
| `validate_configs.py` rejects the entry (Option A not taken) | If P5-B reviewer picks Option B, the audit's fallback path is documented and known-safe. |
| Model identifier `"v4-flash"` doesn't match what gets served | Treated as a placeholder; reviewer confirms before merging P5-B. If unknown at P5-B merge time, prefer `"v4-flash-local-placeholder"` so the string is obviously not production. |
| Ledger consumers assume `provider=tongyi` based on stale docs | §5.3 reconciles the stale `MCP_COST_DISCIPLINE_PLAN.md:367` line. Test #11 pins the actual runtime provider value. |
| Hardware never gets provisioned and the profile lingers as dead config | Acceptable. The profile is data-only; it has zero runtime cost when unused. `_constraints` documents the manual-only requirement. |

## 7. P5 sub-phase split

| Sub-phase | Status | Scope |
|-----------|--------|-------|
| **P5-A** | **Done** (this doc) | Read-only audit + boundary lock-in. Docs-only. No runtime / test / profile / ledger / VERSION / tag changes. |
| **P5-B** | Not started | Smallest viable implementation slice per §5. Requires separate approval. Profile entry + optional `validate_configs.py` allowlist alignment + focused tests + stale-doc reconciliation. |
| **P5-C** | Not started, optional | Wire `_env`, model warmup helper, or per-profile `_provider` hint **only if** real operational usage reveals a need. Each requires a separate plan re-citing §2 / §4 / §6. |
| **P5-D** | Not started, optional | Docs/status closeout for the P5 chain (mirrors P3-E / P4-D pattern). |

P5-B is **not** authorized by P5-A. Any future implementation must
re-cite this §2 / §4 / §6 set verbatim.

## 8. Stop conditions

If during P5-B or later work any of these occur, **stop and escalate
to the human** instead of routing around them:

1. The profile entry needs a field whose name implies routing or
   dispatch (`_default_for`, `_promote_when`, `_auto_targets`,
   etc.).
2. A reviewer recommends "while we're here, also add a
   `provider=tongyi` shim to `tools/local_llm_worker.py`."
3. A reviewer recommends adding `v4_flash_local_experimental` to
   the P3 escalation chain or to a `tasks.json` `default_profile`.
4. The slice grows beyond the files listed in §5.4.
5. Anyone proposes making V4-Flash automatic at the commit gate,
   release audit, or any hook event.
6. `len(mcp.TOOLS)` drifts away from 9.
7. `PROBE_REPORT_SCHEMA_VERSION` changes.
8. `KNOWN_EXTRA_KEYS` in `tools/call_ledger.py` grows.

---

*Last updated: P5-A, HEAD `533e7b9` baseline.*
