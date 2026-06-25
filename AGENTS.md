# AGENTS.md

Codex-facing primary instruction file for local-llm-pipeline.
CLAUDE.md is the Claude Code counterpart (contains slash commands, auto-invocation
hooks, and subagent references not available in Codex).

## 0. Project Identity

### What This Project Is

local-llm-pipeline is a **local AI development control layer** — not a tool collection.

**一句话定位**: 让本地小模型跑重活（摘要、审查、测试计划、代码起草），大模型做审核和决策，降低 token 成本，通过 MCP 接入 Claude Code / Codex。

### What This Project Is NOT

- 不是翻译器、不是浏览器插件、不是游戏项目
- 不是 SaaS / Web 服务
- 不是模型训练/微调平台
- 不是自动部署系统

### Governance Files

| File | Purpose | When to Read |
|------|---------|-------------|
| **AGENTS.md** (this file) | 项目宪法 + agent 操作规则 | 每次任务开始 |
| **SHARED_POLICY.md** | AGENTS+CLAUDE 共享策略（Controller/Worker/MCP） | 涉及 delegation 规则时 |
| **CLAUDE.md** | Claude Code 专用（slash commands, hooks, subagent） | Claude Code 会话自动加载 |
| **PROBLEMS.md** | 累计问题、禁令、已知坑、高风险区域 | 每次代码修改前 |
| **LONGTODO.md** | 长期路线图、需求、延期项、决策队列 | 触及 roadmap 时 |
| **INTERFACES.md** | MCP/CLI/Config/Provider 接口契约 | 涉及 API/CLI/config 变更时 |
| **GRILLME.md** | 新项目初始化访谈模板 | 新项目或新团队成员加入时 |
| **docs/PIPELINE_MODE_ROADMAP.md** | v2 pipeline mode 总路线图 | 涉及 v2 架构/阶段/成功标准时 |
| **docs/PIPELINE_MODE_STATUS.md** | v2 模块完成度跟踪 | 每次 v2 任务完成后更新 |

## 1. Core Design Principles

**不可动摇的原则**:

1. **Local-first**: 默认不调用云端 API。本地模型跑重活，大模型做审核
2. **Advisory-only**: 本地模型输出仅供 controller 参考，绝不自动修改源码
3. **Modular-first**: 默认不引入重依赖（无 SQLite, 无 Web framework, 无 message queue）
4. **Interface-stable**: 默认不破坏已有 CLI/MCP/config 接口
5. **Test-before-change**: 默认先补测试，再改功能
6. **Small-commits**: 默认小步提交，不做大爆炸式重构
7. **Explicit-over-implicit**: 宁可显式配置，不要隐式自动行为（对 agent 来说显式 = 可审计）

**优先级排序**: 安全性 > 接口稳定性 > 测试覆盖 > 功能完整性 > 性能 > UI 美观

## 2. Architecture Map

| Module | Path | Responsibility | Does NOT |
|--------|------|---------------|----------|
| **MCP Server** | `tools/local_llm_mcp_server.py` | 13 tools over stdio JSON-RPC | 不修改源文件，不部署 |
| **Router** | `tools/local_llm_router.py` | Task → profile → model routing | 不执行任务（delegate to worker） |
| **Worker** | `tools/local_llm_worker.py` | Model invocation, retry, structured output | 不做 routing 决策 |
| **Debate** | `tools/local_llm_debate.py` | Multi-model cross-review (2-3 rounds) | 不在 commit gate 中使用 |
| **Hooks** | `tools/claude_hooks/` | Auto-invocation, commit gate, dangerous guard, release guard | 不在 Codex 中运行 |
| **Call Ledger** | `tools/call_ledger.py` | Token/cost observability (JSONL) | 不自动 rotation |
| **Health** | `tools/local_llm_check.py`, `tools/health_store.py` | Environment health, telemetry | 不修改 profiles |
| **Profiles** | `tools/local_llm_profiles.json` | Model registry (10 active + 6 deprecated) | 不自动生成 |
| **Config** | `tools/validate_configs.py` | Profile consistency validation | 不修改 profiles |
| **Installer** | `install_local_llm_pipeline.py` | Cross-project installation | 不自动更新 |
| **Feedback** | `tools/feedback_ledger.py` | Cross-project feedback (JSONL) | 不自动写入 |
| **Tests** | `tests/` | ~3000 tests across 97 files | 不调用真实模型（mocked） |

