# Local Model Routing Policy

## Core Principle

**Community reputation + local benchmark + task fit**, not parameter count.

A model enters the default routing path only when all three conditions are met:

1. Strong community standing (proven on public benchmarks, widely validated)
2. Stable on this machine (benchmarked, no timeouts, acceptable latency)
3. Appropriate for the task type (coder for code, translator for translation, etc.)

All claims below are backed by solo benchmarks on zero12 (2026-05-09/10) or live tests (2026-05-12).

## Blessed Model Tiers

### Tier 1 — Commit Gate (highest frequency, latency-critical)

| Task | Model | Benchmark |
|------|-------|-----------|
| commit gate diff review | `qwen3-coder:30b` | **10.4s** review, 16.9s test-plan |

**Rule**: Commit gate must never use a model >30B or a reasoning model. Latency target: under 30s.

### Tier 2 — Fast Tasks (high frequency)

| Task | Primary | Fallback | Benchmark |
|------|---------|----------|-----------|
| file summarization | `gemma4:e4b` | `qwen3.5-claude-opus-9b` | 31.4s / 28.6s |
| directory summarization | `gemma4:e4b` | `qwen3.5-claude-opus-9b` | same |
| TODO extraction | `qwen3-coder-next-q8` | `qwen3-coder:30b` | 58s summarize |

**Smart summary option**: `qwen3.5-claude-opus-9b` (28.6s summarize, 47.6s review, 9.5GB). Opus-distilled quality in a small package. Use when quality matters more than raw speed.

### Tier 3 — Code Review & Test Planning

| Task | Model | Benchmark |
|------|-------|-----------|
| non-commit diff review | `nvidia-nemotron-3-nano-omni` | **26.8s** review, reasoning-augmented |
| test plan generation | `qwen3-coder-next-q8` | 104.8s test-plan |
| code drafting | `qwen3-coder-next-q8` | dedicated coder |
| fast code tasks | `qwen3-coder:30b` | 10.4s review, 16.9s test-plan |

**Note**: `nvidia-nemotron-3-nano-omni` is a reasoning model (~39GB). Fast for its capability but may cause GPU swap if another large model is loaded. Only for explicit (non-gate) review calls.

Non-reasoning alternative: `Nemotron-3-Nano-30B` (44.6s review, **17.2s** summarize — fastest summarizer tested, but 40GB).

### Tier 4 — Deep Review & Architecture

| Task | Model | Benchmark |
|------|-------|-----------|
| deep code review | `qwen3.6:35b-q8-ud` | **67.9s** review, 0 timeouts |
| architecture review | `qwen3.6:35b-q8-ud` | most reliable deep reviewer |
| heavy backup | `gpt-oss-120b` | **70.2s** review, **23.2s** summarize (120B at remarkable speed) |

### Tier 5 — Reasoning & Risk Analysis (triggered only)

| Task | Model | Benchmark |
|------|-------|-----------|
| risk analysis | `qwen3.5-27b-reasoning` | **126.7s**, 2/2 passed |
| logic checks | `qwen3.5-27b-reasoning` | **125.3s**, 2/2 passed |
| failure mode analysis | `qwen3.5-27b-reasoning` | most reliable |
| **critical** risk analysis | `deepseek-r1-distill-qwen:32b-q8-fixed` | **139.6s** risk, R1 distilled |

**Rule**: Reasoning models are never default. Triggered by explicit request or high-risk classification.

### Tier 6 — Release Audit (pre-release only)

| Task | Model | Benchmark |
|------|-------|-----------|
| release risk review | `mistral-medium-3.5-128b` | **125.7s** review, accuracy king |
| heavy fallback | `gpt-oss-120b` | 70.2s review (120B, faster than Mistral) |

**Rule**: Must never enter commit gate or default review path.

### Tier 7 — Translation

| Task | Model | Benchmark |
|------|-------|-----------|
| translation (CLI/MCP) | `glm-4.7-flash-q8` | **151.4s**, only CLI-verified option (2026-05-12) |
| translation (plugin) | `translategemma-12b-it-q8` | works via immersive plugin, but current CLI prompt template does not trigger translation behavior |

