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

The pipeline exposes 9 source-non-mutating MCP tools via `tools/local_llm_mcp_server.py`:
`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_parallel_review`, `local_draft_code`, `local_contextual_analyze`.

MCP tools are source-non-mutating:
- They never modify source files directly.
- They may write generated artifacts only to `.local_llm_out/`.
- `local_draft_code` writes drafts to `.local_llm_out/` and requires controller verification before any source change.
- No write/delete/shell/git/deploy.

### Task-Level MCP Usage (MCP 2.1 — Hardened)

Every development task must have a local model participation point.
Missing MCP participation points block commit.
Full policy: [docs/mcp-task-policy.md](docs/mcp-task-policy.md)
Model selection: [docs/model-routing-policy.md](docs/model-routing-policy.md)

#### MCP Participation Must-Follow Rules (MCP-USAGE-RETRO-1)

1. **`local_summarize_file`** — mandatory before first edit of any file > 200 lines.
2. **`local_generate_test_plan`** — mandatory before new API, schema, parser, or UI behavior.
3. **`local_debate_review_diff`** — mandatory for hook/gate/DB/schema/security/release changes.
4. **Phase completion report** must include an MCP Usage Matrix.
5. **Reasoning models** must be used for high-risk classification and pre-release assessment.

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
| DB schema, CLI, parser | `local_debate_review_diff` | fast mode (full 3-round for release) |
| Test plan | `local_generate_test_plan` | `code_worker` |
| Code draft | `local_draft_code` | `code_worker` |
| Release/freeze | `local_debate_review_diff` | full 3-round |

#### Hard Stops

- MCP failure (ok=false, timeout, UnicodeDecodeError) → STOP, do not commit.
- Controller must not manually substitute for failed MCP review.
- Staged diff must be re-reviewed even if same as unstaged.
- Commit gate: `commit_reviewer` only. No reasoning, no >30B, no release auditor.
- `local_debate_review_diff` must NOT be skipped for hook/gate/DB/schema/security/release changes.
- Phase completion report must include MCP Usage Matrix.

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
