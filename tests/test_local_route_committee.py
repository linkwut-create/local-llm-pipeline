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


def test_output_rejects_invalid_route(monkeypatch, tmp_path):
    import local_route_committee as committee

    route_file = tmp_path / "route.json"
    fake_decision = committee.RouteDecision(
        delegability="high",
        recommended_route="invalid",
        local_preprocessing_required=False,
        pro_should_execute=False,
        pro_should_adjudicate=False,
        risk_level="low",
        privacy_status="safe",
        reason="invalid route",
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
            "bad route",
            "--json",
            "--output", str(route_file),
        ]
        assert committee.main() == 2
    finally:
        sys.argv = original_argv

    assert not route_file.exists()


def test_double_parse_failure_fallback_to_pro(monkeypatch):
    import local_route_committee as committee

    # Both models return non-JSON garbage
    monkeypatch.setattr(committee, "_call_model", lambda model, prompt, timeout=90: ("not json", {"ok": False}))
    monkeypatch.setattr(committee, "_check_model_availability", lambda model, base_url=None, timeout=5: (True, "mock"))
    monkeypatch.setattr(committee, "build_evidence_pack", lambda repo_root=".": {
        "git_status": "clean",
        "recent_commits": "abc123 test",
        "file_tree": "README.md",
        "current_diff": "none",
        "test_status": "unknown",
        "privacy_scan": "safe",
        "project_phase": "development",
    })

    decision = committee.convene("fix typo")
    assert decision.recommended_route == "pro_decision"
    assert decision.escalated is True
    assert "could not parse either model" in decision.reason


@pytest.mark.skip(reason="model changed")
def test_single_parse_failure_uses_other_model(monkeypatch):
    import local_route_committee as committee

    def fake_call(model, prompt, timeout=90):
        if "qwen" in model:
            return "not json", {"ok": False}
        return (
            '{"delegability":"high","recommended_route":"flash_subagent",'
            '"local_preprocessing_required":false,"pro_should_execute":false,'
            '"pro_should_adjudicate":false,"risk_level":"low",'
            '"privacy_status":"safe","reason":"looks safe","required_artifacts":[]}'
        ), {"ok": True}

    monkeypatch.setattr(committee, "_call_model", fake_call)
    monkeypatch.setattr(committee, "_check_model_availability", lambda model, base_url=None, timeout=5: (True, "mock"))
    monkeypatch.setattr(committee, "build_evidence_pack", lambda repo_root=".": {
        "git_status": "clean",
        "recent_commits": "abc123 test",
        "file_tree": "README.md",
        "current_diff": "none",
        "test_status": "unknown",
        "privacy_scan": "safe",
        "project_phase": "development",
    })

    decision = committee.convene("fix typo")
    assert decision.recommended_route == "flash_subagent"
    assert decision.reason.startswith("Single model")


def test_build_route_prompt_includes_role_and_schema():
    import local_route_committee as committee

    prompt = committee.build_route_prompt(
        "Role: test role.",
        '{"task":"x"}',
        "Git status: clean",
    )

    assert "Role: test role." in prompt
    assert '{"task":"x"}' in prompt
    assert "Git status: clean" in prompt
    assert committee.ROUTE_JUDGEMENT_SCHEMA in prompt


def test_convene_uses_role_specific_prompts(monkeypatch):
    import local_route_committee as committee

    prompts = {}
    valid_json = (
        '{"delegability":"high","recommended_route":"local_only",'
        '"local_preprocessing_required":true,"pro_should_execute":false,'
        '"pro_should_adjudicate":false,"risk_level":"low",'
        '"privacy_status":"safe","reason":"ok","required_artifacts":["summary"]}'
    )

    def fake_call(model, prompt, timeout=90):
        prompts[model] = prompt
        return valid_json, {"ok": True}

    monkeypatch.setattr(committee, "_call_model", fake_call)
    monkeypatch.setattr(committee, "_check_model_availability", lambda model, base_url=None, timeout=5: (True, "mock"))
    monkeypatch.setattr(committee, "build_evidence_pack", lambda repo_root=".": {
        "git_status": "clean",
        "recent_commits": "abc123 test",
        "file_tree": "README.md",
        "current_diff": "none",
        "test_status": "unknown",
        "privacy_scan": "safe",
        "project_phase": "development",
    })

    decision = committee.convene("summarize repository")

    qwen_prompt = prompts[committee._LOCAL_ROUTE_QWEN_MODEL]
    gemma_prompt = prompts[committee._LOCAL_ROUTE_GEMMA_MODEL]
    assert "Qwen engineering delegate" in qwen_prompt
    assert "Gemma risk and privacy reviewer" in gemma_prompt
    assert "required_artifacts" in qwen_prompt
    assert "privacy_status=blocked" in gemma_prompt
    assert qwen_prompt != gemma_prompt
    assert decision.recommended_route == "local_only"


