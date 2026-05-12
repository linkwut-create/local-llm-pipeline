# MCP Audit Design

## 1. Purpose

The MCP Audit system records and governs all MCP / local-model invocations across
the development lifecycle. It is a **development governance database**, not a
simple log.

### What it records

- Every MCP / local-model invocation (start, finish, failure)
- The purpose and result of each invocation
- Failures, blocks, test failures, and hook interceptions
- Whether MCP recommendations were accepted, rejected, or ignored
- How Claude Code resolved problems after MCP feedback
- Correlation to phase, task, commit, and test outcomes

### Why it exists

Without systematic audit, the MCP-assisted development process is opaque.
We cannot answer:

- Was the commit gate followed for this commit?
- How often do local model recommendations lead to actual changes?
- Which tools and models are most reliable?
- Were failures properly recovered or silently ignored?
- Did the Error Recovery Rule actually prevent a bad commit?

The audit system makes these questions answerable.

### Governance, not logging

This is not a log file. A log records events. A governance system records events
**and** enforces process. The distinction matters:

| Log | Governance |
|-----|------------|
| Records what happened | Records what happened AND whether it should have |
| Append-only, passive | Can block progress if process is violated |
| Human-readable | Queryable, statistical, correlational |
| Per-session, ephemeral | Cross-session, durable, project-scoped |

## 2. Scope

### Tools covered

All 7 MCP tools plus hook infrastructure:

- `local_check`
- `local_summarize_file`
- `local_summarize_tree`
- `local_generate_test_plan`
- `local_review_diff`
- `local_debate_review_diff`
- `local_draft_code`
- Commit gate / PreToolUse hook
- Error Recovery Rule
- PostToolUse hook (review state tracking)
- Stop hook (session summary)

### Project scenarios covered

| Scenario | What to record |
|----------|---------------|
| Database schema change | `local_review_diff` output, affected SQL files, migration safety assessment |
| Prompt injection defense | `local_debate_review_diff` output, safety boundary check result |
| Retrieval ranking change | `local_summarize_file` context, `local_review_diff` comparison |
| Accepted/rejected/gold status machine | Decision tracking: which recommendation, why accepted/rejected, post-fix state |
| UI safety change | `local_review_diff` + `local_debate_review_diff` (safety policy changes) |
| Test failure | Test name, failure output, MCP diagnosis, fix applied, re-run result |
| Release/freeze boundary | `local_check` → freeze review → `local_debate_review_diff` → tag |
| Documentation-only change | Was commit gate required? (No, but still recordable) |
| Commit gate blocking | What blocked it, what was the resolution, was it a false positive? |
| CLI bypass (manual `mcp local_review_diff`) | `invocation_source=cli`, `is_hooked=false`, still recorded |
| Direct subprocess call (bypass hooks) | Recordable only if audit wrapper is in the subprocess path |
| `--no-verify` commit bypass | Detected by hook, recorded as `commit_gate_bypassed` |
| Hook deregistration | Detected by `mcp_doctor.py`, recorded as `hook_health_check_failed` |
| Nested/hook-recursive calls | `debate_review_diff` → internal `review_diff` → nested trace |
| Partial tool output / truncation | `output_truncated=true`, `output_size_bytes` vs `expected_size_bytes` |

### Out of scope (for MCP-AUDIT-0 design)

- Actual implementation of any recording mechanism
- Database files, Python modules, CLI tools
- Hook modifications
- MCP server behavior changes
- Dashboard or visualization
- Automatic policy enforcement engine

## 3. Three-layer recording model

### Layer 1: Raw log layer

```
.mcp_audit/raw/{project}/{phase}/{timestamp}_{tool}.log
```

Stores:
- Claude Code output fragments relevant to the invocation
- MCP invocation raw JSON summaries (full response)
- stderr / traceback raw fragments (untruncated)
- Hook interception messages
- Commit gate block messages with full context

Properties:
- Append-only within each file
- Never queried directly — evidence layer only
- Size-capped per file (default 100KB, configurable)
- Retention policy applied at phase granularity
- Can be disabled per-project for sensitive work

### Layer 2: JSONL event layer (MVP — implemented first)

```
.mcp_audit/events.jsonl         — all invocations
.mcp_audit/failures.jsonl       — failures only (denormalized for fast query)
.mcp_audit/recommendations.jsonl — recommendations with adoption status
.mcp_audit/phase_audits.jsonl   — per-phase summary records
```

Properties:
- Append-only, one JSON object per line
- Each record is self-contained (denormalized enough for grep/jq)
- Minimal viable implementation — works before SQLite exists
- Human-readable with `cat`, queryable with `jq`
- Sorted by `created_at` within each file

### Layer 3: SQLite audit DB layer

```
.mcp_audit/mcp_audit.db
```

Properties:
- Built from JSONL via migration script (MCP-AUDIT-2)
- Used for cross-phase queries, statistics, trend analysis
- Indexed on `project_name`, `phase_id`, `tool_name`, `created_at`
- Not the primary recording target — JSONL is the system of record
- Schema designed in this document (Section 9), not implemented yet

### Layer flow

```
MCP invocation
    │
    ├── Raw fragments → .mcp_audit/raw/{project}/{phase}/{timestamp}.log
    │
    ├── Structured event → .mcp_audit/events.jsonl
    │
    ├── (if failure) → .mcp_audit/failures.jsonl
    │
    ├── (if recommendation) → .mcp_audit/recommendations.jsonl
    │
    └── (at phase end) → .mcp_audit/phase_audits.jsonl
                            │
                            └── (MCP-AUDIT-2) → .mcp_audit/mcp_audit.db
```

## 4. Event types

| event_type | Description | Triggers record in |
|------------|-------------|-------------------|
| `mcp_invocation_started` | An MCP tool call began | events.jsonl |
| `mcp_invocation_finished` | An MCP tool call completed successfully | events.jsonl |
| `mcp_invocation_failed` | An MCP tool call failed (timeout, error, bad output) | events.jsonl, failures.jsonl |
| `recommendation_created` | MCP review/debate produced a recommendation | events.jsonl, recommendations.jsonl |
| `recommendation_accepted` | Controller accepted and applied the recommendation | recommendations.jsonl |
| `recommendation_rejected` | Controller explicitly rejected the recommendation | recommendations.jsonl |
| `recommendation_ignored` | Controller neither accepted nor rejected (timeout, context shift) | recommendations.jsonl |
| `test_failed` | A test run failed after MCP-reviewed changes | failures.jsonl |
| `test_passed` | A test run passed after MCP-reviewed changes | events.jsonl |
| `commit_gate_blocked` | Commit gate prevented a commit (missing review) | events.jsonl, failures.jsonl |
| `commit_gate_bypassed` | Commit proceeded without gate (--no-verify, hook disabled) | failures.jsonl |
| `staged_review_passed` | Staged diff review completed successfully | events.jsonl |
| `debate_review_warning` | Debate review found issues requiring controller attention | events.jsonl |
| `error_recovery_triggered` | Error Recovery Rule activated (retry, fallback, escalation) | events.jsonl, failures.jsonl |
| `fix_applied` | A fix was applied in response to MCP feedback | events.jsonl |
| `phase_audit_completed` | Phase-end audit summary generated | phase_audits.jsonl |
| `hook_health_check_failed` | `mcp_doctor.py` or hook self-check detected an issue | failures.jsonl |
| `tool_version_changed` | A tool's version changed (potential drift) | events.jsonl |
| `nested_invocation` | A tool called another tool internally (e.g., debate → review) | events.jsonl |

