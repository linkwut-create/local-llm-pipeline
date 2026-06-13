# Claude Code DeepSeek Routing Inspection

**Date**: 2026-06-14

## Current State: Single-Model DeepSeek V4 Pro

| Config | Value |
|--------|-------|
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_MODEL` | `deepseek-v4-pro[1m]` |
| `ANTHROPIC_SMALL_MODEL` | **NOT SET** |
| `DEEPSEEK_API_KEY` | Set (not printed) |
| `DEEPSEEK_BASE_URL` | Not set |
| `DEEPSEEK_MODEL` | Not set |

## Routing Diagram

```txt
Claude Code
  └─ Anthropic-compatible API → https://api.deepseek.com/anthropic
       └─ deepseek-v4-pro[1m]  ← EVERYTHING goes here
```

## Verdict: SINGLE-MODEL

- **No Flash/Pro split configured.**
- All tasks — main reasoning, subagents, code generation, summarization — use `deepseek-v4-pro`.
- `ANTHROPIC_SMALL_MODEL` is the key missing piece for tiering.
- There is no `ANTHROPIC_SMALL_MODEL=deepseek-v4-flash` configured.
- There are no per-task-type model overrides in settings.

## Impact

| Concern | Detail |
|---------|--------|
| Cost | Pro ~$0.55/$2.19 per 1M input/output vs Flash ~$0.14/$0.28 (≈4—10×) |
| Subagent waste | Subagents, summaries, and cheap tasks all hit Pro |
| No budget protection | Nothing prevents a subagent from burning Pro tokens |

## What Enables Tiering

Setting `ANTHROPIC_SMALL_MODEL=deepseek-v4-flash` in the environment would allow:

```txt
Claude Code
  ├─ Main model → deepseek-v4-pro[1m]  (ANTHROPIC_MODEL)
  └─ Small/subagent → deepseek-v4-flash (ANTHROPIC_SMALL_MODEL)
```

## Next Step

- Set `ANTHROPIC_SMALL_MODEL=deepseek-v4-flash`
- Verify subagents use Flash (inspect via response `model` field)
- Add cost tracking per tier
- local-llm-pipeline soft gate can then recommend Flash/Pro based on task risk

## Notes

- API key not printed, not read from file, not logged.
- Configuration inspected via env vars + Claude settings files only.
