# DeepSeek V4 Flash/Pro Real Smoke Result

**Date**: 2026-06-14
**API Key**: Available (not printed, not logged)

## Results

| Metric | Flash | Pro |
|--------|-------|-----|
| Model | `deepseek-v4-flash` | `deepseek-v4-pro` |
| HTTP status | 200 | 200 |
| Latency | 2147ms | 2317ms |
| Content | `OK` | `OK` |
| Non-empty | ✓ | ✓ |
| Prompt tokens | 9 | 9 |
| Completion tokens | 21 | 43 |
| Total tokens | 30 | 52 |
| Prompt | `"Reply with exactly: OK"` | same |

## Cost Estimate

Using pricing from tiering policy (est.):
- Flash: ~0.000004 CNY (9 × $0.14/1M + 21 × $0.28/1M)
- Pro: ~0.000025 CNY (9 × $0.55/1M + 43 × $2.19/1M)

Both well under 0.01 CNY.

## Notes

- max_tokens=20 produced empty output (reasoning token exhaustion — known from model audit)
- max_tokens=128 resolved: both models returned "OK"
- Flash used fewer completion tokens (21) than Pro (43) — expected, Pro includes reasoning
- Both models confirmed reachable and responding

## Compliance

| Check | Status |
|-------|--------|
| API key printed | No |
| API key in log | No |
| Repo content sent | No |
| External project content sent | No |
| User data sent | No |
| Auto-retry used | No |
| Production auto-router enabled | No |

## Verdict

**Both Flash and Pro transport OK.** Ready for controlled tiering design.
Neither is production auto-routed.