### Event type state machine

```
mcp_invocation_started
    │
    ├── ok=true ──→ mcp_invocation_finished
    │                   │
    │                   ├── has recommendation ──→ recommendation_created
    │                   │                              │
    │                   │                              ├── accepted ──→ fix_applied
    │                   │                              ├── rejected
    │                   │                              └── ignored
    │                   │
    │                   └── no recommendation ──→ (end)
    │
    ├── ok=false ──→ mcp_invocation_failed
    │                    │
    │                    ├── Error Recovery Rule ──→ error_recovery_triggered
    │                    │                              │
    │                    │                              ├── resolved ──→ mcp_invocation_finished
    │                    │                              └── unresolved ──→ (blocked)
    │                    │
    │                    └── commit gate ──→ commit_gate_blocked
    │
    └── timeout ──→ mcp_invocation_failed
```

## 5. Task types

| task_type | Description | Default profile |
|-----------|-------------|-----------------|
| `environment_check` | `local_check` — verify toolchain availability | (no LLM) |
| `file_summary` | `local_summarize_file` — summarize a file | `fast_summary` |
| `tree_summary` | `local_summarize_tree` — summarize a directory | `fast_summary` |
| `test_plan` | `local_generate_test_plan` — generate test plan | `code_worker` |
| `diff_review` | `local_review_diff` — review code changes | `commit_reviewer` |
| `debate_review` | `local_debate_review_diff` — multi-model cross-review | fast mode (2 rounds) |
| `commit_gate` | PreToolUse hook blocks commit until review done | `commit_reviewer` |
| `code_draft` | `local_draft_code` — draft fix/feature/refactor | `code_worker` |
| `error_diagnosis` | MCP-based error analysis after a failure | `code_worker` or `reasoning_checker` |
| `phase_freeze_review` | Pre-freeze comprehensive review | `diff_reviewer` or `deep_reviewer` |
| `release_review` | Pre-release audit | `release_auditor` |
| `documentation_review` | Review of docs-only changes | `fast_summary` (lighter than commit gate) |
| `hook_health_check` | `mcp_doctor.py` diagnostic run | (no LLM) |
| `debate_nested_review` | Internal `local_review_diff` triggered by debate | `diff_reviewer` |

## 6. Failure taxonomy

Each `failure_type` includes: trigger conditions, required fields, whether it requires
Error Recovery Rule, and whether it blocks commit.

### tool_failed

- **Trigger**: MCP tool returned `ok=false`
- **Required fields**: `tool_name`, `error_type`, `error_message`, `exit_code`, `stderr_summary`
- **Error Recovery Rule**: Yes — retry once with same model, then escalate to fallback model
- **Blocks commit**: Yes, if the tool is `local_review_diff` with `commit_gate=true`

### model_timeout

- **Trigger**: LLM call exceeded timeout (default 300s for MCP, configurable)
- **Required fields**: `timeout_seconds`, `model_name`, `input_size_chars`
- **Error Recovery Rule**: Yes — retry with smaller input (truncate), or faster model
- **Blocks commit**: Yes, if the timed-out call was a commit gate review

### model_bad_output

- **Trigger**: Model returned unparseable JSON, empty output, or `confidence=low`
- **Required fields**: `output_preview` (first 500 chars), `parse_error`, `confidence`
- **Error Recovery Rule**: Yes — escalate to next stronger profile
- **Blocks commit**: Yes, if from commit gate or debate review

### model_unavailable

- **Trigger**: Ollama API unreachable, model not found, or GPU OOM
- **Required fields**: `base_url`, `model_name`, `http_status`, `connection_error`
- **Error Recovery Rule**: Yes — try fallback model, then report environment error
- **Blocks commit**: Yes — cannot proceed without review capacity

### commit_gate_blocked

- **Trigger**: PreToolUse hook blocked `git commit` because no prior `local_review_diff`
- **Required fields**: `blocked_command`, `missing_review_for_diff`, `session_mcp_calls`
- **Error Recovery Rule**: N/A — the block IS the recovery. Controller must run review.
- **Blocks commit**: Yes — this is the block itself

### commit_gate_bypassed

- **Trigger**: Commit succeeded despite gate (--no-verify, hook disabled, hook deregistered)
- **Required fields**: `bypass_method`, `commit_hash`, `was_reviewed_before_bypass`
- **Error Recovery Rule**: Yes — flag for post-commit mandatory review
- **Blocks commit**: No (already committed), but records a process violation

### test_failed

- **Trigger**: `pytest` or project test suite returned non-zero after MCP-reviewed changes
- **Required fields**: `test_command`, `failed_test_count`, `failed_test_names`, `test_output_path`
- **Error Recovery Rule**: Yes — MCP error diagnosis → fix → re-test
- **Blocks commit**: Yes — test failure after review means review was insufficient

### diff_review_blocked

- **Trigger**: `local_review_diff` returned `ok=false` or `error` non-null
- **Required fields**: `diff_size_chars`, `review_error`, `uncertain_points`
- **Error Recovery Rule**: Yes — escalate to `diff_reviewer` or `debate_review_diff`
- **Blocks commit**: Yes — per MCP prohibition rules, must not commit without passing review

### debate_review_warning

- **Trigger**: `local_debate_review_diff` found issues classified as `disputed` or `controller_must_verify`
- **Required fields**: `finding_count`, `disputed_count`, `controller_must_verify_count`, `finding_summary`
- **Error Recovery Rule**: No — debate warnings require controller judgment, not automatic fix
- **Blocks commit**: No (advisory), but controller must document decision

### repeated_error_triggered

- **Trigger**: Same tool+model+error_type occurred N times in the same phase (default N=3)
- **Required fields**: `repeat_count`, `first_occurrence_id`, `previous_fix_attempted`
- **Error Recovery Rule**: Yes — escalate to higher-level diagnosis (debate review or manual)
- **Blocks commit**: Yes — repeated error signals systemic issue

### environment_error

- **Trigger**: Python, Ollama, or filesystem environment check failed
- **Required fields**: `check_name`, `check_detail`, `affected_tools`
- **Error Recovery Rule**: Yes — run `local_check`, fix environment, re-verify
- **Blocks commit**: Depends — if review tools are unavailable, yes

### dependency_error

- **Trigger**: Missing Python package (`requests`, etc.) or wrong version
- **Required fields**: `package_name`, `required_version`, `installed_version`
- **Error Recovery Rule**: Yes — install missing dependency, re-run check
- **Blocks commit**: If it prevents MCP tools from running, yes

### path_error

- **Trigger**: File not found, symlink broken, path blocked by security policy
- **Required fields**: `requested_path`, `resolved_path`, `block_reason`
- **Error Recovery Rule**: Yes — resolve path, verify file exists, re-run
- **Blocks commit**: If the missing file is required for review, yes

