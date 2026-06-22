"""Mock tests for local_route_explain MCP tool — no API calls, no profile changes."""

import os
import sys
from pathlib import Path

# Disable SmartClassifier model calls during tests
os.environ["SMART_CLASSIFIER_NO_MODEL"] = "1"

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from local_llm_mcp_server import call_route_explain


# ── Basic invocation ──

def test_docs_review():
    r = call_route_explain({"task": "summarize PROBLEMS.md and suggest missing issues"})
    assert r["ok"] is True
    assert r["task_type"] == "governance-docs"
    assert r["risk_level"] == "low"
    assert r["privacy_status"] == "safe"
    assert r["recommended_local_profile"] == "docs_agent"
    assert r["advisory_only"] is True


def test_release_gate():
    r = call_route_explain({"task": "prepare release gate for v0.13.0"})
    assert r["ok"] is True
    assert r["task_type"] == "release-risk-review"
    assert r["risk_level"] == "high"
    assert r["recommended_local_profile"] is None
    assert "Pro" in r["pro_escalation_condition"]
    assert r["cloud_allowed"] is False  # cloud_ok not set
    assert r["escalate_to_pro"] is False  # cloud_ok not set


def test_interface_change():
    r = call_route_explain({"task": "review interface change in provider config schema"})
    assert r["ok"] is True
    assert r["task_type"] == "interface-review"
    assert r["risk_level"] == "high"
    assert r["recommended_local_profile"] is None
    assert "Pro" in r["pro_escalation_condition"]


def test_env_secret_blocked():
    r = call_route_explain({"task": "check this .env file for secret configuration"})
    assert r["ok"] is True
    assert r["privacy_status"] == "blocked"
    assert r["cloud_allowed"] is False
    assert r["flash_escalation_condition"] is None
    assert r["pro_escalation_condition"] is None


def test_diff_review():
    r = call_route_explain({"task": "review current diff before commit"})
    assert r["ok"] is True
    assert r["task_type"] == "review-diff"
    assert r["risk_level"] == "medium"
    assert r["recommended_local_profile"] == "diff_reviewer_llamacpp"
    assert r["flash_escalation_condition"] is not None


# ── Escalation context flags ──

def test_cloud_ok_enables_cloud():
    r = call_route_explain({"task": "review current diff", "cloud_ok": True})
    assert r["cloud_allowed"] is True


def test_local_failures_flash_escalation():
    r = call_route_explain({
        "task": "review current diff for bugs",
        "local_failures": 2,
        "cloud_ok": True,
    })
    assert r["escalate_to_flash"] is True


def test_local_failures_not_enough():
    r = call_route_explain({
        "task": "review current diff for bugs",
        "local_failures": 1,
        "cloud_ok": True,
    })
    assert r["escalate_to_flash"] is False


def test_high_risk_escalate_to_pro():
    r = call_route_explain({
        "task": "prepare release v2.3 for production deployment",
        "cloud_ok": True,
    })
    assert r["escalate_to_pro"] is True


# ── Output contract ──

def test_all_output_fields():
    r = call_route_explain({"task": "review current diff"})
    required = [
        "task_type", "risk_level", "privacy_status",
        "recommended_local_profile", "flash_escalation_condition",
        "pro_escalation_condition", "cloud_allowed", "reason",
    ]
    for field in required:
        assert field in r, f"Missing output field: {field}"


def test_advisory_only_always():
    r = call_route_explain({"task": "anything"})
    assert r["advisory_only"] is True


# ── Edge cases ──

def test_empty_task():
    r = call_route_explain({"task": ""})
    assert r["ok"] is False
    assert r["error_type"] == "invalid_input"


def test_missing_task():
    r = call_route_explain({})
    assert r["ok"] is False
    assert r["error_type"] == "invalid_input"


def test_unknown_task_still_ok():
    r = call_route_explain({"task": "xyzzy flurbo gronk"})
    assert r["ok"] is True
    assert r["task_type"] == "unknown"
    assert r["risk_level"] == "low"


def test_cli_json_parseable():
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/router_explain.py", "review current diff", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    data = json.loads(r.stdout.strip())
    assert "cloud_allowed" in data
    assert "task_type" in data


def test_cli_no_traceback():
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/router_explain.py", "review current diff", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert "Traceback" not in r.stdout


# ── Output stability ──

def test_would_block_absent_or_false():
    """route_explain output must not assert would_block=true."""
    tasks = [
        "review diff",
        "prepare release",
        "check .env",
        "unknown xyzzy",
    ]
    for task in tasks:
        r = call_route_explain({"task": task})
        assert "would_block" not in r or r.get("would_block") is not True, \
            f"would_block=true for: {task}"


def test_cli_text_output_no_traceback():
    """Text (non-JSON) output path also has no traceback."""
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/route_explain_mcp.py"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert "Traceback" not in r.stdout


def test_unknown_task_remains_low_risk():
    """Any unrecognized task defaults to unknown/low, never high."""
    gibberish_tasks = [
        "xyzzy flurbo gronk",
        "blargle snorf",
        "asdf qwer zxcv",
    ]
    for task in gibberish_tasks:
        r = call_route_explain({"task": task})
        assert r["task_type"] == "unknown", f"Expected unknown, got {r['task_type']} for: {task}"
        assert r["risk_level"] == "low", f"Expected low, got {r['risk_level']} for: {task}"


def test_json_output_stable_fields():
    """All calls return the same set of top-level keys."""
    r1 = call_route_explain({"task": "review diff"})
    r2 = call_route_explain({"task": "prepare release v0.13"})
    assert set(r1.keys()) == set(r2.keys()), \
        f"Field mismatch: {set(r1.keys())} vs {set(r2.keys())}"


# ── Malformed input ──

def test_missing_task_field_no_crash():
    """Missing 'task' key returns ok=false, not a traceback."""
    r = call_route_explain({})
    assert r["ok"] is False
    assert r["error_type"] == "invalid_input"
    assert "Traceback" not in str(r)


def test_empty_task_policy_stable():
    """Empty task string returns ok=false with invalid_input."""
    r = call_route_explain({"task": ""})
    assert r["ok"] is False
    assert r["error_type"] == "invalid_input"


def test_malformed_extra_fields_handled():
    """Extra/unexpected fields do not crash the call."""
    r = call_route_explain({
        "task": "review diff",
        "unexpected_field": 12345,
        "another_bogus": None,
    })
    assert r["ok"] is True
    assert r["task_type"] == "review-diff"


def test_cli_malformed_input_no_traceback():
    """CLI with malformed input does not produce traceback."""
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/router_explain.py", "review current diff", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert "Traceback" not in r.stderr


def test_advisory_only_true_on_malformed():
    """Even on malformed input, advisory_only remains true."""
    r1 = call_route_explain({})       # missing task
    r2 = call_route_explain({"task": ""})  # empty task
    assert r1.get("advisory_only") is True
    assert r2.get("advisory_only") is True
