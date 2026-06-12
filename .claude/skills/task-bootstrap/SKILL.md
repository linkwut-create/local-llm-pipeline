---
name: task-bootstrap
description: Bootstrap a new task by running local_workflow_plan, reading governance docs, and producing a complete task packet ready for delegation.
---

# Task Bootstrap Skill

This skill replaces the manual "read AGENTS.md, check PROBLEMS.md, plan, delegate" loop with a single slash command.

## Trigger

```
/task-bootstrap <task description>
```

## Workflow

### Step 1: Classify

Run `local_workflow_plan` (pure heuristic, no LLM cost) to classify:
- Workflow type
- Risk level
- Whether debate is required
- Estimated cost

### Step 2: Read Relevant Governance Sections

Based on the workflow type, read only what's needed:

| Workflow Type | Read |
|--------------|------|
| `docs-only-change` | PROBLEMS.md §2, §5 |
| `small-code-change` | AGENTS.md §7, PROBLEMS.md §2, §3, §5 |
| `high-risk-runtime-change` | All of PROBLEMS.md, INTERFACES.md §6, §7 |
| `release-local-checkpoint` | Everything + LONGTODO.md |

### Step 3: Identify Affected Files

Use `git ls-files | py -3 tools/local_llm_router.py find-related-files --stdin` to identify:
- Primary files to edit
- Related test files
- Affected subsystems

### Step 4: Generate Task Packet

Produce a structured task packet following the format in `project-governance` skill.

### Step 5: Summarize Key Files

For each file > 200 lines in the "Allowed Files" list, run `local_summarize_file` (if local models are available).

### Step 6: Output Final Brief

```markdown
## Task Bootstrap Complete

**Task**: <summary>
**Risk**: low | medium | high
**Debate Required**: yes | no
**Cloud Escalation**: none | flash | pro
**Estimated Cost**: N seconds local + N USD cloud

### Files to Edit
1. `path` — role

### Do Not Touch
- `path` — reason

### Test Plan
- Run: `pytest path -q`

### Next Step
Delegate to: `planner` | `code-worker` | manual review needed
```
