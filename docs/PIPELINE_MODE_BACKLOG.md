# PIPELINE_MODE_BACKLOG.md — local-llm-pipeline v2-alpha

> **Purpose**: Single source for all v2-alpha work items, their state, and binding acceptance criteria.  
> **Last updated**: 2026-06-23  
> **Current phase**: Phase 0 — Baseline Audit & Documentation Calibration (in progress)  

---

## Legend

| State | Meaning |
|-------|---------|
| ⬜ TODO | Not started. |
| 🔧 IN PROGRESS | Work started, not yet accepted. |
| ✅ DONE | Acceptance criteria met and committed. |
| 🚫 BLOCKED | Cannot proceed; blocker recorded. |
| ⏸️ PAUSED | Intentionally deferred. |

---

## Phase 0 — Baseline Audit & Documentation Calibration

**Goal**: Confirm the latest repository state, eliminate documentation drift, and establish a clean baseline before modifying core pipeline logic.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 0.1 | Record branch, HEAD, working tree state | ✅ DONE | master @ 0d052fd; restored `route_enforcer.py` to HEAD; removed stray `.bak` file. |
| 0.2 | Audit `tools/claude_hooks/route_enforcer.py` | ✅ DONE | HEAD version lacks `pro_execute_allowed`, `plan_only`, plan-hash, and `allowed_tools` authority. These are Phase 2/3 work. |
| 0.3 | Audit `tools/local_route_committee.py` | ✅ DONE | Has independent `ROUTE_PERMISSIONS` table; overlaps with enforcer and uses different shape. Phase 3 will unify. |
| 0.4 | Audit route schema | ✅ DONE | Committee emits `_enforcement`; enforcer does not consume it. Divergence to be fixed in Phase 3. |
| 0.5 | Audit task session | ✅ DONE | Implemented inside `route_enforcer.py`; `get_active_task()` selects by `created_at` only. Phase 1 will harden. |
| 0.6 | Audit artifact capture | ✅ DONE | `save_artifact_indexed` + `artifact_index.json` exist; accepted/rejected tracking missing. Phase 7 will formalize. |
| 0.7 | Audit privacy gate | ✅ DONE | Rule-based, no API calls, advisory-only. Ready for integration tests. |
| 0.8 | Audit cost ledger | ✅ DONE | JSONL ledger, mock pricing, budget guard skeleton. Ready for integration. |
| 0.9 | Run baseline tests | ✅ DONE | `pytest tests/` → 2923 passed, 1 skipped (555.83 s). |
| 0.10 | Write `docs/PIPELINE_MODE_ROADMAP.md` | ✅ DONE | Phase 0–16 order, architecture, route taxonomy, Definition of Done. |
| 0.11 | Create `docs/PIPELINE_MODE_BACKLOG.md` | ✅ DONE | This file. |
| 0.12 | Write `docs/PIPELINE_MODE_STATUS.md` | ✅ DONE | Updated post-commit. |

### Acceptance Criteria

* [x] Working tree state is explicit.
* [x] Documents match code state.
* [x] All subsequent phases are listed in backlog.
* [x] Current known issues are explicitly recorded.

### Known Issues Recorded

1. `get_active_task()` picks the newest directory by `created_at`; it ignores project root, Claude session, status, and test-task flag.
2. `pro_decision` route in `route_enforcer.py` has empty `allowed`/`denied` sets and therefore allows all tools — the `pro_decision` vs `pro_execute_allowed` distinction is not enforced.
3. `local_route_committee.py` and `route_enforcer.py` maintain separate permission tables with different shapes.
4. Route schema has no single validator; committee emits `_enforcement` that enforcer ignores.
5. Bash commands are not classified into safe/test/write/destructive tiers.
6. Agent calls are not restricted beyond route `allowed` sets.
7. No AgentDB; task state is file-system only.
8. Model switching is not tied to task lifecycle completion/failure.

---

## Phase 1 — Task Lifecycle Fix

