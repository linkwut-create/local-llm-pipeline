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

### MCP Integration (v0.3.0+)

The pipeline exposes 6 read-only MCP tools via `tools/local_llm_mcp_server.py`:
`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`.

**MCP boundaries:**
- All MCP tools are read-only — no write, delete, shell, git, or deploy.
- MCP output is advisory only — Claude Code must verify all important claims.
- Default debate mode via MCP is `--fast --summary-only` to keep output compact.

**MCP commands:**
- `/local-mcp` — MCP integration guide and health check.
