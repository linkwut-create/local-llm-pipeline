---
name: project-governance
description: Audit project governance docs and produce a minimal task plan. Reads AGENTS.md, PROBLEMS.md, INTERFACES.md, and optionally LONGTODO.md.
---

# Project Governance Skill

This skill encapsulates the governance document workflow for every non-trivial task.

## Trigger

Use before starting any implementation task:
```
/project-governance <task description>
```

Or to audit an existing task:
```
/project-governance audit <task description>
```

## Workflow

### Step 1: Read Governance Files

Read only the sections relevant to the task:

1. `AGENTS.md` §0 (identity), §1 (principles), §2 (architecture map), §7 (hard no)
2. `PROBLEMS.md` §2 (forbidden patterns), §3 (fragile areas), §5 (review checklist)
3. `INTERFACES.md` — only if task touches API/CLI/config/MCP/provider
4. `LONGTODO.md` — only if task touches roadmap or long-term requirements

### Step 2: Classify the Task

Output:
- Task type: `bug-fix | feature | refactor | docs | release-prep | audit`
- Risk level: `low | medium | high`
- Cloud escalation needed: `none | flash | pro`
- Debate review required: `yes | no`

### Step 3: Produce Task Packet

```markdown
## Task Packet: <summary>

### Governance Rules
- AGENTS.md §X: ...
- PROBLEMS.md BAN-XXX: ...

### Allowed Files
- `path/to/file` — reason

### Forbidden Changes
- Do not modify: ...
- Do not change interfaces: ...

### Required Tests
- ...

### Suggested Subagents
- planner: yes/no
- code-worker: yes/no
- reviewer: yes/no
```

### Step 4: Delegate

Based on the task packet, dispatch to the appropriate subagent:
- Complex/ambiguous → `planner` first
- Well-scoped implementation → `code-worker`
- Review needed → `reviewer`
