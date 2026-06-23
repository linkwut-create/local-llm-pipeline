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

## 更新 (2026-06-23) — llama.cpp 默认后端迁移完成

- `tools/local_llm_worker.py`：默认 provider 改为 `openai-compatible`，默认 endpoint `http://127.0.0.1:4000/v1`；Ollama 仅在 `LOCAL_LLM_BASE_URL` 指向 `:11434` 或显式指定 `provider=ollama` 时触发。
- `tools/local_route_committee.py`：`_call_model()` 改为 OpenAI-compatible `/v1/chat/completions`；默认模型改为 `qwen3.6-deep` / `gemma4-31b`。
- `tools/local_llm_check.py`：默认优先探测 LiteLLM `/v1/models`，Ollama 降为显式 fallback。
- `tools/local_llm_residency.py`：keepalive 改为 `/v1/chat/completions` 短请求；默认常驻模型改为 `qwen3.6-deep`、`gemma4-31b`。
- `tools/local_llm_profiles.json`：`default_profile` 指向 `qwen3.6_llamacpp`（`_backend_class: openai-compatible`）。
- `tools/local_llm_tasks.json`：debate 与 health-report 任务默认指向 `*_llamacpp` profile。
- `tools/update_profiles_from_ollama.py`：标记为 deprecated/embedding-only。
- `INTERFACES.md` / `tools/validate_configs.py`：`_backend_class` 允许 `openai-compatible`。
- 性能基线（首次本地测量，LiteLLM 可达时）：待补充。

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
