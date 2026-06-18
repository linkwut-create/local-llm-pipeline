# Local Multi-Model Worker Rules for Codex

Codex may call `tools/local_llm_router.py` for read-only auxiliary work.
For broad cross-file tasks, start with task_bootstrap (see AGENTS.md).

## Controller Delegation Quick Reference (U-1)

**Core rule**: For non-trivial tasks, delegate read-only heavy work to local
models before editing. Use this checklist:

```
[ ] STEP 0: local_workflow_plan          — classify task type + risk (no LLM cost)
[ ] STEP 1: repo_map + find-related-files — orient in unfamiliar territory
[ ] STEP 2: summarize-file               — each key file > 200 lines before editing
[ ] STEP 3: generate-test-plan           — if new API/schema/parser/CLI/DB
[ ] STEP 4: review-diff (commit_gate)    — after edits, before commit (MUST)
[ ] STEP 5: debate-review-diff           — high-risk paths only (MUST for those)
[ ] STEP 6: draft-commit-message         — advisory, controller finalizes
```

**MUST delegate blocks commit. MAY skip: explanation-only, tiny typo, user says
no MCP, emergency.**

**Budget**: max 5 summarizes, 300s runtime, 10 model calls per task.
Stop on `ok=false`, timeout, or safety boundary.

**Responsibility**: Codex owns implementation plan, edits, test running, commit
message, and final answers. Local models own only read-only context collection,
summaries, test recommendations, and advisory review. Local models NEVER edit,
stage, commit, or push.

Full delegation contract: see AGENTS.md "Controller Delegation Contract (U-1)".

## Task Bootstrap (v0.11.0)

Before cross-file, cross-module, or unfamiliar-repo work:

```bash
python3 tools/task_bootstrap.py --project <PATH> --task "<DESC>" `
  --max-summaries 3 --budget 6000
```

See AGENTS.md for full workflow.

## Codex CLI on Windows

Use `codex.cmd` or `cmd /c codex ...` from PowerShell if script execution policy
blocks `codex.ps1`. This project-level Codex config uses `python3` because the
`py -3` launcher is not available in the current Codex desktop/CLI environment.

## Allowed Tasks

- summarize-file
- summarize-tree
- find-related-files
- extract-todos
- generate-test-plan
- generate-test-draft
- review-diff
- deep-code-review
- architecture-review
- risk-analysis
- logic-check
- failure-mode-analysis
- translate-text
- rewrite-text
- classify-test-failure

## Rules

- Worker output is advisory.
- Codex must verify important claims directly.
- Codex must run tests itself.
- Codex must inspect git diff itself.
- The worker must not modify source code.
- The worker must not read secrets.
- The worker must not handle auth, crypto, database migration, deployment,
  release, or final approval.

## Preferred Workflow

1. Run task_bootstrap for unfamiliar or broad tasks (bundled alternative covering orientation and understanding steps).
2. Use local worker to compress broad context.
3. Read the worker JSON output.
4. Read only the key files directly.
5. Implement changes.
6. Run tests.
7. Use worker for initial diff review.
8. Verify diff directly.

## Multi-Model Debate

Codex may use `tools/local_llm_debate.py` for multi-model cross-review.
Debate results are NOT final conclusions — Codex must verify all findings.

```bash
git diff | python3 tools/local_llm_debate.py review-diff --stdin
git diff | python3 tools/local_llm_debate.py review-diff --stdin --fast
python3 tools/local_llm_debate.py risk-analysis <path>
python3 tools/local_llm_debate.py architecture-review <path>
```

## MCP Integration (v0.11.0)

The pipeline exposes **13** source-non-mutating MCP tools via
`tools/local_llm_mcp_server.py`:

`local_check`, `local_summarize_file`, `local_summarize_tree`,
`local_generate_test_plan`, `local_review_diff`, `local_debate_review_diff`,
`local_parallel_review`, `local_draft_code`, `local_contextual_analyze`,
`local_repo_map`, `local_classify_test_failure`, `local_workflow_plan`,
`local_route_explain`.

MCP tools are source-non-mutating — output only to `.local_llm_out/`.

### Proactive Routing (v0.9.6)

- `local_summarize_file`: auto-selects profile based on file size and CJK ratio
- `local_generate_test_plan`: auto-selects profile based on definition count
  and complexity
- `local_review_diff`: non-commit-gate path uses quality escalation
- `local_debate_review_diff`: auto-decides 2 vs 3 rounds based on diff size
  and security patterns

### Profile Auto-Tuning

```bash
python3 tools/update_profiles_from_ollama.py --auto-tune         # show recommendations
python3 tools/update_profiles_from_ollama.py --auto-tune --apply # apply >20% improvements
```

### llama.cpp MTP Backend (zero12)

```bash
bash tools/start_llamacpp_mtp.sh           # start all 3 MTP servers
bash tools/start_llamacpp_mtp.sh --status  # check status
bash tools/start_llamacpp_mtp.sh --stop    # stop all servers
```

## Standard Commands

```bash
python3 tools/local_llm_check.py
python3 tools/local_llm_router.py summarize-file <path>
python3 tools/local_llm_router.py summarize-tree <path> --max-files 30
python3 tools/local_llm_router.py extract-todos <path>
python3 tools/local_llm_router.py generate-test-plan <path>
git diff | python3 tools/local_llm_router.py review-diff --stdin
python3 tools/local_llm_router.py risk-analysis <path>
```
