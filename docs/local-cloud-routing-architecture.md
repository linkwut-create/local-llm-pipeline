# Local-Cloud Routing Architecture

> **项目定位**: local-first、多模型、可解释、可升级的 AI 工作流控制系统

## 1. Three-Layer Architecture

```
                         User Task
                             |
                             v
                 +-----------------------+
                 |   Router / Policy     |  <-- 控制层
                 |   (决策 + 解释)         |
                 +-------+---------------+
                         |
            +------------+------------+
            |                         |
            v                         v
   +-----------------+      +-----------------+
   |  Local Layer    |      |  Cloud Layer    |
   |  (默认,低风险)    |      |  (升级,高风险)   |
   +-----------------+      +-----------------+
      |          |              |          |
   Ollama    llama.cpp      DeepSeek    DeepSeek
   (free)    (free)         V4 Flash    V4 Pro
                            (cheap)     (capable)
```

**不是两个项目，而是一个项目内的三层调度。**

---

## 2. Layer Definitions

### 2.1 Local Layer — 默认执行层

**原则**: local-first。所有任务默认先在本地执行。

| Profile | Model | Role | Risk |
|---------|-------|------|------|
| `fast_summary` | gemma4:12b-unsloth | 摘要、目录总结、文本改写 | low |
| `docs_agent` | gemma4:31b-unsloth | 文档维护、治理文档 | low |
| `code_worker` | qwen3-coder:30b | 代码起草、fix、feature、test-plan | medium |
| `commit_reviewer` | qwen3-coder:30b | commit gate diff review | medium |
| `diff_reviewer` | nemotron:30b | 非 gate diff review | medium |
| `deep_reviewer` | qwen3.6:35b | 深度 review、架构审查 | high |
| `reasoning_checker` | nemotron:30b | 风险分析、逻辑检查 | medium-high |
| `release_auditor` | qwen3.6:35b | release audit (manual only) | high |
| `translation` | glm4.7:flash | 翻译 | low |

**适合本地执行**:
- 文件摘要、目录总结
- 文档整理、README 更新
- 上下文压缩、repo map
- 普通代码辅助、代码起草
- 测试失败初步分析
- 低风险 diff review
- TODO/FIXME 提取
- 任务拆分、规划

**价值**: 省钱、快启动、保护隐私、减少云端 API 消耗、承接大量"脏活"

### 2.2 Cloud Layer — 升级执行层

**原则**: cloud-on-escalation。不是默认入口，由 router 触发升级。

#### DeepSeek V4 Flash — Worker/Fallback

| Profile | Role | Trigger |
|---------|------|---------|
| `deepseek_v4_flash_worker` | 云端 worker | local 失败 >= 2 次 |
| `deepseek_v4_flash_thinking` | 云端 reasoning | 复杂多文件 + local 失败 >= 1 次 |

**适合 Flash**:
- 本地失败 2 次后的 fallback
- 本地空响应 / JSON 格式错误
- 中等复杂多文件任务
- 普通代码修复
- 测试失败分析（本地未解决）
- 文档重写
- 较复杂但非高风险的执行任务

**成本**: $0.14/$0.28 per 1M tokens (input/output)

#### DeepSeek V4 Pro — Reviewer/Arbiter

| Profile | Role | Trigger |
|---------|------|---------|
| `deepseek_v4_pro_reviewer` | 高风险审查 | release / interface / security |
| `deepseek_v4_pro_planner` | 架构规划 | 长期设计 / 复杂分析 |

**适合 Pro**:
- Release gate
- Interface / API / schema change
- Router / provider / config schema change
- Security / privacy 判断
- 架构决策
- 本地模型与 Flash 结论冲突 → Pro 仲裁
- 高成本失败会造成严重后果的任务

**成本**: $0.435/$0.87 per 1M tokens (input/output)

**Pro 不应该天天干活。它应该像"法官"或"总审查员"。**

### 2.3 Router / Policy Layer — 控制层

**原则**: 解释每一个路由决策。

Router 回答 8 个问题：
1. 这个任务是什么类型？
2. 风险等级是多少？
3. 有没有隐私问题？
4. 本地能不能先做？
5. 什么条件触发 Flash？
6. 什么条件触发 Pro？
7. 是否禁止云端？
8. 为什么这么选？

**实现**: `tools/router_explain.py`

```
py -3 tools/router_explain.py "review current diff" --explain
```

---

## 3. Routing Decision Flow

```
Task received
    |
    v
[Privacy Gate] ----BLOCKED----> Local-only (no cloud)
    |
    v
[Task Classifier] --> task_type
    |
    v
[Risk Assessor] --> risk_level (low|medium|high|critical)
    |
    v
[Profile Mapper] --> recommended_local_profile
    |
    +-- local profile exists?
    |       |
    |       YES --> Try local first
    |       NO  --> Go directly to Flash/Pro (based on risk)
    |
    v
Local execution
    |
    +-- success --> DONE
    |
    +-- failure >= 2 --> Escalate to Flash
    |       |
    |       +-- Flash success --> DONE
    |       |
    |       +-- Flash failure --> Escalate to Pro
    |
    +-- risk=high/critical --> Pro required (regardless of local)
    |
    +-- local-Flash conflict --> Pro arbitration
```

