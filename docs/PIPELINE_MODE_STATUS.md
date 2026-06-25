# PIPELINE_MODE_STATUS.md — local-llm-pipeline v2-alpha

> **Purpose**: Living status for the v2-alpha pipeline mode implementation.  
> **Updated**: 2026-06-25  
> **Current phase**: Phase 14 — Real Dogfood (5/5 tasks, COMPLETE)

## Phase Progress

| Phase | Title | Status | Commit |
|-------|-------|--------|--------|
| 0 | Baseline Audit | Done | f768a7b |
| 1 | Task Lifecycle Fix | Done | b0f753d |
| 2 | Tool Permission Enforcement | Done | 30ace01 |
| 3 | Unified Route Policy | Done | eb5b871 |
| 4 | Route Committee Hardening | Done | 03d7587 |
| 5 | Model Switch Lifecycle | Done | 8f2de45 |
| 6 | Reproducible Hook Installation | Done | 8754f8d |
| 7 | Formalized Artifact Store | Done | 8e0f628 |
| 8 | Minimal AgentDB | Done | 694c08a |
| 9 | Local Worker | Done | 0123ae8 |
| 10 | Flash Worker | Done | 7639218 |
| 11 | Tool Actuator | Done | f65f624 |
| 12 | Pro Adjudication | Done | bf26b40 |
| 13 | End-to-End Dry Run | Done | 0bf4ce2 |
| 14 | Real Dogfood | Complete | 5/5 real tasks: Ollama purge, GGUF consolidation, 4-tool migration, 37-model audition, MCP wildcard fix
| 14.5 | Real pipeline task | Ready | route_enforcer wildcard fixed (2026-06-25 PM), pipeline mode operational |
| 15 | Cost & Quality Evaluation | Ready | Phase 14 complete |
| 16 | v2-alpha Finalization | Not started | Needs Phases 1-15 |

## Pipeline Modules Inventory

| Module | Phase | Purpose |
|--------|-------|---------|
| pipeline_route_policy.py | 3 | Single source of truth for route permissions |
| pipeline_hooks.py | 6 | Reproducible hook install/status/uninstall/doctor |
| pipeline_artifact_store.py | 7 | Fixed directory layout + artifact metadata |
| pipeline_local_worker.py | 9 | Structured local model worker artifacts |
| pipeline_flash_worker.py | 10 | Constrained Flash cloud worker |
| pipeline_tool_actuator.py | 11 | Mechanical verified patch application |
| pipeline_adjudicator.py | 12 | Pro adjudication from compressed artifact pack |
| pipeline_mocks.py | 13 | Mock Plan/Qwen/Gemma/Worker/Pro for dry run |
| pipeline_e2e_dry_run.py | 13 | Full 9-step E2E orchestrator (8 route types) |

## Test Baseline
3141 passed, 32 skipped, 0 failed (100% pass rate, 27 test failures fixed 2026-06-25)

## Infrastructure (2026-06-25)
- Zero12: Vulkan (8060S 116GB), 37 models via LiteLLM, systemd on-demand
- Local: , profiles updated from audition scores
- GGUF: 37 reasoning models at 

## Next Actions
1. ~~Fix route_enforcer wildcard bug (mcp__* not expanding)~~ — DONE (2026-06-25 PM)
2. Phase 14.5: Execute real pipeline task (MCP wildcard fixed)
3. Download nemotron-super compatible GGUF from ModelScope
4. Phase 15: Cost comparison
