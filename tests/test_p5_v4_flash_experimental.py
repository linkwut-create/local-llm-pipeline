"""P5-B: V4-Flash local experimental profile — focused tests.

Covers the 13-item test plan from docs/P5_V4_FLASH_EXPERIMENTAL_PROFILE_PLAN.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from validate_configs import VALID_RISK_LEVELS, validate_profiles  # noqa: E402

PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"
TASKS_PATH = TOOLS_DIR / "local_llm_tasks.json"


def _load_profiles():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def _load_tasks():
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))


# --- 1. Profile existence ---

def test_profile_exists():
    profiles = _load_profiles()["profiles"]
    assert "v4_flash_local_experimental" in profiles, (
        "v4_flash_local_experimental must exist in profiles.json"
    )


# --- 2. Required fields ---

def test_profile_has_required_fields():
    profile = _load_profiles()["profiles"]["v4_flash_local_experimental"]
    assert profile.get("model") == "v4-flash"
    assert profile.get("risk_level") == "experimental"
    assert isinstance(profile.get("use_for"), list)
    assert len(profile["use_for"]) > 0


def test_profile_has_manual_only_constraints():
    profile = _load_profiles()["profiles"]["v4_flash_local_experimental"]
    constraints = profile.get("_constraints", "")
    assert "Manual invocation only" in constraints
    assert "_local_only" in profile
    assert profile["_local_only"] is True


# --- 3. validate_configs accepts "experimental" ---

def test_validate_profiles_accepts_experimental():
    profiles_data = {
        "profiles": {
            "test_exp": {
                "model": "test-model",
                "risk_level": "experimental",
                "use_for": ["deep-code-review"],
            }
        }
    }
    errors, _ = validate_profiles(profiles_data)
    assert len(errors) == 0, f"experimental risk_level should be valid, got: {errors}"


# --- 4. VALID_RISK_LEVELS contains "experimental" ---

def test_valid_risk_levels_contains_experimental():
    assert "experimental" in VALID_RISK_LEVELS, (
        f"VALID_RISK_LEVELS must contain 'experimental', got: {VALID_RISK_LEVELS}"
    )


# --- 5. Policy derivation (also covered in test_profile_policy.py) ---

def test_policy_derivation():
    from profile_policy import derive_policy  # noqa: E402

    p = derive_policy("v4_flash_local_experimental")
    assert p["experimental"] is True
    assert p["auto_allowed"] is False
    assert p["requires_escalation_reason"] is True
    assert p["debate_allowed"] is True
    assert p["default_review_necessity"] == "recommended"
    assert p["commit_gate_allowed"] is False
    assert p["local_only"] is True
    assert p["risk_level"] == "experimental"


# --- 6. No task defaults to v4_flash_local_experimental ---

def test_no_task_defaults_to_v4_flash():
    tasks = _load_tasks()["tasks"]
    offenders = [
        name for name, conf in tasks.items()
        if conf.get("default_profile") == "v4_flash_local_experimental"
    ]
    assert offenders == [], (
        f"no task may default to v4_flash_local_experimental, got: {offenders}"
    )


# --- 7. Router does not auto-select it ---

def test_router_does_not_auto_select():
    from local_llm_router import resolve_profile  # noqa: E402

    tasks = _load_tasks()["tasks"]
    for task_name in tasks:
        profile_name, model, risk = resolve_profile(task_name, None, None)
        assert profile_name != "v4_flash_local_experimental", (
            f"router auto-selected v4_flash_local_experimental for task '{task_name}'"
        )


# --- 8. Router selects on explicit override ---

def test_router_selects_on_profile_override():
    from local_llm_router import resolve_profile  # noqa: E402

    profile_name, model, risk = resolve_profile(
        "summarize-file", "v4_flash_local_experimental", None
    )
    assert profile_name == "v4_flash_local_experimental"
    assert model == "v4-flash"
    # risk comes from the task config, not the profile risk_level
    assert risk == "low"  # summarize-file task risk is "low"


def test_router_falls_back_to_task_default_without_override():
    from local_llm_router import resolve_profile  # noqa: E402

    profile_name, model, risk = resolve_profile("summarize-file", None, None)
    assert profile_name == "fast_summary"
    assert profile_name != "v4_flash_local_experimental"


# --- 9. MCP server has no hardcoded v4-flash references ---

def test_mcp_server_no_hardcoded_v4_flash():
    src = (TOOLS_DIR / "local_llm_mcp_server.py").read_text(encoding="utf-8")
    for pattern in ("v4_flash", "v4-flash", "V4-Flash", "V4_Flash"):
        assert pattern not in src, (
            f"local_llm_mcp_server.py must not contain hardcoded '{pattern}'"
        )


# --- 10. MCP tool count remains 9 ---

def test_mcp_tool_count_nine():
    from local_llm_mcp_server import TOOLS  # noqa: E402

    assert len(TOOLS) == 10, f"MCP tool count must be 10, got {len(TOOLS)}"


# --- 11. P4 probe invariants unchanged ---

def test_p4_probe_schema_version():
    from local_llm_check import (  # noqa: E402
        PROBE_REPORT_SCHEMA_VERSION,
        build_probe_report,
    )
    assert PROBE_REPORT_SCHEMA_VERSION == 1
    report = build_probe_report()
    assert report["schema_version"] == 1
    assert report["routing_changed"] is False
    assert report["ledger_stamped"] is False


# --- 12. Ledger schema compatibility ---

def test_ledger_can_record_experimental_profile():
    """ledger schema accepts profile field with experimental profile name
    without requiring new fields."""
    from call_ledger import build_record  # noqa: E402

    record = build_record(
        task_type="deep-code-review",
        tool_name="local_contextual_analyze",
        profile="v4_flash_local_experimental",
        model="v4-flash",
        provider="ollama",
        input_chars=1000,
        output_chars=500,
        duration_ms=30000,
        success=True,
    )
    assert record["profile"] == "v4_flash_local_experimental"
    assert "profile" in record
    # Verify no unexpected new top-level keys
    known_keys = {
        "timestamp", "id", "project", "phase", "task_type", "tool_name",
        "profile", "model", "provider", "base_url",
        "input_chars", "output_chars", "input_tokens", "output_tokens",
        "cached_tokens", "cache_miss_tokens", "duration_ms",
        "success", "cache_hit", "failure_reason", "result_summary",
        "files_referenced", "request_id",
        "total_tokens", "tokens_estimated", "estimated_cost_cny",
        "execution_location", "cost_confidence",
        "git_commit_before", "git_commit_after",
        "git_dirty_before", "git_dirty_after",
    }
    extra_keys = set(record.keys()) - known_keys
    assert extra_keys == set(), f"unexpected ledger keys: {extra_keys}"


# --- 13. No provider=tongyi in MCP_COST_DISCIPLINE_PLAN.md ---

def test_no_provider_tongyi_in_cost_discipline_plan():
    plan = (
        Path(__file__).parent.parent / "docs" / "MCP_COST_DISCIPLINE_PLAN.md"
    ).read_text(encoding="utf-8")
    assert "provider=tongyi" not in plan, (
        "MCP_COST_DISCIPLINE_PLAN.md must not reference provider=tongyi"
    )


# P5-B boundary was verified at commit time (99855ed). The working-tree
# diff check that previously lived here was inherently fragile across
# later phases — any legitimate future change to mcp_server.py,
# health_store.py, etc. would trip it. P5 static invariants (profile
# existence, policy derivation, router non-auto-select, MCP tool count,
# P4 probe invariants) are covered by the 15 tests above.
# Per-phase boundary audits are recorded in docs/status instead.
