# Local-Translator-Agent First Read-Only Dogfood Task

**Date**: 2026-06-14

## Selected Task

**Review `tests/test_tm_schema.py` test structure — read-only**

## Why Safe

- Test file name only mentions "schema" — structural validation, no data loading
- Translation memory schema tests typically validate table/field definitions
- No audio processing, no OCR, no API calls expected
- No user data in schema validation tests
- Safe even if file contains inline SQL or model definitions — those are code, not secrets

## Files Allowed to Inspect

- `tests/test_tm_schema.py` — test file structure only (not copying content to shadow log)
- `tests/conftest.py` — if exists, for fixture understanding
- `tests/pytest.ini` or root `pytest.ini` — already read

## Files Forbidden to Inspect

- All files in "Blocked Inspection" list from privacy review
- `history.db` — translation memory data
- `glossary.json` — user terminology
- `data/` — all user content directories

## Expected Actual

`local-first` — low-risk read-only structural analysis.

## Stop Conditions

- File contains actual API keys or credentials → Stop, report
- File imports modules from data/ or user content paths → Stop, report
- Privacy gate blocks the task description → Stop
- Soft gate returns `would_block=true` → Stop

## Commands Allowed

```bash
# Read test file structure (file name, class/function names, line count)
# Never copy file contents to shadow log
# Run tests in the governance repo only
py -3 -m pytest tests/test_claude_soft_gate.py -q
```

## Commands Forbidden

```bash
# Never run external project tests
# Never read .env
# Never access audio/user data
```

## Pre-Task Checklist

- [ ] Soft gate pre-task check
- [ ] Privacy gate on task text
- [ ] Shadow route log with correct actual
- [ ] Confirm external repo boundary intact
- [ ] Report findings back to controller before any next action
