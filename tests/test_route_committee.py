"""Tests for tools/local_route_committee.py — merge logic + evidence pack."""
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))


# ── Evidence pack ──

def test_build_evidence_pack_returns_all_keys():
    from local_route_committee import build_evidence_pack
    pack = build_evidence_pack()
    for key in ("git_status", "file_tree", "current_diff", "test_status",
                "privacy_scan", "project_phase", "recent_commits"):
        assert key in pack, f"Missing key: {key}"


def test_format_evidence_pack_is_compact():
    from local_route_committee import build_evidence_pack, format_evidence_pack
    pack = build_evidence_pack()
    text = format_evidence_pack(pack)
    # Should be under 1000 words
    assert len(text.split()) < 1000


# ── Route Judgement ──

def test_route_judgement_to_dict():
    from local_route_committee import RouteJudgement
    j = RouteJudgement(
        delegability="high",
        recommended_route="flash_subagent",
        local_preprocessing_required=True,
        pro_should_execute=False,
        pro_should_adjudicate=False,
        risk_level="medium",
        privacy_status="safe",
        reason="good task for flash",
        required_artifacts=["diff", "test_log"],
        model="qwen3.6:27b",
        confidence=0.85,
    )
    d = j.to_dict()
    assert d["delegability"] == "high"
    assert d["recommended_route"] == "flash_subagent"
    assert d["required_artifacts"] == ["diff", "test_log"]


# ── Merge logic ──

def _make_j(route="flash_subagent", risk="medium", privacy="safe",
            delegability="high", preprocess=True, execute=False, adjudicate=False,
            artifacts=None):
    from local_route_committee import RouteJudgement
    return RouteJudgement(
        delegability=delegability, recommended_route=route,
        local_preprocessing_required=preprocess,
        pro_should_execute=execute, pro_should_adjudicate=adjudicate,
        risk_level=risk, privacy_status=privacy, reason="test",
        required_artifacts=artifacts or [], model="test", confidence=0.8,
    )


def test_merge_blocked_wins():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_subagent")
    gemma = _make_j("blocked", risk="critical")
    result = merge_judgements(qwen, gemma)
    assert result.recommended_route == "blocked"
    assert result.escalated is True


def test_merge_high_risk_escalates():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_subagent")
    gemma = _make_j("flash_subagent", risk="high")
    result = merge_judgements(qwen, gemma)
    assert result.recommended_route == "pro_decision"
    assert result.escalated is True


def test_merge_both_agree_flash():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_subagent")
    gemma = _make_j("flash_subagent")
    result = merge_judgements(qwen, gemma)
    assert result.recommended_route == "flash_subagent"
    assert result.agreement is True
    assert result.escalated is False


def test_merge_both_agree_local():
    from local_route_committee import merge_judgements
    qwen = _make_j("local_only")
    gemma = _make_j("local_only")
    result = merge_judgements(qwen, gemma)
    assert result.recommended_route == "local_only"
    assert result.agreement is True


def test_merge_both_agree_ask_user():
    from local_route_committee import merge_judgements
    qwen = _make_j("ask_user", delegability="low")
    gemma = _make_j("ask_user", delegability="low")
    result = merge_judgements(qwen, gemma)
    assert result.recommended_route == "ask_user"
    assert result.agreement is True


def test_merge_disagreement_escalates():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_subagent")
    gemma = _make_j("pro_decision", risk="high")
    result = merge_judgements(qwen, gemma)
    # high risk from gemma → pro_decision (Rule 2 fires first)
    assert result.recommended_route == "pro_decision"


def test_merge_flash_direct_and_local():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_direct")
    gemma = _make_j("local_only")
    result = merge_judgements(qwen, gemma)
    assert result.recommended_route == "flash_direct"  # prefer flash
    assert result.agreement is True


def test_merge_privacy_blocked():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_subagent", privacy="blocked")
    gemma = _make_j("local_only")
    result = merge_judgements(qwen, gemma)
    # blocked privacy from one model → blocked in merged result
    assert result.privacy_status == "blocked"


# ── ROUTE_PERMISSIONS ──

def test_all_routes_have_permissions():
    from local_route_committee import ROUTE_PERMISSIONS
    expected = {"local_only", "flash_direct", "flash_subagent",
                "pro_decision", "blocked", "ask_user"}
    assert set(ROUTE_PERMISSIONS.keys()) == expected


# ── Single model decision ──

def test_single_model_decision():
    from local_route_committee import _single_model_decision, RouteJudgement
    j = RouteJudgement(
        delegability="high", recommended_route="flash_subagent",
        local_preprocessing_required=True, pro_should_execute=False,
        pro_should_adjudicate=False, risk_level="medium",
        privacy_status="safe", reason="works", required_artifacts=["test"],
        model="qwen3.6:27b", confidence=0.8,
    )
    result = _single_model_decision(j)
    assert result.recommended_route == "flash_subagent"
    assert result.agreement is True


def test_merge_required_artifacts_are_stable_and_deduplicated():
    from local_route_committee import merge_judgements
    qwen = _make_j("flash_direct", artifacts=["diff", "summary"])
    gemma = _make_j("local_only", artifacts=["summary", "test_log"])
    result = merge_judgements(qwen, gemma)
    assert result.required_artifacts == ["diff", "summary", "test_log"]


def test_build_route_output_validates():
    from local_route_committee import (
        RouteDecision,
        build_route_output,
        validate_route_output,
    )
    decision = RouteDecision(
        delegability="high",
        recommended_route="flash_direct",
        local_preprocessing_required=True,
        pro_should_execute=False,
        pro_should_adjudicate=False,
        risk_level="low",
        privacy_status="safe",
        reason="ok",
        required_artifacts=["summary"],
        qwen_judgement={},
        gemma_judgement={},
        agreement=True,
        escalated=False,
        escalated_reason="",
    )
    output = build_route_output(decision)
    assert validate_route_output(output) == []
    assert output["_enforcement"]["allowed"] == sorted(output["_enforcement"]["allowed"])


def test_validate_route_output_rejects_invalid_route():
    from local_route_committee import validate_route_output
    errors = validate_route_output({
        "delegability": "high",
        "recommended_route": "invalid",
        "local_preprocessing_required": True,
        "pro_should_execute": False,
        "pro_should_adjudicate": False,
        "risk_level": "low",
        "privacy_status": "safe",
        "reason": "bad route",
        "required_artifacts": [],
        "qwen_judgement": {},
        "gemma_judgement": {},
        "agreement": True,
        "escalated": False,
        "escalated_reason": "",
        "pro_audit_requested": False,
        "_enforcement": {
            "allowed": ["Read"],
            "denied": [],
            "cloud_ok": False,
            "pro_audit_requested": False,
        },
    })
    assert "invalid recommended_route: 'invalid'" in errors