**Note**: `translategemma-12b-it` can translate when given the right prompt format (immersive plugin proof), but the CLI's `translate-text` prompt template produces a chatbot-style "please provide text" response instead of translation output. If the prompt template is adjusted, it could become a faster alternative (~33s summarize speed suggests ~30-60s translation potential). For now, `glm-4.7-flash` is the only reliable CLI/MCP translation path.

### Tier 8 — Embedding

| Task | Model |
|------|-------|
| text embedding | `nomic-embed-text-v2-moe` |

## Known-Bad / Unusable Models

These models exist locally but are broken, too slow, or fail on this hardware:

| Model | Issue |
|-------|-------|
| `gemma4:26b-q8-ud` | Ollama panic: failed to sample token |
| `mistral-small-4-119b` | blob file missing on disk |
| `deepseek-r1-distill-llama:70b` | >300s reasoning, too slow for MCP |
| `deepseek-r1-distill-qwen:32b-q8` (non-fixed) | FAIL on logic-check, 300s timeout |
| `translategemma-27b-it` | >300s translation, timeout |
| `gemma-4-31b-q8` | 233.5s summarize, too slow for routine |
| `qwen3.5-27b-q8` | 275.1s summarize, 219.2s review |
| `mistral-small-24b` | TIMEOUT on review |

## Model Categories

### Community-Validated (blessed for automated use)

- **Qwen3-Coder series** (30B, next-q8): Agentic coding, tool use, multi-step programming. Strong public benchmarks.
- **Qwen3.5/3.6 series** (9B, 27B-reasoning, 35B): General purpose. Claude-Opus-9b is a hidden gem.
- **DeepSeek-R1-Distill-Qwen-32B-fixed**: R1 reasoning distilled. 139.6s risk analysis.
- **Mistral Medium 3.5 128B**: Accuracy king for deep review and release audit.
- **Gemma 4 series** (e4b, 26b): Google. Fast and reliable for low-stakes tasks.
- **NVIDIA Nemotron** (Nano 30B, Nano Omni 30B): Fast summarizer + reasoning-augmented review.
- **GPT-OSS 120B**: Remarkable speed for 120B (23.2s summarize, 70.2s review).
- **GLM-4.7 Flash**: Multilingual/CJK. Only CLI-verified translation model.
- **Nomic Embed**: Purpose-built embedding.
- **llama4**: Surprisingly fast (19.9s summarize, 44.9s review).

### Experimental / Manual-Only

Must NOT enter automated routing paths without explicit benchmarking:

`command-r:35b`, `nemotron-3-super`, `minicpm-v`, `legalone:r1-8b`, `deepseek-ocr`, `glm-ocr`

## Anti-Patterns

### Do NOT

- Default to the largest available model
- Use reasoning models (R1, Nemotron reasoning) for commit gate
- Use 120B+ models for everyday tasks
- Use unverified models in automated paths
- Use `local-translator-agent/tools/` MCP server copy (outdated)
- Assume a model works for a task without testing it on that specific task

### DO

- Match model to task type (coder → code, translator → translation)
- Keep commit gate under 30s
- Escalate to reasoning/deep models only on explicit request or high-risk trigger
- Benchmark new models on their target task before adding to any tier
- Verify model claims with actual CLI/MCP tests, not just parameter cards

## Profile Assignment Rules

When adding or updating a profile, fill in:

```json
{
  "model": "<model name>",
  "use_for": ["<task list>"],
  "risk_level": "low|medium|medium-high|high",
  "_benchmark": "<real timing from this machine>",
  "_community_reputation": "<why chosen — benchmarks, community validation, model card claims>",
  "_constraints": "<when to use and when NOT to use>",
  "_last_tested": "<date of most recent verification>"
}
```

Fields prefixed with `_` are metadata and do not affect runtime behavior.

## Review Cadence

This policy should be reviewed:
- When a new model is added to Ollama
- When a model receives a major community update
- When benchmark results change significantly
- Before each release
- When a model that "should work" fails an actual CLI/MCP test
