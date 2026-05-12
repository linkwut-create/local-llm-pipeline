# AGENTS.md

## Local Multi-Model Worker Policy

This project includes a local multi-model LLM worker system.

### Controller

- Codex or Claude Code.

### Worker

- `tools/local_llm_router.py` — automatic task routing.
- `tools/local_llm_worker.py` — task execution against local models.
- Backend: Ollama or llama.cpp (OpenAI-compatible).

### Allowed Worker Tasks

- Summarize files.
- Summarize directories.
- Find related files.
- Extract TODO/FIXME/HACK comments.
- Draft test plans.
- Draft test skeletons.
- Draft diff reviews.
- Draft risk analyses.
- Logic checks and failure mode analysis.
- Translate or rewrite non-sensitive text.

### Forbidden Worker Tasks

- The local worker must NOT edit source code.
- The local worker must NOT read secrets (.env, keys, tokens, credentials).
- The local worker must NOT approve changes.
- The local worker must NOT decide whether tests pass.
- The local worker must NOT handle deployment, database migration, authentication, authorization, encryption, or secret management final decisions.
- The local worker must NOT run destructive commands.
- The local worker must NOT commit, push, tag, or release.

### Controller Requirements

- Verify all important worker claims directly.
- Read relevant source code directly.
- Run project tests before claiming completion.
- Review git diff before final response.
- Treat worker output as advisory only.

### MCP Integration (v0.7.0+)

The pipeline exposes 7 source-non-mutating MCP tools via `tools/local_llm_mcp_server.py`:
`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_draft_code`.

MCP tools are source-non-mutating:
- They never modify source files directly.
- They may write generated artifacts only to `.local_llm_out/`.
- `local_draft_code` writes drafts to `.local_llm_out/` and requires controller verification before any source change.
- No write/delete/shell/git/deploy.

### Task-Level MCP Usage (MCP 2.0)

Every development task must have a local model participation point.
Full policy: [docs/mcp-task-policy.md](docs/mcp-task-policy.md)
Model selection: [docs/model-routing-policy.md](docs/model-routing-policy.md)

#### Task → MCP Tool

| Task | MCP Tool | Profile |
|------|----------|---------|
| Session start | `local_check` | (no LLM) |
| File > 200 lines | `local_summarize_file` | `fast_summary` |
| New directory | `local_summarize_tree` | `fast_summary` |
| Pre-commit review | `local_review_diff` | `commit_reviewer` (`commit_gate=true`) |
| Staged review | `local_review_diff` | `commit_reviewer` (`commit_gate=true`) |
| tools/ changes | `local_review_diff` | `diff_reviewer` |
| Hook/gate/router changes | `local_debate_review_diff` | fast mode |
| Test plan | `local_generate_test_plan` | `code_worker` |
| Code draft | `local_draft_code` | `code_worker` |

#### Hard Stops

- MCP failure (ok=false, timeout, UnicodeDecodeError) → STOP, do not commit.
- Controller must not manually substitute for failed MCP review.
- Staged diff must be re-reviewed even if same as unstaged.
- Commit gate: `commit_reviewer` only. No reasoning, no >30B, no release auditor.

### Standard Commands

```bash
python tools/local_llm_check.py
python tools/local_llm_router.py summarize-file <path>
python tools/local_llm_router.py summarize-tree <path> --max-files 30
python tools/local_llm_router.py extract-todos <path>
python tools/local_llm_router.py generate-test-plan <path>
git diff | python tools/local_llm_router.py review-diff --stdin
python tools/local_llm_router.py risk-analysis <path>
```
