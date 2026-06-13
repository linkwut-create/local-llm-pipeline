# Real API Smoke Test — Design Packet

**Status**: Design packet (2026-06-13). No real API calls implemented.
**Prerequisite**: Guarded real-run stub convergence audit PASSED (10/10 cases, stub seam impenetrable).

---

## 1. Smoke Test Objective

The first real DeepSeek API call MUST verify ONLY the following:

1. `DEEPSEEK_API_KEY` is valid and accepted
2. DeepSeek endpoint is reachable
3. A fixed minimal prompt returns a response
4. Token usage and cost are correctly recorded in the ledger
5. Failure exits safely without leaking secrets
6. Privacy / budget / router gates remain effective

**Explicitly excluded** from the first smoke test:
- Complex agent workflows
- Repository review or diff review
- Code generation or refactoring
- Release gate tasks
- Multi-step reasoning
- Any prompt containing real project context

---

## 2. Fixed Prompt Constraint

The first smoke test MUST use exactly:

```
Reply with exactly: OK
```

This prompt is:
- 5 tokens input (approximately)
- No sensitive content
- No project context
- No user data
- Privacy-gate safe

**Forbidden content** (MUST NOT appear in smoke test prompt):
```
- Real source code or diffs
- Repository content or file paths
- .env contents or credential files
- Logs, user data, or business data
- API keys, tokens, or secrets
- Prompt history from previous sessions
- Any text longer than 100 characters
```

---

## 3. Manual Trigger Conditions

Real API smoke test MUST be manually triggered. All conditions below MUST be
satisfied simultaneously. Any single condition failing MUST abort:

| # | Condition | Flag / Gate |
|---|-----------|-------------|
| 1 | `cloud_ok = true` | `--cloud-ok` |
| 2 | `real_run = true` | `--real-run` |
| 3 | Manual smoke test mode | `--manual-smoke-test` |
| 4 | Budget set (max 1 CNY) | `--budget 1` |
| 5 | Flash model only (v1) | `--model deepseek-v4-flash` |
| 6 | Privacy status = safe | gate [3] |
| 7 | Budget allowed = true | gate [4] |
| 8 | Router not unknown/defer | gate [2] |
| 9 | Input tokens <= 100 | enforced |
| 10 | Output tokens <= 20 | enforced |

**Model restriction (v1)**: First smoke test allows `deepseek-v4-flash` ONLY.
`deepseek-v4-pro` is blocked even if all other gates pass. Pro will require a
separate design packet.

**Budget restriction**: `--budget` must be explicitly set to a value between
0.01 and 1.00 CNY. Absent or out-of-range budget → abort.

---

## 4. API Key Handling

| Rule | Enforcement |
|------|-------------|
| Source | `os.environ["DEEPSEEK_API_KEY"]` ONLY |
| Timing | Read ONLY after conditions 1-10 pass |
| No print | Key MUST NOT appear in stdout, stderr, or any output |
| No log | Key MUST NOT appear in ledger JSONL |
| No error echo | Error messages MUST redact key patterns (`sk-...`) |
| No test fixture | Tests MUST use `"sk-test-placeholder"` |
| Missing key | Return `missing_api_key`, no network call attempted |

**Key lookup result fields** (for `missing_api_key` case):
```json
{
  "execution_decision": "missing_api_key",
  "api_key_lookup_attempted": true,
  "api_key_read": false,
  "would_call_deepseek": false,
  "network_call": false
}
```

---

## 5. Budget & Cost Ledger

**Smoke test budget**: fixed at 1 CNY maximum.

**Token limits**:
- Input tokens: <= 100
- Output tokens: <= 20
- Total estimated cost: <= 0.0003 CNY (at Flash pricing)

**Ledger event types**:

| event_type | when |
|------------|------|
| `pre_call_estimate` | before API call, after all gates pass |
| `smoke_test_attempted` | API call initiated |
| `smoke_test_success` | API returned ok with usage data |
| `smoke_test_failed` | API returned error or no usage |
| `blocked_call` | any gate blocked before API call |

**Ledger record after success**:
```
{
  "model": "deepseek-v4-flash",
  "provider": "deepseek",
  "input_tokens": <estimated>,
  "output_tokens": <estimated>,
  "usage_prompt_tokens": <actual from API>,
  "usage_completion_tokens": <actual from API>,
  "estimated_cost": <pre-call>,
  "actual_cost": <post-call from usage>,
  "success": true,
  "smoke_test": true,
  "ledger_event_type": "smoke_test_success"
}
```

**Forbidden in ledger**:
```
- API key
- Full prompt (beyond the fixed "Reply with exactly: OK")
- Full response body
- Any project context
- Un-redacted error messages
```

---

## 6. Real-Run Adapter Change Boundary

The next implementation phase MUST change `tools/deepseek_execution_adapter.py`
gate [6] from:

```python
# Current: stub seam
_guarded_api_call_stub(...)  # never calls API
```

to:

```python
# Next: smoke test path (behind --manual-smoke-test)
if manual_smoke_test:
    _guarded_api_smoke_test_call(...)  # calls API with fixed prompt
else:
    _guarded_api_call_stub(...)  # unchanged for non-smoke real-run
```

