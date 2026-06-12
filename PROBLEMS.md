# PROBLEMS.md

## 0. Purpose

本文件记录：已知问题、历史踩坑、禁止重复的错误做法、高风险区域、需要人工确认的边界。

**这不是 bug list。这是防止 agent 重复犯错的记忆层。**
每次 agent 犯一个值得记录的错，就加一条禁令或已知问题。

---

## 1. Active Problems

### PROB-001: Debate review 对大 diff 产生截断误报
- **Status**: mitigated (not fixed)
- **Area**: tools/local_llm_debate.py, MCP debate tool
- **Symptom**: 大 diff (>10000 chars) 时 debate review 可能因为输入截断而产生 false positive
- **Cause**: worker prompt 有 max_chars 限制，大 diff 被截断后丢失上下文
- **Do Not**: 对大 diff 的 debate 结果做全自动决策。必须由 controller 人工审查
- **Recommended Fix**: 对大 diff 自动分片或压缩后再送入 debate
- **Related Tests**: tests/test_debate*.py
- **Source**: MCP QA memory (`mcp-qa.md`)

### PROB-002: Regex `\b` 边界在 shell 命令上匹配失败
- **Status**: resolved (P2-C1.2, P6)
- **Area**: tools/claude_hooks/ (dangerous command guard)
- **Symptom**: `\b` word boundary 在含有特殊字符的 shell 命令上不匹配，导致危险命令未被拦截
- **Cause**: 正则表达式的 `\b` 在非字母数字字符处行为不符合预期
- **Fix**: 使用显式边界匹配替代 `\b`
- **Source**: MCP QA memory (`mcp-qa.md`)

### PROB-003: qwen3.6_35b_moe_mtp 模型 99.2% 失败率
- **Status**: resolved (2026-06-12: tag fix qwen3.6:35b-q8-ud → qwen3.6:35b; Ollama dropped -q8-ud suffix. Model now works via standard Ollama. MTP endpoints still offline but base model is available.)
- **Area**: tools/local_llm_debate.py, tools/local_llm_profiles.json
- **Symptom**: MTP 模型通过 llama.cpp 端点几乎全部失败
- **Root Cause**: Ollama 模型标签变更（去掉 -q8-ud 后缀），旧标签查询失败
- **Fix**: 2026-06-12 标签全量同步。deep_reviewer 确认可用（review-diff OK）。
- **Related**: [[qwen36-ssm-models]]

### PROB-004: MCP server 进程变更后不重启导致 stale response
- **Status**: known limitation (not a code bug)
- **Area**: tools/local_llm_mcp_server.py
- **Symptom**: MCP handler 代码更新后，旧的 MCP server 进程仍返回旧格式的 response（缺少新增字段）
- **Cause**: MCP server 是持久进程，不会自动检测代码变更并重载
- **Workaround**: 修改 MCP server 代码后必须重启 MCP server 进程
- **Related**: U-3 dogfood finding F6

### PROB-005: cold-start 超时风险（大型 SSM/MoE 模型）
- **Status**: known limitation
- **Area**: worker, Ollama
- **Symptom**: 大模型（35B+ MoE/SSM）在冷启动时加载时间可能超过 MCP tool timeout
- **Mitigation**: 使用更轻量的模型作为默认；重模型仅手动指定
- **Do Not**: 不要把 cold-start 风险高的模型设为 auto-eligible
- **Related**: [[qwen36-ssm-models]]

### PROB-007: deepseek-r1:32b (non-distill) 通过 Ollama 返回空响应
- **Status**: mitigated (2026-06-12: switched deep_reasoning to distill variant)
- **Area**: Ollama / deepseek-r1 model
- **Symptom**: `deepseek-r1:32b` 返回空响应，`deepseek-r1:32b-distill` 正常工作
- **Cause**: Ollama 的 R1 非蒸馏版本可能存在 thinking token 格式兼容问题
- **Mitigation**: deep_reasoning profile 改用 distill variant（任务测试通过）
- **Do Not**: 非蒸馏版可保留在 candidates 列表中作为备选，但不要设为默认

### PROB-006: 翻译任务 worker 对非英语输入产生幻觉
- **Status**: known limitation
- **Area**: tools/local_llm_worker.py, translation tasks
- **Symptom**: 本地翻译模型（尤其 <14B）可能在非英语输入上产生不稳定的术语翻译
- **Mitigation**: 翻译结果必须由 controller 审查，术语一致性由 controller 检查
- **Do Not**: 对翻译任务完全自动化

---

## 2. Forbidden Patterns

### BAN-001: 禁止绕过配置系统
- **Reason**: 配置项绕过 `tools/local_llm_profiles.json` 会导致 validate_configs.py 失败、router 行为不一致、call ledger 统计失真
- **错误示例**: 在 worker 或 MCP server 中硬编码模型名、provider 或 endpoint URL
- **正确做法**: 所有模型/配置变更走 `tools/local_llm_profiles.json` + `validate_configs.py` 验证

