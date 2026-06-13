# Local-Translator-Agent Preset Checker Tests Review

**Date**: 2026-06-14
**Task**: Third real read-only external project dogfood task

## Inspected File

`C:\Users\Zero\local-translator-agent\tests\test_preset_checker.py` (287 lines)

## Read-Only Scope

| Allowed | Inspected |
|---------|-----------|
| Line count | 287 lines |
| Imports | `pytest`, `monkeypatch` |
| Service imports | `services/preset_checker` (check_local_first_preset, PresetStatus), `services/provider_checker` (get_cached_statuses) |
| Test functions | 11 test functions |
| Test style | All mocked via monkeypatch — no real model calls |

## Test Function Inventory (11 tests)

| # | Function | Category |
|---|----------|----------|
| 1 | `test_unknown_when_no_cache` | Cache empty → unknown |
| 2 | `test_ready_when_ollama_ok_fallback_disabled` | Ollama OK → ready |
| 3 | `test_active_when_ollama_ok_and_fallback_matches` | Fallback matches → active |
| 4 | `test_ready_not_active_when_fallback_provider_unreachable` | Fallback unreachable |
| 5 | `test_ready_when_fallback_is_cloud_provider` | DeepSeek fallback → ready |
| 6 | `test_lmstudio_ok_ollama_not_cached` | LM Studio → ready |
| 7 | `test_not_ready_when_local_providers_unreachable` | All local unreachable |
| 8 | `test_recommendation_does_not_imply_auto_enable` | Recommendation isolation |
| 9 | `test_concurrent_preset_check` | Concurrent access safety |
| 10 | `test_system_health_has_local_first_field` | /system/health endpoint |
| 11 | `test_system_health_local_first_no_network` | local_first no network |

## Import Target: `services/preset_checker.py`

| Symbol | Type |
|--------|------|
| `PresetStatus` | Dataclass (status/active/ready fields) |
| `_first_model(ps)` | Internal helper |
| `check_local_first_preset()` | Main public function |

## Privacy-Sensitive Areas Avoided

- No `.env` read
- No `history.db` read
- No user translation data
- No audio/image/OCR content
- No API keys
- All tests fully mocked — no real model calls or network

## What Was Not Inspected

- Test body implementation details
- `PresetStatus` field values
- `provider_checker` module internals

## First Findings

1. **Well-structured preset/readiness checker**: 11 tests covering cache states, fallback logic, multi-provider readiness, concurrent access, and system health.
2. **Fully mocked**: All tests use `monkeypatch` — no real Ollama/LM Studio/DeepSeek calls.
3. **Safe for read-only**: Tests validate logic, not live model behavior.

## External Repo Modification

**None.**

## Recommended Next Read-Only Task

`tests/test_fast.py` or `tests/test_provider_checker.py` — both fast/smoke/config tests.
