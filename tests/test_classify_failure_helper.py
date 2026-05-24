"""Tests for E-B.2: manual test-failure CLI helper.

Covers CLI parsing, input validation, worker call mocking, output schema,
privacy/truncation, file inputs, stdin-json, boundary invariants, and
run_checks.py suggestion line.

No Ollama required — router calls are mocked away.
"""

import json
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))

import classify_failure_helper as helper

# ── Helpers ───────────────────────────────────────────────────────────

def _mock_worker_result(failure_class="assertion", confidence="high",
                        summary="Test failed.", likely_cause="Logic error.",
                        files_to_inspect=None, recommended_action="Check it."):
    """Build a mock worker classification dict."""
    return {
        "ok": True,
        "failure_class": failure_class,
        "confidence": confidence,
        "summary": summary,
        "likely_cause": likely_cause,
        "files_to_inspect": files_to_inspect or ["tests/test_x.py"],
        "recommended_action": recommended_action,
        "advisory_only": True,
    }


def _mock_router_output(classification=None, returncode=0, stderr=""):
    """Build a mock router output file JSON matching the router's format."""
    if classification is None:
        classification = _mock_worker_result()
    # Router writes a wrapper with result.result containing the classification JSON string
    return {
        "ok": True,
        "result": {
            "result": json.dumps(classification),
            "ok": True,
            "summary": "mock",
            "confidence": "medium",
        },
        "error": None,
    }


def _mock_router_output_fenced(classification=None):
    """Build a mock router output where result.result is fenced JSON (real worker format)."""
    if classification is None:
        classification = _mock_worker_result()
    fenced = "```json\n" + json.dumps(classification) + "\n```"
    return {
        "ok": True,
        "result": {
            "result": fenced,
            "ok": True,
            "summary": "mock",
            "confidence": "medium",
        },
        "error": None,
    }


def _write_mock_output(output: dict):
    """Write a mock router output JSON to .local_llm_out/."""
    out_dir = helper.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = "20260525_120000"
    path = out_dir / f"{ts}_classify-test-failure.json"
    path.write_text(json.dumps(output), encoding="utf-8")
    # Touch to ensure mtime is set
    path.touch()


# ── A. Classification result parsing ──────────────────────────────────

class TestClassificationParsing:
    def test_parse_worker_result_from_file(self, tmp_path):
        classification = _mock_worker_result("assertion", "high")
        output = _mock_router_output(classification)
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "assertion"
        assert result["confidence"] == "high"
        assert result["advisory_only"] is True

    def test_parse_worker_result_nested_dict_form(self, tmp_path):
        classification = _mock_worker_result("syntax_error", "high")
        output = _mock_router_output(classification)
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "syntax_error"

    def test_parse_worker_result_unknown_class_fallback(self, tmp_path):
        classification = _mock_worker_result("bogus_class", "medium")
        output = _mock_router_output(classification)
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        # parse_worker_result returns raw worker dict; validation is in classify_failure
        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "bogus_class"  # raw from worker

    def test_parse_fenced_json_string(self, tmp_path):
        """E-C.1: parse_worker_result handles ```json fenced JSON."""
        classification = _mock_worker_result("assertion", "high")
        output = _mock_router_output_fenced(classification)
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "assertion"
        assert result["confidence"] == "high"

    def test_parse_fenced_json_uppercase(self, tmp_path):
        """E-C.1: parse_worker_result handles ```JSON (uppercase)."""
        classification = _mock_worker_result("import_error", "high")
        fenced = "```JSON\n" + json.dumps(classification) + "\n```"
        output = {
            "ok": True,
            "result": {"result": fenced, "ok": True},
            "error": None,
        }
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "import_error"

    def test_parse_bare_fence(self, tmp_path):
        """E-C.1: parse_worker_result handles bare ``` fence (no language tag)."""
        classification = _mock_worker_result("dependency", "high")
        fenced = "```\n" + json.dumps(classification) + "\n```"
        output = {
            "ok": True,
            "result": {"result": fenced, "ok": True},
            "error": None,
        }
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "dependency"

    def test_pure_json_still_works(self, tmp_path):
        """E-C.1: pure JSON string (existing format) still works."""
        classification = _mock_worker_result("syntax_error", "high")
        output = _mock_router_output(classification)  # non-fenced
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is not None
        assert result["failure_class"] == "syntax_error"

    def test_malformed_fenced_json_returns_none(self, tmp_path):
        """E-C.1: malformed fenced JSON safely returns None."""
        output = {
            "ok": True,
            "result": "```json\nnot valid json\n```",
            "error": None,
        }
        out_file = tmp_path / "out.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        result = helper.parse_worker_result("", str(out_file))
        assert result is None

    def test_parse_worker_result_missing_file(self):
        result = helper.parse_worker_result("", "nonexistent.json")
        assert result is None


