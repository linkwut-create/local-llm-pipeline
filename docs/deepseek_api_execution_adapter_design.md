# DeepSeek API Execution Adapter — Design Contract

**Status**: Design audit (2026-06-13). No real API calls implemented.
**Next step after this audit**: `tools/deepseek_execution_adapter.py` (mock skeleton, `--real-run` disabled by default).

---

## 1. Real-Run Gate Sequence

Before any real DeepSeek API call, the execution adapter MUST execute gates in
this exact order. Failure at any step MUST abort the call — no partial bypass.

```
[1] task/context received
      │
[2]  router_explain (RouterEngine.analyze)
      │  └─ task_type, risk_level, privacy_status (router-level)
      │
[3]  privacy_gate (privacy_gate.check)
      │  ├─ blocked        → ABORT (blocked_by_privacy, no retry)
      │  ├─ needs_review   → ABORT unless explicit human review flag set
      │  └─ safe           → continue
      │
[4]  cost_ledger estimate (cost_ledger.estimate)
      │  ├─ unknown_price  → ABORT (unknown_price, no retry)
      │  ├─ budget exceeded → ABORT (blocked_by_budget, no retry)
      │  └─ budget ok      → continue
      │
[5]  deepseek_dry_run plan (deepseek_dry_run.plan)
      │  ├─ decision != allow_dry_run → ABORT (with reason)
      │  └─ allow_dry_run             → continue
      │
[6]  cloud_ok check
      │  ├─ cloud_ok=false → ABORT (cloud escalation not enabled)
      │  └─ cloud_ok=true  → continue
      │
[7]  real_run check
      │  ├─ real_run=false → ABORT (dry-run only — use --real-run to call)
      │  └─ real_run=true  → continue
      │
[8]  API key lookup (os.environ["DEEPSEEK_API_KEY"])
      │  ├─ not set        → ABORT (auth not configured)
      │  └─ set            → continue
      │
[9]  DeepSeek API call (deepseek_client.call_deepseek)
      │
[10] cost_ledger record (cost_ledger.record)
      │
[11] response handling
```

**Hard rules**:
- Gates [2]-[7] must run in-process in the adapter. No gate may delegate to a
  subprocess whose output is not validated.
- Gate [3] (privacy_gate) runs BEFORE any network I/O.
- Gate [8] (API key lookup) runs ONLY after all other gates pass.
- Step [10] (cost record) runs unconditionally after step [9], whether success
  or failure.

---

## 2. Privacy Gate — Real-Run Rules

The real-run adapter MUST be stricter than dry-run. The dry-run plan returns
`allow_dry_run` when privacy is `needs_review`, but the real-run adapter MUST
NOT automatically proceed.

| privacy_status | dry-run behavior             | real-run behavior                      |
|---------------|------------------------------|----------------------------------------|
| `safe`        | allow_dry_run                | continue to budget gate                |
| `needs_review`| allow_dry_run (with note)    | ABORT unless `--privacy-reviewed` flag |
| `blocked`     | blocked_by_privacy           | ABORT (hard block, never retry)        |

**Real-run rules**:
- `privacy_status=blocked` → permanent block. No flag can override.
- `privacy_status=needs_review` → default block. Requires explicit
  `--privacy-reviewed` flag AND a human review confirmation in the shadow log
  timestamped within the last 24 hours.
- `--cloud-ok` alone does NOT bypass `needs_review` in real-run mode.
- Privacy check result MUST be recorded in the adapter output and ledger.

---

## 3. Budget Guard — Real-Run Rules

The adapter MUST enforce budget before any API call. Cost is always estimated
before the call; actual cost (from API usage) is recorded after.

| condition              | dry-run behavior   | real-run behavior            |
|-----------------------|--------------------|------------------------------|
| price known, ok       | allow_dry_run      | continue                     |
| price unknown         | unknown_price      | ABORT (no pricing data)      |
| budget exceeded       | blocked_by_budget  | ABORT (hard block)           |
| no budget set         | allow_dry_run      | ABORT (real-run requires budget) |

**Real-run rules**:
- Real-run MUST require `--budget`. Without it, abort with message:
  "real-run requires --budget <CNY>".
- `unknown_price` in real-run → abort. This is stricter than dry-run.
- Budget check MUST use the current month's ledger state (cumulative).
- After the call, cost_ledger MUST record one of:
  * `pre_call_estimate` — estimated cost before call
  * `post_call_actual` — actual cost from API usage response
  * `post_call_estimated` — estimated cost if API returns no usage
  * `failed_call` — zero-cost record for failed attempts
  * `blocked_call` — zero-cost record for gate-blocked attempts

