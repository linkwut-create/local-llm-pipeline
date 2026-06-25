# SHARED_POLICY.md — Controller-Worker Shared Policy

> Version v0.13.0 (2026-06-25)
> Shared between AGENTS.md (Codex) and CLAUDE.md (Claude Code)

## 1. Controller Delegation Contract (U-1)

Big model plans. Local models execute bounded read-only heavy work.
Big model audits, integrates, edits, and finalizes.

### 1.1 Delegation Steps
workflow_plan -> orient -> understand -> test_plan -> review -> commit

### 1.2 MUST Delegate
- Any non-trivial task: local_workflow_plan
- File > 200 lines: local_summarize_file
- New API/schema/parser: local_generate_test_plan
- Pre-commit: local_review_diff (commit_gate=true)
- MCP/router/hooks/security: local_debate_review_diff
- Release/freeze: local_parallel_review

## 2. Worker Policy
Allowed: summarize, find-related-files, extract TODOs, draft tests/reviews.
Forbidden: edit source, read secrets, auth/crypto, DB migrations, deploy.

## 3. MCP Usage Policy
Mandatory participation. Hard stops: ok=false, timeout, error.
Commit gate = commit_reviewer only. Reasoning = never default.

## 4. Review Gates
pre-commit: local_review_diff
high-risk: local_debate_review_diff
release: local_debate_review_diff + release auditor

## 5. Task Bootstrap
py -3 tools/task_bootstrap.py --project PATH --task DESC --max-summaries 3
### 3.2 Task to MCP Tool Mapping

| Task type | MCP Tool | Profile | Required |
|-----------|----------|---------|----------|
| Session start | local_check | (no LLM) | Always first |
| File over 200 lines | local_summarize_file | fast_summary | Before editing |
| Pre-commit | local_review_diff | commit_reviewer | commit_gate=true |
| Hook/gate/MCP/router | local_debate_review_diff | fast mode | Must use debate |
| Test plan | local_generate_test_plan | code_worker | Before implementing |
| Draft code | local_draft_code | code_worker | advisory output only |
| Release audit | local_parallel_review | parallel | Must use parallel |

### 3.3 Escalation Rules

| Trigger | Default |
|---------|---------|
| summarize confidence=low | No auto-escalation |
| review uncertain_points over 3 | No auto-escalation |
| confidence=medium | Informational only |
| Worker timeout | Downgrades to lighter model |
| MCP timeout | Retry with smaller input |

### 3.4 Prohibition Rules (Hard Stops)
- MCP ok=false, timeout, or error: STOP. Do not commit.
- Never substitute manual review for failed MCP review.
- Staged diff must be re-reviewed even if identical.
- Commit gate must use commit_reviewer only.
- Draft code must not be treated as directly applied code.
- local_debate_review_diff must not be skipped for hook/gate/DB/schema/security/release.

### 3.5 Model Selection Rules
- Default: match model to task type
- Commit gate: commit_reviewer only
- Reasoning models: never default
- Debate review: fast mode default; full 3-round for architecture/DB/schema/release

---

## 4. Review Gates

| Trigger | Gate | Notes |
|---------|------|-------|
| Meaningful diff, pre-commit | local_review_diff (commit_gate=true) | Required |
| Large/high-risk/tools diff | local_debate_review_diff | Fast mode minimum |
| Release/tag/freeze | local_debate_review_diff + release auditor | Full 3-round |

---

## 5. Task Bootstrap

```bash
py -3 tools/task_bootstrap.py --project PATH --task DESC --max-summaries 3 --budget 6000
py -3 tools/task_bootstrap.py --project PATH --task DESC --max-summaries 5 --dry-run --json
```

---

## Related Documents

| File | Scope |
|------|-------|
| AGENTS.md | Codex-specific: agent roles, architecture, hard-no rules |
| CLAUDE.md | Claude-specific: slash commands, hooks, soft gate |
| PROBLEMS.md | Cumulative problems, bans, known traps |
| INTERFACES.md | MCP/CLI/Config/Provider contracts |
| LONGTODO.md | Long-term roadmap, deferred items |