### permission_error

- **Trigger**: Cannot write to `.local_llm_out/` or `.mcp_audit/`
- **Required fields**: `target_path`, `permission_error`, `current_user`
- **Error Recovery Rule**: Yes — fix permissions, create directory, re-run
- **Blocks commit**: If audit records cannot be written, yes

### git_state_error

- **Trigger**: Detached HEAD, rebase in progress, merge conflict
- **Required fields**: `git_state`, `branch_name`, `detached_head_commit`
- **Error Recovery Rule**: No — requires manual git state resolution
- **Blocks commit**: Yes — cannot commit in broken git state

### dirty_worktree_error

- **Trigger**: Uncommitted changes detected when clean worktree expected
- **Required fields**: `dirty_files`, `dirty_file_count`
- **Error Recovery Rule**: No — controller must decide to commit or clean
- **Blocks commit**: No (advisory), but recorded for audit

### user_override

- **Trigger**: Controller explicitly overrode an MCP recommendation or block
- **Required fields**: `override_reason`, `overridden_event_id`, `override_scope`
- **Error Recovery Rule**: No — user override is intentional
- **Blocks commit**: No — user override allows progress

### recommendation_rejected

- **Trigger**: Controller explicitly rejected an MCP recommendation
- **Required fields**: `recommendation_id`, `rejection_reason`, `alternative_action`
- **Error Recovery Rule**: No — rejection is a valid decision
- **Blocks commit**: No — but the rejection must be recorded

### fixed_after_mcp

- **Trigger**: A failure was fixed after MCP diagnosis
- **Required fields**: `original_failure_id`, `fix_description`, `fix_commit`, `verification_result`
- **Error Recovery Rule**: N/A — this IS the recovery result
- **Blocks commit**: No — fix enables commit

### unresolved_failure

- **Trigger**: A failure was NOT resolved after Error Recovery Rule exhausted
- **Required fields**: `failure_id`, `recovery_attempts`, `last_error`, `escalation_target`
- **Error Recovery Rule**: Yes — escalate to manual intervention
- **Blocks commit**: Yes — unresolved failure means process cannot continue safely

### hook_health_check_failed

- **Trigger**: `mcp_doctor.py` detected hook misconfiguration or deregistration
- **Required fields**: `failed_checks`, `hook_file_exists`, `hook_registered`, `config_valid`
- **Error Recovery Rule**: Yes — re-run installer or re-register hooks
- **Blocks commit**: Yes — hooks are required for commit gate enforcement

### tool_version_drift

- **Trigger**: Tool version changed between invocations without explicit upgrade
- **Required fields**: `tool_name`, `old_version`, `new_version`, `version_source`
- **Error Recovery Rule**: No — advisory only, but recorded for reliability analysis
- **Blocks commit**: No — but flags potential misattribution of failures

### nested_invocation_timeout

- **Trigger**: A tool called within another tool (e.g., debate → review) timed out
- **Required fields**: `parent_tool`, `child_tool`, `nesting_depth`, `parent_invocation_id`
- **Error Recovery Rule**: Yes — propagate timeout to parent, parent decides escalation
- **Blocks commit**: Depends on parent tool's gate status

## 7. Required fields

### mcp_invocation_log

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique invocation identifier |
| `created_at` | ISO 8601 | When the invocation started |
| `finished_at` | ISO 8601 | When the invocation completed (null if in progress) |
| `project_name` | string | Short project identifier (e.g., `local-llm-pipeline`, `local-translator-agent`) |
| `project_path` | string | Absolute path to project root |
| `phase_id` | string | Development phase (e.g., `MCP-AUDIT-0`, `TM-1B`) |
| `task_id` | string | Task within phase (e.g., `3`, `risk-analysis`) |
| `tool_name` | string | MCP tool name (e.g., `local_review_diff`) |
| `task_type` | enum | From Section 5 task type list |
| `purpose` | string | Why this invocation was made (1-2 sentence summary) |
| `input_summary` | string | Summary of input (file paths, diff size, prompt hash) |
| `output_summary` | string | Summary of output (ok/fail, confidence, finding count) |
| `files_involved` | JSON array | List of file paths this invocation touched |
| `tests_involved` | JSON array | List of test names this invocation relates to |
| `command` | string | The exact CLI command or MCP tool call |
| `result_status` | enum | `success`, `failed`, `timeout`, `blocked`, `partial` |
| `blocking` | boolean | Whether this invocation was a commit gate (`commit_gate=true`) |
| `commit_before` | string | Git HEAD hash before invocation |
| `commit_after` | string | Git HEAD hash after invocation (null if no commit resulted) |
| `raw_log_path` | string | Relative path to raw log file (null if no raw log) |
| `linked_failure_id` | UUID | Reference to `mcp_failure_log.id` (null if no failure) |
| `invocation_source` | enum | `hook`, `cli`, `mcp_client`, `internal`, `unknown` |
| `is_hooked` | boolean | Whether hooks observed this invocation |
| `trace_id` | UUID | Distributed trace ID for correlating nested calls |
| `session_id` | UUID | Session identifier (matches hook session_id) |
| `tool_version` | string | Version of the tool being invoked |
| `model_name` | string | LLM model used |
| `profile_name` | string | Router profile used |
| `confidence` | enum | `high`, `medium`, `low`, `unknown` |
| `output_truncated` | boolean | Whether model output was truncated |
| `output_size_bytes` | integer | Size of model output in bytes |
| `input_size_bytes` | integer | Size of model input in bytes |
| `latency_ms` | integer | Wall-clock duration of the invocation |
| `retry_count` | integer | Number of retries before this record |
| `notes` | string | Free-text notes from controller |

### mcp_failure_log

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique failure identifier |
| `created_at` | ISO 8601 | When the failure was recorded |
| `project_name` | string | Short project identifier |
| `phase_id` | string | Development phase |
| `task_id` | string | Task within phase |
| `failure_type` | enum | From Section 6 failure taxonomy |
| `severity` | enum | `critical`, `high`, `medium`, `low` |
| `tool_name` | string | Which tool failed |
| `model_name` | string | Which model was in use |
| `command` | string | The command that triggered the failure |
| `exit_code` | integer | Process exit code (null if timeout or signal) |
| `stderr_summary` | string | First 500 chars of stderr, redacted |
| `traceback_summary` | string | First 500 chars of traceback, redacted |
| `files_involved` | JSON array | Files related to the failure |
| `tests_involved` | JSON array | Tests related to the failure |
| `mcp_diagnosis` | string | MCP self-diagnosis of the failure (if available) |
| `possible_causes` | JSON array | List of possible root causes |
| `recommended_fixes` | JSON array | List of recommended fixes |
| `fix_applied` | string | Description of the fix applied |
| `fix_commit` | string | Commit hash of the fix (null if not yet committed) |
| `fix_result` | enum | `fixed`, `workaround`, `escalated`, `unresolved` |
| `resolved` | boolean | Whether the failure is fully resolved |
| `recovery_rule_applied` | boolean | Whether Error Recovery Rule was triggered |
| `recovery_attempts` | integer | Number of recovery attempts |
| `recovery_status` | enum | `none`, `in_progress`, `success`, `failed`, `exhausted` |
| `commit_before` | string | Git HEAD before failure |
| `commit_after` | string | Git HEAD after fix (null if unresolved) |
| `raw_log_path` | string | Path to raw failure log |
| `linked_invocation_id` | UUID | Reference to `mcp_invocation_log.id` |
| `notes` | string | Controller notes on the failure |

