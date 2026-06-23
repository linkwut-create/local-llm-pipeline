# PIPELINE_MODE_STATUS.md — local-llm-pipeline v2-alpha

> **Purpose**: Living status for the v2-alpha pipeline mode implementation.  
> **Updated**: 2026-06-23  
> **Current phase**: Phase 13 — End-to-End Dry Run (not started)  

---

## Repository Baseline

| Item | Value |
|------|-------|
| Branch | `master` |
| HEAD | `3b918ca` |
| Commit message | `fix: /v1 normalization for OpenAI-compat URLs; keep Ollama auto-detect for :11434 legacy` |
| Working tree | Clean (2 untracked: `_test_llamacpp.py`, `pipeline_route_policy_template.txt`) |

### Test Baseline

```text
pytest tests/test_pipeline_route_policy.py tests/test_pipeline_adjudicator.py tests/test_route_enforcer.py tests/test_local_route_committee.py
183 passed in 2.32s
```

---

## Phase Progress

| Phase | Title | Status | Commit |
|-------|-------|--------|--------|
| 0 | Baseline Audit | ✅ Done | `f768a7b` |
| 1 | Task Lifecycle Fix | ✅ Done | `b0f753d` |
| 2 | Tool Permission Enforcement | ✅ Done | `30ace01` |
| 3 | Unified Route Policy | ✅ Done | `eb5b871` |
| 4 | Route Committee Hardening | ✅ Done | `03d7587` |
| 5 | Model Switch Lifecycle | ✅ Done | `8f2de45` |
| 6 | Reproducible Hook Installation | ✅ Done | `8754f8d` |
| 7 | Formalized Artifact Store | ✅ Done | `8e0f628` |
| 8 | Minimal AgentDB | ✅ Done | `694c08a` |
| 9 | Local Worker | ✅ Done | `0123ae8` |
| 10 | Flash Worker | ✅ Done | `7639218` |
| 11 | Tool Actuator | ✅ Done | `f65f624` |
| 12 | Pro Adjudication | ✅ Done | `bf26b40` |
| 13 | End-to-End Dry Run | ⬜ Not started | — |
| 14 | Real Dogfood | ⬜ Not started | Needs Phase 13 |
| 15 | Cost & Quality Evaluation | ⬜ Not started | Needs Phase 14 |
| 16 | v2-alpha Finalization | ⬜ Not started | Needs Phases 1–15 |

---

## Additional Work (Beyond Original Roadmap)

| Commit | Description |
|--------|-------------|
| `d3793b6` | feat!: migrate default local backend from Ollama to llama.cpp |
| `45c7527` | migrate: remove Ollama auto-fallback, default to LiteLLM/llama.cpp |
| `376b953` | fix: add SSH safe patterns to Bash classifier |
| `3b918ca` | fix: /v1 normalization for OpenAI-compat URLs; keep Ollama auto-detect for :11434 legacy |

---

## Pipeline Modules Inventory

| Module | Phase | Purpose |
|--------|-------|---------|
| `pipeline_route_policy.py` | 3 | Single source of truth for route permissions |
| `pipeline_route_policy_template.txt` | 3 | Reference template for route.json |
| `pipeline_hooks.py` | 6 | Reproducible hook install/status/uninstall/doctor |
| `pipeline_artifact_store.py` | 7 | Fixed directory layout + artifact metadata |
| `pipeline_local_worker.py` | 9 | Structured local model worker artifacts |
| `pipeline_flash_worker.py` | 10 | Constrained Flash cloud worker |
| `pipeline_tool_actuator.py` | 11 | Mechanical verified patch application |
| `pipeline_adjudicator.py` | 12 | Pro adjudication from compressed artifact pack |

---

## Known Issues at Phase 12

These are intentionally **not fixed** in Phases 0-12 because they belong to later phases.

1. **No end-to-end integration test** — Each module works independently; no single command runs the full pipeline. Owner: Phase 13.

2. **Mock workers needed for dry run** — Plan generator, Qwen/Gemma, local/Flash workers, and Pro decision mocks don't exist yet. Owner: Phase 13.

3. **Task selection remains fragile** — `get_active_task()` picks newest directory by `created_at` without project/session filtering. Owner: deferred to Phase 13+.

4. **No AgentDB file** — AgentDB may be integrated into artifact store / session infrastructure rather than a standalone `pipeline_agentdb.py`. Owner: verify in Phase 13.

---

## Risk Notes

* The LiteLLM → llama.cpp SSH tunnel is the default local backend. The `_test_llamacpp.py` script (untracked) verifies connectivity.
* `/v1` path normalization was recently fixed to handle OpenAI-compatible URLs correctly.
* Ollama auto-detection is kept for `:11434` legacy endpoints.

---

## Decisions Made

| Decision | Reason |
|----------|--------|
| Skipped standalone AgentDB file | AgentDB functionality integrated into artifact store + session.json |
| Default backend: LiteLLM → llama.cpp | Ollama auto-fallback removed; LiteLLM is the standard path |
| Kept Ollama :11434 auto-detect | Legacy compatibility for existing deployments |

---

## Next Actions

1. Commit the `pipeline_route_policy_template.txt` reference template.
2. Commit or remove `_test_llamacpp.py`.
3. Update `PIPELINE_MODE_BACKLOG.md` to match current state.
4. Begin Phase 13: End-to-End Dry Run with mocks.