**Constraints**:
- `--manual-smoke-test` without `--real-run --cloud-ok` → abort
- `--manual-smoke-test` without `--budget` → abort
- `--manual-smoke-test` with Pro model → abort (v1)
- `--manual-smoke-test` with non-fixed prompt → abort
- Normal `--real-run` (without `--manual-smoke-test`) continues to use stub seam
- The smoke test code path MUST be confined to a single function
- The function MUST be clearly labeled as `_smoke_test` not generic `_real_call`

---

## 7. Failure & Retry Rules

Smoke test retry is MORE conservative than general retry rules:

| Trigger | Retry? | Max | Strategy |
|---------|--------|-----|----------|
| 400 Bad Request | No | 0 | Abort, record `smoke_test_failed` |
| 401/403 Auth | No | 0 | Abort, record `smoke_test_failed`, block further smoke tests |
| 429 Rate Limit | Yes | 1 | Wait 5s, single retry |
| 5xx Server Error | Yes | 1 | Wait 3s, single retry |
| Timeout (>30s) | Yes | 1 | Wait 5s, single retry |
| Connection error | Yes | 1 | Wait 3s, single retry |
| Privacy/budget/router block | No | 0 | Permanent |
| Missing API key | No | 0 | Permanent until key set |
| Unknown model | No | 0 | Permanent |

**Smoke-specific**: timeout is 30s (not 180s). Smoke test is trivial — if it
takes >30s, something is wrong with the endpoint.

---

## 8. Rollback Conditions

If ANY of the following occur, the smoke test capability MUST be disabled and a
full security review required before re-enabling:

```
- API key appears in any output, log, or ledger
- Ledger record contains project code, diffs, or file contents
- Budget calculation error (estimated_cost != actual_cost within 10x)
- unknown_price allows a real API call to proceed
- privacy needs_review allows a real API call to proceed
- router unknown allows a real API call to proceed
- API response or error contains un-redacted secrets
- Real API call bypasses deepseek_execution_adapter.py
- --manual-smoke-test flag works without --real-run
- Smoke test succeeds with Pro model in v1
```

Any single rollback condition triggers → `tools/deepseek_execution_adapter.py`
gate [6] reverts to `real_run_stubbed` (no smoke test path) until fix is
reviewed and re-audited.

---

## 9. Test Plan (For Implementation Phase)

| # | Test | Expected |
|---|------|----------|
| 1 | no `--manual-smoke-test` → no API call | stub seam |
| 2 | no `--cloud-ok` → no API call | cloud_ok_required |
| 3 | no `--real-run` → no API call | mock_plan_ready |
| 4 | no `--budget` → abort | blocked (budget required) |
| 5 | budget > 1 CNY → abort | blocked (budget too high) |
| 6 | Pro model → abort | blocked (Flash only in v1) |
| 7 | unknown model → abort | blocked_by_router |
| 8 | privacy needs_review → abort | blocked_by_privacy |
| 9 | secret text in prompt → abort | blocked_by_privacy |
| 10 | missing API key → abort | missing_api_key, no network call |
| 11 | API key never in output/log/ledger | grep assertions |
| 12 | fixed prompt only accepted | arbitrary prompt rejected |
| 13 | monkeypatched success → `smoke_test_success` ledger event |
| 14 | monkeypatched failure → `smoke_test_failed` ledger event |
| 15 | 401/403 → no retry | 1 attempt, `smoke_test_failed` |
| 16 | 429 → max 1 retry | 2 attempts max |
| 17 | timeout → max 1 retry | 2 attempts max |
| 18 | smoke test path confined to `_smoke_test` function | code inspection |

**Testing strategy**:
- All automated tests use monkeypatch for API calls
- Real API smoke test is a separate manual command, never in CI
- Smoke test script: `py -3 tools/deepseek_smoke_test.py` (standalone, not in adapter)

---

## 10. Implementation Boundaries

**Next phase**: `manual real API smoke test implementation skeleton`

Constraints:
```
1. Default: NO real API calls (unchanged from current)
2. Real smoke test: --manual-smoke-test flag required
3. Smoke test prompt: fixed ("Reply with exactly: OK"), not configurable
4. Model: deepseek-v4-flash ONLY in v1
5. Budget: forced 1 CNY max
6. API call seam: deepseek_client.call_deepseek() behind monkeypatch in tests
7. Real smoke test command: separate script, manual only, never in CI
8. After first successful smoke test: capability remains behind --manual-smoke-test
```

**Graduation criteria** (from smoke test to broader real-run):
```
- [ ] 18 smoke test tests pass (monkeypatched)
- [ ] Manual smoke test succeeds once with real API key
- [ ] Ledger correctly records smoke_test_success with actual usage
- [ ] API key never appears in any output/log/ledger during or after smoke test
- [ ] Rollback conditions reviewed — none triggered
- [ ] Separate design packet for broader real-run
```

---

## Appendix A: CLI Proposal (Not Implemented)

```bash
# Smoke test (manual only, not in CI):
py -3 tools/deepseek_smoke_test.py \
    --cloud-ok \
    --real-run \
    --manual-smoke-test \
    --budget 1 \
    --json

# Adapter unchanged for normal use:
py -3 tools/deepseek_execution_adapter.py \
    --task "review diff" \
    --model deepseek-v4-flash \
    --input-tokens 10000 --output-tokens 2000 \
    --budget 200 \
    --cloud-ok --real-run --json
# → real_run_stubbed (stub seam, unchanged)
```

---

*Design packet completed 2026-06-13. No real API calls were made.*
