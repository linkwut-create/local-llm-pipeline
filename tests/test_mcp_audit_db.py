"""Test mcp_audit_db.py — SQLite audit database (MCP-AUDIT-2)."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import mcp_audit_db as db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**kw):
    return {
        "id": kw.pop("id", "evt-001"),
        "created_at": kw.pop("created_at", "2026-05-13T10:00:00Z"),
        "event_type": "mcp_invocation_finished",
        "tool_name": "local_review_diff",
        "task_type": "diff_review",
        "project_name": "test-project",
        "phase_id": "MCP-AUDIT-2",
        "result_status": "passed",
        **kw,
    }


def _make_failure(**kw):
    return {
        "id": kw.pop("id", "fail-001"),
        "created_at": kw.pop("created_at", "2026-05-13T10:00:00Z"),
        "failure_type": "model_timeout",
        "severity": "high",
        "tool_name": "local_review_diff",
        "project_name": "test-project",
        "phase_id": "MCP-AUDIT-2",
        **kw,
    }


def _make_recommendation(**kw):
    return {
        "id": kw.pop("id", "rec-001"),
        "created_at": kw.pop("created_at", "2026-05-13T10:00:00Z"),
        "recommendation": "Add error handling",
        "severity": "medium",
        "decision": "accepted",
        **kw,
    }


def _make_phase_audit(**kw):
    return {
        "id": kw.pop("id", "phase-001"),
        "created_at": kw.pop("created_at", "2026-05-13T10:00:00Z"),
        "phase_id": "MCP-AUDIT-2",
        "project_name": "test-project",
        "invocation_count": 10,
        "failure_count": 2,
        "final_status": "completed",
        **kw,
    }


def _connect_tmp(tmp):
    return db.connect_audit_db(tmp)


def _close_safe(conn):
    try:
        conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Init and schema
# ---------------------------------------------------------------------------

def test_init_audit_db_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        assert (Path(tmp) / ".mcp_audit" / "mcp_audit.db").exists()


def test_schema_tables_exist():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        assert "mcp_invocation_log" in tables
        assert "mcp_failure_log" in tables
        assert "mcp_recommendation_log" in tables
        assert "mcp_phase_audit" in tables
        _close_safe(conn)


def test_init_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        db.init_audit_db(tmp)  # second call should not raise
        conn = _connect_tmp(tmp)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "mcp_invocation_log" in tables
        _close_safe(conn)


def test_views_exist():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        views = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()]
        assert "v_tool_reliability" in views
        assert "v_phase_summary" in views
        _close_safe(conn)


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------

def test_insert_invocation():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_invocation(conn, _make_event(
            id="evt-1", event_type="commit_gate_blocked", result_status="blocked", blocking=1,
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_invocation_log WHERE id='evt-1'").fetchone()
        assert row is not None
        assert dict(row)["event_type"] == "commit_gate_blocked"
        _close_safe(conn)


def test_insert_failure():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_failure(conn, _make_failure(id="f-1", severity="critical"))
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_failure_log WHERE id='f-1'").fetchone()
        assert row is not None
        _close_safe(conn)


def test_insert_recommendation():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_recommendation(conn, _make_recommendation(id="r-1", decision="rejected"))
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_recommendation_log WHERE id='r-1'").fetchone()
        assert row is not None
        _close_safe(conn)


def test_insert_phase_audit():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_phase_audit(conn, _make_phase_audit(id="p-1"))
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_phase_audit WHERE id='p-1'").fetchone()
        assert row is not None
        _close_safe(conn)


def test_duplicate_insert_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_invocation(conn, _make_event(id="dup-1"))
        conn.commit()
        db.insert_invocation(conn, _make_event(id="dup-1", event_type="different"))
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM mcp_invocation_log WHERE id='dup-1'"
        ).fetchone()[0]
        assert count == 1
        _close_safe(conn)


def test_list_dict_fields_serialized_as_json():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_invocation(conn, _make_event(
            id="evt-json", files_involved=["a.py", "b.py"], tests_involved=["test_a", "test_b"],
        ))
        conn.commit()
        row = conn.execute("SELECT files_involved, tests_involved FROM mcp_invocation_log WHERE id='evt-json'").fetchone()
        parsed_files = json.loads(row[0])
        assert parsed_files == ["a.py", "b.py"]
        parsed_tests = json.loads(row[1])
        assert parsed_tests == ["test_a", "test_b"]
        _close_safe(conn)


# ---------------------------------------------------------------------------
# JSONL import
# ---------------------------------------------------------------------------

def test_import_events_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "events.jsonl").write_text(
            json.dumps(_make_event(id="e1")) + "\n" +
            json.dumps(_make_event(id="e2", event_type="mcp_invocation_failed", result_status="failed")) + "\n",
            encoding="utf-8"
        )
        result = db.import_audit_jsonl(tmp)
        assert result["events_imported"] == 2
        assert result["errors"] == 0


def test_import_failures_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "failures.jsonl").write_text(
            json.dumps(_make_failure(id="f1")) + "\n" +
            json.dumps(_make_failure(id="f2", failure_type="test_failed")) + "\n",
            encoding="utf-8"
        )
        result = db.import_audit_jsonl(tmp)
        assert result["failures_imported"] == 2


def test_import_recommendations_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "recommendations.jsonl").write_text(
            json.dumps(_make_recommendation(id="r1")) + "\n",
            encoding="utf-8"
        )
        result = db.import_audit_jsonl(tmp)
        assert result["recommendations_imported"] == 1


def test_import_phase_audits_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "phase_audits.jsonl").write_text(
            json.dumps(_make_phase_audit(id="p1")) + "\n",
            encoding="utf-8"
        )
        result = db.import_audit_jsonl(tmp)
        assert result["phase_audits_imported"] == 1


def test_import_malformed_jsonl_skips_line():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "events.jsonl").write_text(
            json.dumps(_make_event(id="e1")) + "\n" +
            "not valid json\n" +
            json.dumps(_make_event(id="e3")) + "\n",
            encoding="utf-8"
        )
        result = db.import_audit_jsonl(tmp)
        assert result["events_imported"] == 2
        assert result["errors"] == 1


def test_import_jsonl_preserves_original_files():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        original = json.dumps(_make_event(id="e1")) + "\n"
        (audit_dir / "events.jsonl").write_text(original, encoding="utf-8")
        db.import_audit_jsonl(tmp)
        # Original file should still exist and have same content
        assert (audit_dir / "events.jsonl").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def test_summarize_phase():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        for i in range(3):
            db.insert_invocation(conn, _make_event(id=f"e{i}", phase_id="PHASE-1"))
        db.insert_invocation(conn, _make_event(id="eblock", phase_id="PHASE-1",
            event_type="commit_gate_blocked", result_status="blocked"))
        conn.commit()
        summary = db.summarize_phase(conn, "PHASE-1")
        assert summary is not None
        assert summary["invocation_count"] == 4
        assert summary["blocked_commit_count"] == 1
        _close_safe(conn)


def test_list_failures_by_project():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_failure(conn, _make_failure(id="fa", project_name="proj-a"))
        db.insert_failure(conn, _make_failure(id="fb", project_name="proj-b"))
        conn.commit()
        results = db.list_failures(conn, project_name="proj-a")
        assert len(results) == 1
        assert results[0]["id"] == "fa"
        _close_safe(conn)


def test_list_blocked_commits():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_invocation(conn, _make_event(id="b1", event_type="commit_gate_blocked", result_status="blocked", blocking=1))
        db.insert_invocation(conn, _make_event(id="ok1", event_type="mcp_invocation_finished", result_status="passed"))
        conn.commit()
        results = db.list_blocked_commits(conn)
        assert len(results) == 1
        assert results[0]["id"] == "b1"
        _close_safe(conn)


def test_list_rejected_recommendations():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_recommendation(conn, _make_recommendation(id="r-acc", decision="accepted"))
        db.insert_recommendation(conn, _make_recommendation(id="r-rej", decision="rejected"))
        conn.commit()
        results = db.list_rejected_recommendations(conn)
        assert len(results) >= 1
        assert any(r["id"] == "r-rej" for r in results)
        _close_safe(conn)


def test_tool_reliability_summary():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_invocation(conn, _make_event(id="t1", tool_name="local_check", result_status="passed"))
        db.insert_invocation(conn, _make_event(id="t2", tool_name="local_check", result_status="failed"))
        conn.commit()
        results = db.tool_reliability_summary(conn)
        assert len(results) >= 1
        check_row = [r for r in results if r["tool_name"] == "local_check"][0]
        assert check_row["total_calls"] == 2
        assert check_row["failure_count"] == 1
        _close_safe(conn)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

def test_does_not_store_raw_prompt_or_full_diff():
    """Insert should work, but forbidden fields in JSONL are handled by mcp_audit_logger.
    The DB just stores what it's given — it doesn't add raw content."""
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        # Record with legitimate fields only
        db.insert_invocation(conn, _make_event(id="safe-1", output_summary="ok", notes="nothing sensitive"))
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_invocation_log WHERE id='safe-1'").fetchone()
        assert row is not None
        _close_safe(conn)


# ---------------------------------------------------------------------------
# Windows paths
# ---------------------------------------------------------------------------

def test_windows_paths_supported():
    with tempfile.TemporaryDirectory() as tmp:
        db.init_audit_db(tmp)
        conn = _connect_tmp(tmp)
        db.insert_invocation(conn, _make_event(
            id="win-1",
            project_path="C:\\Users\\Zero\\local-llm-pipeline",
            files_involved=["C:\\Users\\Zero\\project\\tools\\mcp_gate.py"],
        ))
        conn.commit()
        row = conn.execute(
            "SELECT project_path, files_involved FROM mcp_invocation_log WHERE id='win-1'"
        ).fetchone()
        assert "Users" in row["project_path"]
        files = json.loads(row["files_involved"])
        assert "mcp_gate.py" in files[0]
        _close_safe(conn)


def test_db_path_respects_base_dir():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = db.get_audit_db_path(tmp)
        expected = Path(tmp) / ".mcp_audit" / "mcp_audit.db"
        assert db_path == expected


def test_db_path_respects_env_var(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        custom = Path(tmp) / "custom_dir"
        monkeypatch.setenv("MCP_AUDIT_DIR", str(custom))
        db_path = db.get_audit_db_path()
        assert db_path == custom / "mcp_audit.db"
