# Guarded Real-Run Adapter — Design Packet

**Status**: Design packet (2026-06-13). No implementation yet.
**Prerequisite**: Mock skeleton convergence audit PASSED (9/9 cases, `real_run_not_implemented` verified impenetrable).
**Next step after this design**: `guarded real-run adapter implementation skeleton` (default mock, `--real-run` gated behind all checks).

---

## 1. Entry Conditions

A real DeepSeek API call MUST NOT proceed unless ALL of the following are true.
If any condition is false, the adapter MUST abort before API key lookup.

| # | Condition | If false → |
|---|-----------|-------------|
| 1 | `cloud_ok = true` | `cloud_ok_required` |
| 2 | `real_run = true` | `dry_run_only` / `mock_plan_ready` |
| 3 | `privacy_status = safe` | `blocked_by_privacy` (hard block) |
| 4 | `privacy_status != needs_review` | `blocked_by_privacy` (hard block; no bypass in v1) |
| 5 | `budget_allowed = true` | `blocked_by_budget` (hard block) |
| 6 | `price_known = true` | `unknown_price` (hard block) |
| 7 | `model in ALLOWED_MODELS` | `blocked_by_router` |
| 8 | `router_task_type != unknown` | `blocked_by_router` |
| 9 | `risk in (high, critical)` → `model = deepseek-v4-pro` | `needs_pro_review` |
| 10 | user confirmation present | `confirmation_required` |

**Rule**: Conditions 1-9 are checked in gate order [1]-[5]. Condition 10 is a
final human gate before API key lookup. No condition is optional.

**Confirmation**: In v1, the "user confirmation present" condition is satisfied
by the user explicitly passing `--real-run`. Future versions may add a 24-hour
shadow log confirmation window.

---

## 2. Relationship to Mock Skeleton

```
tools/deepseek_execution_adapter.py (current: mock skeleton)
  │
  ├─ Gate [1]: cloud_ok ─────────────────── unchanged
  ├─ Gate [2]: router_explain ───────────── unchanged
  ├─ Gate [3]: privacy_gate ─────────────── unchanged
  ├─ Gate [4]: cost_ledger estimate ─────── unchanged
  ├─ Gate [5]: deepseek_dry_run plan ────── unchanged
  │
  └─ Gate [6]: CURRENT: real_run_not_implemented (always)
                NEXT:    guarded_api_call (only if conditions 1-10 pass)

                guarded_api_call:
                  ├─ API key lookup (os.environ["DEEPSEEK_API_KEY"])
                  ├─ Build request body (minimal, privacy-checked)
                  ├─ cost_ledger record (pre_call_estimate)
                  ├─ deepseek_client.call_deepseek()
                  ├─ cost_ledger record (post_call_actual or post_call_estimated)
                  └─ Return response (redacted if error)
```

**Invariant**: Only `deepseek_execution_adapter.py` may call
`deepseek_client.call_deepseek()`. No other tool — not `deepseek_dry_run.py`,
not `advisory_workflow.py`, not `precommit_advisory.py`, not `router_explain.py`
— may gain API call capability.

---

## 3. Privacy Gate — Real-Run Enforcement

| privacy_status | real-run behavior | overridable? |
|---------------|-------------------|--------------|
| `safe` | continue to budget gate | n/a |
| `needs_review` | **HARD BLOCK** (v1) | no |
| `blocked` | **HARD BLOCK** | no |

**V1 rule**: `needs_review` is a hard block for real-run. The dry-run system
may return `allow_dry_run` with a human-review note for `needs_review`, but the
real-run adapter MUST NOT proceed. This is a hardening from the original design
contract — v1 errs on the side of safety.

**Future relaxation** (NOT in v1): `needs_review` may be allowed only if ALL of
`--privacy-reviewed`, `--real-run`, `--cloud-ok` are set, AND a shadow log
confirmation exists within the last 24 hours, AND the matched rules do not
include critical-severity patterns.

---

## 4. Budget Gate — Real-Run Enforcement

