"""Tests for D-C / D-C.1: local_classify_test_failure MCP tool, handler, ledger keys.

Covers MCP tool registration, input validation, worker wiring, classification
JSON parsing, invalid JSON fallback, ledger extra keys, safety boundaries,
and D-C.1 hotfix regressions (env values are strings, command uses --stdin).
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))

import local_llm_mcp_server as mcp
import call_ledger

# ── A. MCP tool registration ──────────────────────────────────────────

def test_tool_registered_in_TOOLS():
    assert "local_classify_test_failure" in mcp.TOOLS
    tool = mcp.TOOLS["local_classify_test_failure"]
    schema = tool["inputSchema"]
    assert "stderr" in schema["properties"]
    assert "stdout" in schema["properties"]
    assert "exit_code" in schema["properties"]
    assert "test_command" in schema["properties"]
    assert "changed_files" in schema["properties"]
    assert "profile" in schema["properties"]
    assert "model" in schema["properties"]
    assert "stderr" in schema["required"]


def test_tool_registered_in_HANDLERS():
    assert "local_classify_test_failure" in mcp.TOOL_HANDLERS
    assert callable(mcp.TOOL_HANDLERS["local_classify_test_failure"])


def test_tool_count_is_11():
    assert len(mcp.TOOLS) == 11


def test_original_10_tools_still_present():
    original = [
        "local_check", "local_summarize_file", "local_summarize_tree",
        "local_generate_test_plan", "local_review_diff", "local_debate_review_diff",
        "local_parallel_review", "local_contextual_analyze", "local_draft_code",
        "local_repo_map",
    ]
    for name in original:
        assert name in mcp.TOOLS, f"{name} missing from TOOLS"
        assert name in mcp.TOOL_HANDLERS, f"{name} missing from HANDLERS"


# ── B. Validation ─────────────────────────────────────────────────────

def test_missing_stderr_rejected():
    """Empty params: stderr defaults to \"\" which fails the non-empty check."""
    result = mcp.call_classify_test_failure({})
    assert result["ok"] is False
    assert "must be non-empty" in str(result.get("error", ""))


def test_stderr_not_string_rejected():
    result = mcp.call_classify_test_failure({"stderr": 123})
    assert result["ok"] is False


def test_stdout_not_string_rejected():
    result = mcp.call_classify_test_failure({"stderr": "err", "stdout": 456})
    assert result["ok"] is False


def test_exit_code_not_int_rejected():
    result = mcp.call_classify_test_failure({"stderr": "err", "exit_code": "1"})
    assert result["ok"] is False


def test_test_command_not_string_rejected():
    result = mcp.call_classify_test_failure({"stderr": "err", "test_command": {}})
    assert result["ok"] is False


def test_changed_files_not_list_rejected():
    result = mcp.call_classify_test_failure({"stderr": "err", "changed_files": "x"})
    assert result["ok"] is False


def test_changed_files_non_string_elements_rejected():
    result = mcp.call_classify_test_failure({"stderr": "err", "changed_files": [1, 2]})
    assert result["ok"] is False


def test_empty_stderr_and_stdout_rejected():
    result = mcp.call_classify_test_failure({"stderr": "", "stdout": ""})
    assert result["ok"] is False


# ── C. Worker call wiring ─────────────────────────────────────────────

def _mock_worker_output(classification_dict):
    """Return a mock build_success_response-like dict."""
    return {
        "ok": True,
        "tool": "local_classify_test_failure",
        "task": "classify-test-failure",
        "result": classification_dict,
        "profile": "code_worker",
        "model": "test-model",
    }