---

## 4. Escalation Rules

### 4.1 Flash Escalation

| Trigger | Condition |
|---------|-----------|
| Local failure | >= 2 consecutive failures |
| Empty output | Local model returned nothing |
| Invalid JSON | Local output not parseable |
| Medium task | task_type in (draft-fix, draft-feature, draft-refactor, generate-test-plan) |
| Test unresolved | Test failure analysis not resolved after local attempts |

### 4.2 Pro Escalation

| Trigger | Condition |
|---------|-----------|
| Release gate | task_type = release-risk-review |
| Security review | task_type = security-review |
| Interface change | task_type = interface-review |
| Schema migration | Schema/DDL changes detected |
| High/critical risk | risk_level >= high |
| Conflict arbitration | Flash output conflicts with local |
| Architecture decision | task_type = architecture-review + risk=high |

### 4.3 Cloud Blocked

| Trigger | Status |
|---------|--------|
| API key in content | blocked |
| Private key in content | blocked |
| .env reference | blocked |
| Full repo export | blocked |
| Private document text | needs_sanitization |
| Credentials mention (no value) | safe |

### 4.4 No Auto-Escalation

| Condition | Default |
|-----------|---------|
| confidence=low | Controller decides (opt-in via env knob) |
| uncertain_points > 3 | Controller decides (opt-in via env knob) |
| timeout | Downgrade to lighter model (unchanged) |
| privacy=blocked | Local-only — never escalate |

---

## 5. Example Decisions

### Example 1: Simple Query

```
Task: explain what this function does

task_type: summarize-file
risk_level: low
privacy_status: safe
recommended_local_profile: fast_summary
flash_escalation: local failure >= 2 ; empty/invalid output
pro_escalation: Flash-local conflict
cloud_allowed: no (--cloud-ok not set)
reason: low-risk task, local fast_summary sufficient
```

### Example 2: Diff Review

```
Task: review current diff for bugs

task_type: review-diff
risk_level: medium
privacy_status: safe
recommended_local_profile: commit_reviewer
flash_escalation: local failure >= 2 ; risk=medium -> Flash
pro_escalation: Flash-local conflict
cloud_allowed: no (--cloud-ok not set)
reason: medium-risk, local commit_reviewer is appropriate
```

### Example 3: Release Gate

```
Task: prepare release v2.3 for production deployment

task_type: release-risk-review
risk_level: high
privacy_status: safe
recommended_local_profile: (none)
flash_escalation: local failure >= 2 (pre-check only)
pro_escalation: requires Pro review ; risk=high -> Pro required
cloud_allowed: yes (if privacy gate passes)
reason: release decisions require high-risk judgment, Pro mandatory
```

### Example 4: Security Audit

```
Task: audit codebase for SQL injection vulnerabilities

task_type: security-review
risk_level: high
privacy_status: safe
recommended_local_profile: (none)
flash_escalation: local failure >= 2
pro_escalation: security review -> Pro mandatory
cloud_allowed: yes (if privacy gate passes)
reason: security review requires Pro
```

### Example 5: Privacy Blocked

```
Task: fix the API key sk-abc123... in the config

task_type: draft-fix
risk_level: medium
privacy_status: blocked (API key detected)
recommended_local_profile: code_worker
flash_escalation: (none — cloud blocked)
pro_escalation: (none — cloud blocked)
cloud_allowed: NO
reason: privacy gate blocked — contains sensitive data
```

---

## 6. Implementation Status

| Component | Status | File |
|-----------|--------|------|
| Local Layer profiles | Done | `tools/local_llm_profiles.json` |
| Local Layer tasks | Done | `tools/local_llm_tasks.json` |
| Local router | Done | `tools/local_llm_router.py` |
| Local worker | Done | `tools/local_llm_worker.py` |
| Cloud client | Done | `tools/deepseek_client.py` |
| Cloud profiles | Done | `deepseek_v4_flash_worker` / `_thinking` / `pro_reviewer` / `pro_planner` |
| Router explain engine | Done | `tools/router_explain.py` |
| Router explain tests | Done | `tests/test_router_explain.py` (49/49) |
| Runtime proxy (external) | Done | Separate project — not part of this repo |
| Auto escalation to cloud | Pending | — |
| Privacy gate hardening | Pending | — |

---

## 7. Related Documents

| Document | Focus |
|----------|-------|
| `docs/local-llm-routing.md` | Local router logic |
| `docs/model-routing-policy.md` | Local model selection policy |
| `docs/local-llm-risk-policy.md` | Risk classification policy |
| `docs/mcp-task-policy.md` | MCP task-level usage policy |
| `INTERFACES.md` | Interface contracts (MCP/CLI/Config/Provider) |
| `INTERFACES.md §5` | Cloud provider contract (DeepSeek) |
| `tools/router_explain.py` | Router explain implementation |
| `tools/deepseek_client.py` | Cloud API client + privacy gate |
