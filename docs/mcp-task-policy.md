# Task-Level MCP Usage Policy

MCP 2.0 — enforceable task-level discipline for local model participation.
MCP 2.1 — auto-invocation via hooks for common participation points.

Refer to [model-routing-policy.md](model-routing-policy.md) for model selection rationale and benchmark data.

## Core Rule

**Every development task must have a local model participation point.** Not every keystroke — every task.

## Auto-Invocation (MCP 2.1)

The hook system now auto-spawns background workers for common cases:
- **SessionStart** → `local_check` (automatic)
- **Read >300 lines** → `local_summarize_file` (automatic, background)
- **Edit with diff >50 lines** → `local_review_diff` (automatic, background)

These fire-and-forget workers never block. Results are collected at Stop.
Manual invocation is still required for debate review, test plans, draft code,
and explicit commit gate review.

## Task → MCP Tool Mapping

### State Check (always first in a session)

| When | Tool | Profile |
|------|------|---------|
| Starting work in any project | `local_check` | (auto-invoked at SessionStart) |
| After restarting Claude Code | `local_check` | (auto-invoked) |
| Diagnosing model/backend issues | `local_check` | manual if needed |

### File Understanding (before editing)

| When | Tool | Default Profile | Upgrade Trigger |
|------|------|-----------------|-----------------|
| Reading a file > 200 lines for the first time | `local_summarize_file` | `fast_summary` | (auto-invoked for >300 lines) |
| Understanding a new directory | `local_summarize_tree` | `fast_summary` | complex structure → `smart_summary` |
| Files in `tools/`, `tests/`, or config | `local_summarize_file` | `smart_summary` | infrastructure code deserves better model |

### Code Review (after editing)

| When | Tool | Profile | Required Param |
|------|------|---------|----------------|
| Any code change before commit | `local_review_diff` | `commit_reviewer` | `commit_gate=true` |
| Auto-review when diff >50 lines | `local_review_diff` | (auto-invoked via router) | background, advisory |
| Changes to `tools/` (MCP server, router, worker) | `local_review_diff` | `diff_reviewer` | non-gate explicit review |
| Changes to `.mcp.json`, profiles, tasks config | `local_review_diff` | `diff_reviewer` | |
| Staged diff before commit | `local_review_diff` | `commit_reviewer` | `commit_gate=true` |

### High-Risk Review (triggered, not default)

| When | Tool | Profile |
|------|------|---------|
| Changes to hook/gate/MCP server/router logic | `local_debate_review_diff` | fast mode (2 rounds) |
| Changes to safety policy, blocked paths, security boundary | `local_debate_review_diff` | fast mode |
| Architecture changes (new module, restructure) | `local_debate_review_diff` | full 3-round |
| Pre-release audit | explicit `release_auditor` | `release_auditor` |

### Test Planning

| When | Tool | Profile |
|------|------|---------|
| Adding a feature | `local_generate_test_plan` | `code_worker` |
| Fixing a bug | `local_generate_test_plan` | `code_worker` |
| Preparing a release | `local_generate_test_plan` | `code_worker` |

### Code Drafting (advisory only)

| When | Tool | Constraint |
|------|------|------------|
| Drafting a fix | `local_draft_code` (task=draft-fix) | Output → `.local_llm_out/` only |
| Drafting a feature | `local_draft_code` (task=draft-feature) | Controller must manually apply |
| Drafting a refactor | `local_draft_code` (task=draft-refactor) | Never auto-apply |

### Risk Analysis (explicit, not default)

| When | Tool | Profile |
|------|------|---------|
| Security-sensitive changes | `local_contextual_analyze` | `reasoning_checker` |
| Failure mode analysis | `local_contextual_analyze` | `reasoning_checker` |
| Critical/architecture risk | `local_contextual_analyze` | `deep_reasoning` |

## Escalation Rules

These rules determine when to upgrade from default to stronger model/profile:

| Trigger | Action |
|---------|--------|
| `local_summarize_file` returns `confidence=low` | Re-run with `smart_summary` |
| `local_review_diff` returns `uncertain_points` > 3 | Re-run with `diff_reviewer` or `deep_reviewer` |
| Diff touches `tools/local_llm_mcp_server.py` | Minimum `diff_reviewer`. Consider `local_debate_review_diff`. |
| Diff touches commit gate, hook, or router logic | Must use `local_debate_review_diff` (fast mode minimum). |
| Diff touches safety policy, blocked paths, security boundaries | Must use `local_debate_review_diff` or explicit `deep_reviewer`. |
| Pre-release / tag / publish | Must use `release_auditor`. |
| CJK / Unicode content in diff | `commit_reviewer` is sufficient (UTF-8 fix verified). No upgrade needed. |

## Prohibition Rules (Hard Stops)

These are NOT advisory. Violating any of these is a process failure.

### MCP Failure Handling

| Situation | Required Action |
|-----------|----------------|
| MCP `ok=false` | **STOP.** Do not commit. Do not manually substitute. |
| MCP timeout | **STOP.** Do not commit. Do not say "I reviewed it manually." |
| MCP `UnicodeDecodeError` | **STOP.** Fix encoding, re-run review. |
| MCP returns `error` field non-null | **STOP.** Diagnose root cause. |

### Review Integrity

| Situation | Required Action |
|-----------|----------------|
| Staged diff same as reviewed diff? | Must re-review staged diff. "Same diff" is not a reason to skip. |
| MCP review not run for this exact diff | Must run before commit. |
| File modified after MCP review | Must re-run review on new diff. |

### Model Selection

| Situation | Rule |
|-----------|------|
| Commit gate | Must use `commit_reviewer`. Must NOT use reasoning, >30B, or release auditor. |
| Default routing | Must NOT default to largest model. |
| Experimental models | Must NOT enter automated routing. Manual invocation only. |
| `translategemma-12b-it` for CLI translation | Must NOT — does not work with current prompt. Use `glm-4.7-flash` only. |
| Known-bad models (see model-routing-policy.md) | Must NOT use in any automated or semi-automated path. |

### Controller Discipline

| Situation | Rule |
|-----------|------|
| MCP review fails | Controller MUST NOT say "I reviewed it manually, moving on." |
| MCP review passes with low confidence | Controller MUST inspect flagged locations before committing. |
| Worker claims "no issues found" | Controller MUST still read the diff directly. |
| Draft code output | Controller MUST inspect and manually apply. Never treat draft as applied code. |

## Task Lifecycle Checklist

For a typical development task, the MCP participation points are:

```
1. [ ] local_check                         — session start
2. [ ] local_summarize_file                — for any unfamiliar file > 200 lines
3. [ ] local_summarize_tree                — for any unfamiliar directory
4. [ ] local_generate_test_plan            — before implementing (feature/bug)
5. [ ] local_review_diff (commit_gate)     — after editing, before staging
6. [ ] local_review_diff (commit_gate)     — after staging, before commit
7. [ ] local_debate_review_diff            — if change is high-risk (optional, triggered)
```

Not every step is required for every task. Step 5 and 6 are mandatory for every commit.
