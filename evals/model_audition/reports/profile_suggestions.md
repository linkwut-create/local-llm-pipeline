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

## Gemma4 MTP Status

- **Unsloth variants**: gemma4:12b-unsloth, gemma4:26b-unsloth, gemma4:31b-unsloth, gemma4:e4b-unsloth — all work and produce scores 3.1-3.4
- **Native variants**: gemma4:12b, gemma4:26b, gemma4:31b — return empty responses in current Ollama environment
- **Root cause**: MTP (Multi-Token Prediction) incompatibility between gemma4 native GGUF and current Ollama server
- **Mitigation**: Use unsloth variants for now. Require idle/restart handling for production use.
- **Non-blocking**: Unsloth variants cover the needed size range (4B-31B)

---

## Summary

```
Low-risk changes ready (1-2 profiles):
  fast_summary → consider gemma4:12b-unsloth
  docs_agent → consider gemma4:31b-unsloth

High-risk roles — DO NOT CHANGE without more evidence:
  deep_reviewer → needs full battery on qwen3.6:35b
  release_auditor → needs full battery + real gate dogfood
  interface_reviewer → no strong candidate yet

Deferred:
  All >60GB models — hardware constraint, not capability
  Gemma4 native — MTP inference issue, not model quality
```