### Services Provided

- **Task bootstrap**: structured project context before broad work.
- **Review gates**: pre-commit and pre-release safety checks via local models.
- **Call ledger**: token/cost observability across models and tasks.
- **MCP server**: 13 source-non-mutating tools for summarization, review, test,
  workflow planning, route explanation, and repo mapping.

Codex, Claude Code, and local LLMs are executors — the pipeline provides the
control layer that gates commits and releases.

## 3. Agent Roles

Defined in `.claude/agents/`. The role definitions are machine-readable and
enforced by Claude Code's subagent system.

| Agent | File | Model | Writes | Purpose |
|-------|------|-------|--------|---------|
| **planner** | `.claude/agents/planner.md` | deepseek-v4-pro + max | No | Break tasks, assess risk, read governance docs, output plan |
| **code-worker** | `.claude/agents/code-worker.md` | deepseek-v4-flash + high | Yes | Implement only files in task packet, never expand scope |
| **reviewer** | `.claude/agents/reviewer.md` | deepseek-v4-pro + xhigh | No | Review diffs against all BANs, catch interface breaks, flag missing tests |
| **tester** | `.claude/agents/tester.md` | deepseek-v4-flash + medium | No* | Run tests, classify failures, suggest minimal fixes |
| **interface-reviewer** | `.claude/agents/interface-reviewer.md` | deepseek-v4-pro + high | No | Review diffs for CLI/MCP/config/provider contract breakage |
| **docs-agent** | `.claude/agents/docs-agent.md` | deepseek-v4-flash + low | Yes† | Update governance files after task completion |

*Tester may fix only if task packet explicitly authorizes.
†Docs-agent may only edit .md files.

### Invocation

```
/project-governance <task>   — audit governance docs, produce task packet
/task-bootstrap <task>       — classify, read docs, find files, generate packet
```

Skills defined in `.claude/skills/`.

### Delegation Chain

```
Task → planner (plan) → code-worker (implement) → reviewer (audit)
                                      ↓ fail
                               escalate to DeepSeek Flash/Pro
```

## 7. Hard No

- **No editing files outside the task packet allowed-files list.**
- **No committing, pushing, tagging, or releasing** without explicit authorization.
- **No bypassing local-first for cloud convenience** (BAN-011).
- **No uploading secrets, private keys, `.env`, full repos, or unsanitized user data to cloud APIs.**
- **No skipping debate review** when diff touches MCP server/router/hooks/gate/security/DB schema (BAN-004).
- **No modifying `VERSION`** outside release-prep phase.
- **No adding dependencies** without explicit approval.
- **No expanding task scope** — if you find an unrelated bug, report it; don't fix it.
- **No `local_debate_review_diff` skip** for hook/gate/DB/schema/security/release changes.
- **No PowerShell here-string for `git commit -m`** (BAN-005).
- **No chat log or execution log contamination in governance files** (BAN-009).
- **No treating draft code (`.local_llm_out/`) as applied code.**

## Controller Delegation Contract (U-1)

> [!NOTE] See **SHARED_POLICY.md §1** for the full Controller Delegation Contract:
> Delegation Decision Tree, MUST/SHOULD/MAY tables, Budget Controls, Work Order
> and Result Packet schemas, Responsibility Split, and Prohibition Rules.
> This section is the Codex-specific summary.

**Core principle**: Big model plans. Local models execute bounded read-only heavy
work. Big model audits, integrates, edits, and finalizes.

Delegation: Trivial -> answer directly. Non-trivial -> workflow_plan -> orient
-> understand -> test_plan -> review -> commit. Full tree at SHARED_POLICY.md §1.1.

MUST delegate: workflow_plan, summarize (>200 lines), test_plan (new API),
review_diff (pre-commit), debate (high-risk), parallel_review (release).
Full table at SHARED_POLICY.md §1.2.

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

> NOTE: See SHARED_POLICY.md section 2 for the full Worker Policy.
> Codex is the controller. Local workers are advisory only.

## MCP Integration (v0.13.0)

> NOTE: See SHARED_POLICY.md section 3 for the full MCP Usage Policy:
> Must-Follow Rules, Task-to-Tool Mapping, Escalation, Prohibition, Model Selection.
> 13 tools via tools/local_llm_mcp_server.py, auto-started from .mcp.json.
