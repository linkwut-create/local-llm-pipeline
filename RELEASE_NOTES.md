# v0.12.0 Release Notes

**Release**: v0.12.0 (from v0.11.0 baseline)
**Date**: 2026-05-27
**Status**: local release candidate, 50 commits ahead of origin/master, not pushed, not tagged

## Summary

v0.12.0 is a **productivity + governance + quality verification** release.
It adds advisory draft-text advisors, closes the backend governance chain,
introduces a controller delegation contract, exposes a heuristic workflow
planner as the 12th MCP tool, and delivers the Z-chain quality/value
verification toolkit (quality smoke, cost savings, feedback ledger).

## Highlights

### Productivity Advisors (J-chain)

Three new CLI tasks generate advisory draft text from git diff:

| Task | Usage |
|------|-------|
| `draft-commit-message` | `git diff --cached \| py -3 tools/local_llm_router.py draft-commit-message --stdin` |
| `draft-pr-summary` | `git diff main..HEAD \| py -3 tools/local_llm_router.py draft-pr-summary --stdin` |
| `draft-changelog-entry` | `git diff main..HEAD \| py -3 tools/local_llm_router.py draft-changelog-entry --stdin` |

All advisory-only: risk=low, profile=code_worker, output to `.local_llm_out/` only.

### Backend Governance Chain (J-chain, closed)

- Profiles carry `_backend_class` (ollama/ollama_heavy_manual/ollama_mtp_pending/llamacpp_unconfigured/unavailable/placeholder)
- Call ledger records `backend` and `failure_type` with structured classification
- Router enforces `_backend_class` eligibility (explicit `--profile` override preserved)

### Controller Delegation (U-chain)

- CLAUDE.md and AGENTS.md now carry a formal Controller Delegation Contract
- Delegation decision tree, MUST/SHOULD/SKIP triggers, work order schema, result packet schema
- Budget controls: max 5 summarizes, 300s runtime, 10 model calls per task

### Workflow Orchestration (P-chain)

- `local_workflow_plan` — heuristic workflow planner, 12th MCP tool
- Classifies tasks into 4 workflow types (small-code-change/docs-only-change/high-risk-runtime-change/release-local-checkpoint)
- Outputs 7-phase command sequence with work_order_template aligned to U-1 delegation contract

### Quality/Value Verification (Z-chain, closed)

| Phase | Deliverable | Description |
|-------|------------|-------------|
| Z-2 | `tools/quality_smoke.py` | CLI battery of fixed-input model calls with 6 heuristic checks (empty output, off-target, malformed JSON, abnormal confidence, hallucination, latency) |
| Z-3 | `call_ledger_cli.py savings` | Cloud-equivalent cost savings estimation over 3,124 call ledger records (14.3M tokens, 26.30 CNY cloud equivalent) |
| Z-4 | `tools/feedback_ledger.py` | Manual CLI-only cross-project feedback ledger (record/summary/by-target, 8 suggestion types, 5 dispositions) |

All Z-chain tools are CLI-only, advisory-only, and write only to `.local_llm_out/`. No MCP tool was added for Z-2 through Z-4.

### Call Ledger Growth

| Metric | Value |
|--------|-------|
| Records | 3,124 |
| Total tokens | 14.3M |
| Execution locations | local/lan/remote |
| Cost confidence | high/medium/low/none |

### MCP Tools (12)

`local_check`, `local_summarize_file`, `local_summarize_tree`, `local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`, `local_parallel_review`, `local_draft_code`, `local_contextual_analyze`, `local_repo_map`, `local_classify_test_failure`, `local_workflow_plan`

## Quality

| Gate | Result |
|------|--------|
| `validate_configs.py` | PASS |
| `pytest tests/ -q` | 2119 passed, 0 failures |
| Commit gate review | active, enforced per-commit |
| Auto-invocation (Phase 2.0) | SessionStart local_check, PostToolUse summarize/review |

## Known Caveats

- Prompt adherence varies with `qwen3-coder:30b` behavior
- MTP backend (`qwen3.6_35b_moe_mtp`) requires llama.cpp MTP blocked on upstream Qwen3.6 tensor fix; excluded from default debate chain (J-L3)
- Model `qwen3.6:35b-q8-ud` works through Ollama via `deep_reviewer`
- `nonexistent` model references in ledger are historical test artifacts only
- `.local_llm_out/` directory is not tracked in git; ledger records are local-only

## Current Status

```text
HEAD                 9a52d24
VERSION              0.12.0
tag                  none (v0.12.0 tag deferred)
local commits        50 ahead of origin/master
push                 not done
release zip          not created
```

---

# v0.11.0 Release Notes

**Release**: v0.11.0 (from v0.10.0 baseline)
**Date**: 2026-05-25
**Status**: released / public — GitHub Release published 2026-05-25

## Summary

v0.11.0 introduces **task_bootstrap** as a CLI-first control-layer task
entry: one command generates a structured project context package (repo map,
selected file summaries, risk hints, suggested next calls, what-NOT-to-read).
Validated on two downstream projects (local-translator-agent,
local-durable-agent).  Completes the first full workflow dogfood loop:
task_bootstrap → bounded implementation → tests → review_diff gate → commit.