### mcp_recommendation_log

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique recommendation identifier |
| `invocation_id` | UUID | Reference to `mcp_invocation_log.id` |
| `tool_name` | string | Which tool produced the recommendation |
| `recommendation` | string | The recommendation text (redacted if needed) |
| `severity` | enum | `critical`, `high`, `medium`, `low` |
| `category` | string | Category tag (e.g., `security`, `performance`, `bug`, `style`, `architecture`) |
| `decision` | enum | `accepted`, `rejected`, `partially_accepted`, `ignored`, `overridden_by_user`, `obsolete_after_fix` |
| `decision_reason` | string | Why this decision was made |
| `applied_change` | string | Summary of the change applied (if accepted) |
| `applied_commit` | string | Commit hash where change was applied |
| `related_files` | JSON array | Files affected by this recommendation |
| `related_tests` | JSON array | Tests affected by this recommendation |
| `created_at` | ISO 8601 | When the recommendation was created |
| `decided_at` | ISO 8601 | When the decision was made |
| `finding_classification` | enum | `high_confidence`, `candidate`, `disputed`, `controller_must_verify` |
| `debate_round` | integer | Which debate round produced this (1-3, null for non-debate) |
| `notes` | string | Controller notes |

### mcp_phase_audit

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique phase audit identifier |
| `project_name` | string | Short project identifier |
| `phase_id` | string | Development phase |
| `started_at` | ISO 8601 | When the phase began |
| `finished_at` | ISO 8601 | When the phase completed |
| `invocation_count` | integer | Total MCP invocations in this phase |
| `failure_count` | integer | Total failures in this phase |
| `blocked_commit_count` | integer | Times commit gate blocked a commit |
| `bypassed_commit_count` | integer | Times commit gate was bypassed |
| `accepted_recommendation_count` | integer | Recommendations accepted |
| `rejected_recommendation_count` | integer | Recommendations rejected |
| `ignored_recommendation_count` | integer | Recommendations ignored |
| `tests_run` | integer | Total test cases executed |
| `tests_failed` | integer | Test cases that failed |
| `tests_passed` | integer | Test cases that passed |
| `final_test_result` | enum | `all_passed`, `some_failed`, `not_run`, `not_applicable` |
| `commit_before` | string | Git HEAD at phase start |
| `commit_after` | string | Git HEAD at phase end |
| `final_status` | enum | `completed`, `blocked`, `failed`, `abandoned` |
| `summary` | string | Phase summary (from controller or auto-generated) |
| `next_recommendation` | string | Recommendation for the next phase |

## 8. JSONL examples

### Example 1: successful local_review_diff

```json
{
  "event_type": "mcp_invocation_finished",
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "created_at": "2026-05-13T10:15:30.123456+00:00",
  "finished_at": "2026-05-13T10:15:58.654321+00:00",
  "project_name": "local-translator-agent",
  "project_path": "/home/dev/local-translator-agent",
  "phase_id": "TM-1B",
  "task_id": "4",
  "tool_name": "local_review_diff",
  "task_type": "diff_review",
  "purpose": "Pre-commit review: FTS5 fuzzy search + similar translation UI changes",
  "input_summary": "Diff 342 lines across 3 files: fts5_search.py, templates/similar.html, test_fts5.py",
  "output_summary": "ok=true, confidence=medium, 2 findings (both high_confidence), no uncertain_points",
  "files_involved": ["src/fts5_search.py", "templates/similar.html", "tests/test_fts5.py"],
  "tests_involved": ["test_fts5_search_basic", "test_fts5_search_unicode", "test_similar_ui_rendering"],
  "command": "mcp__local-llm__local_review_diff commit_gate=true",
  "result_status": "success",
  "blocking": true,
  "commit_before": "abc123def456",
  "commit_after": null,
  "raw_log_path": ".mcp_audit/raw/local-translator-agent/TM-1B/20260513_101530_review_diff.log",
  "linked_failure_id": null,
  "invocation_source": "mcp_client",
  "is_hooked": true,
  "trace_id": "11111111-2222-3333-4444-555555555555",
  "session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "tool_version": "0.7.0",
  "model_name": "qwen3-coder:30b",
  "profile_name": "commit_reviewer",
  "confidence": "medium",
  "output_truncated": false,
  "output_size_bytes": 8456,
  "input_size_bytes": 28500,
  "latency_ms": 28123,
  "retry_count": 0,
  "notes": ""
}
```

### Example 2: commit_gate_blocked

```json
{
  "event_type": "commit_gate_blocked",
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "created_at": "2026-05-13T11:20:05.000000+00:00",
  "project_name": "local-translator-agent",
  "project_path": "/home/dev/local-translator-agent",
  "phase_id": "TM-1B",
  "task_id": "5",
  "tool_name": "commit_gate",
  "task_type": "commit_gate",
  "purpose": "PreToolUse hook intercepted git commit",
  "input_summary": "Commit attempted: 'fix: correct FTS5 LIKE escape for CJK queries'",
  "output_summary": "BLOCKED: no prior local_review_diff for current diff. Run MCP review first.",
  "files_involved": ["src/fts5_search.py"],
  "tests_involved": [],
  "command": "git commit -m 'fix: correct FTS5 LIKE escape for CJK queries'",
  "result_status": "blocked",
  "blocking": true,
  "commit_before": "abc123def456",
  "commit_after": null,
  "raw_log_path": ".mcp_audit/raw/local-translator-agent/TM-1B/20260513_112005_commit_gate_blocked.log",
  "linked_failure_id": null,
  "invocation_source": "hook",
  "is_hooked": true,
  "trace_id": "22222222-3333-4444-5555-666666666666",
  "session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "tool_version": "0.7.0",
  "model_name": null,
  "profile_name": null,
  "confidence": null,
  "output_truncated": false,
  "output_size_bytes": 0,
  "input_size_bytes": 0,
  "latency_ms": 5,
  "retry_count": 0,
  "notes": "Controller then ran local_review_diff(commit_gate=true), which passed. Commit proceeded as def789ab."
}
```

### Example 3: test_failed then fixed_after_mcp

