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

def test_real_run_not_implemented():
    result = execute(
        task="review current diff before commit",
        model=FLASH_MODEL,
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
        real_run=True,
    )
    assert result["execution_decision"] == "real_run_not_implemented"
    assert result["would_call_deepseek"] is False
    assert result["api_key_read"] is False
    assert result["mock_only"] is True
    assert "mock skeleton" in result["reason"].lower()


def test_real_run_blocked_even_for_release():
    """Even release gate tasks cannot bypass mock real-run block."""
    result = execute(
        task="prepare release gate v0.13.0",
        model=PRO_MODEL,
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
        real_run=True,
    )
    assert result["execution_decision"] == "real_run_not_implemented"
    assert result["would_call_deepseek"] is False


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
    import deepseek_execution_adapter as da
    source = Path(da.__file__).read_text(encoding="utf-8")
    # Exclude docstrings and comments
    lines = source.split("\n")
    in_docstring = False
    code_lines = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(ln)
    code_only = "\n".join(code_lines)
    assert "DEEPSEEK_API_KEY" not in code_only
    assert "os.environ" not in code_only
    # api_key_read is a field name (not reading a key) — that's OK
    # Verify no real API key lookup pattern exists
    assert "api_key or os.environ" not in code_only


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
    assert "urllib" not in source


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
        "cloud_ok_required", "mock_plan_ready", "real_run_not_implemented",
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


def test_real_run_not_implemented_ledger(tmp_path, monkeypatch):
    """real_run_not_implemented event is recorded when requested."""
    test_dir = tmp_path / "cost_ledger_mock3"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = execute(
        task="review diff", model=FLASH_MODEL,
        input_tokens=1000, output_tokens=500,
        budget=200, cloud_ok=True, real_run=True,
        record_ledger=True,
    )
    assert result["execution_decision"] == "real_run_not_implemented"
    assert result["cost_recorded"] is True
    assert result["ledger_event_type"] == "real_run_not_implemented"
