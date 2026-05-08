# Local LLM Risk Policy

## Core Principle

Local models handle reading, compression, drafting, and questioning.
Code modification, test conclusions, architecture decisions, and final acceptance belong to the controller (Claude Code / Codex) and the human.

## Security Boundaries

### Blocked Paths (worker cannot read)

- `.git`
- `.env`, `.env.*`
- `*.pem`, `*.key`
- `id_rsa`, `id_ed25519`
- `node_modules`
- `venv`, `.venv`
- `__pycache__`
- `dist`, `build`, `target`
- `.local_llm_out`

### Forbidden Operations

The local worker must never:

- Modify business code
- Write to source files
- Auto-commit
- Auto-push
- Auto-publish or release
- Claim tests passed
- Claim tasks are complete
- Process API keys, tokens, passwords, or private keys
- Make final decisions on authentication, authorization, encryption, or database migrations

### Risk Level Matrix

| Risk | Worker Can | Controller Must |
|---|---|---|
| low | Complete the task independently | Review output |
| medium | Draft results | Verify key claims, read related code |
| medium-high | Suggest findings | Verify all findings, run tests |
| high | Only advise | Independently verify everything, run tests, check diff |

## Failure Handling

- If the local model is unavailable, tasks fail gracefully with error JSON.
- No task should silently succeed without model output.
- Connection errors, timeouts, and model errors all produce structured error output.
- The controller should not skip verification just because the worker succeeded.

## Upgrade Path

### When to add local_llm_debate.py (Phase 2)

- Phase 1 CLI is stable for 2+ weeks.
- You regularly need multiple perspectives on the same code.
- You want a coder model and reasoning model to cross-check each other.
- Max 2 debate rounds to prevent infinite loops.

### When to add MCP (Phase 3)

- Phase 1 CLI routing is stable.
- You want native tool integration in Claude Code / Codex.
- You want automatic tool discovery instead of manual commands.
- MCP server must NOT expose: arbitrary shell, write_file, delete_file, git_commit, git_push, deploy.
