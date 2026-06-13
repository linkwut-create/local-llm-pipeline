# Dogfood Checkpoint #40 — Corrected

**Date**: 2026-06-14
**Decision**: PASS_WITH_LIMITS

## Reason

- Safety invariants pass: privacy_bypass=0, false_cloud_on_secret=0, new critical_misrouting=0
- No router changes, no soft gate changes, no DeepSeek calls
- Warning gate / Stop hook / hard block remain blocked
- Process deviation existed: #37 initially had record without new implementation commit
- Process deviation existed: #39 was initially merged into #36 (not independently committed)
- Process deviation existed: #36 commit hash not listed in initial checkpoint report

## Correction Commits

| # | Commit | Description |
|---|--------|-------------|
| #37 | `3ce6dbb` | `test: complete dogfood 37 advisory workflow coverage` |
| #39 | `4be61a6` | `docs: complete dogfood 39 checkpoint prep` |
| #40 | (this commit) | `docs: correct dogfood checkpoint 40` |

## Safety Status

```txt
privacy_bypass:           0
false_cloud_on_secret:    0
new critical_misrouting:  0
total critical_misrouting: 5 (historical, from pre-calibration data)
router:                   unchanged
soft gate:                unchanged
DeepSeek:                 not called
warning gate:             still blocked (match_rate 70.7% < 85%)
Stop hook:                still blocked
hard block:               still blocked
```

## Verified Commits

| # | Status | Independent |
|---|--------|-------------|
| #31 | committed | yes |
| #32 | committed | yes |
| #33 | committed | yes |
| #34 | committed | yes |
| #35 | committed | yes |
| #36 | committed | yes (hash now in records) |
| #37 | corrected (3ce6dbb) | yes |
| #38 | committed | yes |
| #39 | corrected (4be61a6) | yes |
| #40 | this document | yes |

## Constraints

- No history rewrite
- No rebase
- No squash
- No router modification
- No soft gate modification
- No warning gate activation
- No Stop hook activation
- No hard block activation
- No DeepSeek calls
- No API key reads
- No `git add -A`

## Next Steps

Continue #41—#50 under the same constraints. Warning gate design remains blocked
until match_rate >= 85% and critical_misrouting = 0.
