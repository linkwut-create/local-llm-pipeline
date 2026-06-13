# Local-Translator-Agent Provider Checker Tests Review

**Date**: 2026-06-14
**Task**: Fourth real read-only external project dogfood task

## Inspected File

`C:\Users\Zero\local-translator-agent\tests\test_provider_checker.py` (649 lines)

## Read-Only Scope

| Allowed | Inspected |
|---------|-----------|
| Line count | 649 lines |
| Imports | `pytest`, `services/provider_checker` (9 symbols) |
| Test functions | 25 test functions |
| Test style | All OpenAI calls mocked via monkeypatch |

## Test Function Inventory (25 tests)

| Category | Tests | Count |
|----------|-------|-------|
| Status defaults | `test_provider_status_defaults` | 1 |
| Provider checks | OK, unreachable, unauthorized, timeout, unconfigured, cache update | 6 |
| Active provider | `test_check_active_provider` | 1 |
| All providers | returns all, populates cache, timeout, no exception on timeout | 4 |
| Chat probe | OK, unreachable, unconfigured | 3 |
| Cache | get empty, get after check, get none returns active | 3 |
| **API key redaction** | sk_key, bearer_token, api_key_param, authorization_header | **4** |
| Error handling | safe_error truncation, preserves error_type | 2 |
| Concurrency | concurrent read/write safety | 1 |

## Import Target: `services/provider_checker.py`

| Symbol | Type |
|--------|------|
| `ProviderStatus` | Dataclass |
| `_safe_error(exc)` | **Redacts API keys from error messages** |
| `_build_client(base_url, api_key, timeout)` | OpenAI client factory |
| `check_provider(name, timeout)` | Single provider check |
| `check_active_provider(timeout)` | Active provider check |
| `check_all_providers(timeout)` | All providers check |
| `run_chat_probe(name, model, timeout)` | Chat probe |
| `get_cached_status(name)` | Cache read |
| `get_cached_statuses()` | All cached statuses |

## Privacy-Sensitive Areas

| Area | Handling |
|------|----------|
| API keys | `_safe_error` redacts sk- keys, bearer tokens, api_key params, auth headers |
| Provider configs | NOT read — only function signatures inspected |
| .env | NOT read |
| Network calls | All mocked in tests |
| `_build_client` parameters | Takes api_key as param — does not read from .env |

## What Was Not Inspected

- Test body implementation (especially provider names/config values)
- `_build_client` default base_url/api_key values
- Provider configuration instances
- Any API key patterns in test fixtures

## First Findings

1. **Privacy-aware by design**: 4 dedicated tests for API key redaction in error messages.
2. **Comprehensive provider testing**: 25 tests covering all failure modes + cache + concurrency.
3. **All mocked**: No real OpenAI/Ollama/DeepSeek calls in tests.
4. **Safe for structural review**: Function signatures do not expose secrets.

## External Repo Modification

**None.**

## Recommended Next Read-Only Task

`tests/test_fast.py` — fast/smoke tests, likely lightest dependency footprint.