**Goal**: Ensure one development task keeps the same task session across multiple Claude Code turns.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 1.1 | Extend `session.json` schema with `status`, `project_root`, `claude_session_id`, `parent_task_id`, `is_test_task` | ⬜ TODO | |
| 1.2 | Define active-task selection rules (project root, session id, status not terminal, not test, not discarded) | ⬜ TODO | |
| 1.3 | Update `UserPromptSubmit` to append messages to active task instead of creating new task for continuation words | ⬜ TODO | |
| 1.4 | Implement control-statement detection (`继续`, `批准`, `运行测试`, `重试`, `接受`, `拒绝`, `停止`, `取消任务`, `新建任务`) | ⬜ TODO | |
| 1.5 | Add task control functions: `create_task`, `get_active_task`, `append_task_message`, `set_task_status`, `complete_task`, `cancel_task`, `resume_task` | ⬜ TODO | |
| 1.6 | Test isolation: all tests use temporary directories | ⬜ TODO | |
| 1.7 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] A multi-turn task uses the same `task_id` until explicitly completed, failed, cancelled, or a new task is requested.
* [ ] Tests cover: first-message creation, message reuse, completed task exclusion, project isolation, session isolation, test non-pollution, explicit new-task creation.

---

## Phase 2 — Tool Permission Enforcement Fix

**Goal**: Close bypasses through Bash, Agent, and ambiguous empty-whitelist routes.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 2.1 | Disambiguate `allowed_tools = null` vs `[]` vs explicit whitelist | ⬜ TODO | |
| 2.2 | Fail-closed when route is missing/unparseable | ⬜ TODO | |
| 2.3 | Separate `pro_decision` and `pro_execute_allowed` | ⬜ TODO | |
| 2.4 | Define safe route permission tables | ⬜ TODO | |
| 2.5 | Implement Bash command classifier (safe_readonly, safe_test, workspace_write, dependency_change, destructive, network_or_remote, unknown) | ⬜ TODO | |
| 2.6 | Restrict Agent by route and record Agent input/model/result | ⬜ TODO | |
| 2.7 | Add/update tests for every bypass case | ⬜ TODO | |

### Acceptance Criteria

* [ ] No route + Bash write → deny.
* [ ] `local_only` + Bash write → deny.
* [ ] `blocked` + Agent → deny.
* [ ] `pro_decision` + Edit → deny.
* [ ] `pro_execute_allowed` + Edit → allow.
* [ ] `pro_execute_allowed` + `rm -rf` → deny.
* [ ] Safe test commands → allow.
* [ ] Unknown Bash → ask/deny.

---

## Phase 3 — Unified Route Policy

**Goal**: One source of truth for route schema and permissions.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 3.1 | Create `tools/pipeline_route_policy.py` | ⬜ TODO | |
| 3.2 | Migrate route enums, schema, permission mapping, Bash policy, risk escalation, validator, fallback into policy module | ⬜ TODO | |
| 3.3 | Remove duplicate tables from `route_enforcer.py` and `local_route_committee.py` | ⬜ TODO | |
| 3.4 | Migrate old route names (`flash_direct`, `claude_code_pro`, `manual_confirm`) with explicit mapping | ⬜ TODO | |
| 3.5 | Implement schema validation and safe downgrade | ⬜ TODO | |
| 3.6 | Add snapshot tests for route policy | ⬜ TODO | |

### Acceptance Criteria

* [ ] Committee-generated route and Enforcer interpretation are identical.
* [ ] Invalid schema triggers fail-closed downgrade.
* [ ] Old route names are migrated deterministically.
* [ ] Same route produces same permissions in every module.

---

## Phase 4 — Route Committee Hardening

**Goal**: Stable, explainable, verifiable route.json output.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 4.1 | Move model names to env/config (`LOCAL_ROUTE_QWEN_MODEL`, `LOCAL_ROUTE_GEMMA_MODEL`) | ⬜ TODO | |
| 4.2 | Detect model availability before calling | ⬜ TODO | |
| 4.3 | Record call latency, input summary, output path | ⬜ TODO | |
| 4.4 | Fix Qwen/Gemma roles and prompts | ⬜ TODO | |
| 4.5 | Implement one-round controlled disagreement | ⬜ TODO | |
| 4.6 | Implement deterministic merge rules | ⬜ TODO | |
| 4.7 | Save evidence pack artifact | ⬜ TODO | |
| 4.8 | Add/update tests for failure modes | ⬜ TODO | |

### Acceptance Criteria

* [ ] Both models agree.
* [ ] Both models disagree.
* [ ] Qwen/Gemma timeout.
* [ ] Both unavailable.
* [ ] Invalid JSON.
* [ ] Privacy blocked.
* [ ] High risk.
* [ ] Disagreement round limit enforced.

---

## Phase 5 — Model Switch Lifecycle

