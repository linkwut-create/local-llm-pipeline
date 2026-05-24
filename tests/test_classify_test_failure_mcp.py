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


# ── I. D-D.1 response envelope propagation ────────────────────────────

def _mock_worker_output_nested(classification_dict):
    """Return a realistic _wrap_worker_call-like dict with the classification
    serialized as a JSON string inside result.result, matching what the real
    worker pipeline produces."""
    if isinstance(classification_dict, str):
        inner = classification_dict
    else:
        inner = json.dumps(classification_dict, ensure_ascii=False)
    return {
        "ok": True,
        "tool": "local_classify_test_failure",
        "task": "classify-test-failure",
        "result": {
            "task": "classify-test-failure",
            "tool": "classify-test-failure",
            "profile": "code_worker",
            "model": "qwen3-coder:30b",
            "provider": "ollama",
            "ok": True,
            "result": inner,
            "warnings": [],
            "error": None,
        },
        "profile": "code_worker",
        "model": "qwen3-coder:30b",
    }


@patch("local_llm_mcp_server._wrap_worker_call")
def test_top_level_propagation_from_nested_json(mock_wrap):
    """Worker returns classification as JSON string in result.result.result.
    Top-level failure_class/confidence/advisory_only must reflect it."""
    mock_wrap.return_value = _mock_worker_output_nested({
        "ok": True,
        "failure_class": "assertion",
        "confidence": "high",
        "summary": "assert 2 == 3 failed",
        "likely_cause": "bad math",
        "files_to_inspect": ["tests/test_math.py"],
        "recommended_action": "check the add function",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "AssertionError: assert 2 == 3",
        "exit_code": 1,
    })
    assert result["failure_class"] == "assertion"
    assert result["confidence"] == "high"
    assert result["advisory_only"] is True


@patch("local_llm_mcp_server._wrap_worker_call")
def test_import_error_propagation_nested(mock_wrap):
    """import_error/high in nested JSON propagates to top-level."""
    mock_wrap.return_value = _mock_worker_output_nested({
        "ok": True,
        "failure_class": "import_error",
        "confidence": "high",
        "summary": "cannot import build_record",
        "likely_cause": "missing export",
        "files_to_inspect": ["tools/call_ledger.py"],
        "recommended_action": "check call_ledger exports",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "ImportError: cannot import name 'build_record'",
        "exit_code": 1,
    })
    assert result["failure_class"] == "import_error"
    assert result["confidence"] == "high"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_malformed_inner_json_fallback(mock_wrap):
    """When inner result string is not valid JSON, handler falls back
    safely with unknown/low and classification_parse_warning."""
    mock_wrap.return_value = _mock_worker_output_nested("not valid json {{{")
    result = mcp.call_classify_test_failure({"stderr": "error"})
    assert result["failure_class"] == "unknown"
    assert result["confidence"] == "low"
    assert result["advisory_only"] is True
    assert "classification_parse_warning" in result


@patch("local_llm_mcp_server._wrap_worker_call")
def test_dependency_propagation_nested(mock_wrap):
    """dependency/medium propagates correctly from nested JSON."""
    mock_wrap.return_value = _mock_worker_output_nested({
        "ok": True,
        "failure_class": "dependency",
        "confidence": "medium",
        "summary": "missing pytest-mock",
        "likely_cause": "not installed",
        "files_to_inspect": [],
        "recommended_action": "pip install pytest-mock",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "ModuleNotFoundError: No module named 'pytest_mock'",
    })
    assert result["failure_class"] == "dependency"
    assert result["confidence"] == "medium"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_syntax_error_propagation_nested(mock_wrap):
    """syntax_error/high propagates correctly from nested JSON."""
    mock_wrap.return_value = _mock_worker_output_nested({
        "ok": True,
        "failure_class": "syntax_error",
        "confidence": "high",
        "summary": "unmatched brace",
        "likely_cause": "typo",
        "files_to_inspect": ["tools/local_llm_mcp_server.py"],
        "recommended_action": "fix brace",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "SyntaxError: unmatched '}'",
    })
    assert result["failure_class"] == "syntax_error"
    assert result["confidence"] == "high"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_timeout_propagation_nested(mock_wrap):
    """timeout/high propagates correctly from nested JSON."""
    mock_wrap.return_value = _mock_worker_output_nested({
        "ok": True,
        "failure_class": "timeout",
        "confidence": "high",
        "summary": "test timed out",
        "likely_cause": "slow integration test",
        "files_to_inspect": ["tests/test_slow.py"],
        "recommended_action": "increase timeout or optimize",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({
        "stderr": "TimeoutExpired: 120s",
        "exit_code": 124,
    })
    assert result["failure_class"] == "timeout"
    assert result["confidence"] == "high"


@patch("local_llm_mcp_server._wrap_worker_call")
def test_inner_result_is_dict_not_json_string(mock_wrap):
    """Backward compat: when result.result is already a dict, use it directly."""
    mock_wrap.return_value = _mock_worker_output({
        "ok": True,
        "failure_class": "flaky",
        "confidence": "medium",
        "summary": "intermittent failure",
        "likely_cause": "race condition",
        "files_to_inspect": [],
        "recommended_action": "add retry",
        "advisory_only": True,
    })
    result = mcp.call_classify_test_failure({"stderr": "sometimes fails"})
    assert result["failure_class"] == "flaky"
    assert result["confidence"] == "medium"
