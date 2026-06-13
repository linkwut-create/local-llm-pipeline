# DeepSeek V4 Flash/Pro Real Smoke Plan

**Date**: 2026-06-14
**Phase**: Controlled Real-Tiering Pilot

## Flash Smoke

| Parameter | Value |
|-----------|-------|
| Model | `deepseek-v4-flash` |
| Prompt | `"Reply with exactly: OK"` (5 tokens target) |
| Max tokens | 20 |
| Temperature | 0 |
| Expected | Non-empty response, no error |

## Pro Smoke

| Parameter | Value |
|-----------|-------|
| Model | `deepseek-v4-pro` |
| Prompt | `"Reply with exactly: OK"` (5 tokens target) |
| Max tokens | 20 |
| Temperature | 0 |
| Expected | Non-empty response, no error |

## Recorded Fields

| Field | Source |
|-------|--------|
| `model` | From request |
| `latency_ms` | Wall-clock round trip |
| `prompt_tokens` | From response `usage.prompt_tokens` |
| `completion_tokens` | From response `usage.completion_tokens` |
| `total_tokens` | From response `usage.total_tokens` |
| `non_empty_response` | `len(content) > 0` |
| `estimated_cost` | From cost ledger pricing |

## Forbidden

- Do NOT print API key or full headers
- Do NOT send repo content, external project files, or user data
- Do NOT embed secrets in the prompt
- Do NOT auto-retry on failure — one attempt per model
- Do NOT enable this as production auto-router

## API Key Handling

- Key read from `os.environ["DEEPSEEK_API_KEY"]` — env-only, never logged
- If key not set: skip, record `NOT_CONFIGURED`, do not prompt user
- Key value never appears in any output, log, or committed file

## Pre-Call Checklist

- [ ] DEEPSEEK_API_KEY exists in environment
- [ ] Prompt is synthetic (no repo content)
- [ ] Max tokens ≤ 20
- [ ] Temperature = 0
- [ ] Privacy gate check on prompt text: safe
