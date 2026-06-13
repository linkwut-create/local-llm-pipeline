# LONGTODO.md

## 0. Long-Term Vision

**一句话目标**: local-llm-pipeline 是本地 AI 开发控制层 — 让小模型跑重活，大模型做审核，降低 token 成本，接入 Claude Code / Codex / MCP。

**目标用户**: 使用 AI coding assistant 的开发者（自己 + 其他开发者）。

**核心场景**:
- 每次提交前自动审查 diff
- 大文件修改前自动生成摘要
- 新 API/schema 变更前自动生成测试计划
- 高风险变更的多模型交叉审查
- 跨项目复用同一套审查基础设施

**成功标准**:
- 本地模型参与率 ≥ 80%（每次非 trivial 任务至少一个 MCP 参与点）
- Review gate 拦截率 > 0（不是摆设）
- Token 成本相对于纯大模型方案降低 ≥ 50%
- 跨 ≥3 个项目安装运行

---

## 1. Non-Goals

长期也不准备做：

- **不做 SaaS / Web UI** — 这是 CLI + MCP 工具，永远本地运行
- **不支持云端模型作为默认** — 本地优先，云端仅作为显式 opt-in
- **不做自动代码合并 / 自动部署** — controller 始终有最终决策权
- **不做 SQLite-backed ledger** — JSONL 足够，不引入数据库依赖
- **不做 Context Budget 自动化** — 留给 controller 决策
- **不做训练 / 微调模型** — pipeline 只使用已有 Ollama 模型
- **不做实时 UI popup** — hook 协议限制
- **不做 per-user guard allowlist** — 所有 block 需要 terminal override

---

## 2. Roadmap

### Phase 1: Stability (current — v0.12.0+)
- [x] MCP server 12 tools, all source-non-mutating
- [x] Controller delegation contract (U-1)
- [x] Backend governance (J-chain)
- [x] Call efficiency reporting (J-L chain)
- [x] Workflow orchestration (P-chain)
- [x] Advisor output quality (Q-chain)
- [x] Quality/value verification (Z-chain)
- [x] Cross-project feedback ledger (Z-4)
- [x] **项目治理文档体系** (2026-06-12: AGENTS/PROBLEMS/LONGTODO/INTERFACES/GRILLME + 11 BAN)
- [x] **模板目录** (2026-06-12: templates/project-governance/)
- [x] **Profile 标签全量同步** (2026-06-12: 13+ profiles, Ollama 简化标签)
- [x] **DeepSeek V4 cloud escalation** (2026-06-12: 4 profiles + API client + privacy gate)
- [x] **Subagent + Skill 自动化** (2026-06-12: planner/code-worker/reviewer + project-governance/task-bootstrap)
- [x] **Router escalation CLI flags** (2026-06-12: --local-only/--cloud-ok/--no-cloud/--privacy)
- [x] **模型任务测试** (2026-06-12: 7/8 关键 profile 通过, deep_reasoning distill 修复)
- [x] **DeepSeek API 真实调用验证** (2026-06-12: Flash/Flash-thinking/Pro 全部 OK)

### Phase 2: Cross-Project Distribution
- [x] 治理文档模板分发到 local-translator-agent (2026-06-12)
- [ ] 治理文档模板分发到 local-durable-agent (项目不存在，待创建)
- [ ] 治理文档模板分发到 browser-local-agent (项目不存在，待创建)
- [ ] 标准化 installer 的 post-install 治理文档初始化
- [ ] 跨项目 agent 工作流一致性验证

### Phase 3: Agent Integration
- [x] Subagent role 标准化 (2026-06-12: 6 roles — planner/code-worker/reviewer/tester/interface-reviewer/docs-agent)
- [ ] Subagent 输入格式标准化（task packet: 目标 + 相关文档片段 + 允许文件 + 禁止范围）
- [ ] Subagent 输出格式标准化
- [x] GRILLME.md 作为新项目初始化的标准第一步 (2026-06-12: 模板已分发到 local-translator-agent)

