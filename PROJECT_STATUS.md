# Project Status

## Stable version

**v0.9.5** — commit `c26b8c0`, branch `master`

## Purpose

User-scope global MCP toolchain. Register once, use across all git projects.

## Validation (v0.9.5)

| Check | Result |
|---|---|
| `python tools/validate_configs.py` | PASS (0 errors, 2 warnings) |
| `python -m pytest -q` | 252 passed |
| `python tools/run_checks.py` | 13/13 (source_repo_mode, full pytest) |
| real project smoke test (local-translator-agent) | PASS: local_check + local_summarize_file, output to target .local_llm_out/ |

## Key fixes in v0.9.5

- `_read_version()` reads from LOCAL_LLM_SOURCE_REPO (pipeline install), not target project.
- `_get_source_repo_root()` distinguishes pipeline assets from target project boundary.

## Key delivery in v0.9.4

- VERSION / CHANGELOG / MCP server / global launcher version alignment.
- Global launcher delegates core tool handling to MCP server (no duplicate path).
- run_checks source-repo mode runs full pytest.
- Documentation: 7 source-non-mutating tools, draft writes only to .local_llm_out/.
- release-risk-review prompt registry.
- Path boundary: deny outside-project reads by default.
- `docs/local-llm-global-mcp.md`.

## Policy

Frozen unless real bugs appear. No feature development on the toolchain itself.
