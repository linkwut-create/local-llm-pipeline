# Project Status & Forward Plan -- 2026-06-25

> Based on comprehensive audit of 140 task sessions, 8 checkpoint docs, 10+ audit/design docs.

---

## 1. Plan vs Reality: Gap Analysis

### 1.1 MCP Tools

| Planned | Actual | Gap |
|---------|--------|-----|
| 13 source-non-mutating MCP tools | 13 tools, all implemented | Match |
| local_workflow_plan (heuristic) | Implemented, no LLM calls | Match |
| local_route_explain (mock-only) | Implemented, advisory-only | Match |
| local_debate_review_diff (fast mode) | Implemented, timeout issue | Needs MCP server restart |
| local_parallel_review (release) | Implemented | Match |

### 1.2 Profile / Model Layer

| Planned | Actual | Gap |
|---------|--------|-----|
| 24 profile entries | 10 active + 6 deprecated | Doc fixed this session |
| Ollama backend | Deprecated, LiteLLM primary | Migration complete |
| 37 models via LiteLLM | Verified (zero12:4000) | Match |
| 3 llama.cpp MTP endpoints | All unreachable | Not deployed |
| Ollama daemon | Needs manual systemctl disable | Not done |

### 1.3 Pipeline Mode v2

| Phase | Planned | Actual |
|-------|---------|--------|
| 0-13 Baseline to E2E Dry Run | Done | 13/13 code exists |
| 14 Real Dogfood | >=5 real tasks | 4/5 |
| 15 Cost & Quality | Evaluate | Not started |
| 16 v2-alpha Finalization | Cleanup + release | Not started |
| **Overall readiness** | -- | **~22%** |

Module test coverage:

| Module | Tests | Health |
|--------|-------|--------|
| pipeline_route_policy | 32 | OK |
| pipeline_hooks | 13 | OK |
| pipeline_flash_worker | 17 | OK |
| pipeline_e2e_dry_run | 25 | OK |
| pipeline_artifact_store | 12 | Low |
| pipeline_local_worker | 11 | Low |
| pipeline_tool_actuator | 9 | Low |
| pipeline_adjudicator | 5 | **Critical** |
| pipeline_mocks | 0 | **Critical** |

### 1.4 Hook / Gate System

| Feature | Status |
|---------|--------|
| UserPromptSubmit -> task session | Done |
| PreToolUse route enforcement | Done (2 deadlocks fixed this session) |
| PostToolUse artifact capture | Done |
| Stop route committee trigger | Done (re-evaluation fixed this session) |
| Dangerous command guard | Done |
| Commit gate (MCP review before commit) | Done |
| Doctor (30 checks, 6 auto-fixes) | Done |

### 1.5 Soft Gate / Routing

| Metric | Current | Target |
|--------|---------|--------|
| Soft gate skeleton | PASS_WITH_LIMITS | -- |
| Router calibration C1-C5 | 10/10 correct | -- |
| Shadow route records | 158 | 188+ |
| match_rate | 70.7% | >=85% |
| critical_misrouting | 6 (historical) | 0 |
| privacy_bypass | 0 | 0 |
| false_cloud_on_secret | 0 | 0 |
| Warning gate | **Blocked** | match_rate < 85% |
| Stop hook enforcement | **Blocked** | critical_misrouting > 0 |
| Hard block | **Blocked** | depends on warning gate |

### 1.6 DeepSeek Cloud Layer

| Stage | Status |
|-------|--------|
| deepseek_client (real client) | Done, wired but not called |
| deepseek_dry_run (22 tests) | Done |
| deepseek_execution_adapter (25 tests) | Done, mock skeleton |
| Smoke test #1 (max_tokens=20) | **Failed** -- reasoning tokens consumed all output |
| Smoke test #2 (same) | **Failed** |
| Broader real-run | **Blocked** |
| Pro model smoke test | **Blocked** |

### 1.7 Governance Docs

| Doc | Status |
|-----|--------|
| AGENTS.md | 4 stale items fixed this session |
| CLAUDE.md | Heavy duplication with AGENTS.md, high maintenance cost |
| PROBLEMS.md | Actively maintained |
| LONGTODO.md | Many v0.10/v0.11/v0.12 refs, Phase 2/3 plans stale |
| INTERFACES.md | 20+ IFACE-CHANGE entries, some version refs stale |
| docs/ (67 files) | checkpoint #50-#90 missing |

### 1.8 Test Suite

| Metric | Value | Trend |
|--------|-------|-------|
| Test functions | 2974 | from ~2100 |
| Test files | 97 | |
| Passed | 3083 (est.) | |
| Failed | 54 | from 31 |
| Pass rate | 98.3% | from 98.8% |

