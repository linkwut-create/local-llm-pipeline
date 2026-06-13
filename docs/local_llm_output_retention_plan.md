# .local_llm_out Retention Plan

**Date**: 2026-06-14
**Current size**: 165MB
**Status**: Plan only — no cleanup executed in this phase.

## What's in .local_llm_out/

| Directory/File | Content | Growth pattern |
|---------------|---------|---------------|
| `shadow_routes/*.jsonl` | Dogfood shadow route records | Steady (1 line per task) |
| `auto/` | Auto-invocation outputs | Accumulating |
| `pytest-tmp/` | Test temporary directories | Leftover from test runs |
| `cost_ledger/*.jsonl` | Cost tracking records | Very slow |
| Other JSON/JSONL | Bootstrap, repo_map outputs | Per-task |

## Why Growth Matters

- 165MB is not critical but unbounded
- `shadow_routes/` is our dogfood audit trail — must retain
- `pytest-tmp/` is disposable
- `auto/` can be pruned after review

## Retention Policy Proposal

| Path | Retention | Rotation |
|------|-----------|----------|
| `shadow_routes/` | Keep all (audit trail) | Monthly file rotation already active |
| `cost_ledger/` | Keep all (financial records) | Monthly rotation active |
| `auto/` | Keep 30 days | Delete files older than 30 days |
| `pytest-tmp/` | **Delete immediately** | Not needed after test run |
| `bootstrap_*` | Keep 7 days | Delete older |
| `repo_map_*` | Keep 7 days | Delete older |
| `cache/` | Keep 7 days | Delete older |

## Safe Cleanup Command (proposal only — do not execute)

```bash
# Remove pytest leftovers
rm -rf .local_llm_out/pytest-tmp/

# Remove auto outputs older than 30 days
find .local_llm_out/auto -type f -mtime +30 -delete

# Remove bootstrap/repo_map older than 7 days
find .local_llm_out -name "bootstrap_*" -mtime +7 -delete
find .local_llm_out -name "repo_map_*" -mtime +7 -delete
```

## What Must Never Be Committed

All `.local_llm_out/` — already in `.gitignore`. Verify:

```bash
git check-ignore .local_llm_out/
```

## What Must Never Be Deleted

- `shadow_routes/` (audit trail)
- `cost_ledger/` (financial records)
- Any file less than 7 days old in any directory

## Implementation Triggers

| Trigger | Action |
|---------|--------|
| `.local_llm_out/` exceeds 500MB | Run cleanup |
| `.local_llm_out/` exceeds 1GB | Alert + immediate cleanup |
| After each checkpoint | Delete pytest-tmp |
| Monthly | Review auto/ cache age |
