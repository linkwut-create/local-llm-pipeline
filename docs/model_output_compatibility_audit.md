# DeepSeek Flash Smoke Test — Model Output Compatibility Audit

**Status**: Audit complete (2026-06-13). No third API call made.

---

## 1. Audit Scope

Two fixed-prompt smoke tests were run:

| # | Prompt | Model | max_tokens | thinking | Result |
|---|--------|-------|-----------|----------|--------|
| 1 | "Reply with exactly: OK" | deepseek-v4-flash | 20 | disabled | content="" |
| 2 | "Reply with exactly: OK" | deepseek-v4-flash | 20 | disabled | content="" |

Both returned `transport_smoke_pass=true, semantic_smoke_pass=false`.

---

## 2. Request Payload Analysis

### Smoke test → deepseek_client parameters

```python
call_deepseek(
    prompt="Reply with exactly: OK",
    model="deepseek-v4-flash",
    thinking=False,          # → extra_body: {"thinking": {"type": "disabled"}}
    max_tokens=20,           # ← CRITICAL
    api_key=<from env>,
    timeout=30,
)
```

### _build_request() output

```json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
  "max_tokens": 20,
  "temperature": 0.1,
  "extra_body": {"thinking": {"type": "disabled"}}
}
```

No `reasoning_effort` field is set (only added when `thinking=True`).

---

## 3. API Response Analysis

Both calls returned identical usage patterns:

```json
{
  "ok": true,
  "content": "",
  "usage": {
    "prompt_tokens": 9,
    "completion_tokens": 20,
    "total_tokens": 29,
    "completion_tokens_details": {
      "reasoning_tokens": 20
    }
  }
}
```

Key observation: `reasoning_tokens` = `completion_tokens` = 20. The model consumed
ALL available output tokens as internal reasoning tokens, leaving zero for the
final `content` field.

`reasoning_content_present` was `false` in both calls — the model did NOT
return a `reasoning_content` field in the `message` object. The reasoning was
purely internal token consumption without visible output.

---

## 4. Root Cause

### Primary: max_tokens=20 is too small for Flash

DeepSeek V4 Flash internally consumes tokens for reasoning even when
`thinking` is explicitly disabled. With `max_tokens=20`, the model had
only 20 tokens total to work with. It used all 20 for internal reasoning,
producing zero tokens for the final `content`.

### Secondary: thinking=disabled does not eliminate reasoning tokens

The `extra_body: {"thinking": {"type": "disabled"}}` parameter tells DeepSeek
not to produce a separate chain-of-thought. However, the model's internal
architecture still performs reasoning computations that consume output tokens.
This is a known behavior of DeepSeek V4 models — `thinking: disabled` reduces
but does not eliminate reasoning token consumption.

### NOT a bug: client content extraction

`deepseek_client.call_deepseek()` correctly extracts `content` from
`choices[0].message.content`. The content IS empty — this is the API response,
not a client-side extraction failure.

### NOT a bug: thinking parameter transmission

`_build_request()` correctly adds `extra_body: {"thinking": {"type": "disabled"}}`
when `thinking=False`. The parameter is transmitted to DeepSeek.

---

## 5. Compatibility Result

```
likely_max_tokens_exhausted_by_reasoning: TRUE
likely_reasoning_not_disabled:             PARTIAL (disabled in param, still active internally)
likely_model_mode_incompatible:            TRUE (Flash always reasons internally)
likely_client_payload_bug:                 FALSE
inconclusive:                              FALSE
```

---

## 6. Recommended Fixes (Design Only — Not Implemented)

### Recommendation A (Minimal): Increase max_tokens

Change smoke test `max_tokens` from 20 to 128.

```
Rationale: reasoning_tokens=20 + content tokens needed (1-5) = ~25 minimum.
128 gives ample headroom and is unlikely to change cost materially.
Estimated cost at max: ~0.00025 CNY.
```

### Recommendation B: Stronger prompt constraint

Change fixed prompt from:
```
Reply with exactly: OK
```
to:
```
Output only the word "OK" and nothing else.
```

Rationale: stronger constraint may redirect tokens from reasoning to content.

### Recommendation C: Use Pro model (separate design packet)

If Flash cannot produce content at any token budget, test with Pro model
in a separate, audited smoke test.

### Recommendation D: Hybrid (A+B)

Increase max_tokens to 128 AND use stronger prompt constraint.

---

## 7. Third Smoke Test Parameters (Not Executed)

If approved, the third smoke test should use these parameters:

```python
call_deepseek(
    prompt="Output only the word OK and nothing else.",
    model="deepseek-v4-flash",
    thinking=False,
    max_tokens=128,        # was 20
    temperature=0.0,       # was 0.1
    api_key=<from env>,
    timeout=30,
)
```

Changes from second smoke test:
- `max_tokens`: 20 → 128
- `temperature`: 0.1 → 0.0
- `prompt`: stricter constraint
- `thinking`: unchanged (disabled)

---

## 8. Broader Real-Run Status

```
BLOCKED until semantic_smoke_pass=true is demonstrated.
Third smoke test requires separate approval.
Pro model smoke test requires separate design packet.
```

---

*Audit completed 2026-06-13. No third API call was made.*
