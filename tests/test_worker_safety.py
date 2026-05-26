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
    assert "draft-commit-message" in NO_RETRY_TASKS
    assert "draft-fix" in NO_RETRY_TASKS
    assert "draft-feature" in NO_RETRY_TASKS
    assert "draft-refactor" in NO_RETRY_TASKS
    assert "find-related-files" in NO_RETRY_TASKS
    assert "benchmark" in NO_RETRY_TASKS


def test_draft_commit_message_task_config():
    """J-B: draft-commit-message must be advisory-only."""
    import json
    from pathlib import Path
    tasks_path = Path(__file__).parent.parent / "tools" / "local_llm_tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    t = tasks["tasks"].get("draft-commit-message")
    assert t is not None, "draft-commit-message missing from tasks.json"
    assert t["risk"] == "low", f"risk should be low, got {t.get('risk')}"
    assert t["may_modify_code"] is False, "may_modify_code must be false"
    assert t["controller_must_verify"] is True, "controller_must_verify must be true"
    assert t["default_profile"] == "code_worker"


def test_draft_commit_message_prompt_exists():
    """J-B: prompt must exist and contain advisory-only boundaries."""
    from local_llm_worker import TASK_PROMPTS
    prompt = TASK_PROMPTS.get("draft-commit-message")
    assert prompt is not None, "draft-commit-message prompt missing from TASK_PROMPTS"
    assert "NEVER run git commit" in prompt
    assert "NEVER stage files" in prompt
    assert "NEVER edit source files" in prompt
    assert "ADVISORY ONLY" in prompt or "advisory" in prompt.lower()
    assert "DRAFT" in prompt
    assert "empty" in prompt.lower() or "meaningless" in prompt.lower()


def test_draft_pr_summary_task_config():
    """J-D: draft-pr-summary must be advisory-only."""
    import json
    from pathlib import Path
    tasks_path = Path(__file__).parent.parent / "tools" / "local_llm_tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    t = tasks["tasks"].get("draft-pr-summary")
    assert t is not None, "draft-pr-summary missing from tasks.json"
    assert t["risk"] == "low", f"risk should be low, got {t.get('risk')}"
    assert t["may_modify_code"] is False, "may_modify_code must be false"
    assert t["controller_must_verify"] is True, "controller_must_verify must be true"
    assert t["default_profile"] == "code_worker"


def test_draft_pr_summary_prompt_exists():
    """J-D: prompt must exist and contain advisory-only boundaries."""
    from local_llm_worker import TASK_PROMPTS
    prompt = TASK_PROMPTS.get("draft-pr-summary")
    assert prompt is not None, "draft-pr-summary prompt missing from TASK_PROMPTS"
    assert "NEVER create a PR" in prompt
    assert "NEVER push" in prompt
    assert "NEVER run git commit" in prompt
    assert "NEVER stage files" in prompt
    assert "Do NOT modify source files" in prompt
    assert "ADVISORY ONLY" in prompt or "advisory" in prompt.lower()
    assert "DRAFT" in prompt
    assert "empty" in prompt.lower() or "too small" in prompt.lower()


def test_draft_pr_summary_in_no_retry():
    """J-D: draft-pr-summary should not retry (generative, non-trivial)."""
    from local_llm_worker import NO_RETRY_TASKS
    assert "draft-pr-summary" in NO_RETRY_TASKS


def test_draft_pr_summary_prompt_registry():
    """J-D: prompt registry entry must exist and have valid hash."""
    import json
    from pathlib import Path
    import hashlib
    registry_path = Path(__file__).parent.parent / "tools" / "prompts" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry["prompts"].get("draft-pr-summary")
    assert entry is not None, "draft-pr-summary missing from registry.json"
    assert entry["prompt_id"] == "draft-pr-summary"
    assert entry["version"] == "v1"
    assert entry["file"] == "draft-pr-summary.v1.md"
    prompt_path = Path(__file__).parent.parent / "tools" / "prompts" / entry["file"]
    text = prompt_path.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    assert entry["hash"] == actual_hash, f"hash mismatch: stored={entry['hash'][:8]}, actual={actual_hash[:8]}"


def test_draft_changelog_entry_task_config():
    """J-E: draft-changelog-entry must be advisory-only."""
    import json
    from pathlib import Path
    tasks_path = Path(__file__).parent.parent / "tools" / "local_llm_tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    t = tasks["tasks"].get("draft-changelog-entry")
    assert t is not None, "draft-changelog-entry missing from tasks.json"
    assert t["risk"] == "low", f"risk should be low, got {t.get('risk')}"
    assert t["may_modify_code"] is False, "may_modify_code must be false"
    assert t["controller_must_verify"] is True, "controller_must_verify must be true"
    assert t["default_profile"] == "code_worker"


