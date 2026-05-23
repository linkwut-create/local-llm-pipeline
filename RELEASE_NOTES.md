# v0.10.0 Release Notes

**Release**: v0.10.0 (from v0.9.8 baseline)
**Date**: 2026-05-24
**Status**: version bumped; tag not yet created

## Summary

v0.10.0 is a maintenance and observability release spanning 15 commits.
It resolves six reliability gaps identified in P6/P7 audits without
introducing new features, API changes, or breaking schema changes.

## Active Maintenance Items (6)

1. **C2 streaming stdout contract fix** — Unified streaming/non-streaming
   output paths with a 5-strategy compat parser.  `load_worker_output()`
   no longer returns `missing_worker_output` on streaming results.

2. **P6-B2-C call ledger write-failure observability** — Added bounded
   `_record_write_failure()` diagnostic log (self-truncating at 1 MB).
   `mcp_doctor` gained 3 ledger health checks.  `record_call()` still
   never raises.

3. **M3 manual call ledger rotation** — Added `rotate_ledger()` and
   `call_ledger_cli.py rotate` subcommand.  Manual archive only — no
   auto-truncation, no data deletion.

4. **H6 classify_error disambiguation** — Narrowed substring heuristics,
   word-boundary 5xx gating, connection-before-timeout ordering.
   `error_type` value space unchanged (6 values).  No migration required.

5. **M7 cost-estimate credibility** — Added `execution_location`
   (`local`/`lan`/`remote`/`unknown`) and `cost_confidence`
   (`high`/`medium`/`low`/`none`) to every ledger record.  Distinguishes
   localhost Ollama from LAN-proxy Ollama without claiming exact dollar
   costs for LAN.

6. **P6-B3-B/H5 endpoint resolution unification** — Extracted shared
   `_resolve_provider()` and `_resolve_endpoint()` helpers so worker and
   debate use the same priority chain.  Debate gained `LOCAL_LLM_PROVIDER`
   support and `--base-url` CLI flag.

## Deferred Indefinitely

- **P5-C / V4-Flash polish** — `_env` wiring, model warmup, provider
  hint for the experimental profile.  Not a v0.10.0 blocker.  Requires
  separate re-authorization.

## Validation

| Check | Result |
|-------|--------|
| pytest | 1300/1300 passed |
| run_checks | 13/13 passed |
| commit-gate reviews | all passed (ok=true) |
| git diff --check | clean |

## Compatibility

- All `error_type` values unchanged (6 values)
- Call ledger schema: 2 additive fields (`execution_location`, `cost_confidence`)
- Old ledger records fully readable without migration
- Worker, debate, router, MCP server interfaces unchanged
- Profiles JSON schema unchanged
- `_MTP_ENDPOINTS` hardcode unchanged (display-only)
- `estimated_cost_cny` behavior unchanged

## Release Gate

| Step | Status |
|------|--------|
| Version bump to 0.10.0 | Done |
| `v0.10.0` tag | Pending |
| Full debate review (3-round) on HEAD | Pending |
| Release auditor review | Pending |
| Zip archive | Pending |
| GitHub push | Pending |

## Commit Chain (15)

```
C2  b984511 → 336274c (4 commits)
P6-B2-C  6f644c6 → 90f06b5 (2 commits)
M3  c975222 → 8e640a0 (2 commits)
H6  4f4b648 → b41ec97 → 3e9481e (3 commits)
M7  89bf88e (1 commit)
P6-B3-B/H5  55a34b8 (1 commit)
Closeout 3a704ff (1 commit)
Release bump (this commit)
```
