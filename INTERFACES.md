# INTERFACES.md

## 0. Purpose

本文件记录所有稳定接口、调用习惯、兼容性要求。

**任何修改 API / CLI / config / storage schema / MCP tool / provider contract 的任务，都必须先读本文件。**

---

## 1. MCP Tool Contract

### Tool: local_check
- **Purpose**: 环境健康检查。Ollama 连通性、模型可用性、profile 推荐
- **Input**: 无必填参数
- **Output**: `{ok: bool, ollama_connected: bool, models_available: int, recommendations: [str], advisory_only: true}`
- **Side Effects**: 无
- **LLM Call**: 无（纯启发式）
- **Compatibility**: output 只能增字段

### Tool: local_summarize_file
- **Purpose**: 用本地 LLM 总结单个文件
- **Input**: `{path: str, profile?: str, model?: str, max_chars?: int}`
- **Output**: `{ok: bool, summary: str, confidence: "high"|"medium"|"low", advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是（worker via router）
- **Timeout**: 60s (default), 120s (max)
- **Compatibility**: output 只能增字段

### Tool: local_summarize_tree
- **Purpose**: 用本地 LLM 总结目录结构
- **Input**: `{path: str, max_files?: int, profile?: str, model?: str}`
- **Output**: `{ok: bool, summary: str, advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是
- **Compatibility**: output 只能增字段

### Tool: local_generate_test_plan
- **Purpose**: 为源文件生成测试计划
- **Input**: `{path: str, profile?: str, model?: str, use_repo_map?: bool, repo_map_path?: str, repo_map_max_files?: int}`
- **Output**: `{ok: bool, test_categories: [str], edge_cases: [str], coverage_suggestions: [str], repo_map_context_used?: bool, advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是
- **Opt-in**: `use_repo_map=true` 注入 repo-map 上下文（advisory only）
- **Compatibility**: output 只能增字段

### Tool: local_review_diff
- **Purpose**: 用单个本地模型审查 git diff
- **Input**: `{diff_text: str, profile?: str, model?: str, commit_gate?: bool}`
- **Output**: `{ok: bool, problems: [...], test_gaps: [...], compatibility_risks: [...], security_concerns: [...], advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是
- **Commit Gate**: `commit_gate=true` 使用 `commit_reviewer` profile，target < 30s
- **Compatibility**: output 只能增字段

### Tool: local_debate_review_diff
- **Purpose**: 多模型交叉审查 git diff
- **Input**: `{diff_text: str, fast?: bool, summary_only?: bool, profiles?: str, rounds?: int, max_chars?: int}`
- **Output**: `{ok: bool, findings: [...], consensus: str, advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是（2-3 模型依次调用）
- **Fast mode**: 2 rounds (default for MCP)
- **Full mode**: 3 rounds (architecture/DB/schema/release)
- **Compatibility**: output 只能增字段

### Tool: local_parallel_review
- **Purpose**: 多个本地模型并行独立审查同一 diff
- **Input**: `{diff_text: str}`
- **Output**: `{ok: bool, findings: [...], synthesis: str, advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是（2-3 模型并行）
- **Use**: 仅 release audit / freeze boundary
- **Compatibility**: output 只能增字段

### Tool: local_draft_code
- **Purpose**: 用本地 LLM 起草代码
- **Input**: `{task: "draft-fix"|"draft-feature"|"draft-refactor"|"suggest-improvements", prompt: str, context_file?: str, profile?: str, model?: str}`
- **Output**: `{ok: bool, draft: str, advisory_only: true, controller_must_verify: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/` — **绝不修改源文件**
- **LLM Call**: 是
- **Compatibility**: output 只能增字段

### Tool: local_contextual_analyze
- **Purpose**: 用本地 LLM 做定向分析
- **Input**: `{path: str, question: str, previous_result?: str, profile?: str, model?: str, max_chars?: int}`
- **Output**: `{ok: bool, analysis: str, advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`
- **LLM Call**: 是
- **Compatibility**: output 只能增字段

### Tool: local_repo_map
- **Purpose**: 生成仓库结构映射
- **Input**: `{path?: str, max_files?: int, include_tests?: bool, include_docs?: bool, refresh?: bool, write_output?: bool}`
- **Output**: `{ok: bool, map: {...}, advisory_only: true, ...}`
- **Side Effects**: 可选写入 `.local_llm_out/repo_map.json`
- **LLM Call**: 无（纯启发式）
- **Compatibility**: output 只能增字段

### Tool: local_classify_test_failure
- **Purpose**: 分类测试失败
- **Input**: `{stderr: str (required), stdout?: str, exit_code?: int, test_command?: str, changed_files?: [str], profile?: str, model?: str}`
- **Output**: `{ok: bool, failure_class: "assertion"|"import_error"|"dependency"|"syntax_error"|"timeout"|"resource"|"config"|"unknown", confidence: "high"|"medium"|"low", advisory_only: true, ...}`
- **Side Effects**: 写结果到 `.local_llm_out/`, 记录 ledger `test_failure_class` / `test_failure_confidence` / `test_failure_exit_code`
- **LLM Call**: 是
- **Compatibility**: output 只能增字段；failure_class enum 只能增不能改

### Tool: local_workflow_plan
- **Purpose**: 根据任务类型推荐工作流（纯启发式，无 LLM）
- **Input**: `{task_description?: str, files?: [str], format?: "json"|"text"}`
- **Output**: `{ok: bool, workflow_type: "small-code-change"|"docs-only-change"|"high-risk-runtime-change"|"release-local-checkpoint", phases: [...], work_order_template: {...}, advisory_only: true, ...}`
- **Side Effects**: 无
- **LLM Call**: 无（纯启发式）
- **Compatibility**: output 只能增字段；workflow_type enum 只能增

### Tool: local_route_explain
- **Purpose**: 解释 DeepSeek V4 Flash/Pro 路由决策（纯启发式，无 LLM，无 API 调用）。Mock-only，advisory-only。
- **Input**: `{task: str (required), cloud_ok?: bool, local_failures?: int}`
- **Output**: `{ok: bool, task_type: str, risk_level: str, privacy_status: str, recommended_local_profile: str|null, flash_escalation_condition: str|null, pro_escalation_condition: str|null, cloud_allowed: bool, reason: str, escalate_to_flash: bool, escalate_to_pro: bool, advisory_only: true, ...}`
- **Side Effects**: 无
- **LLM Call**: 无（纯启发式，in-process via RouterEngine）
- **Compatibility**: output 字段只能增；task_type 值只能增

---

## 2. CLI Contract

### Command: py -3 tools/local_llm_router.py <task> --stdin
- **Purpose**: 对 stdin 输入执行指定的 worker task
- **Tasks**: `summarize-file`, `summarize-tree`, `generate-test-plan`, `review-diff`, `draft-commit-message`, `draft-pr-summary`, `draft-changelog-entry`, `find-related-files`, `classify-test-failure`
- **Input**: stdin (text) + CLI args
- **Output**: stdout (human-readable or JSON with `--json`)
- **Exit Codes**: 0=success, 1=worker failure, 2=invalid input
- **Side Effects**: 写 `.local_llm_out/`
- **Compatibility**: task 名只能增不能改；输出格式只增字段

### Command: py -3 tools/call_ledger_cli.py <subcommand>
- **Subcommands**: `summary`, `by-task`, `by-profile`, `by-model`, `by-backend`, `by-mcp-tool`, `by-project`, `by-location`, `recent`, `savings`, `escalations`, `debates`, `diagnostics`, `rotate`
- **Output**: stdout (table or JSON with `--json`)
- **Exit Codes**: 0=success, 1=error
- **Side Effects**: 只读（除了 `rotate`）
- **Compatibility**: subcommand 只能增

### Command: py -3 tools/local_workflow_plan.py --stdin --task "<desc>"
- **Purpose**: 纯启发式工作流规划
- **Input**: stdin (file list) + `--task` arg
- **Output**: stdout (human-readable or JSON with `--json`)
- **Exit Codes**: 0=success
- **LLM Call**: 无
- **Compatibility**: 输出格式只增字段

### Command: py -3 tools/router_explain.py "<task>" [--explain|--json|--demo]
- **Purpose**: Explain DeepSeek V4 Flash/Pro routing decisions. Mock-only.
- **Input**: task description (positional args)
- **Output**: stdout — structured RouteDecision (human-readable with `--explain`, JSON with `--json`, demo with `--demo`)
- **Output Fields**: `task_type`, `risk_level`, `privacy_status`, `recommended_local_profile`, `flash_escalation_condition`, `pro_escalation_condition`, `cloud_allowed`, `reason`
- **Exit Codes**: 0=success
- **LLM Call**: 无（纯启发式）
- **Side Effects**: 无
- **Compatibility**: output 字段只能增；task_type 值只能增

### Command: py -3 tools/shadow_route_log.py "<task>" [--actual "<decision>"] [--list|--stats]
- **Purpose**: Record router_explain advisory decisions as shadow routing log (JSONL). Advisory-only.
- **Input**: task description + optional `--actual` (human decision), `--list`, `--stats`
- **Output**: JSONL to `.local_llm_out/shadow_routes/YYYYMMDD.jsonl`
- **Exit Codes**: 0=success
- **LLM Call**: None (pure heuristic in-process via RouterEngine)
- **Side Effects**: Writes `.local_llm_out/shadow_routes/`
- **Compatibility**: JSONL schema fields additive only

### Command: py -3 tools/advisory_workflow.py "<task>" [--cloud-ok] [--local-failures N] [--json]
- **Purpose**: Preflight route-aware task advisor. Wraps router_explain + shadow_route_log. Advisory-only.
- **Input**: task description + optional `--cloud-ok`, `--local-failures`, `--json`
- **Output**: recommended_controller_decision (local|local-first|flash-fallback|pro-review|cloud-blocked|defer) + full router analysis
- **Exit Codes**: 0=success
- **LLM Call**: None (pure heuristic in-process via RouterEngine)
- **Side Effects**: Writes shadow routing log (`.local_llm_out/shadow_routes/`)
- **Compatibility**: decision values additive only

### Command: py -3 tools/precommit_advisory.py [--cloud-ok] [--task "<desc>"] [--json]
- **Purpose**: Non-blocking precommit route check. Reads git diff, prints advisory, always exits 0.
- **Input**: auto-detected git diff (or `--task` override) + optional `--cloud-ok`, `--json`
- **Output**: precommit recommendation + full router analysis
- **Exit Codes**: ALWAYS 0 — never blocks commit
- **LLM Call**: None (pure heuristic in-process via RouterEngine)
- **Side Effects**: Writes shadow routing log (`.local_llm_out/shadow_routes/`)
- **Compatibility**: non-blocking by design; exit code contract must never change

### Command: py -3 tools/shadow_route_report.py [--since <DATE>] [--json] [--output <PATH>]
- **Purpose**: Shadow route report exporter — dogfood metrics from `.local_llm_out/shadow_routes/*.jsonl`. Advisory-only.
- **Input**: optional `--since` (YYYY-MM-DD or ISO), `--json`, `--output` (path under `.local_llm_out/` or external)
- **Output**: Markdown report to stdout or file; JSON with `--json`
- **Exit Codes**: 0=success
- **LLM Call**: None (pure data aggregation, no model calls)
- **Side Effects**: Writes report file only when `--output` specified
- **Compatibility**: report metric keys additive only

### Command: py -3 tools/cost_ledger.py --estimate|--record|--summary [--model <NAME>] [--input-tokens <N>] [--output-tokens <N>] [--task "<DESC>"] [--budget <CNY>] [--json]
- **Purpose**: Local cost ledger and budget guard skeleton for future DeepSeek Flash/Pro calls. Estimate costs, record to JSONL, summarize monthly usage. Advisory-only.
- **Input**: `--estimate` (dry-run, no write) or `--record` (write JSONL) or `--summary` (monthly report) + optional `--model`, `--input-tokens`, `--output-tokens`, `--task`, `--budget`, `--month`, `--notes`, `--json`
- **Output**: stdout (human-readable or JSON with `--json`). Records written to `.local_llm_out/cost_ledger/YYYYMM.jsonl`.
- **Exit Codes**: 0=success, 1=no mode selected, 2=invalid arguments
- **LLM Call**: None (pure local arithmetic, no model calls)
- **Side Effects**: Writes `.local_llm_out/cost_ledger/` (append-only JSONL)
- **Compatibility**: JSONL schema fields additive only; pricing configurable via `COST_LEDGER_PRICING_JSON` env var

### Command: py -3 tools/task_bootstrap.py --project <PATH> --task "<DESC>"
- **Purpose**: 结构化项目上下文初始化
- **Output**: `.local_llm_out/*_bootstrap.md` + `*_bootstrap.json`
- **Exit Codes**: 0=success
- **Compatibility**: bootstrap JSON schema version 向前兼容

### Command: py -3 tools/classify_failure_helper.py
- **Purpose**: 测试失败分类 CLI wrapper
- **Input**: `--stderr` / `--stderr-file` / `--stdout` / `--stdout-file` / `--exit-code` / `--test-command` / `--changed-file` / `--profile` / `--model` / `--json` / `--stdin-json`
- **Output**: stdout (human-readable or JSON)
- **Exit Codes**: 0=classification produced, 2=invalid input, 3=worker/router failure
- **Side Effects**: 写 `.local_llm_out/`
- **Compatibility**: exit code semantics 不变

### Command: py -3 tools/run_checks.py
- **Purpose**: 运行完整测试套件
- **Exit Codes**: 0=all pass, 1=some failed
- **Compatibility**: 检查类别只能增

---

## 3. Config Contract

### Config File: tools/local_llm_profiles.json
- **Format**: JSON
- **Schema**: 每个 profile 至少包含 `model`, `risk_level`, `use_for`
- **Allowed risk_level values** (as of v0.12.0): `"low"`, `"medium"`, `"medium-high"`, `"high"`, `"experimental"`
- **Allowed _backend_class values** (as of v0.12.0): `"ollama"`, `"ollama_heavy_manual"`, `"ollama_mtp_pending"`, `"llamacpp_unconfigured"`, `"unavailable"`, `"placeholder"`
- **Validation**: `py -3 tools/validate_configs.py`
- **Compatibility**: 现有 profile 名不能删除或改名；只能增 profile；只能增字段

### Config Key: `_backend_class`
- **Type**: string
- **Default**: `"ollama"` (implicit for profiles without explicit class)
- **Allowed Values**: see above
- **Used By**: router (eligibility check), call ledger (backend field), health check
- **Compatibility Notes**: 新增 backend class 需要更新 validate_configs 和 router eligibility

### Config Key: `use_for`
- **Type**: [string]
- **Default**: [] (manual only)
- **Used By**: router (task → profile matching), validate_configs
- **Compatibility**: use_for 值只能增（新增 task type）

### Env Var: `LOCAL_LLM_BASE_URL` / `OLLAMA_HOST`
- **Purpose**: 指定远程 Ollama 实例
- **Type**: URL string
- **Used By**: worker, health check
- **Compatibility**: 行为不变 — 设置后所有工具使用远程 Ollama

### Env Var: `LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE`
- **Purpose**: 恢复 legacy auto-escalation 行为
- **Type**: truthy string (`true`/`1`/`yes`/`on`, case-insensitive)
- **Default**: OFF
- **Used By**: MCP server (`_check_quality_escalation`)

### Env Var: `LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN`
- **Purpose**: 恢复 legacy auto-escalation 行为
- **Type**: truthy string
- **Default**: OFF
- **Used By**: MCP server (`_check_quality_escalation`)

---

## 4. File / Directory Contract

### Path: .local_llm_out/
- **Purpose**: 所有本地 LLM 产出的输出目录
- **Format**: 自由格式（Markdown, JSON, text）
- **Created By**: worker, MCP server, hooks
- **Read By**: controller（人工）
- **Can Delete**: 是（安全删除，只影响历史输出）
- **Migration Required**: 否

### Path: .local_llm_out/auto/
- **Purpose**: 自动调用 worker 的输出
- **Created By**: hooks (auto-invocation)
- **Cleanup**: Stop hook 清理 >24h 的文件
- **Can Delete**: 是

### Path: .local_llm_out/feedback/
- **Purpose**: 跨项目 feedback ledger
- **Format**: JSONL (append-only)
- **Created By**: `tools/feedback_ledger.py`
- **Can Delete**: 否（历史记录）

### Path: .local_llm_out/cost_ledger/
- **Purpose**: 云端 API 调用成本预估账本
- **Format**: JSONL (YYYYMM.jsonl, append-only)
- **Created By**: `tools/cost_ledger.py`
- **Read By**: controller（人工）+ budget guard（未来）
- **Can Delete**: 是（删除后失去历史成本追踪；费用未被真实从账户扣除）
- **Migration Required**: 否

### Path: tools/local_llm_profiles.json
- **Purpose**: 模型 profile 注册表
- **Format**: JSON
- **Can Delete**: 否（核心配置）
- **Migration Required**: 修改时必须同步更新 validate_configs

### Path: .mcp.json
- **Purpose**: MCP server 配置（pre-existing tracked config file）
- **Format**: JSON
- **Can Delete**: 否
- **Do Not**: 不要清理此文件 — 它是 tracked config，无 secrets

### Path: VERSION
- **Purpose**: 项目版本号
- **Format**: semver (e.g., `0.12.0`)
- **Do Not**: 不要在非 release-prep phase 修改 VERSION

---

## 5. Model Provider Contract

### Provider Interface (worker)
- **Required Methods**: `call_model(prompt, model, ...) -> ModelCallResult`
- **Input Format**: text prompt + model name
- **Output Format**: `ModelCallResult(content: str, usage: dict | None)`
- **Supported Providers**: `ollama`, `openai-compatible`, `deepseek`
- **Error Handling**: 返回 `(None, error_info)` 而非 raise
- **Timeout Rules**: worker 层 60s default, debate 层 120s, cloud 层 180s
- **Fallback Rules**: 
  - Timeout → lighter model
  - confidence=low | uncertain_points > 3 → 默认不升级（P3-C1/C2）
  - 可恢复 legacy 行为 via env knob

### Cloud Provider Contract (DeepSeek)

- **Provider**: `deepseek`
- **Base URL**: `https://api.deepseek.com`
- **Models**: `deepseek-v4-pro`, `deepseek-v4-flash`
- **Auth**: `DEEPSEEK_API_KEY` env var (required)
- **API Format**: OpenAI-compatible ChatCompletions
- **Thinking Mode**: via `extra_body={"thinking": {"type": "enabled"|"disabled"}}`
- **Reasoning Effort**: `low` / `medium` / `high` (maps to `reasoning_effort` parameter)
- **Context**: 1M tokens max input
- **Output**: 16K-32K tokens (Flash), 32K (Pro)
- **Privacy Gate**:
  - 默认不上传文件内容
  - 必须通过 privacy gate 检查：不含 `.env`、secrets、私有大文本、未经脱敏的用户内容
  - 只允许上传 task packet（本地压缩后的结构化摘要）+ explicitly allowed file snippets
- **Escalation Triggers**:
  - Flash: 本地模型同一任务失败 2 次，或 task packet 超过本地上下文限制
  - Pro: 修改公共接口 / provider / router / MCP / config schema，或 release gate，或本地模型与 Flash 结论冲突
- **Cost Discipline**: cloud agent 必须在 call ledger 中标记 `execution_location=cloud`、`cost_confidence=high`

### Provider Registration (profiles)
- **Entry Format**: `{"model": str, "risk_level": str, "use_for": [str], "_backend_class": str, ...}`
- **Naming Convention**: `family_size_quant_variant` (e.g., `qwen3.6_14b_q8_ud`)
- **Auto-eligibility**: `_backend_class == "ollama"` or `"ollama_mtp_pending"`
- **Manual-only**: `_backend_class == "ollama_heavy_manual"` or model with `risk_level == "experimental"`

---

## 6. Call Ledger Contract

### Ledger Format
- **File**: `.local_llm_out/call_ledger.jsonl`
- **Format**: JSONL (每行一个 JSON object)
- **Schema**: `{timestamp, request_id, task_type, profile, model, provider, backend, tokens_estimated, tokens_in, tokens_out, estimated_cost_cny, execution_location, cost_confidence, duration_ms, success, error_type, failure_type, extra: {...}}`
- **Compatibility**: 字段只能增；现有字段类型不变

### Ledger CLI
- **Subcommands**: see CLI Contract above
- **Read-only** (除了 `rotate`)
- **--json** flag: 输出 JSON 而非表格
- **--diagnostics** flag: 包含 JSONL 文件健康信息

---

## 7. Compatibility Policy

### 默认规则
1. **Minor version (0.x.0) 不破坏已有接口**
2. **破坏性修改必须写 migration 说明**
3. **旧配置至少保留一个版本（deprecation 期）**
4. **所有 schema 变化必须有测试**
5. **CLI 输出字段默认只增不删**

### 破坏性修改的定义
- 删除或重命名 MCP tool 的 input/output 字段
- 删除或重命名 CLI subcommand / flag
- 删除或重命名 config key
- 修改 exit code 语义
- 修改文件路径约定
- 修改 provider contract 的必填方法签名

### 非破坏性修改
- 新增 MCP tool
- 新增 CLI subcommand / flag
- 新增 config key（带默认值）
- 新增 output 字段
- 新增 provider 可选方法

---

## 8. Interface Change Log

### IFACE-CHANGE-007: cost_ledger 新增 CLI tool
- **Date**: 2026-06-13 (cost-ledger chain)
- **What**: 新增 `tools/cost_ledger.py` CLI tool — 本地成本账本 + budget guard skeleton
- **Breaking**: 否（纯新增）
- **Migration**: 无
- **Tests**: 26 mock tests in `tests/test_cost_ledger.py`

### IFACE-CHANGE-006: local_route_explain 新增为 13th MCP tool
- **Date**: 2026-06-13 (route-explain-mcp chain)
- **What**: MCP tool 数量 12 → 13；新增 `local_route_explain` — heuristic route explanation
- **Breaking**: 否（纯新增）
- **Migration**: 无
- **Tests**: 14 mock tests in `tests/test_route_explain_mcp.py`

### IFACE-CHANGE-005: router_explain 新增 CLI tool
- **Date**: 2026-06-13 (router-explain chain)
- **What**: 新增 `tools/router_explain.py` CLI tool — DeepSeek V4 Flash/Pro 路由解释
- **Breaking**: 否（纯新增）
- **Migration**: 无
- **Tests**: 49 mock tests in `tests/test_router_explain.py`

### IFACE-CHANGE-001: local_workflow_plan 新增为 12th MCP tool
- **Date**: 2026-05-26 (S-chain)
- **What**: MCP tool 数量 11 → 12
- **Breaking**: 否（纯新增）
- **Migration**: 无
- **Tests**: 14 focused + tool count updated across 8 locations

### IFACE-CHANGE-002: local_classify_test_failure 新增为 11th MCP tool
- **Date**: 2026-05-26 (D-chain)
- **What**: MCP tool 数量 10 → 11
- **Breaking**: 否（纯新增）
- **Migration**: 无
- **Tests**: 52 prompt + 28 MCP handler

### IFACE-CHANGE-003: local_generate_test_plan 新增 use_repo_map opt-in
- **Date**: 2026-05-26 (C3-chain)
- **What**: 新增 `use_repo_map`, `repo_map_path`, `repo_map_max_files` 参数
- **Breaking**: 否（opt-in，默认不变）
- **Migration**: 无

### IFACE-CHANGE-004: call_ledger 新增 backend / failure_type 字段
- **Date**: 2026-05-26 (J-C4)
- **What**: ledger schema 新增 `backend` 和 `failure_type`
- **Breaking**: 否（新增字段，向后兼容）
- **Migration**: 旧记录 `backend` 为 `""`, `failure_type` 为 `""`
