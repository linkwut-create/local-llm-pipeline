# PROBLEMS.md

<!-- TEMPLATE: Copy this file to your project root.
     Populate by running GRILLME.md interview (especially Group H).
     Add to this file every time an agent makes a mistake worth preventing again.
     Delete this comment block after first customization. -->

## 0. Purpose

本文件记录：已知问题、历史踩坑、禁止重复的错误做法、高风险区域、需要人工确认的边界。

**这不是 bug list。这是防止 agent 重复犯错的记忆层。**
每次 agent 犯一个值得记录的错，就加一条禁令或已知问题。

---

## 1. Active Problems

<!-- TODO: 当前已知但未修复的问题 -->

### PROB-001: <!-- 问题标题 -->
- **Status**: active / mitigated / resolved
- **Area**: <!-- backend / frontend / config / tests / ... -->
- **Symptom**:
- **Cause**:
- **Do Not**:
- **Recommended Fix**:
- **Related Tests**:
- **Related Files**:

## 2. Forbidden Patterns

<!-- TODO: 禁止重复的错误做法 -->

### BAN-001: <!-- 禁令标题 -->
- **Reason**: <!-- 为什么禁止 -->
- **错误示例**: <!-- 具体的错误代码或做法 -->
- **正确做法**: <!-- 应该怎么做 -->

## 3. Fragile Areas

<!-- TODO: 高风险模块 -->

| 文件 / 区域 | 风险原因 | 修改前必须 |
|------------|---------|-----------|
| **TODO** | TODO | TODO |

## 4. Historical Incidents

<!-- TODO: 过去发生过的问题 -->

### INC-001: <!-- 标题 -->
- **Date**:
- **Symptom**:
- **Root Cause**:
- **Fix**:
- **Resulting Ban**: BAN-XXX

## 5. Review Checklist

每次修改代码前检查：

- [ ] 是否触碰 Fragile Areas 中的高风险文件？
- [ ] 是否违反 Forbidden Patterns 中的任何禁令？
- [ ] 是否需要更新 INTERFACES.md？
- [ ] 是否需要更新 tests？

---

<!-- CUSTOMIZATION CHECKLIST:
     [ ] §1: At least initial known problems documented
     [ ] §2: At least initial forbidden patterns documented
     [ ] §3: Fragile areas identified
     [ ] All TODO markers removed
-->