### Phase 4: Productization
- [ ] 自动 log rotation（hook-events.jsonl 目前无界增长）
- [ ] 更多编译/解释语言的支持（目前 Python-first）
- [ ] E2E workflow 示例和教程
- [ ] 社区贡献指南

---

## 3. Long-Term Requirements

### REQ-001: 跨项目 agent 工作流一致性
- **Priority**: high
- **Status**: planned
- **Why**: 目前每个项目有独立的 AGENTS.md，但没有机制保证 agent 在不同项目之间行为一致
- **Acceptance Criteria**:
  - 从模板新建的项目能在 10 分钟内初始化完整的治理文档
  - Agent 在任意项目中都能遵循相同的 delegation contract
  - 跨项目 feedback ledger 能追溯每个问题的来源项目
- **Dependencies**: 模板目录、GRILLME.md
- **Risks**: 模板可能与特定项目结构耦合

### REQ-002: Subagent 任务包标准化
- **Priority**: high
- **Status**: planned
- **Why**: 当前 subagent 输入是自由格式，浪费 token 且 agent 容易跑偏
- **Acceptance Criteria**:
  - 每个 subagent call 的输入包包含: 目标、相关文档片段（≤3）、允许文件列表、禁止操作列表、期望输出格式
  - Controller 的 subagent dispatch 时间缩短 ≥ 30%
  - Subagent 偏差率（做非授权操作）降低 ≥ 80%
- **Dependencies**: Subagent role 定义
- **Risks**: 过度约束可能让 agent 无法应对意外情况

### REQ-003: 治理文档自动维护
- **Priority**: medium
- **Status**: researching
- **Why**: 治理文档容易过时。最好有机制让每次任务结束时自动检查是否需要更新
- **Acceptance Criteria**:
  - 每个 non-trivial 任务结束后有检查步骤（自动化 + 人工）
  - 检查项: 新问题？新禁令？新接口？新长期需求？新设计原则？
- **Dependencies**: 治理文档体系稳定运行
- **Risks**: 自动化检查可能产生 noise

### REQ-004: MCP server 热重载
- **Priority**: medium
- **Status**: researching
- **Why**: 当前 MCP server 代码变更后需要手动重启，导致 stale response（PROB-004）
- **Acceptance Criteria**: MCP server 检测到 handler 代码变更后自动重载
- **Dependencies**: MCP protocol 对 hot-reload 的支持
- **Risks**: 重载可能中断进行中的 MCP 调用

### REQ-005: Streaming usage passthrough (call-ledger v2-B)
- **Priority**: low
- **Status**: deferred
- **Why**: 当前 streaming 路径使用 `chars//4` 估计 token，非 streaming 路径有真实 usage。统一后 ledger 更准确
- **Acceptance Criteria**: Ollama NDJSON final-frame usage 和 OpenAI `stream_options={"include_usage": true}` 都被正确记录
- **Dependencies**: call_ledger.py v2-B 设计
- **Risks**: streaming 的 usage 记录格式可能与 non-streaming 不同

---

## 4. Deferred Ideas

| Idea | Reason Deferred | Revisit Condition |
|------|----------------|-------------------|
| SQLite-backed ledger | JSONL 足够，引入 DB 增加复杂度 | JSONL 文件 > 100MB 或查询性能成为瓶颈 |
| Context Budget 自动化 | 留给 controller 决策更安全 | controller 频繁超出 context window |
| Dashboard / analytics UI | 这是 CLI + MCP 工具，不是 web 应用 | 有明确的用户需求 |
| Per-user guard allowlist | guard 的当前设计是有意的严格 | 频繁出现 legitimate block 的 false positive |
| llama.cpp backend 完整支持 | Ollama 已满足所有当前需求 | llama.cpp 提供 Ollama 无法提供的功能 |
| Background queue / daemon | 增加运维复杂度，当前 fire-and-forget 足够 | 需要跨 worker 的调度或持久化 |
| Auto-fix from review suggestions | 安全边界 — 本地模型不应自动修改源码 | 本地模型的 diff review 准确率达到可接受水平 |

