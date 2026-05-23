"""Test blocked-path enforcement in the worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from local_llm_worker import is_blocked_path


def test_git_blocked():
    assert is_blocked_path(Path(".git/config"))
    assert is_blocked_path(Path(".git/HEAD"))
    assert is_blocked_path(Path("some/deep/.git/objects"))


def test_env_blocked():
    assert is_blocked_path(Path(".env"))
    assert is_blocked_path(Path(".env.local"))
    assert is_blocked_path(Path(".env.production"))


def test_key_files_blocked():
    assert is_blocked_path(Path("secrets/id_rsa"))
    assert is_blocked_path(Path("id_ed25519"))
    assert is_blocked_path(Path("cert.pem"))
    assert is_blocked_path(Path("private.key"))


def test_vendor_dirs_blocked():
    assert is_blocked_path(Path("node_modules/express/index.js"))
    assert is_blocked_path(Path("venv/lib/python3.11/site.py"))
    assert is_blocked_path(Path(".venv/bin/activate"))
    assert is_blocked_path(Path("__pycache__/mod.cpython-311.pyc"))
    assert is_blocked_path(Path("dist/bundle.js"))
    assert is_blocked_path(Path("build/output.o"))
    assert is_blocked_path(Path("target/debug/main"))


def test_output_dir_blocked():
    assert is_blocked_path(Path(".local_llm_out/result.json"))


def test_normal_files_allowed():
    assert not is_blocked_path(Path("src/main.py"))
    assert not is_blocked_path(Path("README.md"))
    assert not is_blocked_path(Path("tools/local_llm_worker.py"))
    assert not is_blocked_path(Path("package.json"))
    assert not is_blocked_path(Path("docs/guide.md"))
    assert not is_blocked_path(Path("tests/test_foo.py"))


# --- v0.8.1 retry and error classification tests ---

def test_classify_error_timeout():
    from local_llm_worker import classify_error
    import requests
    e = requests.Timeout("timed out")
    error_type, suggestion = classify_error(e, "summarize-file")
    assert error_type == "timeout"
    assert suggestion


def test_classify_error_connection():
    from local_llm_worker import classify_error
    import requests
    e = requests.ConnectionError("connection refused")
    error_type, suggestion = classify_error(e, "summarize-file")
    assert error_type == "backend_unreachable"


def test_classify_error_empty_response():
    from local_llm_worker import classify_error
    e = ValueError("empty response from model")
    error_type, suggestion = classify_error(e, "summarize-file")
    assert error_type == "empty_response"


def test_classify_error_invalid_json():
    from local_llm_worker import classify_error
    e = ValueError("json decode error in response")
    error_type, suggestion = classify_error(e, "summarize-file")
    assert error_type == "invalid_json"


# ---------------------------------------------------------------------------
# v0.10.0-J H6 — classify_error substring disambiguation
# ---------------------------------------------------------------------------

def test_port_number_not_classified_as_backend_error():
    from local_llm_worker import classify_error
    e = RuntimeError("port 5001 is already in use")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type != "backend_error"


def test_standalone_500_still_backend_error():
    from local_llm_worker import classify_error
    e = RuntimeError("HTTP 500 internal server error")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_error"


def test_internal_server_error_is_backend_error():
    from local_llm_worker import classify_error
    e = RuntimeError("internal server error on backend")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_error"


def test_bad_gateway_is_backend_error():
    from local_llm_worker import classify_error
    e = RuntimeError("bad gateway from upstream")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_error"


def test_service_unavailable_is_backend_error():
    from local_llm_worker import classify_error
    e = RuntimeError("service unavailable — try later")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_error"


def test_generic_json_word_not_invalid_json():
    from local_llm_worker import classify_error
    e = RuntimeError("response body contains non-JSON extension field")
    error_type, _ = classify_error(e, "summarize-file")
    # Generic mention of "JSON" alone should not trigger invalid_json.
    assert error_type != "invalid_json"


def test_jsondecode_still_invalid_json():
    from local_llm_worker import classify_error
    e = ValueError("jsondecode error while parsing model output")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "invalid_json"


def test_not_json_message_is_invalid_json():
    from local_llm_worker import classify_error
    e = ValueError("response is not json")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "invalid_json"


def test_parse_error_is_invalid_json():
    from local_llm_worker import classify_error
    e = ValueError("could not parse model response")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "invalid_json"


def test_failed_to_parse_is_invalid_json():
    from local_llm_worker import classify_error
    e = ValueError("failed to parse output")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "invalid_json"


def test_unknown_exception_returns_unknown_error():
    from local_llm_worker import classify_error
    e = RuntimeError("some completely unexpected thing happened")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "unknown_error"


def test_timeout_type_still_works():
    from local_llm_worker import classify_error
    import requests
    e = requests.Timeout("read timed out")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "timeout"


def test_connection_error_type_still_works():
    from local_llm_worker import classify_error
    import requests
    e = requests.ConnectionError("connection refused")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_unreachable"


# v0.10.0-J H6-J — connection-context timeout must not be captured as generic timeout
def test_connection_timed_out_is_backend_unreachable():
    from local_llm_worker import classify_error
    e = RuntimeError("Connection to 192.168.1.2 timed out")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_unreachable"


def test_connection_timed_out_short_is_backend_unreachable():
    from local_llm_worker import classify_error
    e = RuntimeError("connection timed out")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_unreachable"


def test_backend_connection_timed_out_is_backend_unreachable():
    from local_llm_worker import classify_error
    e = RuntimeError("backend connection timed out")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "backend_unreachable"


def test_generic_timed_out_still_timeout():
    from local_llm_worker import classify_error
    e = RuntimeError("request timed out after 60s")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "timeout"


def test_empty_response_still_works():
    from local_llm_worker import classify_error
    e = ValueError("empty response from model")
    error_type, _ = classify_error(e, "summarize-file")
    assert error_type == "empty_response"


def test_no_retry_tasks_exclude_draft():
    from local_llm_worker import NO_RETRY_TASKS
    assert "draft-fix" in NO_RETRY_TASKS
    assert "draft-feature" in NO_RETRY_TASKS
    assert "draft-refactor" in NO_RETRY_TASKS
    assert "benchmark" in NO_RETRY_TASKS


def test_short_tasks_can_retry():
    from local_llm_worker import NO_RETRY_TASKS
    assert "summarize-file" not in NO_RETRY_TASKS
    assert "review-diff" not in NO_RETRY_TASKS
    assert "generate-test-plan" not in NO_RETRY_TASKS


def test_worker_output_has_error_fields():
    from local_llm_worker import WorkerOutput
    o = WorkerOutput(error="test", error_type="timeout",
                     suggestion="try smaller input", retries=1)
    assert o.error_type == "timeout"
    assert o.suggestion is not None
    assert o.retries == 1


# --- CJK stdin regression (v0.9.6) ---

CJK_TEXT = "diff --git a/x b/x\n-连接失败\n+テスト文章\n【原文】\n【译文】\n"


def test_worker_stdin_read_handles_cjk(monkeypatch):
    """Worker gather_input() must decode CJK bytes from stdin correctly."""
    import argparse, io
    from local_llm_worker import gather_input, WorkerConfig

    raw = CJK_TEXT.encode("utf-8")

    class MockStdin:
        buffer = io.BytesIO(raw)

    monkeypatch.setattr(sys, "stdin", MockStdin())
    args = argparse.Namespace(task="review-diff", stdin=True, target=None)
    config = WorkerConfig()
    config.max_chars = 200_000
    content, _, warnings, _ = gather_input(args, config)
    assert "连接失败" in content, f"Chinese missing from stdin content"
    assert "テスト文章" in content, f"Japanese missing from stdin content"
    assert "【原文】" in content, f"CJK bracket missing from stdin content"


def test_worker_stdin_read_handles_invalid_utf8(monkeypatch):
    """Worker gather_input() must not crash on invalid UTF-8 bytes."""
    import argparse, io
    from local_llm_worker import gather_input, WorkerConfig

    # Mix valid UTF-8 with an invalid continuation byte (0xFF)
    raw = "start ".encode("utf-8") + b"\xff\xfe" + " end".encode("utf-8")

    class MockStdin:
        buffer = io.BytesIO(raw)

    monkeypatch.setattr(sys, "stdin", MockStdin())
    args = argparse.Namespace(task="review-diff", stdin=True, target=None)
    config = WorkerConfig()
    config.max_chars = 200_000
    content, _, warnings, _ = gather_input(args, config)
    # With errors="replace", the invalid bytes are replaced with U+FFFD
    assert "start" in content
    assert "end" in content