### BAN-002: 禁止直接修改公共接口而不更新 INTERFACES.md
- **Reason**: CLI、MCP tool schema、config key 的接口漂移是项目最常见的回归源
- **影响**: 下游消费者（MCP client、hook、installer、其他项目）静默失败
- **正确做法**: 修改接口后更新 INTERFACES.md 对应条目，并跑完整测试套件

### BAN-003: 禁止在未理解现有 delegation contract 的情况下新增 MCP tool
- **Reason**: MCP tool 数量、schema、escalation chain 是精心设计的。随意新增会破坏 controller 的信任模型
- **正确做法**: 新 MCP tool 需要: (a) 明确的 use case; (b) source-non-mutating 边界; (c) escalation chain 设计; (d) ledger key 规划; (e) POLICY.md 更新

### BAN-004: 禁止 `local_debate_review_diff` 被跳过
- **触发条件**: diff 触碰 MCP server / router / hooks / gate / security / DB schema / release/freeze
- **Reason**: 这些是高风险的变更类别，必须经过多模型交叉审查
- **例外**: 无。即使是 docs-only 变更触及这些文件也必须 debate

### BAN-005: 禁止用 PowerShell here-string 做 `git commit -m`
- **Reason**: PowerShell here-string (`@'...'@`) 作为 `git commit -m` 参数会导致编码问题
- **正确做法**: 使用 bash heredoc 或临时文件方式传入 commit message
- **Source**: [[git-commit-heredoc]]

### BAN-006: 禁止把临时脚本变成核心依赖
- **Reason**: 临时脚本缺少测试、文档、接口契约。变成核心依赖后维护成本指数增长
- **正确做法**: 临时脚本留在 `.local_llm_out/` 或明确标记 `# TEMPORARY – DO NOT DEPEND ON`

### BAN-007: 禁止新增无测试覆盖的配置项
- **Reason**: 配置项是接口契约的一部分。无测试覆盖的配置项会在后续重构中悄悄失效
- **正确做法**: 新增配置项必须包含: (a) profile JSON 条目; (b) validate_configs 覆盖; (c) policy derivation 测试

### BAN-008: 禁止 CLI 输出字段删除
- **适用范围**: 所有 CLI tool 的 stdout JSON 格式
- **Reason**: 下游脚本依赖 CLI JSON 输出做解析。删除字段 = 静默破坏下游
- **正确做法**: 只增不减。旧字段标记 deprecated 保留至少一个版本

### BAN-009: 禁止把聊天记录、执行日志或上一轮回答原文拼入治理文档
- **Reason**: 治理文档是稳定操作契约，不是对话归档。聊天记录会污染 agent 后续行为，导致规则重复、错位、上下文膨胀
- **禁止**:
  - 把 `Thought` / `Write(` / `Wrote N lines` / `hidden` 等执行日志写入文档
  - 把 assistant 的长回答原文整段复制进治理文件
  - 把多个文件模板拼接到同一个文件
  - 把模板文件写成项目实例文件（`templates/` 下不应有 `local-llm-pipeline` 具体内容）
- **正确做法**:
  - 每个治理文件必须从空白结构重写
  - 每个文件标题（`# XXX.md`）必须与文件名一致
  - 模板目录只保留通用占位内容（`<!-- TODO: ... -->`）
  - 根目录文件才允许写本项目具体内容
  - 修改治理文件前先读目标文件，确认当前内容

### BAN-010: 禁止在最终汇报中同时保留错误命令和正确命令
- **Reason**: 用户可能复制第一条命令执行，造成漏加文件或提交失败
- **禁止**:
  - 在最终答案中保留已知错误命令
  - 先输出错误命令，再输出正确命令而不明确废弃前者
  - 使用截断、缩写或占位文件名（如 `IN.md`）代替真实文件名
- **正确做法**:
  - 最终汇报只保留一条可直接执行的命令
  - 如果此前命令错误，必须明确标注"废弃，不要执行"
  - 提交前用 `git diff --cached --name-only` 验证暂存文件清单

### BAN-011: 禁止为了方便绕过 local-first 直接调用云模型
- **Reason**: local-first 是项目核心设计原则。绕过本地直接调用云端会让隐私保护、成本控制、离线能力全部失效
- **禁止**:
  - 在 router 中将云模型设为任何 task 的默认 profile
  - 未经隐私 gate 检查就将文件内容发送到云端
  - 把 `.env`、secrets、私有大文本、未公开论文原文、完整仓库上传云端
  - 在本地模型可用时跳过本地直接调用云端
- **正确做法**:
  - 默认走本地模型
  - 本地失败 2 次后才升级 DeepSeek Flash
  - 高风险/接口/release 才升级 DeepSeek Pro
  - 含敏感内容的文件必须先本地摘要、脱敏、压缩，再决定是否上传
  - 云模型只接收 task packet + explicit file snippets，不接收完整仓库

---

## 3. Fragile Areas

