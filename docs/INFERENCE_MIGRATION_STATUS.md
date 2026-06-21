# Inference Migration Status

Updated: 2026-06-21

## Architecture

LiteLLM:4000 (zero12) unified gateway:
- qwen3.6-deep -> llama.cpp:8001 (only resident, Q8_0 Dense 27B)
- qwen3-coder-30b -> llama.cpp:8003 (on-demand, 6s start)
- gemma4-31b -> llama.cpp:8004 (on-demand, 8s start)
- 4 more models -> on-demand (nemotron, deepseek, glm, gemma4-26b)
- bge-m3 + nomic-embed -> Ollama (embedding only)

## Resident: Qwen3.6 27B Dense

Highest intelligence local model. Dense architecture.
Q8_0, prompt 34 tok/s, gen 6 tok/s, 16K context.
Uses reasoning-auto. Content needs max_tokens >= 1024.

## On-Demand Models (systemd)

All services created, stopped by default:
- qwen3-coder-llama (port 8003, Q8_K_XL)
- gemma4-31b-llama (port 8004, Q8_0)
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