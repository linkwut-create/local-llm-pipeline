# Z-Chain Baseline — local-llm-pipeline Quality/Value Verification

**Purpose**: Canonical baseline for the Z-chain quality/value verification line.
All Z-2 through Z-4 slices reference this document as their single source of truth.

**Status**: Z-1 committed. Z-2 committed (`ac3d5c3`). Z-3 committed (`3a84077`, `37759c9`). Z-4 committed (`8a6ff00`). **Z-chain closed.**

---

## 1. local-llm-pipeline Current Baseline

Captured at Z-4 (2026-05-27):

| Item | Value |
|------|-------|
| HEAD | `d3ce4d6` |
| VERSION | `0.12.0` |
| Working tree | clean |
| Tests | 2119 passed (`py -3 -m pytest tests/ -q`) |
| MCP tools | 12 (`local_check`, `local_summarize_file`, `local_summarize_tree`, `local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`, `local_parallel_review`, `local_draft_code`, `local_contextual_analyze`, `local_repo_map`, `local_classify_test_failure`, `local_workflow_plan`) |
| Call ledger records | 2,980 |
| Success rate | 91.0% (2,713 success / 267 failure) |
| Total tokens | ~13.5M (2.27M input / 11.25M output) |
| Total cost | 0 CNY (all local/LAN, no cloud spend) |
| Push | no |
| Tag | none |
| Release | none |

### Verification commands

```bash
# Test suite
py -3 -m pytest tests/ -q

# Config validation
py -3 tools/validate_configs.py

# Health check
py -3 tools/run_checks.py

# Call ledger summary
py -3 tools/call_ledger_cli.py summary

# MCP server verify (after restart)
# /mcp → local-llm connected 12 tools
```

---

## 2. Known Target Projects

Projects that the pipeline has dogfooded against or is designed to support:

| Project | Path | Role |
|---------|------|------|
| local-llm-pipeline | `C:\Users\Zero\local-llm-pipeline` | Pipeline self-host (primary) |
| local-translator-agent | `C:\Users\Zero\local-translator-agent` | Downstream consumer (dogfood verified) |
| local-durable-agent | `C:\Users\Zero\Documents\New project 3\local-durable-agent` | Downstream consumer (bootstrap validated) |

---

## 3. Dogfood Baselines

### 3.1 local-translator-agent

| Item | Value |
|------|-------|
| HEAD | `a3b11a1` |
| S-C chain | closed |
| Targeted tests | 213 passed |
| Push | no |
| Last dogfood | X-0.5 (cross-project delegation, 2026-05-27) |

### 3.2 local-durable-agent

| Item | Value |
|------|-------|
| Last validation | F-O (task_bootstrap cross-project, 2026-05-26) |
| Bootstrap result | exit 0, 3/3 summaries OK |

---

## 4. Z-Chain Roadmap

```
Z-0: quality/value verification planning audit       ← DONE (audit, no commit)
Z-1: project brief/current baseline doc               ← DONE (`6941d78`)
Z-2: local model output quality smoke                 ← DONE (`ac3d5c3`)
Z-3: cost/token savings report                        ← DONE (`3a84077`, `37759c9`)
Z-4: cross-project feedback ledger                    ← DONE (`8a6ff00`)
```

| Phase | Type | Description | Status |
|-------|------|-------------|--------|
| Z-0 | Audit (no code) | Design quality smoke, cost savings, feedback loop. Pick first slice. | Done |
| Z-1 | Docs-only | This baseline document. | Done (`6941d78`) |
| Z-2 | Code | `tools/quality_smoke.py` — CLI battery of fixed-input model calls with heuristic quality checks. | Done (`ac3d5c3`) |
| Z-3 | Code | `tools/call_ledger_cli.py savings` — read-only aggregation over call ledger with cloud-equivalent cost table. | Done (`3a84077`) |
| Z-4 | Code | `tools/feedback_ledger.py` — append-only manual cross-project feedback tracking. | Done (`8a6ff00`) |

### Hard constraints (all Z-chain phases)

- MCP tool count stays at 12 — no 13th tool
- VERSION stays at `0.12.0` throughout Z-chain
- No push, no tag, no release
- No local-translator-agent modifications
- No runtime behavior changes outside the new tools
- All new tools write only to `.local_llm_out/`

---

## 5. Quality Threshold Definitions

Used by Z-2 quality smoke. All checks are advisory — none block commit.

