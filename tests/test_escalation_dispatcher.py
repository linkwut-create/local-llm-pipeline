"""Tests for tools/escalation_dispatcher.py — route.json execution."""
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))


@pytest.fixture
def route_local_only(tmp_path):
    p = tmp_path / "route.json"
    p.write_text(json.dumps({
        "recommended_route": "local_only",
        "risk_level": "low",
        "local_preprocessing_required": False,
    }), encoding="utf-8")
    return p


@pytest.fixture
def route_flash_direct(tmp_path):
    p = tmp_path / "route.json"
    p.write_text(json.dumps({
        "recommended_route": "flash_direct",
        "risk_level": "medium",
        "local_preprocessing_required": False,
    }), encoding="utf-8")
    return p


@pytest.fixture
def route_blocked(tmp_path):
    p = tmp_path / "route.json"
    p.write_text(json.dumps({
        "recommended_route": "blocked",
        "risk_level": "critical",
        "local_preprocessing_required": False,
    }), encoding="utf-8")
    return p


@pytest.fixture
def route_ask_user(tmp_path):
    p = tmp_path / "route.json"
    p.write_text(json.dumps({
        "recommended_route": "ask_user",
        "risk_level": "medium",
        "local_preprocessing_required": False,
    }), encoding="utf-8")
    return p


# ── Short-circuit routes ──

def test_blocked_route_no_execution(route_blocked):
    import escalation_dispatcher as ed
    result = ed.dispatch(str(route_blocked), task="test")
    assert result.escalated is True
    assert "blocked" in result.escalation_reason
    assert len(result.phases) == 0


def test_ask_user_route_no_execution(route_ask_user):
    import escalation_dispatcher as ed
    result = ed.dispatch(str(route_ask_user), task="test")
    assert result.escalated is True
    assert "human" in result.escalation_reason


def test_route_file_not_found():
    import escalation_dispatcher as ed
    result = ed.dispatch("nonexistent.json", task="test")
    assert result.task == "test"


# ── Local execution ──

def test_local_execution_success(route_local_only, monkeypatch):
    import escalation_dispatcher as ed

    def _mock_local(task, profile="fast_summary"):
        return True, "LOCAL-OUTPUT", 42

    monkeypatch.setattr(ed, "_run_local", _mock_local)
    result = ed.dispatch(str(route_local_only), task="summarize")
    assert len(result.phases) == 1
    assert result.phases[0].success is True
    assert "LOCAL-OUTPUT" in result.phases[0].output
    assert result.total_cost == 0.0


def test_local_execution_failure(route_local_only, monkeypatch):
    import escalation_dispatcher as ed

    def _mock_local(task, profile="fast_summary"):
        return False, "model unavailable", 0

    monkeypatch.setattr(ed, "_run_local", _mock_local)
    result = ed.dispatch(str(route_local_only), task="summarize")
    assert result.phases[0].success is False


# ── Cloud execution ──

def test_flash_direct_cloud_call(route_flash_direct, monkeypatch):
    import escalation_dispatcher as ed

    def _mock_cloud(task, model, max_tokens=1024):
        return True, "FLASH-OUTPUT", 150, 0.00005

    monkeypatch.setattr(ed, "_run_cloud", _mock_cloud)
    result = ed.dispatch(str(route_flash_direct), task="test",
                         cloud_ok=True)
    assert len(result.phases) == 1
    assert result.phases[0].success is True
    assert "FLASH-OUTPUT" in result.phases[0].output
    assert result.total_cost == 0.00005


def test_flash_direct_without_cloud_ok(route_flash_direct, monkeypatch):
    import escalation_dispatcher as ed
    result = ed.dispatch(str(route_flash_direct), task="test",
                         cloud_ok=False)
    assert result.phases[0].success is False
    assert "cloud_ok" in result.phases[0].output.lower()