@patch("local_llm_mcp_server._wrap_worker_call")
def test_worker_called_with_correct_task(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "assertion", "confidence": "medium",
        "summary": "test", "likely_cause": "test", "files_to_inspect": [],
        "recommended_action": "check", "advisory_only": True,
    })
    mcp.call_classify_test_failure({
        "stderr": "AssertionError: assert 1 == 2",
        "exit_code": 1,
    })
    assert mock_wrap.called
    call_args = mock_wrap.call_args
    assert call_args[1]["task"] == "classify-test-failure"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_stderr_truncated_in_payload(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "unknown", "confidence": "low",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    huge_stderr = "x" * 60_000
    mcp.call_classify_test_failure({"stderr": huge_stderr})
    assert mock_wrap.called
    stdin = mock_wrap.call_args[1].get("stdin_data", "")
    payload = json.loads(stdin)
    assert len(payload["stderr"]) <= 50_001  # _STDERR_MAX_CHARS + some slack


@patch("local_llm_mcp_server._wrap_worker_call")
def test_stdout_truncated_in_payload(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "unknown", "confidence": "low",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    huge_stdout = "y" * 30_000
    mcp.call_classify_test_failure({"stderr": "err", "stdout": huge_stdout})
    assert mock_wrap.called
    stdin = mock_wrap.call_args[1].get("stdin_data", "")
    payload = json.loads(stdin)
    assert len(payload["stdout"]) <= 20_001  # _STDOUT_MAX_CHARS


@patch("local_llm_mcp_server._wrap_worker_call")
def test_test_command_capped(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "unknown", "confidence": "low",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    long_cmd = "pytest " + "x" * 2000
    mcp.call_classify_test_failure({"stderr": "err", "test_command": long_cmd})
    assert mock_wrap.called
    stdin = mock_wrap.call_args[1].get("stdin_data", "")
    payload = json.loads(stdin)
    assert len(payload["test_command"]) <= 1000


@patch("local_llm_mcp_server._wrap_worker_call")
def test_changed_files_capped(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "unknown", "confidence": "low",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    many_files = [f"file_{i}.py" for i in range(100)]
    mcp.call_classify_test_failure({"stderr": "err", "changed_files": many_files})
    stdin = mock_wrap.call_args[1].get("stdin_data", "")
    payload = json.loads(stdin)
    assert len(payload["changed_files"]) <= 50


# ── C-1. D-C.1 hotfix regressions ─────────────────────────────────────

@patch("local_llm_mcp_server._wrap_worker_call")
def test_command_uses_stdin(mock_wrap):
    """Bug 2 fix: cmd must include --stdin."""
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "assertion", "confidence": "medium",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    mcp.call_classify_test_failure({
        "stderr": "AssertionError",
        "exit_code": 1,
        "test_command": "pytest -q",
        "changed_files": ["a.py"],
    })
    assert mock_wrap.called
    cmd = mock_wrap.call_args[0][1]  # second positional arg is cmd list
    assert "--stdin" in cmd, f"--stdin missing from cmd: {cmd}"
    stdin_data = mock_wrap.call_args[1].get("stdin_data", "")
    assert stdin_data
    payload = json.loads(stdin_data)
    assert "stderr" in payload
    assert "stdout" in payload
    assert payload.get("exit_code") == 1
    assert payload.get("test_command") == "pytest -q"
    assert payload.get("changed_files") == ["a.py"]


@patch("local_llm_mcp_server._wrap_worker_call")
def test_env_values_are_all_strings(mock_wrap):
    """Bug 1 fix: all extra_env values must be str for subprocess env."""
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "import_error", "confidence": "high",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    mcp.call_classify_test_failure({
        "stderr": "ImportError: cannot import X",
        "exit_code": 1,
    })
    assert mock_wrap.called
    extra_env = mock_wrap.call_args[1].get("extra_env", {})
    for key, value in extra_env.items():
        assert isinstance(value, str), (
            f"extra_env[{key!r}] = {value!r} is {type(value).__name__}, expected str"
        )


@patch("local_llm_mcp_server._wrap_worker_call")
def test_exit_code_stored_in_ledger_json_not_as_raw_int(mock_wrap):
    """Bug 1 fix: test_failure_exit_code inside LOCAL_LLM_LEDGER_EXTRA JSON."""
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "timeout", "confidence": "medium",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    mcp.call_classify_test_failure({
        "stderr": "timeout",
        "exit_code": 124,
    })
    assert mock_wrap.called
    extra_env = mock_wrap.call_args[1].get("extra_env", {})
    raw_json = extra_env.get("LOCAL_LLM_LEDGER_EXTRA", "")
    assert raw_json
    ledger_payload = json.loads(raw_json)
    assert ledger_payload.get("test_failure_exit_code") == 124
    # Must NOT be a separate raw env var with int value
    assert "test_failure_exit_code" not in extra_env, (
        "test_failure_exit_code must be inside LOCAL_LLM_LEDGER_EXTRA JSON, "
        "not a raw env key"
    )


# ── D. Classification parse (valid JSON result) ───────────────────────

@patch("local_llm_mcp_server._wrap_worker_call")
def test_valid_classification_parsed(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "import_error", "confidence": "high",
        "summary": "Import error in test", "likely_cause": "missing module",
        "files_to_inspect": ["tests/test_x.py"],
        "recommended_action": "pip install missing-package",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "ImportError: cannot import name foo",
        "exit_code": 1,
    })
    assert result["failure_class"] == "import_error"
    assert result["confidence"] == "high"
    assert result["advisory_only"] is True


@patch("local_llm_mcp_server._wrap_worker_call")
def test_invalid_failure_class_coerced_to_unknown(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "bogus_class", "confidence": "medium",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({"stderr": "error"})
    assert result["failure_class"] == "unknown"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_invalid_confidence_coerced_to_low(mock_wrap):
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "assertion", "confidence": "certain",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({"stderr": "error"})
    assert result["confidence"] == "low"


# ── E. Invalid JSON fallback ──────────────────────────────────────────

@patch("local_llm_mcp_server._wrap_worker_call")
def test_invalid_json_result_fallback(mock_wrap):
    mock_wrap.return_value = _mock_worker_output("this is not json at all")
    result = mcp.call_classify_test_failure({"stderr": "error"})
    assert result["failure_class"] == "unknown"
    assert result["confidence"] == "low"
    assert result["advisory_only"] is True
    assert "classification_parse_warning" in result
    assert result["classification_parse_warning"] == "invalid_json"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_non_dict_result_text_fallback(mock_wrap):
    mock_wrap.return_value = _mock_worker_output("plain text output")
    result = mcp.call_classify_test_failure({"stderr": "error"})
    assert result["failure_class"] == "unknown"
    assert result["confidence"] == "low"


# ── F. Ledger extra keys ──────────────────────────────────────────────

def test_ledger_known_extra_keys():
    assert "test_failure_class" in call_ledger.KNOWN_EXTRA_KEYS
    assert "test_failure_confidence" in call_ledger.KNOWN_EXTRA_KEYS
    assert "test_failure_exit_code" in call_ledger.KNOWN_EXTRA_KEYS


def test_ledger_no_forbidden_keys():
    """stderr/stdout/test_command must NOT be in KNOWN_EXTRA_KEYS."""
    assert "test_failure_full_stderr" not in call_ledger.KNOWN_EXTRA_KEYS
    assert "test_failure_command" not in call_ledger.KNOWN_EXTRA_KEYS
    assert "test_failure_changed_files_count" not in call_ledger.KNOWN_EXTRA_KEYS


@patch("local_llm_mcp_server._wrap_worker_call")
def test_ledger_extra_passed_to_worker(mock_wrap):
    """Classification fields in _ledger_extra for parsed worker output."""
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "timeout", "confidence": "medium",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "timeout", "exit_code": 2,
    })
    assert "_ledger_extra" in result
    le = result["_ledger_extra"]
    assert le["test_failure_class"] == "timeout"
    assert le["test_failure_confidence"] == "medium"
    # D-C.1: test_failure_exit_code is inside LOCAL_LLM_LEDGER_EXTRA JSON
    raw_json = le.get("LOCAL_LLM_LEDGER_EXTRA", "")
    ledger_payload = json.loads(raw_json)
    assert ledger_payload["test_failure_exit_code"] == 2


@patch("local_llm_mcp_server._wrap_worker_call")
def test_ledger_extra_fallback_on_invalid_json(mock_wrap):
    mock_wrap.return_value = _mock_worker_output("not json")
    result = mcp.call_classify_test_failure({"stderr": "error"})
    le = result["_ledger_extra"]
    assert le["test_failure_class"] == "unknown"
    assert le["test_failure_confidence"] == "low"


# ── G. Ledger privacy (D-C.1) ─────────────────────────────────────────

@patch("local_llm_mcp_server._wrap_worker_call")
def test_ledger_env_excludes_stderr_stdout_test_command(mock_wrap):
    """Extra env / ledger payload must NOT leak stderr, stdout, or test_command."""
    mock_wrap.return_value = _mock_worker_output({
        "ok": True, "failure_class": "assertion", "confidence": "high",
        "summary": "x", "likely_cause": "x", "files_to_inspect": [],
        "recommended_action": "x", "advisory_only": True,
    })
    mcp.call_classify_test_failure({
        "stderr": "AssertionError: secret-token-12345",
        "stdout": "API_KEY=abcdef",
        "test_command": "pytest tests/test_secret.py -q",
        "exit_code": 1,
    })
    extra_env = mock_wrap.call_args[1].get("extra_env", {})
    # Check LOCAL_LLM_LEDGER_EXTRA JSON does not contain stderr/stdout/test_command
    raw_json = extra_env.get("LOCAL_LLM_LEDGER_EXTRA", "")
    assert raw_json
    ledger_payload = json.loads(raw_json)
    assert "stderr" not in ledger_payload
    assert "stdout" not in ledger_payload
    assert "test_command" not in ledger_payload
    # Raw env keys must not contain stderr/stdout/test_command
    for key in extra_env:
        assert "stderr" not in key.lower(), f"forbidden key in extra_env: {key}"
        assert "stdout" not in key.lower(), f"forbidden key in extra_env: {key}"
        assert "test_command" not in key.lower(), f"forbidden key in extra_env: {key}"
    # Full stderr must not appear as any env value
    for value in extra_env.values():
        assert "secret-token-12345" not in value
        assert "API_KEY=abcdef" not in value


# ── H. Safety boundaries ──────────────────────────────────────────────

def test_handler_no_commit_gate_param():
    """Handler must not accept or require commit_gate."""
    schema = mcp.TOOLS["local_classify_test_failure"]["inputSchema"]
    assert "commit_gate" not in schema["properties"]


def test_no_review_diff_behavior_change():
    """local_review_diff schema unchanged."""
    rd_schema = mcp.TOOLS["local_review_diff"]["inputSchema"]
    assert "failure_class" not in str(rd_schema)


def test_no_test_plan_behavior_change():
    """local_generate_test_plan schema and handler unchanged."""
    tp_schema = mcp.TOOLS["local_generate_test_plan"]["inputSchema"]
    assert "use_repo_map" in tp_schema["properties"]  # C3-B still there


def test_version_unchanged():
    """VERSION file not modified by this test suite (read-only check)."""
    version_path = SCRIPT_DIR.parent / "VERSION"
    if version_path.exists():
        v = version_path.read_text().strip()
        assert v == "0.10.0"
