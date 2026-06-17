# PIPELINE_MODE_ROADMAP.md — local-llm-pipeline v2

> **Status**: Active planning (2026-06-17)
> **Phase**: Hook adapter hardening → route enforcement → worker artifact → Pro adjudication
> **Current completion**: ~20-25% (pipeline mode usable); ~30-35% (multi-model code-agent prototype)

## 0. Total Objective

`local-llm-pipeline v2` targets Claude Code Pipeline Mode:

```
Claude Code / Pro cloud model:
  Accept task, initial understanding, generate plan, final adjudication.

Local Qwen 27B + Gemma 31B:
  Local routing intelligence layer — read plan + evidence pack,
  debate, output route.json.

Flash / low-cost cloud model:
  Mid-level execution — patch candidate, test failure analysis,
  local fix proposals, diff first-pass review.

Local small models:
  Low-level processing — log summary, file summary, repo map,
  context compression, keyword scanning.

Tool layer:
  Real actions — read/write files, apply patch, run tests, git diff.

AgentDB / artifact store:
  Record task state, plan, route, model calls, patches, test logs,
  diffs, costs, final decisions.
```

Core principle:

```
Pro can be the first to accept a task, but must not default to
executing all heavy work. Critical nodes must be checked by hooks
against task state and route.json. route.json must evolve from
advisory suggestion to execution constraint.
```

## 1. Architecture

```
User Prompt
    │
    ▼
[UserPromptSubmit Hook]
    │  create task session, inject PLAN-ONLY
    ▼
Pro / Claude Code ──► plan.json
    │                    │
    │                    ▼
    │              [Stop Hook]
    │                    │  trigger route committee
    │                    ▼
    │              Qwen 27B ──► qwen_judgement.json
    │              Gemma 31B ──► gemma_judgement.json
    │                    │  deterministic merge
    │                    ▼
    │              route.json
    │                    │
    ▼                    ▼
[PreToolUse Hook] ◄── route enforcement
    │  allow / deny / ask_user
    ▼
Worker Layer:
    local_summary_worker ──► summaries, repo maps
    flash_patch_worker   ──► patch_candidate.diff
    flash_failure_analyzer ─► failure analysis
    │
    ▼
Tool Layer:
    apply_patch, run_tests, capture diffs
    │
    ▼
[PostToolUse Hook]
    │  save artifacts, update task state
    ▼
Pro Adjudication
    │  read artifact pack → accept / reject / retry / escalate
    ▼
[Stop Hook]
    │  finalize task, close session
```

## 2. Phase Breakdown

### Phase A: Hook Closure (current focus)

| # | Module | Status | Target |
|---|--------|--------|--------|
| A1 | route_enforcer main() + stdin dispatch | ✅ Done (2026-06-17) | subprocess-tested |
| A2 | Hook registration in settings.local.json | ✅ Done (2026-06-17) | 4 events registered |
| A3 | PreToolUse matcher tuning | 🔧 Partial | targeted deny for Edit/Write/Bash |
| A4 | PostToolUse artifact capture hardening | 🔧 Partial | test logs, diffs, tool metadata |
| A5 | Stop hook route committee auto-trigger | 🔧 Partial | plan→route pipeline |
| A6 | End-to-end hook loop test | ⬜ TODO | real Claude Code session |

### Phase B: Route Committee Hardening

| # | Module | Status | Target |
|---|--------|--------|--------|
| B1 | Committee model config (env vars, no hardcode) | 🔧 Partial | `LOCAL_ROUTE_QWEN_MODEL` etc. |
| B2 | Qwen role: delegability + engineering judgment | 🔧 Partial | structured JSON output |
| B3 | Gemma role: risk + conservatism + privacy check | 🔧 Partial | structured JSON output |
| B4 | Deterministic merge rules hardening | 🔧 Partial | consistent on repeated runs |
| B5 | route.json schema validator | 🔧 Partial | reject invalid routes |
| B6 | Committee timeout/error fallback to pro_decision | ✅ Done | 120s timeout, retry, fallback |

### Phase C: AgentDB + Artifact Store

| # | Module | Status | Target |
|---|--------|--------|--------|
| C1 | Task session directory structure | 🔧 Partial | fixed layout per task_id |
| C2 | Artifact metadata schema | ⬜ TODO | type, creator, model, accepted |
| C3 | SQLite AgentDB (tasks, artifacts, calls, costs) | ⬜ TODO | queryable task history |
| C4 | Cost ledger v2 integration | 🔧 Partial | per-task, per-model breakdown |

### Phase D: Worker + Tool Layer

