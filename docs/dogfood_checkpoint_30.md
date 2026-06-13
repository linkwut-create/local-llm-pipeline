# Dogfood Checkpoint 30 — Integrity Audit

**Date**: 2026-06-13
**Decision**: **PASS_WITH_LIMITS**

## 1. Scope

Audit covers dogfood records #21—#30, commit grouping, test results, and safety
invariants.

## 2. Commit Map

```
#21 e126c87 test: cover route explain MCP CLI
#22-28 61c9db0 test: cover privacy gate, dogfood status, shadow route, router profiles
#29 —        (dogfood logged, no code change needed)
#30 —        (terminal checkpoint, no commit)
```

## 3. Dogfood Record Map

All records #21—#30 have shadow_route_log entries with actual="local-first"
(for #21-#29) or actual="pro-review" (for #30 checkpoint).

| # | Task | Router | Actual |
|---|------|--------|--------|
| 21 | route explain MCP CLI tests | unknown/low | local-first |
| 22 | router profiles tests | unknown/low | local-first |
| 23 | README troubleshooting | rewrite-text/low | local-first |
| 24 | privacy gate doc mention tests | unknown/low | local-first |
| 25 | cost ledger estimate JSON tests | unknown/low | local-first |
| 26 | cost ledger estimate examples | rewrite-text/low | local-first |
| 27 | dogfood status text output tests | unknown/low | local-first |
| 28 | shadow route since filter tests | unknown/low | local-first |
| 29 | dogfood notes before cp 30 | unknown/low | local-first |
| 30 | checkpoint review | unknown/low | pro-review |

## 4. Process Deviation

**#22—#28 merged into single commit 61c9db0**.

Reason: commit-gate overhead for 8 consecutive test-only additions led to
batch commit. Dogfood records were logged individually before the batch commit.

Impact on data trust: LOW. Each task has an independent shadow_route_log entry
with unique timestamp and router classification. The commit grouping does not
affect dogfood data integrity — it only weakens the 1:1 audit trail between
commit hash and dogfood record number.

Mitigation: #31 onward will restore 1-task-1-commit discipline.

## 5. Test Results

Core governance suite: 101 passed, 1 fixed (test_recommendation_stays_accurate_with_critical).

3 failures found and fixed in this audit:
- `test_recommendation_stays_accurate_with_critical` (#11 test): assertion too strict for <30 record case. Fixed.
- `test_doc_mention_api_key_safe` (#24 test): used text that correctly triggers privacy gate. Fixed to use genuinely safe text.
- `test_cli_missing_file_fails` (#14 test): assumed --profiles flag exists. validate_configs ignores unknown flags. Fixed.

All 3 were introduced in this dogfood batch, not pre-existing. All 3 are now fixed.

## 6. Safety Invariants

```
privacy_bypass: 0
false_cloud_on_secret: 0
new critical_misrouting: 0 (all 5 are pre-existing calibration records)
would_block: always false
advisory_only: always true
```

## 7. Router / Soft Gate Status

No changes. Router calibration C1-C5 remains the only calibration round.
Soft gate remains advisory-only with would_block=false.

## 8. Decision

```
PASS_WITH_LIMITS

Allowed: continue dogfood #31-#40
Required: restore 1-task-1-commit discipline
Blocked: warning gate, Stop hook, hard block
```

## 9. Next Step

Continue natural dogfood accumulation #31-#40. Each task must have independent
dogfood record and independent commit.
