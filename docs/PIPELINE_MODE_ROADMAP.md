# PIPELINE_MODE_ROADMAP.md — local-llm-pipeline v2-alpha

> **Scope**: Claude Code Pipeline Mode v2-alpha  
> **Status**: Active  
> **Last reviewed**: 2026-06-23  

## Total Objective

Build a runnable Claude Code Pipeline Mode out of the existing pieces:

* Claude Code hooks (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`)
* Local Qwen + Gemma route committee
* Task session skeleton
* Route enforcement
* Artifact capture
* v1 router, privacy gate, cost ledger

Target workflow:

```text
User task
  → Cloud model generates plan.json
  → Local Qwen + Gemma review evidence and generate route.json
  → Hooks enforce route.json on critical tools
  → Local / Flash worker produces artifact
  → Tool layer applies patch, runs tests, saves diff
  → Cloud model reads artifact pack and adjudicates
  → AgentDB records task, cost, tests, and decisions
```

Core principles:

1. **Pro plans and adjudicates; it does not default to doing all execution.**
2. **The local route committee chooses the model and execution layer.**
3. **route.json is a constraint, not advice.**
4. **Every execution result is a traceable artifact.**
5. **Pro taking over execution requires explicit authorization and a logged reason.**

---

## Phase Order

Phases must be executed sequentially. Each phase is committed separately and documented in `PIPELINE_MODE_BACKLOG.md` and `PIPELINE_MODE_STATUS.md`.

| Phase | Title | Goal |
|-------|-------|------|
| 0 | Baseline Audit & Documentation Calibration | Confirm repository truth, eliminate doc drift, establish clean baseline. |
| 1 | Task Lifecycle Fix | Keep one task session across multi-turn conversations. |
| 2 | Tool Permission Enforcement Fix | Close Bash, Agent, and empty-whitelist bypasses. |
| 3 | Unified Route Policy | Single source of truth for route schema and permissions. |
| 4 | Route Committee Hardening | Controlled cross-review, deterministic merge, safe fallback. |
| 5 | Model Switch Lifecycle | Switch models per task phase and restore on completion/failure. |
| 6 | Reproducible Hook Installation | `install`/`status`/`uninstall`/`doctor` for Claude Code hooks. |
| 7 | Formalized Artifact Store | Task directory is a self-contained replay of one task. |
| 8 | Minimal AgentDB | SQLite record of tasks, routes, artifacts, calls, costs, decisions. |
| 9 | Local Worker | Structured local-model artifacts (summary, diff review, repo map). |
| 10 | Flash Worker | Constrained Flash patch/test-review artifacts. |
| 11 | Tool Actuator | Verified apply-patch, test-run, diff-capture, rollback. |
| 12 | Pro Adjudication | Structured decision from compressed evidence pack. |
| 13 | End-to-End Dry Run | Mock full pipeline in one command. |
| 14 | Real Dogfood | ≥5 real tasks using pipeline mode on itself. |
| 15 | Cost & Quality Evaluation | Compare direct Claude Code vs pipeline mode. |
| 16 | v2-alpha Finalization | Clean up, document, release alpha. |

---

## Architecture

```text
User Prompt
    │
    ▼
[UserPromptSubmit Hook]
    │  create task session; inject PLAN-ONLY
    ▼
Pro / Claude Code ──► plan.json
    │                    │
    │                    ▼
    │              [Stop Hook]
    │                    │  trigger route committee
    │                    ▼
    │              Qwen ──► qwen_initial.json
    │              Gemma ──► gemma_initial.json
    │              controlled disagreement round
    │                    │  deterministic merge
    │                    ▼
    │              route.json
    │                    │
    ▼                    ▼
[PreToolUse Hook] ◄── route enforcement
    │  allow / deny / ask
    ▼
Worker Layer:
    local_worker     ──► summaries, repo maps, diff reviews
    flash_worker     ──► patch_candidate.diff, failure analysis
    │
    ▼
Tool Actuator:
    apply_patch, run_tests, capture_diff, rollback
    │
    ▼
[PostToolUse Hook]
    │  save artifacts, update task state
    ▼
Pro Adjudication
    │  read artifact pack → accept / reject / retry / escalate
    ▼
[Stop Hook]
    │  finalize task, restore model, close session
    ▼
AgentDB + Artifact Store
```

---

## Route Taxonomy (v2-alpha)

| Route | Allowed Tools | Denied Tools | Bash Policy |
|-------|---------------|--------------|-------------|
| `blocked` | none | all | deny all |
| `ask_user` | `Read`, `Grep`, `Glob` | `Edit`, `Write`, `NotebookEdit`, `Agent`, `Bash` | deny all |
| `local_only` | `Read`, `Grep`, `Glob`, `local_worker` | `Edit`, `Write`, `NotebookEdit`, `Agent` | safe read/test only |
| `local_summary` | `Read`, `Grep`, `Glob`, `local_worker` | `Edit`, `Write`, `NotebookEdit`, `Agent` | safe read/test only |
| `flash_worker` | `Read`, `Grep`, `Glob`, `flash_worker` | Pro direct `Edit`/`Write` | safe read/test only |
| `flash_subagent` | `Read`, `Grep`, `Glob`, `Agent` | — | Agent bound to Flash profile |
| `pro_decision` | `Read`, `Grep`, `Glob` | `Edit`, `Write` | test/status/diff only |
| `pro_execute_allowed` | necessary `Edit`/`Write`/`Bash` | destructive / sensitive | deny destructive |

---

## Definition of Done for v2-alpha

* [ ] Multi-turn messages keep the same task session.
* [ ] Hooks are reproducibly installable.
* [ ] No plan → critical execution blocked.
* [ ] No route → critical execution blocked.
* [ ] Bash cannot bypass route permissions.
* [ ] Agent cannot bypass `blocked`/`local` routes.
* [ ] `pro_decision` and `pro_execute_allowed` are strictly separated.
* [ ] Route policy has a single source of truth.
* [ ] Qwen/Gemma routing fails safely to `pro_decision`.
* [ ] Model switches are reversible.
* [ ] Local worker produces structured artifacts.
* [ ] Flash worker produces patch candidates.
* [ ] Tool actuator applies patches and runs tests.
* [ ] Pro outputs structured adjudication.
* [ ] AgentDB can query a complete task history.
* [ ] ≥5 real dogfood tasks completed.
* [ ] Direct vs pipeline cost comparison exists.
* [ ] Full test suite passes.
* [ ] Docs and code state are consistent.

---

## Paused Items (post v2-alpha)

The following are intentionally out of scope until v2-alpha is done:

* New MCP tool extensions.
* New complex skills / commands.
* Vector database integration.
* UI.
* Cross-machine control platform.
* Multi-project orchestration.
* Automatic push / deploy.
* Long-term autonomous development.
* Model performance leaderboards unrelated to pipeline mode.
* Inference backend migrations not required by pipeline mode.
* Profile system expansion beyond the committee's needs.

If any of these becomes a hard dependency for a v2-alpha phase, the dependency must be justified in `PIPELINE_MODE_STATUS.md` before work begins.
