# CLAUDE.md

Codex users: see AGENTS.md for Codex-facing instructions (CLAUDE.md contains
Claude-specific slash commands, auto-invocation hooks, and subagent references).

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

### Available CLI Tasks

- `draft-commit-message` — draft a commit message from staged diff:
  `git diff --cached | py -3 tools/local_llm_router.py draft-commit-message --stdin`
  (advisory-only, output to `.local_llm_out/`, controller decides final message)

### Available Subagent

- `local-worker-auditor` — uses the local worker and audits its output.

### Task Bootstrap (v0.11.0-F)

For cross-file, cross-module, or unfamiliar-repo tasks, start with:

```bash
# Quick file selection check (no LLM calls):
py -3 tools/task_bootstrap.py --project <PATH> --task "<DESC>" \
  --max-summaries 5 --dry-run --json

# Full task context package (repo_map + summaries):
py -3 tools/task_bootstrap.py --project <PATH> --task "<DESC>" \
  --max-summaries 3 --budget 6000
```

Output (written to `.local_llm_out/`):
- `*_bootstrap.md` — human-readable context: repo map summary, selected files,
  summaries, risk hints, suggested next calls, what NOT to read first.
- `*_bootstrap.json` — machine-readable structured output.

The bootstrap selects files by slot allocation: entrypoints (≤1/3 slots),
task keyword matches (≤1/3 slots), largest project sources (remaining).
Embedded/vendor paths (`tools/local_llm_*`, `models/`, `node_modules/`)
are deprioritized. Instruction files are root-level only.

Boundaries: CLI-only, advisory-only, writes only `.local_llm_out/`,
no MCP tool, no hooks/gates/guards/queue, does not modify target project.
Validated on local-translator-agent and local-durable-agent.

### MCP Integration (v0.7.0+)

The pipeline exposes 10 source-non-mutating MCP tools via `tools/local_llm_mcp_server.py`:
`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_parallel_review`, `local_draft_code`, `local_contextual_analyze`,
`local_repo_map`.

Claude Code auto-starts the MCP server from `.mcp.json` when entering the project.
Verify with `/mcp` — should show `local-llm connected 10 tools`.

### Auto-Invocation (Phase 2.0)

Hooks automatically spawn background workers for common MCP participation points.
No user action needed — the system detects and responds:

| Trigger | Event | Background Action |
|---------|-------|-------------------|
| Session start | SessionStart | `local_check` (environment health) |
| Read file >300 lines | PostToolUse | `local_summarize_file` via router |
| Edit file, diff >50 lines | PostToolUse | `local_review_diff` via router |
| Session end | Stop | Collects & reports auto results |

Workers use `subprocess.Popen` (fire-and-forget, never blocks the session).
Results land in `.local_llm_out/auto/`. Dedup prevents duplicate spawns
(60s window for summarize, 120s for review; max 10 per session).

The existing manual MCP invocation path still works and is required for:
- `local_debate_review_diff` (high-risk changes, sequential 2-3 round)
- `local_parallel_review` (release audit, multi-model parallel ~150s)
- `local_generate_test_plan` (new API/schema; optional `use_repo_map=true` for advisory repo-map context)
- `local_draft_code` (code generation)
- Commit gate review (explicit `commit_gate=true`)

### Task-Level MCP Usage Policy (MCP 2.1 — Hardened)

**Every development task must have a local model participation point.**
Not every keystroke — every task. Missing MCP participation points block commit.
This is enforced by process discipline, with audit trail.

Full policy: [docs/mcp-task-policy.md](docs/mcp-task-policy.md)
Model selection: [docs/model-routing-policy.md](docs/model-routing-policy.md)
Usage retro: [docs/mcp-audit-design.md](docs/mcp-audit-design.md) (MCP-USAGE-RETRO-1 section)

#### MCP Participation Must-Follow Rules (MCP-USAGE-RETRO-1)

These are NOT advisory. Skipping any of these without documented reason is a
process deviation and must be recorded in the phase completion report.

**1. local_summarize_file — mandatory before first edit of any file > 200 lines.**

If you read a file > 200 lines for the first time and plan to edit it, you
MUST run `local_summarize_file` first. Direct Read-only inspection does not
satisfy this requirement — the local model must produce a structured summary.

**2. local_generate_test_plan — mandatory before implementing new API, schema, parser, or UI behavior.**

If the phase introduces new functions, classes, CLI commands, DB schema changes,
import/export logic, or parsing, you MUST run `local_generate_test_plan` before
writing tests or implementation code.

**3. local_debate_review_diff — mandatory for specific change categories.**