```json
{
  "event_type": "test_failed",
  "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "created_at": "2026-05-13T12:05:00.000000+00:00",
  "project_name": "local-llm-pipeline",
  "project_path": "/home/dev/local-llm-pipeline",
  "phase_id": "MCP-3F",
  "task_id": "2",
  "failure_type": "test_failed",
  "severity": "high",
  "tool_name": "local_review_diff",
  "model_name": "qwen3-coder:30b",
  "command": "python -m pytest tests/test_mcp_gate.py -q",
  "exit_code": 1,
  "stderr_summary": "FAILED tests/test_mcp_gate.py::test_session_start_clears_state - AssertionError: mcp_calls not empty after SessionStart",
  "traceback_summary": "test_session_start_clears_state: assert len(state['mcp_calls']) == 0, got 3",
  "files_involved": ["tools/claude_hooks/mcp_gate.py", "tests/test_mcp_gate.py"],
  "tests_involved": ["test_session_start_clears_state"],
  "mcp_diagnosis": "SessionStart handler was not clearing mcp_calls dict in place; it reassigned a new dict but callers held stale reference.",
  "possible_causes": ["Mutable state not cleared in place", "Dict reassignment instead of .clear()"],
  "recommended_fixes": ["Use dict.clear() instead of reassignment in SessionStart handler"],
  "fix_applied": "Changed `state['mcp_calls'] = {}` to `state['mcp_calls'].clear()` in SessionStart handler",
  "fix_commit": "def789ab0123",
  "fix_result": "fixed",
  "resolved": true,
  "recovery_rule_applied": true,
  "recovery_attempts": 1,
  "recovery_status": "success",
  "commit_before": "abc123def456",
  "commit_after": "def789ab0123",
  "raw_log_path": ".mcp_audit/raw/local-llm-pipeline/MCP-3F/20260513_120500_test_failed.log",
  "linked_invocation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "notes": "Test re-ran after fix: all passing."
}
```

### Example 4: recommendation_rejected due to phase boundary

```json
{
  "event_type": "recommendation_rejected",
  "id": "d4e5f6a7-b8c9-0123-defa-123456789013",
  "invocation_id": "e5f6a7b8-c9d0-1234-efab-123456789014",
  "tool_name": "local_debate_review_diff",
  "recommendation": "Consider adding retry with exponential backoff for Ollama API calls in local_llm_worker.py. Currently retries are fixed 1s interval, which may not be sufficient under heavy GPU load.",
  "severity": "medium",
  "category": "reliability",
  "decision": "rejected",
  "decision_reason": "Phase boundary: TM-1B is frozen. This improvement belongs in TM-2A (resilience phase). Noted for next phase planning.",
  "applied_change": null,
  "applied_commit": null,
  "related_files": ["tools/local_llm_worker.py"],
  "related_tests": [],
  "created_at": "2026-05-13T14:00:00.000000+00:00",
  "decided_at": "2026-05-13T14:01:30.000000+00:00",
  "finding_classification": "candidate",
  "debate_round": 2,
  "notes": "Deferred to TM-2A. Added to phase planning doc."
}
```

## 9. SQLite schema draft

> NOTE: These schemas are design drafts only. No database is created in MCP-AUDIT-0.
> Implementation target: MCP-AUDIT-2.

```sql
-- Core invocation table
CREATE TABLE IF NOT EXISTS mcp_invocation_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    project_name TEXT NOT NULL,
    project_path TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    task_id TEXT,
    tool_name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    purpose TEXT,
    input_summary TEXT,
    output_summary TEXT,
    files_involved TEXT,        -- JSON array
    tests_involved TEXT,        -- JSON array
    command TEXT,
    result_status TEXT NOT NULL CHECK (result_status IN ('success','failed','timeout','blocked','partial')),
    blocking INTEGER NOT NULL DEFAULT 0,
    commit_before TEXT,
    commit_after TEXT,
    raw_log_path TEXT,
    linked_failure_id TEXT,
    invocation_source TEXT NOT NULL DEFAULT 'unknown',
    is_hooked INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT,
    session_id TEXT,
    tool_version TEXT,
    model_name TEXT,
    profile_name TEXT,
    confidence TEXT CHECK (confidence IN ('high','medium','low','unknown')),
    output_truncated INTEGER NOT NULL DEFAULT 0,
    output_size_bytes INTEGER,
    input_size_bytes INTEGER,
    latency_ms INTEGER,
    retry_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    FOREIGN KEY (linked_failure_id) REFERENCES mcp_failure_log(id)
);

CREATE INDEX idx_invocation_project ON mcp_invocation_log(project_name, phase_id);
CREATE INDEX idx_invocation_tool ON mcp_invocation_log(tool_name, created_at);
CREATE INDEX idx_invocation_status ON mcp_invocation_log(result_status, created_at);
CREATE INDEX idx_invocation_commit ON mcp_invocation_log(commit_before, commit_after);
CREATE INDEX idx_invocation_trace ON mcp_invocation_log(trace_id);
CREATE INDEX idx_invocation_session ON mcp_invocation_log(session_id);

-- Failure table
CREATE TABLE IF NOT EXISTS mcp_failure_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    project_name TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    task_id TEXT,
    failure_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    tool_name TEXT,
    model_name TEXT,
    command TEXT,
    exit_code INTEGER,
    stderr_summary TEXT,
    traceback_summary TEXT,
    files_involved TEXT,        -- JSON array
    tests_involved TEXT,        -- JSON array
    mcp_diagnosis TEXT,
    possible_causes TEXT,       -- JSON array
    recommended_fixes TEXT,     -- JSON array
    fix_applied TEXT,
    fix_commit TEXT,
    fix_result TEXT CHECK (fix_result IN ('fixed','workaround','escalated','unresolved')),
    resolved INTEGER NOT NULL DEFAULT 0,
    recovery_rule_applied INTEGER NOT NULL DEFAULT 0,
    recovery_attempts INTEGER NOT NULL DEFAULT 0,
    recovery_status TEXT CHECK (recovery_status IN ('none','in_progress','success','failed','exhausted')),
    commit_before TEXT,
    commit_after TEXT,
    raw_log_path TEXT,
    linked_invocation_id TEXT,
    notes TEXT,
    FOREIGN KEY (linked_invocation_id) REFERENCES mcp_invocation_log(id)
);

CREATE INDEX idx_failure_project ON mcp_failure_log(project_name, phase_id);
CREATE INDEX idx_failure_type ON mcp_failure_log(failure_type, created_at);
CREATE INDEX idx_failure_severity ON mcp_failure_log(severity, resolved);
CREATE INDEX idx_failure_recovery ON mcp_failure_log(recovery_status, created_at);

-- Recommendation table
CREATE TABLE IF NOT EXISTS mcp_recommendation_log (
    id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL,
    tool_name TEXT,
    recommendation TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    category TEXT,
    decision TEXT CHECK (decision IN ('accepted','rejected','partially_accepted','ignored','overridden_by_user','obsolete_after_fix')),
    decision_reason TEXT,
    applied_change TEXT,
    applied_commit TEXT,
    related_files TEXT,         -- JSON array
    related_tests TEXT,         -- JSON array
    created_at TEXT NOT NULL,
    decided_at TEXT,
    finding_classification TEXT CHECK (finding_classification IN ('high_confidence','candidate','disputed','controller_must_verify')),
    debate_round INTEGER,
    notes TEXT,
    FOREIGN KEY (invocation_id) REFERENCES mcp_invocation_log(id)
);

CREATE INDEX idx_rec_invocation ON mcp_recommendation_log(invocation_id);
CREATE INDEX idx_rec_decision ON mcp_recommendation_log(decision, created_at);
CREATE INDEX idx_rec_severity ON mcp_recommendation_log(severity, decision);

-- Phase audit table
CREATE TABLE IF NOT EXISTS mcp_phase_audit (
    id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    blocked_commit_count INTEGER NOT NULL DEFAULT 0,
    bypassed_commit_count INTEGER NOT NULL DEFAULT 0,
    accepted_recommendation_count INTEGER NOT NULL DEFAULT 0,
    rejected_recommendation_count INTEGER NOT NULL DEFAULT 0,
    ignored_recommendation_count INTEGER NOT NULL DEFAULT 0,
    tests_run INTEGER NOT NULL DEFAULT 0,
    tests_failed INTEGER NOT NULL DEFAULT 0,
    tests_passed INTEGER NOT NULL DEFAULT 0,
    final_test_result TEXT CHECK (final_test_result IN ('all_passed','some_failed','not_run','not_applicable')),
    commit_before TEXT,
    commit_after TEXT,
    final_status TEXT CHECK (final_status IN ('completed','blocked','failed','abandoned')),
    summary TEXT,
    next_recommendation TEXT
);

CREATE INDEX idx_phase_project ON mcp_phase_audit(project_name);
CREATE INDEX idx_phase_status ON mcp_phase_audit(final_status, finished_at);

-- Tool reliability view (for MCP-AUDIT-3+)
-- Not a table; created as a view for query convenience
-- CREATE VIEW tool_reliability AS
-- SELECT
--     tool_name,
--     model_name,
--     COUNT(*) AS total_calls,
--     SUM(CASE WHEN result_status = 'success' THEN 1 ELSE 0 END) AS success_count,
--     SUM(CASE WHEN result_status = 'failed' THEN 1 ELSE 0 END) AS failure_count,
--     SUM(CASE WHEN result_status = 'timeout' THEN 1 ELSE 0 END) AS timeout_count,
--     AVG(latency_ms) AS avg_latency_ms,
--     AVG(CASE WHEN confidence = 'high' THEN 1.0 WHEN confidence = 'medium' THEN 0.5 ELSE 0.0 END) AS avg_confidence_score
-- FROM mcp_invocation_log
-- WHERE model_name IS NOT NULL
-- GROUP BY tool_name, model_name;
```

