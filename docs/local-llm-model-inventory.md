# Local LLM Model Inventory

All models on zero12 (Ollama, Radeon 8060S, 128GB RAM). 58 total entries.

## Fast Summary

| Model | Size | Notes |
|---|---|---|
| `gemma4:e4b` | 9.6 GB | Fastest option, daily default |
| `gemma-4-e4b-q8:latest` | 8.7 GB | Q8 quant of the above |
| `qwen3.5-9b-q8:latest` | 12 GB | Reliable generalist |
| `minicpm-v:latest` | 5.5 GB | Small vision-capable |
| `minicpm-v:4.5-q8` | 8.7 GB | Vision, good multilingual |
| `glm-4.7-flash-q8:latest` | 35 GB | Strong multilingual, fast |
| `gpt-oss-20b-f16:latest` | 13 GB | Open GPT-style, small |
| `qwen3.5-claude-opus-9b-q8_0:latest` | 9.5 GB | Claude Opus distilled, good reasoning |

## Code Workers

| Model | Size | Notes |
|---|---|---|
| `qwen3-coder-next-q8:latest` | 86 GB | **Primary coder** — strongest code understanding |
| `qwen3-coder-next-q8-agent:latest` | 86 GB | Agent-tuned, same digest as above |
| `qwen3-coder:30b` | 18 GB | Reliable fallback coder |
| `qwen3.6:27b-q8-ud` | 35 GB | Good code + general reasoning |
| `qwen3.5-27b-q8:latest` | 35 GB | Solid general purpose |

## Diff Reviewers

| Model | Size | Notes |
|---|---|---|
| `qwen3-coder-next-q8:latest` | 86 GB | Best for structured diff review |
| `qwen3.6:27b-q8-ud` | 35 GB | Good balance of speed and quality |
| `qwen3.5-35b-q8:latest` | 48 GB | Deeper review but slower |
| `mistral-small-24b-q8_xl:latest` | 28 GB | Efficient, good for medium diffs |

## Deep Reviewers

| Model | Size | Notes |
|---|---|---|
| `qwen3.5-35b-q8:latest` | 48 GB | Daily deep review workhorse |
| `qwen3.6:35b-q8-ud` | 38 GB | Newer Qwen 35B |
| `gemma-4-31b-q8:latest` | 35 GB | Strong all-rounder |
| `gemma4-31b-opus:latest` | 32 GB | Opus-distilled Gemma |
| `gemma4:26b-q8-ud` | 27 GB | Lighter Gemma 4 |
| `command-r:35b` | 18 GB | Good at following instructions |
| `llama4:latest` | 67 GB | Meta's latest, heavy |
| `nvidia-nemotron-30b-q8_0:latest` | 33 GB | Nvidia generalist |
| `Nemotron-3-Nano-30B:latest` | 40 GB | Nvidia nano |

## Architecture / Release Auditors (Heavy)

| Model | Size | Notes |
|---|---|---|
| `mistral-medium-3.5-128b-q5_k_xl:latest` | 88 GB | **Strongest** — use for release audits only |
| `mistral-small-4-119b-2603-q5_k_xl:latest` | 89 GB | Very strong, heavy |
| `nemotron-3-super:latest` | 86 GB | Strong reasoning + review hybrid |
| `gpt-oss-120b-f16:latest` | 65 GB | Massive, very slow |
| `qwen3.5-122b-iq3-original:latest` | 44 GB | 122B Qwen, heavy |

## Reasoning Checkers

| Model | Size | Notes |
|---|---|---|
| `deepseek-r1-distill-llama:70b-q8-k-xl` | 81 GB | **Strongest reasoning** — slow |
| `deepseek-r1-distill-qwen:32b-q8` | 34 GB | Good reasoning, faster |
| `deepseek-r1-distill-qwen:32b-q8-fixed` | 34 GB | Fixed variant |
| `qwen3.5-27b-reasoning:latest` | 28 GB | Fastest reasoning, daily driver |
| `nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-q8_k_xl:latest` | 35 GB | Reasoning + omni |

## Translation

| Model | Size | Notes |
|---|---|---|
| `translategemma-27b-it-q8:latest` | 28 GB | Primary translation model |
| `translategemma-12b-it-q8:latest` | 12 GB | Lighter translation |
| `glm-4.7-flash-q8:latest` | 35 GB | Multilingual, very fast |
| `legalone:r1-8b` | 8.7 GB | Legal text specialist |

## OCR / Vision

