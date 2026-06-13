"""Tests for tools/deepseek_smoke_test.py — monkeypatched, no real API calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from deepseek_smoke_test import (
    run_smoke_test,
    _manual_smoke_call_stub,
    _live_smoke_call,
    _extract_response_text,
    _redact_error,
    _safe_preview,
    FIXED_PROMPT,
    FIXED_PROMPT_ID,
    FLASH_MODEL,
    ALLOWED_MODELS,
    MAX_BUDGET_CNY,
)


# ═══════════════════════════════════════════════════════════════
# 1-3: Missing flags (unchanged — still stub path)
# ═══════════════════════════════════════════════════════════════

def test_missing_manual_smoke_test():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True, real_run=True,
                       manual_smoke_test=False, allow_live_smoke=False)
    assert r["execution_decision"] == "missing_manual_smoke_test"


def test_missing_cloud_ok():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=False, real_run=True,
                       manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "missing_cloud_ok"


def test_missing_real_run():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True, real_run=False,
                       manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "missing_real_run"


# ═══════════════════════════════════════════════════════════════
# 4-5: Model restrictions
# ═══════════════════════════════════════════════════════════════

def test_pro_model_not_allowed():
    r = run_smoke_test(model="deepseek-v4-pro", budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "model_not_allowed_for_smoke_test"


def test_unknown_model_not_allowed():
    r = run_smoke_test(model="unknown-model", budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "model_not_allowed_for_smoke_test"


# ═══════════════════════════════════════════════════════════════
# 6-7: Budget constraints
# ═══════════════════════════════════════════════════════════════

def test_missing_budget():
    r = run_smoke_test(model=FLASH_MODEL, budget=None, cloud_ok=True,
                       real_run=True, manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "missing_budget"


def test_budget_too_high():
    r = run_smoke_test(model=FLASH_MODEL, budget=100, cloud_ok=True,
                       real_run=True, manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "budget_limit_too_high"


# ═══════════════════════════════════════════════════════════════
# 8: Valid path → stub seam (no --allow-live-smoke)
# ═══════════════════════════════════════════════════════════════

def test_valid_path_stubbed():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True, allow_live_smoke=False)
    assert r["execution_decision"] == "manual_smoke_test_stubbed"
    assert r["stub_only"] is True
    assert r["live_smoke_enabled"] is False
    assert r["would_call_deepseek"] is False
    assert r["network_call"] is False
    assert r["api_key_read"] is False


# ═══════════════════════════════════════════════════════════════
# 9-11: Allow-live-smoke — missing API key
# ═══════════════════════════════════════════════════════════════

def test_live_smoke_missing_key(monkeypatch):
    """--allow-live-smoke with missing API key → missing_api_key."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       allow_live_smoke=True)
    assert r["execution_decision"] == "missing_api_key"
    assert r["api_key_lookup_attempted"] is True
    assert r["api_key_read"] is False
    assert r["would_call_deepseek"] is False
    assert r["network_call"] is False


