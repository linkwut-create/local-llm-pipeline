---
owner: zero
status: approved
created: 2026-06-13
updated: 2026-06-13
phase: 4
freeze: true
audit: needed-for-real-call
milestones:
  - route-advisory
  - cost-ledger
  - privacy-gate
  - dry-run-contract
  - dry-run-convergence-audit
  - api-execution-adapter-design
  - mock-skeleton
  - mock-skeleton-convergence-audit
  - guarded-real-run-design
---

# Phase 4 PRD: Local-to-Cloud Routing Pipeline

## 0. Governance

> **G-1**: Phase 4 从 route advisory 覆盖到 DeepSeek execution adapter design audit。所有新增工具均已提交并通过 shadow route report 验证。当前阶段冻结，不得再新增功能。
>
> **G-2**: 以下所有内容均为 **已落地实现**（见 `git log` 和 `INTERFACES.md`）。本 PRD 是实现后的文档收敛，非设计草稿。
>
> **G-3**: 真实 DeepSeek API 调用仍未实现。下一阶段 `deepseek_execution_adapter.py` 的第一版必须以 `--real-run` 默认关闭的 mock skeleton 交付。

---

## 1. 当前系统覆盖

| Layer | Tool | Purpose | API? |
|-------|------|---------|------|
| Route advisory | `router_explain.py` | Task classification + risk grading | No |
| Route advisory | `shadow_route_log.py` | Router vs human decision log (JSONL) | No |
| Route advisory | `shadow_route_report.py` | Shadow route metrics + mismatch detection | No |
| Route advisory | `advisory_workflow.py` | Preflight task advisor | No |
| Route advisory | `precommit_advisory.py` | Non-blocking pre-commit route check (always exit 0) | No |
| Cost governance | `cost_ledger.py` | Dry-run cost estimation + budget guard skeleton | No |
| Cost governance | `call_ledger.py` | Per-call JSONL accounting (local LLM) | No |
| Cost governance | `call_ledger_cli.py` | Query CLI for call ledger | No |
| Privacy governance | `privacy_gate.py` | Rule-based secret/credential/private-key detection | No |
| Privacy governance | `deepseek_client.py` | Real API client with built-in `_check_privacy()` | **Yes** |
| Execution contract | `deepseek_dry_run.py` | Composes router + privacy + cost into governance plan | No |
| **Design** | `docs/deepseek_api_execution_adapter_design.md` | 10-section execution adapter design contract | N/A |
| **Design** | `docs/guarded_real_run_adapter_design.md` | 12-section guarded real-run design packet | N/A |
| **Mock** | `tools/deepseek_execution_adapter.py` | 6-gate mock skeleton (real-run blocked) | No |
| **Future** | `tools/deepseek_execution_adapter.py` gate [6] | guarded_api_call (next phase) | **Yes** (future) |

---

## 2. 已验证的组合行为

| 场景 | 预期 decision | 实际 | 审计日期 |
|------|-------------|------|---------|
| diff review + Flash + budget ok | `allow_dry_run` | `allow_dry_run` | 2026-06-13 |
| release gate + Flash | `needs_pro_review` | `needs_pro_review` | 2026-06-13 |
| release gate + Pro | `allow_dry_run` | `allow_dry_run` | 2026-06-13 |
| `.env` credentials text | `allow_dry_run` (needs_review) | `allow_dry_run` (needs_review) | 2026-06-13 |
| huge tokens + low budget | `blocked_by_budget` | `blocked_by_budget` | 2026-06-13 |
| gibberish unknown task | `defer` | `defer` | 2026-06-13 |
| unknown model | `unknown_price` | `unknown_price` | 2026-06-13 |

---

## 3. 真实调用进入条件

真实 DeepSeek API 调用必须满足以下全部条件，缺一不可：

```txt
1. cloud_ok = true    （显式 flag）
2. real_run = true    （显式 flag，默认关闭）
3. privacy_status = safe（或 needs_review + --privacy-reviewed flag）
4. budget allowed      （未知价格 / 超预算均视为不允许）
5. model in allowlist  （deepseek-v4-flash 或 deepseek-v4-pro）
6. DEEPSEEK_API_KEY env var 已设置
7. 上述所有步骤通过 controller 的显式确认
```

任何条件不满足 → 不进入 API 调用。

---

## 4. 禁止清单（当前阶段）

```txt
- 不调用 DeepSeek API（禁止，除非所有条件满足）
- 不修改 deepseek_client.py
- 不修改 local_llm_profiles.json
- 不修改 hooks / mcp_gate.py
- 不接 llm-proxy
- 不自动执行 worker / 不上传上下文
- 不提交 .local_llm_out/
- 不读取 API key 到日志 / JSONL
- dry-run 不增加真实调用能力
```

---

## 5. 下一阶段

```txt
Phase 4a: deepseek_execution_adapter.py mock skeleton
  - --real-run 默认关闭
  - 所有 gate 逻辑实现，但 API 调用位置为 mock/stub
  - 通过测试但不发起网络请求

Phase 4b: 真实 DeepSeek 调用
  - 在 mock skeleton 审计通过后，接入 deepseek_client.call_deepseek()
  - --real-run 启用（需满足全部进入条件）
```

---

*PRD generated 2026-06-13 from completed Phase 4 implementation. No new requirements — this is a convergence document.*