def test_draft_changelog_entry_prompt_exists():
    """J-E: prompt must exist and contain advisory-only boundaries."""
    from local_llm_worker import TASK_PROMPTS
    prompt = TASK_PROMPTS.get("draft-changelog-entry")
    assert prompt is not None, "draft-changelog-entry prompt missing from TASK_PROMPTS"
    assert "NEVER edit CHANGELOG.md" in prompt
    assert "NEVER push" in prompt
    assert "NEVER run git commit" in prompt
    assert "NEVER stage files" in prompt
    assert "Do NOT modify source files" in prompt
    assert "ADVISORY ONLY" in prompt or "advisory" in prompt.lower()
    assert "DRAFT" in prompt
    assert "empty" in prompt.lower() or "too small" in prompt.lower()


def test_draft_changelog_entry_in_no_retry():
    """J-E: draft-changelog-entry should not retry (generative, non-trivial)."""
    from local_llm_worker import NO_RETRY_TASKS
    assert "draft-changelog-entry" in NO_RETRY_TASKS


def test_draft_changelog_entry_prompt_registry():
    """J-E: prompt registry entry must exist and have valid hash."""
    import json
    from pathlib import Path
    import hashlib
    registry_path = Path(__file__).parent.parent / "tools" / "prompts" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry["prompts"].get("draft-changelog-entry")
    assert entry is not None, "draft-changelog-entry missing from registry.json"
    assert entry["prompt_id"] == "draft-changelog-entry"
    assert entry["version"] == "v1"
    assert entry["file"] == "draft-changelog-entry.v1.md"
    prompt_path = Path(__file__).parent.parent / "tools" / "prompts" / entry["file"]
    text = prompt_path.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    assert entry["hash"] == actual_hash, f"hash mismatch: stored={entry['hash'][:8]}, actual={actual_hash[:8]}"


# --- J-K2: find-related-files advisor v2 ---

def test_find_related_files_task_config():
    """J-K2: find-related-files must be advisory-only."""
    import json
    from pathlib import Path
    tasks_path = Path(__file__).parent.parent / "tools" / "local_llm_tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    t = tasks["tasks"].get("find-related-files")
    assert t is not None, "find-related-files missing from tasks.json"
    assert t["risk"] == "low", f"risk should be low, got {t.get('risk')}"
    assert t["may_modify_code"] is False, "may_modify_code must be false"
    assert t["controller_must_verify"] is True, "controller_must_verify must be true"
    assert t["default_profile"] == "code_worker"


def test_find_related_files_prompt_exists():
    """J-K2: prompt must exist and contain advisory-only boundaries."""
    from local_llm_worker import TASK_PROMPTS
    prompt = TASK_PROMPTS.get("find-related-files")
    assert prompt is not None, "find-related-files prompt missing from TASK_PROMPTS"
    assert "Primary candidates" in prompt
    assert "Related tests" in prompt
    assert "Suggested inspection order" in prompt
    assert "Suggested next tool calls" in prompt
    assert "Do NOT modify source files" in prompt
    assert "NEVER run git commit" in prompt
    assert "NEVER stage files" in prompt
    assert "NEVER push" in prompt
    assert "Do NOT fabricate file paths" in prompt
    assert "verbatim" in prompt
    assert "Do not guess" in prompt
    assert "synthesize test file" in prompt
    assert "ADVISORY ONLY" in prompt


def test_find_related_files_in_no_retry():
    """J-K2: find-related-files should not retry (advisory, generative)."""
    from local_llm_worker import NO_RETRY_TASKS
    assert "find-related-files" in NO_RETRY_TASKS


def test_find_related_files_prompt_registry():
    """J-K2: prompt registry entry must exist and have valid hash."""
    import json
    from pathlib import Path
    import hashlib
    registry_path = Path(__file__).parent.parent / "tools" / "prompts" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = registry["prompts"].get("find-related-files")
    assert entry is not None, "find-related-files missing from registry.json"
    assert entry["prompt_id"] == "find-related-files"
    assert entry["version"] == "v1"
    assert entry["file"] == "find-related-files.v1.md"
    prompt_path = Path(__file__).parent.parent / "tools" / "prompts" / entry["file"]
    text = prompt_path.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    assert entry["hash"] == actual_hash, f"hash mismatch: stored={entry['hash'][:8]}, actual={actual_hash[:8]}"


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


