# Inference Migration Status

Updated: 2026-06-22

## Architecture

LiteLLM:4000 (zero12) unified gateway:
- qwen3.6-deep -> llama.cpp:8001 (resident priority 1, Q8_0 Dense 27B)
- gemma4-31b -> llama.cpp:8004 (resident priority 2, Q8_0 Dense 31B)
- qwen3-coder-30b -> llama.cpp:8003 (Q8_K_XL MoE/A3B, on-demand only)
- 4 more models -> on-demand (nemotron, deepseek, glm, gemma4-26b)
- bge-m3 + nomic-embed -> Ollama (embedding only)

Resident policy:
1. Keep the dense 27B Qwen route resident first.
2. Keep Gemma 4 31B dense resident second when memory allows.
3. All other models are on-demand. MoE models, including qwen3-coder 30B-A3B,
   must not be treated as resident services.

## Resident: Qwen3.6 27B Dense

Highest intelligence local model. Dense architecture.
Q8_0, prompt 34 tok/s, gen 6 tok/s, 16K context.
Uses reasoning-auto. Content needs max_tokens >= 1024.

## On-Demand Models (systemd)

All services created; resident policy controls which are enabled:
- qwen36-llama (port 8001, dense 27B; resident priority 1)
- gemma4-31b-llama (port 8004, dense 31B; resident priority 2)
- qwen3-coder-llama (port 8003, MoE/A3B; on-demand only, backs LiteLLM `qwen3-coder-30b`)
- gemma4-26b-llama (port 8002)
- nemotron-30b-llama (port 8009)
- deepseek-r1-32b-llama (port 8010)
- glm4-flash-llama (port 8011)

## GGUF Files

Q8 versions: /home/zero12/ai-cold/llamacpp-models/
Ollama-recovered: /mnt/data/models/recovered-gguf/
Quarantine: .quarantine/ (6 models with Q8 replacements)

## TODO

- Auto model switching in pipeline workflow
- MTP-compatible llama.cpp build
- Ollama Qwen3.5 series removal

## 更新 (2026-06-22)

- `qwen3-coder-llama.service` is installed as a user systemd service for explicit on-demand starts; it is disabled/inactive under the resident policy.
- LiteLLM `qwen3-coder-30b` now routes to `openai/qwen3-coder-30b.sha256-13b998bb.gguf` at `http://127.0.0.1:8003/v1`.
- Verified LiteLLM `/v1/models` exposes `qwen3-coder-30b`; LiteLLM chat smoke returned `OK` while the on-demand service was running.
- Verified local pipeline `commit_reviewer_llamacpp` completed `review-diff` through the local `127.0.0.1:4000` tunnel after starting the on-demand service.
- Resident policy corrected after review: qwen-coder is MoE/A3B and must be
  on-demand, not resident. Dense resident priority is 27B Qwen first, Gemma 4
  31B second.

## 更新 (2026-06-21 第二批)

新增 llama.cpp profiles:
- diff_reviewer_llamacpp: Nemotron 30B (28s)
- deep_reasoning_llamacpp: DeepSeek R1 32B (18s)
- translation_llamacpp: GLM-4.7 Flash (14s)
- gemma4_26b_llamacpp: Gemma4 26B Q8_K_XL (16s)

不兼容:
- qwen3.6-35b-moe-mtp-q8_k_xl.gguf: MTP 格式需要新版 llama.cpp
- qwen3.6-27b-mtp-q8_k_xl.gguf: 同上

所有新增 profile 自动 fallback 到常驻 Qwen3.6 27B。
