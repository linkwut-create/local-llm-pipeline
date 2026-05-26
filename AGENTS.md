# AGENTS.md

Codex-facing primary instruction file for local-llm-pipeline.
CLAUDE.md is the Claude Code counterpart (contains slash commands, auto-invocation
hooks, and subagent references not available in Codex).

## Project Role

local-llm-pipeline is a **local AI development control layer** — not a tool
collection.  It provides:

- **Task bootstrap**: structured project context before broad work.
- **Review gates**: pre-commit and pre-release safety checks via local models.
- **Call ledger**: token/cost observability across models and tasks.
- **MCP server**: 12 source-non-mutating tools for summarization, review, test, workflow planning
  planning, and repo mapping.

Codex, Claude Code, and local LLMs are executors — the pipeline provides the
control layer that gates commits and releases.

## Required Workflow for Broad Tasks

For cross-file, cross-module, unfamiliar-repo, or architecture-sensitive tasks,
always start with task bootstrap:

```bash
# Full task context package (repo_map + summaries + risk hints):
py -3 tools/task_bootstrap.py --project <PATH> --task "<TASK_DESCRIPTION>" `
  --max-summaries 3 --budget 6000

# Quick file-selection check (no LLM calls):
py -3 tools/task_bootstrap.py --project <PATH> --task "<TASK_DESCRIPTION>" `
  --max-summaries 5 --dry-run --json
```

Output (written to `.local_llm_out/`):
- `*_bootstrap.md` — human-readable: repo map summary, selected files,
  summaries, risk hints, suggested next calls, what NOT to read first.
- `*_bootstrap.json` — machine-readable structured output.

Then:
1. Read `selected_files` and summaries
2. Make bounded implementation
3. Run targeted tests
4. Run `py -3 tools/run_checks.py`
5. Run `git diff --check`
6. Use review gate before commit (see below)
7. Commit only after tests and review pass

## Verification Commands

```bash
# Targeted tests:
py -3 -m pytest tests/test_task_bootstrap.py -q
py -3 -m pytest tests/test_call_ledger.py -q

# Full suite:
py -3 tools/run_checks.py

# Pre-commit hygiene:
git diff --check
git status --short --untracked-files=all
```

## Review Gates

| Trigger | Gate | Notes |
|---------|------|-------|
| Meaningful diff, pre-commit | `local_review_diff` (`commit_gate=true`) | Required before commit |
| Large / high-risk / tools diff | `local_debate_review_diff` | Fast mode minimum |
| Release / tag / freeze | `local_debate_review_diff` + release auditor | Full 3-round |

If a native MCP gate is unavailable (timeout, `ok=false`, error), **stop and
report** — do not substitute with CLI review or manual-only judgment.

## Ledger Commands

```bash
py -3 tools/call_ledger_cli.py model-summary     # per-model token/call recap
py -3 tools/call_ledger_cli.py by-mcp-tool       # per-MCP-tool grouping
```

## Safety Boundaries

- **Do not push** unless explicitly authorized.
- **Do not create or move tags** unless explicitly authorized.
- **Do not create GitHub releases** unless explicitly authorized.
- **Do not change VERSION** unless in a release-prep phase.
- **Do not modify MCP/router/worker/path-policy** unless the task explicitly
  authorizes it.
- **Do not clean up `.mcp.json`** — it is a pre-existing tracked config file
  with no secrets.  Only act on it if the task explicitly authorizes it.
- **v0.11.0 tag is at `6f146e7`** — do not move or delete it.
- Treat MCP invocation as **best-effort**; prefer deterministic CLI commands
  when control flow matters.

## Codex-Specific Notes

- Use **Windows-compatible quoting** for paths with spaces (PowerShell
  backtick-continuation or short 8.3 names).
- Prefer **`py -3`** over `python` or `python3` — this project targets
  Windows with `py` launcher.
- **No auto-invocation hooks** — Codex does not support Claude Code's
  `PostToolUse`/`SessionStart`/`Stop` hooks.  Call review gates explicitly.
- **CLAUDE.md** contains Claude-specific features (slash commands,
  auto-invocation, subagent).  Codex should read it for shared policy but
  ignore slash-command and hook sections.
- AGENTS.md is the **primary Codex instruction file**.
- `.codex/config.toml` starts the MCP server for Codex; tools are available
  but not guaranteed — fall back to CLI when MCP is unresponsive.

## Local Multi-Model Worker Policy

This project includes a local multi-model LLM worker system.

### Controller

Codex or Claude Code.

### Worker

- `tools/local_llm_router.py` — automatic task routing.
- `tools/local_llm_worker.py` — task execution against local models.
- Backend: Ollama or llama.cpp (OpenAI-compatible).

### Allowed Worker Tasks

- Summarize files, directories.
- Find related files.
- Extract TODO/FIXME/HACK comments.
- Draft test plans, test skeletons, diff reviews, risk analyses.
- Logic checks and failure mode analysis.
- Translate or rewrite non-sensitive text.

### Forbidden Worker Tasks

- Editing source code.
- Reading secrets (`.env`, keys, tokens, credentials).
- Handling auth, crypto, database migrations, deployment, or release final
  decisions.
- Final test judgment or code approval.
- Committing, pushing, tagging, or releasing.

### Controller Requirements

- Verify all important worker claims directly.
- Read relevant source code directly.
- Run project tests before claiming completion.
- Review git diff before final response.
- Treat worker output as advisory only.

## MCP Integration (v0.11.0)

The pipeline exposes **12** source-non-mutating MCP tools via
`tools/local_llm_mcp_server.py`:

`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_parallel_review`, `local_draft_code`, `local_contextual_analyze`,
`local_repo_map`, `local_classify_test_failure`.

MCP tools are source-non-mutating:
- Never modify source files directly.
- May write generated artifacts only to `.local_llm_out/`.
- `local_draft_code` writes drafts to `.local_llm_out/` and requires
  controller verification before any source change.
- No write, delete, shell, git, deploy.

### MCP Participation Must-Follow Rules

1. **`local_summarize_file`** — mandatory before first edit of any file
   > 200 lines.
2. **`local_generate_test_plan`** — mandatory before new API, schema, parser,
   or UI behavior.
3. **`local_debate_review_diff`** — mandatory for hook/gate/DB/schema/security/
   release changes.
4. **Phase completion report** must include an MCP Usage Matrix.
5. **Reasoning models** must be used for high-risk classification and
   pre-release assessment.

### Hard Stops

- MCP failure (`ok=false`, timeout, `UnicodeDecodeError`) → **STOP, do not commit.**
- Controller must not manually substitute for failed MCP review.
- Staged diff must be re-reviewed even if same as unstaged.
- Commit gate: `commit_reviewer` only. No reasoning, no >30B, no release auditor.
- `local_debate_review_diff` must NOT be skipped for hook/gate/DB/schema/
  security/release changes.
- Phase completion report must include MCP Usage Matrix.

Full MCP policy: [docs/mcp-task-policy.md](docs/mcp-task-policy.md)
Model selection: [docs/model-routing-policy.md](docs/model-routing-policy.md)
