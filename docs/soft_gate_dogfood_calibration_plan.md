# Soft Gate Dogfood Calibration Plan

**Date**: 2026-06-13
**Status**: Plan only. No router changes made.
**Prerequisite**: CLAUDE.md default soft gate protocol committed.
**Next step**: Router calibration round for soft gate governance tasks.

---

## 1. Current Metrics

| Metric | Value | Target (warning gate) |
|--------|-------|----------------------|
| total_records | 166 | n/a |
| match_rate | 67.4% | >= 85% |
| unknown_rate | 44.6% | <= 25% |
| blocked_count | 5 | n/a |
| high_risk_count | 40 | n/a |
| privacy_bypass | 0 | 0 ✅ |
| false_cloud_on_secret | 0 | 0 ✅ |
| critical_misrouting | 2 | 0 |
| release_security_interface_pro_rate | 26.7% | >= 50% |

---

## 2. Mismatch Classification

### Type 1: High-risk under-classified (2 critical_misrouting)

Both are pre-existing calibration exercises, not systemic failures:

1. "calibrate router explain edge cases..." → interface-review/high, actual=local-first
   - **Root cause**: Deliberate calibration exercise. Human overrode router.
   - **Fix**: Stale data. Will age out as new records accumulate.

2. "review INTERFACES.md for breaking changes..." → release-risk-review/high, actual=local
   - **Root cause**: Governance doc review, human chose local.
   - **Fix**: Stale data. Pre-dates current router rules.

### Type 2: Unknown task over-produced (~74 records, 44.6%)

Router returns "unknown" for vocabulary not in its pattern set:

| Example task text | Router says | Should be |
|------------------|-------------|-----------|
| "design audit for DeepSeek API execution adapter..." | unknown | api-execution-boundary |
| "precommit review for DeepSeek API execution adapter..." | unknown | api-execution-boundary |
| "design Claude Code soft gate integration..." | unknown (was api-execution-boundary later) | governance-docs or api-execution-boundary |
| "plan soft gate dogfood calibration..." | unknown | governance-docs |
| "audit Claude Code soft gate skeleton..." | unknown | api-execution-boundary |
| "implement Claude Code soft gate skeleton..." | draft-feature/medium | api-execution-boundary/high |
| "draft CLAUDE.md default soft gate usage rules..." | governance-docs/low | ✅ (correct, but actual=pro-review) |

### Type 3: Medium-risk ambiguity

Tasks like "implement ... skeleton" are drafting code but also touching API boundaries.
Router correctly classifies as draft-feature/medium, but human escalates to pro-review.
This is acceptable — conscious escalation is a feature, not a bug.

### Type 4: Actual logging mismatch

Several records have actual="pro-review" but router says unknown/low or governance-docs/low.
This is conscious human escalation for governance-boundary tasks. Acceptable pattern.

### Type 5: Stale historical data

The first ~60 records pre-date router calibration for api-execution-boundary.
These records drag down match_rate but are not indicative of current accuracy.

---

## 3. Router Calibration Candidates

### C1: Broaden governance-docs pattern

```
Current: \bgovernance\b, \bproblems\.md\b, etc.
Add: \bsoft.gate\b, \bconvergence.audit\b, \bcalibration.plan\b,
     \bdogfood\b, \bdefault.workflow\b
Expected: governance-docs/low
Risk: low — purely documentation tasks
```

### C2: Broaden api-execution-boundary pattern

```
Current: deepseek.*(adapter|execution|api.call|real), execution.adapter, etc.
Add: \bAPI.boundary\b, \bgovernance.integration\b.*\b(claud|codex|agent)\b,
     \bcontrol.plane\b, \bdefault.governance\b
Expected: api-execution-boundary/high
Risk: medium — careful not to catch "review API docs"
```

### C3: Add "design audit" / "design packet" recognition

```
Current: No pattern for design audit tasks.
Add: \bdesign.audit\b, \bdesign.packet\b (as governance-docs when paired
     with governance keywords; as api-execution-boundary when paired
     with deepseek/adapter/real-run/API)
Expected: governance-docs/low OR api-execution-boundary/high (context-dependent)
Risk: medium — needs context-sensitivity
```

### C4: Add "Stop hook" / "warning gate" / "hard block" as high-risk

```
Pattern: \bstop.hook\b, \bwarning.gate\b, \bhard.block\b,
         \bautomatic.blocking\b, \bexecution.enforcement\b
Expected: api-execution-boundary/high
Risk: low — these are clearly API/governance boundary terms
```

### C5: Expand "precommit review" mapping

```
Current: Sometimes maps to deep-code-review/medium, sometimes unknown.
Fix: Add "precommit review" as governance-docs/low (it's a governance check,
     not a code review).
Expected: governance-docs/low
Risk: low
```

---

## 4. Soft Gate Test Gaps

### Missing severity/decision coverage

| Scenario | Current test? | Need? |
|----------|--------------|-------|
| "soft gate protocol" → governance integration | No | Yes — expect orange/manual_confirm |
| "warning gate design" → api-execution-boundary | No | Yes — expect orange/manual_confirm |
| "Stop hook integration" → api-execution-boundary | No | Yes — expect orange/manual_confirm |
| "hard block implementation" → api-execution-boundary | No | Yes — expect orange/manual_confirm |
| "control plane design" → governance-docs or api-execution-boundary | No | Yes |
| "calibration plan" → governance-docs | No | Yes — expect green/allow or yellow/warn |
| "broader real-run implementation" → api-execution-boundary | No (covered by existing) | Yes — verify blocking |

### Missing invariant tests

| Test | Current? |
|------|----------|
| Any decision with "allow" + would_block=false | ✅ |
| All 5 decisions ensure would_block=false | ✅ |
| advisory_only=true after every code path | ✅ |

---

## 5. Special Cases Needing Attention

### Case: "local-first" actual but router wants pro-review

Several records show human choosing local-first for interface-review/high tasks.
These are governance doc reviews — correct human judgment but router disagrees.

**Recommendation**: Do NOT recalibrate router to make these "local". Instead,
accept that governance doc reviews will naturally cluster at local-first/pro-review
boundary and that conscious human override is a feature.

### Case: "pro-review" actual but router says unknown/low

Conscious human escalation for API boundary tasks. Router calibration (C2-C4 above)
will reduce this category by giving router more vocabulary. Remaining cases are
acceptable — pro-review is the safe default for unknown high-stakes tasks.

---

## 6. Next Calibration Round

```
Task: router calibration round for soft gate governance tasks
Scope:
  - Implement C1-C5 calibration candidates
  - Add 8-10 new router tests
  - Add 6-8 new soft_gate tests
  - Run full test suite
  - Re-run shadow_route_report to measure improvement
Target:
  - critical_misrouting: 0 (mark existing 2 as stale calibration data)
  - unknown_rate: < 35% (from 44.6%)
  - match_rate: > 75% (from 67.4%)
  - privacy_bypass: 0 (maintain)
  - false_cloud_on_secret: 0 (maintain)
NOT target:
  - match_rate >= 85% (may require multiple rounds)
  - warning gate activation
```

---

## 7. Block Conditions (Unchanged)

```
Until calibration improves:
- no warning gate
- no Stop hook
- no hard block
- no automatic blocking
- no broader DeepSeek real-run
```

---

*Calibration plan completed 2026-06-13. No router changes made. No API calls.*