You MUST run debate review (fast mode minimum, full 3-round for architecture)
when the diff touches any of:
- `tools/claude_hooks/` (hook logic, gate logic, doctor)
- `tools/local_llm_mcp_server.py` (MCP server)
- `tools/local_llm_router.py` (routing logic)
- Safety policy, blocked paths, security boundaries
- Database schema changes (SQLite DDL)
- Audit system infrastructure
- Release/freeze boundaries

MCP-AUDIT-4 and MCP-AUDIT-5 both involved these categories but skipped debate
review. This is a documented process deviation — not a precedent.

**4. Phase completion report MUST include an MCP Usage Matrix.**

Every phase completion report must contain:

```
MCP Usage Matrix
- local_check: used / not used / reason
- local_summarize_file: used / not used / reason
- local_generate_test_plan: used / not used / reason
- local_review_diff: used / not used / result
- local_debate_review_diff: used / not used / reason
- deep_reviewer / reasoning_checker: used / not used / reason
- recommendations accepted: N
- recommendations rejected: N
- deviations from plan: (list)
```

**5. Reasoning models must be used for high-risk classification tasks.**

`deep_reviewer` or `reasoning_checker` must be used when:
- Classifying whether a diff is high-risk
- Evaluating gate bypass risks
- Pre-release/freeze risk assessment

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
| Test plan with repo-map advisory | `local_generate_test_plan` + `use_repo_map=true` | `code_worker` | Opt-in; repo map advisory only, does not prove tests pass |
| Draft code (fix/feature/refactor) | `local_draft_code` | `code_worker` | Output → `.local_llm_out/` only |
| DB schema, CLI, import/export, parser | `local_generate_test_plan` | `code_worker` | Before implementing |
| Phase freeze, release audit | `local_parallel_review` | parallel multi-family | Must use parallel |

#### Escalation Rules

P3 narrowed the runtime auto-escalation chain: `confidence=="low"` and
`len(uncertain_points) > 3` no longer auto-escalate to a stronger model
by default. Both legacy behaviors remain restorable via env knobs
(truthy: `true` / `1` / `yes` / `on`, case-insensitive). The `timeout`
path still downgrades unconditionally — note this is a downgrade to a
lighter model, not a strong-model escalation, so it doesn't inflate cost.

| Trigger | Default | Opt-in restore / controller action |
|---------|---------|------------------------------------|
| `summarize` returns `confidence=low` | No auto-escalation. Controller may manually re-run with `smart_summary` if the flagged area matters. | `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true` restores legacy auto-escalation. |
| `review` returns `uncertain_points` > 3 | No auto-escalation. Controller may manually re-run with `diff_reviewer` / `deep_reviewer` if the uncertain points are material. | `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN=true` restores legacy auto-escalation. |
| Worker `error_type == "timeout"` | Downgrades to a lighter model (unchanged). | n/a — downgrade, not escalation. |
| Diff touches MCP server, commit gate, router | Debate or deep review mandatory (controller policy, not runtime). | n/a |
| Pre-release / tag / publish | `release_auditor` mandatory (controller policy). | n/a |
| MCP tool timeout | Retry with smaller input or faster model; record failure. | n/a |
| Reasoning model timeout | Fall back to code_worker; record deviation. | n/a |

The ledger `escalation_trigger` value space is unchanged
(`timeout` / `low_confidence` / `uncertain_points` / `unknown`); only
the *frequency* of `low_confidence` and `uncertain_points` labels
changes once the knobs are OFF. `escalation_reason` remains a
free-form string — there is no strict enum, no `structural_risk`
runtime trigger, and no `escalate=true` / `user_requested` MCP
parameter.

#### Prohibition Rules (Hard Stops)

- MCP `ok=false`, timeout, `UnicodeDecodeError`, or non-null `error` → **STOP. Do not commit.**
- Controller MUST NOT say "I reviewed it manually" as substitute for failed MCP review.
- Staged diff MUST be re-reviewed even if identical to unstaged reviewed diff.
- Commit gate MUST use `commit_reviewer`. MUST NOT use reasoning, >30B, or release auditor.
- Experimental / known-bad models MUST NOT enter automated routing.
- Draft code MUST NOT be treated as directly applied code. Controller must inspect and manually apply.
- `local_debate_review_diff` MUST NOT be skipped for hook/gate/DB/schema/security/release changes.

#### Model Selection Rules

- Default: match model to task type (coder→code, translator→translation).
- Commit gate: `commit_reviewer` (qwen3-coder:30b) only. Target < 30s.
- Translation (CLI/MCP): `glm-4.7-flash` only. `translategemma-12b-it` does not work with current CLI prompt.
- Reasoning models: never default. Triggered by explicit request or high-risk classification.
- Release audit models: never in commit gate or default review path.
- Debate review: fast mode (2 rounds) default; full 3-round for architecture/DB/schema/release.

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