| Model | Size | Notes |
|---|---|---|
| `deepseek-ocr:q8` | 3.1 GB | OCR specialist |
| `glm-ocr:latest` | 2.2 GB | GLM OCR |
| `minicpm-v:latest` | 5.5 GB | Vision-capable |
| `minicpm-v:4.5-q8` | 8.7 GB | Vision, good multilingual |

## Embedding

| Model | Size | Notes |
|---|---|---|
| `nomic-embed-text-v2-moe:latest` | 957 MB | Primary embedding |
| `bge-m3:latest` | 1.2 GB | Multilingual embedding |

## Standalone GGUF Models (not in Ollama)

Loadable via llama.cpp. Some have higher precision than Ollama equivalents.

## Newly Added (v0.8.1+)

| Model | Size | Benchmark | Status |
|---|---|---|---|
| `gemma4-26b-it:q8_0` | 26 GB | 37.8s summarize-file | ✅ Working in Ollama |
| `gemma-4-26B-A4B-it-assistant-F16.gguf` | 815 MB | N/A | MTP drafter — not standalone |
| `gemma-4-31B-it-assistant-F16.gguf` | 911 MB | N/A | MTP drafter — on zero12 |

### Mistral Small 119B Q6 (llama.cpp only)

| File | Size | Notes |
|---|---|---|
| `/mnt/data/llamacpp-models/mistral-small-119b-q6.gguf` | 92 GB | Q6 quality. Too large for Ollama (89GB fails to load). Use via llama.cpp: `llama-server -m mistral-small-119b-q6.gguf --port 8080 -ngl 99` |
| `/mnt/data/llamacpp-models/mistral-small-4-119b-q5_k_xl-merged.gguf` | 84 GB | Q5_K_XL merged from 3 shards. llama.cpp only. |

### Gemma 4 31B Assistant (Instruction-Tuned)

Official Google assistant/instruction-tuned GGUF files. These are optimized for instruction-following and assistant tasks, different from the base Gemma models in Ollama.

| File | Size | Quant |
|---|---|---|
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-BF16-00001-of-00002.gguf` | — | BF16 (shard 1) |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-BF16-00002-of-00002.gguf` | — | BF16 (shard 2) |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-Q4_0.gguf` | — | Q4_0 (fast) |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-Q4_1.gguf` | — | Q4_1 |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-IQ4_NL.gguf` | — | IQ4_NL (quality) |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-IQ4_XS.gguf` | — | IQ4_XS (small) |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-Q3_K_M.gguf` | — | Q3_K_M |
| `/home/zero12/.cache/modelscope/.../gemma-4-31B-it-Q3_K_S.gguf` | — | Q3_K_S |

### Fish Speech

| File | Size | Notes |
|---|---|---|
| `/home/zero12/fish-speech/checkpoints/s2-pro-f16.gguf` | — | TTS model, not an LLM |

### llama.cpp Launch

```bash
# Gemma 4 31B Assistant (IQ4_NL recommended for quality)
llama-server -m ~/.cache/modelscope/.../gemma-4-31B-it-IQ4_NL.gguf --port 8080 -ngl 99

# Mistral Small 119B Q6 (best quality deep review)
llama-server -m /mnt/data/llamacpp-models/mistral-small-119b-q6.gguf --port 8081 -ngl 99
```

Then use via pipeline:
```powershell
$env:LOCAL_LLM_BASE_URL = "http://zero12:8080/v1"
python tools/local_llm_router.py summarize-file README.md --provider openai-compatible
```

## Development Variants (filtered by auto-update)

These share digests with base models. SKIP_SUFFIXES filters them.

| Variant | Base Model |
|---|---|
| `*-original:latest` | Same digest as base |
| `*-agent:latest` | Agent-tuned tag |
| `*-agentprefill:latest` | Agent prefill variant |
| `*-toolfix:latest` | Tool fix variant |

## Heavy Models (use sparingly)

| Model | Size | Est. Time | Use Case |
|---|---|---|---|
| `mistral-medium-3.5-128b` | 88 GB | 60-120s | Release audit |
| `mistral-small-4-119b` | 89 GB | 50-100s | Architecture review |
| `nemotron-3-super` | 86 GB | 60-90s | Deep review |
| `deepseek-r1-distill-llama:70b` | 81 GB | 90-150s | Critical reasoning |
| `gpt-oss-120b-f16` | 65 GB | 120s+ | Fallback only |
| `qwen3.5-122b` | 44 GB | 60-120s | Architecture |
| `llama4` | 67 GB | 60-90s | General deep review |
