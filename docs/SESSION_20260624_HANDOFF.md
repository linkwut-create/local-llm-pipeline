# Session Handoff - 2026-06-24

## Completed Today (14 commits)

### Infrastructure
- P1: Port 4000 opened on zero12 firewall
- LiteLLM: 53 models via llama.cpp, Ollama deprecated
- Systemd services: all models on-demand (ports 8001-8057)
- model_launcher.py: on-demand model lifecycle via systemd
- model_queue.py: file-based serialized queue, multi-window safe
- profiles.json + tasks.json rewritten: openai-compatible backend

### Pipeline Core
- RouteDecision: tier + cloud_model fields (local|flash|pro)
- step_execute: real dispatch - all tiers verified
  - local -> llama.cpp via LiteLLM
  - flash -> DeepSeek-V4 Flash API
  - pro -> DeepSeek-V4 Pro API
- Committee JSON parsing fixed: strip fences, largest object, 32K tokens
- Route policy: MCP tools allowed under local_only (breaks deadlock)
- All timeouts: 1000s minimum for local model inference

### Verified
- E2E tests: 25/25 pass
- Full pipeline: committee consensus -> tier dispatch -> artifact saved
- Model launcher: on-demand start tested (gemma4-12b, 3s)
- Model queue: enqueue -> worker -> result returned (1s)
- 270 commits pushed to origin

## Not Done

### Zero12
- [ ] Ollama daemon auto-restarts - need manual: sudo systemctl disable --now ollama
- [ ] 8002 (gemma4-26b-A4B) unstable - keeps crashing

### MCP Server
- [ ] Needs restart to pick up DEBATE_TIMEOUT=1000s
- [ ] debate_review timed out at 360s (old cached value)

### Pipeline Gaps
- [ ] Committee fallback: pro_decision is too restrictive (Edit/Write denied)
  Should fallback to direct (with warnings) instead
- [ ] Phase 14: 1/5 real tasks completed
- [ ] Route enforcer wildcard expansion exists but session route.json must be fresh
- [ ] 120+ stale task sessions accumulate - need auto-cleanup
- [ ] CLI committee path not fully tested with evidence truncation

### Cloud Model Switching
- [x] tier dispatch works for flash/pro
- [ ] Committee does not specify per-subtask cloud model
- [ ] DeepSeek classifier intermittently unavailable (API rate limiting)

## Key Files Changed
- tools/local_route_committee.py: tier, parsing, max_tokens, evidence truncation
- tools/pipeline_route_policy.py: MCP tools in local_only
- tools/pipeline_e2e_dry_run.py: step_execute three-tier dispatch
- tools/model_launcher.py: on-demand lifecycle, config path env var
- tools/model_queue.py: NEW - serialized model request queue
- tools/local_llm_profiles.json: Ollama removed, llamacpp profiles
- tools/local_llm_tasks.json: remapped to new profiles
- tools/local_llm_mcp_server.py: timeouts 1000s, commit gate fix
- tools/local_llm_worker.py: ensure_running before inference
- .mcp.json: direct connection to zero12:4000