| condition | real-run behavior |
|-----------|-------------------|
| `price_known = false` | **HARD BLOCK** |
| `budget exceeded` | **HARD BLOCK** |
| `budget not set` | **HARD BLOCK** (real-run requires `--budget`) |
| `budget ok` | continue |

**Ledger events for real-run**:

| event_type | when | cost field |
|------------|------|------------|
| `pre_call_estimate` | before API call, after all gates pass | estimated_cost |
| `blocked_call` | gate blocks before API call | null |
| `failed_call` | API call fails (error/HTTP/timeout) | estimated_cost |
| `post_call_estimated` | API call succeeds, no usage data | estimated_cost |
| `post_call_actual` | API call succeeds, usage data available | actual_cost from API |

---

## 5. API Key Handling

| Rule | Enforcement |
|------|-------------|
| Source | `os.environ["DEEPSEEK_API_KEY"]` ONLY |
| Timing | Read ONLY after all 10 conditions pass |
| No CLI arg | Parser rejects `--api-key` |
| No log | Never appears in stdout, stderr, ledger, or JSONL |
| No echo | Error messages redact key if API response contains it |
| No test | Tests use fake key `"sk-test-placeholder"` or monkeypatch |
| Empty check | Abort with redacted message if key not set |

**Key lookup position in gate sequence**: Between condition 10 (confirmation)
and the actual API call. This is the ONLY location where the key is read.

---

## 6. Model Allowlist

| Model | real-run allowed | notes |
|-------|-----------------|-------|
| `deepseek-v4-flash` | yes | default, medium/low risk |
| `deepseek-v4-pro` | yes | high/critical risk tasks |
| any other | **HARD BLOCK** | `blocked_by_router` |

The allowlist is hardcoded in `deepseek_execution_adapter.py`. It is NOT
configurable via env or profiles — changing it requires a code change + audit.

---

## 7. Request Body Boundaries

The adapter MUST NOT send to DeepSeek:

```
- Full repository contents
- Compressed archives (zip, tar, gz)
- .env files or their contents
- Private key files (pem, key, p12)
- Un-redacted logs
- Complete credential dumps
- Auto-collected context (no filesystem crawling)
```

**Allowed content (v1)**:
- Task description (the `--task` string, privacy-checked)
- Explicitly provided text input (gated through privacy_gate)
- Diff summaries (max 10,000 chars, privacy-checked)

**If diff content is to be sent**: it must be passed via a dedicated
`--diff-text` flag, limited to 10,000 characters, and checked by privacy_gate
before inclusion in the request body.

---

## 8. Response Handling

| Content | Rule |
|---------|------|
| Response text | Returned to user (stdout) |
| Response summary | May be written to ledger `extra` field (max 500 chars) |
| Full response body | NOT stored in ledger |
| Error messages | Redacted — no API key, no raw request body |
| Token usage | Written to ledger (prompt_tokens, completion_tokens) |
| Prompt content | NOT stored in ledger |
| Secrets in response | Redacted if detected |

**Redaction rules**:
- Strip `DEEPSEEK_API_KEY` and any `sk-...` patterns from error messages
- Truncate error bodies to 500 chars
- Never include raw request body in error output

---

## 9. Retry Rules

| Trigger | Retry? | Max | Strategy |
|---------|--------|-----|----------|
| 400 Bad Request | No | 0 | Report error, abort |
| 401/403 Auth | No | 0 | Report auth error, abort |
| 429 Rate Limit | Yes | 2 | Exponential: 2s, 4s |
| 5xx Server Error | Yes | 2 | Exponential: 1s, 2s |
| Timeout (>180s) | Yes | 2 | Exponential: 3s, 6s |
| Connection error | Yes | 2 | Exponential: 1s, 2s |
| Privacy gate block | No | 0 | Permanent |
| Budget gate block | No | 0 | Permanent |
| Router unknown/defer | No | 0 | Permanent |

**Retry tracking**: Each retry writes a `failed_call` ledger event. The final
attempt (success or exhaustion) writes the appropriate terminal event.

---

## 10. CLI Design (Not Implemented)

Proposed CLI for the guarded real-run adapter:

