"""Tests for D-C: local_classify_test_failure MCP tool, handler, ledger keys.

Covers MCP tool registration, input validation, worker wiring, classification
JSON parsing, invalid JSON fallback, ledger extra keys, and safety boundaries.
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
    result = mcp.call_classify_test_failure({
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
    # stdin_data should be truncated
    stdin = mock_wrap.call_args[1].get("stdin_data", "")
    payload = json.loads(stdin)
    assert len(payload["stderr"]) <= 50_001  # _STDERR_MAX_CHARS + some slack


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
    assert le["test_failure_exit_code"] == 2


@patch("local_llm_mcp_server._wrap_worker_call")
def test_ledger_extra_fallback_on_invalid_json(mock_wrap):
    mock_wrap.return_value = _mock_worker_output("not json")
    result = mcp.call_classify_test_failure({"stderr": "error"})
    le = result["_ledger_extra"]
    assert le["test_failure_class"] == "unknown"
    assert le["test_failure_confidence"] == "low"


# ── G. Safety boundaries ──────────────────────────────────────────────

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
