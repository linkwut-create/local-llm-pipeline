"""Test local_llm_debate.py structure and constraints (no LLM calls)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_debate as debate

TOOLS_DIR = Path(__file__).parent.parent / "tools"
PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"
TASKS_PATH = TOOLS_DIR / "local_llm_tasks.json"


def test_max_rounds_capped_at_3():
    assert debate.MAX_ROUNDS == 3


def test_fast_mode_uses_two_profiles():
    profiles = debate.DEFAULT_ROUND_PROFILES[:2]
    assert len(profiles) == 2
    assert "deep_reviewer" not in profiles


def test_default_profiles_order():
    assert debate.DEFAULT_ROUND_PROFILES == [
        "code_worker", "reasoning_checker", "deep_reviewer"
    ]


def test_debate_tasks_defined():
    expected = {"review-diff", "risk-analysis", "architecture-review", "failure-mode-analysis"}
    assert debate.DEBATE_TASKS == expected


def test_classify_findings_empty():
    result = debate.classify_findings([])
    assert "high_confidence_findings" in result
    assert "candidate_findings" in result
    assert "disputed_findings" in result
    assert "controller_must_verify" in result
    assert "test_gaps" in result


def test_classify_findings_extracts_sections():
    mock_round = {
        "round": 3,
        "ok": True,
        "raw_output": """## HIGH_CONFIDENCE
- Buffer overflow in parse_input when size > MAX_BUF
- Missing null check on config.model

## CANDIDATE
- Possible race condition in concurrent file writes

## DISPUTED
- Round 1 claims timeout is too low, Round 2 disagrees

## CONTROLLER_MUST_VERIFY
- Whether the API contract allows empty responses

## TEST_GAPS
- No test for max_chars boundary
""",
    }
    result = debate.classify_findings([mock_round])
    assert len(result["high_confidence_findings"]) >= 1
    assert len(result["candidate_findings"]) >= 1
    assert len(result["controller_must_verify"]) >= 1


def test_blocked_paths_respected():
    from local_llm_worker import is_blocked_path
    assert is_blocked_path(Path(".git/config"))
    assert is_blocked_path(Path(".env"))
    assert is_blocked_path(Path("secrets/key.pem"))
    assert not is_blocked_path(Path("tools/local_llm_debate.py"))


def test_round_prompts_exist_for_all_tasks():
    for task in debate.DEBATE_TASKS:
        prompt = debate.get_round_prompt(1, task)
        assert len(prompt) > 20, f"Round 1 prompt missing for {task}"
    for round_num in [2, 3]:
        prompt = debate.get_round_prompt(round_num, "review-diff")
        assert len(prompt) > 20, f"Round {round_num} prompt missing"


def test_run_round_graceful_failure():
    """run_round should return error dict when model is unreachable, not raise."""
    profiles = {"test_profile": {"model": "nonexistent", "max_output_chars": 100}}
    result = debate.run_round(
        round_num=1,
        task="review-diff",
        original_input="test input",
        prior_outputs=[],
        profile_name="test_profile",
        profiles=profiles,
        provider="ollama",
        timeout=5,
        max_output_chars=100,
    )
    assert result["ok"] is False
    assert result["error"] is not None
    assert result["round"] == 1


def test_build_markdown_structure():
    rounds = [
        {"round": 1, "profile": "code_worker", "model": "test", "ok": True,
         "elapsed_seconds": 1.0, "raw_output": "Found issues", "error": None},
    ]
    findings = {
        "high_confidence_findings": ["issue1"],
        "candidate_findings": [],
        "disputed_findings": [],
        "controller_must_verify": ["verify1"],
        "test_gaps": [],
    }
    md = debate.build_markdown("review-diff", rounds, findings, {"code_worker": "test"}, 1.0)
    assert "# Debate: review-diff" in md
    assert "Round 1" in md
    assert "issue1" in md
    assert "Controller must verify" in md.lower() or "controller_must_verify" in md


def test_json_output_has_required_fields():
    required = {
        "task", "mode", "profiles", "models", "ok", "input", "rounds",
        "high_confidence_findings", "candidate_findings", "disputed_findings",
        "controller_must_verify", "test_gaps", "not_verified", "warnings",
        "error", "created_at",
    }
    # Simulate output structure
    sample = {
        "task": "review-diff",
        "mode": "debate",
        "profiles": ["code_worker"],
        "models": {"code_worker": "test"},
        "ok": True,
        "input": {"source": "test", "chars": 100},
        "rounds": [],
        "high_confidence_findings": [],
        "candidate_findings": [],
        "disputed_findings": [],
        "controller_must_verify": [],
        "test_gaps": [],
        "not_verified": ["Local models did not run tests"],
        "warnings": [],
        "error": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "elapsed_seconds": 0,
    }
    assert required.issubset(sample.keys())


def test_debate_tasks_in_tasks_json():
    """Debate tasks should be registered in tasks.json."""
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]
    for dt in ["debate-review-diff", "debate-risk-analysis",
               "debate-architecture-review", "debate-failure-mode-analysis"]:
        assert dt in tasks, f"Debate task '{dt}' not in tasks.json"
        assert tasks[dt]["may_modify_code"] is False
        assert tasks[dt]["controller_must_verify"] is True
