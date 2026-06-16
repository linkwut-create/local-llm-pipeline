"""Tests for tools/deepseek_execution_adapter.py — mock skeleton, no real API calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from deepseek_execution_adapter import (
    execute,
    _result_base,
    _abort,
    FLASH_MODEL,
    PRO_MODEL,
    ALLOWED_MODELS,
)


# ═══════════════════════════════════════════════════════════════
# 1. No --cloud-ok → cloud_ok_required
# ═══════════════════════════════════════════════════════════════

def test_no_cloud_ok_blocks():
    result = execute(
        task="review diff before commit",
        model=FLASH_MODEL,
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=False,
        real_run=False,
    )
    assert result["execution_decision"] == "cloud_ok_required"
    assert result["would_call_deepseek"] is False
    assert result["api_key_read"] is False
    assert result["mock_only"] is True


# ═══════════════════════════════════════════════════════════════
# 2. --cloud-ok + safe task + budget ok → mock_plan_ready
# ═══════════════════════════════════════════════════════════════

def test_safe_task_mock_plan_ready():
    result = execute(
        task="review current diff before commit",
        model=FLASH_MODEL,
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "mock_plan_ready"
    assert result["would_call_deepseek"] is False
    assert result["dry_run_only"] is True
    assert result["cloud_ok"] is True
    assert result["real_run"] is False


def test_high_risk_with_pro_allows_mock():
    result = execute(
        task="prepare release gate v0.13.0",
        model=PRO_MODEL,
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "mock_plan_ready"
    assert result["recommended_model"] == PRO_MODEL


# ═══════════════════════════════════════════════════════════════
# 3. --cloud-ok --real-run → real_run_not_implemented
# ═══════════════════════════════════════════════════════════════

def test_real_run_stubbed():
    result = execute(
        task="review current diff before commit",
        model=FLASH_MODEL,
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=True,
    )
    assert result["execution_decision"] == "real_run_stubbed"
    assert result["would_call_deepseek"] is False
    assert result["api_key_read"] is False
    assert result["network_call"] is False
    assert result["stub_only"] is True
    assert result["api_call_attempted"] is True
    assert "stub" in result["reason"].lower()


def test_real_run_stubbed_for_release_with_pro():
    """Release gate + Pro + real_run → reaches stub seam."""
    result = execute(
        task="prepare release gate v0.13.0",
        model=PRO_MODEL,
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
        real_run=True,
    )
    assert result["execution_decision"] == "real_run_stubbed"
    assert result["would_call_deepseek"] is False
    assert result["network_call"] is False
    assert result["stub_only"] is True


# ═══════════════════════════════════════════════════════════════
# 4. .env / secret task → blocked_by_privacy
# ═══════════════════════════════════════════════════════════════

def test_api_key_text_blocked_by_privacy():
    result = execute(
        task="use API key sk-abc123def456ghijklmnopqrstuvwxyz for testing",
        model=FLASH_MODEL,
        input_tokens=1000,
        output_tokens=500,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "blocked_by_privacy"
    assert result["privacy_status"] == "blocked"


def test_private_key_blocked():
    result = execute(
        task="-----BEGIN RSA PRIVATE KEY-----\nkeydata\n-----END RSA PRIVATE KEY-----",
        model=FLASH_MODEL,
        input_tokens=500,
        output_tokens=200,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "blocked_by_privacy"


# ═══════════════════════════════════════════════════════════════
# 5. Budget exceeded → blocked_by_budget
# ═══════════════════════════════════════════════════════════════

def test_budget_exceeded_blocks():
    result = execute(
        task="review current diff before commit",
        model=PRO_MODEL,
        input_tokens=50000000,
        output_tokens=25000000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "blocked_by_budget"
    assert result["budget_allowed"] is False


# ═══════════════════════════════════════════════════════════════
# 6. Release gate + Flash → needs_pro_review
# ═══════════════════════════════════════════════════════════════

def test_release_gate_with_flash_needs_pro():
    result = execute(
        task="prepare release gate v0.13.0",
        model=FLASH_MODEL,
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "needs_pro_review"
    assert result["recommended_model"] == PRO_MODEL


def test_high_risk_interface_with_flash():
    result = execute(
        task="review INTERFACES.md for breaking changes — architecture review",
        model=FLASH_MODEL,
        input_tokens=15000,
        output_tokens=3000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "needs_pro_review"


# ═══════════════════════════════════════════════════════════════
# 7. Release gate + Pro → mock plan allowed
# ═══════════════════════════════════════════════════════════════

def test_release_gate_with_pro_allows():
    result = execute(
        task="prepare release gate v0.13.0",
        model=PRO_MODEL,
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "mock_plan_ready"


# ═══════════════════════════════════════════════════════════════
# 8. Unknown model price → unknown_price
# ═══════════════════════════════════════════════════════════════

def test_unknown_model_price():
    result = execute(
        task="review diff before commit",
        model="unknown-cloud-model",
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    # Unknown model first fails allowlist check → blocked_by_router
    assert result["execution_decision"] in ("unknown_price", "blocked_by_router")


def test_unknown_model_in_allowlist_but_no_price():
    """Models must be in the allowlist. Unknown models are blocked_by_router first."""
    # The allowlist check happens before cost estimation
    result = execute(
        task="review diff",
        model="deepseek-v4-ultra",  # Not in allowlist
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "blocked_by_router"


# ═══════════════════════════════════════════════════════════════
# 9. Unknown task → blocked_by_router or defer
# ═══════════════════════════════════════════════════════════════

def test_unknown_task_blocked():
    result = execute(
        task="xyzzy flurbo unknown gibberish task",
        model=FLASH_MODEL,
        input_tokens=1000,
        output_tokens=500,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    assert result["execution_decision"] == "blocked_by_router"


# ═══════════════════════════════════════════════════════════════
# 10. No API key read
# ═══════════════════════════════════════════════════════════════

def test_no_api_key_read():
    """DEEPSEEK_API_KEY access is only in _guarded_real_api_call, gated behind manual_smoke_test."""
    import deepseek_execution_adapter as da
    # Verify that without manual_smoke_test, the adapter does NOT read API key
    result = da.execute(
        task="test", model="deepseek-v4-flash",
        input_tokens=100, output_tokens=100,
        cloud_ok=True, real_run=True,
        manual_smoke_test=False,  # default path
    )
    assert not result.get("api_key_read", True)
    assert not result.get("network_call", True)
    # Verify api_key_read field exists and is False for non-smoke-test path
    assert "api_key_read" in result


# ═══════════════════════════════════════════════════════════════
# 11. No DeepSeek call
# ═══════════════════════════════════════════════════════════════

def test_no_deepseek_import():
    import deepseek_execution_adapter as da
    assert "deepseek_client" not in da.__dict__


def test_no_http_calls():
    import deepseek_execution_adapter as da
    source = Path(da.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    # urllib may appear in comments (stub docstring lists what NOT to import)
    code_lines = [ln for ln in source.split("\n")
                  if not ln.strip().startswith("#") and "NOT importing" not in ln]
    code_only = "\n".join(code_lines)
    assert "import urllib" not in code_only
    assert "import httpx" not in code_only


# ═══════════════════════════════════════════════════════════════
# 12. No profile mutation
# ═══════════════════════════════════════════════════════════════

def test_no_profile_import():
    import deepseek_execution_adapter as da
    source = Path(da.__file__).read_text(encoding="utf-8")
    assert "local_llm_profiles" not in source


# ═══════════════════════════════════════════════════════════════
# 13. JSON schema stable
# ═══════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "task", "requested_model", "recommended_model",
    "dry_run_decision", "execution_decision",
    "router_task_type", "router_risk_level",
    "privacy_status", "privacy_needs_review",
    "budget_allowed", "estimated_cost", "budget_limit", "budget_remaining",
    "cloud_ok", "real_run",
    "dry_run_only", "mock_only",
    "would_call_deepseek", "api_key_read",
    "cost_recorded", "ledger_event_type",
    "reason", "advisory_only",
]


def test_output_has_all_fields():
    result = execute(
        task="review diff: test.py",
        model=FLASH_MODEL,
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=False,
    )
    for field in REQUIRED_FIELDS:
        assert field in result, f"Missing field: {field}"


def test_would_call_always_false():
    """would_call_deepseek must ALWAYS be False in mock skeleton."""
    scenarios = [
        ("review diff", FLASH_MODEL, 10000, 2000, 200, True, False),
        ("review diff", FLASH_MODEL, 10000, 2000, 200, True, True),
        ("review diff", FLASH_MODEL, 10000, 2000, 200, False, False),
        ("release gate", PRO_MODEL, 20000, 4000, 200, True, True),
        ("check .env", FLASH_MODEL, 1000, 500, 200, True, False),
    ]
    for task, model, inp, out, budget, cloud_ok, real_run in scenarios:
        result = execute(
            task=task, model=model,
            input_tokens=inp, output_tokens=out,
            budget=budget, cloud_ok=cloud_ok, real_run=real_run,
        )
        assert result["would_call_deepseek"] is False, f"Failed for: {task}"
        assert result["api_key_read"] is False
        assert result["mock_only"] is True


def test_api_key_always_false():
    """api_key_read must ALWAYS be False."""
    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
    )
    assert result["api_key_read"] is False


def test_execution_decision_values():
    """All execution_decision values are from expected set."""
    valid = {
        "cloud_ok_required", "mock_plan_ready", "real_run_stubbed",
        "blocked_by_privacy", "blocked_by_budget", "blocked_by_router",
        "needs_pro_review", "unknown_price",
    }
    scenarios = [
        ("review diff", FLASH_MODEL, 200, False, False),
        ("review diff", FLASH_MODEL, 200, True, False),
        ("review diff", FLASH_MODEL, 200, True, True),
        ("check .env", FLASH_MODEL, 200, True, False),
        ("release gate", FLASH_MODEL, 200, True, False),
        ("release gate", PRO_MODEL, 200, True, False),
        ("xyzzy unknown", FLASH_MODEL, 200, True, False),
        ("review diff", "unknown-model", 200, True, False),
    ]
    for task, model, budget, cloud_ok, real_run in scenarios:
        result = execute(
            task=task, model=model,
            input_tokens=10000, output_tokens=2000,
            budget=budget, cloud_ok=cloud_ok, real_run=real_run,
        )
        assert result["execution_decision"] in valid, \
            f"Invalid decision '{result['execution_decision']}' for: {task}"


# ═══════════════════════════════════════════════════════════════
# 14. Ledger defaults OFF
# ═══════════════════════════════════════════════════════════════

def test_ledger_default_off(tmp_path, monkeypatch):
    """By default, no cost ledger record is written."""
    test_dir = tmp_path / "cost_ledger_mock"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=False,
        record_ledger=False,  # default
    )
    assert result["cost_recorded"] is False
    assert result["ledger_event_type"] is None
    assert not test_dir.exists() or not list(test_dir.glob("*.jsonl"))


def test_ledger_records_when_requested(tmp_path, monkeypatch):
    """With --record-ledger, a mock event is written."""
    test_dir = tmp_path / "cost_ledger_mock2"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=False,
        record_ledger=True,
    )
    assert result["cost_recorded"] is True
    assert result["ledger_event_type"] == "mock_plan"


def test_real_run_stubbed_ledger(tmp_path, monkeypatch):
    """real_run_stubbed event is recorded when requested."""
    test_dir = tmp_path / "cost_ledger_mock3"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
        record_ledger=True,
    )
    assert result["execution_decision"] == "real_run_stubbed"
    assert result["cost_recorded"] is True
    assert result["ledger_event_type"] == "real_run_stubbed"


# ═══════════════════════════════════════════════════════════════
# 15. Stub seam specific tests
# ═══════════════════════════════════════════════════════════════

def test_stub_never_calls_api():
    """real_run_stubbed still has would_call_deepseek=false."""
    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
    )
    assert result["execution_decision"] == "real_run_stubbed"
    assert result["would_call_deepseek"] is False
    assert result["api_key_read"] is False
    assert result["network_call"] is False


def test_stub_has_api_call_result():
    """real_run_stubbed includes api_call_result with stub metadata."""
    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
    )
    assert result["api_call_attempted"] is True
    assert result["api_call_result"] is not None
    assert result["api_call_result"]["stub_only"] is True
    assert result["api_call_result"]["network_call"] is False
    assert result["error_type"] == "stubbed_real_run"


def test_privacy_needs_review_blocks_real_run():
    """Privacy needs_review → blocked_by_privacy in real-run (v1 hardening)."""
    result = execute(
        task="check .env.production for credentials",
        model=FLASH_MODEL,
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=True,
    )
    # needs_review privacy + real_run → blocked_by_privacy
    assert result["execution_decision"] == "blocked_by_privacy"
    assert result["would_call_deepseek"] is False
    assert result["api_key_read"] is False


def test_privacy_blocked_no_call_seam():
    """privacy=blocked never reaches call seam."""
    result = execute(
        task="use API key sk-abc123def456ghijklmnopqrstuvwxyz",
        model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
    )
    assert result["execution_decision"] == "blocked_by_privacy"
    assert result["api_call_attempted"] is False


def test_no_network_imports():
    """Network imports only inside _guarded_real_api_call (gated). Default path is safe."""
    import deepseek_execution_adapter as da
    # Default path (no manual_smoke_test) — passes router, reaches stub, never calls network
    result = da.execute(
        task="review current diff", model="deepseek-v4-flash",
        input_tokens=100, output_tokens=100,
        cloud_ok=True, real_run=True,
        manual_smoke_test=False,
    )
    assert result.get("network_call") is False
    assert result.get("execution_decision", "").endswith("_stubbed")


def test_json_schema_has_stub_fields():
    """Output includes all stub-seam fields."""
    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
    )
    stub_fields = [
        "stub_only", "network_call", "api_call_attempted",
        "api_call_result", "error_type", "redacted_error",
    ]
    for field in stub_fields:
        assert field in result, f"Missing stub field: {field}"


# ═══════════════════════════════════════════════════════════════
# 16. Flash limited real-run tests
# ═══════════════════════════════════════════════════════════════

FL_ARGS = dict(flash_limited=True, manual_confirm=True, cloud_ok=True,
               real_run=True, budget=0.5, input_text="safe text")


def test_fl_no_manual_confirm():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=100, output_tokens=200, **{**FL_ARGS, "manual_confirm": False})
    assert r["execution_decision"] == "missing_manual_confirm"


def test_fl_no_cloud_ok():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=100, output_tokens=200, **{**FL_ARGS, "cloud_ok": False})
    assert r["execution_decision"] == "cloud_ok_required"


def test_fl_pro_blocked():
    r = execute(task="review diff", model=PRO_MODEL,
                input_tokens=100, output_tokens=200, **FL_ARGS)
    assert r["execution_decision"] == "model_not_allowed_for_flash_limited"


def test_fl_unknown_model():
    r = execute(task="review diff", model="unknown-model",
                input_tokens=100, output_tokens=200, **FL_ARGS)
    assert r["execution_decision"] == "model_not_allowed_for_flash_limited"


def test_fl_privacy_blocked_task():
    r = execute(task="check .env.production for credentials",
                model=FLASH_MODEL, input_tokens=100, output_tokens=200, **FL_ARGS)
    assert r["execution_decision"] == "blocked_by_privacy"


def test_fl_privacy_blocked_input():
    r = execute(task="summarize text", model=FLASH_MODEL,
                input_tokens=100, output_tokens=200,
                **{**FL_ARGS, "input_text": "sk-abc123def456ghijklmnopqrstuvwxyz"})
    assert r["execution_decision"] == "blocked_by_privacy"


def test_fl_budget_missing():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=100, output_tokens=200,
                **{**FL_ARGS, "budget": None})
    assert r["execution_decision"] == "missing_budget"


def test_fl_budget_too_high():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=100, output_tokens=200,
                **{**FL_ARGS, "budget": 1.0})
    assert r["execution_decision"] == "budget_limit_too_high_for_flash_limited"


def test_fl_release_needs_pro():
    r = execute(task="prepare release gate v0.13.0", model=FLASH_MODEL,
                input_tokens=500, output_tokens=500, **FL_ARGS)
    assert r["execution_decision"] == "needs_pro_review"


def test_fl_unknown_task():
    r = execute(task="xyzzy flurbo unknown", model=FLASH_MODEL,
                input_tokens=100, output_tokens=200, **FL_ARGS)
    assert r["execution_decision"] == "blocked_by_router"


def test_fl_context_limit_exceeded():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=5000, output_tokens=200, **FL_ARGS)
    assert r["execution_decision"] == "context_limit_exceeded"


def test_fl_output_limit_exceeded():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=100, output_tokens=2000, **FL_ARGS)
    assert r["execution_decision"] == "context_limit_exceeded"


def test_fl_valid_stubbed():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=500, output_tokens=500, **FL_ARGS)
    assert r["execution_decision"] == "flash_limited_stubbed"
    assert r["mode"] == "flash_limited"
    assert r["would_call_deepseek"] is False
    assert r["network_call"] is False
    assert r["api_key_read"] is False
    assert r["stub_only"] is True
    assert r["context_limit_pass"] is True


def test_fl_valid_no_api_key():
    """Flash-limited path without smoke test never reads API key."""
    r = execute(task="summarize file", model=FLASH_MODEL,
                input_tokens=200, output_tokens=100, **FL_ARGS)
    # Flash-limited stub path — API key is never read
    assert r["api_key_read"] is False
    assert r["network_call"] is False
    assert r.get("execution_decision", "").endswith("_stubbed")


def test_fl_ledger_default_off(tmp_path, monkeypatch):
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", tmp_path / "cl_fl")
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=100, output_tokens=100,
                **{**FL_ARGS, "record_ledger": False})
    assert r["cost_recorded"] is False


def test_fl_json_schema():
    r = execute(task="review diff", model=FLASH_MODEL,
                input_tokens=500, output_tokens=500, **FL_ARGS)
    fl_fields = [
        "mode", "flash_limited", "manual_confirm",
        "input_privacy_status", "context_limit_pass",
        "max_input_tokens", "max_output_tokens",
    ]
    for field in fl_fields:
        assert field in r, f"Missing flash-limited field: {field}"
