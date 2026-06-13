# Local-Translator-Agent Profile Tests Review

**Date**: 2026-06-14
**Task**: Second real read-only external project dogfood task

## Inspected File

`C:\Users\Zero\local-translator-agent\tests\test_profiles.py` (77 lines)

## Read-Only Scope

| Allowed | Inspected |
|---------|-----------|
| Line count | 77 lines |
| Imports | `pathlib.Path`, `fastapi.testclient.TestClient` |
| App imports | `app.app` (FastAPI), `profiles` (PROFILES_DIR, delete_profile) |
| Test functions | 2 test functions |
| Test client | FastAPI `TestClient(app)` |

## Test Function Inventory

| Function | Category | What it tests |
|----------|----------|---------------|
| `test_read_default_profiles` | Profile read | GET /profiles returns default profiles (general, literal, natural, …) |
| `test_create_and_update_custom_profile` | Profile CRUD | Create and update custom user profiles |

## Import Target: `profiles.py` — Public API

| Symbol | Type |
|--------|------|
| `PROFILES_DIR` | Config path (`DATA_DIR / "profiles"`) |
| `normalize_profile_id(profile_id)` | ID normalization |
| `_legacy_compatible(profile, builtin)` | Legacy format helper |
| `get_profile(profile_id)` | Read single profile |
| `list_profiles()` | List all profiles |
| `save_profile(profile_id, data)` | Create/update profile |
| `delete_profile(profile_id)` | Delete profile |

## Privacy-Sensitive Areas Avoided

- No `.env` read
- No `history.db` read
- No user translation data
- No audio/image/OCR content
- No API keys
- `profiles.py` references `DATA_DIR` for config storage — not user content

## What Was Not Inspected

- Test body implementation details
- Profile JSON data content (actual profile values)
- `DATA_DIR` content (may contain user profiles)
- FastAPI route definitions in `app.py`

## First Findings

1. **Small, focused test file**: 2 tests covering profile listing and CRUD.
2. **Uses FastAPI TestClient**: Tests go through the web API layer — integration-style.
3. **Profile storage is config**: `PROFILES_DIR` stores profile definitions, not translation data.
4. **Safe for further read-only**: Both tests validate HTTP response codes and JSON structure.

## External Repo Modification

**None.** Zero files created, modified, or deleted in `local-translator-agent`.

## Recommended Next Read-Only Task

Review `tests/test_provider_checker.py` or `tests/test_fast.py` — both are fast/smoke tests unlikely to touch audio/user data.
