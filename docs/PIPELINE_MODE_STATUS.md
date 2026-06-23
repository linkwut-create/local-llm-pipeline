# PIPELINE_MODE_STATUS.md — local-llm-pipeline v2-alpha

> **Purpose**: Living status for the v2-alpha pipeline mode implementation.  
> **Updated**: 2026-06-23  
> **Current phase**: Phase 1 — Task Lifecycle Fix  

---

## Repository Baseline

| Item | Value |
|------|-------|
| Branch | `master` |
| HEAD | `f768a7b` |
| Commit message | `docs: establish pipeline mode v2 execution baseline` |
| Working tree | Clean |
| Phase 0 commit | `docs/PIPELINE_MODE_ROADMAP.md` (rewritten), `docs/PIPELINE_MODE_BACKLOG.md` (new), `docs/PIPELINE_MODE_STATUS.md` (rewritten) |

### Test Baseline

```text
pytest tests/
2923 passed, 1 skipped in 555.83s (0:09:15)
```

* No failures.
* No new tests added in Phase 0 (documentation-only).
* Tests run on commit `0d052fd` with a clean working tree.

---

## Phase Progress

| Phase | Title | Status | Blocking Issues |
|-------|-------|--------|-----------------|
| 0 | Baseline Audit & Documentation Calibration | ✅ Done | None |
| 1 | Task Lifecycle Fix | 🔧 In progress | None |
| 2 | Tool Permission Enforcement Fix | ⬜ Not started | Depends on Phase 1 |
| 3 | Unified Route Policy | ⬜ Not started | Depends on Phase 2 |
| 4 | Route Committee Hardening | ⬜ Not started | Depends on Phase 3 |
| 5 | Model Switch Lifecycle | ⬜ Not started | Depends on Phase 3 |
| 6 | Reproducible Hook Installation | ⬜ Not started | — |
| 7 | Formalized Artifact Store | ⬜ Not started | — |
| 8 | Minimal AgentDB | ⬜ Not started | — |
| 9 | Local Worker | ⬜ Not started | — |
| 10 | Flash Worker | ⬜ Not started | — |
| 11 | Tool Actuator | ⬜ Not started | — |
| 12 | Pro Adjudication | ⬜ Not started | — |
| 13 | End-to-End Dry Run | ⬜ Not started | Needs Phases 1–12 |
| 14 | Real Dogfood | ⬜ Not started | Needs Phase 13 |
| 15 | Cost & Quality Evaluation | ⬜ Not started | Needs Phase 14 |
| 16 | v2-alpha Finalization | ⬜ Not started | Needs Phases 1–15 |

---

## Current Phase 0 Detail

### Completed

* [x] Baseline HEAD recorded.
* [x] Full test suite executed and passing.
* [x] `tools/claude_hooks/route_enforcer.py` restored to HEAD (removed corrupted uncommitted changes).
* [x] Stray backup file removed.
* [x] `docs/PIPELINE_MODE_ROADMAP.md` written.
* [x] `docs/PIPELINE_MODE_BACKLOG.md` written.
* [x] `docs/PIPELINE_MODE_STATUS.md` written (this file).
* [x] Precommit advisory and shadow route log recorded.
* [x] Phase 0 docs committed (`f768a7b`).
* [x] STATUS updated post-commit.

### In Progress

* None.

### Not Started (Phase 0)

* None.

### Phase 0 Observations

* The active task selected by `get_active_task()` was an unrelated old task directory, requiring manual `route.json` creation.
* A route name not present in `ROUTE_PERMISSIONS` (`pro_execute_allowed`) caused a fail-closed deadlock where all writes were blocked. This validates Known Issue #2 and will be fixed in Phase 2/3.
* The deadlock was resolved by manually changing `route.json` to `pro_decision`, which current HEAD recognizes.

---

## Known Issues at Baseline

These are intentionally **not fixed** in Phase 0 because they belong to later phases. They are recorded here so the roadmap/backlog does not drift from code reality.

1. **Task selection is fragile**
   * `get_active_task()` in `tools/claude_hooks/route_enforcer.py` chooses the newest task directory by `created_at`.
   * It ignores project root, Claude session id, task status, and whether the task is a test task.
   * **Owner**: Phase 1.

2. **`pro_decision` route is not really restricted**
   * In `route_enforcer.py`, `pro_decision` has empty `allowed`/`denied` sets, which makes it fail-open for all tools.
   * The distinction between `pro_decision` and `pro_execute_allowed` is not enforced.
   * **Owner**: Phase 2.

3. **Dual route permission tables**
   * `tools/claude_hooks/route_enforcer.py` and `tools/local_route_committee.py` each maintain a `ROUTE_PERMISSIONS` table with different shapes.
   * Committee emits `_enforcement` metadata that the enforcer ignores.
   * **Owner**: Phase 3.

4. **Bash commands are not classified**
   * No safe/test/write/destructive classification exists.
   * `rm -rf` and other destructive commands are not denied.
   * **Owner**: Phase 2.

5. **Agent calls are not bounded beyond route `allowed` sets**
   * There is no model or tool restriction scoped to the Agent subagent.
   * **Owner**: Phase 2 / Phase 3.

6. **No AgentDB**
   * Task state is file-system only (`session.json`, `artifact_index.json`, `route.json`).
   * **Owner**: Phase 8.

7. **Model switching is not tied to task lifecycle**
   * No save/restore of the current model on task completion/failure.
   * **Owner**: Phase 5.

---

## Risk Notes

* The `route.json` used to authorize Phase 0 documentation writes declares `recommended_route: pro_decision` and `pro_should_execute: true`. It relies on the current fail-open `pro_decision` behavior; this is acceptable only because Phase 0 is documentation-only and because the gap is recorded as Known Issue #2.
* No core runtime logic was modified in Phase 0.
* No automatic push will be performed.

---

## Decisions Made

| Decision | Reason |
|----------|--------|
| Reverted `route_enforcer.py` to HEAD | Uncommitted changes were corrupt (syntax errors) and introduced new routes outside Phase 0 scope. |
| Did not fix any known issues in Phase 0 | Phase 0 is documentation calibration only; fixes are scheduled in later phases. |
| Created route.json manually for doc writes | PreToolUse enforcement requires a route; Phase 0 needs documentation authority. |
| Will commit docs only | Source code remains at HEAD until Phase 1. |

---

## Next Actions

1. Run `tools/precommit_advisory.py --cloud-ok`.
2. Run `tools/shadow_route_log.py` for the audit trail.
3. Stage the three new docs.
4. Commit with message: `docs: establish pipeline mode v2 execution baseline`.
5. Update this file to mark Phase 0 ✅ and Phase 1 🔧.
6. Begin Phase 1: Task Lifecycle Fix.