def test_flash_failure_escalates_to_pro(route_flash_direct, monkeypatch):
    import escalation_dispatcher as ed

    call_count = [0]

    def _mock_cloud(task, model, max_tokens=1024):
        call_count[0] += 1
        if call_count[0] == 1:
            return False, "Flash timeout", 0, 0.0
        else:
            return True, "PRO-FALLBACK", 200, 0.001

    monkeypatch.setattr(ed, "_run_cloud", _mock_cloud)
    result = ed.dispatch(str(route_flash_direct), task="test",
                         cloud_ok=True)
    assert result.escalated is True
    assert "Flash failed" in result.escalation_reason
    assert len(result.phases) >= 2  # original + fallback
    pro_phase = [p for p in result.phases if p.phase == "pro_fallback"]
    assert len(pro_phase) == 1
    assert pro_phase[0].success is True


# ── Budget enforcement ──

def test_budget_hard_stop(route_flash_direct, monkeypatch):
    import escalation_dispatcher as ed

    def _mock_cloud(task, model, max_tokens=1024):
        return True, "output", 1000, 10.0  # costs more than budget

    monkeypatch.setattr(ed, "_run_cloud", _mock_cloud)
    result = ed.dispatch(str(route_flash_direct), task="test",
                         cloud_ok=True, max_budget=1.0)
    assert result.escalated is True
    assert "budget" in result.escalation_reason.lower()


# ── Local preprocessing ──

def test_local_preprocess_before_cloud(tmp_path, monkeypatch):
    import escalation_dispatcher as ed

    route = tmp_path / "route.json"
    route.write_text(json.dumps({
        "recommended_route": "flash_subagent",
        "risk_level": "medium",
        "local_preprocessing_required": True,
    }), encoding="utf-8")

    def _mock_local(task, profile="fast_summary"):
        return True, "LOCAL-PREP", 30

    def _mock_cloud(task, model, max_tokens=1024):
        return True, "CLOUD-MAIN", 200, 0.001

    monkeypatch.setattr(ed, "_run_local", _mock_local)
    monkeypatch.setattr(ed, "_run_cloud", _mock_cloud)
    result = ed.dispatch(str(route), task="test", cloud_ok=True)
    assert len(result.phases) == 2
    assert result.phases[0].phase == "local_preprocess"
    assert result.phases[1].phase == "main"


# ── CLI ──

def test_cli_requires_route():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "escalation_dispatcher.py")],
        capture_output=True, text=True,
        cwd=str(TOOLS_DIR.parent),
    )
    assert r.returncode != 0


def test_cli_json_output(tmp_path):
    route = tmp_path / "r.json"
    route.write_text(json.dumps({
        "recommended_route": "local_only",
        "risk_level": "low",
    }), encoding="utf-8")

    import subprocess, escalation_dispatcher as ed

    # Monkeypatch _run_local to avoid real Ollama calls
    import escalation_dispatcher
    orig = escalation_dispatcher._run_local
    escalation_dispatcher._run_local = lambda t, p="": (True, "ok", 10)

    r = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "escalation_dispatcher.py"),
         "--route", str(route), "--task", "test", "--json"],
        capture_output=True, text=True,
        cwd=str(TOOLS_DIR.parent),
    )
    escalation_dispatcher._run_local = orig

    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert "phases" in data
    assert data["total_cost"] == 0.0


# ── Pro execution ──

def test_pro_decision_cloud_call(tmp_path, monkeypatch):
    import escalation_dispatcher as ed

    route = tmp_path / "route.json"
    route.write_text(json.dumps({
        "recommended_route": "pro_decision",
        "risk_level": "high",
    }), encoding="utf-8")

    def _mock_cloud(task, model, max_tokens=1024):
        return True, "PRO-OUTPUT", 300, 0.005

    monkeypatch.setattr(ed, "_run_cloud", _mock_cloud)
    result = ed.dispatch(str(route), task="security audit", cloud_ok=True)
    assert result.phases[0].success is True
    assert "PRO-OUTPUT" in result.phases[0].output
