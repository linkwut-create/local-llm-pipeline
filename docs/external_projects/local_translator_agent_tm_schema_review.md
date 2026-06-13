# Local-Translator-Agent TM Schema Test Review

**Date**: 2026-06-14
**Task**: First real read-only external project dogfood task

## Inspected File

`C:\Users\Zero\local-translator-agent\tests\test_tm_schema.py` (207 lines)

## Read-Only Scope

| Allowed | Inspected |
|---------|-----------|
| Line count | 207 lines |
| Imports | os, sqlite3, tempfile, pytest |
| Service imports | `tm_service` (migrate_tm, source_hash), `session_service` (migrate_db) |
| Helper functions | `_init_db_with_history(db_path)` |
| Test function names | 19 test functions |
| Test categories | Migration safety, schema existence, column validation, index validation, hash function |

## Test Function Inventory (19 tests)

### Migration Safety (5)
- `test_migrate_tm_idempotent` — TM migration is idempotent
- `test_migrate_tm_does_not_remove_history_table` — preserves history
- `test_migrate_tm_does_not_remove_history_columns` — preserves history columns
- `test_migrate_tm_does_not_remove_translation_session_table` — preserves sessions
- `test_migrate_tm_does_not_remove_translation_session_columns` — preserves session columns

### Schema Existence (1)
- `test_tm_table_exists` — parametrized, checks table exists

### Column Validation (7)
- `test_translation_project_columns` — project table schema
- `test_translation_document_columns` — document table schema
- `test_translation_segment_columns` — segment table schema
- `test_translation_variant_columns` — variant table schema
- `test_human_revision_columns` — human revision table schema
- `test_terminology_decision_columns` — terminology decision table schema
- `test_translation_memory_entry_columns` — TM entry table schema

### Index Validation (2)
- `test_segment_hash_index_exists` — segment hash index
- `test_tm_hash_index_exists` — TM hash index

### Hash Function (4)
- `test_source_hash_deterministic` — same input = same hash
- `test_source_hash_different_text_different_hash` — different input = different hash
- `test_source_hash_whitespace_sensitive` — whitespace matters
- `test_source_hash_unicode` — unicode support

## Privacy-Sensitive Areas Avoided

- No `.env` read
- No `history.db` read
- No user translation data accessed
- No audio/image/OCR content
- No API keys or credentials
- All tests use temporary SQLite (`tempfile`) — no real database touched

## What Was Not Inspected

- Test body implementation details (not copied)
- `services/tm_service.py` full source (import target, not yet read)
- `services/session_service.py` full source (import target, not yet read)
- Test fixtures/conftest.py

## First Findings

1. **Well-structured test suite**: 19 tests covering migration safety, schema columns, indexes, and hash determinism.
2. **Safe by design**: Uses `tempfile` for SQLite — no risk of reading real user data.
3. **Good coverage pattern**: Migration idempotency + non-destructive verification + schema validation.
4. **Import targets safe**: `tm_service` and `session_service` are service-layer modules, not data access.

## External Repo Modification

**None.** Zero files created, modified, or deleted in `local-translator-agent`.

## Recommended Next Read-Only Task

Review `services/tm_service.py` public API surface (function signatures, class names, docstrings only) — to understand the schema layer that these tests validate.