```bash
py -3 tools/deepseek_execution_adapter.py \
    --task "review current diff before commit" \
    --model deepseek-v4-flash \
    --input-tokens 10000 \
    --output-tokens 2000 \
    --budget 200 \
    --cloud-ok \
    --real-run \
    [--diff-text "..."] \
    [--record-ledger] \
    [--json]
```

**Behavior matrix**:

| flags | result |
|-------|--------|
| (no `--cloud-ok`) | `cloud_ok_required` — abort |
| `--cloud-ok` only | `mock_plan_ready` — gates checked, no API call |
| `--cloud-ok --real-run`, gate fails | blocked_by_* — abort with reason |
| `--cloud-ok --real-run`, gates pass | guarded_api_call — API key lookup → call → record |

**Default**: `--real-run` is OFF. The adapter defaults to mock skeleton behavior.

---

## 11. Test Plan (For Implementation Phase)

The implementation MUST include at minimum these tests before `--real-run` can
be enabled in production:

| # | Test | Expected |
|---|------|----------|
| 1 | no `--cloud-ok` | `cloud_ok_required`, no API key read |
| 2 | no `--real-run` | `mock_plan_ready`, no API call |
| 3 | privacy=blocked | `blocked_by_privacy`, no API key read |
| 4 | privacy=needs_review | `blocked_by_privacy`, no API key read |
| 5 | budget exceeded | `blocked_by_budget`, no API key read |
| 6 | unknown price | `unknown_price`, no API key read |
| 7 | release + Flash | `needs_pro_review`, no API key read |
| 8 | release + Pro | gates pass, reaches API call seam |
| 9 | all gates pass | API key lookup ONLY after condition 10 |
| 10 | API key never in stdout/stderr/ledger | grep assertions |
| 11 | 401/403 | no retry, `failed_call` event |
| 12 | 429 | max 2 retries, exponential backoff |
| 13 | 5xx | max 2 retries, exponential backoff |
| 14 | failed call | `failed_call` ledger event, no secrets |
| 15 | successful call | `post_call_actual` or `post_call_estimated` ledger event |

**Testing strategy**:
- All tests default to monkeypatch/stub for `call_deepseek()`
- Real API smoke test is manual-only, behind `--real-run`, with explicit confirmation
- CI never runs with `--real-run` or real API key

---

## 12. Implementation Boundaries

**Next phase**: `guarded real-run adapter implementation skeleton`

That phase MUST follow these constraints:

```
1. Default: mock only (--real-run disabled)
2. --real-run behind all 10 conditions
3. API call seam: deepseek_client.call_deepseek()
4. First implementation: stub the API call (monkeypatch in tests)
5. Real API smoke test: manual only, separate script, never in CI
6. --real-run + real API key: NEVER in tests/test_*.py
```

**Graduation criteria** (from implementation skeleton to guarded real-run):

```
- [ ] All 15 tests pass with stub API call
- [ ] Shadow route match_rate >= 85% (currently 82.7%; needs router vocabulary expansion)
- [ ] privacy_bypass = 0, false_cloud_on_secret = 0 for 30 days
- [ ] cost ledger has >= 30 mock_plan events
- [ ] Mock skeleton audit re-passed with no regressions
- [ ] Manual smoke test with real API key succeeds once
- [ ] Design audit sign-off (this document reviewed)
```

---

## Appendix A: Decision Matrix (Guarded Real-Run)

| cloud_ok | real_run | privacy | budget | risk | model | result |
|----------|----------|---------|--------|------|-------|--------|
| false | * | * | * | * | * | cloud_ok_required |
| true | false | * | * | * | * | mock_plan_ready |
| true | true | blocked | * | * | * | blocked_by_privacy |
| true | true | needs_review | * | * | * | blocked_by_privacy |
| true | true | safe | exceeded | * | * | blocked_by_budget |
| true | true | safe | unknown | * | * | unknown_price |
| true | true | safe | ok | high | flash | needs_pro_review |
| true | true | safe | ok | high | pro | **ALLOWED** |
| true | true | safe | ok | medium/low | flash/pro | **ALLOWED** |
| true | true | safe | ok | * | unknown | blocked_by_router |

Co-Authored-By: Claude <noreply@anthropic.com>
