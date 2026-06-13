# Provider Checker Privacy/Error-Redaction Improvement Proposal

**Phase**: Controlled Proposal Mode — Round 1
**Target project**: local-translator-agent
**Date**: 2026-06-14

## Selected Issue

Improve test coverage for `_safe_error` redaction in `services/provider_checker.py`.
This function redacts API keys, bearer tokens, and authorization headers from error
messages before they can leak into logs or user-facing output.

## Why This Is a Real Issue

During read-only review (#86—#87), we identified that `_safe_error` is tested with
4 specific redaction patterns (sk- keys, bearer tokens, api_key params, auth headers)
but the test file is 649 lines with 25 tests — only 4 cover redaction. The function's
implementation (not read) likely handles additional edge cases that are untested:

- Empty strings / null values in error messages
- URL-encoded credentials
- Multiple keys in a single error message
- Non-key patterns that look like keys (false positives)

## Why This Is Safe for Proposal Mode

- **Already reviewed**: File structure, imports, and function signatures known from #86.
- **No new file reads needed**: All analysis based on already-reviewed public API surface.
- **No secrets to read**: `_safe_error` takes Exception objects, not credentials.
- **No external test execution**: We propose tests, not run them.
- **No external repo modification**: Proposal only.

## Blocked Actions (must NOT perform)

- Do NOT modify `local-translator-agent` external repo
- Do NOT run `test_provider_checker.py`
- Do NOT call any provider (Ollama, OpenAI, DeepSeek)
- Do NOT read `.env` or provider config instances
- Do NOT read `_safe_error` implementation body if it contains API key patterns

## External Repo Status

**Read-only.** Zero files created, modified, or deleted.

## Expected Approval Path

1. Controller reviews this proposal
2. If approved, proceed to #92 (read-only analysis)
3. Then #93 (patch plan), #94 (risk report + approval checklist)
4. User explicitly approves before any implementation phase

---

## Read-Only Analysis (#92)

### Current Behavior Summary

`_safe_error(exc: Exception) -> str` in `services/provider_checker.py`:
- Takes an Exception from provider calls (OpenAI, Ollama, etc.)
- Redacts API key patterns before returning error text
- Called by `check_provider`, `check_all_providers`, `run_chat_probe`

Existing tests cover 4 redaction patterns:
- `sk-` API keys
- Bearer tokens
- `api_key=` query parameters
- Authorization headers

### Likely Files to Touch

| File | Action | Risk |
|------|--------|------|
| `tests/test_provider_checker.py` | Add redaction edge-case tests | Low — test-only |
| `services/provider_checker.py` | Possibly update `_safe_error` if tests reveal gaps | Medium — production code |

### Likely Tests to Add

| Test | What it covers |
|------|---------------|
| `test_safe_error_empty_string` | Empty/null error messages |
| `test_safe_error_url_encoded_credentials` | `api_key=sk-abc123` in URL-encoded form |
| `test_safe_error_multiple_keys` | Multiple keys in one error message |
| `test_safe_error_non_key_patterns` | Strings that look like keys but aren't (false positives) |
| `test_safe_error_truncation_still_works` | Truncation preserved alongside redaction |

### Privacy-Sensitive Boundaries

- Do NOT read `_safe_error` implementation body if it contains API key regex patterns
- Do NOT read provider config to get sample keys
- Test data must use synthetic/fake key patterns only
- No real provider calls needed — all tests use monkeypatch

### Known Unknowns

- Whether `_safe_error` handles unicode/non-ASCII error messages
- Whether redaction works on multi-line error messages
- Whether the function is called in all error paths or only some
- What exact regex patterns are used (intentionally not read)

### What Must Be Manually Approved Before Modification

- Controller must confirm: no real API key exposure in test data
- Controller must confirm: all proposed tests are additive, not destructive
- Controller must confirm: external repo modification boundary
