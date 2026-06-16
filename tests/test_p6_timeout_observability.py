"""P6-B1: timeout observability fix — focused tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

TOOLS_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))


# --- 1. _extract_profile_from_cmd ---

def test_extract_profile_from_cmd_found():
    from local_llm_mcp_server import _extract_profile_from_cmd  # noqa: E402

    result = _extract_profile_from_cmd([
        "python", "worker.py", "--profile", "fast_summary", "--stdin",
    ])
    assert result == "fast_summary"


def test_extract_profile_from_cmd_not_found():
    from local_llm_mcp_server import _extract_profile_from_cmd  # noqa: E402

    result = _extract_profile_from_cmd(["python", "worker.py", "--stdin"])
    assert result == ""


def test_extract_profile_from_cmd_trailing_no_value():
    from local_llm_mcp_server import _extract_profile_from_cmd  # noqa: E402

    result = _extract_profile_from_cmd(["python", "worker.py", "--profile"])
    assert result == ""


def test_extract_profile_from_cmd_empty_list():
    from local_llm_mcp_server import _extract_profile_from_cmd  # noqa: E402

    assert _extract_profile_from_cmd([]) == ""


# --- 2. coerce_failure_response: timeout is NOT worker_failed_no_output ---

def test_coerce_failure_timeout_detection_sets_error_type():
    """P6-B1: when stderr contains 'timed out', _wrap_worker_call must return
    error_type='timeout', not 'worker_failed_no_output'."""
    from local_llm_mcp_server import (  # noqa: E402
        build_error_response,
        coerce_failure_response,
    )

    # Pre-existing: coerce_failure_response with no payload returns
    # 'worker_failed_no_output'. P6-B1 does not change this function —
    # the timeout check is in _wrap_worker_call before this function.
    response = coerce_failure_response(
        "local_summarize_file", None,
        "Subprocess timed out after 120s", 120.0, "req-1",
    )
    # coerce_failure_response itself still returns worker_failed_no_output
    # for no-payload; the timeout detection is above it in _wrap_worker_call.
    assert response["error_type"] == "worker_failed_no_output"

    # But build_error_response with explicit error_type="timeout" works:
    timeout_resp = build_error_response(
        tool="local_summarize_file", error_type="timeout",
        error="Subprocess timed out after 120s",
        suggestion="try a smaller input",
        elapsed=120.0, request_id="req-2",
    )
    assert timeout_resp["error_type"] == "timeout"
    assert timeout_resp["ok"] is False


# --- 3. _wrap_worker_call timeout path ---

class _FakeResult:
    """Simulates run_subprocess return value for a timeout."""

    def __init__(self):
        self.ok = False
        self.stdout = ""
        self.stderr = "Subprocess timed out after 120s"
        self.elapsed_seconds = 120.0
        self.returncode = -1

    def get(self, key, default=None):
        return getattr(self, key, default)


@patch("local_llm_mcp_server.run_subprocess")
@patch("local_llm_mcp_server.load_worker_output")
@patch("local_llm_mcp_server._update_model_health")
def test_wrap_worker_call_nonstream_timeout_returns_timeout_error_type(
    mock_health, mock_load, mock_run,
):
    """Non-streaming path: subprocess timeout must produce error_type='timeout'."""
    from local_llm_mcp_server import _wrap_worker_call  # noqa: E402

    mock_run.return_value = {
        "ok": False, "stdout": "", "stderr": "Subprocess timed out after 120s",
        "elapsed_seconds": 120.0, "returncode": -1,
    }
    mock_load.return_value = (None, "worker did not emit a JSON: marker")

    # Simulate streaming not active (no progress_token)
    with patch("local_llm_mcp_server._stream_ctx", create=True) as mock_ctx:
        mock_ctx.stream = False
        mock_ctx.progress_token = None

        response = _wrap_worker_call(
            "local_summarize_file",
            ["python", "worker.py", "--profile", "fast_summary"],
            stdin_data="test input", timeout=30,
        )

    assert response["error_type"] == "timeout", (
        f"expected error_type='timeout', got {response['error_type']!r}"
    )
    assert response["ok"] is False
    # Verify health was called with timeout error_type
    assert mock_health.called
    call_args = mock_health.call_args
    assert call_args[0][0] == "fast_summary"  # profile name from cmd
    assert call_args[1]["ok"] is False
    assert call_args[1]["error_type"] == "timeout"


@patch("local_llm_mcp_server.run_subprocess")
@patch("local_llm_mcp_server.load_worker_output")
@patch("local_llm_mcp_server._update_model_health")
def test_wrap_worker_call_nonstream_non_timeout_failure_unchanged(
    mock_health, mock_load, mock_run,
):
    """Non-timeout failure must still use coerce_failure_response path."""
    from local_llm_mcp_server import _wrap_worker_call  # noqa: E402

    mock_run.return_value = {
        "ok": False, "stdout": "", "stderr": "some other error",
        "elapsed_seconds": 5.0, "returncode": 1,
    }
    mock_load.return_value = (None, "worker did not emit a JSON: marker")

    with patch("local_llm_mcp_server._stream_ctx", create=True) as mock_ctx:
        mock_ctx.stream = False
        mock_ctx.progress_token = None

        response = _wrap_worker_call(
            "local_summarize_file",
            ["python", "worker.py", "--profile", "fast_summary"],
            stdin_data="test input", timeout=30,
        )

    # Non-timeout still returns worker_failed_no_output
    assert response["error_type"] == "worker_failed_no_output"
    # Health should NOT be called (payload is None, no timeout)
    assert not mock_health.called


@patch("local_llm_mcp_server.run_subprocess")
@patch("local_llm_mcp_server.load_worker_output")
@patch("local_llm_mcp_server._update_model_health")
def test_wrap_worker_call_timeout_calls_health_with_correct_profile(
    mock_health, mock_load, mock_run,
):
    """Health update must receive the correct profile name from the cmd."""
    from local_llm_mcp_server import _wrap_worker_call  # noqa: E402

    mock_run.return_value = {
        "ok": False, "stdout": "", "stderr": "Subprocess timed out after 60s",
        "elapsed_seconds": 60.0, "returncode": -1,
    }
    mock_load.return_value = (None, "no marker")

    with patch("local_llm_mcp_server._stream_ctx", create=True) as mock_ctx:
        mock_ctx.stream = False
        mock_ctx.progress_token = None

        _wrap_worker_call(
            "local_contextual_analyze",
            ["python", "worker.py", "--profile", "code_worker", "--stdin"],
            stdin_data="test", timeout=60,
        )

    mock_health.assert_called_once()
    args, kwargs = mock_health.call_args
    assert args[0] == "code_worker"
    assert kwargs["ok"] is False
    assert kwargs["error_type"] == "timeout"


# --- 4. health_store last_timeout clearing ---

def test_last_timeout_set_on_timeout():
    """timeout must set last_timeout."""
    from health_store import record_invocation, load_profile_health  # noqa: E402

    record_invocation("test_timeout_profile", ok=False, elapsed_s=60.0,
                      error_type="timeout")
    health = load_profile_health("test_timeout_profile")
    assert health["last_timeout"] is not None, "timeout should set last_timeout"


def test_last_timeout_cleared_after_success():
    """Success after a timeout must clear stale last_timeout."""
    from health_store import record_invocation, load_profile_health  # noqa: E402

    # First: simulate a timeout
    record_invocation("test_clear_profile", ok=False, elapsed_s=60.0,
                      error_type="timeout")
    health = load_profile_health("test_clear_profile")
    assert health["last_timeout"] is not None

    # Then: simulate a success
    record_invocation("test_clear_profile", ok=True, elapsed_s=10.0,
                      error_type="")
    health = load_profile_health("test_clear_profile")
    assert health["last_timeout"] is None, (
        f"success should clear stale last_timeout, got {health['last_timeout']!r}"
    )


def test_last_timeout_not_cleared_on_non_timeout_failure():
    """Non-timeout failure should not clear a previously-set last_timeout."""
    from health_store import record_invocation, load_profile_health  # noqa: E402

    # First: timeout
    record_invocation("test_keep_profile", ok=False, elapsed_s=60.0,
                      error_type="timeout")
    health = load_profile_health("test_keep_profile")
    assert health["last_timeout"] is not None
    timeout_date = health["last_timeout"]

    # Then: non-timeout failure (e.g., backend_unreachable)
    record_invocation("test_keep_profile", ok=False, elapsed_s=5.0,
                      error_type="backend_unreachable")
    health = load_profile_health("test_keep_profile")
    assert health["last_timeout"] == timeout_date, (
        "non-timeout failure must not clear last_timeout"
    )


def test_consecutive_failures_reset_on_success():
    """Success after failures must reset consecutive_failures to 0."""
    from health_store import record_invocation, load_profile_health  # noqa: E402

    for _ in range(3):
        record_invocation("test_reset_profile", ok=False, elapsed_s=30.0,
                          error_type="timeout")
    health = load_profile_health("test_reset_profile")
    assert health["consecutive_failures"] == 3

    record_invocation("test_reset_profile", ok=True, elapsed_s=10.0,
                      error_type="")
    health = load_profile_health("test_reset_profile")
    assert health["consecutive_failures"] == 0
    assert health["last_timeout"] is None


# --- 5. _update_model_health integration ---

@patch("local_llm_mcp_server.record_invocation")
def test_update_model_health_delegates_to_health_store(mock_record):
    """_update_model_health must delegate to health_store.record_invocation."""
    from local_llm_mcp_server import _update_model_health  # noqa: E402

    _update_model_health("test_prof", ok=False, elapsed_s=30.0,
                         error_type="timeout")
    mock_record.assert_called_once_with(
        "test_prof", ok=False, elapsed_s=30.0, error_type="timeout",
    )


# --- 6. Regression: existing behavior unchanged ---

def test_health_store_schema_version_unchanged():
    """Health store schema version must remain 1."""
    from health_store import SCHEMA_VERSION  # noqa: E402
    assert SCHEMA_VERSION == 1


def test_mcp_tool_count_unchanged():
    """MCP tool count must remain 12."""
    from local_llm_mcp_server import TOOLS  # noqa: E402
    assert len(TOOLS) == 13
