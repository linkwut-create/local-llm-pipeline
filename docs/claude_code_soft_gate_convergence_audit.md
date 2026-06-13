# Claude Code Soft Gate — Convergence Audit

**Date**: 2026-06-13
**Audit scope**: `tools/claude_soft_gate.py` + `tests/test_claude_soft_gate.py`
**Decision**: **PASS_WITH_LIMITS**

---

## 1. Scope

Audit verifies the soft gate skeleton meets all soft-gate safety invariants:
no blocks, no API keys, no network, no file reads, stable schema, correct
severity/decision mapping.

---

## 2. Safety Invariants

| Invariant | Result |
|-----------|--------|
| `would_block = false` in ALL cases | ✅ Verified (5 CLI cases + 16 tests) |
| `advisory_only = true` in ALL cases | ✅ Verified |
| No `DEEPSEEK_API_KEY` access | ✅ Static audit: OK |
| No `os.environ` access | ✅ Static audit: OK |
| No `requests`/`httpx` import | ✅ Static audit: OK |
| No `open()` / `read_text()` | ✅ Static audit: OK |
| No `subprocess` | ✅ Static audit: OK |
| No file content reads | ✅ Path-only via privacy_gate |
| No hook integration | ✅ No hook code |
| No DeepSeek API calls | ✅ No import of deepseek_client |

---

## 3. CLI Audit Cases

| Case | decision | severity | would_block | advisory | Pass |
|------|----------|----------|-------------|----------|------|
| "summarize README safely" | allow | green | false | true | ✅ |
| "prepare release gate" | manual_confirm_recommended | orange | false | true | ✅ |
| .env path + cloud | cloud_blocked | red | false | true | ✅ |
| sk- API key text | cloud_blocked | red | false | true | ✅ |
| unknown gibberish | defer | yellow | false | true | ✅ |

All 5 cases: would_block=false, advisory_only=true.

---

## 4. Schema Audit

Required fields verified: decision, severity, stage, task, task_type,
risk_level, privacy_status, privacy_detail, budget_status, recommended_route,
cloud_allowed, files_checked, files_matched, manual_confirm_recommended,
hard_block_recommended, advisory_only, would_block, reason,
next_required_action, generated_at.

All present in all output paths.

---

## 5. Test Coverage

```
385 passed (16 soft_gate + 47 adapter + 39 smoke + 22 dry_run +
44 privacy + 26 cost_ledger + 186 existing + 5 router)
```

Soft gate specific: 16 tests covering all severity levels, every decision,
privacy invariants, JSON schema, safety checks.

---

## 6. Shadow Route Status

| Metric | Value |
|--------|-------|
| total_records | 158 |
| match_rate | 70.5% |
| high_risk_count | 40 |
| privacy_bypass | 0 |
| false_cloud_on_secret | 0 |
| critical_misrouting | 2 (pre-existing calibrations) |

---

## 7. Blockers

```
None.
Soft gate skeleton is safe and stable.
```

---

## 8. Final Decision

```
PASS_WITH_LIMITS

Allowed:
  - CLAUDE.md default soft-gate usage draft
  - Continued dogfood recording
  - Soft gate in advisory role

Not allowed (until shadow route improves):
  - Warning gate
  - Stop hook
  - Hard block
  - Automatic workflow enforcement
```

---

*Audit completed 2026-06-13. No API calls. No hooks.*
