# Dogfood Checkpoint #45 — Integrity Correction

**Date**: 2026-06-14
**Decision**: PASS_WITH_LIMITS

## Safety Invariants

```txt
privacy_bypass:           0 ✓
false_cloud_on_secret:    0 ✓
router:                   unchanged
soft gate:                unchanged
DeepSeek:                 not called
API key:                  not read
warning gate:             still blocked (match_rate 72.2% < 85%)
Stop hook:                still blocked
hard block:               still blocked
```

## Process Issue

`critical_misrouting` increased from 5 to 6 during #41—#45. The new entry
is #44 task:

```txt
task:     "add soft gate dogfood status progress formatting tests"
router:   governance-integration / high
actual:   local-first
result:   new critical_misrouting +1
```

## Root Cause

The router classification (`governance-integration / high`) was correct:
the task involves dogfood status thresholds, warning gate candidate logic,
and progress formatting — all control-plane governance concerns.

The `actual` label was wrong. A high-risk governance-integration task should
be logged as `pro-review`, not `local-first`. Even though the implementation
was local-only test code with no cloud call, the routing recommendation
was `pro-review` and `manual_confirm_recommended=true`.

**This is an operator labeling/process error, not a router error.**

## Correction

- Do **not** rewrite historical shadow_route JSONL
- Do **not** run router calibration
- Record this as a labeling/process error in the checkpoint log
- The critical_misrouting count remains 6 (historical record is not altered)

## Forward Rule

For future dogfood tasks, when the router returns:

| Condition | Actual must be |
|-----------|---------------|
| `router_risk_level == "high"` | `pro-review` (normally) |
| `decision == "manual_confirm_recommended"` | `pro-review` (normally) |
| `task_type in {governance-integration, control-plane-boundary}` | `pro-review` (normally) |
| `task_type in {release-risk-review, interface-review, security-review}` | `pro-review` |
| Low/medium ordinary implementation, tests, or docs | `local-first` |

"Normally" means: unless there is a documented reason to override.
Overrides should be noted in the commit message or the shadow_route_log
call.

## Commit Map (#41—#44)

| # | Commit | Description | Actual |
|---|--------|-------------|--------|
| #41 | `31204ef` | `test: cover cost ledger record schema` | `local-first` ✓ |
| #42 | `fd03abc` | `test: cover privacy gate filename casing` | `local-first` ✓ |
| #43 | `e946aaf` | `docs: update cost ledger privacy notes` | `local-first` ✓ |
| #44 | `0d18185` | `test: cover dogfood status progress formatting` | `local-first` ✗ (应为 `pro-review`) |

## Next Steps

Continue #46—#50 with the corrected actual labeling rule in effect.
Warning gate design remains blocked until match_rate >= 85% and
critical_misrouting = 0.
