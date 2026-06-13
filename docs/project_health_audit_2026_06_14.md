# Project Health Audit — 2026-06-14

Full project scan performed during #90 checkpoint transition.

## Test Suite

```txt
2646 passed, 31 failed (98.8% pass rate)
```

### Failure Categories

| Category | Count | Root Cause |
|----------|-------|-----------|
| MCP tool count mismatch | 10 | Server has 13 tools, 10 test files assert 12 |
| LLM-dependent (live Ollama) | 11 | Require specific model state or network |
| Pre-existing isolation | 2 | `test_summary_empty_no_crash` (real ledger), `test_cli_json_parseable` (empty stdout) |
| Cross-project dry-run | 2 | Require external project at specific path |
| Environment/path | 6 | Non-git directory, path boundary assumptions |

### Severity Assessment

| Category | Blocks implementation? | Action |
|----------|----------------------|--------|
| MCP tool count | No — cosmetic mismatch | Update assertions to dynamic count or current value |
| LLM-dependent | No — environment-specific | Mark as xfail or skip in CI |
| Pre-existing isolation | No — known for many checkpoints | Fix or document |
| Cross-project | No — requires specific setup | Skip without external project |
| Environment/path | No — platform-specific | Document assumptions |

## Infrastructure

| Item | Status | Action |
|------|--------|--------|
| Ollama (44 models) | OK | — |
| llama.cpp MTP (3 endpoints) | Not reachable | Expected — services not running |
| OpenAI-compatible server | Not reachable | Expected — not deployed |
| Config validation | OK (0 errors, 8 shared-model warnings) | — |
| `.local_llm_out/` | **165MB, no rotation** | Needs retention policy |
| Git state | Clean, master, 182 commits ahead of origin | Push when ready |

## Documentation

| Item | Status | Action |
|------|--------|--------|
| docs/ file count | 55 + 9 external project docs | Review for staleness |
| Checkpoint docs | Only #30, #40, #45 exist | #50-#90 are terminal-only |
| Stale version refs | v0.10/v0.11/v0.12 in docs/ and LONGTODO.md | Update or remove |
| PROBLEMS.md | 253 lines | Healthy — actively maintained |
| AGENTS.md | Present | — |
| INTERFACES.md | Present | — |

## Tools

| Item | Status |
|------|--------|
| tools/*.py | 49 files |
| Untracked files | 0 |
| MCP server tools | 13 (local_workflow_plan added) |

## Dogfood / Shadow Route

| Metric | Value |
|--------|-------|
| Records | 345+ |
| Match rate | 74.2% |
| Unknown rate | 43.5% |
| Critical misrouting | 6 (all historical) |
| Privacy bypass | 0 |
| False cloud-on-secret | 0 |
| Warning gate candidate | false |

## Known but Not Blocking

- MCP server tool count mismatch between tests and implementation
- `.local_llm_out/` unbounded growth
- Checkpoint doc gaps for terminal-only checkpoints
- Stale version references in docs
- Pre-existing test isolation failures

## External Project Status

**local-translator-agent dogfood: FROZEN.**
4/4 external read-only tasks completed. 1 controlled proposal completed.
No external repo modification. Next phase: return to governance repo health.
