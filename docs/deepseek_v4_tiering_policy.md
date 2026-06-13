# DeepSeek V4 Flash/Pro Tiering Policy

**Date**: 2026-06-14
**Phase**: Controlled Real-Tiering Pilot
**Status**: Design — not yet in production auto-router

## Model Names

| Model | Role | Pricing (per 1M tokens) |
|-------|------|--------------------------|
| `deepseek-v4-flash` | High-volume, low-cost, fast | Input $0.14 / Output $0.28 (est.) |
| `deepseek-v4-pro` | High-quality, reasoning, critical | Input $0.55 / Output $2.19 (est.) |

Pricing source: [DeepSeek API Docs](https://api-docs.deepseek.com/quick_start/pricing)
Note: Exact V4 pricing TBC from official page; use cost ledger to track real usage.

## Flash Route (`deepseek-v4-flash`)

**Use when**: Low-risk, high-volume, cheap, repeatable tasks.

| Task type | Example |
|-----------|---------|
| Ordinary summary | Summarize a single file |
| Log triage | Classify test failure from stderr |
| Documentation rewrite | Clean up README, fix typos |
| Low-risk code suggestion | Suggest a single function improvement |
| Draft report | External read-only report first draft |
| Shadow route aggregation | Summarize checkpoint findings |
| Budget class | `< 0.01 CNY per call` |

## Pro Route (`deepseek-v4-pro`)

**Use when**: High-risk, architecture, release, privacy/security, final review.

| Task type | Example |
|-----------|---------|
| Architecture decision | Propose module split or interface change |
| Provider/API review | Review code that touches API keys or providers |
| Release gate | Pre-release checklist validation |
| Multi-file patch plan | Cross-file change proposal |
| Critical mismatch analysis | Analyze shadow route misrouting |
| Security/privacy boundary review | Audit code for secret leakage |
| Final human-confirm review | Last check before manual approval |
| Budget class | `0.01–0.50 CNY per call` |

## Not Allowed (either tier)

| Condition | Reason |
|-----------|--------|
| Automatic production routing | No auto-escalation without human approval |
| Secret-bearing prompts | Never send API keys, tokens, .env content |
| External repo raw content | Never send external project source files |
| Uncontrolled long prompts | Cap at ~4000 tokens input for pilot |
| API key in prompt or log | Key is env-only, never in message body |
| User data (audio, history, subtitles) | Never send user-generated content |

## Decision Fields

When the router recommends DeepSeek, it must populate:

```json
{
  "recommended_provider": "deepseek",
  "recommended_model": "deepseek-v4-flash | deepseek-v4-pro",
  "tier_reason": "<why this tier was chosen>",
  "budget_class": "<estimated cost tier>",
  "privacy_status": "safe | blocked | needs_review",
  "requires_manual_confirm": true
}
```

`requires_manual_confirm` is always `true` during controlled pilot — no auto-call.

## Pilot Constraints

- All DeepSeek calls require explicit user confirmation
- Synthetic prompts only for smoke tests
- Real task prompts capped at 4000 input tokens
- All usage recorded in cost ledger
- Model responses checked for non-empty before counting
- No retry loops — one attempt per call during pilot
