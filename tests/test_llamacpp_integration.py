"""Integration tests for the llama.cpp default-backend migration.

These tests verify that worker, health check, residency daemon, and route
committee all default to the OpenAI-compatible LiteLLM/llama.cpp gateway at
http://127.0.0.1:4000/v1, and that Ollama paths are only triggered explicitly.

Tests that require a live LiteLLM endpoint are skipped automatically when the
endpoint is unreachable. Mock-based tests run unconditionally.
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _live_litellm_reachable() -> bool:
    try:
        import requests
        resp = requests.get("http://127.0.0.1:4000/v1/models", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


LIVE_LITELLM = _live_litellm_reachable()


# --------------------------------------------------------------------------- #
# Worker default provider
# --------------------------------------------------------------------------- #

def test_worker_defaults_to_openai_compatible():
    import local_llm_worker as worker

    with patch.dict(os.environ, {}, clear=True):
        provider = worker._resolve_provider()
        assert provider == "openai-compatible"
        endpoint = worker._resolve_endpoint(provider)
        assert endpoint == "http://127.0.0.1:4000/v1"


def test_worker_ollama_detected_on_11434():
    import local_llm_worker as worker

    with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434/v1"}, clear=True):
        provider = worker._resolve_provider()
        assert provider == "ollama"


# --------------------------------------------------------------------------- #
# Health check defaults to LiteLLM /v1/models
# --------------------------------------------------------------------------- #

def test_check_litellm_uses_v1_models_and_api_key(monkeypatch):
    import local_llm_check as chk

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    calls = []

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "qwen3.6-deep"}, {"id": "gemma4-31b"}]}

    def fake_get(url, headers=None, timeout=5):
        calls.append((url, headers))
        return FakeResp()

    monkeypatch.setattr(chk.requests, "get", fake_get)
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "sk-test")

    result = chk.check_litellm()
    assert result.ok is True
    assert len(calls) == 1
    assert calls[0][0] == "http://127.0.0.1:4000/v1/models"
    assert calls[0][1].get("Authorization") == "Bearer sk-test"


@pytest.mark.skipif(not LIVE_LITELLM, reason="LiteLLM not reachable at 127.0.0.1:4000")
def test_check_litellm_live_lists_models():
    import local_llm_check as chk

    result = chk.check_litellm()
    assert result.ok is True
    assert result.data
    assert any("qwen3.6-deep" in m or "gemma4-31b" in m for m in result.data)


# --------------------------------------------------------------------------- #
# Residency keepalive via /v1/chat/completions
# --------------------------------------------------------------------------- #

def test_residency_keepalive_uses_chat_completions(monkeypatch):
    import local_llm_residency as residency

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    calls = []

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "pong"}}]}

    def fake_post(url, json=None, headers=None, timeout=30):
        calls.append((url, json, headers))
        return FakeResp()

    monkeypatch.setattr(residency.requests, "post", fake_post)
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "sk-test")

    result = residency._send_keepalive("qwen3.6-deep", "30m")
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == "http://127.0.0.1:4000/v1/chat/completions"
    assert calls[0][1]["model"] == "qwen3.6-deep"
    assert calls[0][1]["messages"] == [{"role": "user", "content": "ping"}]
    assert calls[0][1]["max_tokens"] == 1
    assert calls[0][2].get("Authorization") == "Bearer sk-test"


def test_residency_defaults_to_llamacpp_models():
    import local_llm_residency as residency

    assert residency.DEFAULT_MODELS == ["qwen3.6-deep", "gemma4-31b"]


# --------------------------------------------------------------------------- #
# Route committee uses /v1/chat/completions
# --------------------------------------------------------------------------- #

def test_route_committee_call_model_uses_chat_completions(monkeypatch):
    import local_route_committee as committee

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    calls = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "{\"delegability\":\"high\",\"recommended_route\":\"local_only\",\"local_preprocessing_required\":true,\"pro_should_execute\":false,\"pro_should_adjudicate\":false,\"risk_level\":\"low\",\"privacy_status\":\"safe\",\"reason\":\"ok\",\"required_artifacts\":[]}"}}]
            }).encode("utf-8")

    def fake_urlopen(req, timeout=90):
        calls.append((req.full_url, req.data, req.headers))
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    raw = committee._call_model("qwen3.6-deep", "route this task")
    assert "recommended_route" in raw
    assert len(calls) == 1
    assert calls[0][0] == "http://127.0.0.1:4000/v1/chat/completions"

    payload = json.loads(calls[0][1])
    assert payload["model"] == "qwen3.6-deep"
    assert payload["messages"] == [{"role": "user", "content": "route this task"}]


def test_route_committee_defaults_to_llamacpp_model_names():
    import local_route_committee as committee

    with patch.dict(os.environ, {}, clear=True):
        assert committee._LOCAL_ROUTE_QWEN_MODEL == "qwen3.6-deep"
        assert committee._LOCAL_ROUTE_GEMMA_MODEL == "gemma4-31b"
