# PIPELINE_MODE_STATUS.md — v2 Completion Tracker

> **Last updated**: 2026-06-22 (resident model priority clarified: dense first, MoE on-demand)
> **Git**: local branch ahead of origin; local hook audit import fallback, debate routing, and router probe fixes are uncommitted; no push/tag/release
> **Tests**: 399 targeted router/hook/audit/debate/MCP-server tests passed; full router profile tests now pass with `sys.executable` instead of Windows `py -3`
> **Review gates**: hook audit fallback final diff review PASS; dense two-model debate PASS; `commit_reviewer_llamacpp` review-diff completed through LiteLLM -> llama.cpp:8003 with qwen-coder started on demand
> **Full checks**: `tools/run_checks.py` 12/13 PASS; pytest collector error remains in `tools/test_all_models.py::test_model_with_task` (missing `model` fixture)
> **Codex CLI**: project cwd exposes `local-llm` MCP via `python3 tools/local_llm_mcp_server.py`; current process env may override project config with zero12 Ollama at `193.168.2.2:11434`

## Recent Progress

- Worktree convergence is complete: Codex/agent baseline files were committed in `094775e`.
- Codex project config now routes local LLM MCP calls to the zero12 SSH tunnel (`127.0.0.1:11436`) with `qwen3.6:27b` as the resident model.
- Router model discovery now falls back to the Ollama HTTP API when the local `ollama` CLI is unavailable, matching the Codex sandbox path.
- Worker/residency keepalive payloads now normalize `-1` and `0` to numeric values for Ollama 0.30.7 compatibility.
- B2/B3 route committee prompt hardening is complete locally: Qwen and Gemma now receive role-specific prompts while sharing the same JSON output schema.
- B4/B5 route committee validator hardening is complete locally: artifact merges are deterministic and generated route.json output is validated before write.
- F1 secrets/.env protection is locally complete and E2E-pending: PreToolUse now hard-denies direct file and shell access to `.env`, private key, token, and credentials paths before route enforcement.
- Debate default route stabilization is in progress: default debate rounds now avoid unavailable Qwen3.6 MTP profiles and use `commit_reviewer`, `fast_summary`, then `reasoning_checker`.
- Inference migration for qwen-coder is complete at the route level: LiteLLM `qwen3-coder-30b` routes to `openai/qwen3-coder-30b.sha256-13b998bb.gguf`, and local `commit_reviewer_llamacpp` completed a real review-diff through the `127.0.0.1:4000` tunnel after the qwen-coder service was started on demand. Operational policy is now explicit: qwen-coder is MoE/A3B and must be on-demand, not resident.
- Resident model priority: dense 27B Qwen route first, Gemma 4 31B dense second, all other models on-demand. If docs say `qwen3.5 27b`, verify against the actual zero12 service/model name before renaming the existing `qwen36-llama.service`.
- Router OpenAI-compatible health probes now send `LOCAL_LLM_API_KEY` as a bearer token, so authenticated LiteLLM endpoints are no longer misclassified as unreachable.
- `local_review_diff` commit-gate timeout now assumes a prewarmed route: llama.cpp-backed profiles are explicitly started and waited on before the timed review subprocess starts, so model loading is not counted as review generation time.
- Next route committee slice after F1 remains A6/C1/E1: E2E hook loop test, task session directory stabilization, or adjudication input schema.

## Module Completion Overview

### 1. Hook Adapter (route_enforcer.py)

| Check | Status |
|-------|--------|
| main() stdin→JSON→dispatch→stdout | ✅ |
| UserPromptSubmit → PLAN-ONLY context | ✅ |
| PreToolUse → route enforcement | ✅ |
| PostToolUse → artifact capture (A4) | ✅ |
| Stop → route committee trigger + model switch | ✅ |
| Unknown event / invalid JSON → {} | ✅ |
| Subprocess-level tests | ✅ (49 tests) |
| Hook registration (4 events) | ✅ |
| PreToolUse matcher: Edit\|Write\|NotebookEdit\|Bash\|Agent | ✅ |
| PreToolUse secrets/.env hard-deny (F1) | ✅ local / E2E pending |
| PostToolUse matcher: Edit\|Write\|NotebookEdit\|Bash | ✅ |
| E2E verified in real Claude Code session | ⬜ |

**Completion**: 88% (was 85%)

### 2. Flash Model Switch

| Check | Status |
|-------|--------|
| flash_direct FORCES deny Pro Edit/Write | ✅ |
| flash_direct allows Agent (subagent delegation) | ✅ |
| flash_subagent full access | ✅ |
| Flash authorization popup (PreToolUse ask) | ✅ |
| PostToolUse auto-mark flash_authorized | ✅ |
| _apply_model_switch() Stop hook → settings.local.json | ✅ |
| DeepSeek v4 Flash API verified (200 OK) | ✅ |
| flash-mode skill | ✅ |
| /model manual switch documented | ✅ |

**Completion**: 90%

### 3. Route Committee

| Check | Status |
|-------|--------|
| LOCAL_ROUTE_QWEN_MODEL env var (B1) | ✅ |
| LOCAL_ROUTE_GEMMA_MODEL env var (B1) | ✅ |
| Timeout + retry + parse fallback | ✅ |
| --output direct route.json write | ✅ |
| Qwen/Gemma structured output prompt | ✅ |
| Deterministic merge rules hardening | ✅ |
| route.json schema validator | ✅ |

**Completion**: 75% (was 60%)

### 4. Artifact Store (A4)

