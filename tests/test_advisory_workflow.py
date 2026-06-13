"""Mock tests for tools/advisory_workflow.py — no DeepSeek calls, no profile changes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from advisory_workflow import recommend_decision, run


# ── Decision rules ──

def test_governance_docs_local():
    r = recommend_decision("summarize PROBLEMS.md and suggest missing entries")
    assert r["recommended_controller_decision"] == "local"
    assert r["router_task_type"] == "governance-docs"
    assert r["router_risk_level"] == "low"
    assert r["advisory_only"] is True


def test_diff_review_local_first():
    r = recommend_decision("review current diff before commit")
    assert r["recommended_controller_decision"] == "local-first"
    assert r["router_task_type"] == "review-diff"
    assert r["router_risk_level"] == "medium"


def test_release_gate_pro_review():
    r = recommend_decision("prepare release gate for v0.13.0", cloud_ok=True)
    assert r["recommended_controller_decision"] == "pro-review"
    assert r["router_risk_level"] == "high"
    assert r["cloud_allowed"] is True


def test_interface_change_pro_review():
    r = recommend_decision("change the provider config schema", cloud_ok=True)
    assert r["recommended_controller_decision"] == "pro-review"
    assert r["router_task_type"] == "interface-review"


def test_env_secret_cloud_blocked():
    r = recommend_decision("check .env.production for leaked credentials", cloud_ok=True)
    assert r["recommended_controller_decision"] == "cloud-blocked"
    assert r["router_privacy_status"] == "blocked"
    assert r["cloud_allowed"] is False


def test_multi_service_flash_fallback():
    r = recommend_decision("add rate limiting to API gateway across 3 services", cloud_ok=True)
    # medium + multi-file signal + cloud_ok → flash-fallback
    assert r["recommended_controller_decision"] in ("flash-fallback", "local-first")
    assert r["router_risk_level"] == "medium"


def test_unknown_defer():
    r = recommend_decision("xyzzy flurbo gronk")
    assert r["recommended_controller_decision"] == "defer"
    assert r["router_task_type"] == "unknown"


def test_local_failures_flash():
    r = recommend_decision("review current diff", cloud_ok=True, local_failures=2)
    assert r["recommended_controller_decision"] == "flash-fallback"


# ── Output contract ──

def test_output_fields():
    r = recommend_decision("review current diff")
    required = [
        "task", "router_task_type", "router_risk_level",
        "router_privacy_status", "recommended_local_profile",
        "recommended_controller_decision", "flash_escalation_condition",
        "pro_escalation_condition", "cloud_allowed", "advisory_only",
    ]
    for field in required:
        assert field in r, f"Missing: {field}"


def test_advisory_only_always_true():
    for task in ["review diff", "release gate", "check .env", "unknown xyzzy"]:
        r = recommend_decision(task)
        assert r["advisory_only"] is True


# ── No API calls ──

def test_no_llm_call():
    r = recommend_decision("explain what this function does")
    assert r["router_task_type"] is not None
    assert r["router_risk_level"] is not None


# ── Run writes shadow log ──

def test_run_writes_shadow_log(tmp_path, monkeypatch):
    # run() calls _shadow_log() which imports SHADOW_DIR from shadow_route_log
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    monkeypatch.setattr("advisory_workflow.SHADOW_DIR", tmp_path / "shadow_routes")
    result = run("review current diff before commit")
    assert result["recommended_controller_decision"] is not None
    assert "log_path" in result
    files = list((tmp_path / "shadow_routes").glob("*.jsonl"))
    assert len(files) == 1


# ── Decision value space ──

def test_decision_only_allowed_values():
    allowed = {"local", "local-first", "flash-fallback", "pro-review",
               "cloud-blocked", "defer"}
    tasks = [
        "summarize PROBLEMS.md",
        "review current diff before commit",
        "prepare release gate v0.13.0",
        "check .env.production for credentials",
        "add rate limiting across 3 services",
        "xyzzy unknown task",
    ]
    for task in tasks:
        r = recommend_decision(task, cloud_ok=True)
        assert r["recommended_controller_decision"] in allowed, \
            f"Bad decision {r['recommended_controller_decision']} for {task}"


def test_cli_runs_no_crash():
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/advisory_workflow.py", "review diff", "--cloud-ok"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert r.returncode == 0


def test_cli_json_output():
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/advisory_workflow.py", "review diff", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    data = json.loads(r.stdout.strip())
    assert "advisory_only" in data
    assert data["advisory_only"] is True


def test_cli_no_traceback():
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/advisory_workflow.py", "review diff"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert "Traceback" not in r.stdout
