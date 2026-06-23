"""Tests for pipeline_local_worker.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import pipeline_local_worker as pw


class TestWorkerRegistry:
    def test_all_workers_registered(self):
        assert len(pw.WORKERS) >= 4
        for name in ("log_summary", "file_summary", "diff_review", "repo_map"):
            assert name in pw.WORKERS, f"missing worker: {name}"

    def test_registry_is_read_only_via_register(self):
        contract = pw.WORKERS["log_summary"]
        assert contract.name == "log_summary"
        assert contract.artifact_type == "log_summary"


class TestWorkerContracts:
    def test_log_summary_contract(self):
        c = pw.WORKERS["log_summary"]
        assert "stderr" in c.input_schema["required"]
        assert "failure_type" in c.output_schema["required"]
        assert c.forbidden_actions == ("edit", "write", "commit", "push", "deploy")

    def test_file_summary_contract(self):
        c = pw.WORKERS["file_summary"]
        assert "path" in c.input_schema["required"]
        assert "purpose" in c.output_schema["required"]
        assert c.max_input_chars == 100000

    def test_diff_review_contract(self):
        c = pw.WORKERS["diff_review"]
        assert "diff_text" in c.input_schema["required"]
        assert "recommendation" in c.output_schema["required"]
        assert c.timeout_sec == 180

    def test_repo_map_contract(self):
        c = pw.WORKERS["repo_map"]
        assert "file_list" in c.input_schema["required"]
        assert "subsystems" in c.output_schema["required"]

    def test_all_workers_forbid_edit(self):
        for name, c in pw.WORKERS.items():
            assert "edit" in c.forbidden_actions, f"{name} should forbid edit"
            assert "write" in c.forbidden_actions, f"{name} should forbid write"

    def test_all_workers_have_schemas(self):
        for name, c in pw.WORKERS.items():
            assert isinstance(c.input_schema, dict), f"{name} input_schema not dict"
            assert isinstance(c.output_schema, dict), f"{name} output_schema not dict"


class TestRunWorker:
    def test_run_unknown_worker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tmp_path))
        result = pw.run_worker("nonexistent", "task-001", {})
        assert result is None

    def test_list_workers(self):
        import io, contextlib
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            for name in pw.WORKERS:
                print(f"  {name}")
        output = stdout.getvalue()
        for name in ("log_summary", "file_summary", "diff_review", "repo_map"):
            assert name in output


class TestWorkerContractSerialization:
    def test_contract_asdict(self):
        from dataclasses import asdict
        c = pw.WORKERS["log_summary"]
        d = asdict(c)
        assert d["name"] == "log_summary"
        assert "input_schema" in d
        assert "output_schema" in d
        # Can be serialized to JSON
        json.dumps(d, default=str)