**Goal**: Model changes align with task phase and are restored afterwards.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 5.1 | Define model roles: planner, router, worker, adjudicator, override_executor | ⬜ TODO | |
| 5.2 | Define switch rules per phase | ⬜ TODO | |
| 5.3 | Save/restore model in `session.json` (`initial_model`, `current_model`, `previous_model`, `target_model`, `model_switch_reason`) | ⬜ TODO | |
| 5.4 | Restore initial model on completion/failure/cancellation | ⬜ TODO | |
| 5.5 | Avoid global config mutation | ⬜ TODO | |
| 5.6 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] `flash_subagent` does not switch the main session model.
* [ ] `flash_worker` returns to Pro adjudication.
* [ ] Task completion/failure restores initial model.
* [ ] Multiple tasks do not pollute each other's model state.

---

## Phase 6 — Reproducible Hook Installation

**Goal**: A fresh clone can install, check, and remove pipeline hooks with one command.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 6.1 | Implement `pipeline hooks install` | ⬜ TODO | |
| 6.2 | Implement `pipeline hooks status` | ⬜ TODO | |
| 6.3 | Implement `pipeline hooks uninstall` | ⬜ TODO | |
| 6.4 | Implement `pipeline hooks doctor` | ⬜ TODO | |
| 6.5 | Provide config template and installation docs | ⬜ TODO | |
| 6.6 | Handle Windows/POSIX paths and Python detection | ⬜ TODO | |
| 6.7 | Backup existing settings, idempotent install, safe uninstall | ⬜ TODO | |
| 6.8 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] Empty settings install.
* [ ] Existing settings merge.
* [ ] Repeated install is idempotent.
* [ ] Uninstall removes only this project's hooks.
* [ ] Invalid Python path handled.
* [ ] Windows and POSIX path formats handled.

---

## Phase 7 — Formalized Artifact Store

**Goal**: A task directory can replay the entire task without reading chat history.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 7.1 | Define fixed directory layout under `.local_llm_out/tasks/<task_id>/` | ⬜ TODO | |
| 7.2 | Define artifact metadata schema (creator, model, time, dependencies, hash, accepted, verified) | ⬜ TODO | |
| 7.3 | Implement artifact reader and task report | ⬜ TODO | |
| 7.4 | Prevent name collisions | ⬜ TODO | |
| 7.5 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] Directory layout matches specification.
* [ ] Artifact metadata is complete.
* [ ] Task report can be generated from directory alone.

---

## Phase 8 — Minimal AgentDB

**Goal**: SQLite stores structured task facts; filesystem stores large artifacts.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 8.1 | Design schema (tasks, messages, routes, artifacts, model_calls, test_runs, patch_candidates, decisions, costs, tool_calls, overrides) | ⬜ TODO | |
| 8.2 | Implement `agentdb init` | ⬜ TODO | |
| 8.3 | Implement `agentdb import-task` | ⬜ TODO | |
| 8.4 | Implement `agentdb task`, `agentdb recent`, `agentdb report`, `agentdb costs` | ⬜ TODO | |
| 8.5 | Ensure DB writes cannot break task execution | ⬜ TODO | |
| 8.6 | Support backfill from existing task directories | ⬜ TODO | |
| 8.7 | Add/update tests with temp DB | ⬜ TODO | |

### Acceptance Criteria

* [ ] Can query current task phase, route, model actions, patch adoption, test result, Pro override, total cost.

---

## Phase 9 — Local Worker

**Goal**: Local models produce structured low-level artifacts.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 9.1 | Define `local_log_summary` worker | ⬜ TODO | |
| 9.2 | Define `local_file_summary` worker | ⬜ TODO | |
| 9.3 | Define `local_diff_review` worker | ⬜ TODO | |
| 9.4 | Define `repo_map` worker | ⬜ TODO | |
| 9.5 | Define worker contract (input schema, read scope, output schema, timeout, max context, failure fallback, forbidden tools, artifact type) | ⬜ TODO | |
| 9.6 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] At least one real task uses a local worker artifact in a downstream route or Pro decision.

---

## Phase 10 — Flash Worker

**Goal**: Low-cost cloud model produces candidate artifacts, never direct commits.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 10.1 | Define `flash_test_failure_analyzer` | ⬜ TODO | |
| 10.2 | Define `flash_patch_worker` | ⬜ TODO | |
| 10.3 | Define `flash_diff_reviewer` | ⬜ TODO | |
| 10.4 | Enforce Flash constraints (no commit/push/deploy, unified diff, artifact output, tool-layer apply) | ⬜ TODO | |
| 10.5 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] At least one real task's Flash patch candidate is applied and passes tests, or is rejected by Pro with a logged reason.

---

## Phase 11 — Tool Actuator