Also adds model-summary to the call ledger CLI.

Infrastructure delivered in earlier post-v0.10.0 chains (D/E/B1/C/A):
repo map generator + MCP tool, diff preclassifier safety core,
test failure classifier MCP tool + manual CLI helper, call ledger
library + CLI, and summary cache authority cleanup.

## New User-Visible CLI

| Tool | Purpose |
|------|---------|
| `tools/task_bootstrap.py` | project context package (repo_map + summaries + risk hints) |
| `tools/call_ledger_cli.py model-summary` | per-model token/call usage recap |
| `tools/call_ledger_cli.py by-mcp-tool` | per-MCP-tool grouping (existing) |
| `tools/classify_failure_helper.py` | manual test-failure classifier (advisory-only CLI) |

## MCP Tool Additions

| Tool | Type |
|------|------|
| `local_repo_map` | heuristic repo/codebase map (10th tool) |
| `local_classify_test_failure` | advisory test failure classification (11th tool) |

## Validation

| Item | Result |
|------|--------|
| task_bootstrap tests | 82/82 |
| call_ledger tests | 162/162 |
| Full suite (last run_checks) | 1858+ passed |
| Full regression | **pending H-C** |
| Downstream dogfood (translator-agent) | pass (F-M) |
| Downstream dogfood (durable-agent) | pass (F-O) |
| Workflow dogfood (full loop) | pass (G-B) |

## Compatibility

- No breaking changes
- All existing MCP tools, router, worker, path-policy unchanged
- CLI additions are purely additive
- `.mcp.json` packaging hygiene — deferred to H-D (pre-existing)

## Release Gate

| Step | Status |
|------|--------|
| Version bump to 0.11.0 | Done |
| RELEASE_NOTES updated | Done |
| CHANGELOG updated | Done |
| Full regression | 1858+ passed |
| `v0.11.0` tag at `6f146e7` | Done — pushed |
| Source zip generated + verified | Done (H-G) |
| `.mcp.json` audit | Done — clean, env empty |
| Forbidden artifact scan | Done — clean |
| GitHub Release published | Done (GH-E) |
| Zip asset uploaded | Done — 628,754 bytes |
| Post-release remote verification | Done (GH-F) |
| Public repo + anonymous access verified | Done (GH-F) |
| SHA256 | `6F946175FABBA7278986A4456106A81F6C907315DF2BFA931E7D6BE43BBB236B` |
| Docs/status closeout | This commit (GH-G) |

## Commit Chain (39, v0.10.0..HEAD)

```
F-D  4471d1c  feat: add task bootstrap CLI
F-G  d8dee6b  fix: refine task bootstrap selection and summaries
F-J  8b0573e  fix: interleave task bootstrap selection and cache summaries
F-L  487f8af  fix: parse task bootstrap summary paths from stdout
F-N  a6ca16a  docs: close out task bootstrap workflow
F-P  502b4d7  docs: record task bootstrap cross-project validation
G-B  b3e217c  feat: add call ledger model-summary command
G-C  c038528  docs: close out workflow dogfood loop

    (plus 31 commits from D/E/B1/C/A chains pre-dating the F-series)
```

---
*Previous release notes (v0.10.0) follow below.*

---

# v0.10.0 Release Notes

**Release**: v0.10.0 (from v0.9.8 baseline)
**Date**: 2026-05-24
**Status**: version bumped; tagged at `53bbe89`

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
| `v0.10.0` tag | Done (`53bbe89`) |
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

## Post-Release Maintenance (v0.10.0-30-g7b48010, unreleased)

30 commits since the `v0.10.0` tag at `53bbe89`.  VERSION remains `0.10.0`.
No new tag, no zip, no push.

**D chain** — advisory-only MCP test failure classifier:
- Worker prompt + response schema for `classify-test-failure`
- `local_classify_test_failure` MCP tool (11th tool)
- Real MCP dogfood + envelope propagation hotfix (`f354d32`)

**E chain** — manual CLI helper + real CLI dogfood:
- `tools/classify_failure_helper.py` (`9168c19`)
- Real CLI dogfood failed — worker uses markdown-fenced JSON, parser only handled pure JSON
- `_strip_json_code_fence()` parser hotfix (`29cface`)
- Dogfood rerun passed — 4 valid cases all exit 0 (`E_C2_MANUAL_HELPER_DOGFOOD_PASS=yes`)

**Boundary**: helper is advisory-only manual CLI; `run_checks.py` prints tip only, no auto-call.  No hooks, gates, guards, or queue integration.  No VERSION bump, no tag.

**Other chains**: B1 preclassifier/advisory-debate-skip, C1-C3 repo map, A1-A2 summary cache — see CHANGELOG.md and PROJECT_STATUS.md for full details.

**Known caveats**: several recent commit subjects have a cosmetic leading `@` (PowerShell here-string artifact).  Not amended — purely cosmetic, no functional impact.