| # | Module | Status | Target |
|---|--------|--------|--------|
| D1 | local_summary_worker artifact output | ⬜ TODO | structured summaries |
| D2 | flash_patch_worker (diff output only) | ⬜ TODO | patch_candidate.diff |
| D3 | flash_failure_analyzer | ⬜ TODO | failure cause candidates |
| D4 | apply_patch tool | ⬜ TODO | trackable, rollback-able |
| D5 | test runner artifact capture | 🔧 Partial | logs + pass/fail parse |

### Phase E: Pro Adjudication

| # | Module | Status | Target |
|---|--------|--------|--------|
| E1 | Adjudication input pack schema | ⬜ TODO | compressed evidence |
| E2 | Pro decision output format (structured JSON) | ⬜ TODO | accept/reject/retry/escalate |
| E3 | Pro override mechanism + audit record | ⬜ TODO | justified, recorded |

### Phase F: Safety + Observability

| # | Module | Status | Target |
|---|--------|--------|--------|
| F1 | Secrets/.env protection in PreToolUse | 🔧 Partial | hard deny |
| F2 | Destructive command guard | 🔧 Partial | rm/git reset/curl pipe |
| F3 | Bash command tiering (safe/medium/danger) | ⬜ TODO | per-route permissions |
| F4 | Audit log (allow/deny/ask/override) | 🔧 Partial | full replay |
| F5 | Pipeline status CLI command | ⬜ TODO | why-is-it-blocked |

## 3. Route → Permission Mapping

| Route | Allowed Tools | Denied Tools | Notes |
|-------|--------------|--------------|-------|
| `blocked` | none | all | Hard stop |
| `ask_user` | Read, Grep, Glob | Edit, Write, Bash, Agent | Pending human |
| `local_only` | Read, Grep, Glob, Bash | Edit, Write, NotebookEdit | No cloud |
| `local_summary` | Read, Grep, Glob, Bash | Edit, Write | Summary artifacts only |
| `flash_worker` | Read, Grep, Glob, worker tools | Pro direct Edit/Write | Flash artifacts |
| `flash_direct` | Read, Grep, Glob, Bash, Write, Task, Skill | Edit, NotebookEdit | Limited cloud |
| `flash_subagent` | Read, Grep, Glob, Bash, Write, Edit, Task, Skill | — | Full cloud agent |
| `pro_decision` | Read, Grep, Glob | Edit, Write, Bash (ask) | Pro must decide |
| `pro_execute_allowed` | all (record mandatory) | — | Pro override |

## 4. Success Criteria

### Level 1: Hook Control Established
- [ ] No task session → critical execution blocked
- [ ] No plan → critical execution blocked
- [ ] No route → critical execution blocked
- [ ] route=blocked → hard stop
- [ ] route=ask_user → pause
- [ ] route=pro_decision → record Pro continuation reason

### Level 2: Local Routing Established
- [ ] Qwen/Gemma read plan
- [ ] Qwen/Gemma output structured judgment
- [ ] Dual-model disagreement resolved by merge rules
- [ ] route.json consumed by PreToolUse

### Level 3: Worker Artifact Established
- [ ] Local worker produces summary artifacts
- [ ] Flash worker produces patch candidate artifacts
- [ ] Tool layer applies patches
- [ ] Tool layer runs tests
- [ ] Artifacts saved and replayable

### Level 4: Pro Adjudication Established
- [ ] Pro reads artifact pack
- [ ] Pro outputs structured decision
- [ ] Pro does not default to re-executing all work
- [ ] Pro override is recorded

### Level 5: Cost Improvement
- [ ] Pro token share decreases
- [ ] Flash/local artifacts have real contribution
- [ ] Total task cost does not increase
- [ ] Rework count does not significantly increase
- [ ] Task quality does not decrease

## 5. Current Completion Estimate

```
Ordinary local LLM toolbox completion:  65-75%
Multi-model code-agent prototype:       30-35%
Claude Code pipeline mode usable:       20-25%
```

## 6. Paused / Deferred

Until hook closure, route enforcement, AgentDB, and worker artifacts are proven:

- New MCP tools
- New complex Claude commands
- New complex skills
- New complex subagents
- Vector database
- UI
- Cross-project deployment
- Full agent loop
- Model leaderboards
- Release automation
- Push/deploy automation

## 7. Reference

- Current status: [PIPELINE_MODE_STATUS.md](PIPELINE_MODE_STATUS.md)
- Project backlog: [PIPELINE_MODE_BACKLOG.md](PIPELINE_MODE_BACKLOG.md) (TBD)
- Governance: [AGENTS.md](../AGENTS.md), [PROBLEMS.md](../PROBLEMS.md)
- Long-term roadmap: [LONGTODO.md](../LONGTODO.md)
