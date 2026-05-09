# Local LLM Model Benchmark Results

## Test Setup

- **Date**: 2026-05-09/10
- **Machine**: zero12 (Radeon 8060S, 128GB RAM)
- **Backend**: Ollama (remote via OLLAMA_HOST)
- **Test file**: AGENTS.md (2270 bytes)
- **Method**: Solo testing — one model at a time, no GPU contention
- **Models tested**: 31 unique text models
- **Note**: Early batches ran in parallel causing false timeouts/slowdowns. Final results are corrected solo runs.

## Solo Results (definitive)

### Summarize-File

| Model | Size | Duration | Status |
|---|---|---|---|
| Nemotron-3-Nano-30B | 40GB | **17.2s** | OK |
| llama4 | 67GB | **19.9s** | OK |
| gpt-oss-120b-f16 | 65GB | **23.2s** | OK |
| qwen3.5-claude-opus-9b | 9.5GB | **28.6s** | OK |
| gemma4:e4b | 9.6GB | **31.4s** | OK |
| nvidia-nemotron-3-nano-omni | 35GB | 32.7s | OK |
| translategemma-12b-it | 12GB | 33.3s | OK |
| qwen3.5-9b-q8 | 12GB | 42.0s | OK |
| legalone:r1-8b | 8.7GB | 44.3s | OK |
| nvidia-nemotron-30b | 33GB | 44.5s | OK |
| gemma-4-e4b-q8 | 8.7GB | 45.2s | OK |
| command-r:35b | 18GB | 53.0s | OK |
| mistral-small-24b | 28GB | 55.6s | OK |
| qwen3-coder-next-q8 | 86GB | 58.0s | OK |
| qwen3.5-122b-iq3 | 44GB | 105.3s | OK |
| deepseek-r1-distill-qwen:32b-fixed | 34GB | 157.4s | OK |
| mistral-medium-3.5-128b | 88GB | 183.1s | OK |
| gemma-4-31b-q8 | 35GB | 233.5s | OK (slow) |
| nemotron-3-super | 86GB | 235.4s | OK (heavy) |
| qwen3.5-27b-q8 | 35GB | 275.1s | OK (slow) |

### Review-Diff

| Model | Size | Duration | Status |
|---|---|---|---|
| qwen3-coder:30b | 18GB | **10.4s** | OK |
| qwen3-coder-next-q8 | 86GB | 20.4s | OK |
| **nvidia-nemotron-3-nano-omni** | 35GB | **26.8s** | OK |
| Nemotron-3-Nano-30B | 40GB | 44.6s | OK |
| qwen3.5-claude-opus-9b | 9.5GB | 47.6s | OK |
| qwen3.5-122b-iq3 | 44GB | 56.2s | OK |
| **qwen3.6:35b-q8-ud** | 38GB | **67.9s** | OK |
| qwen3.5-35b-q8 | 48GB | 67.6s | OK |
| gpt-oss-120b-f16 | 65GB | 70.2s | OK |
| qwen3.6:27b-q8-ud | 35GB | 113.7s | OK |
| mistral-medium-3.5-128b | 88GB | 125.7s | OK |
| llama4 | 67GB | 158.6s | OK |
| deepseek-r1-distill-qwen:32b-fixed | 34GB | 210.5s | OK |
| nemotron-3-super | 86GB | 239.6s | OK (heavy) |

### Generate-Test-Plan

| Model | Duration | Status |
|---|---|---|
| qwen3-coder:30b | 16.9s | OK |
| qwen3.6:35b-q8-ud | 98.4s | OK |
| qwen3-coder-next-q8 | 104.8s | OK |

### Reasoning (solo)

| Model | Task | Duration | Status |
|---|---|---|---|
| qwen3.5-27b-reasoning | logic-check | **125.3s** | OK |
| qwen3.5-27b-reasoning | risk-analysis | **126.7s** | OK |
| deepseek-r1-distill-qwen:32b-fixed | risk-analysis | 139.6s | OK |

### Translation

| Model | Duration | Status |
|---|---|---|
| glm-4.7-flash-q8 | 151.4s | OK |
| translategemma-12b-it | 33.3s | OK (summarize task) |

## Models With Issues

| Model | Issue | Type |
|---|---|---|
| gemma4:26b-q8-ud | `panic: failed to sample token` | Ollama bug |
| mistral-small-4-119b | blob file missing on disk | Deployment |
| deepseek-r1-70b | >300s for reasoning tasks | Too slow for MCP |
| translategemma-27b-it | >300s for translation | Too slow for MCP |
| gemma-4-31b-q8 | 233s summarize | Too slow for routine |
| qwen3.5-27b-q8 | 275s summarize, 219s review | Too slow |
| mistral-small-24b | TIMEOUT review in parallel, 56s summarize OK | Borderline |

## Profile Assignments (v0.6.1 final, solo-corrected)

| Profile | Model | Why |
|---|---|---|
| fast_summary | gemma4:e4b (31s) | Fastest light model |
| smart_summary | qwen3.5-claude-opus-9b (29s) | Opus quality in 9.5GB |
| code_worker | qwen3-coder-next-q8 (105s test-plan) | Dedicated coder, intelligence > speed |
| fast_code | qwen3-coder:30b (10s review, 17s test-plan) | 6x faster for quick code tasks |
| diff_reviewer | nvidia-nemotron-3-nano-omni (27s review) | Fastest review + reasoning capability |
| deep_reviewer | qwen3.6:35b-q8-ud (68s review) | 0 timeouts, most reliable |
| heavy_reviewer | gpt-oss-120b (70s review, 120B) | 120B intelligence at reasonable speed |
| reasoning_checker | qwen3.5-27b-reasoning (125-127s) | 2/2 passed, most reliable |
| deep_reasoning | deepseek-r1-32b-fixed (140s) | CLI only, critical reasoning |
| translation | glm-4.7-flash-q8 (151s) | Only reliable option via MCP |
| release_auditor | mistral-medium-3.5-128b (126s review) | Accuracy king, 0 timeouts |
| architecture_reviewer | qwen3.6:35b-q8-ud (68s review) | Most reliable, 0 timeouts |
| embedding | nomic-embed-text-v2-moe | Only embedding option |
