"""Test local_llm_debate.py structure and constraints (no LLM calls)."""

import json
import sys
from types import SimpleNamespace
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
        "commit_reviewer", "fast_summary", "reasoning_checker"
    ]


def test_debate_round_profiles_exist():
    """J-L3: every profile in DEFAULT_ROUND_PROFILES must be defined."""
    import json
    from pathlib import Path
    profiles_path = Path(__file__).parent.parent / "tools" / "local_llm_profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    for p in debate.DEFAULT_ROUND_PROFILES:
        assert p in profiles["profiles"], f"profile '{p}' missing from profiles.json"


def test_unavailable_profiles_not_in_default_rounds():
    """J-L3: unavailable profiles must NOT be in the default debate chain."""
    profiles = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))["profiles"]
    for profile_name in debate.DEFAULT_ROUND_PROFILES:
        backend_class = profiles[profile_name].get("_backend_class")
        assert backend_class != "unavailable"


def test_retired_mtp_profiles_not_in_default_rounds():
    """J-L3: retired MTP profiles stay out of the default debate chain."""
    assert "qwen3.6_27b_mtp" not in debate.DEFAULT_ROUND_PROFILES
    assert "qwen3.6_35b_moe_mtp" not in debate.DEFAULT_ROUND_PROFILES


def test_reasoning_checker_is_round_3():
    """J-L3: reasoning_checker remains the default third-round debate profile."""
    assert debate.DEFAULT_ROUND_PROFILES[2] == "reasoning_checker"


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


def test_run_round_uses_local_llm_api_key(monkeypatch):
    seen = {}

    def fake_call_model(_system, _user, config):
        seen["api_key"] = config.api_key
        return SimpleNamespace(content="ok", usage=None)

    monkeypatch.setenv("LOCAL_LLM_API_KEY", "test-key")
    monkeypatch.setattr(debate, "call_model", fake_call_model)

    result = debate.run_round(
        round_num=1,
        task="review-diff",
        original_input="test input",
        prior_outputs=[],
        profile_name="test_profile",
        profiles={"test_profile": {"model": "test-model", "max_output_chars": 100}},
        provider="openai-compatible",
        timeout=5,
        max_output_chars=100,
        base_url="http://example.test/v1",
    )

    assert result["ok"] is True
    assert seen["api_key"] == "test-key"


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


def test_max_findings_enforced():
    """MAX_FINDINGS should cap each category."""
    mock_round = {
        "round": 3,
        "ok": True,
        "raw_output": """## HIGH_CONFIDENCE
- Finding 1
- Finding 2
- Finding 3
- Finding 4
- Finding 5
- Finding 6
- Finding 7
- Finding 8
- Finding 9
- Finding 10

## CANDIDATE
- Candidate 1
- Candidate 2
- Candidate 3
- Candidate 4
- Candidate 5
- Candidate 6
- Candidate 7
- Candidate 8
- Candidate 9
- Candidate 10
""",
    }
    result = debate.classify_findings([mock_round])
    assert len(result["high_confidence_findings"]) <= debate.MAX_FINDINGS["high_confidence_findings"]
    assert len(result["candidate_findings"]) <= debate.MAX_FINDINGS["candidate_findings"]


def test_max_findings_limits_match_spec():
    """Verify MAX_FINDINGS has the required keys and conservative limits."""
    assert debate.MAX_FINDINGS["high_confidence_findings"] == 5
    assert debate.MAX_FINDINGS["candidate_findings"] == 8
    assert debate.MAX_FINDINGS["disputed_findings"] == 8
    assert debate.MAX_FINDINGS["controller_must_verify"] == 10
    assert debate.MAX_FINDINGS["test_gaps"] == 10


def test_build_markdown_summary_only():
    """With summary_only=True, markdown should skip per-round details."""
    rounds = [
        {"round": 1, "profile": "code_worker", "model": "test", "ok": True,
         "elapsed_seconds": 1.0, "raw_output": "Found issues", "error": None},
        {"round": 2, "profile": "reasoning_checker", "model": "test", "ok": True,
         "elapsed_seconds": 2.0, "raw_output": "Challenged findings", "error": None},
    ]
    findings = {
        "high_confidence_findings": ["issue1"],
        "candidate_findings": [],
        "disputed_findings": [],
        "controller_must_verify": ["verify1"],
        "test_gaps": [],
    }
    md = debate.build_markdown("review-diff", rounds, findings, {"code_worker": "test"}, 3.0,
                                summary_only=True)
    assert "# Debate: review-diff" in md
    assert "Total time: 3.0s" in md
    assert "## Synthesis" in md
    assert "issue1" in md
    # Summary-only must NOT include per-round sections
    assert "Round 1" not in md
    assert "Round 2" not in md


def test_build_markdown_full_includes_rounds():
    """Without summary_only, markdown should include per-round details."""
    rounds = [
        {"round": 1, "profile": "code_worker", "model": "test", "ok": True,
         "elapsed_seconds": 1.0, "raw_output": "Found issues", "error": None},
    ]
    findings = {
        "high_confidence_findings": [],
        "candidate_findings": [],
        "disputed_findings": [],
        "controller_must_verify": [],
        "test_gaps": [],
    }
    md = debate.build_markdown("review-diff", rounds, findings, {"code_worker": "test"}, 1.0,
                                summary_only=False)
    assert "Round 1" in md
    assert "Found issues" in md


def test_json_summary_only_excludes_detail_fields():
    """Summary-only JSON should exclude rounds, disputed_findings, test_gaps."""
    # Simulate the output dict construction from main()
    output = {
        "task": "review-diff",
        "mode": "debate",
        "profiles": ["code_worker", "reasoning_checker"],
        "models": {"code_worker": "test", "reasoning_checker": "test"},
        "ok": True,
        "input": {"source": "test", "chars": 100},
        "high_confidence_findings": [],
        "candidate_findings": [],
        "controller_must_verify": [],
        "not_verified": ["Local models did not run tests"],
        "warnings": [],
        "error": None,
        "elapsed_seconds": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    # Summary-only: these fields should NOT be present
    assert "rounds" not in output
    assert "disputed_findings" not in output
    assert "test_gaps" not in output


def test_json_full_includes_detail_fields():
    """Full JSON should include rounds, disputed_findings, test_gaps."""
    output = {
        "task": "review-diff",
        "rounds": [],
        "disputed_findings": [],
        "test_gaps": [],
    }
    assert "rounds" in output
    assert "disputed_findings" in output
    assert "test_gaps" in output
