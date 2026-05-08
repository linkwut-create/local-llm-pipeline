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
