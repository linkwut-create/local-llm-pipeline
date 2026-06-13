# Test Failure Triage Plan

**Date**: 2026-06-14
**Status**: Plan only — no fixes applied in this phase.

## Failure Categories & Triage

### 1. MCP Tool Count Mismatch (10 tests)

**Symptom**: `assert 13 == 12` — server has 13 tools, tests expect 12.
**Root cause**: `local_workflow_plan` was added as 13th MCP tool but test assertions weren't updated.

**Triage**: Stale expectation. Fix by updating test assertions to match current tool count or using `>= 12` instead of `== 12`.

**Blocks implementation?** No — tests are counting tools, not testing tool behavior.

**Recommended**: Update all 10 assertions to `>= 12` or dynamic count. Do not hardcode to 13 (brittle to future tool changes).

### 2. LLM-Dependent Live Tests (11 tests)

**Symptom**: Failures in `test_local_llm_v093`, `test_worker_ledger_env`, `test_mcp_ledger_env`.
**Root cause**: Require specific Ollama model state, network, or timing.

**Triage**: Environment-dependent. Pass when Ollama models are warm, fail when cold.

**Blocks implementation?** No — these test live model interaction, not governance logic.

**Recommended**: Add `@pytest.mark.live_ollama` marker. Run with `--run-live-ollama` flag. Skip in CI.

### 3. Pre-Existing Isolation Failures (2 tests)

**`test_summary_empty_no_crash`**: Calls `summary()` on real ledger dir without monkeypatch. Real ledger has 29+ records. Fix: monkeypatch LEDGER_DIR.

**`test_cli_json_parseable`**: `route_explain_mcp.py --json` produces empty stdout. CLI may expect stdin or args. Fix: investigate CLI contract, then fix test or CLI.

**Blocks implementation?** No — both are test isolation issues, not logic bugs.

### 4. Cross-Project Dry-Run (2 tests)

**Symptom**: `test_cross_project_dry_run.py` failures.
**Root cause**: Require external project at specific path that doesn't exist.

**Triage**: Skip when external project not present.

**Blocks implementation?** No — these test cross-project scenarios that are not yet active.

### 5. Environment/Path (6 tests)

**Symptom**: Non-git directory, path boundary assumptions.
**Root cause**: Platform or environment assumptions in tests.

**Triage**: Document assumptions. Skip or xfail in incompatible environments.

**Blocks implementation?** No.

## Implementation Phase Blocking Criteria

Only these failures would block implementation:

| Condition | Block? |
|-----------|--------|
| Privacy gate test failure | **Yes — blocks** |
| Shadow route safety invariant failure | **Yes — blocks** |
| Soft gate `would_block=true` forced | **Yes — blocks** |
| MCP server crash/startup failure | **Yes — blocks** |
| Config validation error | **Yes — blocks** |
| Tool count mismatch | No |
| LLM live test | No |
| Pre-existing isolation | No |
| Cross-project dry-run | No |
| Environment/path | No |

## Execution Order (when approved)

1. Fix MCP tool count assertions (lowest risk, mechanical)
2. Mark live Ollama tests with proper markers
3. Fix pre-existing isolation failures
4. Document or skip cross-project tests
5. Document environment/path assumptions