---

## 5. Decision Queue

| # | 问题 | 取舍 | 需要什么证据才能决定 |
|---|------|------|---------------------|
| 1 | 是否引入 `review_necessity="user-forced"` ledger stamp (P3-C3)？ | 增加 ledger 字段 vs 保持 schema 稳定 | 是否有实际需要区分 "auto" vs "user-forced" review 的场景 |
| 2 | 是否需要 MCP server hot-reload？ | 开发便利 vs 实现复杂度 | MCP server 代码变更频率和 stale response 的实际影响 |
| 3 | 是否需要跨项目 ledger 聚合？ | 全局视图 vs 项目隔离 | 是否有跨项目成本分析的实际需求 |
| 4 | 是否需要 `local_llm_profiles.json` 的 JSON Schema 验证？ | 更严格的验证 vs 灵活性 | validate_configs.py 当前的检查是否足够 |
| 5 | 是否从 shadow routing log 进入 advisory workflow integration？ | 积累证据 vs 提前自动化 | 30—50 条 shadow log，准确率 ≥ 85%，无 critical misrouting |
| 6 | 是否启用真实 DeepSeek Flash/Pro 自动升级？ | 省钱 + 安全 vs 云端成本 + 隐私风险 | shadow routing 稳定，privacy gate 硬化，budget guard 就绪 |

---

## 6. Shadow Routing — Future Work

Shadow routing log (`tools/shadow_route_log.py`) 已就绪，下一步工作：

1. **Aggregate accuracy**: 累计 30—50 条 shadow log 后，输出准确率报告 (`--stats`)
2. **Route decision dashboard**: 按 task_type / risk_level / match 分组查看
3. **Advisory workflow integration**: controller/agent 执行任务前自动调用 `local_route_explain`，记录建议但不自动执行
4. **DeepSeek auto-escalation**: 仅在 shadow routing 通过后启用 — 需要 privacy gate + budget guard + cost ledger + fallback/retry 规则

---

## 7. Cost Ledger — Status (2026-06-13)

Cost ledger + budget guard skeleton (`tools/cost_ledger.py`) is ready.

**Done**:
- `--estimate` dry-run cost estimation (never writes)
- `--record` append-only JSONL to `.local_llm_out/cost_ledger/YYYYMM.jsonl`
- `--summary` monthly cost aggregation
- `--budget <CNY>` budget limit with exceeded detection
- Configurable pricing via `COST_LEDGER_PRICING_JSON` env var
- Unknown model → `unknown_price` (never crashes)
- 26 mock tests

**Pending**:
- Privacy gate hardening (budget guard gate integration)
- DeepSeek dry-run execution contract
- Real Flash/Pro cost tracking with accurate pricing
- Budget guard auto-block before real API calls

---

## 8. Privacy Gate — Status (2026-06-13)

Privacy gate hardening (`tools/privacy_gate.py`) is ready.

**Done**:
- `--text` content privacy check (regex + keyword rules)
- `--path` file path privacy check (suffix + exact match)
- 9 rule categories: private keys, API keys, credential files, full repo export, cloud upload semantics
- 3-tier output: `safe` | `blocked` | `needs_review`
- README/Changelog/template context auto-downgrade
- 44 mock tests

**Pending**:
- Budget guard integration (cost_ledger + privacy_gate → combined gate)
- DeepSeek dry-run execution contract
- Real content scanning (file content, not just path)

---

## 9. Advisory Workflow — Status

Advisory workflow preflight (`tools/advisory_workflow.py`) is ready.

**Done**:
- Preflight CLI: `py -3 tools/advisory_workflow.py "<task>"`
- Outputs recommended_controller_decision + full router analysis
- Writes shadow routing log automatically
- 13 mock tests

**Pending**:
- Hook integration (auto-invoke preflight on certain task triggers)
- Controller comparison dashboard
- Decision accuracy tracking over time