# ── B. Input validation ───────────────────────────────────────────────

class TestInputValidation:
    def test_missing_all_inputs(self):
        args = helper.parse_args([])
        err = helper.validate_inputs(args)
        assert err is not None
        assert err["ok"] is False
        assert err["error_type"] == "invalid_input"
        assert err["exit_code"] == 2

    def test_empty_stderr_and_stdout(self):
        args = helper.parse_args(["--stderr", "", "--stdout", ""])
        err = helper.validate_inputs(args)
        assert err is not None
        assert err["exit_code"] == 2

    def test_stderr_and_stderr_file_mutually_exclusive(self):
        args = helper.parse_args(["--stderr", "x", "--stderr-file", "/tmp/x.txt"])
        err = helper.validate_inputs(args)
        assert err is not None
        assert err["exit_code"] == 2

    def test_stdout_and_stdout_file_mutually_exclusive(self):
        args = helper.parse_args(["--stdout", "x", "--stdout-file", "/tmp/x.txt"])
        err = helper.validate_inputs(args)
        assert err is not None
        assert err["exit_code"] == 2

    def test_stdin_json_mixed_with_direct_args_rejected(self):
        args = helper.parse_args(["--stdin-json", "--stderr", "x"])
        err = helper.validate_inputs(args)
        assert err is not None
        assert err["exit_code"] == 2

    def test_valid_stderr_only(self):
        args = helper.parse_args(["--stderr", "AssertionError"])
        err = helper.validate_inputs(args)
        assert err is None

    def test_valid_stdout_only(self):
        args = helper.parse_args(["--stdout", "some output"])
        err = helper.validate_inputs(args)
        assert err is None

    def test_valid_stderr_file(self, tmp_path):
        f = tmp_path / "err.txt"
        f.write_text("AssertionError: assert 2 == 3")
        args = helper.parse_args(["--stderr-file", str(f)])
        err = helper.validate_inputs(args)
        assert err is None
        assert "assert 2 == 3" in args._stderr_text

    def test_stderr_file_missing(self):
        args = helper.parse_args(["--stderr-file", "/nonexistent/path.txt"])
        err = helper.validate_inputs(args)
        assert err is not None
        assert err["exit_code"] == 2


# ── C. Truncation ─────────────────────────────────────────────────────