# ---------------------------------------------------------------------------
# v0.10.0-M — endpoint resolution unification tests
# ---------------------------------------------------------------------------


def test_resolve_provider_explicit():
    """--provider takes highest priority."""
    from local_llm_worker import _resolve_provider
    assert _resolve_provider("ollama") == "ollama"
    assert _resolve_provider("openai-compatible") == "openai-compatible"


def test_resolve_provider_from_env(monkeypatch):
    """LOCAL_LLM_PROVIDER env takes effect when no CLI arg."""
    from local_llm_worker import _resolve_provider
    monkeypatch.setenv("LOCAL_LLM_PROVIDER", "openai-compatible")
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert _resolve_provider(None) == "openai-compatible"


def test_resolve_provider_default_ollama(monkeypatch):
    """Default to ollama when nothing is set."""
    from local_llm_worker import _resolve_provider
    monkeypatch.delenv("LOCAL_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert _resolve_provider(None) == "ollama"


def test_resolve_endpoint_ollama_default(monkeypatch):
    """Ollama default is localhost:11434."""
    from local_llm_worker import _resolve_endpoint
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert _resolve_endpoint("ollama") == "http://localhost:11434"


def test_resolve_endpoint_openai_compat_default(monkeypatch):
    """OpenAI-compatible default is localhost:8080/v1."""
    from local_llm_worker import _resolve_endpoint
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert _resolve_endpoint("openai-compatible") == "http://localhost:8080/v1"


def test_resolve_endpoint_args_override(monkeypatch):
    """--base-url overrides all env vars."""
    from local_llm_worker import _resolve_endpoint
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://env.example.com:11434")
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama-host.example.com")
    assert _resolve_endpoint("ollama", "http://cli.example.com:9999") == "http://cli.example.com:9999"


def test_resolve_endpoint_local_llm_base_url_priority(monkeypatch):
    """LOCAL_LLM_BASE_URL takes priority over OLLAMA_HOST."""
    from local_llm_worker import _resolve_endpoint
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://env.example.com:11434")
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama-host.example.com")
    assert _resolve_endpoint("ollama") == "http://env.example.com:11434"


def test_resolve_endpoint_ollama_host_fallback(monkeypatch):
    """OLLAMA_HOST used when LOCAL_LLM_BASE_URL not set."""
    from local_llm_worker import _resolve_endpoint
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "193.168.2.2")
    # OLLAMA_HOST without http:// prefix gets normalized
    assert _resolve_endpoint("ollama") == "http://193.168.2.2"


def test_resolve_endpoint_ollama_host_with_http(monkeypatch):
    """OLLAMA_HOST with http:// prefix preserved as-is."""
    from local_llm_worker import _resolve_endpoint
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://192.168.2.2:11434")
    assert _resolve_endpoint("ollama") == "http://192.168.2.2:11434"


def test_debate_resolve_base_url_delegates_to_shared(monkeypatch):
    """debate's resolve_base_url uses the same logic as worker."""
    from local_llm_worker import _resolve_endpoint
    from local_llm_debate import resolve_base_url
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert resolve_base_url("ollama") == _resolve_endpoint("ollama")
    assert resolve_base_url("openai-compatible") == _resolve_endpoint("openai-compatible")


def test_debate_worker_agree_on_defaults(monkeypatch):
    """worker and debate produce same endpoint given identical env."""
    from local_llm_worker import _resolve_provider, _resolve_endpoint
    from local_llm_debate import resolve_base_url
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_PROVIDER", raising=False)
    provider = _resolve_provider(None)
    worker_url = _resolve_endpoint(provider)
    debate_url = resolve_base_url(provider)
    assert worker_url == debate_url


def test_worker_config_uses_shared_helpers(monkeypatch):
    """resolve_config() uses the shared helpers internally."""
    import argparse
    from local_llm_worker import resolve_config
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_LLM_PROVIDER", raising=False)
    args = argparse.Namespace(
        task="summarize-file", profile=None, target=None, max_files=20,
        provider=None, model=None, base_url=None, timeout=None,
        max_chars=None, max_output_chars=None, output_dir=None,
        target_language=None, style=None, json_only=False, no_markdown=False,
        stream=False,
    )
    cfg = resolve_config(args)
    assert cfg.provider == "ollama"
    assert cfg.base_url == "http://localhost:11434"
