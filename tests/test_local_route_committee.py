"""Tests for tools/local_route_committee.py CLI."""
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
CLAUDE_HOOKS_DIR = TOOLS_DIR / "claude_hooks"
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(CLAUDE_HOOKS_DIR))


def test_output_flag_writes_route_json(monkeypatch, tmp_path):
    import local_route_committee as committee

    route_file = tmp_path / "route.json"

    fake_decision = committee.RouteDecision(
        delegability="medium",
        recommended_route="flash_subagent",
        local_preprocessing_required=False,
        pro_should_execute=False,
        pro_should_adjudicate=False,
        risk_level="medium",
        privacy_status="safe",
        reason="safe to run locally",
        required_artifacts=[],
        qwen_judgement={},
        gemma_judgement={},
        agreement=True,
        escalated=False,
        escalated_reason="",
    )

    monkeypatch.setattr(committee, "convene", lambda **kwargs: fake_decision)
    monkeypatch.setattr(committee, "build_evidence_pack", lambda: "")

    original_argv = sys.argv
    try:
        sys.argv = [
            "local_route_committee.py",
            "fix null pointer",
            "--plan", str(tmp_path / "plan.json"),
            "--json",
            "--output", str(route_file),
        ]
        (tmp_path / "plan.json").write_text(json.dumps({"task": "fix"}), encoding="utf-8")
        assert committee.main() == 0
    finally:
        sys.argv = original_argv

    assert route_file.exists()
    data = json.loads(route_file.read_text(encoding="utf-8"))
    assert data["recommended_route"] == "flash_subagent"
    assert "Write" in data["_enforcement"]["allowed"]
    assert "Edit" in data["_enforcement"]["allowed"]
    assert data["_enforcement"]["cloud_ok"] is True


def test_output_without_json_still_writes_file(monkeypatch, tmp_path):
    import local_route_committee as committee

    route_file = tmp_path / "route.json"

    fake_decision = committee.RouteDecision(
        delegability="low",
        recommended_route="local_only",
        local_preprocessing_required=True,
        pro_should_execute=False,
        pro_should_adjudicate=False,
        risk_level="low",
        privacy_status="safe",
        reason="read only",
        required_artifacts=[],
        qwen_judgement={},
        gemma_judgement={},
        agreement=True,
        escalated=False,
        escalated_reason="",
    )

    monkeypatch.setattr(committee, "convene", lambda **kwargs: fake_decision)
    monkeypatch.setattr(committee, "build_evidence_pack", lambda: "")

    original_argv = sys.argv
    try:
        sys.argv = [
            "local_route_committee.py",
            "summarize file",
            "--plan", str(tmp_path / "plan.json"),
            "--output", str(route_file),
        ]
        (tmp_path / "plan.json").write_text(json.dumps({"task": "summarize"}), encoding="utf-8")
        assert committee.main() == 0
    finally:
        sys.argv = original_argv

    assert route_file.exists()
    data = json.loads(route_file.read_text(encoding="utf-8"))
    assert data["recommended_route"] == "local_only"
