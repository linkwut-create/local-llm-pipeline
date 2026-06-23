"""Tests for agentdb.py — minimal SQLite pipeline database."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import agentdb


class TestInit:
    def test_init_creates_db(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        result = agentdb.init_db()
        assert db.exists()
        assert "initialized" in result

    def test_init_idempotent(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.init_db()  # should not crash
        assert db.exists()


class TestUpsertTask:
    def test_insert_and_query(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.upsert_task("task-001", status="active", phase="planning",
                             user_task="fix bug", created_at="2026-01-01T00:00:00Z")
        data = agentdb.query_task("task-001")
        assert data is not None
        assert data["status"] == "active"
        assert data["phase"] == "planning"

    def test_update_existing(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.upsert_task("task-001", status="active", created_at="2026-01-01T00:00:00Z")
        agentdb.upsert_task("task-001", status="completed", phase="complete")
        data = agentdb.query_task("task-001")
        assert data["status"] == "completed"
        assert data["phase"] == "complete"

    def test_query_nonexistent(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        assert agentdb.query_task("nonexistent") is None


class TestArtifacts:
    def test_insert_artifact(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.upsert_task("task-001", status="active", created_at="now")
        agentdb.insert_artifact("task-001", {
            "name": "test.json", "type": "test_run", "tool": "Bash",
            "size_bytes": 100, "sha256": "abc123", "creator": "qwen",
            "accepted": True, "verified": True,
            "created_at": "2026-01-01T00:00:00Z",
        })
        data = agentdb.query_task("task-001")
        assert len(data["artifacts"]) == 1
        assert data["artifacts"][0]["name"] == "test.json"
        assert data["artifacts"][0]["accepted"] == 1


class TestModelCalls:
    def test_insert_model_call(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.upsert_task("task-001", status="active", created_at="now")
        agentdb.insert_model_call("task-001", {
            "model": "qwen3.6-deep", "role": "qwen", "round": "initial",
            "latency_sec": 2.5, "input_chars": 1000, "output_chars": 200,
            "ok": True, "error": None,
        })
        data = agentdb.query_task("task-001")
        assert len(data["model_calls"]) == 1
        assert data["model_calls"][0]["model"] == "qwen3.6-deep"


class TestDecisions:
    def test_insert_decision(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.upsert_task("task-001", status="active", created_at="now")
        agentdb.insert_decision("task-001", {
            "decision": "accept", "reason": "patch looks correct",
            "accepted_patch_id": "patch_001.diff", "requires_more_tests": False,
            "created_at": "2026-01-01T00:00:00Z",
        })
        data = agentdb.query_task("task-001")
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["decision"] == "accept"


class TestCosts:
    def test_insert_and_query_costs(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        # Need a task first due to FK constraint
        agentdb.upsert_task("task-001", status="active", created_at="2026-01-01T00:00:00Z")
        agentdb.insert_cost("task-001", "claude-fable-5", 5000, 500, 0.075, "anthropic")
        agentdb.insert_cost("task-001", "deepseek-v4-flash", 2000, 300, 0.001, "deepseek")
        data = agentdb.query_costs()
        assert data["total_cost"] > 0, f"Expected non-zero cost, got {data}"
        assert len(data["by_model"]) == 2

    def test_costs_zero_when_empty(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        data = agentdb.query_costs()
        assert data["total_cost"] == 0


class TestRecent:
    def test_recent_returns_tasks(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        agentdb.upsert_task("task-001", status="active", created_at="2026-06-01T00:00:00Z")
        agentdb.upsert_task("task-002", status="completed", created_at="2026-06-02T00:00:00Z")
        tasks = agentdb.query_recent(5)
        assert len(tasks) == 2

    def test_recent_respects_limit(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        for i in range(10):
            agentdb.upsert_task(f"task-{i:03d}", status="active",
                                 created_at=f"2026-06-{i+1:02d}T00:00:00Z")
        tasks = agentdb.query_recent(3)
        assert len(tasks) == 3


class TestDBFailureIsolation:
    """DB writes must never crash — they are advisory only."""

    def test_insert_on_closed_db_does_not_raise(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        agentdb.init_db()
        # Insert with bad data should not raise
        agentdb.upsert_task(None)  # type: ignore
        # No exception = pass


class TestImportTask:
    def test_import_from_filesystem(self, tmp_path, monkeypatch):
        db = tmp_path / "test.sqlite"
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        # Create a fake task directory
        task_dir = tmp_path / "tasks" / "import-test-001"
        task_dir.mkdir(parents=True)
        (task_dir / "artifacts").mkdir()
        (task_dir / "session.json").write_text(json.dumps({
            "task_id": "import-test-001", "status": "active",
            "user_task": "fix import bug", "phase": "executing",
            "created_at": "2026-06-01T00:00:00Z",
            "messages": [{"role": "user", "content": "fix it",
                          "timestamp": "2026-06-01T00:00:01Z"}],
        }), encoding="utf-8")
        (task_dir / "route.json").write_text(json.dumps({
            "recommended_route": "pro_execute_allowed",
        }), encoding="utf-8")
        (task_dir / "artifacts" / "artifact_index.json").write_text(json.dumps([
            {"name": "test.json", "type": "test_run", "sha256": "abc",
             "created_at": "2026-06-01T00:00:02Z"},
        ]), encoding="utf-8")

        # Point db and tasks at tmp_path
        monkeypatch.setenv("LOCAL_LLM_AGENTDB_PATH", str(db))
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path / "tasks"))
        agentdb.init_db()

        result = agentdb.import_task("import-test-001")
        assert "import-test-001" in result
        data = agentdb.query_task("import-test-001")
        assert data is not None
        assert len(data["artifacts"]) == 1