---

## 2. This Session's Fixes

| # | Issue | Commit |
|---|-------|--------|
| F1 | AGENTS.md: MCP 12->13, profiles 24->16, tests 2100->3000, v0.11->v0.13 | a94aa52 |
| F2 | should_trigger_committee() no mtime comparison -> session deadlock | c4b9e81 |
| F3 | plan_only permissions too narrow: no MCP/Bash/Skill | c4b9e81 |
| F4 | MCP server Ollama comments updated to LiteLLM | 31dc903 |

### Found But Not Fixed

| # | Issue | Reason |
|---|-------|--------|
| U1 | Write tool read-before-write conflicts with new plan.json | Framework limitation, workaround: Bash echo |
| U2 | 54 pre-existing test failures | Batch fix needed |
| U3 | .local_llm_out/ 165MB no rotation | Needs policy |
| U4 | 120+ stale task sessions | Needs cleanup logic |
| U5 | AGENTS.md / CLAUDE.md heavy duplication | Extract shared policy |

---

## 3. Infrastructure

| Component | Status | Note |
|-----------|--------|------|
| zero12 LiteLLM :4000 | OK | 37 models |
| qwen3.6-deep (8001) | OK resident | Q8_0, 34 tok/s prompt |
| gemma4-31b (8004) | OK resident | priority 2 |
| qwen3-coder-30b (8003) | OK on-demand | MoE/A3B |
| gemma4-26b-A4B (8002) | **Unstable** | Keeps crashing |
| deepseek-r1-32b (8010) | OK on-demand | distill variant |
| nemotron-30b (8009) | OK on-demand | |
| glm4-flash (8011) | OK on-demand | |
| Ollama daemon | **Needs manual disable** | systemctl |
| MCP server | **Needs restart** | DEBATE_TIMEOUT not applied |
| Git remote | **182 commits ahead** | Not pushed |

---

## 4. Forward Plan

### Phase A: Stabilize (P0, ~2h)

| # | Task |
|---|------|
| A1 | Push 182 commits to origin |
| A2 | Disable zero12 Ollama daemon |
| A3 | Restart MCP server (DEBATE_TIMEOUT=1000s) |
| A4 | Clean up 120+ stale task sessions |
| A5 | .local_llm_out/ add 7-day rotation |
| A6 | Fix/disable 8002 unstable service |

### Phase B: Pipeline v2 Completion (~4h)

| # | Task |
|---|------|
| B1 | Phase 14 #5: final real pipeline task |
| B2 | Phase 15: Cost & Quality Evaluation |
| B3 | Phase 16: v2-alpha Finalization |
| B4 | pipeline_adjudicator.py tests 5 -> 15+ |
| B5 | pipeline_mocks.py tests 0 -> 10+ |

### Phase C: Doc Cleanup (~3h)

| # | Task |
|---|------|
| C1 | LONGTODO.md update stale version refs |
| C2 | AGENTS.md + CLAUDE.md extract shared policy |
| C3 | INTERFACES.md audit 20+ IFACE-CHANGE |
| C4 | Fill checkpoint #50-#90 summaries |
| C5 | docs/ stale ref global fix |

### Phase D: Test Fixes (~4h)

| # | Task |
|---|------|
| D1 | 10 files MCP tool count hardcoded 12->13 |
| D2 | 11 LLM-dependent add xfail marker |
| D3 | 6 environment/path boundary fixes |
| D4 | Target: 98.3% -> 99%+ |

### Phase E: DeepSeek Unlock (conditional)

| # | Blocking Condition | Current | Target |
|---|-------------------|---------|--------|
| E1 | semantic_smoke_pass | false | true (max_tokens=128) |
| E2 | match_rate | 70.7% | >=85% |
| E3 | critical_misrouting | 6 | 0 |
| E4 | New dogfood records | -- | 30+ |
| E5 | Pro smoke test | Not run | Need design packet |

---

## 5. Paused Items (intentional)

- SQLite-backed ledger -- JSONL sufficient
- Dashboard / Web UI -- CLI + MCP tool
- Context Budget automation -- controller decision
- Per-user guard allowlist -- strict design intentional
- llama.cpp MTP endpoints -- Ollama simplified tags work
- Broader DeepSeek real-run -- smoke test failed
- Flash limited real pilot -- same
- Pro smoke chain -- same
- llm-proxy -- paused
- Automatic worker execution -- paused

---

*Generated: 2026-06-25 | Based on: 140 task sessions + 8 checkpoint docs + 10 audit/design docs + 54 git commits*
