# Profile Suggestions

Generated: 2026-06-13
Based on: 21-model audition (full 15-case battery + 3-model dogfood)
Status: **ADVISORY ONLY — do not auto-apply**

---

## Recommended Changes

### fast_summary

| Field | Value |
|-------|-------|
| Current | (check tools/local_llm_profiles.json) |
| Suggested | gemma4:12b-unsloth or qwen3.5:35b |
| Evidence | gemma4:12b-unsloth = fast_summary(3.1), qwen3.5:35b = fast_summary(3.4) across full 15-case battery |
| Confidence | Medium — gemma4 unsloth variants work reliably; gemma4 native variants return empty (MTP issue) |

### docs_agent

| Field | Value |
|-------|-------|
| Current | (check tools/local_llm_profiles.json) |
| Suggested | gemma4:31b-unsloth (3.4) or qwen3-coder:30b (3.6) |
| Evidence | gemma4:31b-unsloth = docs_agent(3.4); qwen3-coder:30b = docs_agent(3.6) |
| Confidence | Medium — qwen3-coder scores high but dogfood on 004 showed JSON understanding (not docs). Role fit may be scoring artifact. |

### code_worker

| Field | Value |
|-------|-------|
| Current | (check tools/local_llm_profiles.json) |
| Suggested | qwen3-coder:30b (needs more evidence) |
| Evidence | Dogfood on 004_json_contract showed correct JSON structure understanding but output truncated at 200 tokens. Full-run shows avoid release_auditor (correct for coder). |
| Confidence | Low — single-case dogfood insufficient. Run full battery before switching. |

---

## Do Not Change (Insufficient Evidence)

### deep_reviewer

| Field | Value |
|-------|-------|
| Reason | No model scored high enough across all deep_reviewer-relevant cases (005, 008, 011). qwen3.6:35b shows promise in dogfood but full-run only shows test_agent(3.1). |
| Action | Re-run qwen3.6:35b with num_predict=400 on full battery. |

### release_auditor

| Field | Value |
|-------|-------|
| Reason | This is the highest-risk role. Dogfood on 011_release_gate with qwen3.6:35b was excellent but single-case only. Full-run shows qwen3.6:35b as test_agent(3.1), not release_auditor. |
| Action | Run qwen3.6:35b on full battery at num_predict=400. Verify against real release gate dogfood before considering change. |

### interface_reviewer

| Field | Value |
|-------|-------|
| Reason | No model shows strong interface_reviewer signal. Best is qwen3.5:35b as secondary. |
| Action | Defer until more evidence. |

---

## Needs More Evidence

| Model | Why | Action |
|-------|-----|--------|
| qwen3-coder:30b | code_worker potential not confirmed by single case | Full battery at num_predict=400 |
| qwen3.6:35b | Strong release gate dogfood but full-run scores don't match | Full battery at num_predict=400 |
| nemotron:30b | 0 score — likely preflight/parameter issue, not capability | Re-test with fixed preflight |
| deepseek-r1:32b-distill | 0 score — all 15 cases failed. Known PROB-007 timeout issue | Debug preflight path |

---

## Deferred (Infrastructure, Not Capability)

| Model | Issue | Action |
|-------|-------|--------|
| gemma4:26b (native) | Empty response — MTP inference issue | Wait for MTP fix |
| gemma4:12b (native) | Empty response — MTP inference issue | Wait for MTP fix |
| gemma4:31b (native) | Not tested — likely same MTP issue | Defer |
| nemotron:super (123B) | >60GB, likely won't load on current hardware | Deferred heavy |
| mistral4:119b | >60GB | Deferred heavy |
| mistral3.5:128b | >60GB | Deferred heavy |
| gpt-oss:120b | >60GB | Deferred heavy |
| qwen3.5:122b | >60GB | Deferred heavy |
| deepseek-r1:70b | >60GB | Deferred heavy |
| llama4:code (108B) | >60GB | Deferred heavy |
| qwen3-coder:next (79B) | >60GB | Deferred heavy |

---

## Gemma4 Native vs Unsloth vs MTP — Separate Conclusions

### Diagnostic Results (2026-06-13)