---

## 4. Dual Switch: cloud_ok + real_run

Two explicit flags are required for any real API call. One alone is insufficient.

| cloud_ok | real_run | behavior                          |
|----------|----------|-----------------------------------|
| false    | false    | abort before gate [2]             |
| false    | true     | abort: cloud escalation disabled  |
| true     | false    | run gates [2]-[5], stop at [7]   |
| true     | true     | full execution through [11]      |

**CLI contract**:
```
py -3 tools/deepseek_execution_adapter.py \
    --task "..." --model deepseek-v4-flash \
    --input-tokens N --output-tokens N \
    --budget 200 \
    --cloud-ok --real-run
```

**Rules**:
- `--real-run` without `--cloud-ok` → abort.
- `--cloud-ok` without `--real-run` → gates run, plan generated, but API not called
  (equivalent to deepseek_dry_run.plan with budget enforcement).
- `--real-run` implies acceptance of all governance gates having been checked.
- The adapter MUST print the dry-run plan before making the API call, even in
  real-run mode, so the human can see the final gate assessment.

---

## 5. API Key Handling

| Rule | Enforcement |
|------|-------------|
| Source | `os.environ["DEEPSEEK_API_KEY"]` ONLY |
| No CLI arg | Parser MUST NOT accept `--api-key` |
| No log | Key MUST NOT appear in ledger, stdout, stderr, or error messages |
| No echo | Error messages MUST redact the key if it appears in API error responses |
| No test | Tests MUST use fake key "sk-test-placeholder" or mock |
| Validation | Check key is non-empty after lookup; abort if empty |

**Key lookup order**:
1. `os.environ.get("DEEPSEEK_API_KEY", "")` — standard location
2. If empty → abort: "DEEPSEEK_API_KEY environment variable not set"
3. No other lookup paths. No `.env` file parsing. No config file reading.

---

## 6. Model Allowlist

Only explicitly listed models may be used for real API calls.

| Model | real-run allowed | notes |
|-------|-----------------|-------|
| `deepseek-v4-flash` | yes | default |
| `deepseek-v4-pro` | yes | high-risk/release tasks |
| any other string | no | abort with: "model '<name>' not in real-run allowlist" |

**Validation**:
- Model check happens at gate [1] (before router_explain).
- Unknown models abort immediately — no network I/O.
- The allowlist is hardcoded in the adapter (not read from profiles).

---

## 7. Failure & Retry Rules

| HTTP status / error type | Retry? | Max retries | Strategy |
|--------------------------|--------|-------------|----------|
| 400 (Bad Request) | No | 0 | Report error, do not retry |
| 401/403 (Auth/Forbidden) | No | 0 | Report auth error, do not retry |
| 429 (Rate Limit) | Yes | 2 | Exponential backoff: 2s, 4s |
| 5xx (Server Error) | Yes | 2 | Exponential backoff: 1s, 2s |
| Timeout (>180s) | Yes | 1 | Single retry after 3s |
| Connection error | Yes | 2 | Exponential backoff: 1s, 2s |
| Privacy gate block | No | 0 | Permanent block |
| Budget gate block | No | 0 | Permanent block |
| Router unknown/defer | No | 0 | Requires human reclassification |
| Unknown price | No | 0 | Requires pricing config |

**Retry tracking**:
- Each retry increments a counter in the adapter state.
- After max retries, abort and record `failed_call` to ledger.
- Retry attempts are recorded in the adapter output (not the ledger).

---

## 8. Ledger & Audit Fields

Every real-run attempt MUST write a record to `cost_ledger`. The record schema
extends the existing `cost_ledger.record()` fields.

### Required fields (for every call attempt)

```
timestamp            — ISO 8601 UTC
request_id           — UUID v4, generated at gate [2]
trace_id             — same as request_id (links dry-run plan to real call)
task                 — task description
model                — requested model name
provider             — "deepseek"
input_tokens_est     — estimated input tokens
output_tokens_est    — estimated output tokens
input_tokens_actual  — API response usage.prompt_tokens (or null)
output_tokens_actual — API response usage.completion_tokens (or null)
estimated_cost       — pre-call estimate (CNY)
actual_cost          — post-call calculation from actual usage (or null)
currency             — "CNY"
privacy_status       — safe | needs_review | blocked
privacy_reviewed     — true if --privacy-reviewed flag was set
budget_limit         — monthly budget cap (CNY)
budget_allowed       — true if budget check passed
cloud_ok             — true if --cloud-ok
real_run             — true if --real-run
decision             — allow_dry_run | blocked_by_* | needs_pro_review | defer | unknown_price
success              — true if API returned ok
http_status          — HTTP status code (or null)
error_type           — privacy | budget | auth | timeout | http_4xx | http_5xx | connection | unknown
elapsed_ms           — wall-clock time from gate [2] to response
redaction_applied    — true if error messages were redacted
```