class TestTruncation:
    def test_stderr_within_limit_not_truncated(self):
        payload, info = helper.truncate_and_build_payload("short err", "", None, "", [])
        assert info["truncated"] is False
        assert payload["stderr"] == "short err"

    def test_stderr_exceeds_limit_truncated(self):
        big = "x" * (helper._STDERR_MAX_CHARS + 100)
        payload, info = helper.truncate_and_build_payload(big, "", None, "", [])
        assert info["truncated"] is True
        assert len(payload["stderr"]) == helper._STDERR_MAX_CHARS
        assert info["input_lengths"]["stderr"] == helper._STDERR_MAX_CHARS + 100

    def test_stdout_truncated(self):
        big = "y" * (helper._STDOUT_MAX_CHARS + 50)
        payload, info = helper.truncate_and_build_payload("err", big, None, "", [])
        assert info["truncated"] is True
        assert len(payload["stdout"]) == helper._STDOUT_MAX_CHARS

    def test_test_command_truncated(self):
        long_cmd = "pytest " + "x" * helper._TEST_COMMAND_MAX_CHARS
        payload, info = helper.truncate_and_build_payload("err", "", None, long_cmd, [])
        assert info["truncated"] is True
        assert len(payload["test_command"]) == helper._TEST_COMMAND_MAX_CHARS

    def test_changed_files_truncated(self):
        many = [f"file_{i}.py" for i in range(helper._CHANGED_FILES_MAX + 10)]
        payload, info = helper.truncate_and_build_payload("err", "", None, "", many)
        assert info["truncated"] is True
        assert len(payload["changed_files"]) == helper._CHANGED_FILES_MAX

    def test_input_lengths_recorded(self):
        payload, info = helper.truncate_and_build_payload("hello", "world", 1, "cmd", ["a.py"])
        assert info["input_lengths"]["stderr"] == 5
        assert info["input_lengths"]["stdout"] == 5
        assert info["input_lengths"]["test_command"] == 3
        assert info["input_lengths"]["changed_files"] == 1


# ── D. stdin-json parsing ─────────────────────────────────────────────

class TestStdinJson:
    def test_valid_stdin_json(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(
            json.dumps({"stderr": "AssertionError", "exit_code": 1})))
        result = helper.parse_stdin_json()
        assert isinstance(result, dict)
        assert result.get("stderr") == "AssertionError"
        assert result.get("exit_code") == 1

    def test_stdin_json_not_object(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO("[1, 2, 3]"))
        result = helper.parse_stdin_json()
        assert result["ok"] is False
        assert result["exit_code"] == 2

    def test_stdin_json_invalid(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        result = helper.parse_stdin_json()
        assert result["ok"] is False
        assert result["exit_code"] == 2

    def test_stdin_json_empty_stderr_stdout(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"stderr": "", "stdout": ""})))
        result = helper.parse_stdin_json()
        assert result["ok"] is False
        assert result["exit_code"] == 2

    def test_stdin_json_stderr_not_string(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"stderr": 123})))
        result = helper.parse_stdin_json()
        assert result["ok"] is False
        assert result["exit_code"] == 2

    def test_stdin_json_changed_files_not_list(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"stderr": "e", "changed_files": "x"})))
        result = helper.parse_stdin_json()
        assert result["ok"] is False
        assert result["exit_code"] == 2

    def test_stdin_json_exit_code_not_int(self, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"stderr": "e", "exit_code": "abc"})))
        result = helper.parse_stdin_json()
        # exit_code "abc" → json.loads keeps it as str → type check fails
        assert result["ok"] is False
        assert result["exit_code"] == 2


# ── E. Full flow with mocked router ───────────────────────────────────

