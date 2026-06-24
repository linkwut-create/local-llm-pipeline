# PIPELINE_MODE_BACKLOG.md — local-llm-pipeline v2-alpha

> **Purpose**: Single source for all v2-alpha work items, their state, and binding acceptance criteria.  
> **Last updated**: 2026-06-23  
> **Current phase**: Phase 14 — Real Dogfood (not started)  
> **Phases completed**: 0–13 (all committed)  

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

**Goal**: Confirm the latest repository state, eliminate documentation drift, and establish a clean baseline before modifying core pipeline logic. ✅ **COMPLETE** (`f768a7b`)

---

## Phase 1 — Task Lifecycle Fix

**Goal**: Ensure one development task keeps the same task session across multiple Claude Code turns. ✅ **COMPLETE** (`b0f753d`)

---

## Phase 2 — Tool Permission Enforcement Fix

**Goal**: Close bypasses through Bash, Agent, and ambiguous empty-whitelist routes. ✅ **COMPLETE** (`30ace01`)

---

## Phase 3 — Unified Route Policy

**Goal**: One source of truth for route schema and permissions. ✅ **COMPLETE** (`eb5b871`)

---

## Phase 4 — Route Committee Hardening

**Goal**: Stable, explainable, verifiable route.json output.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
**Goal**: Stable, explainable, verifiable route.json output. ✅ **COMPLETE** (`03d7587`)

---

## Phase 5 — Model Switch Lifecycle

**Goal**: Model changes align with task phase and are restored afterwards. ✅ **COMPLETE** (`8f2de45`)

---

## Phase 6 — Reproducible Hook Installation

**Goal**: A fresh clone can install, check, and remove pipeline hooks with one command. ✅ **COMPLETE** (`8754f8d`)

---

## Phase 7 — Formalized Artifact Store

**Goal**: A task directory can replay the entire task without reading chat history. ✅ **COMPLETE** (`8e0f628`)

---

## Phase 8 — Minimal AgentDB

**Goal**: SQLite stores structured task facts; filesystem stores large artifacts. ✅ **COMPLETE** (`694c08a`)

---

## Phase 9 — Local Worker

**Goal**: Local models produce structured low-level artifacts. ✅ **COMPLETE** (`0123ae8`)

---

## Phase 10 — Flash Worker

**Goal**: Low-cost cloud model produces candidate artifacts, never direct commits. ✅ **COMPLETE** (`7639218`)

---

## Phase 11 — Tool Actuator

**Goal**: Mechanical, verified actions from model candidates. ✅ **COMPLETE** (`f65f624`)

---

## Phase 12 — Pro Adjudication

**Goal**: Pro decides from a compressed artifact pack, not by re-executing everything. ✅ **COMPLETE** (`bf26b40`)

---

## Phase 13 — End-to-End Dry Run

**Goal**: One command runs the full pipeline with mocks.

### Work Items

| # | Item | State | Notes |
|---|------|-------|-------|
| 13.1 | Build mock plan generator | ✅ DONE | pipeline_mocks.py |
| 13.2 | Build mock Qwen/Gemma | ✅ DONE | pipeline_mocks.py |
| 13.3 | Build mock local/Flash workers | ✅ DONE | pipeline_mocks.py |
| 13.4 | Build mock Pro decision | ✅ DONE | pipeline_mocks.py |
| 13.5 | Wire task session, route, enforcement, artifact, test, adjudication, AgentDB | ✅ DONE | pipeline_e2e_dry_run.py |
| 13.6 | Add tests covering all route types and failure modes | ✅ DONE | 25 tests pass, 256 total |

### Acceptance Criteria

* [x] One command runs the full dry-run and produces task artifacts and DB records.

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
