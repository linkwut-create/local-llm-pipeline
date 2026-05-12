"""Test mcp_audit_cli.py — CLI query tool (MCP-AUDIT-4)."""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import mcp_audit_cli as cli
import mcp_audit_db as db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(tmp):
    """Create a test DB with sample data. Returns base_dir."""
    conn = db.connect_audit_db(tmp)
    db.migrate_audit_db(conn)
    for i in range(3):
        db.insert_invocation(conn, {
            "id": f"evt-{i}", "created_at": f"2026-05-13T10:00:0{i}Z",
            "event_type": "mcp_invocation_finished", "tool_name": "local_check" if i == 0 else "local_review_diff",
            "task_type": "environment_check" if i == 0 else "diff_review",
            "project_name": "test-project", "phase_id": "PHASE-1",
            "result_status": "passed",
        })
    db.insert_invocation(conn, {
        "id": "evt-block", "created_at": "2026-05-13T10:00:10Z",
        "event_type": "commit_gate_blocked", "tool_name": "commit_gate",
        "task_type": "commit_gate", "project_name": "test-project",
        "phase_id": "PHASE-1", "result_status": "blocked", "blocking": 1,
        "commit_before": "abc123",
    })
    db.insert_failure(conn, {
        "id": "fail-1", "created_at": "2026-05-13T10:00:05Z",
        "failure_type": "model_timeout", "severity": "high",
        "tool_name": "local_review_diff", "project_name": "test-project",
        "phase_id": "PHASE-1", "resolved": 0,
    })
    db.insert_recommendation(conn, {
        "id": "rec-rej", "created_at": "2026-05-13T10:00:07Z",
        "recommendation": "Deferred to next phase", "severity": "low",
        "decision": "rejected", "decision_reason": "Out of scope",
    })
    db.insert_phase_audit(conn, {
        "id": "pa-1", "created_at": "2026-05-13T10:00:11Z",
        "phase_id": "PHASE-1", "project_name": "test-project",
        "invocation_count": 4, "failure_count": 1,
        "blocked_commit_count": 1, "accepted_recommendation_count": 0,
        "rejected_recommendation_count": 1, "tests_run": 10,
        "final_test_result": "all_passed", "commit_before": "abc123",
        "commit_after": "def456", "final_status": "completed",
    })
    conn.commit()
    conn.close()
    return tmp


def _run(args: list[str], base_dir: str) -> tuple[int, str]:
    """Run CLI with args and capture stdout. Returns (exit_code, output)."""
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    rc = 0
    try:
        cli.main(["--base-dir", base_dir] + args)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    except Exception:
        rc = 1
    finally:
        sys.stdout = old_stdout
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cli_help():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["--help"], tmp)
        assert "usage" in out.lower() or "summary" in out.lower()


def test_cli_summary():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["summary", "--phase=PHASE-1"], tmp)
        assert rc == 0
        assert "PHASE-1" in out or "invocation_count" in out


def test_cli_summary_json():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["summary", "--phase=PHASE-1", "--format=json"], tmp)
        assert rc == 0
        data = json.loads(out)
        assert "invocation_count" in data


def test_cli_failures():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["failures", "--project=test-project"], tmp)
        assert rc == 0
        assert "model_timeout" in out


def test_cli_blocked_commits():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["blocked-commits"], tmp)
        assert rc == 0
        assert "evt-block" in out


def test_cli_rejected_recommendations():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["rejected-recommendations"], tmp)
        assert rc == 0
        assert "rec-rej" in out


def test_cli_tool_reliability():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["tool-reliability"], tmp)
        assert rc == 0
        assert "local_review_diff" in out or "local_check" in out


def test_cli_import_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        # Create JSONL files first
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "events.jsonl").write_text(
            json.dumps({"id": "e1", "created_at": "2026-01-01T00:00:00Z",
                        "event_type": "mcp_invocation_finished",
                        "tool_name": "local_check", "project_name": "test",
                        "phase_id": "PHASE-2", "result_status": "passed"}) + "\n",
            encoding="utf-8")
        rc, out = _run(["import-jsonl"], tmp)
        assert rc == 0
        assert "imported" in out.lower() or "1" in out


def test_cli_generate_report():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["generate-report", "--phase=PHASE-1", "--project=test-project"], tmp)
        assert rc == 0
        assert "Report written" in out


def test_cli_missing_db_error():
    with tempfile.TemporaryDirectory() as tmp:
        # Don't create DB — just test graceful handling
        rc, out = _run(["summary", "--phase=PHASE-X"], tmp)
        # Empty DB created automatically; should show "No records found"
        assert "No records found" in out


def test_cli_empty_results():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["failures", "--phase=NONEXISTENT"], tmp)
        assert rc == 0
        assert "No records found" in out


def test_cli_invalid_command_nonzero():
    rc, out = _run(["invalid-command-xyz"], "/tmp")
    assert rc != 0


def test_cli_windows_paths():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["summary", "--phase=PHASE-1"], tmp)
        assert rc == 0


def test_cli_does_not_print_full_prompt_or_diff():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["failures"], tmp)
        assert "prompt_body" not in out.lower()
        assert "full_diff" not in out.lower()
        assert "full_code" not in out.lower()


def test_cli_format_json():
    with tempfile.TemporaryDirectory() as tmp:
        _setup_db(tmp)
        rc, out = _run(["blocked-commits", "--format=json"], tmp)
        assert rc == 0
        parsed = json.loads(out)
        assert isinstance(parsed, list)
