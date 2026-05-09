"""Test local_llm_logging.py — structured JSONL logging."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_logging as log_mod


def test_is_logging_enabled_default(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_LOG", raising=False)
    assert log_mod.is_logging_enabled()


def test_is_logging_disabled(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LOG", "0")
    assert not log_mod.is_logging_enabled()


def test_write_log_entry(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "1")

        log_mod.write_log_entry({"source": "test", "tool": "local_check",
                                  "task": "check", "ok": True,
                                  "duration_sec": 1.5})

        assert log_mod.LOG_FILE.exists()
        lines = log_mod.LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["source"] == "test"
        assert entry["ok"] is True


def test_log_success(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "1")

        log_mod.log_success("cli", "summarize_file", "summarize-file",
                            "fast_summary", "gemma4:e4b", "ollama",
                            31.2, 1000, 500, cache_hit=True, retries=0)

        entry = json.loads(log_mod.LOG_FILE.read_text(encoding="utf-8").strip())
        assert entry["ok"] is True
        assert entry["cache_hit"] is True
        assert entry["retries"] == 0
        assert entry["task"] == "summarize-file"


def test_log_failure(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "1")

        log_mod.log_failure("mcp", "local_review_diff", "review-diff",
                            "diff_reviewer", "nemotron", "ollama",
                            120.0, "timeout", "model timed out",
                            5000, retries=1)

        entry = json.loads(log_mod.LOG_FILE.read_text(encoding="utf-8").strip())
        assert entry["ok"] is False
        assert entry["error_type"] == "timeout"
        assert entry["retries"] == 1


def test_log_disabled_does_not_write(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "0")

        log_mod.write_log_entry({"source": "test", "ok": True})
        assert not log_mod.LOG_FILE.exists()


def test_log_has_request_id(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "1")

        log_mod.write_log_entry({"source": "test", "ok": True})
        entry = json.loads(log_mod.LOG_FILE.read_text(encoding="utf-8").strip())
        assert "request_id" in entry
        assert entry["request_id"].startswith("req_")


def test_log_no_sensitive_fields(monkeypatch):
    """ensure prompt, response, file content are REDACTED."""
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "1")

        log_mod.write_log_entry({
            "source": "test", "ok": True,
            "prompt": "secret prompt", "response": "secret output",
            "api_key": "sk-1234", "file_content": "password=123",
        })

        entry = json.loads(log_mod.LOG_FILE.read_text(encoding="utf-8").strip())
        assert "prompt" not in entry
        assert "response" not in entry
        assert "api_key" not in entry
        assert "file_content" not in entry
        assert entry["source"] == "test"


def test_log_contains_required_fields(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        log_mod.LOG_DIR = Path(tmp)
        log_mod.LOG_FILE = log_mod.LOG_DIR / "local_llm.jsonl"
        monkeypatch.setenv("LOCAL_LLM_LOG", "1")

        log_mod.write_log_entry({"source": "test", "ok": True})
        entry = json.loads(log_mod.LOG_FILE.read_text(encoding="utf-8").strip())
        assert "timestamp" in entry
        assert "request_id" in entry
        assert "source" in entry
