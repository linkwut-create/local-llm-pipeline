# AGENTS.md

<!-- TEMPLATE: Copy this file to your project root.
     Run GRILLME.md interview to fill in project-specific content.
     Delete this comment block after customization. -->

## 0. Project Identity

### What This Project Is

<!-- TODO: 一句话定位。本项目是…… -->

### What This Project Is NOT

<!-- TODO: 本项目不是……（3-5 条硬边界） -->

### Governance Files

| File | Purpose | When to Read |
|------|---------|-------------|
| **AGENTS.md** (this file) | 项目宪法 + agent 操作规则 | 每次任务开始 |
| **PROBLEMS.md** | 累计问题、禁令、已知坑、高风险区域 | 每次代码修改前 |
| **LONGTODO.md** | 长期路线图、需求、延期项、决策队列 | 触及 roadmap 时 |
| **INTERFACES.md** | API/CLI/Config/Provider 接口契约 | 涉及 API/CLI/config 变更时 |
| **GRILLME.md** | 项目初始化访谈模板 | 新团队成员加入时 |

## 1. Core Design Principles

<!-- TODO: 不可动摇的设计原则（3-7 条）。每条一行，用"禁止"或"默认"开头。 -->

1. **TODO**: 原则一
2. **TODO**: 原则二
3. **TODO**: 原则三

**优先级排序**: <!-- TODO: 安全性 > 接口稳定性 > ... -->

## 2. Architecture Map

<!-- TODO: 核心模块及其职责边界 -->

| Module | Path | Responsibility | Does NOT |
|--------|------|---------------|----------|
| **TODO** | `src/` | TODO | TODO |

## 3. Agent Roles

<!-- TODO: 允许使用的 agent 类型及其职责 -->

| Agent | Responsibility | Allowed Actions | Forbidden Actions |
|-------|---------------|-----------------|-------------------|
| **planner-agent** | 拆任务，不改代码 | Read files, propose plan | Edit, commit |
| **code-agent** | 只改指定文件 | Edit specified files only | Expand scope, change interfaces |
| **test-agent** | 跑测试，定位失败 | Run tests, report failures | Modify source code |
| **review-agent** | 审查 diff | Read diff, flag issues | Commit, push |
| **interface-agent** | 检查接口兼容性 | Read interfaces, flag breaks | Modify interfaces |
| **docs-agent** | 更新文档 | Edit docs only | Modify source code |

## 4. Context Rules

每个 agent 只允许接收：
- 当前任务目标
- 必要文档片段（≤3 个文件的相关 section）
- 相关源文件路径（≤5 个）
- 禁止修改范围
- 期望输出格式

**禁止**把完整聊天记录、完整仓库、完整长期规划塞给所有 agent。

## 5. Development Rules

每次任务流程：
1. Read AGENTS.md relevant sections
2. Read PROBLEMS.md active problems
3. Read INTERFACES.md if touching API/config/CLI
4. Make small plan
5. Implement
6. Test
7. Update docs if necessary

## 6. Commit Rules

提交前必须确认：
- [ ] Tests pass
- [ ] No secret leakage
- [ ] No unexpected format change
- [ ] No undocumented interface change
- [ ] No regression against active problems
- [ ] Review gate passed (if applicable)

## 7. Hard No

<!-- TODO: 绝对禁止的操作 -->

绝对禁止：
- **TODO**: 禁止项 1
- **TODO**: 禁止项 2
- **TODO**: 禁止项 3

---

<!-- CUSTOMIZATION CHECKLIST:
     [ ] §0: Project identity filled in
     [ ] §1: Design principles filled in
     [ ] §2: Architecture map filled in
     [ ] §3: Agent roles customized for this project
     [ ] §7: Hard prohibitions filled in
     [ ] All TODO markers removed
-->