### Forbidden fields (MUST NOT appear in any record)

```
api_key
prompt_body
full_response_body
full_diff
file_content
secret
password
token (raw token values)
```

---

## 9. Dry-Run / Real-Run Boundary

**Separation principle**: `deepseek_dry_run.py` must never gain real API call
capability. The execution adapter is a separate file.

| Responsibility | deepseek_dry_run.py | deepseek_execution_adapter.py |
|---------------|--------------------|-------------------------------|
| Router analysis | yes (via RouterEngine) | yes (via RouterEngine) |
| Privacy check | yes (via privacy_gate) | yes (via privacy_gate) |
| Cost estimate | yes (via cost_ledger) | yes (via cost_ledger) |
| Plan generation | yes (plan()) | yes (wrap plan()) |
| API key lookup | **NO** | yes (gated) |
| DeepSeek API call | **NO** | yes (gated) |
| Cost ledger record | no | yes (before + after) |
| `--real-run` flag | **NO** (rejected) | yes |
| `would_call_deepseek` | always false | true only in real-run |

**Invariant**: `deepseek_dry_run.py` will never have `--real-run`, never import
`deepseek_client`, never read `DEEPSEEK_API_KEY`. This is enforced by design,
not by runtime check.

---

## 10. Minimum Implementation Plan

The next phase after this design audit should produce:

```
tools/deepseek_execution_adapter.py   — skeleton with gate logic
tests/test_deepseek_execution_adapter.py — mock tests (no real API)
```

**First version (mock skeleton)**:
- All gates [2]-[8] implemented and tested with mock inputs.
- `--real-run` flag accepted but DEFAULT DISABLED.
- When `--real-run` is NOT set: runs gates, prints plan, exits 0.
- When `--real-run` IS set: runs gates, prints plan, then:
  - First version: prints "REAL_RUN would call DeepSeek API here" and exits 0
    (no actual API call).
  - Later version: calls `deepseek_client.call_deepseek()`.
- Always records to cost_ledger.
- 100% mock-testable without network.

**Graduation criteria to enable real API calls**:
- [ ] shadow routing match_rate >= 95% (current: 95.6%)
- [ ] privacy bypass count = 0 for 90 days (current: 0)
- [ ] cost ledger has recorded >= 30 dry-run estimates (current: 0)
- [ ] budget guard has been dogfooded for >= 20 real development sessions
- [ ] `--real-run` has passed mock skeleton audit with all gates verified
- [ ] DEEPSEEK_API_KEY is configured and tested with a minimal "ping" call
  (single-token test, not a real task)

---

## Appendix A: Gate Decision Matrix (Reference)

| privacy | budget | risk | model | cloud_ok | real_run | result |
|---------|--------|------|-------|----------|----------|--------|
| blocked | * | * | * | * | * | blocked_by_privacy |
| needs_review | * | * | * | * | true (no flag) | blocked_by_privacy |
| needs_review | * | * | * | * | true (+flag) | continue |
| safe | exceeded | * | * | * | * | blocked_by_budget |
| safe | unknown | * | * | * | * | blocked (unknown_price) |
| safe | ok | high | flash | true | true | blocked (needs_pro_review) |
| safe | ok | high | pro | true | true | ALLOW |
| safe | ok | low/medium | flash | false | * | abort (cloud not ok) |
| safe | ok | low/medium | flash | true | false | plan only |
| safe | ok | low/medium | flash | true | true | ALLOW |
| safe | ok | low | unknown_model | * | true | blocked (model not allowed) |

## Appendix B: Current Tool Inventory (for reference)

| Tool | Purpose | Real API? |
|------|---------|-----------|
| `router_explain.py` | Task classification + risk | No |
| `privacy_gate.py` | Secret/credential detection | No |
| `cost_ledger.py` | Budget estimation + tracking | No |
| `deepseek_dry_run.py` | Governance plan composer | No |
| `deepseek_client.py` | Real DeepSeek API client | **Yes** |
| `advisory_workflow.py` | Preflight task advisor | No |
| `precommit_advisory.py` | Pre-commit route check | No |
| `shadow_route_log.py` | Router vs human decision log | No |
| `shadow_route_report.py` | Shadow route metrics | No |

---

*Design audit completed 2026-06-13. No DeepSeek API calls were made during this audit.*
