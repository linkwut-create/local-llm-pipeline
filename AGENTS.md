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

## Controller Delegation Contract (U-1)

**Core principle**: Big model plans. Local models execute bounded read-only heavy
work. Big model audits, integrates, edits, and finalizes. Local models never
edit, stage, commit, or push.

### Delegation Decision Tree

When Codex receives a non-trivial task, it MUST follow this decision tree:

```
Task received
  │
  ├─ Trivial? (explanation-only, no code change)
  │   └─ YES → Answer directly. No MCP delegation needed.
  │
  ├─ Tiny low-risk edit? (single-line typo, ≤5 line fix, not a high-risk path)
  │   └─ YES → May skip local_summarize_file. MUST still run review_diff
  │            (commit_gate=true) before commit.
  │
  └─ Non-trivial (cross-file, new feature, API change, unfamiliar module...)
      │
      ├─ [MUST] STEP 0: local_workflow_plan
      │     Classify task type and risk level first. Pure-heuristic, no LLM cost.
      │
      ├─ [MUST] STEP 1: Orient
      │     repo_map + find-related-files → understand project structure
      │
      ├─ [MUST] STEP 2: Understand
      │     local_summarize_file for each key file > 200 lines before editing
      │
      ├─ [CONDITIONAL] STEP 3: Test Plan
      │     local_generate_test_plan if new API/schema/parser/CLI/DB/import-export
      │
      ├─ [MUST] STEP 4: Review
      │     local_review_diff (commit_gate=true) after edits, before commit
      │
      ├─ [CONDITIONAL] STEP 5: Debate
      │     local_debate_review_diff for high-risk paths only
      │     (MCP server, router, hooks, gate, security boundaries, DB schema,
      │      release/freeze boundaries)
      │
      └─ [MUST] STEP 6: Commit
          draft-commit-message → controller reviews → finalizes → commits
```

### MUST Delegate (block commit if skipped without documented reason)

| Trigger | Tool | Notes |
|---------|------|-------|
| Any non-trivial task, first step | `local_workflow_plan` | Pure heuristic, no LLM cost |
| Key file > 200 lines, first edit | `local_summarize_file` | Before editing |
| New API / schema / parser / CLI / DB / import-export | `local_generate_test_plan` | Before implementing |
| Any code change, pre-commit | `local_review_diff` (commit_gate=true) | Required gate |
| MCP server / router / hooks / gate / security / DB schema | `local_debate_review_diff` | Fast mode minimum |
| Release / freeze boundary | `local_parallel_review` | Parallel multi-family review |

### SHOULD Delegate (strong recommendation, not a hard gate)

| Trigger | Tool |
|---------|------|
| Cross-file / cross-module task | `find-related-files` |
| Unfamiliar directory | `local_summarize_tree` |
| After edits, non-gate review | `local_review_diff` (commit_gate=false) |
| Multi-commit batch | `draft-pr-summary` + `draft-changelog-entry` |
| Cost/efficiency question | `call_ledger_cli.py by-task` |

### MAY Skip Delegation

| Situation | Condition |
|-----------|-----------|
| Explanation-only answer | No code changes |
| Tiny docs typo | Single-line, not safety/security doc |
| One-line fully specified edit | Not a high-risk path |
| User explicitly says "no MCP" or "no tools" | User override |
| Emergency stop / rollback | Safety first |

### Budget Controls

Before delegating heavy work, the controller sets limits:

- `max_files_to_summarize` — cap on summarize-file calls per task
- `max_runtime_seconds` — cap on total local model time
- `max_model_calls` — cap on total LLM calls
- Stop on `ok=false`, timeout, or high uncertainty
- Stop on safety boundary (secrets, auth, crypto paths)
- Deep/reasoning models are never default — only when explicitly required

### Work Order Schema

When the controller delegates work to local models, it specifies:

```json
{
  "task_description": "<what the user asked>",
  "controller_objective": "<what the controller is trying to achieve>",
  "risk_level": "low | medium | high",
  "local_steps_requested": [
    {"step": "summarize", "tool": "local_summarize_file", "target": "<path>", "reason": "<why>"}
  ],
  "target_files": ["<path>"],
  "search_scope": "<project root or subdirectory>",
  "allowed_tools": ["local_summarize_file", "local_review_diff", ...],
  "forbidden_actions": ["edit", "stage", "commit", "push"],
  "budget_limits": {
    "max_files_to_summarize": 5,
    "max_runtime_seconds": 300,
    "max_model_calls": 10
  },
  "expected_outputs": ["summaries", "related_files", "risk_notes"],
  "review_level": "commit_gate | debate_fast | debate_full",
  "debate_policy": "required | optional | skip",
  "stop_conditions": ["ok=false", "timeout", "high_uncertainty", "safety_boundary"],
  "controller_notes": "<free-form context>"
}
```

### Result Packet Schema

Local models return results in a consistent advisory-only packet:

```json
{
  "files_examined": ["<path>"],
  "related_files": ["<test_path>", "<config_path>"],
  "summaries": [{"file": "<path>", "summary": "<markdown>", "confidence": "high|medium|low"}],
  "test_recommendations": ["<rec>"],
  "risk_notes": ["<note>"],
  "uncertainty": "low | medium | high",
  "uncertain_points": ["<point>"],
  "skipped_steps": [{"step": "debate", "reason": "docs-only"}],
  "budget_used": {"files_summarized": 3, "runtime_seconds": 85, "model_calls": 5},
  "suggested_next_calls": ["local_review_diff", "draft-commit-message"],
  "controller_must_verify": true,
  "advisory_only": true
}
```

### Responsibility Split

| Responsibility | Controller (Codex) | Local Models |
|---------------|-------------------|--------------|
| Task classification & risk grading | Decides (uses workflow_plan as advisory) | Input via workflow_plan |
| File discovery & scoping | Decides scope | Executes find-related-files, repo_map |
| Code understanding | Verifies summaries directly | Drafts summaries |
| Implementation plan | **Owns** | - |
| Writing code | **Owns** | Draft only (→ .local_llm_out/) |
| Reading secrets (.env, tokens, keys) | **Owns** (reads directly) | **Forbidden** |
| Diff review | Final judgment | Advisory review |
| Debate review | Decides whether needed | Executes rounds |
| Running tests | **Owns** | Classify failures only |
| Commit message | **Owns** (advisors draft) | Draft only |
| Final user-facing answer | **Owns** | - |
| Deciding to ask the user | **Owns** | - |

### Prohibition Rules (Hard Stops)

- Local models MUST NOT edit, stage, commit, push, tag, or release.
- Controller MUST NOT say "I reviewed it manually" as substitute for failed MCP review.
- Draft code MUST NOT be treated as applied code — controller must inspect and manually apply.
- `local_debate_review_diff` MUST NOT be skipped for hook/gate/DB/schema/security/release changes.
- MCP `ok=false`, timeout, or error → **STOP. Do not commit.**

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
`local_repo_map`, `local_classify_test_failure`, `local_workflow_plan`.

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
