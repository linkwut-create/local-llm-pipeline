"""Tests for tools/deepseek_smoke_test.py — skeleton only, no real API calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from deepseek_smoke_test import (
    run_smoke_test,
    _manual_smoke_call_stub,
    FIXED_PROMPT,
    FIXED_PROMPT_ID,
    FLASH_MODEL,
    ALLOWED_MODELS,
    MAX_BUDGET_CNY,
)


# ═══════════════════════════════════════════════════════════════
# 1-3: Missing flags
# ═══════════════════════════════════════════════════════════════

def test_missing_manual_smoke_test():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True, real_run=True,
                       manual_smoke_test=False)
    assert r["execution_decision"] == "missing_manual_smoke_test"
    assert r["would_call_deepseek"] is False


def test_missing_cloud_ok():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=False, real_run=True,
                       manual_smoke_test=True)
    assert r["execution_decision"] == "missing_cloud_ok"


def test_missing_real_run():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True, real_run=False,
                       manual_smoke_test=True)
    assert r["execution_decision"] == "missing_real_run"


# ═══════════════════════════════════════════════════════════════
# 4-5: Model restrictions
# ═══════════════════════════════════════════════════════════════

def test_pro_model_not_allowed():
    r = run_smoke_test(model="deepseek-v4-pro", budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["execution_decision"] == "model_not_allowed_for_smoke_test"


def test_unknown_model_not_allowed():
    r = run_smoke_test(model="unknown-model", budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["execution_decision"] == "model_not_allowed_for_smoke_test"


# ═══════════════════════════════════════════════════════════════
# 6-7: Budget constraints
# ═══════════════════════════════════════════════════════════════

def test_missing_budget():
    r = run_smoke_test(model=FLASH_MODEL, budget=None, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["execution_decision"] == "missing_budget"


def test_budget_too_high():
    r = run_smoke_test(model=FLASH_MODEL, budget=100, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["execution_decision"] == "budget_limit_too_high"


# ═══════════════════════════════════════════════════════════════
# 8: Valid path → stub seam
# ═══════════════════════════════════════════════════════════════

def test_valid_path_stubbed():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["execution_decision"] == "manual_smoke_test_stubbed"
    assert r["stub_only"] is True
    assert r["smoke_call_attempted"] is True
    assert r["smoke_call_result"] is not None
    assert r["smoke_call_result"]["stub_only"] is True


# ═══════════════════════════════════════════════════════════════
# 9-11: Safety invariants
# ═══════════════════════════════════════════════════════════════

def test_valid_path_still_no_api_call():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["would_call_deepseek"] is False


def test_valid_path_still_no_network():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["network_call"] is False


def test_valid_path_still_no_api_key():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    assert r["api_key_read"] is False
    assert r["api_key_lookup_attempted"] is False
    assert r["api_key_value_logged"] is False


# ═══════════════════════════════════════════════════════════════
# 12-13: Fixed prompt
# ═══════════════════════════════════════════════════════════════

def test_fixed_prompt_is_exact():
    assert FIXED_PROMPT == "Reply with exactly: OK"


def test_fixed_prompt_id():
    assert FIXED_PROMPT_ID == "smoke-test-v1-fixed"


# ═══════════════════════════════════════════════════════════════
# 14: Privacy blocked
# ═══════════════════════════════════════════════════════════════

def test_privacy_blocked_fixed_prompt():
    """Fixed prompt 'Reply with exactly: OK' is privacy-safe."""
    from privacy_gate import check as privacy_check
    result = privacy_check(text=FIXED_PROMPT)
    assert result["privacy_status"] == "safe", \
        f"Fixed prompt must be privacy-safe, got {result['privacy_status']}"


# ═══════════════════════════════════════════════════════════════
# 15-16: Ledger
# ═══════════════════════════════════════════════════════════════

def test_ledger_default_off(tmp_path, monkeypatch):
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", tmp_path / "cost_ledger")
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       record_ledger=False)
    assert r["cost_recorded"] is False


def test_ledger_records_stubbed(tmp_path, monkeypatch):
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", tmp_path / "cost_ledger_smoke")
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True,
                       record_ledger=True)
    assert r["cost_recorded"] is True
    assert r["ledger_event_type"] == "manual_smoke_test_stubbed"


# ═══════════════════════════════════════════════════════════════
# 17-18: No network/key imports
# ═══════════════════════════════════════════════════════════════

def test_no_network_imports():
    import deepseek_smoke_test as ds
    source = Path(ds.__file__).read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import httpx" not in source
    assert "import urllib" not in source
    assert "from requests" not in source
    assert "from httpx" not in source


def test_no_api_key_access():
    import deepseek_smoke_test as ds
    source = Path(ds.__file__).read_text(encoding="utf-8")
    # Exclude docstrings
    in_doc = False
    code = []
    for ln in source.split("\n"):
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc; continue
        if in_doc: continue
        if s.startswith("#"): continue
        code.append(ln)
    code_only = "\n".join(code)
    assert "DEEPSEEK_API_KEY" not in code_only
    assert "os.environ" not in code_only


# ═══════════════════════════════════════════════════════════════
# 19: JSON schema stable
# ═══════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "execution_decision", "model", "fixed_prompt_id",
    "fixed_prompt_preview", "estimated_input_tokens",
    "estimated_output_tokens", "budget_limit",
    "privacy_status", "router_task_type", "router_risk_level",
    "cloud_ok", "real_run", "manual_smoke_test",
    "would_call_deepseek", "network_call",
    "api_key_read", "api_key_lookup_attempted",
    "api_key_value_logged", "stub_only",
    "smoke_call_attempted", "smoke_call_result",
    "ledger_event_type", "cost_recorded", "reason",
]


def test_output_has_all_fields():
    r = run_smoke_test(model=FLASH_MODEL, budget=1, cloud_ok=True,
                       real_run=True, manual_smoke_test=True)
    for field in REQUIRED_FIELDS:
        assert field in r, f"Missing field: {field}"


# ═══════════════════════════════════════════════════════════════
# Additional edge cases
# ═══════════════════════════════════════════════════════════════

def test_stub_result_has_no_network():
    stub = _manual_smoke_call_stub()
    assert stub["network_call"] is False
    assert stub["api_key_read"] is False
    assert stub["success"] is False
    assert stub["stub_only"] is True


def test_allowlist_only_flash():
    assert ALLOWED_MODELS == {"deepseek-v4-flash"}
    assert "deepseek-v4-pro" not in ALLOWED_MODELS


def test_budget_max_is_1():
    assert MAX_BUDGET_CNY == 1.0
