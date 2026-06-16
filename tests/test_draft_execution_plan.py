"""Tests for tools/draft_execution_plan.py — execution plan generation."""
import importlib
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

dep = importlib.import_module("draft_execution_plan")


# ── Template selection ──

def test_select_template_default():
    t = dep._select_template("do something random and unusual")
    assert t == "default"


def test_select_template_feature():
    assert dep._select_template("implement user authentication") == "feature"
    assert dep._select_template("add new API endpoint for payments") == "feature"
    assert dep._select_template("build a notification service") == "feature"


def test_select_template_bug_fix():
    assert dep._select_template("fix null pointer crash in handler") == "bug-fix"
    assert dep._select_template("patch the login vulnerability") == "bug-fix"
    assert dep._select_template("hotfix production outage") == "bug-fix"


def test_select_template_refactor():
    assert dep._select_template("refactor database layer") == "refactor"
    assert dep._select_template("restructure the module hierarchy") == "refactor"
    assert dep._select_template("clean up unused imports") == "refactor"


def test_select_template_docs():
    assert dep._select_template("update README with examples") == "docs"
    assert dep._select_template("write API documentation") == "docs"


def test_select_template_release():
    assert dep._select_template("release v0.13.0") == "release"
    assert dep._select_template("version bump to 1.0.0") == "release"


# ── Phase task types ──

def test_phase_task_type_mapping():
    assert dep.PHASE_TASK_TYPE["understand"] == "summarize-file"
    assert dep.PHASE_TASK_TYPE["plan"] == "architecture-review"
    assert dep.PHASE_TASK_TYPE["implement"] == "draft-feature"
    assert dep.PHASE_TASK_TYPE["test"] == "generate-test-plan"
    assert dep.PHASE_TASK_TYPE["review"] == "review-diff"
    assert dep.PHASE_TASK_TYPE["release"] == "release-risk-review"


# ── Plan generation ──

def test_plan_has_correct_structure():
    plan = dep.draft_execution_plan("add user authentication")
    assert plan.task == "add user authentication"
    assert len(plan.phases) >= 3
    assert plan.advisory_only is True

    d = plan.to_dict()
    assert "task" in d
    assert "phases" in d
    assert "total_estimated_cost_cny" in d
    for p in d["phases"]:
        assert "index" in p
        assert "name" in p
        assert "recommended_model" in p
        assert "execution_route" in p
        assert "cost_tier" in p


def test_plan_phases_are_sequential():
    plan = dep.draft_execution_plan("fix memory leak in parser")
    indices = [p.index for p in plan.phases]
    assert indices == list(range(1, len(plan.phases) + 1))


def test_plan_model_names_not_hardcoded(monkeypatch):
    """Model names should come from profiles, not be hardcoded. If profiles
    are unavailable, fallback to sensible defaults."""
    plan = dep.draft_execution_plan("write documentation for API")
    for p in plan.phases:
        # Model names must never be the internal concept strings
        assert p.recommended_model != "flash", \
            f"Phase {p.name}: model is concept 'flash', not resolved name"
        assert p.recommended_model != "pro", \
            f"Phase {p.name}: model is concept 'pro', not resolved name"
        # Must be a string with at least some content
        assert len(p.recommended_model) > 2, \
            f"Phase {p.name}: model name too short: {p.recommended_model}"


def test_plan_cost_is_reasonable():
    plan = dep.draft_execution_plan("simple thing")
    assert plan.total_estimated_cost_cny >= 0.0
    assert plan.total_estimated_cost_cny < 100.0, \
        f"Cost too high for a 4-phase plan: {plan.total_estimated_cost_cny}"


def test_feature_plan_has_5_phases():
    plan = dep.draft_execution_plan("implement a real-time notification system")
    assert len(plan.phases) == 5  # understand, plan, implement, test, review


def test_bugfix_plan_has_4_phases():
    plan = dep.draft_execution_plan("fix crash in database connection pool")
    assert len(plan.phases) == 4  # understand, implement, test, review


def test_docs_plan_has_3_phases():
    plan = dep.draft_execution_plan("update changelog with release notes")
    assert len(plan.phases) == 3  # understand, implement, review


def test_release_plan_has_4_phases():
    plan = dep.draft_execution_plan("release v1.0.0")
    assert len(plan.phases) == 4  # understand, review, test, release


# ── Real-run mode ──

def test_real_run_returns_not_implemented():
    plan = dep.draft_execution_plan(
        "anything", cloud_ok=True, real_run=True)
    assert plan.planner_model == "deepseek-v4-pro"
    assert len(plan.phases) == 1
    assert "not_implemented" in plan.phases[0].name


def test_real_run_without_cloud_ok_uses_heuristic():
    """real_run without cloud_ok should fall back to heuristic."""
    plan = dep.draft_execution_plan(
        "fix a bug", cloud_ok=False, real_run=True)
    assert len(plan.phases) >= 3  # heuristic mode


# ── JSON serialization ──

def test_to_dict_is_json_serializable():
    plan = dep.draft_execution_plan("add search feature to API")
    d = plan.to_dict()
    json_str = json.dumps(d, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["task"] == "add search feature to API"


# ── CLI ──

def test_cli_json_output():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "draft_execution_plan.py"),
         "fix bug in parser", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(TOOLS_DIR.parent),
    )
    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert "task" in data
    assert len(data["phases"]) >= 3


def test_cli_task_with_spaces():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "draft_execution_plan.py"),
         "add", "user", "authentication", "feature", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(TOOLS_DIR.parent),
    )
    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert "authentication" in data["task"]


# ── Cost estimation ──

def test_local_only_is_free():
    assert dep._estimate_phase_cost("local_only", 5000) == 0.0


def test_blocked_is_free():
    assert dep._estimate_phase_cost("blocked", 5000) == 0.0


def test_pro_is_most_expensive():
    pro_cost = dep._estimate_phase_cost("claude_code_pro", 5000)
    flash_cost = dep._estimate_phase_cost("flash_subagent", 5000)
    direct_cost = dep._estimate_phase_cost("flash_direct", 5000)
    assert pro_cost > flash_cost > direct_cost