def test_live_smoke_no_key_on_gate_failure(monkeypatch):
    """Key lookup NOT attempted when gate fails early."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=False, real_run=True,
                       manual_smoke_test=True, allow_live_smoke=True)
    assert r["execution_decision"] == "missing_cloud_ok"
    assert r["api_key_lookup_attempted"] is False


# ═══════════════════════════════════════════════════════════════
# 12: Monkeypatched live success
# ═══════════════════════════════════════════════════════════════

def test_monkeypatched_live_success(monkeypatch):
    """Monkeypatch _live_smoke_call → smoke_test_success."""
    def fake_live(api_key):
        return {
            "success": True, "response_text": "OK",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "http_status": 200, "elapsed_ms": 500,
            "error_type": None, "error": None,
            "network_call": True, "api_key_read": True,
            "api_key_never_logged": True,
        }
    monkeypatch.setattr("deepseek_smoke_test._live_smoke_call", fake_live)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-placeholder")

    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       allow_live_smoke=True)
    assert r["execution_decision"] == "manual_smoke_test_success"
    assert r["would_call_deepseek"] is True
    assert r["network_call"] is True
    assert r["api_key_read"] is True
    assert r["live_smoke_enabled"] is True
    assert r["response_text_preview"] == "OK"


def test_monkeypatched_live_failure(monkeypatch):
    """Monkeypatch _live_smoke_call → smoke_test_failed."""
    def fake_live(api_key):
        return {
            "success": False, "response_text": "",
            "usage": None, "http_status": 401,
            "elapsed_ms": 200, "error_type": "auth_error",
            "error": "401 Unauthorized",
            "network_call": True, "api_key_read": True,
            "api_key_never_logged": True,
        }
    monkeypatch.setattr("deepseek_smoke_test._live_smoke_call", fake_live)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-placeholder")

    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       allow_live_smoke=True, record_ledger=True)
    assert r["execution_decision"] == "manual_smoke_test_failed"
    assert r["ledger_event_type"] == "smoke_test_failed"


# ═══════════════════════════════════════════════════════════════
# 13-14: API key safety
# ═══════════════════════════════════════════════════════════════

def test_api_key_never_in_output(monkeypatch):
    """API key value never appears in any output field."""
    key = "sk-very-secret-test-key-12345678"
    def fake_live(api_key):
        return {"success": True, "response_text": "OK", "usage": None,
                "http_status": 200, "elapsed_ms": 100,
                "error_type": None, "error": None,
                "network_call": True, "api_key_read": True,
                "api_key_never_logged": True}
    monkeypatch.setattr("deepseek_smoke_test._live_smoke_call", fake_live)
    monkeypatch.setenv("DEEPSEEK_API_KEY", key)

    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       allow_live_smoke=True)
    result_json = json.dumps(r, ensure_ascii=False)
    assert key not in result_json
    assert "sk-very-secret" not in result_json


def test_redact_error_strips_keys():
    """_redact_error removes sk-... patterns."""
    err = "Error: sk-abc123def456ghijklmnop with HTTP 401"
    redacted = _redact_error(err)
    assert "sk-abc123" not in redacted
    assert "REDACTED_KEY" in redacted


# ═══════════════════════════════════════════════════════════════
# 15-16: Fixed prompt
# ═══════════════════════════════════════════════════════════════

def test_fixed_prompt_is_exact():
    assert FIXED_PROMPT == "Reply with exactly: OK"


def test_fixed_prompt_id():
    assert FIXED_PROMPT_ID == "smoke-test-v1-fixed"


# ═══════════════════════════════════════════════════════════════
# 17: Privacy blocked
# ═══════════════════════════════════════════════════════════════

def test_privacy_blocked_fixed_prompt():
    from privacy_gate import check as privacy_check
    result = privacy_check(text=FIXED_PROMPT)
    assert result["privacy_status"] == "safe"


# ═══════════════════════════════════════════════════════════════
# 18-19: Source security
# ═══════════════════════════════════════════════════════════════

def test_no_network_imports():
    import deepseek_smoke_test as ds
    source = Path(ds.__file__).read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import httpx" not in source
    assert "from requests" not in source
    assert "from httpx" not in source


def test_no_api_key_in_code():
    import deepseek_smoke_test as ds
    source = Path(ds.__file__).read_text(encoding="utf-8")
    in_doc = False; code = []
    for ln in source.split("\n"):
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc; continue
        if in_doc: continue
        if s.startswith("#"): continue
        code.append(ln)
    code_only = "\n".join(code)
    # DEEPSEEK_API_KEY access is OK only via os.environ.get (live seam)
    # It should not be hardcoded or in test fixtures
    assert 'DEEPSEEK_API_KEY = "' not in code_only
    assert "DEEPSEEK_API_KEY =" not in code_only


# ═══════════════════════════════════════════════════════════════
# 20: JSON schema stable
# ═══════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "execution_decision", "model", "fixed_prompt_id",
    "fixed_prompt_preview", "live_smoke_enabled",
    "would_call_deepseek", "network_call",
    "api_key_lookup_attempted", "api_key_read",
    "api_key_value_logged", "stub_only",
    "smoke_call_attempted", "smoke_call_result",
    "http_status", "response_text_preview", "usage",
]


def test_output_has_all_fields():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       allow_live_smoke=False)
    for field in REQUIRED_FIELDS:
        assert field in r, f"Missing field: {field}"


# ═══════════════════════════════════════════════════════════════
# Additional
# ═══════════════════════════════════════════════════════════════

def test_stub_result_has_no_network():
    stub = _manual_smoke_call_stub()
    assert stub["network_call"] is False
    assert stub["api_key_read"] is False


def test_allowlist_only_flash():
    assert ALLOWED_MODELS == {"deepseek-v4-flash"}


def test_budget_max_is_1():
    assert MAX_BUDGET_CNY == 1.0


# ═══════════════════════════════════════════════════════════════
# Response extraction tests
# ═══════════════════════════════════════════════════════════════

def test_extract_content_field():
    r = {"ok": True, "content": "OK", "usage": None}
    assert _extract_response_text(r) == "OK"


def test_extract_nested_choices():
    r = {"choices": [{"message": {"content": "Hello"}}]}
    assert _extract_response_text(r) == "Hello"


def test_extract_reasoning_not_in_response():
    """Reasoning_content must NOT be returned as response text."""
    r = {"choices": [{"message": {"content": "", "reasoning_content": "Thought: OK"}}]}
    text = _extract_response_text(r)
    assert text == "", "reasoning_content must not leak into response_text"


def test_extract_text_field():
    r = {"text": "Direct text"}
    assert _extract_response_text(r) == "Direct text"


def test_extract_empty():
    assert _extract_response_text({}) == ""


def test_extract_content_priority():
    """content field takes priority over choices path."""
    r = {"content": "From content", "choices": [{"message": {"content": "From choices"}}]}
    assert _extract_response_text(r) == "From content"


def test_safe_preview_empty():
    assert _safe_preview("") == "(empty)"


def test_safe_preview_none():
    assert _safe_preview(None) == "(no response)"


def test_safe_preview_normal():
    assert _safe_preview("OK") == "OK"


def test_safe_preview_truncate():
    assert len(_safe_preview("x" * 200)) <= 100


def test_reasoning_metadata_extraction():
    """Reasoning metadata: presence=true but raw text NOT in output."""
    from deepseek_smoke_test import _extract_reasoning_metadata
    r = {"choices": [{"message": {"reasoning_content": "secret thought"}}],
         "usage": {"completion_tokens_details": {"reasoning_tokens": 19}}}
    meta = _extract_reasoning_metadata(r)
    assert meta["reasoning_content_present"] is True
    assert meta["reasoning_text_logged"] is False
    assert meta["reasoning_text_included_in_response"] is False
    assert meta["reasoning_tokens"] == 19
    # Raw reasoning text must NOT be in the metadata
    assert "secret" not in str(meta)


def test_reasoning_metadata_none():
    from deepseek_smoke_test import _extract_reasoning_metadata
    meta = _extract_reasoning_metadata({})
    assert meta["reasoning_content_present"] is False


def test_monkeypatched_live_with_content(monkeypatch):
    """Monkeypatched success with content → response_text_preview populated."""
    def fake_live(api_key):
        return {
            "success": True, "response_text": "OK",
            "response_text_source": "content",
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "http_status": 200, "elapsed_ms": 100,
            "error_type": None, "error": None,
            "network_call": True, "api_key_read": True,
            "api_key_never_logged": True,
        }
    monkeypatch.setattr("deepseek_smoke_test._live_smoke_call", fake_live)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-placeholder")

    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       allow_live_smoke=True)
    assert r["execution_decision"] == "manual_smoke_test_success"
    assert r["response_text_preview"] == "OK"
