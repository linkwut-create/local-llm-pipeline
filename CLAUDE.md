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
Verify with `/mcp` — should show `local-llm connected 7 tools`.

### Local LLM Usage Policy

**Prefer using local-llm MCP tools for low-risk heavy reading and review tasks.**

Use `local_check` when:
- starting work in a newly opened project
- diagnosing model/backend availability

Use `local_summarize_tree` when:
- first understanding an unfamiliar project
- planning a feature across multiple files

Use `local_summarize_file` when:
- reading long files before making a plan

Use `local_generate_test_plan` when:
- adding a feature, fixing a bug, or preparing a release

Use `local_review_diff` before commit when:
- there is a small or medium diff
- the change touches installer, MCP, router, tasks, profiles, or safety policy

Use `local_debate_review_diff` only for small diffs or high-risk changes.
Default is fast mode (2 rounds) + summary-only. For large diffs use CLI.

Use `local_draft_code` to draft possible fixes, features, refactors, or improvements.
Drafts write only to `.local_llm_out/` — NEVER modify source files.
Controller must inspect and manually apply any draft. Never treat draft output as directly applied code.

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