| 文件 / 区域 | 风险原因 | 修改前必须 |
|------------|---------|-----------|
| `tools/local_llm_mcp_server.py` | MCP tool schema、escalation chain、subprocess 调用 | Debate review (fast mode) |
| `tools/local_llm_router.py` | 所有 worker 调用的路由入口 | Debate review + full test suite |
| `tools/claude_hooks/` | 钩子逻辑 / gate logic / doctor | Debate review (fast mode) |
| `tools/local_llm_profiles.json` | 24 profiles，配置变更波及 router + ledger + MCP | validate_configs.py + router tests |
| `tools/call_ledger.py` | 所有调用的记账系统 | Ledger schema 只能增字段 |
| `tools/local_llm_debate.py` | 多模型 debate 编排 | 完整 debate smoke test |
| `tools/local_llm_worker.py` | 所有本地模型调用的执行端 | worker tests + MCP smoke |
| `tools/validate_configs.py` | 配置一致性守门员 | 自身测试必须 100% pass |
| `VERSION` | 版本号，影响 installer / manifest / CHANGELOG | 只在 release-prep phase 修改 |

---

## 4. Historical Incidents

### INC-001: PowerShell here-string 导致 commit message 异常
- **Date**: 2026-05
- **Symptom**: git commit -m 使用了 PowerShell here-string，commit message 内容异常
- **Root Cause**: PowerShell 的 here-string 编码与 git 期望的 UTF-8 不兼容
- **Fix**: 改用 bash heredoc
- **Resulting Ban**: BAN-005
- **Source**: [[git-commit-heredoc]]

### INC-002: MCP server stale process 导致 U-3 dogfood 失败
- **Date**: 2026-05-27
- **Symptom**: U-3 dogfood 时 MCP tool 返回的 response 缺少 `work_order_template` 字段
- **Root Cause**: MCP server 进程未重启，仍运行旧代码
- **Fix**: 重启 MCP server
- **Resulting Rule**: PROB-004 — MCP server 代码变更后必须重启

### INC-003: D-C 实现中 test_failure_exit_code 类型错误导致 subprocess 崩溃
- **Date**: 2026-05
- **Symptom**: `test_failure_exit_code` (int) 作为 raw `extra_env` key 传入 subprocess，导致 `environment can only contain strings` 错误
- **Root Cause**: 类型不匹配 — int 不能直接放入 env var
- **Fix**: D-C.1 hotfix — 通过 `_build_ledger_extra_env` kwargs 和 JSON 序列化传递
- **Lesson**: MCP server 传入 worker subprocess 的 env var 必须是 string

### INC-004: 翻译 worker 输出 markdown code fence 导致 JSON 解析失败
- **Date**: 2026-05
- **Symptom**: E-C dogfood — classify_failure_helper CLI 返回 `worker_failure — could not parse classification`
- **Root Cause**: worker 在 JSON 外包裹了 markdown code fence (` ```json ... ``` `)
- **Fix**: E-C.1 hotfix — 添加 `_strip_json_code_fence()` parser
- **Lesson**: 本地模型输出不可靠，所有 JSON 解析必须有 fallback

### INC-005: 治理文档首次生成时模板文件错位
- **Date**: 2026-06-12
- **Symptom**: `templates/project-governance/GRILLME.md` 首次写入时被写入了 INTERFACES.md 模板内容；根目录 AGENTS.md 在增强时出现了内容片段重复
- **Root Cause**: agent 批量 Write 时未逐文件验证内容-文件名一致性，将对话上下文中的模板片段错误路由到了错误的文件路径
- **Fix**: 逐文件审计、重写 GRILLME.md 模板、验证全部 11 个文件标题与内容一致性
- **Resulting Ban**: BAN-009

---

## 5. Review Checklist

每次修改代码前检查：

- [ ] 是否触碰 Fragile Areas 中的高风险文件？
- [ ] 是否违反 Forbidden Patterns 中的任何禁令？
- [ ] 是否需要更新 INTERFACES.md？
- [ ] 是否需要更新 tests？
- [ ] 是否需要 debate review（触碰 MCP/hooks/router/gate/DB/schema/security）？
- [ ] 是否需要 parallel review（release/freeze 边界）？
- [ ] CLI 输出格式是否向后兼容？
- [ ] config 是否向后兼容？
- [ ] MCP tool schema 是否向后兼容？

---

## 6. Deferred Known Issues

以下是已知但暂不修复的问题（设计决策，非疏忽）：

| Issue | Priority | Defer Reason |
|-------|----------|-------------|
| P6-B2-C: `record_call()` write-failure propagation | Low | 设计意图是 "must never crash the call" |
| M3: ledger 自动 rotation | Low | 手工 CLI rotation 已足够 |
| M7: LAN proxy cost estimation | Low | 静态 cloud cost reference 已提供合理近似 |
| P6-B3-B: MTP endpoint 硬编码 | Low | 需要独立设计 config surface |
| P5-C: `_env` wiring for experimental profile | Low | 延期至实际使用需要时 |