| Check | Definition | Threshold |
|-------|-----------|-----------|
| **Empty output** | Response is empty, whitespace-only, or contains only JSON wrapper with no content | FAIL if content < 10 non-whitespace chars |
| **Off-target output** | Output references wrong file/module names or unrelated domain concepts | WARN if target filename not found in output; FAIL if all domain keywords absent |
| **Malformed JSON** | Output claims to be JSON but does not parse | FAIL if `json.loads()` raises on claimed-JSON output |
| **Abnormal confidence** | Worker-reported `confidence` is not in `{high, medium, low}` | FAIL if confidence missing or unrecognized value |
| **Obvious hallucination** | Output references non-existent file paths or function names | WARN if path/symbol not found in repo map; FAIL if >3 fabricated references |
| **Timeout / latency** | Call exceeds profile-specific time budget | FAIL if duration > profile timeout × 1.5 |

### Advisory vs blocking

- All quality checks are **advisory** — they flag degradation, never block workflows
- Z-2 exit code 0 = all within thresholds; exit code 1 = quality degradation flagged
- No gate/hook/commit integration

---

## 6. Cost-Savings Assumptions

Used by Z-3 cost savings report.

| Assumption | Detail |
|-----------|--------|
| **Data source** | Existing `.local_llm_out/audit/calls.jsonl` — no new data collection |
| **Read-only** | `call_ledger_cli.py savings` never mutates the ledger |
| **Cloud rates** | Static mapping in `tools/cloud_cost_reference.json` — manual updates only |
| **Savings formula** | `saved = sum(cloud_equivalent_rate × tokens) - actual_cost` per dimension |
| **Cost confidence** | Each bucket tagged with confidence level derived from `execution_location` and `tokens_estimated` |
| **No mutation** | `estimated_cost_cny` field unchanged; existing ledger schema untouched |

### Cloud-equivalent rate mapping (preliminary)

| Local profile size | Comparable cloud tier | Est. rate (CNY/1K tokens) |
|--------------------|-----------------------|---------------------------|
| ~4B (gemma4, fast_summary) | DeepSeek-V3 lite / GPT-3.5 | 0.001 in / 0.002 out |
| ~12B (smart_summary) | DeepSeek-V3 mid | 0.002 in / 0.004 out |
| ~27-30B (qwen3-coder, commit_reviewer) | DeepSeek-V3 / GPT-4o-mini | 0.004 in / 0.008 out |
| ~35B+ (deep_reviewer, reasoning) | DeepSeek-R1 / GPT-4o | 0.010 in / 0.020 out |
| ~70B+ (dsr1, nemotron) | GPT-4.5 / Claude 3.5 Sonnet | 0.020 in / 0.040 out |

Rates are **approximate and manually maintained**. Not used for billing — for savings estimation only.

---

## 7. Feedback-Loop Assumptions

Used by Z-4 cross-project feedback ledger.

| Assumption | Detail |
|-----------|--------|
| **Manual only** | Controllers (Claude Code / Codex) write feedback records manually — no automatic writes |
| **CLI-only** | `tools/feedback_ledger.py` — no MCP tool, no hooks, no gate integration |
| **Append-only** | JSONL to `.local_llm_out/feedback/feedback.jsonl` — never mutates, never deletes |
| **Privacy** | Same rules as call ledger — no secrets, no full file bodies, no prompt content |
| **Disposition taxonomy** | `accepted`, `rejected`, `false_positive`, `converted_to_fix`, `deferred` |
| **Cross-project** | Each record links `source_project` (pipeline) to `target_project` (where finding applies) |

---

## 8. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Quality smoke produces false positives | Medium | Low | Advisory-only, no gate integration, exit code never blocks |
| Cloud cost reference goes stale | High | Low | Static JSON, manual updates, documented as approximate |
| Feedback ledger never populated | Medium | Medium | Manual-only by design — adoption depends on controller discipline |
| Z-2 model calls increase ledger volume | High | Low | ~6 calls per run, ~1.2K tokens per run — negligible |
| Scope creep into 13th MCP tool | Low | High | Hard constraint documented; Z-2/Z-4 are CLI-only |
| Cross-project ledger attribution gap | High | Medium | Z-4 partially addresses; Z-1 documents the known limitation |

---

## 9. Boundaries

- **Z-chain is a verification line**, not a feature line — all outputs are advisory
- **No new MCP tools** — all new functionality is CLI-only
- **No runtime behavior changes** to existing worker/router/MCP server/hooks
- **No VERSION bumps** — `0.12.0` is the Z-chain baseline version
- **No push, no tag, no release** — Z-chain is local-only
- **No local-translator-agent changes** — S-C is closed