Systematic API comparison (`/api/generate` vs `/api/chat`, T=0.1/0.7/1.0,
with/without system prompt, English/Chinese prompts):

| Variant | T=0.1 (default) | T=0.7 | T=1.0 | Chat | Verdict |
|---------|:-:|:-:|:-:|:-:|--------|
| gemma4:26b native | EMPTY | marginal | OK (EN only) | EMPTY | **unstable** |
| gemma4:12b native | EMPTY | EMPTY | EMPTY | — | **broken** |
| gemma4:31b native | EMPTY | — | — | — | **broken** |
| gemma4:26b-unsloth | OK (60ch) | — | — | — | **stable** |
| gemma4:12b-unsloth | OK (3.1 score) | — | — | — | **stable** |

### Root Cause

**Ollama native gemma4 GGUF packaging has temperature sensitivity.**
At T ≤ 0.7, the model gets stuck in a sampling dead zone and produces
empty output. This is NOT a model weight problem — unsloth variants and
llama.cpp endpoints work fine with the same weights. It is an Ollama
template/packaging/serving issue.

Additional findings:
- System prompt makes native gemma4 WORSE (even at T=0.7)
- Chinese/technical prompts fail at all temperatures on native
- `/api/chat` and `/api/generate` both affected equally
- gemma4:12b native is completely non-functional at any temperature

### Three Separate Categories

1. **Native Ollama gemma4 (12b/26b/31b)**: `status: unstable_under_ollama`
   - Do NOT use for any role without direct API confirmation
   - Root cause: Ollama GGUF template temperature sensitivity
   - Not a model quality issue — unsloth proves weights are fine

2. **Unsloth gemma4 (12b/26b/31b/e4b)**: `status: stable`
   - Works reliably at T=0.1 with English and technical prompts
   - Candidate for: fast_summary, docs_agent, task_bootstrapper
   - Scores: 3.1-3.4 across full battery

3. **Gemma4 MTP (llama.cpp endpoint)**: `status: deferred`
   - Endpoint idle/restart stability issues
   - Not an Ollama problem — llama.cpp server lifecycle issue
   - Qwen3.6 MTP `nextn.eh_proj` tensor support also pending

### Actionable Strategy

```
Native gemma4 → do not use (Ollama packaging bug, not model)
Unsloth gemma4 → candidate for summary/docs only
MTP endpoint → deferred (infrastructure, not model)
```

- **Mitigation**: Use unsloth variants for summary/docs roles
- **Non-blocking**: Unsloth variants cover 4B-31B range
- **Native gemma4**: Revisit after Ollama template/packaging fix

---

## fast_summary Observation — gemma4:12b-unsloth

Date: 2026-06-13
Profile change: committed `fd6a9ce`

| # | File | Status | Latency | Quality |
|---|------|:--:|--------|---------|
| 1 | AGENTS.md | non-empty | 89s | Accurate: constitution, agent roles, MCP tools |
| 2 | PROBLEMS.md | non-empty | 74s | Accurate: PROB/BAN entries, fragile areas |
| 3 | INTERFACES.md | non-empty | 78s | Accurate: MCP/CLI contracts, privacy risks |
| 4 | LONGTODO.md | non-empty | 57s | Accurate: roadmap chains, dependencies |
| 5 | profile_suggestions.md | non-empty | 59s | Accurate: self-diagnosis summary |

Result:
- Empty response: **0/5**
- Hallucination: **0/5**
- Over-expansion: **0/5**
- Latency: **57-89s** (median 75s, acceptable for 12B)
- Verdict: **STABLE — keep as fast_summary primary**

---

## Summary

```
✅ Applied:
  fast_summary → gemma4:12b-unsloth (fd6a9ce, 5/5 observation passed)

⏸️  Pending observation:
  docs_agent → gemma4:31b-unsloth (wait for fast_summary to prove stable)

🔒 Frozen — DO NOT CHANGE without more evidence:
  deep_reviewer → needs full battery on qwen3.6:35b
  release_auditor → needs full battery + real gate dogfood
  interface_reviewer → no strong candidate yet

Deferred:
  All >60GB models — hardware constraint, not capability
  Native gemma4 — Ollama GGUF temperature sensitivity (T≤0.7 empty), not weight quality
```
