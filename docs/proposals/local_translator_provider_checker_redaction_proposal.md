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

---

## Patch Plan (#93)

### Objective

Add 5 edge-case tests for `_safe_error` redaction in `test_provider_checker.py`
without modifying production code unless tests reveal a gap.

### Files to Touch

| File | Action | Priority |
|------|--------|----------|
| `tests/test_provider_checker.py` | Add 5 test functions | P0 |
| `services/provider_checker.py` | Only if tests reveal a gap | P2 (conditional) |

### Files NOT to Touch

| File | Reason |
|------|--------|
| `.env` | Secrets |
| `tools/local_llm_profiles.json` | Provider config |
| `services/llm_provider.py` | May contain API endpoint URLs |
| `history.db` | User data |
| Any file not explicitly listed above | Scope control |

### Proposed Test Additions

1. `test_safe_error_empty_string` — empty Exception message
2. `test_safe_error_url_encoded_credentials` — URL-encoded `api_key=sk-...`
3. `test_safe_error_multiple_keys` — two API keys in one error
4. `test_safe_error_false_positive` — strings that resemble keys but aren't
5. `test_safe_error_truncation_preserved` — truncation + redaction combined

### Implementation Steps (if approved)

1. Read test_provider_checker.py imports/fixtures to understand test setup
2. Add 5 test functions using existing monkeypatch patterns
3. Run `py -3 -m pytest tests/test_provider_checker.py -q` in external repo
4. If all pass: commit. If failures reveal _safe_error gaps: fix + commit.
5. Verify no other tests regressed.

### Rollback Plan

- All additions are new test functions — delete them to roll back.
- If production code was modified: revert to prior commit.
- No database migration, no config change, no API change.

### Side-Effect Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Test uses real API key pattern | Low | Synthetic keys only |
| Test calls real provider | None | All tests already mocked |
| Test breaks existing tests | Low | Additive only, same fixture patterns |

---

## Risk Report & Manual Approval Checklist (#94)

### Privacy Risk

| Concern | Verdict |
|---------|---------|
| API key exposure in test data | **None** — synthetic patterns only |
| Provider config exposure | **None** — not read |
| `.env` exposure | **None** — not read |
| User data exposure | **None** — no user data involved |

### Provider/API-Key Risk

| Concern | Verdict |
|---------|---------|
| Real provider call | **None** — all monkeypatch |
| API key in error message | Already redacted by `_safe_error` |
| New API surface | **None** — test-only |

### Test Side-Effect Risk

| Concern | Verdict |
|---------|---------|
| Test modifies filesystem | **No** — monkeypatch only |
| Test modifies database | **No** — no DB in this test file |
| Test calls network | **No** — all mocked |

### External Repo Modification Risk

| Concern | Verdict |
|---------|---------|
| Accidental commit to wrong repo | **Mitigated** — user controls git |
| Accidental file creation outside test dir | **Mitigated** — only touches test_provider_checker.py |

### Manual Approval Checklist

- [ ] User confirms: this proposal is understood
- [ ] User confirms: no real API keys will be used in test data
- [ ] User confirms: external repo modification is explicitly authorized
- [ ] User confirms: test run in external repo is explicitly authorized
- [ ] User confirms: if _safe_error gaps are found, production code changes are explicitly authorized
- [ ] User confirms: rollback plan is acceptable

### Stop Conditions

- **STOP if** `_safe_error` implementation contains real API key regex patterns and reading it would expose them
- **STOP if** test_provider_checker.py imports any module that reads `.env` or real credentials
- **STOP if** any test run triggers a real network call
- **STOP if** privacy gate returns `blocked` on any file path in scope
- **STOP if** `would_block == true` in any soft gate output

**No external repo change may occur until user explicitly approves implementation phase.**