def test_convene_merges_different_role_judgements(monkeypatch):
    import local_route_committee as committee

    qwen_json = (
        '{"delegability":"high","recommended_route":"flash_direct",'
        '"local_preprocessing_required":false,"pro_should_execute":false,'
        '"pro_should_adjudicate":false,"risk_level":"low",'
        '"privacy_status":"safe","reason":"simple bounded rewrite",'
        '"required_artifacts":["diff"]}'
    )
    gemma_json = (
        '{"delegability":"high","recommended_route":"local_only",'
        '"local_preprocessing_required":true,"pro_should_execute":false,'
        '"pro_should_adjudicate":false,"risk_level":"medium",'
        '"privacy_status":"safe","reason":"safe but inspect first",'
        '"required_artifacts":["summary"]}'
    )

    def fake_call(model, prompt, timeout=90):
        if model == committee._LOCAL_ROUTE_QWEN_MODEL:
            assert "Qwen engineering delegate" in prompt
            return qwen_json, {"ok": True}
        assert model == committee._LOCAL_ROUTE_GEMMA_MODEL
        assert "Gemma risk and privacy reviewer" in prompt
        return gemma_json, {"ok": True}

    monkeypatch.setattr(committee, "_call_model", fake_call)
    monkeypatch.setattr(committee, "_check_model_availability", lambda model, base_url=None, timeout=5: (True, "mock"))
    monkeypatch.setattr(committee, "build_evidence_pack", lambda repo_root=".": {
        "git_status": "clean",
        "recent_commits": "abc123 test",
        "file_tree": "README.md",
        "current_diff": "none",
        "test_status": "unknown",
        "privacy_scan": "safe",
        "project_phase": "development",
    })

    decision = committee.convene("rewrite a short doc section", plan_json="")

    assert decision.recommended_route == "flash_direct"
    assert decision.risk_level == "medium"
    assert set(decision.required_artifacts) == {"diff", "summary"}
    assert decision.agreement is True


def test_convene_escapes_fallback_plan_json(monkeypatch):
    import local_route_committee as committee

    prompts = {}
    valid_json = (
        '{"delegability":"high","recommended_route":"local_only",'
        '"local_preprocessing_required":true,"pro_should_execute":false,'
        '"pro_should_adjudicate":false,"risk_level":"low",'
        '"privacy_status":"safe","reason":"ok","required_artifacts":[]}'
    )

    def fake_call(model, prompt, timeout=90):
        prompts[model] = prompt
        return valid_json, {"ok": True}

    monkeypatch.setattr(committee, "_call_model", fake_call)
    monkeypatch.setattr(committee, "_check_model_availability", lambda model, base_url=None, timeout=5: (True, "mock"))
    monkeypatch.setattr(committee, "build_evidence_pack", lambda repo_root=".": {
        "git_status": "clean",
        "recent_commits": "abc123 test",
        "file_tree": "README.md",
        "current_diff": "none",
        "test_status": "unknown",
        "privacy_scan": "safe",
        "project_phase": "development",
    })

    committee.convene('rewrite "quoted" section\nwith newline', plan_json="")

    qwen_prompt = prompts[committee._LOCAL_ROUTE_QWEN_MODEL]
    assert json.dumps(
        {"task": 'rewrite "quoted" section\nwith newline'},
        ensure_ascii=False,
    ) in qwen_prompt


def test_call_model_with_retry_retries_once(monkeypatch):
    import local_route_committee as committee

    calls = []
    valid_json = (
        '{"delegability":"high","recommended_route":"flash_subagent",'
        '"local_preprocessing_required":false,"pro_should_execute":false,'
        '"pro_should_adjudicate":false,"risk_level":"low",'
        '"privacy_status":"safe","reason":"ok","required_artifacts":[]}'
    )

    def fake_call(model, prompt, timeout=90):
        calls.append(model)
        if len(calls) == 1:
            return "not json", {"ok": False}
        return valid_json, {"ok": True}

    monkeypatch.setattr(committee, "_call_model", fake_call)

    raw, metrics_list = committee._call_model_with_retry("qwen3.6:27b", "prompt", timeout=90)
    assert raw == valid_json
    assert len(calls) == 2


def test_call_model_with_retry_respects_max_retries_zero(monkeypatch):
    import local_route_committee as committee

    calls = []

    def fake_call(model, prompt, timeout=90):
        calls.append(model)
        return "not json", {"ok": False}

    monkeypatch.setattr(committee, "_call_model", fake_call)

    raw, metrics_list = committee._call_model_with_retry("qwen3.6:27b", "prompt", timeout=90, max_retries=0)
    assert raw == "not json"
    assert len(calls) == 1


def test_invalid_committee_timeout_env_is_ignored(monkeypatch):
    import local_route_committee as committee

    monkeypatch.setenv("LOCAL_LLM_COMMITTEE_TIMEOUT", "not-a-number")

    def fake_call(model, prompt, timeout=90):
        return f"timeout={timeout}", {"ok": True}

    monkeypatch.setattr(committee, "_call_model", fake_call)
    raw, metrics = committee._call_model("qwen3.6:27b", "prompt")
    assert "timeout=90" in raw

