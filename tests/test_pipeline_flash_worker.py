"""Tests for pipeline_flash_worker.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pipeline_flash_worker as fw


class TestFlashWorkers:
    def test_three_workers_registered(self):
        names = {w.name for w in (fw.test_failure_analyzer, fw.patch_worker, fw.diff_reviewer)}
        assert "flash_test_failure_analyzer" in names
        assert "flash_patch_worker" in names
        assert "flash_diff_reviewer" in names

    def test_patch_worker_forbids_apply(self):
        assert "apply" in fw.patch_worker.forbidden_actions
        assert "commit" in fw.patch_worker.forbidden_actions

    def test_all_forbid_commit_push_deploy(self):
        for w in (fw.test_failure_analyzer, fw.patch_worker, fw.diff_reviewer):
            for banned in ("commit", "push", "deploy"):
                assert banned in w.forbidden_actions, f"{w.name} missing {banned}"

    def test_failure_analyzer_output_schema(self):
        c = fw.test_failure_analyzer
        assert "failure_hypotheses" in c.output_schema["required"]
        assert "repair_strategy" in c.output_schema["required"]

    def test_patch_worker_output_requires_patch(self):
        c = fw.patch_worker
        assert "patch" in c.output_schema["required"]
        assert "explanation" in c.output_schema["required"]


class TestUnifiedDiffValidator:
    def test_valid_diff_with_hunk(self):
        diff = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 old line
+new line
 unchanged"""
        assert fw.is_unified_diff(diff) is True

    def test_valid_diff_with_diff_header(self):
        diff = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-old
+new"""
        assert fw.is_unified_diff(diff) is True

    def test_not_a_diff(self):
        assert fw.is_unified_diff("just some text") is False

    def test_empty_not_a_diff(self):
        assert fw.is_unified_diff("") is False

    def test_none_not_a_diff(self):
        assert fw.is_unified_diff(None) is False


class TestValidatePatch:
    def test_simple_patch_valid(self):
        patch = "--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new"
        valid, reason = fw.validate_patch(patch)
        assert valid is True

    def test_non_diff_rejected(self):
        valid, reason = fw.validate_patch("not a patch")
        assert valid is False
        assert "unified diff" in reason

    def test_env_file_rejected(self):
        patch = "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-old\n+new"
        valid, reason = fw.validate_patch(patch)
        assert valid is False
        assert "sensitive" in reason.lower()

    def test_key_file_rejected(self):
        patch = "--- a/id_rsa\n+++ b/id_rsa\n@@ -1 +1 @@\n-old\n+new"
        valid, reason = fw.validate_patch(patch)
        assert valid is False

    def test_shell_injection_rejected(self):
        patch = """--- a/script.sh
+++ b/script.sh
@@ -1 +1 @@
-old
+; rm -rf /tmp/important"""
        valid, reason = fw.validate_patch(patch)
        assert valid is False
        assert "suspicious" in reason.lower()

    def test_empty_patch_rejected(self):
        valid, reason = fw.validate_patch("")
        assert valid is False


class TestRunFlashWorker:
    def test_unknown_worker_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        result = fw.run_flash_worker("nonexistent", "task-001", {})
        assert result is None
