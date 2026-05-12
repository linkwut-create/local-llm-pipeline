"""Test mcp_audit_logger.py — JSONL audit event logging (MCP-AUDIT-1)."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import mcp_audit_logger as audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# Basic event writing
# ---------------------------------------------------------------------------

def test_write_audit_event_creates_events_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "mcp_invocation_started",
            "tool_name": "local_check",
            "task_type": "environment_check",
            "project_name": "test-project",
            "phase_id": "MCP-AUDIT-1",
        })
        assert eid is not None
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        assert len(events) == 1
        assert events[0]["event_type"] == "mcp_invocation_started"
        assert events[0]["tool_name"] == "local_check"
        assert "id" in events[0]
        assert "created_at" in events[0]


def test_write_failure_event_creates_failures_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        fid = audit.write_failure_event(tmp, {
            "failure_type": "model_timeout",
            "severity": "high",
            "tool_name": "local_review_diff",
            "project_name": "test-project",
            "phase_id": "MCP-AUDIT-1",
        })
        assert fid is not None
        failures = _read_jsonl(Path(tmp) / ".mcp_audit" / "failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["failure_type"] == "model_timeout"
        # Also check events.jsonl got a failure event
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        assert any(e["event_type"] == "mcp_invocation_failed" for e in events)


def test_write_recommendation_event_creates_recommendations_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        rid = audit.write_recommendation_event(tmp, {
            "decision": "accepted",
            "recommendation": "Add retry logic for API calls",
            "severity": "medium",
            "project_name": "test-project",
            "phase_id": "MCP-AUDIT-1",
        })
        assert rid is not None
        recs = _read_jsonl(Path(tmp) / ".mcp_audit" / "recommendations.jsonl")
        assert len(recs) == 1
        assert recs[0]["decision"] == "accepted"


def test_write_phase_audit_event_creates_phase_audits_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        pid = audit.write_phase_audit_event(tmp, {
            "phase_id": "MCP-AUDIT-1",
            "project_name": "test-project",
            "invocation_count": 15,
            "failure_count": 2,
            "final_status": "completed",
        })
        assert pid is not None
        pa = _read_jsonl(Path(tmp) / ".mcp_audit" / "phase_audits.jsonl")
        assert len(pa) == 1
        assert pa[0]["phase_id"] == "MCP-AUDIT-1"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_event_requires_event_type():
    errors = audit.validate_event({"id": "test-1"})
    assert any("event_type" in e for e in errors)


def test_invalid_event_type_rejected():
    errors = audit.validate_event({"id": "test-1", "event_type": "bogus_type"})
    assert any("invalid event_type" in e for e in errors)
    # Also test via write
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "bogus_type",
            "tool_name": "test",
        })
        assert eid is None


def test_invalid_failure_type_rejected():
    errors = audit.validate_failure({"id": "f-1", "failure_type": "not_a_failure"})
    assert any("invalid failure_type" in e for e in errors)
    with tempfile.TemporaryDirectory() as tmp:
        fid = audit.write_failure_event(tmp, {
            "failure_type": "not_a_failure",
            "severity": "low",
        })
        assert fid is None


def test_invalid_recommendation_decision_rejected():
    errors = audit.validate_recommendation({"id": "r-1", "decision": "maybe_later"})
    assert any("invalid decision" in e for e in errors)
    with tempfile.TemporaryDirectory() as tmp:
        rid = audit.write_recommendation_event(tmp, {
            "decision": "maybe_later",
            "recommendation": "test",
        })
        assert rid is None


# ---------------------------------------------------------------------------
# MCP-AUDIT-0 discovered failure scenarios
# ---------------------------------------------------------------------------

def test_commit_gate_blocked_event():
    """Record a commit gate blocked event."""
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "commit_gate_blocked",
            "tool_name": "commit_gate",
            "task_type": "commit_gate",
            "project_name": "local-llm-pipeline",
            "phase_id": "MCP-AUDIT-0",
            "purpose": "PreToolUse hook blocked git commit — no prior MCP review",
            "command": "git commit -m 'test'",
            "result_status": "blocked",
            "blocking": True,
            "output_summary": "BLOCKED: dirty_since_review=True, reviewed_repo mismatch",
            "notes": "Hook state from local-translator-agent was used in local-llm-pipeline",
        })
        assert eid is not None
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        evt = events[0]
        assert evt["event_type"] == "commit_gate_blocked"
        assert evt["blocking"] is True


def test_cli_review_not_recognized_failure():
    """Record the case where CLI-based review was not recognized by commit gate."""
    with tempfile.TemporaryDirectory() as tmp:
        fid = audit.write_failure_event(tmp, {
            "failure_type": "cli_review_not_recognized",
            "severity": "high",
            "tool_name": "local_review_diff",
            "project_name": "local-llm-pipeline",
            "phase_id": "MCP-AUDIT-0",
            "command": "git diff --cached | python3.14 tools/local_llm_router.py review-diff --stdin",
            "exit_code": 0,
            "stderr_summary": "",
            "hook_state_summary": "diff_reviewed=True, dirty_since_review=True, reviewed_repo=local-translator-agent",
            "possible_causes": [
                "CLI review does not go through MCP protocol",
                "Hook only tracks MCP tool calls, not subprocess invocations",
            ],
            "fix_applied": "Manually aligned hook state.json to match current repo/head/diff_hash",
            "fix_result": "fixed",
            "resolved": True,
            "notes": "Hook state had to be manually updated: reviewed_repo, reviewed_head, reviewed_diff_hash",
        })
        assert fid is not None
        failures = _read_jsonl(Path(tmp) / ".mcp_audit" / "failures.jsonl")
        assert failures[0]["failure_type"] == "cli_review_not_recognized"


def test_hook_state_mismatch_failure():
    """Record hook state repo/head mismatch."""
    with tempfile.TemporaryDirectory() as tmp:
        fid = audit.write_failure_event(tmp, {
            "failure_type": "hook_state_mismatch",
            "severity": "high",
            "tool_name": "commit_gate",
            "project_name": "local-llm-pipeline",
            "project_path": "C:/Users/Zero/local-llm-pipeline",
            "phase_id": "MCP-AUDIT-0",
            "hook_state_summary": json.dumps({
                "reviewed_repo": "C:/Users/Zero/local-translator-agent",
                "actual_repo": "C:/Users/Zero/local-llm-pipeline",
                "reviewed_head": "c8e8873...",
                "actual_head": "b0ae4fd...",
            }),
            "notes": "Cross-project state pollution: hook state carried over from local-translator-agent",
        })
        assert fid is not None
        failures = _read_jsonl(Path(tmp) / ".mcp_audit" / "failures.jsonl")
        assert failures[0]["failure_type"] == "hook_state_mismatch"


def test_staged_diff_hash_mismatch_failure():
    """Record staged diff hash mismatch between review and commit attempt."""
    with tempfile.TemporaryDirectory() as tmp:
        fid = audit.write_failure_event(tmp, {
            "failure_type": "staged_diff_hash_mismatch",
            "severity": "high",
            "tool_name": "commit_gate",
            "project_name": "local-llm-pipeline",
            "phase_id": "MCP-AUDIT-0",
            "staged_diff_hash": "411b0264fc19d61f...",
            "reviewed_diff_hash": "52967f379ff29a5b...",
            "blocking": True,
            "notes": "Diff hash computed with different encoding (bytes vs utf-8 string)",
        })
        assert fid is not None


def test_manual_hook_state_alignment_failure():
    """Record manual hook state alignment event."""
    with tempfile.TemporaryDirectory() as tmp:
        fid = audit.write_failure_event(tmp, {
            "failure_type": "manual_state_alignment_required",
            "severity": "medium",
            "tool_name": "commit_gate",
            "project_name": "local-llm-pipeline",
            "phase_id": "MCP-AUDIT-0",
            "command": "python3.14 -c '...' # set reviewed_repo, reviewed_head, reviewed_diff_hash",
            "notes": "Manual alignment needed because CLI review doesn't update hook PostToolUse state",
        })
        assert fid is not None


# ---------------------------------------------------------------------------
# append-only and data integrity
# ---------------------------------------------------------------------------

def test_jsonl_append_only():
    """Multiple writes should append, not overwrite."""
    with tempfile.TemporaryDirectory() as tmp:
        audit.write_audit_event(tmp, {"event_type": "mcp_invocation_started", "tool_name": "t1"})
        audit.write_audit_event(tmp, {"event_type": "mcp_invocation_finished", "tool_name": "t1"})
        audit.write_audit_event(tmp, {"event_type": "mcp_invocation_started", "tool_name": "t2"})
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        assert len(events) == 3


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

def test_default_does_not_store_raw_prompt_or_diff():
    """Forbidden fields (prompt_body, full_diff, full_code, api_key, password) are stripped."""
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "mcp_invocation_finished",
            "tool_name": "local_review_diff",
            "prompt_body": "THIS SHOULD NOT APPEAR",
            "full_diff": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
            "full_code": "def secret(): pass",
            "api_key": "sk-1234567890abcdef1234567890",
            "password": "s3cr3t!",
            "secret": "do-not-log-this",
            "event_type_ok": True,  # non-forbidden field
        })
        assert eid is not None
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        evt = events[0]
        assert "prompt_body" not in evt
        assert "full_diff" not in evt
        assert "full_code" not in evt
        assert "api_key" not in evt
        assert "password" not in evt
        assert "secret" not in evt
        # Non-forbidden fields survive
        assert "event_type" in evt


def test_raw_log_path_allowed_without_raw_content():
    """raw_log_path is allowed; raw content is not."""
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "mcp_invocation_finished",
            "tool_name": "local_review_diff",
            "raw_log_path": ".mcp_audit/raw/test-project/MCP-AUDIT-0/20260513_review.log",
            "prompt_body": "SHOULD BE STRIPPED",
        })
        assert eid is not None
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        evt = events[0]
        assert evt["raw_log_path"] == ".mcp_audit/raw/test-project/MCP-AUDIT-0/20260513_review.log"
        assert "prompt_body" not in evt


def test_secret_patterns_in_summary_fields_are_redacted():
    """If a summary field accidentally contains a secret pattern, it gets redacted."""
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "mcp_invocation_finished",
            "tool_name": "local_review_diff",
            "output_summary": "Used token sk-abcdefghijklmnopqrstuvwxyz in request",
        })
        assert eid is not None
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        evt = events[0]
        assert evt["output_summary"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Phase audit
# ---------------------------------------------------------------------------

def test_phase_audit_counts():
    with tempfile.TemporaryDirectory() as tmp:
        pid = audit.write_phase_audit_event(tmp, {
            "phase_id": "MCP-AUDIT-1",
            "project_name": "local-llm-pipeline",
            "invocation_count": 42,
            "failure_count": 3,
            "blocked_commit_count": 2,
            "accepted_recommendation_count": 5,
            "rejected_recommendation_count": 1,
            "tests_run": 450,
            "final_test_result": "all_passed",
            "commit_before": "abc123",
            "commit_after": "def456",
            "final_status": "completed",
        })
        assert pid is not None
        pa = _read_jsonl(Path(tmp) / ".mcp_audit" / "phase_audits.jsonl")
        assert pa[0]["invocation_count"] == 42
        assert pa[0]["failure_count"] == 3
        assert pa[0]["final_status"] == "completed"


# ---------------------------------------------------------------------------
# Windows path handling
# ---------------------------------------------------------------------------

def test_windows_paths_are_serialized_safely():
    """Windows backslash paths should serialize without escaping issues."""
    with tempfile.TemporaryDirectory() as tmp:
        eid = audit.write_audit_event(tmp, {
            "event_type": "mcp_invocation_started",
            "tool_name": "local_summarize_file",
            "project_path": "C:\\Users\\Zero\\local-llm-pipeline",
            "files_involved": ["C:\\Users\\Zero\\local-llm-pipeline\\tools\\local_llm_check.py"],
        })
        assert eid is not None
        events = _read_jsonl(Path(tmp) / ".mcp_audit" / "events.jsonl")
        evt = events[0]
        assert "Users" in str(evt.get("project_path", ""))
        # Should be valid JSON with backslashes
        raw = (Path(tmp) / ".mcp_audit" / "events.jsonl").read_text(encoding="utf-8")
        json.loads(raw.strip().split("\n")[0])  # must parse


def test_audit_dir_respects_env_var(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        custom = Path(tmp) / "custom_audit"
        monkeypatch.setenv("MCP_AUDIT_DIR", str(custom))
        eid = audit.write_audit_event(tmp, {"event_type": "mcp_invocation_started", "tool_name": "t"})
        assert eid is not None
        assert (custom / "events.jsonl").exists()


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------

def test_all_required_event_types_defined():
    required = {
        "mcp_invocation_started", "mcp_invocation_finished", "mcp_invocation_failed",
        "recommendation_created", "recommendation_accepted", "recommendation_rejected",
        "test_failed", "test_passed", "commit_gate_blocked", "staged_review_passed",
        "debate_review_warning", "error_recovery_triggered", "fix_applied",
        "phase_audit_completed", "hook_state_mismatch",
        "cli_review_not_recognized", "staged_diff_hash_mismatch",
        "manual_hook_state_alignment",
    }
    assert required <= set(audit.EVENT_TYPES)


def test_all_required_failure_types_defined():
    required = {
        "tool_failed", "model_timeout", "model_bad_output", "model_unavailable",
        "commit_gate_blocked", "test_failed", "diff_review_blocked",
        "debate_review_warning", "repeated_error_triggered",
        "environment_error", "dependency_error", "path_error", "permission_error",
        "git_state_error", "dirty_worktree_error", "hook_state_mismatch",
        "cli_review_not_recognized", "staged_diff_hash_mismatch",
        "manual_state_alignment_required", "user_override",
        "recommendation_rejected", "fixed_after_mcp", "unresolved_failure",
    }
    assert required <= set(audit.FAILURE_TYPES)


def test_all_decision_values_defined():
    required = {"accepted", "rejected", "partially_accepted", "ignored",
                "overridden_by_user", "obsolete_after_fix"}
    assert required <= set(audit.RECOMMENDATION_DECISIONS)
