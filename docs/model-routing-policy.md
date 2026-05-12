# Local Model Routing Policy

## Core Principle

**Community reputation + local benchmark + task fit**, not parameter count.

A model enters the default routing path only when all three conditions are met:

1. Strong community standing (proven on public benchmarks, widely validated)
2. Stable on this machine (benchmarked, no timeouts, acceptable latency)
3. Appropriate for the task type (coder for code, translator for translation, etc.)

## Blessed Model Tiers

### Tier 1 — Commit Gate & Fast Tasks (everyday, high-frequency)

| Task | Model | Rationale |
|------|-------|-----------|
| commit gate diff review | `qwen3-coder:30b` | Qwen3-Coder family is purpose-built for agentic coding, tool use, and multi-step programming. ~10s on this machine. |
| file summarization | `gemma4:e4b` | Lightweight, fast (~30s), sufficient for understanding file structure. |
| directory summarization | `gemma4:e4b` | Same as above. |
| TODO extraction | `qwen3-coder-next-q8` | Coder model, low latency. |

**Rule**: Commit gate must never use a model >30B or a reasoning model. Latency matters.

### Tier 2 — Code Review & Test Planning (moderate frequency)

| Task | Model | Rationale |
|------|-------|-----------|
| non-commit diff review | `nvidia-nemotron-3-nano-omni-30b-a3b-reasoning` | Reasoning-augmented review. Only for explicit (non-gate) review calls. |
| test plan generation | `qwen3-coder-next-q8` | Dedicated coder model. |
| code drafting (fix/feature/refactor) | `qwen3-coder-next-q8` | Coder model, output restricted to `.local_llm_out/`. |
| improvement suggestions | `gemma4-26b-it:q8_0` | Generalist, good at spotting patterns. |

### Tier 3 — Reasoning & Risk Analysis (triggered, not default)

| Task | Model | Rationale |
|------|-------|-----------|
| risk analysis | `qwen3.5-27b-reasoning` | Reliable reasoning model. 125s, 2/2 passed. |
| logic checks | `qwen3.5-27b-reasoning` | Same as above. |
| failure mode analysis | `qwen3.5-27b-reasoning` | Systematic enumeration of failure cases. |
| **critical** risk analysis | `deepseek-r1-distill-qwen:32b-q8-fixed` | DeepSeek R1 reasoning distilled into Qwen 32B. Use only for architecture changes, security risks, root cause analysis. 140s. |

**Rule**: Reasoning models are never default. They are triggered by explicit request or high-risk classification.

### Tier 4 — Deep Review & Architecture (explicit, low frequency)

| Task | Model | Rationale |
|------|-------|-----------|
| deep code review | `qwen3.6:35b-q8-ud` | Strong generalist. 68s, 0 timeouts — most reliable deep reviewer. |
| architecture review | `qwen3.6:35b-q8-ud` | Same model for architecture tasks. |
| debate review | `code_worker` → `diff_reviewer` → `deep_reviewer` | Multi-model escalation. Three rounds: coder, reasoning, deep. |

### Tier 5 — Release Audit (pre-release only)

| Task | Model | Rationale |
|------|-------|-----------|
| release risk review | `mistral-medium-3.5-128b` | Accuracy king. 126s, 0 timeouts. 128B MoE. |
| heavy review fallback | `gpt-oss-120b` | 120B model. 70s review. Use only when Mistral is unavailable. |

**Rule**: Release audit models must never enter the commit gate or default review path.

### Tier 6 — Translation (task-specific)

| Task | Model | Rationale |
|------|-------|-----------|
| general translation | `translategemma-12b-it-q8` | Purpose-built translation model. |
| complex / CJK translation | `glm-4.7-flash-q8` | Strong multilingual capability. 151s. |
| high-stakes translation | `qwen3.6:35b-q8-ud` | Backup for nuanced text. |

### Tier 7 — Embedding

| Task | Model | Rationale |
|------|-------|-----------|
| text embedding | `nomic-embed-text-v2-moe` | Purpose-built embedding model. |

## Anti-Patterns

### Do NOT

- Default to the largest available model
- Use reasoning models (R1, Nemotron reasoning) for commit gate
- Use 120B+ models for everyday tasks
- Round-robin across all installed models
- Use experimental / unverified models in automated paths
- Use `local-translator-agent/tools/` MCP server copy (outdated)

### DO

- Match model to task type (coder → code, translator → translation)
- Keep commit gate under 30s
- Escalate to reasoning/deep models only on explicit request or high-risk trigger
- Benchmark new models before adding them to any tier
- Use the `_benchmark` field in profiles to track real performance

## Model Categories

### Community-Validated (blessed for automated use)

- **Qwen3-Coder series**: Agentic coding, tool use, multi-step programming
- **Qwen3.5/3.6 series**: General purpose, strong multilingual
- **DeepSeek-R1-Distill series**: Reasoning (R1 distilled into Qwen/Llama)
- **Mistral Medium**: Deep review, accuracy
- **Gemma 4 series**: Fast summarization, general tasks
- **NVIDIA Nemotron Nano Omni**: Reasoning-augmented review
- **GPT-OSS**: Large-scale review (backup)
- **GLM-4.7 Flash**: Multilingual / CJK capability
- **Nomic Embed**: Embedding

### Experimental / Manual-Only

These models exist locally but must NOT enter automated routing paths without explicit benchmarking:

- `llama4`, `command-r`, `nemotron-3-super`, `minicpm-v`, `legalone`, `deepseek-ocr`, `glm-ocr`

## Profile Assignment Rules

When adding or updating a profile, fill in:

```json
{
  "model": "<model name>",
  "use_for": ["<task list>"],
  "risk_level": "low|medium|medium-high|high",
  "_benchmark": "<real timing from this machine>",
  "_community_reputation": "<why this model was chosen — public benchmark results, community validation, official model card claims>",
  "_constraints": "<when to use and when NOT to use this model>"
}
```

Fields prefixed with `_` are metadata and do not affect runtime behavior.

## Review Cadence

This policy should be reviewed:
- When a new model is added to Ollama
- When a model receives a major community update
- When benchmark results change significantly
- Before each release
