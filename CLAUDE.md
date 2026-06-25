# CLAUDE.md

Codex users: see AGENTS.md for Codex-facing instructions (CLAUDE.md contains
Claude-specific slash commands, auto-invocation hooks, and subagent references).

## Project Governance Files

| File | Purpose | When to Read |
|------|---------|-------------|
| **AGENTS.md** | 项目宪法 + agent 操作规则 (Codex-facing) | 每次任务开始 |
| **SHARED_POLICY.md** | AGENTS+CLAUDE 共享策略 (Controller/Worker/MCP) | 涉及 delegation 规则时 |
| **CLAUDE.md** (this file) | Claude Code 专用指令 | 会话自动加载 |
| **PROBLEMS.md** | 累计问题、禁令、已知坑 | 每次代码修改前 |
| **LONGTODO.md** | 长期路线图、需求、延期项 | 触及 roadmap 时 |
| **INTERFACES.md** | MCP/CLI/Config/Provider 接口契约 | 涉及接口变更时 |
| **docs/local-cloud-routing-architecture.md** | 三层路由架构 (Local→Router→Cloud) | 涉及路由/升级/云端决策时 |
| **GRILLME.md** | 新项目初始化访谈模板 | 新项目初始化时 |

## Controller Delegation Contract (U-1)

> NOTE: See **SHARED_POLICY.md §1** for the full Controller Delegation Contract:
> Delegation Decision Tree, MUST/SHOULD/MAY tables, Budget Controls, Work Order
> and Result Packet schemas, Responsibility Split, and Prohibition Rules.

**Core principle**: Big model (Claude Code) plans. Local models execute bounded
read-only heavy work. Big model audits, integrates, edits, and finalizes.

Decision tree summary: Trivial -> answer directly. Tiny edit -> may skip
summarize, MUST review_diff. Non-trivial -> workflow_plan -> orient ->
understand -> test_plan -> review -> commit. Full tree: SHARED_POLICY.md §1.1.

## Local Multi-Model Worker Policy

> NOTE: See **SHARED_POLICY.md §2** for the full Worker Policy: allowed/forbidden
> tasks, controller requirements, and confidence handling.

Claude Code is the controller. Local workers are advisory only.

### Claude Code Must
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

- `draft-pr-summary` — draft a PR summary from git diff or commit range:
  `git diff main..HEAD | py -3 tools/local_llm_router.py draft-pr-summary --stdin`
  (advisory-only, output to `.local_llm_out/`, controller decides final PR text)

- `draft-changelog-entry` — draft a changelog entry from git diff or commit range:
  `git diff main..HEAD | py -3 tools/local_llm_router.py draft-changelog-entry --stdin`
  (advisory-only, output to `.local_llm_out/`, controller decides final entry)

- `find-related-files` — identify related files for a task (primary, support, tests,
  affected subsystems, inspection order, next tool calls):
  `git ls-files | py -3 tools/local_llm_router.py find-related-files --stdin`
  (advisory-only, output to `.local_llm_out/`, controller decides what to read/edit)

- `local_workflow_plan` — heuristic workflow planner (no LLM calls). Recommends
  command sequence for the current task based on change type:
  `git diff --name-only | py -3 tools/local_workflow_plan.py --stdin --task "description"`
  (advisory-only, stdout or JSON, controller decides final workflow)

- `router_explain` — explain DeepSeek V4 Flash/Pro routing decisions. Outputs
  task_type, risk_level, privacy_status, recommended local profile, escalation
  conditions, and cloud_allowed verdict. Mock-only, no real API calls:
  `py -3 tools/router_explain.py "review current diff" --explain`
  `py -3 tools/router_explain.py "prepare release v2.3" --json`
  `py -3 tools/router_explain.py --demo`
  (advisory-only, controller decides final routing)

- `advisory_workflow` — preflight route-aware task advisor. Wraps router_explain
  + shadow_route_log. Outputs recommended_controller_decision:
  `py -3 tools/advisory_workflow.py "<task>" --cloud-ok`
  (advisory-only, never executes, never calls DeepSeek)

- `precommit_advisory` — non-blocking precommit route check. Reads git diff,
  prints advisory recommendation, always exits 0:
  `py -3 tools/precommit_advisory.py`
  `py -3 tools/precommit_advisory.py --cloud-ok`
  (advisory-only, never blocks commit, never calls DeepSeek)

- `shadow_route_report` — dogfood metrics report from shadow routing JSONL logs.
  Reads `.local_llm_out/shadow_routes/*.jsonl`, computes match rate, unknown rate,
  privacy bypass detection, critical misrouting count, and recommendation:
  `py -3 tools/shadow_route_report.py`
  `py -3 tools/shadow_route_report.py --since 2026-06-13 --json`
  `py -3 tools/shadow_route_report.py --output .local_llm_out/shadow_route_report.md`
  (advisory-only, no LLM calls, no DeepSeek, no profile changes)

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

