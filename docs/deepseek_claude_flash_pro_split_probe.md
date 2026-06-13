# Claude Code DeepSeek Flash/Pro Split Probe

**Date**: 2026-06-14

## Setup

```powershell
$env:ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$env:ANTHROPIC_MODEL = "deepseek-v4-pro[1m]"
$env:ANTHROPIC_SMALL_MODEL = "deepseek-v4-flash[1m]"
```

## Anthropic Endpoint Verification

| Model | HTTP | Latency | Content | Tokens (in/out) |
|-------|------|---------|---------|-----------------|
| `deepseek-v4-pro` | 200 | 2301ms | OK (via thinking+text blocks) | 8/32 |
| `deepseek-v4-flash` | 200 | 2236ms | OK (via thinking+text blocks) | 9/32 |

Both models confirmed reachable and responding via `https://api.deepseek.com/anthropic`.

Response format: `[{type: "thinking", text: ""}, {type: "text", text: "OK"}]` — DeepSeek V4 includes a thinking block even when reasoning is minimal.

## Current Limitation

This probe was run FROM INSIDE Claude Code. Claude Code cannot change its own
model routing mid-session. The `ANTHROPIC_SMALL_MODEL` env var was set in a
sub-shell PowerShell session — it does not affect the already-running process.

## Verdict

| Question | Answer |
|----------|--------|
| ANTHROPIC_MODEL | `deepseek-v4-pro[1m]` |
| ANTHROPIC_SMALL_MODEL | `deepseek-v4-flash[1m]` (set in sub-shell) |
| Claude Code 接受 small model? | **Cannot verify from inside session** |
| Flash observable? | **Cannot observe from inside** |
| Both models work via Anthropic endpoint? | **Yes — confirmed** |
| API key read? | No |
| Repo content sent? | No |
| External repo modified? | No |

## To Verify Split: Start New Session

The split can only be verified by:

1. Close this Claude Code session.
2. Set `ANTHROPIC_SMALL_MODEL=deepseek-v4-flash[1m]` in the terminal BEFORE
   launching Claude Code.
3. Run a small task (e.g., "summarize a single sentence").
4. Observe whether the response or logs mention `deepseek-v4-flash`.

## If Claude Code Ignores SMALL_MODEL

If Claude Code does not support per-task-type model routing via env vars,
the alternative is:

```txt
local-llm-pipeline soft gate → recommend Flash/Pro → controller calls
the appropriate model via direct API, not via Claude Code internal routing.
```

This would make local-llm-pipeline the tiering layer, not Claude Code.
