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
