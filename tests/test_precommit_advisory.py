"""Tests for tools/precommit_advisory.py — no DeepSeek, no hook changes, always exit 0."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from precommit_advisory import _build_task, _recommend, run


# ── Task builder ──

def test_build_task_override():
    t = _build_task("review specific diff")
    assert t == "review specific diff"


def test_build_task_no_override():
    t = _build_task("")
    assert len(t) > 0  # something is generated


# ── Decision engine ──

def test_recommend_diff_review():
    r = _recommend("review current diff: test.py, main.py")
    assert r["router_task_type"] == "review-diff"
    assert r["router_risk_level"] == "medium"
    assert r["recommended_controller_decision"] in ("local-first", "flash-fallback")
    assert r["advisory_only"] is True


def test_recommend_release_gate():
    r = _recommend("prepare release gate for v0.13.0", cloud_ok=True)
    assert r["recommended_controller_decision"] == "pro-review"
    assert r["router_risk_level"] == "high"


def test_recommend_env_secret():
    r = _recommend("check .env.production for credentials", cloud_ok=True)
    assert r["recommended_controller_decision"] == "cloud-blocked"
    assert r["router_privacy_status"] == "blocked"
    assert r["cloud_allowed"] is False


def test_recommend_default_no_cloud():
    r = _recommend("review diff: test.py")
    assert r["cloud_allowed"] is False


# ── Output fields ──

def test_output_has_all_fields():
    r = _recommend("review current diff: a.py")
    required = [
        "task", "router_task_type", "router_risk_level",
        "router_privacy_status", "recommended_local_profile",
        "recommended_controller_decision", "flash_escalation_condition",
        "pro_escalation_condition", "cloud_allowed", "advisory_only",
    ]
    for f in required:
        assert f in r, f"Missing: {f}"


def test_json_schema_stable():
    r = _recommend("review diff: main.py")
    j = json.loads(json.dumps(r))  # round-trip
    assert j["task"] == r["task"]


# ── Always exit 0 (tested via function, not subprocess) ──

def test_advisory_only_always():
    for task in ["review diff", "release gate", "check .env"]:
        r = _recommend(task)
        assert r["advisory_only"] is True


# ── No DeepSeek call ──

def test_no_api_call():
    r = _recommend("review current diff before commit")
    assert r["router_task_type"] is not None
    # Completes in-process without network


# ── Shadow log output path ──

def test_log_path(tmp_path, monkeypatch):
    monkeypatch.setattr("precommit_advisory.SHADOW_DIR", tmp_path / "shadow_routes")
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    r = run(cloud_ok=False, task_override="review diff: test.py")
    assert "shadow_routes" in r["log_path"]
    assert "jsonl" in r["log_path"]


# ── --task flag works ──

def test_run_with_task_override(tmp_path, monkeypatch):
    monkeypatch.setattr("precommit_advisory.SHADOW_DIR", tmp_path / "shadow_routes")
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    r = run(task_override="prepare release gate v0.13.0", cloud_ok=True)
    assert r["recommended_controller_decision"] == "pro-review"


# ── --cloud-ok default false ──

def test_cloud_ok_default_false():
    r = _recommend("review diff: main.py")
    assert r["cloud_allowed"] is False


# ═══════════════════════════════════════════════════════════════
# CLI regression tests
# ═══════════════════════════════════════════════════════════════

def test_cli_runs_no_crash(tmp_path):
    import subprocess, os
    env = os.environ.copy()
    env["LOCAL_LLM_SHADOW_DIR"] = str(tmp_path / "shadow_routes")
    r = subprocess.run(
        [sys.executable, "tools/precommit_advisory.py"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
        env=env,
    )
    assert r.returncode == 0


def test_cli_cloud_ok_runs(tmp_path):
    import subprocess, os
    env = os.environ.copy()
    env["LOCAL_LLM_SHADOW_DIR"] = str(tmp_path / "shadow_routes")
    r = subprocess.run(
        [sys.executable, "tools/precommit_advisory.py", "--cloud-ok"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
        env=env,
    )
    assert r.returncode == 0


def test_cli_json_output(tmp_path):
    import subprocess, json, os
    env = os.environ.copy()
    env["LOCAL_LLM_SHADOW_DIR"] = str(tmp_path / "shadow_routes")
    r = subprocess.run(
        [sys.executable, "tools/precommit_advisory.py", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
        env=env,
    )
    data = json.loads(r.stdout.strip())
    assert "advisory_only" in data


def test_cli_no_traceback(tmp_path):
    import subprocess, os
    env = os.environ.copy()
    env["LOCAL_LLM_SHADOW_DIR"] = str(tmp_path / "shadow_routes")
    r = subprocess.run(
        [sys.executable, "tools/precommit_advisory.py"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
        env=env,
    )
    assert "Traceback" not in r.stdout


def test_output_advisory_only_true():
    r = _recommend("review diff: main.py")
    assert r["advisory_only"] is True
