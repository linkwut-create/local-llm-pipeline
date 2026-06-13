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
