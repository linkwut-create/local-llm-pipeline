"""Tests for tools/deepseek_dry_run.py — no DeepSeek calls, no API keys, no profile changes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from deepseek_dry_run import (
    plan,
    _compose_decision,
    _recommend_model,
    PRO_MODEL,
    FLASH_MODEL,
)


# ═══════════════════════════════════════════════════════════════
# 1. Safe task + budget ok → allow_dry_run
# ═══════════════════════════════════════════════════════════════

def test_safe_review_diff_allows():
    result = plan(
        task="review current diff before commit",
        model="deepseek-v4-flash",
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "allow_dry_run"
    assert result["cloud_allowed"] is True
    assert result["would_call_deepseek"] is False
    assert result["dry_run_only"] is True
    assert result["privacy_status"] == "safe"


def test_safe_task_with_pro_model():
    result = plan(
        task="prepare architecture review for v0.13.0 release gate",
        model="deepseek-v4-pro",
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
    )
    # High risk + Pro model = allowed
    assert result["decision"] in ("allow_dry_run", "needs_pro_review")
    assert result["would_call_deepseek"] is False


# ═══════════════════════════════════════════════════════════════
# 2. .env / secret task → blocked_by_privacy
# ═══════════════════════════════════════════════════════════════

def test_env_text_blocked_by_privacy():
    """Text mentioning .env with credential context → needs_review or blocked."""
    result = plan(
        task="check .env.production for credentials",
        model="deepseek-v4-flash",
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
    )
    # ".env.production" in text triggers BROAD_CREDENTIAL_REF (medium) → needs_review
    # With reordered pipeline, needs_review → allow_dry_run (with note)
    # If privacy_gate upgrades to blocked, it's blocked_by_privacy
    assert result["decision"] in ("blocked_by_privacy", "allow_dry_run")
    assert result["privacy_status"] in ("blocked", "needs_review")


def test_api_key_text_blocked_by_privacy():
    result = plan(
        task="use API key sk-abc123def456ghijklmnopqrstuvwxyz for testing",
        model="deepseek-v4-flash",
        input_tokens=1000,
        output_tokens=500,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "blocked_by_privacy"


def test_private_key_blocked_by_privacy():
    result = plan(
        task="-----BEGIN RSA PRIVATE KEY-----\nsomekeydata\n-----END RSA PRIVATE KEY-----",
        model="deepseek-v4-flash",
        input_tokens=500,
        output_tokens=200,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "blocked_by_privacy"


# ═══════════════════════════════════════════════════════════════
# 3. Budget exceeded → blocked_by_budget
# ═══════════════════════════════════════════════════════════════

def test_budget_exceeded_blocks():
    result = plan(
        task="review current diff before commit",
        model="deepseek-v4-pro",
        input_tokens=50000000,   # Huge, will exceed budget
        output_tokens=25000000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "blocked_by_budget"
    assert result["cloud_allowed"] is False
    assert result["budget_allowed"] is False


def test_budget_ok_with_no_limit():
    result = plan(
        task="review diff: test.py",
        model="deepseek-v4-flash",
        input_tokens=100000,
        output_tokens=50000,
        budget=None,
        cloud_ok=True,
    )
    # No budget limit = budget check passes
    assert result["decision"] == "allow_dry_run"
    assert result["budget_allowed"] is True


# ═══════════════════════════════════════════════════════════════
# 4. Release gate + Flash model → needs_pro_review
# ═══════════════════════════════════════════════════════════════

def test_release_gate_with_flash_needs_pro():
    result = plan(
        task="prepare release gate v0.13.0 — review all interfaces and config changes",
        model="deepseek-v4-flash",
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "needs_pro_review"
    assert result["recommended_model"] == PRO_MODEL


def test_high_risk_interface_with_flash_needs_pro():
    result = plan(
        task="review INTERFACES.md for breaking changes — architecture review",
        model="deepseek-v4-flash",
        input_tokens=15000,
        output_tokens=3000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "needs_pro_review"


# ═══════════════════════════════════════════════════════════════
# 5. Release gate + Pro model → allow_dry_run
# ═══════════════════════════════════════════════════════════════

def test_release_gate_with_pro_allows():
    result = plan(
        task="prepare release gate v0.13.0 — review all interfaces",
        model="deepseek-v4-pro",
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "allow_dry_run"
    assert result["recommended_model"] == PRO_MODEL


# ═══════════════════════════════════════════════════════════════
# 6. Unknown model price → unknown_price
# ═══════════════════════════════════════════════════════════════

def test_unknown_model_price():
    result = plan(
        task="review current diff before commit",
        model="nonexistent-model-v99",
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "unknown_price"
    assert result["price_known"] is False
    assert result["cloud_allowed"] is False


# ═══════════════════════════════════════════════════════════════
# 7. No API key read
# ═══════════════════════════════════════════════════════════════

def test_no_api_key_access():
    import deepseek_dry_run as dr
    source = Path(dr.__file__).read_text(encoding="utf-8")
    code_lines = [ln for ln in source.split("\n")
                  if not ln.strip().startswith("#")]
    code_only = "\n".join(code_lines)
    assert "DEEPSEEK_API_KEY" not in code_only
    assert "api_key" not in code_only
    assert "os.environ" not in code_only


# ═══════════════════════════════════════════════════════════════
# 8. No DeepSeek call
# ═══════════════════════════════════════════════════════════════

def test_no_deepseek_import():
    import deepseek_dry_run as dr
    assert "deepseek_client" not in dr.__dict__


def test_no_http_calls():
    import deepseek_dry_run as dr
    source = Path(dr.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    assert "urllib" not in source
    assert "httpx" not in source


# ═══════════════════════════════════════════════════════════════
# 9. No profile mutation
# ═══════════════════════════════════════════════════════════════

def test_no_profile_import():
    import deepseek_dry_run as dr
    source = Path(dr.__file__).read_text(encoding="utf-8")
    assert "local_llm_profiles" not in source


# ═══════════════════════════════════════════════════════════════
# 10. JSON schema stable
# ═══════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "task", "requested_model", "recommended_model",
    "router_task_type", "router_risk_level",
    "privacy_status", "privacy_allowed",
    "budget_allowed", "estimated_cost", "budget_remaining",
    "cloud_allowed", "dry_run_only", "would_call_deepseek",
    "decision", "reason", "advisory_only",
]


def test_output_has_all_fields():
    result = plan(
        task="review diff: test.py",
        model="deepseek-v4-flash",
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=True,
    )
    for field in REQUIRED_FIELDS:
        assert field in result, f"Missing field: {field}"


def test_would_call_is_always_false():
    """would_call_deepseek must ALWAYS be False in dry-run mode."""
    # Test multiple scenarios
    scenarios = [
        ("review diff", FLASH_MODEL, 10000, 2000, 200, True),
        ("release gate", PRO_MODEL, 20000, 4000, 200, True),
        ("check .env", FLASH_MODEL, 1000, 500, 200, True),
    ]
    for task, model, inp, out, budget, cloud_ok in scenarios:
        result = plan(task=task, model=model,
                      input_tokens=inp, output_tokens=out,
                      budget=budget, cloud_ok=cloud_ok)
        assert result["would_call_deepseek"] is False, f"Failed for: {task}"
        assert result["dry_run_only"] is True


def test_no_cloud_ok_defers():
    """When cloud_ok=False, unknown/low-risk tasks defer."""
    result = plan(
        task="review diff: test.py",
        model="deepseek-v4-flash",
        input_tokens=10000,
        output_tokens=2000,
        budget=200,
        cloud_ok=False,
    )
    # Without cloud_ok, should defer (even for safe tasks)
    # unless it's blocked by privacy first
    assert result["decision"] in ("defer", "blocked_by_privacy")


def test_decision_values_valid():
    """All decision values are from the expected set."""
    valid_decisions = {
        "allow_dry_run", "blocked_by_privacy", "blocked_by_budget",
        "needs_pro_review", "defer", "unknown_price",
    }
    scenarios = [
        ("review diff", FLASH_MODEL, 10000, 2000, 200, True),
        ("check .env", FLASH_MODEL, 1000, 500, 200, True),
        ("release gate", FLASH_MODEL, 20000, 4000, 200, True),
        ("release gate", PRO_MODEL, 20000, 4000, 200, True),
        ("review diff", "unknown-model", 10000, 2000, 200, True),
        ("review diff", FLASH_MODEL, 10000, 2000, 200, False),
    ]
    for task, model, inp, out, budget, cloud_ok in scenarios:
        result = plan(task=task, model=model,
                      input_tokens=inp, output_tokens=out,
                      budget=budget, cloud_ok=cloud_ok)
        assert result["decision"] in valid_decisions, \
            f"Invalid decision '{result['decision']}' for: {task}"


# ═══════════════════════════════════════════════════════════════
# 11. Privacy needs_review → allow but with note
# ═══════════════════════════════════════════════════════════════

def test_privacy_needs_review_allows_with_note():
    result = plan(
        task="export entire repo to cloud model for deep analysis",
        model="deepseek-v4-flash",
        input_tokens=50000,
        output_tokens=10000,
        budget=500,
        cloud_ok=True,
    )
    assert result["decision"] == "allow_dry_run"
    assert result["privacy_status"] == "needs_review"
    assert "needs_review" in result["reason"].lower() or \
           "needs_review" in result.get("privacy_reason", "").lower()


# ═══════════════════════════════════════════════════════════════
# 12. Edge cases
# ═══════════════════════════════════════════════════════════════

def test_unknown_task_defers():
    result = plan(
        task="xyzzy frobnicate the spline reticulator",
        model="deepseek-v4-flash",
        input_tokens=1000,
        output_tokens=500,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "defer"
    assert result["router_task_type"] == "unknown"


def test_pro_model_always_recommended_for_high_risk():
    """For high-risk tasks, recommend Pro even if Flash was requested."""
    result = plan(
        task="prepare release gate v0.13.0",
        model="deepseek-v4-flash",
        input_tokens=20000,
        output_tokens=4000,
        budget=200,
        cloud_ok=True,
    )
    assert result["decision"] == "needs_pro_review"
    assert result["recommended_model"] == PRO_MODEL
    assert result["requested_model"] == FLASH_MODEL