## 10. Phase audit report format

Each phase produces a markdown report at:

```
docs/mcp-audit/{project}/{phase}.md
```

### Report template

```markdown
# MCP Phase Audit: {phase_id}

- **Project**: {project_name}
- **Phase**: {phase_id}
- **Started**: {started_at}
- **Finished**: {finished_at}
- **Duration**: {duration_human_readable}
- **Commit before**: `{commit_before}`
- **Commit after**: `{commit_after}`
- **Final status**: {final_status}

## MCP Invocations

| # | Tool | Purpose | Model | Result | Latency |
|---|------|---------|-------|--------|---------|
| 1 | local_check | Session start | (no LLM) | success | 2s |
| 2 | local_summarize_file | Understand fts5_search.py | gemma4:e4b | success | 8s |
| 3 | local_review_diff | Pre-commit gate | qwen3-coder:30b | success | 28s |
| ... | ... | ... | ... | ... | ... |

**Total**: {invocation_count} invocations

## MCP Tools Used

| Tool | Count | Success | Failed | Avg Latency |
|------|-------|---------|--------|-------------|
| local_check | 2 | 2 | 0 | 2s |
| local_summarize_file | 3 | 3 | 0 | 9s |
| local_review_diff | 2 | 2 | 0 | 27s |
| local_debate_review_diff | 1 | 1 | 0 | 156s |

## Failures

| # | Type | Severity | Tool | Summary | Resolved |
|---|------|----------|------|---------|----------|
| 1 | commit_gate_blocked | low | commit_gate | Blocked commit before review | yes |
| 2 | test_failed | high | local_review_diff | test_session_start_clears_state | yes (fixed) |

**Total**: {failure_count} failures, {resolved_count} resolved

## Commit Gate Activity

- **Blocks**: {blocked_commit_count}
- **Bypasses**: {bypassed_commit_count}

## Test Results

- **Tests run**: {tests_run}
- **Passed**: {tests_passed}
- **Failed**: {tests_failed}
- **Result**: {final_test_result}

## Recommendations

| # | Source | Severity | Recommendation (summary) | Decision | Reason |
|---|--------|----------|--------------------------|----------|--------|
| 1 | local_review_diff | medium | Fix docstring typo | accepted | Applied in commit abc123 |
| 2 | local_debate_review_diff | medium | Add retry backoff | rejected | Deferred to next phase |

### Adoption Summary

- **Accepted**: {accepted_recommendation_count}
- **Rejected**: {rejected_recommendation_count}
- **Ignored**: {ignored_recommendation_count}
- **Adoption rate**: {adoption_rate}%

## User Overrides

(none, or list each override with reason)

## Final Status

**{final_status}** — {summary}

## Next Recommendation

{next_recommendation}
```

## 11. Query requirements

Future CLI (MCP-AUDIT-4) must support these queries:

### Summary by phase

```bash
python -m mcp_audit summary --phase TM-1B.5
python -m mcp_audit summary --project local-translator-agent
python -m mcp_audit summary --phase MCP-AUDIT-0 --json
```

Output: invocation count, failure count, recommendation adoption rate, test result, duration.

### Failures by project

```bash
python -m mcp_audit failures --project local-translator-agent
python -m mcp_audit failures --project local-translator-agent --unresolved
python -m mcp_audit failures --project local-llm-pipeline --severity critical
```

Output: table of failures with type, severity, resolution status, linked commits.

### Blocked commits

```bash
python -m mcp_audit commits --blocked
python -m mcp_audit commits --blocked --phase TM-1B
python -m mcp_audit commits --bypassed
```

Output: list of blocked/bypassed commits with timestamps, reasons, resolutions.

### Rejected recommendations

```bash
python -m mcp_audit recommendations --rejected
python -m mcp_audit recommendations --rejected --project local-translator-agent
python -m mcp_audit recommendations --ignored
```

Output: list of rejected/ignored recommendations with reasons, severity, phase context.

### Tool reliability

```bash
python -m mcp_audit tools --reliability
python -m mcp_audit tools --reliability --tool local_review_diff
python -m mcp_audit tools --reliability --model qwen3-coder:30b
```

Output: success rate, avg latency, timeout rate, confidence distribution per tool/model.

### Error recovery history

```bash
python -m mcp_audit recovery --phase TM-1B
python -m mcp_audit recovery --unresolved
```

Output: recovery attempts, success rate, avg attempts to resolution, still-unresolved items.

### Phase readiness

```bash
python -m mcp_audit readiness --phase TM-1B.5
```

Output: checklist of gates passed/failed, whether phase can be considered complete.

### Recommendation adoption rate

```bash
python -m mcp_audit recommendations --adoption-rate
python -m mcp_audit recommendations --adoption-rate --by-tool
python -m mcp_audit recommendations --adoption-rate --by-phase TM-1B
```

Output: percentage of accepted vs rejected vs ignored recommendations.

### Full audit trail for a commit

```bash
python -m mcp_audit trace --commit def789ab
```

Output: all MCP invocations, reviews, failures, and recommendations leading to that commit.

