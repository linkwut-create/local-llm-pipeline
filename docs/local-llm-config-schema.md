# Config Schema Validation

## Purpose

`validate_configs.py` ensures `local_llm_profiles.json` and `local_llm_tasks.json`
can't silently fail due to misconfiguration.

## Usage

```bash
python tools/validate_configs.py           # human-readable output
python tools/validate_configs.py --json    # machine-readable JSON
python tools/validate_configs.py --quiet   # exit code only (for CI)
```

Exit codes: `0` = valid, `1` = errors found, `2` = file not found.

## Profile Rules

Each profile in `profiles.json` must have:
- `model`: non-empty string
- `risk_level`: one of `low`, `medium`, `medium-high`, `high`
- `use_for`: list of task names

Additional checks:
- Duplicate models across profiles produce a warning (allowed but verify intent)
- Embedding profiles must not be used for code generation/review/draft tasks
- `temperature` must be a number if present

## Task Rules

Each task in `tasks.json` must have:
- `default_profile`: must exist in profiles.json
- `may_modify_code`: must be `false` (local models never modify source)
- `controller_must_verify`: must be `true`
- `risk`: one of `low`, `medium`, `medium-high`, `high`
- `max_output_chars`: integer
- `allowed_use` and `forbidden_use`: strings

Additional checks for draft tasks (`draft-fix`, `draft-feature`, `draft-refactor`, `suggest-improvements`):
- `may_modify_code` must be `false`
- `controller_must_verify` must be `true`

Additional checks for high-risk tasks (`release-risk-review`, `architecture-review`, `deep-code-review`, `risk: high`):
- `controller_must_verify` must be `true`

## Integration with run_checks

`run_checks.py` automatically validates configs on every run:

```
[Config Schema]
  [PASS] profiles.json + tasks.json: valid
```

A config error will fail run_checks and prevent release.

## Common Errors

| Error | Fix |
|---|---|
| `default_profile 'X' does not exist` | Add profile X to profiles.json or fix task reference |
| `may_modify_code must be false` | Set `may_modify_code: false` — local models never modify source |
| `controller_must_verify must be true` | Set `controller_must_verify: true` — required for draft/high-risk tasks |
| `invalid risk_level 'X'` | Use `low`, `medium`, `medium-high`, or `high` |
| `model is empty` | Provide a valid Ollama model name |