class TestFullFlow:
    def test_classify_assertion_success(self, tmp_path, monkeypatch):
        """End-to-end: valid input → router mocked → classification returned."""
        classification = _mock_worker_result("assertion", "high", "assert failed")
        output = _mock_router_output(classification)

        # Write mock output to .local_llm_out so find_router_output finds it
        out_dir = helper.OUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = "20260525_120000"
        out_file = out_dir / f"{ts}_classify-test-failure.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        def mock_run(*a, **kw):
            m = MagicMock()
            m.returncode = 0
            m.stdout = json.dumps(output)
            m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", mock_run)
        args = helper.parse_args(["--stderr", "AssertionError: assert 2 == 3",
                                   "--exit-code", "1", "--json"])
        result = helper.classify_failure(args)
        assert result["ok"] is True
        assert result["advisory_only"] is True
        assert result["failure_class"] == "assertion"
        assert result["confidence"] == "high"
        assert "input_lengths" in result
        assert "truncated" in result

    def test_classify_import_error(self, tmp_path):
        classification = _mock_worker_result("import_error", "high", "cannot import")
        output = _mock_router_output(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "ImportError: cannot import name 'foo'",
                                       "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is True
            assert result["failure_class"] == "import_error"
            assert result["confidence"] == "high"

    def test_classify_dependency(self, tmp_path):
        classification = _mock_worker_result("dependency", "high", "missing module")
        output = _mock_router_output(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "ModuleNotFoundError: No module named 'x'",
                                       "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is True
            assert result["failure_class"] == "dependency"

    def test_classify_syntax_error(self, tmp_path):
        classification = _mock_worker_result("syntax_error", "high", "unmatched }")
        output = _mock_router_output(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "SyntaxError: unmatched '}'", "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is True
            assert result["failure_class"] == "syntax_error"

    def test_classify_timeout(self, tmp_path):
        classification = _mock_worker_result("timeout", "high", "timed out")
        output = _mock_router_output(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "TimeoutExpired", "--exit-code", "124",
                                       "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is True
            assert result["failure_class"] == "timeout"

    def test_missing_input_exit_2(self):
        args = helper.parse_args([])
        result = helper.classify_failure(args)
        assert result["ok"] is False
        assert result["exit_code"] == 2

    def test_router_failure_exit_3(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "router crashed"
            args = helper.parse_args(["--stderr", "error", "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is False
            assert result["exit_code"] == 3

    def test_router_timeout_exit_3(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300)):
            args = helper.parse_args(["--stderr", "error", "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is False
            assert result["exit_code"] == 3

    def test_classify_with_fenced_output(self, tmp_path):
        """E-C.1: full classify_failure with fenced JSON worker output returns ok=true."""
        classification = _mock_worker_result("timeout", "high", "timed out")
        output = _mock_router_output_fenced(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "TimeoutExpired", "--exit-code", "124",
                                       "--json"])
            result = helper.classify_failure(args)
            assert result["ok"] is True
            assert result["failure_class"] == "timeout"
            assert result["confidence"] == "high"


# ── F. Output schema ──────────────────────────────────────────────────

class TestOutputSchema:
    def test_json_output_has_all_required_fields(self, tmp_path):
        classification = _mock_worker_result()
        output = _mock_router_output(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "error", "--json"])
            result = helper.classify_failure(args)

        required = ["ok", "advisory_only", "failure_class", "confidence",
                    "summary", "likely_cause", "files_to_inspect",
                    "recommended_action", "truncated", "input_lengths",
                    "output_path", "elapsed_seconds", "profile"]
        for field in required:
            assert field in result, f"missing field: {field}"
        assert result["advisory_only"] is True

    def test_human_output_contains_expected_labels(self, tmp_path, capsys):
        classification = _mock_worker_result(
            failure_class="assertion", confidence="high",
            summary="A test failed.", likely_cause="Wrong logic.",
            files_to_inspect=["tests/test_x.py"],
            recommended_action="Check the assertion.",
        )
        output = _mock_router_output(classification)
        _write_mock_output(output)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "error"])
            result = helper.classify_failure(args)
            result.pop("exit_code", None)
            helper.print_human(result)

        captured = capsys.readouterr()
        assert "classification:" in captured.out
        assert "confidence:" in captured.out
        assert "summary:" in captured.out
        assert "action:" in captured.out

    def test_json_output_excludes_full_stderr(self, tmp_path):
        """Full stderr must not appear in JSON output."""
        classification = _mock_worker_result()
        output = _mock_router_output(classification)
        _write_mock_output(output)
        secret_stderr = "SECRET_TOKEN=abc123\n" + ("x" * 100)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", secret_stderr, "--json"])
            result = helper.classify_failure(args)

        result_json = json.dumps(result)
        assert "SECRET_TOKEN" not in result_json
        assert "abc123" not in result_json
        # input_lengths should still be correct
        assert result["input_lengths"]["stderr"] == len(secret_stderr)


# ── G. Boundary invariants ────────────────────────────────────────────

class TestBoundaries:
    def test_advisory_only_always_true(self, tmp_path):
        for cls_name in ["assertion", "import_error", "dependency", "syntax_error", "timeout"]:
            classification = _mock_worker_result(cls_name, "high")
            output = _mock_router_output(classification)
            _write_mock_output(output)

            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = json.dumps(output)
                mock_run.return_value.stderr = ""
                args = helper.parse_args(["--stderr", "err", "--json"])
                result = helper.classify_failure(args)
                assert result["advisory_only"] is True, f"advisory_only=False for {cls_name}"

    def test_writes_output_file(self, tmp_path):
        """Helper writes to .local_llm_out/ (allowed output side effect)."""
        classification = _mock_worker_result()
        output = _mock_router_output(classification)

        # Ensure output file exists before we mock subprocess.run
        out_dir = helper.OUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = "20260525_121000"
        out_file = out_dir / f"{ts}_classify-test-failure.json"
        out_file.write_text(json.dumps(output), encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "err", "--json"])
            result = helper.classify_failure(args)

        assert result["output_path"] is not None
        rel = str(Path(result["output_path"]))
        assert rel.replace("\\", "/").startswith(".local_llm_out/")

    def test_no_tracked_repo_file_modifications(self, tmp_path):
        """Confirm the helper does not write to any tracked repo path."""
        # The helper only writes to .local_llm_out/ and stdout.
        # We verify by checking that import does not cause side effects
        # and the classify_failure function doesn't touch tools/ or tests/.
        classification = _mock_worker_result()
        output = _mock_router_output(classification)
        _write_mock_output(output)

        tools_dir = SCRIPT_DIR
        tests_dir = SCRIPT_DIR.parent / "tests"

        before_tools = {p.name for p in tools_dir.rglob("*") if p.is_file()}
        before_tests = {p.name for p in tests_dir.rglob("*") if p.is_file()}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps(output)
            mock_run.return_value.stderr = ""
            args = helper.parse_args(["--stderr", "err", "--json"])
            helper.classify_failure(args)

        after_tools = {p.name for p in tools_dir.rglob("*") if p.is_file()}
        after_tests = {p.name for p in tests_dir.rglob("*") if p.is_file()}

        # No new or removed files in tools/ or tests/
        assert before_tools == after_tools, f"tools/ changed: {before_tools ^ after_tools}"
        assert before_tests == after_tests, f"tests/ changed: {before_tests ^ after_tests}"


# ── H. run_checks suggestion ──────────────────────────────────────────

class TestRunChecksSuggestion:
    """Verify run_checks.py has the expected tip line."""

    def test_run_checks_contains_tip(self):
        run_checks_path = SCRIPT_DIR / "run_checks.py"
        content = run_checks_path.read_text(encoding="utf-8")
        assert "classify_failure_helper" in content, (
            "run_checks.py must contain the classifier tip line"
        )
        assert "Tip:" in content

    def test_tip_after_failure_print(self):
        """The tip should be in the failure branch of run_checks.py."""
        run_checks_path = SCRIPT_DIR / "run_checks.py"
        content = run_checks_path.read_text(encoding="utf-8")
        # The tip is printed when pytest fails (not ok AND stdout exists)
        lines = content.split("\n")
        tip_lines = [i for i, line in enumerate(lines) if "classify_failure_helper" in line]
        assert len(tip_lines) >= 1
        # Tip should be within the failure branch
        for idx in tip_lines:
            context_start = max(0, idx - 8)
            context = "\n".join(lines[context_start:idx + 1])
            assert "not ok" in context or "FAIL" in context or "failure" in context.lower(), (
                f"Tip at line {idx} does not appear to be inside a failure branch"
            )