| Check | Status |
|-------|--------|
| tool_call_N.json per invocation | ✅ |
| Bash output classified (7 types) | ✅ |
| Edit/Write edit_record_N.json | ✅ |
| artifact_index.json (typed/sized/timestamped) | ✅ |
| _truncate_output safe truncation | ✅ |
| Artifact metadata (type, tool, size, timestamp) | ✅ |
| Git diff / test log capture | ✅ |
| Save tool call metadata for all tool types | ✅ |
| Artifact accepted/rejected tracking | ⬜ |

**Completion**: 75% (was 30%)

### 5. Task Session

| Check | Status |
|-------|--------|
| create_task_session() | ✅ |
| session.json with phase tracking | ✅ |
| flash_authorized flag | ✅ |
| user_task.md | ✅ |
| git_status.txt | ⬜ |
| Fixed directory structure per task_id | 🔧 |

**Completion**: 60% (was 50%)

### 6. AgentDB

| Check | Status |
|-------|--------|
| SQLite database | ⬜ |
| Init / report commands | ⬜ |

**Completion**: 5% (unchanged)

### 7. Local Worker

| Check | Status |
|-------|--------|
| v1 MCP tools (summarize, review, repo_map) | ✅ |
| Output as task artifact | ⬜ |

**Completion**: 55% (unchanged)

### 8. Flash Worker

| Check | Status |
|-------|--------|
| DeepSeek API real call verified | ✅ |
| flash_patch_worker / flash_failure_analyzer | ⬜ |
| Execution adapter real_run path | ⬜ (mock skeleton only) |

**Completion**: 20% (was 10%)

### 9. Pro Adjudication

| Check | Status |
|-------|--------|
| Adjudication pack schema | ⬜ |
| Decision output format | ⬜ |

**Completion**: 5% (unchanged)

### 10. Safety & Security

| Check | Status |
|-------|--------|
| Secrets blocking in PreToolUse | ✅ local / E2E pending |
| Destructive command guard | 🔧 |
| Bash command tiering | ⬜ |

**Completion**: 45% (was 30%)

### 11. Testing

| Check | Status |
|-------|--------|
| route_enforcer tests | ✅ (65 tests) |
| route_enforcer + local_route_committee targeted tests | ✅ (57 tests) |
| route_committee tests | ✅ (13 tests) |
| End-to-end dry-run | ⬜ |
| Real task dogfood | ⬜ |

**Completion**: 45% (was 40%)

### 12. Documentation

| Check | Status |
|-------|--------|
| PIPELINE_MODE_ROADMAP.md | ✅ |
| PIPELINE_MODE_STATUS.md | ✅ |
| PIPELINE_MODE_BACKLOG.md | ⬜ |
| User/dev guides | ⬜ |

**Completion**: 30% (was 25%)

---

## Phase Summary

```
Phase A (Hook Closure):   85% — main() + register + matchers + flash auth + artifacts
Phase B (Route Committee): 75% — env vars, prompt hardening, schema validator, and merge rules done
Phase C (AgentDB):          5% — not started
Phase D (Worker+Tool):     30% — artifact capture done, workers still v1
Phase E (Pro Adjudication):  5% — not started
Phase F (Safety+Obs):      45% — secrets/.env hook hard-deny integrated locally; E2E pending

Pipeline mode overall:     34% (was 32%)
```

## Shadow Route Status

| Metric | Value | Target |
|--------|-------|--------|
| Records | 664 | — |
| Match rate | 75.6% | ≥85% |
| Unknown rate | 45.6% | — |
| Critical misrouting | 7 | 0 |
| Privacy bypass | 0 | 0 ✅ |
| False cloud-on-secret | 0 | 0 ✅ |
| Warning gate | blocked | — |

## Worktree Status

- `tests/conftest.py` now uses a per-process pytest basetemp under the current working directory, with `LOCAL_LLM_PYTEST_TMP` as an explicit override. This fixes the Codex/Windows path-mapping failure where the old fixed `.local_llm_out/pytest-tmp` directory could not be removed.
- `.codex/config.toml` and `.codex/hooks.json` now use `python3` so Codex desktop/CLI do not depend on the unavailable `py -3` launcher or a PowerShell-only `python` shim.
- Real Codex CLI verification passed outside the sandbox: `codex doctor` overall OK, `codex mcp list` includes enabled `local-llm`, and zero12/Ollama handled a real `summarize-file` worker call.
- Targeted hook/committee tests pass under `python3`; `.pytest_cache` still reports a non-blocking permission warning in this environment. Do not use `--cache-clear` in the current mapped workspace because it tries to delete the old restricted cache directory.
- F1 full `tools/run_checks.py` reached 2900 passed / 1 skipped / 1 collection error; the remaining error is `tools/test_all_models.py::test_model_with_task` being collected as a pytest test without a `model` fixture.
- Codex/agent baseline candidates are present in the worktree: `.agents/skills/project-governance/SKILL.md`, `.agents/skills/task-bootstrap/SKILL.md`, `.codex/agents/*.toml`, and `.codex/hooks.json`.
- Local-only state is ignored: `.pytest_cache/` and `.claude/session-handoff-*.md`.
- No commit, push, tag, or release has been performed.

## Next Priority (ranked)

1. **A6**: E2E hook loop test in real Claude Code session.
2. **C1**: Task session directory structure stabilization.
3. **E1**: Adjudication input pack schema.
4. **F2/F3**: Destructive command guard and Bash command tiering.
7. **Push**: local commits to origin (blocked by release guard — needs debate review).
