# INTERFACES.md

<!-- TEMPLATE: Copy this file to your project root.
     Populate by documenting every stable interface in your project.
     Update every time an interface changes.
     Delete this comment block after first customization. -->

## 0. Purpose

本文件记录所有稳定接口、调用习惯、兼容性要求。

**任何修改 API / CLI / config / storage schema / plugin protocol 的任务，都必须先读本文件。**

---

## 1. CLI Contract

<!-- TODO: 每个 CLI 命令的接口契约 -->

### Command: <!-- `xxx` -->
- **Purpose**:
- **Usage**:
- **Inputs**:
- **Outputs**:
- **Exit Codes**:
- **Backward Compatibility**:
- **Examples**:

## 2. API Contract

<!-- TODO: 每个 API endpoint 的接口契约（如果有） -->

### Endpoint: <!-- GET/POST /xxx -->
- **Purpose**:
- **Request**:
- **Response**:
- **Errors**:
- **Compatibility Notes**:

## 3. Config Contract

<!-- TODO: 每个配置项的接口契约 -->

### Config Key: <!-- xxx -->
- **Type**:
- **Default**:
- **Allowed Values**:
- **Used By**:
- **Compatibility Notes**:

## 4. File / Directory Contract

<!-- TODO: 重要的文件/目录约定 -->

### Path: <!-- xxx -->
- **Purpose**:
- **Format**:
- **Created By**:
- **Read By**:
- **Can Delete**:
- **Migration Required**:

## 5. Provider / Plugin Contract

<!-- TODO: 如果有 provider 或 plugin 系统 -->

### Provider Interface
- **Required Methods**:
- **Input Format**:
- **Output Format**:
- **Error Handling**:
- **Timeout Rules**:
- **Fallback Rules**:

## 6. Compatibility Policy

### 默认规则
1. Minor version 不破坏已有接口
2. 破坏性修改必须写 migration
3. 旧配置至少保留一个版本
4. 所有 schema 变化必须有测试

## 7. Interface Change Log

<!-- TODO: 记录每次接口变更 -->

### IFACE-CHANGE-001
- **Date**:
- **What changed**:
- **Why**:
- **Breaking**:
- **Migration**:
- **Tests**:
- **Docs updated**:

---

<!-- CUSTOMIZATION CHECKLIST:
     [ ] §1: All CLI commands documented with exit codes
     [ ] §2: All API endpoints documented (if applicable)
     [ ] §3: All config keys documented with defaults
     [ ] §4: Key file/directory conventions documented
     [ ] §5: Provider/plugin contract documented (if applicable)
     [ ] §6: Compatibility policy customized
     [ ] All TODO markers removed
-->
