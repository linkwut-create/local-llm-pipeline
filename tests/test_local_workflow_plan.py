"""Tests for tools/local_workflow_plan.py — heuristic workflow planner."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_workflow_plan as wp


# ---------------------------------------------------------------------------
# classify_workflow_type
# ---------------------------------------------------------------------------

def test_classify_small_code_change():
    assert wp.classify_workflow_type(
        ["src/main.py", "tests/test_main.py"],
        "Fix login timeout bug",
    ) == "small-code-change"


def test_classify_docs_change():
    assert wp.classify_workflow_type(
        ["docs/guide.md", "CHANGELOG.md"],
        "Update documentation",
    ) == "docs-only-change"


def test_classify_docs_change_single_readme():
    assert wp.classify_workflow_type(
        ["README.md"],
        "Update readme",
    ) == "docs-only-change"


def test_classify_high_risk_router():
    assert wp.classify_workflow_type(
        ["tools/local_llm_router.py", "tests/test_router_profiles.py"],
        "Change router eligibility based on backend class",
    ) == "high-risk-runtime-change"


def test_classify_high_risk_mcp_server():
    assert wp.classify_workflow_type(
        ["tools/local_llm_mcp_server.py"],
        "Add new MCP tool",
    ) == "high-risk-runtime-change"


def test_classify_high_risk_hooks():
    assert wp.classify_workflow_type(
        ["tools/claude_hooks/mcp_auto_worker.py"],
        "Fix hook trigger",
    ) == "high-risk-runtime-change"


def test_classify_high_risk_debate():
    assert wp.classify_workflow_type(
        ["tools/local_llm_debate.py"],
        "Change debate round logic",
    ) == "high-risk-runtime-change"


def test_classify_high_risk_call_ledger():
    assert wp.classify_workflow_type(
        ["tools/call_ledger.py"],
        "Add new field to call ledger",
    ) == "high-risk-runtime-change"


def test_classify_release_checkpoint():
    assert wp.classify_workflow_type(
        ["CHANGELOG.md", "PROJECT_STATUS.md", "RELEASE_NOTES.md"],
        "Release v0.13.0 checkpoint",
    ) == "release-local-checkpoint"


def test_classify_release_by_task_keyword_only():
    assert wp.classify_workflow_type(
        [],
        "version bump to 0.14.0",
    ) == "release-local-checkpoint"


def test_classify_unknown_empty():
    assert wp.classify_workflow_type([], "") == "unknown"


# ---------------------------------------------------------------------------
# classify_risk_level
# ---------------------------------------------------------------------------

def test_risk_low_for_docs():
    assert wp.classify_risk_level("docs-only-change") == "low"


def test_risk_medium_for_small_code():
    assert wp.classify_risk_level("small-code-change") == "medium"


def test_risk_high_for_high_risk():
    assert wp.classify_risk_level("high-risk-runtime-change") == "high"


def test_risk_medium_for_release():
    assert wp.classify_risk_level("release-local-checkpoint") == "medium"


# ---------------------------------------------------------------------------
# classify_debate_required
# ---------------------------------------------------------------------------

def test_debate_skipped_for_docs():
    required, reason = wp.classify_debate_required("docs-only-change",
                                                    ["docs/guide.md"])
    assert required is False
    assert "docs-only" in reason.lower()


def test_debate_required_for_high_risk():
    required, reason = wp.classify_debate_required(
        "high-risk-runtime-change",
        ["tools/local_llm_router.py"],
    )
    assert required is True


def test_debate_required_for_hooks():
    required, reason = wp.classify_debate_required(
        "small-code-change",
        ["tools/claude_hooks/mcp_auto_worker.py"],
    )
    assert required is True


def test_debate_skipped_for_small_code_no_triggers():
    required, reason = wp.classify_debate_required(
        "small-code-change",
        ["src/main.py", "tests/test_main.py"],
    )
    assert required is False


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------

def test_plan_small_code_contains_stages():
    plan = wp.build_plan(["src/main.py"], "Fix bug")
    assert plan["workflow_type"] == "small-code-change"
    assert plan["risk_level"] == "medium"
    assert plan["debate_required"] is False
    assert "orient" in plan["phases"]
    assert "review" in plan["phases"]
    assert "commit" in plan["phases"]


def test_plan_docs_has_no_debate():
    plan = wp.build_plan(["docs/guide.md"], "Update docs")
    assert plan["workflow_type"] == "docs-only-change"
    assert plan["debate_required"] is False
    assert "review-diff" in str(plan["phases"]["review"]["commands"])


def test_plan_high_risk_has_debate():
    plan = wp.build_plan(["tools/local_llm_router.py"],
                         "Change router logic")
    assert plan["workflow_type"] == "high-risk-runtime-change"
    assert plan["debate_required"] is True
    review_cmds = " ".join(plan["phases"]["review"]["commands"])
    assert "debate" in review_cmds.lower()


def test_plan_release_has_changelog():
    plan = wp.build_plan(["CHANGELOG.md"], "Release checkpoint")
    assert plan["workflow_type"] == "release-local-checkpoint"
    batch_cmds = " ".join(plan["phases"]["batch_release"]["commands"])
    assert "draft-changelog-entry" in batch_cmds
    assert "draft-pr-summary" in batch_cmds


def test_plan_review_phase_includes_commit_gate_hint():
    plan = wp.build_plan(["src/main.py"], "Fix bug")
    review_cmds = " ".join(plan["phases"]["review"]["commands"])
    assert "review-diff" in review_cmds
    assert "commit_gate" in review_cmds


def test_plan_controller_must_decide():
    plan = wp.build_plan(["src/main.py"], "Fix bug")
    decisions = plan["controller_must_decide"]
    assert any("edit" in d.lower() for d in decisions)
    assert any("accept" in d.lower() or "reject" in d.lower() for d in decisions)
    assert any("commit" in d.lower() for d in decisions)


def test_plan_has_estimated_cost():
    plan = wp.build_plan(["src/main.py"], "Fix bug")
    assert isinstance(plan["estimated_cost_seconds"], int)
    assert plan["estimated_cost_seconds"] >= 0


def test_plan_advisory_only_flag():
    plan = wp.build_plan([], "")
    assert plan["advisory_only"] is True


def test_plan_empty_returns_unknown():
    plan = wp.build_plan([], "")
    assert plan["workflow_type"] == "unknown"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_cli_no_args_returns_help_code():
    """No args → exit code 2 (insufficient input)."""
    rc = wp.main([])
    assert rc == 2


def test_cli_task_only_ok():
    """Task-only input is valid (no files needed for classification)."""
    rc = wp.main(["--task", "test only"])
    assert rc == 0


def test_cli_task_and_files(monkeypatch, capsys):
    """Task + files produces valid output."""
    monkeypatch.setattr(wp, "gather_input",
                        lambda args: ("Fix bug", ["src/main.py"]))
    rc = wp.main(["--task", "Fix bug", "--stdin"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Small Code Change" in captured


def test_cli_json_format(monkeypatch, capsys):
    """JSON output contains expected keys."""
    monkeypatch.setattr(wp, "gather_input",
                        lambda args: ("Fix bug", ["src/main.py", "tests/test_main.py"]))
    rc = wp.main(["--task", "Fix bug", "--format", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "workflow_type" in data
    assert "risk_level" in data
    assert "phases" in data


# ---------------------------------------------------------------------------
# is_docs_path / is_high_risk_path
# ---------------------------------------------------------------------------

def test_is_docs_path_positive():
    assert wp._is_docs_path("docs/guide.md") is True
    assert wp._is_docs_path("README.md") is True
    assert wp._is_docs_path("CHANGELOG.md") is True
    assert wp._is_docs_path("CLAUDE.md") is True
    assert wp._is_docs_path("PROJECT_STATUS.md") is True
    assert wp._is_docs_path("LICENSE") is True


def test_is_docs_path_negative():
    assert wp._is_docs_path("src/main.py") is False
    assert wp._is_docs_path("tools/router.py") is False
    assert wp._is_docs_path("tests/test_main.py") is False


def test_is_high_risk_path_positive():
    assert wp._is_high_risk_path("tools/local_llm_router.py") is True
    assert wp._is_high_risk_path("tools/local_llm_mcp_server.py") is True
    assert wp._is_high_risk_path("tools/claude_hooks/mcp_auto_worker.py") is True
    assert wp._is_high_risk_path("tools/call_ledger.py") is True


def test_is_high_risk_path_negative():
    assert wp._is_high_risk_path("src/main.py") is False
    assert wp._is_high_risk_path("tests/test_main.py") is False
    assert wp._is_high_risk_path("docs/guide.md") is False