**Goal**: Mechanical, verified actions from model candidates.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 11.1 | Implement `apply_patch` with pre/post diff, allowed-file check, sensitive-file check, error capture, rollback | ⬜ TODO | |
| 11.2 | Implement test runner with command detection, log capture, pass/fail parse, duration, DB record | ⬜ TODO | |
| 11.3 | Implement diff capture at key points | ⬜ TODO | |
| 11.4 | Implement rollback scoped to this task | ⬜ TODO | |
| 11.5 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] Patch application, testing, diff capture, and rollback are all traceable and do not destroy existing user work.

---

## Phase 12 — Pro Adjudication

**Goal**: Pro decides from a compressed artifact pack, not by re-executing everything.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 12.1 | Define adjudication pack schema | ⬜ TODO | |
| 12.2 | Define Pro decision output schema | ⬜ TODO | |
| 12.3 | Implement override flow with route change, reason, file/tool limits, verification | ⬜ TODO | |
| 12.4 | Add/update tests | ⬜ TODO | |

### Acceptance Criteria

* [ ] Pro can accept/reject/retry/escalate/cancel from artifact pack.
* [ ] Pro override is logged and bounded.

---

## Phase 13 — End-to-End Dry Run

**Goal**: One command runs the full pipeline with mocks.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 13.1 | Build mock plan generator | ⬜ TODO | |
| 13.2 | Build mock Qwen/Gemma | ⬜ TODO | |
| 13.3 | Build mock local/Flash workers | ⬜ TODO | |
| 13.4 | Build mock Pro decision | ⬜ TODO | |
| 13.5 | Wire task session, route, enforcement, artifact, test, adjudication, AgentDB | ⬜ TODO | |
| 13.6 | Add tests covering all route types and failure modes | ⬜ TODO | |

### Acceptance Criteria

* [ ] One command runs the full dry-run and produces task artifacts and DB records.

---

## Phase 14 — Real Dogfood

**Goal**: Use pipeline mode on its own development tasks.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 14.1 | Pick low-risk tasks (test failures, local bugs, doc/test sync) | ⬜ TODO | |
| 14.2 | Record per-task metrics (tokens, routing, artifacts, tests, decisions, cost, time, rework, intervention) | ⬜ TODO | |
| 14.3 | Complete ≥5 real tasks with required mix | ⬜ TODO | |

### Acceptance Criteria

* [ ] ≥5 real tasks completed.
* [ ] ≥2 Flash patch tasks.
* [ ] ≥1 local-only task.
* [ ] ≥1 Pro escalation.
* [ ] ≥1 blocked or ask_user.

---

## Phase 15 — Cost & Quality Evaluation

**Goal**: Determine whether the architecture actually reduces Pro consumption.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 15.1 | Define comparable task pairs (direct vs pipeline) | ⬜ TODO | |
| 15.2 | Record Pro/Flash/local tokens, cost, time, pass rate, rework, intervention, diff quality | ⬜ TODO | |
| 15.3 | Analyze and document results honestly | ⬜ TODO | |

### Acceptance Criteria

* [ ] Pro token share decreases.
* [ ] Total cost does not increase.
* [ ] Quality does not decrease.
* [ ] Rework does not significantly increase.
* [ ] Local/Flash artifacts are actually adopted.
* [ ] Failures are documented with cause, not hidden by feature expansion.

---

## Phase 16 — v2-alpha Finalization

**Goal**: A clean, installable, verifiable, replayable alpha.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 16.1 | Remove obsolete route names | ⬜ TODO | |
| 16.2 | Remove duplicate permission tables | ⬜ TODO | |
| 16.3 | Clean test-generated task directories from real `.local_llm_out/tasks/` | ⬜ TODO | |
| 16.4 | Complete install, troubleshooting, and security boundary docs | ⬜ TODO | |
| 16.5 | Complete config samples and migration notes | ⬜ TODO | |
| 16.6 | Run full test suite | ⬜ TODO | |
| 16.7 | Ensure clean working tree | ⬜ TODO | |
| 16.8 | Generate final status report | ⬜ TODO | |

### Acceptance Criteria

* [ ] All Definition of Done items checked or explicitly rejected with reason.
* [ ] Full test suite passes.
* [ ] Docs and code state are consistent.
* [ ] Working tree is clean.

---

## Global Rules

1. **One phase per commit** — never mix phases.
2. **Tests must pass before proceeding** — targeted tests + relevant regression tests.
3. **No automatic push**.
4. **No scope expansion** into paused items.
5. **No deletion of v1 features** without test-proven conflict.
6. **All new behavior must have tests**.
7. **Documentation is the source of state** — update BACKLOG and STATUS after every phase commit.
