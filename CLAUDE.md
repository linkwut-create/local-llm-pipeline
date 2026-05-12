# CLAUDE.md

## Local Multi-Model Worker Policy

This project uses a local multi-model LLM worker for low-risk, read-only assistance.
Claude Code is the controller. The local worker is advisory only.

### Allowed Local Worker Tasks

- Summarize files.
- Summarize directories.
- Find related files.
- Extract TODO/FIXME/HACK comments.
- Draft test plans.
- Draft test skeletons.
- Draft diff reviews.
- Draft risk analysis.
- Logic checks and failure mode analysis.
- Translate or rewrite non-sensitive text.

### Forbidden Local Worker Tasks

- Editing source code.
- Reading secrets (.env, keys, tokens, credentials).
- Handling authentication or authorization final decisions.
- Handling cryptography final decisions.
- Handling database migrations.
- Deployment or release.
- Final test judgment.
- Final code approval.

### Claude Code Must

- Verify important worker claims directly.
- Read relevant source files directly.
- Run tests before claiming success.
- Review git diff before final response.
- Treat worker output as advisory only.

### Available Commands

- `/local-check` — run environment health check.
- `/local-worker` — run a specific worker task.
- `/local-route` — auto-route a task to the right model.
- `/local-review-diff` — initial review of current git diff.
- `/local-risk` — risk analysis of a file or plan.
- `/local-test-plan` — generate a test plan for a file.
- `/local-debate` — multi-model cross-review (3 rounds: coder → reasoning → deep).

### Available Subagent

- `local-worker-auditor` — uses the local worker and audits its output.

### MCP Integration (v0.7.0+)

The pipeline exposes 7 source-non-mutating MCP tools via `tools/local_llm_mcp_server.py`:
`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_draft_code`.

Claude Code auto-starts the MCP server from `.mcp.json` when entering the project.
Verify with `/mcp` — should show `local-llm connected 8 tools`.

### Task-Level MCP Usage Policy (MCP 2.0)

**Every development task must have a local model participation point.**
Not every keystroke — every task. This is enforced by process discipline, not hooks.

Full policy: [docs/mcp-task-policy.md](docs/mcp-task-policy.md)
Model selection: [docs/model-routing-policy.md](docs/model-routing-policy.md)

#### Task → MCP Tool Mapping

| Task type | MCP Tool | Profile | Required |
|-----------|----------|---------|----------|
| Session start | `local_check` | (no LLM) | Always first |
| File > 200 lines, first read | `local_summarize_file` | `fast_summary` | Before editing |
| New directory | `local_summarize_tree` | `fast_summary` | Before planning |
| Code change → pre-commit | `local_review_diff` | `commit_reviewer` | `commit_gate=true` |
| Code change → staged | `local_review_diff` | `commit_reviewer` | `commit_gate=true` |
| Changes to `tools/` (MCP/router/worker) | `local_review_diff` | `diff_reviewer` | Explicit review |
| Hook/gate/MCP server/router logic | `local_debate_review_diff` | fast mode | Must use debate |
| Safety policy, blocked paths | `local_debate_review_diff` | fast mode | Must use debate |
| Feature/bug/release test plan | `local_generate_test_plan` | `code_worker` | Before implementing |
| Draft code (fix/feature/refactor) | `local_draft_code` | `code_worker` | Output → `.local_llm_out/` only |

#### Escalation Rules

| Trigger | Action |
|---------|--------|
| `summarize` returns `confidence=low` | Upgrade to `smart_summary` |
| `review` returns `uncertain_points` > 3 | Upgrade to `diff_reviewer` or `deep_reviewer` |
| Diff touches MCP server, commit gate, router | Debate or deep review mandatory |
| Pre-release / tag / publish | `release_auditor` mandatory |

#### Prohibition Rules (Hard Stops)

- MCP `ok=false`, timeout, `UnicodeDecodeError`, or non-null `error` → **STOP. Do not commit.**
- Controller MUST NOT say "I reviewed it manually" as substitute for failed MCP review.
- Staged diff MUST be re-reviewed even if identical to unstaged reviewed diff.
- Commit gate MUST use `commit_reviewer`. MUST NOT use reasoning, >30B, or release auditor.
- Experimental / known-bad models MUST NOT enter automated routing.
- Draft code MUST NOT be treated as directly applied code. Controller must inspect and manually apply.

#### Model Selection Rules

- Default: match model to task type (coder→code, translator→translation).
- Commit gate: `commit_reviewer` (qwen3-coder:30b) only. Target < 30s.
- Translation (CLI/MCP): `glm-4.7-flash` only. `translategemma-12b-it` does not work with current CLI prompt.
- Reasoning models: never default. Triggered by explicit request or high-risk classification.
- Release audit models: never in commit gate or default review path.

### MCP Boundaries

- MCP tools are source-non-mutating — may write only to `.local_llm_out/`.
- No write, delete, shell, git, commit, push, tag, or deploy.
- All draft tasks: `may_modify_code=false`, `controller_must_verify=true`.
- All MCP output is advisory only — Claude Code must verify important claims.

### MCP Docs

- [Code Drafting Guide](docs/local-llm-code-drafting.md) — draft-fix/feature/refactor usage
- [MCP Usage Patterns](docs/local-llm-mcp-usage-patterns.md) — MCP vs CLI decision matrix
- [MCP Client Verification](docs/local-llm-mcp-client-verification.md) — setup guide
- [MCP Server Docs](docs/local-llm-mcp.md) — tool reference and security boundaries
