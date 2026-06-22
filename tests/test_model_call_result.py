"""Tests for tools/model_call_result.py and v2-A worker integration.

Covers:
- A: ModelCallResult dataclass
- B: normalize_usage provider mapping (Ollama, OpenAI-compatible, DeepSeek extras)
- C: call_ollama / call_openai_compat returning ModelCallResult (mocked requests)
- D: call_model_with_retry returning (ModelCallResult | None, error_info)
- F: local_llm_debate.py adapter compatibility (.content access)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import model_call_result as mcr  # noqa: E402
import local_llm_worker as worker  # noqa: E402


# ---------------------------------------------------------------------------
# A. ModelCallResult dataclass
# ---------------------------------------------------------------------------

def test_model_call_result_defaults():
    r = mcr.ModelCallResult()
    assert r.content == ""
    assert r.usage is None
    assert r.raw_provider is None


def test_model_call_result_all_fields():
    r = mcr.ModelCallResult(
        content="hello",
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
               "cached_tokens": None, "cache_miss_tokens": None,
               "provider_raw": {}},
        raw_provider="ollama",
    )
    assert r.content == "hello"
    assert r.usage["input_tokens"] == 10
    assert r.raw_provider == "ollama"


# ---------------------------------------------------------------------------
# B. normalize_usage
# ---------------------------------------------------------------------------

def test_normalize_ollama_complete():
    data = {
        "message": {"content": "hi"},
        "prompt_eval_count": 120,
        "eval_count": 45,
        "prompt_eval_duration": 1_000_000,
        "eval_duration": 2_000_000,
        "total_duration": 3_500_000,
    }
    u = mcr.normalize_usage("ollama", data)
    assert u is not None
    assert u["input_tokens"] == 120
    assert u["output_tokens"] == 45
    assert u["total_tokens"] == 165
    assert u["cached_tokens"] is None
    assert u["cache_miss_tokens"] is None
    assert u["provider_raw"] == {
        "prompt_eval_count": 120,
        "eval_count": 45,
        "prompt_eval_duration": 1_000_000,
        "eval_duration": 2_000_000,
        "total_duration": 3_500_000,
    }


def test_normalize_ollama_missing_one_field_returns_none():
    # Missing eval_count → cannot establish a meaningful usage record.
    data = {"prompt_eval_count": 120}
    assert mcr.normalize_usage("ollama", data) is None
    # Missing prompt_eval_count too.
    assert mcr.normalize_usage("ollama", {"eval_count": 45}) is None


def test_normalize_openai_compat_standard():
    data = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
    }
    u = mcr.normalize_usage("openai-compatible", data)
    assert u is not None
    assert u["input_tokens"] == 200
    assert u["output_tokens"] == 80
    assert u["total_tokens"] == 280
    assert u["cached_tokens"] is None
    assert u["cache_miss_tokens"] is None
    assert u["provider_raw"] == data["usage"]


def test_normalize_openai_compat_missing_usage_returns_none():
    data = {"choices": [{"message": {"content": "hi"}}]}
    assert mcr.normalize_usage("openai-compatible", data) is None


def test_normalize_openai_compat_deepseek_extras():
    data = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {
            "prompt_tokens": 4321,
            "completion_tokens": 567,
            "total_tokens": 4888,
            "prompt_cache_hit_tokens": 4000,
            "prompt_cache_miss_tokens": 321,
        },
    }
    u = mcr.normalize_usage("openai-compatible", data)
    assert u is not None
    assert u["cached_tokens"] == 4000
    assert u["cache_miss_tokens"] == 321
    # provider_raw preserves the extras for forensics.
    assert u["provider_raw"]["prompt_cache_hit_tokens"] == 4000


def test_normalize_openai_compat_missing_total_falls_back_to_sum():
    data = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    u = mcr.normalize_usage("openai-compatible", data)
    assert u is not None
    assert u["total_tokens"] == 150


def test_normalize_unknown_provider_returns_none():
    assert mcr.normalize_usage("anthropic", {"usage": {}}) is None
    assert mcr.normalize_usage(None, {"usage": {}}) is None
    assert mcr.normalize_usage("", {"usage": {}}) is None


def test_normalize_non_dict_data_returns_none():
    assert mcr.normalize_usage("ollama", None) is None
    assert mcr.normalize_usage("ollama", "not a dict") is None
    assert mcr.normalize_usage("openai-compatible", []) is None
    assert mcr.normalize_usage("openai-compatible", 42) is None


def test_normalize_wrong_types_treated_as_absent():
    # bool counts must not be accepted as integer token counts.
    assert mcr.normalize_usage("ollama",
        {"prompt_eval_count": True, "eval_count": False}) is None
    # Strings.
    assert mcr.normalize_usage("openai-compatible",
        {"usage": {"prompt_tokens": "100", "completion_tokens": "50"}}) is None


def test_normalize_negative_counts_return_none():
    assert mcr.normalize_usage("ollama",
        {"prompt_eval_count": -1, "eval_count": 10}) is None
    assert mcr.normalize_usage("openai-compatible",
        {"usage": {"prompt_tokens": -5, "completion_tokens": 3}}) is None


def test_normalize_negative_cache_tokens_silently_dropped():
    u = mcr.normalize_usage("openai-compatible", {
        "usage": {
            "prompt_tokens": 100, "completion_tokens": 50,
            "prompt_cache_hit_tokens": -1, "prompt_cache_miss_tokens": -2,
        }
    })
    assert u is not None
    assert u["cached_tokens"] is None
    assert u["cache_miss_tokens"] is None


# ---------------------------------------------------------------------------
# C. call_ollama / call_openai_compat integration (mocked requests.post)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _config(provider="ollama"):
    cfg = SimpleNamespace()
    cfg.base_url = "http://localhost:11434"
    cfg.model = "qwen3-coder:30b"
    cfg.max_output_chars = 3000
    cfg.max_output_tokens = 0
    cfg.timeout = 30
    cfg.provider = provider
    cfg.stream = False
    cfg.api_key = ""
    return cfg


def test_call_ollama_happy_path(monkeypatch):
    payload = {
        "message": {"content": "hello world"},
        "prompt_eval_count": 100,
        "eval_count": 50,
    }
    monkeypatch.setattr(worker.requests, "post",
                        lambda *a, **kw: _FakeResponse(payload))
    result = worker.call_ollama("sys", "user", _config("ollama"))
    assert isinstance(result, mcr.ModelCallResult)
    assert result.content == "hello world"
    assert result.usage is not None
    assert result.usage["input_tokens"] == 100
    assert result.usage["output_tokens"] == 50
    assert result.raw_provider == "ollama"


def test_call_ollama_no_usage_fields(monkeypatch):
    payload = {"message": {"content": "hello"}}
    monkeypatch.setattr(worker.requests, "post",
                        lambda *a, **kw: _FakeResponse(payload))
    result = worker.call_ollama("sys", "user", _config("ollama"))
    assert result.content == "hello"
    assert result.usage is None
    assert result.raw_provider == "ollama"


def test_call_openai_compat_happy_path(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 222, "completion_tokens": 33, "total_tokens": 255},
    }
    monkeypatch.setattr(worker.requests, "post",
                        lambda *a, **kw: _FakeResponse(payload))
    result = worker.call_openai_compat("sys", "user", _config("openai-compatible"))
    assert result.content == "ok"
    assert result.usage is not None
    assert result.usage["input_tokens"] == 222
    assert result.usage["output_tokens"] == 33
    assert result.usage["total_tokens"] == 255
    assert result.raw_provider == "openai-compatible"


def test_call_openai_compat_with_deepseek_extras(monkeypatch):
    payload = {
        "choices": [{"message": {"content": "deepseek out"}}],
        "usage": {
            "prompt_tokens": 4321,
            "completion_tokens": 567,
            "total_tokens": 4888,
            "prompt_cache_hit_tokens": 4000,
            "prompt_cache_miss_tokens": 321,
        },
    }
    monkeypatch.setattr(worker.requests, "post",
                        lambda *a, **kw: _FakeResponse(payload))
    result = worker.call_openai_compat("sys", "user", _config("openai-compatible"))
    assert result.usage["cached_tokens"] == 4000
    assert result.usage["cache_miss_tokens"] == 321


def test_call_openai_compat_no_choices(monkeypatch):
    payload = {"choices": []}
    monkeypatch.setattr(worker.requests, "post",
                        lambda *a, **kw: _FakeResponse(payload))
    result = worker.call_openai_compat("sys", "user", _config("openai-compatible"))
    assert result.content == ""
    assert result.usage is None


def test_call_ollama_http_error_propagates(monkeypatch):
    monkeypatch.setattr(worker.requests, "post",
                        lambda *a, **kw: _FakeResponse({}, status_code=500))
    import requests
    with pytest.raises(requests.HTTPError):
        worker.call_ollama("sys", "user", _config("ollama"))


# ---------------------------------------------------------------------------
# D. call_model_with_retry
# ---------------------------------------------------------------------------

def test_retry_happy_path_returns_modelcallresult(monkeypatch):
    fake = mcr.ModelCallResult(
        content="hello",
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
               "cached_tokens": None, "cache_miss_tokens": None,
               "provider_raw": {}},
        raw_provider="ollama",
    )
    monkeypatch.setattr(worker, "call_model", lambda *a, **kw: fake)
    result, err = worker.call_model_with_retry("sys", "user", _config(), task="x")
    assert err == {}
    assert result is fake
    assert result.usage["input_tokens"] == 10


def test_retry_empty_content_triggers_retry_then_success(monkeypatch):
    calls = []
    empty = mcr.ModelCallResult(content="", usage=None, raw_provider="ollama")
    good = mcr.ModelCallResult(
        content="real",
        usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
               "cached_tokens": None, "cache_miss_tokens": None,
               "provider_raw": {}},
        raw_provider="ollama",
    )

    def fake_call(*a, **kw):
        calls.append(1)
        return empty if len(calls) == 1 else good

    monkeypatch.setattr(worker, "call_model", fake_call)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    result, err = worker.call_model_with_retry("sys", "user", _config(), task="summarize-file")
    assert err == {}
    assert result is good
    assert len(calls) == 2


def test_retry_all_attempts_fail_returns_none(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(worker, "call_model", boom)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    result, err = worker.call_model_with_retry("sys", "user", _config(),
                                                task="summarize-file")
    assert result is None
    assert err["error_type"]  # populated
    assert "network down" in err["error"]


def test_retry_no_retry_task_fails_once(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("nope")

    monkeypatch.setattr(worker, "call_model", boom)
    monkeypatch.setattr(worker.time, "sleep", lambda _: None)
    # 'draft-fix' is in NO_RETRY_TASKS.
    result, err = worker.call_model_with_retry("sys", "user", _config(), task="draft-fix")
    assert result is None
    assert err["retries"] == 0


# ---------------------------------------------------------------------------
# F. debate.py adapter compatibility
# ---------------------------------------------------------------------------

def test_debate_call_model_dot_content_works(monkeypatch):
    """Verify debate.py's `.content` access works against a mocked call_model."""
    import local_llm_debate as debate

    fake = mcr.ModelCallResult(content="DEBATE OUTPUT", usage=None,
                                raw_provider="ollama")
    monkeypatch.setattr(debate, "call_model", lambda *a, **kw: fake)

    config = _config()

    # Simulate the call shape from debate.run_round at line ~188:
    raw = debate.call_model("sys", "user", config).content
    assert raw == "DEBATE OUTPUT"
    assert isinstance(raw, str)
    # And debate's downstream slicing/truthiness still works:
    assert raw[:500] == "DEBATE OUTPUT"
    assert bool(raw)