The pipeline exposes 13 source-non-mutating MCP tools via `tools/local_llm_mcp_server.py`:
`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_parallel_review`, `local_draft_code`, `local_contextual_analyze`,
`local_repo_map`, `local_classify_test_failure`, `local_workflow_plan`,
`local_route_explain`.

Claude Code auto-starts the MCP server from `.mcp.json` when entering the project.
Verify with `/mcp` — should show `local-llm connected 13 tools`.

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

> NOTE: See **SHARED_POLICY.md §3** for the full MCP Usage Policy: Must-Follow
> Rules, Task-to-Tool Mapping, Escalation Rules, Prohibition Rules, and Model
> Selection Rules. Full policy also at docs/mcp-task-policy.md.

**Every non-trivial task must have a local model participation point.**

### MCP Boundaries

- MCP tools are source-non-mutating — may write only to `.local_llm_out/`.
- No write, delete, shell, git, commit, push, tag, or deploy.
- All draft tasks: `may_modify_code=false`, `controller_must_verify=true`.
- All MCP output is advisory only — Claude Code must verify important claims.

## Claude Code Soft Gate Protocol (PASS_WITH_LIMITS, 2026-06-13)

Soft gate is **advisory-only**. It never blocks Claude Code, never calls
DeepSeek, never reads API keys, never reads file contents. It exists to surface
governance risk before key actions. See `docs/claude_code_soft_gate_design.md`
and `docs/claude_code_soft_gate_convergence_audit.md` for full design and audit.

**Current status**: PASS_WITH_LIMITS. Allowed: advisory usage guidance.
Blocked: warning gate, Stop hook, hard block (match_rate < 85%, critical_misrouting > 0).

### Default Call Points

**1. Pre-task soft gate** — before non-trivial tasks (multi-file, new tool, governance, model path, privacy/budget/API boundary, release/security/interface):

```bash
py -3 tools/claude_soft_gate.py --stage pre-task --task "<task>" --json
```

**2. Pre-commit advisory** — before every commit (already established):

```bash
py -3 tools/precommit_advisory.py --cloud-ok
py -3 tools/shadow_route_log.py "precommit review for <task>" --actual "<actual>"
```

**3. Pre-cloud soft gate** — before any cloud model call:

```bash
py -3 tools/claude_soft_gate.py --stage pre-cloud --task "<intent>" --cloud-ok --json
# If file paths are relevant, pass names only (no content read):
py -3 tools/claude_soft_gate.py --stage pre-cloud --task "<intent>" \
    --files "path1,path2" --cloud-ok --json
```

### Decision Handling

| decision | Claude Code action |
|----------|--------------------|
| `allow` | Proceed. Normal test workflow. |
| `warn` | Proceed. Note risk in execution report. |
| `defer` | Pause scope expansion. Clarify task or reduce context. |
| `manual_confirm_recommended` | Do NOT auto-escalate to cloud. Report to user, wait for confirmation. |
| `cloud_blocked` | Do NOT send to any cloud API. Report and use local models. |

**Invariant**: `would_block=false` and `advisory_only=true` in ALL soft gate
outputs. This is intentional — soft gate is an advisor, not an enforcer.

### Actual Decision Enum & Rules

```
local        — fully local execution
local-first  — local first, consider upgrade only if needed
flash-fallback — medium complexity, Flash as fallback (broader real-run paused)
pro-review   — release/security/interface/API boundary/governance boundary
cloud-blocked — secret/.env/API key/private data/cloud-forbidden
defer        — insufficient info, unclear task, can't assess risk
```

### Dogfood Protocol

```bash
# Task start
py -3 tools/advisory_workflow.py --task "<task>" --cloud-ok
py -3 tools/shadow_route_log.py "<task>" --actual "<decision>"

# After development, before commit
py -3 tools/precommit_advisory.py --cloud-ok
py -3 tools/shadow_route_log.py "precommit review for <task>" --actual "<decision>"

# Periodic review
py -3 tools/shadow_route_report.py --since 2026-06-13 --json
```

### Paused Items

```
- warning gate (blocked: match_rate < 85%)
- Stop hook (blocked: critical_misrouting > 0)
- hard block (blocked: requires warning gate first)
- broader DeepSeek real-run
- Flash limited real pilot
- Pro smoke chain
- llm-proxy
- automatic worker execution
```

### Upgrade Criteria (soft gate → warning gate)

```
- shadow route match_rate >= 85%
- critical_misrouting = 0
- privacy_bypass = 0
- false_cloud_on_secret = 0
- >= 30 additional soft gate dogfood records
- user confirms noise level acceptable
```

### MCP Docs

- [Code Drafting Guide](docs/local-llm-code-drafting.md) — draft-fix/feature/refactor usage
- [MCP Usage Patterns](docs/local-llm-mcp-usage-patterns.md) — MCP vs CLI decision matrix
- [MCP Client Verification](docs/local-llm-mcp-client-verification.md) — setup guide
- [MCP Server Docs](docs/local-llm-mcp.md) — tool reference and security boundaries
