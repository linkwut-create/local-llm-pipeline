# Post-Calibration Shadow Route Audit

**Date**: 2026-06-13
**Calibration commit**: `2a91b2b fix: calibrate router for soft gate governance tasks`
**Decision**: **PASS_WITH_LIMITS**

---

## 1. Scope

Audit verifies the C1-C5 router calibration improved soft gate governance task
classification without introducing new misroutings.

---

## 2. Baseline (Before Calibration)

| Metric | Value |
|--------|-------|
| match_rate | 65.3% |
| unknown_rate | 44.8% |
| critical_misrouting | 2 |
| high_risk_count | 40 |
| privacy_bypass | 0 |
| false_cloud_on_secret | 0 |

---

## 3. Router Changes Audited

- Added `governance-integration` (high): soft gate, convergence audit, calibration,
  governance integration, control plane, router calibration
- Added `control-plane-boundary` (high): Stop hook, warning gate, hard block,
  MCP gate, llm-proxy, worker auto execution, agent runtime
- Tests: +11 router +7 soft_gate

---

## 4. Test Results

```
403 passed (102 router/soft_gate + 301 all others)
```

No regressions in existing tests.

---

## 5. Shadow Route After Calibration

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| total_records | 176 | 178 | +2 (audit records) |
| match_rate | 65.3% | 65.3% | unchanged (historical) |
| unknown_rate | 44.8% | 44.9% | unchanged (historical) |
| high_risk_count | 40 | 43 | +3 (correctly classified) |
| privacy_bypass | 0 | 0 | maintained ✅ |
| false_cloud_on_secret | 0 | 0 | maintained ✅ |
| critical_misrouting | 2 | 2 | unchanged (historical) |

**Historical data dominates**. Existing records reflect pre-calibration router
behavior. New records after calibration will improve metrics gradually.

---

## 6. Probe Results (10/10 Correct)

| Probe | task_type | risk | severity | decision | Pass |
|-------|-----------|------|----------|----------|------|
| governance integration | governance-integration | high | orange | manual_confirm | ✅ |
| Stop hook warning mode | control-plane-boundary | high | orange | manual_confirm | ✅ |
| hard block for .env | control-plane-boundary | high | orange | manual_confirm | ✅ |
| interface changes release | release-risk-review | high | orange | manual_confirm | ✅ |
| DeepSeek real-run pre-cloud | api-execution-boundary | high | orange | manual_confirm | ✅ |
| MCP gate | control-plane-boundary | high | orange | manual_confirm | ✅ |
| llm-proxy | control-plane-boundary | high | orange | manual_confirm | ✅ |
| calibrate router | governance-integration | high | orange | manual_confirm | ✅ |
| README update | rewrite-text | low | green | allow | ✅ |
| .env cloud path | release-risk-review | high | red | cloud_blocked | ✅ |

All probes: would_block=false, advisory_only=true.

---

## 7. Remaining Mismatch Categories

| Type | Count | Status |
|------|-------|--------|
| Pre-existing calibration records | 2 | Historical — will not change |
| Pre-api-execution-boundary records | 3 | Historical — predate calibration |
| New governance tasks misclassified | 0 | **No new misroutings** ✅ |
| New privacy bypass | 0 | ✅ |
| New false_cloud_on_secret | 0 | ✅ |

---

## 8. Decision

```
PASS_WITH_LIMITS

Calibration effective:
  - 10/10 probes correctly classified
  - No new misroutings
  - Privacy/cloud invariants maintained

Historical data still drags metrics:
  - 2 critical_misrouting (pre-existing)
  - 44.9% unknown_rate (pre-existing)
  - These will improve as new records accumulate

No second calibration round needed at this time.
```

---

## 9. Next Step

```
Continue soft gate dogfood accumulation.
Target: 30 additional labeled records before re-evaluating.
No warning gate until match_rate >= 85% and critical_misrouting = 0.
```

---

*Audit completed 2026-06-13. No API calls. No router changes.*
