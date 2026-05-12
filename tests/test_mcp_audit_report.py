"""Test mcp_audit_report.py — phase report generator (MCP-AUDIT-3)."""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import mcp_audit_db as db
import mcp_audit_report as report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db_with_phase(tmp, phase_id="MCP-AUDIT-3", project_name="test-project"):
    """Create a test DB with sample data for a phase. Returns conn, tmp."""
    db_dir = tmp
    conn = db.connect_audit_db(db_dir)
    db.migrate_audit_db(conn)

    # Add invocations
    for i in range(5):
        db.insert_invocation(conn, {
            "id": f"evt-{i}", "created_at": f"2026-05-13T10:00:0{i}Z",
            "event_type": "mcp_invocation_finished", "tool_name": "local_review_diff",
            "task_type": "diff_review", "project_name": project_name,
            "phase_id": phase_id, "result_status": "passed",
        })
    # Add a blocked commit
    db.insert_invocation(conn, {
        "id": "evt-block", "created_at": "2026-05-13T10:00:10Z",
        "event_type": "commit_gate_blocked", "tool_name": "commit_gate",
        "task_type": "commit_gate", "project_name": project_name,
        "phase_id": phase_id, "result_status": "blocked", "blocking": 1,
        "output_summary": "BLOCKED: dirty_since_review=True",
        "commit_before": "abc123", "commit_after": "def456",
    })
    # Add a failure
    db.insert_failure(conn, {
        "id": "fail-1", "created_at": "2026-05-13T10:00:05Z",
        "failure_type": "model_timeout", "severity": "high",
        "tool_name": "local_review_diff", "project_name": project_name,
        "phase_id": phase_id, "exit_code": -1, "resolved": 1,
        "stderr_summary": "Read timed out",
    })
    # Add a recommendation (accepted)
    db.insert_recommendation(conn, {
        "id": "rec-acc", "created_at": "2026-05-13T10:00:06Z",
        "recommendation": "Add retry logic", "severity": "medium",
        "decision": "accepted", "applied_commit": "fix123",
    })
    # Add a recommendation (rejected)
    db.insert_recommendation(conn, {
        "id": "rec-rej", "created_at": "2026-05-13T10:00:07Z",
        "recommendation": "Deferred to next phase", "severity": "low",
        "decision": "rejected", "decision_reason": "Out of scope for this phase",
    })
    # Link recommendations to phase via invocation
    db.insert_invocation(conn, {
        "id": "evt-rec", "created_at": "2026-05-13T10:00:08Z",
        "event_type": "recommendation_created", "tool_name": "local_review_diff",
        "project_name": project_name, "phase_id": phase_id,
        "result_status": "passed", "linked_recommendation_id": "rec-acc",
    })
    db.insert_invocation(conn, {
        "id": "evt-rec2", "created_at": "2026-05-13T10:00:09Z",
        "event_type": "recommendation_created", "tool_name": "local_review_diff",
        "project_name": project_name, "phase_id": phase_id,
        "result_status": "passed", "linked_recommendation_id": "rec-rej",
    })
    # Phase audit
    db.insert_phase_audit(conn, {
        "id": "pa-1", "created_at": "2026-05-13T10:00:11Z",
        "phase_id": phase_id, "project_name": project_name,
        "invocation_count": 7, "failure_count": 1,
        "blocked_commit_count": 1, "accepted_recommendation_count": 1,
        "rejected_recommendation_count": 1, "tests_run": 100,
        "final_test_result": "all_passed", "commit_before": "abc123",
        "commit_after": "def456", "final_status": "completed",
    })
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Basic report generation
# ---------------------------------------------------------------------------

def test_generate_phase_report_basic():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "# MCP Audit Report" in md
        assert "MCP-AUDIT-3" in md


def test_report_contains_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "## 1. Metadata" in md
        assert "test-project" in md
        assert "abc123" in md
        assert "def456" in md
        assert "completed" in md


def test_report_contains_summary_counts():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "## 2. Summary" in md
        assert "MCP calls" in md
        assert "Failures" in md
        assert "Blocked commits" in md


def test_report_contains_tool_usage():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "## 3. Tool usage" in md
        assert "local_review_diff" in md


def test_report_contains_failures():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "## 4. Failures" in md
        assert "model_timeout" in md


def test_report_handles_no_failures():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = db.connect_audit_db(tmp)
        db.insert_invocation(conn, {
            "id": "evt-0", "created_at": "2026-05-13T10:00:00Z",
            "event_type": "mcp_invocation_finished", "tool_name": "local_check",
            "project_name": "test", "phase_id": "PHASE-EMPTY", "result_status": "passed",
        })
        conn.commit()
        md = report.generate_phase_report(conn, "PHASE-EMPTY", "test")
        conn.close()
        assert "No failures recorded" in md


