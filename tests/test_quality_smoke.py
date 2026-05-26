"""Tests for Z-2: local model output quality smoke.

Covers CLI parsing, battery selection, heuristic checks, report schema,
exit codes, output-dir behavior, and boundary invariants.
All tests are mocked — no real model calls, no Ollama required.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))

import quality_smoke as qs


# ── Helpers ───────────────────────────────────────────────────────────

def _mock_worker_output(**overrides):
    """Build a realistic worker output dict for testing checks."""
    data = {
        "task": "summarize-file",
        "tool": "summarize-file",
        "profile": "fast_summary",
        "model": "gemma4:e4b",
        "provider": "ollama",
        "ok": True,
        "summary": "This file defines a ModelCallResult dataclass for token usage tracking.",
        "result": "## Summary\n\nThis file defines the `ModelCallResult` dataclass.\n\n"
                  "Key functions: `normalize_usage()` maps provider-specific usage fields.\n\n"
                  "Tests: `tests/test_model_call_result.py`.",
        "confidence": "medium",
        "error": None,
        "error_type": None,
        "created_at": "2026-05-27T12:00:00+00:00",
    }
    data.update(overrides)
    return data


def _mock_subprocess_result(stdout="", stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def _write_fake_worker_output(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── CLI parsing ────────────────────────────────────────────────────────

class TestCLIParsing:
    def test_defaults(self):
        args = qs.parse_args([])
        assert args.battery == "default"
        assert args.timeout == 120
        assert args.profile == "fast_summary"
        assert args.review_profile == "commit_reviewer"
        assert args.test_plan_profile == "code_worker"
        assert not args.json_output

    def test_battery_quick(self):
        args = qs.parse_args(["--battery", "quick"])
        assert args.battery == "quick"

    def test_battery_full(self):
        args = qs.parse_args(["--battery", "full"])
        assert args.battery == "full"

    def test_battery_invalid_rejected(self):
        with pytest.raises(SystemExit):
            qs.parse_args(["--battery", "invalid"])

    def test_json_flag(self):
        args = qs.parse_args(["--json"])
        assert args.json_output

    def test_profile_override(self):
        args = qs.parse_args(["--profile", "deep_reviewer"])
        assert args.profile == "deep_reviewer"

    def test_model_override(self):
        args = qs.parse_args(["--model", "qwen3-coder:30b"])
        assert args.model == "qwen3-coder:30b"

    def test_timeout_override(self):
        args = qs.parse_args(["--timeout", "60"])
        assert args.timeout == 60

    def test_review_profile_override(self):
        args = qs.parse_args(["--review-profile", "deep_reviewer"])
        assert args.review_profile == "deep_reviewer"

    def test_test_plan_profile_override(self):
        args = qs.parse_args(["--test-plan-profile", "reasoning_checker"])
        assert args.test_plan_profile == "reasoning_checker"

    def test_output_dir_override(self):
        args = qs.parse_args(["--output-dir", "/tmp/smoke"])
        assert args.output_dir == "/tmp/smoke"


# ── Battery selection ──────────────────────────────────────────────────

class TestBatterySelection:
    def test_default_has_four_entries(self):
        assert len(qs.BATTERY_DEFAULT) == 4

    def test_quick_has_two_entries(self):
        assert len(qs.BATTERY_QUICK) == 2

    def test_full_equals_default(self):
        assert qs.BATTERY_FULL == qs.BATTERY_DEFAULT

    def test_all_entries_have_required_keys(self):
        for entry in qs.BATTERY_DEFAULT:
            assert "task" in entry
            assert "label" in entry
            assert "args" in entry
            assert "keywords" in entry
            assert "ceiling_ms" in entry
            assert "min_chars" in entry

    def test_tasks_are_valid(self):
        valid = {"summarize-file", "review-diff", "generate-test-plan"}
        for entry in qs.BATTERY_DEFAULT:
            assert entry["task"] in valid

    def test_quick_is_summarize_only(self):
        for entry in qs.BATTERY_QUICK:
            assert entry["task"] == "summarize-file"


# ── Heuristic checks ───────────────────────────────────────────────────

class TestCheckEmpty:
    def test_pass_normal_content(self):
        data = _mock_worker_output(result="This is a valid summary with enough content to pass the minimum character threshold.")
        result = qs._check_empty(data, 50)
        assert result["result"] == "pass"

    def test_fail_very_short(self):
        data = _mock_worker_output(result="Hi")
        result = qs._check_empty(data, 50)
        assert result["result"] == "fail"

    def test_fail_worker_not_ok(self):
        data = _mock_worker_output(ok=False, error="model not found")
        result = qs._check_empty(data, 50)
        assert result["result"] == "fail"

    def test_warn_below_minimum(self):
        data = _mock_worker_output(result="Short but acceptable summary text here.")
        result = qs._check_empty(data, 200)
        assert result["result"] == "warn"


class TestCheckOffTarget:
    def test_pass_target_and_keywords_found(self):
        data = _mock_worker_output(
            result="model_call_result.py defines the ModelCallResult dataclass for usage tracking.",
            summary="File: model_call_result.py")
        result = qs._check_off_target(data, ["ModelCallResult", "dataclass"], "tools/model_call_result.py")
        assert result["result"] == "pass"

    def test_fail_no_target_no_keywords(self):
        data = _mock_worker_output(
            result="This is a general discussion about Python programming.",
            summary="General Python")
        result = qs._check_off_target(data, ["specific", "unique"], "nonexistent_file.py")
        assert result["result"] == "fail"

    def test_warn_target_missing_but_keywords_present(self):
        data = _mock_worker_output(
            result="The ModelCallResult dataclass handles usage tracking.",
            summary="Data class for usage")
        result = qs._check_off_target(data, ["ModelCallResult", "dataclass"], "tools/model_call_result.py")
        assert result["result"] == "warn"


class TestCheckMalformedJSON:
    def test_pass_plain_text(self):
        data = _mock_worker_output(result="This is plain text, not JSON.")
        result = qs._check_malformed_json(data)
        assert result["result"] == "pass"

    def test_pass_valid_json_string(self):
        data = _mock_worker_output(result=json.dumps({"key": "value"}))
        result = qs._check_malformed_json(data)
        assert result["result"] == "pass"

    def test_fail_looks_like_json_but_invalid(self):
        data = _mock_worker_output(result="{this is not valid json")
        result = qs._check_malformed_json(data)
        assert result["result"] == "fail"


class TestCheckConfidence:
    def test_pass_high(self):
        result = qs._check_confidence({"confidence": "high"})
        assert result["result"] == "pass"

    def test_pass_medium(self):
        result = qs._check_confidence({"confidence": "medium"})
        assert result["result"] == "pass"

    def test_warn_low(self):
        result = qs._check_confidence({"confidence": "low"})
        assert result["result"] == "warn"

    def test_fail_missing(self):
        result = qs._check_confidence({})
        assert result["result"] == "fail"

    def test_fail_invalid(self):
        result = qs._check_confidence({"confidence": "certain"})
        assert result["result"] == "fail"


class TestCheckHallucination:
    def _real(self):
        return {"model_call_result.py", "test_model_call_result.py",
                "quality_smoke.py", "call_ledger.py", "conftest.py"}

    def test_pass_no_fabricated(self):
        data = _mock_worker_output(
            result="See `model_call_result.py` and `call_ledger.py` for details.")
        result = qs._check_hallucination(data, self._real())
        assert result["result"] == "pass"

    def test_warn_one_fabricated(self):
        data = _mock_worker_output(
            result="See `fake_file.py` for the implementation.")
        result = qs._check_hallucination(data, self._real())
        assert result["result"] == "warn"

    def test_fail_many_fabricated(self):
        data = _mock_worker_output(
            result="Files: `a.py`, `b.py`, `c.py`, `d.py` are all relevant.")
        result = qs._check_hallucination(data, self._real())
        assert result["result"] == "fail"


class TestCheckLatency:
    def test_pass_within_ceiling(self):
        result = qs._check_latency(30000, 120000)
        assert result["result"] == "pass"

    def test_warn_above_ceiling(self):
        result = qs._check_latency(130000, 120000)
        assert result["result"] == "warn"

    def test_fail_way_above_ceiling(self):
        result = qs._check_latency(200000, 120000)
        assert result["result"] == "fail"


# ── Report schema ──────────────────────────────────────────────────────

class TestReportSchema:
    def test_report_has_required_top_level_keys(self):
        report = qs._build_report([], "fast_summary", "", "default", "abc1234")
        required = {"smoke_version", "generated_at", "baseline_commit",
                     "baseline_version", "battery", "profile", "model",
                     "summary", "calls", "advisory_only", "not_a_gate"}
        assert set(report.keys()) >= required

    def test_report_advisory_only(self):
        report = qs._build_report([], "fast_summary", "", "default", "abc1234")
        assert report["advisory_only"] is True
        assert report["not_a_gate"] is True

    def test_report_summary_all_pass(self):
        cr = [{"checks": [{"result": "pass"}, {"result": "pass"}]}]
        report = qs._build_report(cr, "fast_summary", "", "default", "abc1234")
        assert report["summary"]["overall"] == "pass"
        assert report["summary"]["failed"] == 0

    def test_report_summary_with_fail(self):
        cr = [{"checks": [{"result": "pass"}, {"result": "fail"}]}]
        report = qs._build_report(cr, "fast_summary", "", "default", "abc1234")
        assert report["summary"]["overall"] == "degraded"
        assert report["summary"]["failed"] == 1

    def test_report_summary_with_warns(self):
        cr = [{"checks": [{"result": "pass"}, {"result": "warn"}]}]
        report = qs._build_report(cr, "fast_summary", "", "default", "abc1234")
        assert report["summary"]["overall"] == "pass"
        assert report["summary"]["warned"] == 1

    def test_report_smoke_version(self):
        report = qs._build_report([], "fast_summary", "", "default", "abc1234")
        assert report["smoke_version"] == 1


# ── Exit code behavior ─────────────────────────────────────────────────

class TestExitCodes:
    def test_main_exit_0_on_all_pass(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        with patch.object(qs, "_run_one") as mock_run:
            mock_run.return_value = {
                "task": "summarize-file", "label": "test", "profile": "p", "model": "m",
                "duration_ms": 1000, "output_path": str(outdir / "out.json"),
                "worker_ok": True,
                "checks": [{"check": "empty_output", "result": "pass",
                            "detail": "content: 200 chars"}],
            }
            with patch.object(qs, "_get_baseline_commit", return_value="abc1234"):
                rc = qs.main(["--battery", "quick", "--output-dir", str(outdir)])
            assert rc == 0

    def test_main_exit_1_on_fail(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        with patch.object(qs, "_run_one") as mock_run:
            mock_run.return_value = {
                "task": "summarize-file", "label": "test", "profile": "p", "model": "m",
                "duration_ms": 1000, "output_path": str(outdir / "out.json"),
                "worker_ok": True,
                "checks": [{"check": "empty_output", "result": "fail",
                            "detail": "content: 5 chars"}],
            }
            with patch.object(qs, "_get_baseline_commit", return_value="abc1234"):
                rc = qs.main(["--battery", "quick", "--output-dir", str(outdir)])
            assert rc == 1

    def test_main_exit_0_on_warn_only(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        with patch.object(qs, "_run_one") as mock_run:
            mock_run.return_value = {
                "task": "summarize-file", "label": "test", "profile": "p", "model": "m",
                "duration_ms": 1000, "output_path": str(outdir / "out.json"),
                "worker_ok": True,
                "checks": [{"check": "empty_output", "result": "warn",
                            "detail": "content: 80 chars"}],
            }
            with patch.object(qs, "_get_baseline_commit", return_value="abc1234"):
                rc = qs.main(["--battery", "quick", "--output-dir", str(outdir)])
            assert rc == 0

    def test_model_override_passed_to_run_one(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        with patch.object(qs, "_run_one") as mock_run:
            mock_run.return_value = {
                "task": "t", "label": "l", "profile": "p", "model": "qwen3-coder:30b",
                "duration_ms": 0, "output_path": str(outdir / "x.json"),
                "worker_ok": True, "checks": [{"check": "e", "result": "pass", "detail": ""}],
            }
            with patch.object(qs, "_get_baseline_commit", return_value="abc1234"):
                qs.main(["--battery", "quick", "--output-dir", str(outdir),
                         "--model", "qwen3-coder:30b"])
            assert mock_run.call_count == 2
            for call_args in mock_run.call_args_list:
                assert call_args[0][2] == "qwen3-coder:30b"


# ── Real calls (mocked subprocess) ─────────────────────────────────────

class TestRunOne:
    def test_run_one_success(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        outdir.mkdir(parents=True, exist_ok=True)
        out_path = outdir / "test_out.json"
        worker_data = _mock_worker_output()
        _write_fake_worker_output(out_path, worker_data)

        entry = {
            "task": "summarize-file",
            "label": "test entry",
            "args": [str(Path("tools/model_call_result.py"))],
            "keywords": ["ModelCallResult", "dataclass"],
            "ceiling_ms": 120_000,
            "min_chars": 50,
        }

        mock_result = _mock_subprocess_result(stdout=json.dumps(worker_data))

        with patch.object(qs, "OUT_DIR", outdir):
            with patch.object(subprocess, "run", return_value=mock_result):
                with patch.object(qs, "_load_output", return_value=worker_data):
                    with patch.object(qs, "_collect_real_paths",
                                      return_value={"model_call_result.py", "conftest.py"}):
                        result = qs._run_one(entry, "fast_summary", "", 120)

        assert result["task"] == "summarize-file"
        assert result["worker_ok"] is True
        assert len(result["checks"]) == 6
        for c in result["checks"]:
            assert c["result"] in ("pass", "warn", "fail")

    def test_run_one_timeout(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        outdir.mkdir(parents=True, exist_ok=True)

        entry = {
            "task": "summarize-file",
            "label": "test entry",
            "args": [str(Path("tools/model_call_result.py"))],
            "keywords": ["ModelCallResult"],
            "ceiling_ms": 120_000,
            "min_chars": 50,
        }

        with patch.object(qs, "OUT_DIR", outdir):
            with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
                result = qs._run_one(entry, "fast_summary", "", 30)

        assert result["worker_ok"] is False
        assert result["worker_error"] == "timeout"


# ── Output directory ───────────────────────────────────────────────────

class TestOutputDir:
    def test_output_dir_created(self, tmp_path):
        outdir = tmp_path / "nonexistent" / "smoke"
        with patch.object(qs, "_run_one") as mock_run:
            mock_run.return_value = {
                "task": "t", "label": "l", "profile": "p", "model": "m",
                "duration_ms": 0, "output_path": str(outdir / "x.json"),
                "worker_ok": True, "checks": [{"check": "e", "result": "pass", "detail": ""}],
            }
            with patch.object(qs, "_get_baseline_commit", return_value="abc1234"):
                rc = qs.main(["--battery", "quick", "--output-dir", str(outdir)])
            assert rc == 0
        assert outdir.exists()

    def test_report_written_to_output_dir(self, tmp_path):
        outdir = tmp_path / "smoke_out"
        with patch.object(qs, "_run_one") as mock_run:
            mock_run.return_value = {
                "task": "t", "label": "l", "profile": "p", "model": "m",
                "duration_ms": 0, "output_path": str(outdir / "x.json"),
                "worker_ok": True, "checks": [{"check": "e", "result": "pass", "detail": ""}],
            }
            with patch.object(qs, "_get_baseline_commit", return_value="abc1234"):
                qs.main(["--battery", "quick", "--output-dir", str(outdir)])
        reports = list(outdir.glob("smoke_report_*.json"))
        assert len(reports) == 1
        data = json.loads(reports[0].read_text(encoding="utf-8"))
        assert data["advisory_only"] is True


# ── Boundary invariants ────────────────────────────────────────────────

class TestBoundaries:
    def test_no_mcp_import(self):
        """quality_smoke.py must not import MCP server or register as a tool."""
        source = (SCRIPT_DIR / "quality_smoke.py").read_text(encoding="utf-8")
        assert "TOOLS" not in source
        assert "TOOL_HANDLERS" not in source
        assert "local_llm_mcp_server" not in source

    def test_no_hook_import(self):
        source = (SCRIPT_DIR / "quality_smoke.py").read_text(encoding="utf-8")
        assert "claude_hooks" not in source
        assert "mcp_gate" not in source

    def test_smoke_version_is_int(self):
        assert isinstance(qs.SMOKE_VERSION, int)
        assert qs.SMOKE_VERSION >= 1

    def test_valid_confidence_set(self):
        assert qs._VALID_CONFIDENCE == {"high", "medium", "low"}

    def test_output_not_in_source_tree(self, tmp_path):
        outdir = tmp_path / "smoke"
        assert "tools" not in str(outdir)
        assert str(PROJECT_ROOT) not in str(outdir) or ".local_llm_out" in str(outdir)


# ── PROJECT_ROOT constant ──────────────────────────────────────────────

PROJECT_ROOT = SCRIPT_DIR.parent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
