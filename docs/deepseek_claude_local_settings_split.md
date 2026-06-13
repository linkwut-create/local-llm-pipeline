# Claude Code DeepSeek Local Settings Split

日期: 2026-06-14

## 背景

Claude Code subagent 消耗过高 — 一个极小分类任务消耗 79.0k tokens。
需要验证 Claude Code 内部是否真正支持主模型 Pro / subagent Flash 的分层。

通过 `.claude/settings.local.json` 的 `env` 字段持久化模型配置，
从 DeepSeek usage 侧验证 subagent 是否走了 Flash。

## 配置内容

文件: `.claude/settings.local.json` (local scope, 不影响团队)

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_MODEL": "deepseek-v4-pro[1m]",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
    "CLAUDE_CODE_SUBAGENT_MODEL": "deepseek-v4-flash"
  }
}
```

注意: 未写入 API key (API key 通过环境变量或全局 settings 提供)。

## 验证记录

| 项目 | 状态 |
|------|------|
| settings.local.json 是否存在 | 是 (已存在, 本次合并 env 字段) |
| 是否写入 API key | 否 |
| 主模型 | `deepseek-v4-pro[1m]` |
| Haiku/default model | `deepseek-v4-flash` |
| subagent model | `deepseek-v4-flash` |
| 是否重新启动 Claude Code | 待验证 |
| 是否触发 subagent | 待验证 |
| 是否在 DeepSeek usage 中看到 Flash | 待验证 |
| 是否仍全部走 Pro | 待验证 |
| 结论 | 待 DeepSeek usage 侧验证 |

## 官方文档支撑

- `CLAUDE_CODE_SUBAGENT_MODEL`: 用于所有 subagents / agent teams 的模型
- `ANTHROPIC_DEFAULT_HAIKU_MODEL`: 用于 haiku / background functionality
- `ANTHROPIC_SMALL_FAST_MODEL`: 已弃用
- 环境变量应在启动 `claude` 前设置, 也可写入 `settings.json` 的 `env` 字段
- Local scope (`.claude/settings.local.json`): 个人、本仓库、不共享

参考:
- https://code.claude.com/docs/en/env-vars
- https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/settings

## 真正判定方式

不要看 Claude 自己说"可不可见"。看 DeepSeek 账单或 usage:

```
如果 usage 里出现 deepseek-v4-flash:
  Claude Code subagent 分层成功

如果 usage 仍只有 deepseek-v4-pro:
  Claude Code 内部分层失败，改用 local-llm-pipeline 外部分流

如果无法区分:
  需要 logging proxy；否则不能确认
```

## 注意

`.claude/settings.local.json` 不提交 (local scope 个人配置)。