def test_report_contains_commit_gate_events():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "## 5. Commit gate events" in md
        assert "commit_gate_blocked" in md


def test_report_contains_accepted_recommendations():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "Accepted" in md
        assert "Add retry logic" in md


def test_report_contains_rejected_recommendations():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "Rejected" in md
        assert "Deferred to next phase" in md


def test_report_contains_tests_section():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "## 7. Tests" in md
        assert "all_passed" in md


# ---------------------------------------------------------------------------
# Risk judgment
# ---------------------------------------------------------------------------

def test_risk_low_when_no_failures():
    data = {"failures": [], "failure_count": 0, "bypass_count": 0, "recommendations": []}
    assert report._status_from_counts(data) == "low"


def test_risk_medium_when_resolved_failures():
    data = {
        "failures": [{"severity": "high", "resolved": 1}],
        "failure_count": 1,
        "bypass_count": 0,
        "recommendations": [],
    }
    assert report._status_from_counts(data) == "medium"


def test_risk_high_when_unresolved_high_failure():
    data = {
        "failures": [{"severity": "high", "resolved": 0}],
        "failure_count": 1,
        "bypass_count": 0,
        "recommendations": [],
    }
    assert report._status_from_counts(data) == "high"


def test_risk_blocked_when_unresolved_blocking_failure():
    data = {
        "failures": [{"severity": "blocking", "resolved": 0}],
        "failure_count": 1,
        "bypass_count": 0,
        "recommendations": [],
    }
    assert report._status_from_counts(data) == "blocked"


def test_risk_blocked_when_unresolved_critical_failure():
    data = {
        "failures": [{"severity": "critical", "resolved": 0}],
        "failure_count": 1,
        "bypass_count": 0,
        "recommendations": [],
    }
    assert report._status_from_counts(data) == "blocked"


def test_gate_bypass_sets_high_risk():
    data = {
        "failures": [],
        "failure_count": 0,
        "bypass_count": 1,
        "recommendations": [],
    }
    assert report._status_from_counts(data) == "high"


def test_rejected_blocking_recommendation_sets_high():
    data = {
        "failures": [],
        "failure_count": 0,
        "bypass_count": 0,
        "recommendations": [{"severity": "blocking", "decision": "rejected"}],
    }
    assert report._status_from_counts(data) == "high"


# ---------------------------------------------------------------------------
# Write report to disk
# ---------------------------------------------------------------------------

def test_write_phase_report_creates_markdown():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp, "PHASE-X")
        conn.close()
        path = report.write_phase_report(tmp, "PHASE-X", "test-project")
        assert path is not None
        assert Path(path).exists()
        content = Path(path).read_text(encoding="utf-8")
        assert "# MCP Audit Report" in content


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_markdown_escape():
    """Pipe characters in values should be escaped."""
    escaped = report._md_escape("hello | world")
    assert "\\|" in escaped
    assert "|" not in escaped.replace("\\|", "")


def test_does_not_include_full_prompt_or_full_diff():
    """Report must not contain raw prompt_body, full_diff, or full_code strings."""
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp)
        md = report.generate_phase_report(conn, "MCP-AUDIT-3", "test-project")
        conn.close()
        assert "prompt_body" not in md.lower()
        assert "full_diff" not in md.lower()
        assert "full_code" not in md.lower()


def test_windows_paths_supported():
    with tempfile.TemporaryDirectory() as tmp:
        conn = _setup_db_with_phase(tmp, "PHASE-WIN", "test-project")
        conn.close()
        path = report.write_phase_report(tmp, "PHASE-WIN", "test-project")
        assert path is not None
        assert "\\" in path or "/" in path


def test_missing_phase_returns_empty_report():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = db.connect_audit_db(tmp)
        md = report.generate_phase_report(conn, "NONEXISTENT", "test")
        conn.close()
        assert "NONEXISTENT" in md
        assert "MCP calls" in md  # should still generate a valid report
        assert "0" in md  # counts should be zero


# ---------------------------------------------------------------------------
# Next recommendation
# ---------------------------------------------------------------------------

def test_next_recommendation_blocked():
    data = {"bypass_count": 0}
    assert "Fix" in report._next_recommendation(data, "blocked")


def test_next_recommendation_high_bypass():
    data = {"bypass_count": 1}
    rec = report._next_recommendation(data, "high")
    assert "bypass" in rec.lower() or "gate" in rec.lower()


def test_next_recommendation_low():
    data = {"bypass_count": 0}
    assert "Proceed" in report._next_recommendation(data, "low")
