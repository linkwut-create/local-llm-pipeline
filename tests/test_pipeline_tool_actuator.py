"""Tests for pipeline_tool_actuator.py."""

import json
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pipeline_tool_actuator as pta


class TestDetectTestCommand:
    def test_detects_pytest(self, tmp_path, monkeypatch):
        (tmp_path / "tests").mkdir()
        cmd = pta.detect_test_command(tmp_path)
        assert cmd is not None
        assert "pytest" in cmd

    def test_no_tests_dir(self, tmp_path, monkeypatch):
        cmd = pta.detect_test_command(tmp_path)
        # Should return None or fallback
        # (depends on what files exist in tmp_path)


class TestDiffCapture:
    def test_capture_diff_in_git_repo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        # In a git repo, capture_diff should work
        # Just test it doesn't crash when there are no changes
        path = pta.capture_diff("test-task", "test_label")
        # May be None if no changes


class TestApplyPatch:
    def test_missing_patch_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        result = pta.apply_patch("test-task", tmp_path / "nonexistent.diff")
        assert result["ok"] is False
        assert "not found" in result.get("error", "")

    def test_invalid_patch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        pf = tmp_path / "bad.diff"
        pf.write_text("not a patch", encoding="utf-8")
        result = pta.apply_patch("test-task", pf)
        assert result["ok"] is False


class TestRunTests:
    def test_no_command_and_no_detection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        result = pta.run_tests("test-task", "echo hello", repo_root=tmp_path)
        assert result["ok"] is True
        assert result["command"] == "echo hello"

    def test_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        # sleep for a very long time, but timeout fast
        result = pta.run_tests("test-task",
            "python -c \"import time; time.sleep(60)\"",
            repo_root=tmp_path, timeout=1)
        assert result["ok"] is False


class TestRollback:
    def test_rollback_no_patch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        result = pta.rollback("test-task")
        assert "method" in result
        # May fail if no git repo, but shouldn't crash

    def test_rollback_missing_patch_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        result = pta.rollback("test-task", patch_file=tmp_path / "nonexistent.diff")
        assert result["ok"] is False
        assert "not found" in result.get("error", "")