## 12. Privacy and storage policy

### What goes WHERE

| Content | Raw log | JSONL | SQLite |
|---------|---------|-------|--------|
| Full code | YES (capped) | NO | NO |
| Full diff | YES (capped) | NO | NO |
| Full prompt text | YES (capped) | NO | NO |
| Full model output | YES (capped) | NO | NO |
| File paths | YES | YES (summary) | YES |
| Commit hashes | YES | YES | YES |
| Test names | YES | YES | YES |
| Error messages (redacted) | YES | YES | YES |
| Stack traces (redacted) | YES | YES (first 500 chars) | YES (first 500 chars) |
| Recommendation text | YES | YES (redacted if needed) | YES (redacted if needed) |
| Purpose/summary | YES | YES | YES |
| Secrets, tokens, keys | NEVER (redacted before write) | NEVER | NEVER |
| Passwords, API keys | NEVER (redacted before write) | NEVER | NEVER |
| Personal data | NEVER | NEVER | NEVER |

### Redaction policy

- Secrets are redacted using the same `_REDACT_RE` patterns from `mcp_gate.py`
- Redaction happens BEFORE write, not after
- If redaction fails (cannot confirm no secrets), the content is stored as `[REDACTED: secret detection uncertain]`
- A `has_secrets_detected` boolean flag is set on any record where secrets were found
- `redacted_fields` lists which fields were redacted

### Storage paths

- Default: `.mcp_audit/` in project root
- Configurable via `MCP_AUDIT_DIR` environment variable
- Raw logs: `.mcp_audit/raw/{project}/{phase}/`
- JSONL files: `.mcp_audit/events.jsonl`, etc.
- SQLite DB: `.mcp_audit/mcp_audit.db`

### Retention

- Default: no automatic deletion (MCP-AUDIT-0 design note: retention policy TBD in MCP-AUDIT-1)
- Raw logs: capped at 100KB per file, max 50 files per phase per tool
- JSONL: no size cap (append-only, line-oriented, compact)
- SQLite: VACUUM periodically
- Future: configurable retention by age, phase, project

### Sensitive projects

- Raw log layer can be disabled: `MCP_AUDIT_RAW_LOG_ENABLED=0`
- JSONL layer remains active but with stricter redaction
- SQLite layer only stores summaries, never raw content

### Tamper resistance

- JSONL files are append-only by convention (not enforced by filesystem)
- SQLite WAL mode provides crash safety
- No cryptographic signing in MCP-AUDIT-0 design
- Tamper detection (hash chain or similar) is a future concern (MCP-AUDIT-3+)
- Audit record integrity depends on filesystem permissions in MVP

## 13. Implementation roadmap

| Phase | Name | Deliverable | Dependencies |
|-------|------|-------------|--------------|
| **MCP-AUDIT-0** | Design document | This document | None |
| **MCP-AUDIT-1** | JSONL event logger | `mcp_audit/logger.py` writes to `events.jsonl`, `failures.jsonl`, `recommendations.jsonl` | MCP-AUDIT-0 |
| **MCP-AUDIT-2** | SQLite audit DB | `mcp_audit/db.py` creates schema, migrates from JSONL, provides query API | MCP-AUDIT-1 |
| **MCP-AUDIT-3** | Audit summarizer skill | `/local-audit-summary` skill generates phase audit reports (Section 10) | MCP-AUDIT-2 |
| **MCP-AUDIT-4** | CLI query tool | `python -m mcp_audit summary|failures|commits|recommendations|tools` | MCP-AUDIT-2 |
| **MCP-AUDIT-5** | Hook/wrapper integration | Hooks auto-record invocations; commit gate checks audit state | MCP-AUDIT-2 |
| **MCP-EVAL-0** | MCP effectiveness evaluation | Analyzes audit data to measure: recommendation adoption rate, tool reliability, error recovery success rate, phase completion quality | MCP-AUDIT-4 |
| **MCP-PLAYBOOK-0** | Error recovery knowledge base | Builds playbook from failure patterns: common failures → proven fixes, model-specific reliability data, phase-specific risk profiles | MCP-EVAL-0 |

### Phase dependency graph

```
MCP-AUDIT-0 (design)
    │
    └── MCP-AUDIT-1 (JSONL logger)
            │
            └── MCP-AUDIT-2 (SQLite DB)
                    │
                    ├── MCP-AUDIT-3 (summarizer skill)
                    ├── MCP-AUDIT-4 (CLI query tool)
                    └── MCP-AUDIT-5 (hook integration)
                            │
                            └── MCP-EVAL-0 (effectiveness eval)
                                    │
                                    └── MCP-PLAYBOOK-0 (knowledge base)
```

### MCP-AUDIT-1 implementation notes (forward-looking)

The JSONL logger (MCP-AUDIT-1) must:
1. Be callable from both hooks (PreToolUse/PostToolUse) and manual controller invocation
2. Accept structured event data as input (dict → JSONL line)
3. Handle concurrent writes safely (append-only, line-buffered)
4. Redact secrets before write
5. Create output directories on demand
6. Validate required fields before write
7. Return the event ID for linking
8. Never throw — log errors to stderr, never block the caller

## 14. Non-goals

This phase (MCP-AUDIT-0) explicitly does NOT:

- Implement any database (SQLite or otherwise)
- Modify MCP server behavior
- Modify hook behavior
- Create CLI tools
- Build a dashboard or visualization
- Implement automatic policy enforcement
- Create retention/deletion mechanisms
- Add cryptographic signing or tamper-proofing
- Integrate with external monitoring systems
- Change the existing MCP tool API
- Add new MCP tools
- Modify `mcp_gate.py`, `mcp_doctor.py`, or any existing tool
- Create Python modules for audit functionality
- Run database migrations
- Tag or release

Future phases MAY implement these, but each requires its own design document first.

## Appendix A: Coverage checklist

The audit system must cover these invocation scenarios (derived from actual project usage in local-translator-agent TM-1A/TM-1B and local-llm-pipeline MCP phases):

- [ ] Session start `local_check`
- [ ] First-read file summary for files > 200 lines
- [ ] New directory tree summary
- [ ] Test plan generation before implementation
- [ ] Pre-commit diff review (`commit_gate=true`)
- [ ] Staged diff review (`commit_gate=true`)
- [ ] Debate review for high-risk changes (hooks, gates, MCP server, safety policy)
- [ ] Code draft (fix/feature/refactor → `.local_llm_out/`)
- [ ] Commit gate block event
- [ ] Commit gate bypass event (`--no-verify`, hook deregistration)
- [ ] Error Recovery Rule triggering (retry, escalate, fallback)
- [ ] Error Recovery Rule exhaustion (all retries failed)
- [ ] Test failure after MCP-reviewed change
- [ ] Test pass after MCP-reviewed change
- [ ] Recommendation acceptance with applied commit
- [ ] Recommendation rejection with reason
- [ ] Recommendation ignored (context shift, timeout)
- [ ] User override of MCP block
- [ ] Phase freeze boundary review
- [ ] Documentation-only change (no commit gate required)
- [ ] CLI invocation bypass (not routed through hooks)
- [ ] Nested invocation (debate → internal review)
- [ ] Tool version change detection
- [ ] Model unavailable / fallback
- [ ] Model bad output / escalation
- [ ] Hook health check failure
- [ ] Cross-project invocation (global MCP launcher mode)

