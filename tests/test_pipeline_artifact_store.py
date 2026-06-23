"""Tests for pipeline_artifact_store.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pipeline_artifact_store as store


class TestSaveArtifact:
    def test_save_writes_file_and_index(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_task_001"

        path = store.save_artifact(task_id, "test.json", '{"key":"value"}',
                                    artifact_type="test_run", tool_name="Bash",
                                    creator="qwen3-coder:30b")
        assert path.exists()
        assert path.name == "test.json"

        index = store.list_artifacts(task_id)
        assert len(index) == 1
        entry = index[0]
        assert entry["type"] == "test_run"
        assert entry["tool"] == "Bash"
        assert entry["creator"] == "qwen3-coder:30b"
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64

    def test_sha256_is_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_sha"

        p1 = store.save_artifact(task_id, "a.json", "hello")
        p2 = store.save_artifact(task_id, "b.json", "hello")

        idx = store.list_artifacts(task_id)
        assert idx[0]["sha256"] == idx[1]["sha256"]

    def test_sha256_differs_for_different_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_sha2"

        p1 = store.save_artifact(task_id, "a.json", "hello")
        p2 = store.save_artifact(task_id, "b.json", "world")

        idx = store.list_artifacts(task_id)
        assert idx[0]["sha256"] != idx[1]["sha256"]


class TestNameCollision:
    def test_collision_appends_sequence(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_collision"

        p1 = store.save_artifact(task_id, "log.txt", "first")
        p2 = store.save_artifact(task_id, "log.txt", "second")

        assert p1.name == "log.txt"
        assert p2.name == "log_001.txt"
        assert p1.read_text(encoding="utf-8") == "first"
        assert p2.read_text(encoding="utf-8") == "second"

    def test_multiple_collisions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_multi_collision"

        for i in range(5):
            store.save_artifact(task_id, "log.txt", f"entry {i}")

        idx = store.list_artifacts(task_id)
        names = [e["name"] for e in idx]
        assert "log.txt" in names
        assert "log_001.txt" in names
        assert "log_004.txt" in names
        assert len(names) == 5


class TestReadArtifacts:
    def test_read_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_read"

        store.save_artifact(task_id, "data.txt", "hello world")
        content = store.read_artifact(task_id, "data.txt")
        assert content == "hello world"

    def test_read_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        assert store.read_artifact("nonexistent", "x.txt") is None

    def test_find_by_type(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_find"

        store.save_artifact(task_id, "a.json", "", artifact_type="test_run")
        store.save_artifact(task_id, "b.json", "", artifact_type="git_diff")
        store.save_artifact(task_id, "c.json", "", artifact_type="test_run")

        test_runs = store.find_artifacts_by_type(task_id, "test_run")
        assert len(test_runs) == 2


class TestStatusUpdates:
    def test_mark_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_accept"

        store.save_artifact(task_id, "patch.diff", "-old\n+new",
                            artifact_type="patch_candidate")
        assert store.mark_accepted(task_id, "patch.diff", True) is True

        idx = store.list_artifacts(task_id)
        assert idx[0]["accepted"] is True

    def test_mark_verified(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_verify"

        store.save_artifact(task_id, "patch.diff", "-old\n+new")
        store.mark_verified(task_id, "patch.diff", True)

        idx = store.list_artifacts(task_id)
        assert idx[0]["verified"] is True

    def test_mark_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        assert store.mark_accepted("nonexistent", "x.txt") is False


class TestTaskReport:
    def test_report_empty_task(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "tasks_dir", lambda: tmp_path)
        task_id = "test_report"
        store.artifacts_dir(task_id).mkdir(parents=True, exist_ok=True)
        # Create minimal session.json
        session = {
            "task_id": task_id, "user_task": "fix bug",
            "created_at": "2026-06-23T00:00:00Z", "status": "active",
            "phase": "executing",
        }
        (store.task_dir(task_id) / "session.json").write_text(
            json.dumps(session), encoding="utf-8")

        report = store.generate_task_report(task_id)
        assert "Task Report" in report
        assert "fix bug" in report
        assert "Artifacts: 0 total" in report