## Appendix B: Risk coverage from local model analysis

The local model risk analysis (2026-05-13, `qwen3-coder-next-q8`) identified these risks and their mitigations are incorporated above:

| Risk ID | Risk | Mitigation section |
|---------|------|--------------------|
| 1 | Log omission (bypass hooks) | Section 6: `commit_gate_bypassed`, `invocation_source` field |
| 2 | Incomplete failure records | Section 6: `tool_failed`, `model_timeout`, `model_bad_output` with required fields |
| 3 | Raw log size explosion | Section 12: 100KB cap per file, max 50 files per phase |
| 4 | Sensitive info leakage | Section 12: redaction policy, `has_secrets_detected` flag, `redacted_fields` |
| 5 | Claude Code self-reporting unreliability | Section 6: `recorder_health_status`, fallback recorder (MCP-AUDIT-1 design note) |
| 6 | Hook vs manual recording inconsistency | Section 7: `invocation_source`, `is_hooked` fields |
| 7 | Missing commit_before/commit_after | Section 7: `commit_before`, `commit_after` on all tables |
| 8 | Recommendation adoption ambiguity | Section 7: `decision` enum with 6 states including `ignored` |
| 9 | Cross-project confusion | Section 7: `project_name`, `project_path` on all records |
| 10 | Phase/task correlation gaps | Section 7: `phase_id`, `task_id` on all records |
| 11 | Concurrent invocation races | Section 7: `trace_id` (UUID), `session_id`, `invocation_order` |
| 12 | Tool reliability blind spots | Section 9: `tool_reliability` view, Section 11: reliability queries |
| 13 | Error recovery invisibility | Section 6: `error_recovery_triggered`, Section 7: recovery fields on failure log |
| 14 | Test result correlation | Section 7: `tests_involved`, `final_test_result` |
| 15 | Hook deregistration (missed) | Section 6: `hook_health_check_failed` |
| 16 | Tool version drift (missed) | Section 7: `tool_version`, Section 6: `tool_version_drift` |
| 17 | Audit DB tampering (missed) | Section 12: tamper resistance notes; future concern |
| 18 | Partial tool output (missed) | Section 7: `output_truncated`, `output_size_bytes` |
| 19 | Clock skew (missed) | Section 7: `wall_clock_start/end` (ISO 8601 with timezone) |
| 20 | Hook recursion (missed) | Section 6: `nested_invocation_timeout`, Section 7: `trace_id` for nesting |
| 21 | --no-verify bypass (missed) | Section 6: `commit_gate_bypassed` |

## MCP-AUDIT-1 Implementation Notes

**Status**: Complete (2026-05-13)

### Files created

- `tools/mcp_audit_logger.py` — JSONL event logger module (336 lines)
- `tests/test_mcp_audit_logger.py` — 23 focused tests

### JSONL output files

Default location: `.mcp_audit/` in project root (configurable via `MCP_AUDIT_DIR`).

| File | Purpose |
|------|---------|
| `.mcp_audit/events.jsonl` | All audit events (invocations, results, blocks, fixes) |
| `.mcp_audit/failures.jsonl` | All failures (denormalized for fast query) |
| `.mcp_audit/recommendations.jsonl` | Recommendations with adoption status |
| `.mcp_audit/phase_audits.jsonl` | Per-phase summary records |

### API

| Function | Description |
|----------|-------------|
| `ensure_audit_dirs(base_dir)` | Create `.mcp_audit/` directory |
| `utc_now_iso()` | ISO 8601 UTC timestamp |
| `generate_event_id()` | UUID v4 event ID |
| `append_jsonl(path, record)` | Append one JSON line to a JSONL file |
| `write_audit_event(base_dir, event)` | Write to `events.jsonl` |
| `write_failure_event(base_dir, failure)` | Write to `failures.jsonl` + `events.jsonl` |
| `write_recommendation_event(base_dir, rec)` | Write to `recommendations.jsonl` + `events.jsonl` |
| `write_phase_audit_event(base_dir, audit)` | Write to `phase_audits.jsonl` + `events.jsonl` |
| `validate_event(record)` | Validate event type, task type, result status |
| `validate_failure(record)` | Validate failure type, severity |
| `validate_recommendation(record)` | Validate decision, severity |
| `validate_phase_audit(record)` | Validate phase_id, final_status |

### Enumerations implemented

- **event_type**: 18 values including `hook_state_mismatch`, `cli_review_not_recognized`, `staged_diff_hash_mismatch`, `manual_hook_state_alignment`
- **task_type**: 12 values
- **failure_type**: 23 values including `hook_state_mismatch`, `cli_review_not_recognized`, `staged_diff_hash_mismatch`, `manual_state_alignment_required`
- **recommendation decision**: 6 values (`accepted`, `rejected`, `partially_accepted`, `ignored`, `overridden_by_user`, `obsolete_after_fix`)
- **severity**: 6 values (`info`, `low`, `medium`, `high`, `critical`, `blocking`)
- **result_status**: 9 values (`started`, `passed`, `failed`, `blocked`, `warning`, `skipped`, `timeout`, `resolved`, `unresolved`)

### Privacy enforcement

- Forbidden fields (`prompt_body`, `full_diff`, `full_code`, `file_content`, `api_key`, `token`, `password`, `secret`) are stripped before write
- Secret patterns (API keys, tokens, passwords) in summary fields are redacted to `[REDACTED]`
- `raw_log_path` is writable but raw content never goes into JSONL

### First-class failure scenarios from MCP-AUDIT-0

The following real failures discovered during MCP-AUDIT-0 are first-class recordable events:

1. **CLI review not recognized**: `event_type=cli_review_not_recognized`, `failure_type=cli_review_not_recognized`
2. **Hook state repo mismatch**: `event_type=hook_state_mismatch`, `failure_type=hook_state_mismatch`
3. **Staged diff hash mismatch**: `event_type=staged_diff_hash_mismatch`, `failure_type=staged_diff_hash_mismatch`
4. **Manual hook state alignment**: `event_type=manual_hook_state_alignment`, `failure_type=manual_state_alignment_required`

### Known limitations

- **No SQLite yet** — next phase (MCP-AUDIT-2)
- **No automatic hook/wrapper integration** — future phase (MCP-AUDIT-5). Currently the logger exists but automatic capture depends on hooks calling it.
- **No query CLI** — future phase (MCP-AUDIT-4)
- **No dashboard** — non-goal for now
- **Commit gate still requires MCP-protocol review** — CLI-based review is recordable but does not satisfy the gate. This is by design: the gate enforces process, the logger records what happened.

### Tests

- **Focused**: 23/23 passed
- **Full suite**: 454 passed, 11 failed (pre-existing Windows+Python 3.14 subprocess handle inheritance, unrelated)
- **Test coverage**: event writing, failure recording, recommendation tracking, phase audits, validation, privacy, append-only behavior, Windows path handling, env var configuration, enum completeness
