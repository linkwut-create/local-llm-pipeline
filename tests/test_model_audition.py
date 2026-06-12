"""Tests for model audition system — all mocked, no real model calls."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

# Import audition modules
from model_audition import load_case, list_cases, run_audition, save_results
from score_model_audition import auto_score, compute_role_fit, recommend_roles, load_results


# ── Case loading ──

class TestCaseLoading:
    def test_list_cases_returns_all(self):
        cases = list_cases()
        assert len(cases) >= 15, f"Expected >= 15 cases, got {len(cases)}"

    def test_each_case_has_id(self):
        for case_name in list_cases():
            case = load_case(case_name)
            assert case is not None, f"Case '{case_name}' failed to load"
            assert case["case_id"], f"Case '{case_name}' has no case_id"
            assert case["prompt"], f"Case '{case_name}' has no prompt"

    def test_case_003_contains_tag_drift(self):
        case = load_case("003")
        assert case is not None
        assert "tag" in case["prompt"].lower() or "drift" in case["prompt"].lower()

    def test_case_005_contains_diff_review(self):
        case = load_case("005")
        assert case is not None
        # Check title or prompt for diff/review keywords
        text = (case["title"] + " " + case["prompt"]).lower()
        assert "diff" in text or "review" in text or "interface" in text

    def test_case_009_contains_pollution(self):
        case = load_case("009")
        assert case is not None
        assert "pollution" in case["prompt"].lower() or "GRILLME" in case["prompt"]

    def test_case_010_contains_privacy(self):
        case = load_case("010")
        assert case is not None
        assert "cloud" in case["prompt"].lower() or "api key" in case["prompt"].lower()

    def test_case_011_contains_release(self):
        case = load_case("011")
        assert case is not None
        assert "release" in case["prompt"].lower() or "tag" in case["prompt"].lower()

    def test_case_014_contains_command_hygiene(self):
        case = load_case("014")
        assert case is not None
        assert "command" in case["prompt"].lower() or "IN.md" in case["prompt"]

    def test_case_015_contains_role_assignment(self):
        case = load_case("015")
        assert case is not None
        assert "role" in case["prompt"].lower() or "assignment" in case["prompt"].lower()


# ── Auto scoring ──

class TestAutoScoring:
    def test_empty_output_scores_low(self):
        result = {"raw_output": ""}
        scores = auto_score(result)
        assert scores["correctness"] <= 2  # empty = 1
        assert scores["usefulness"] <= 2   # short = 1

    def test_rich_output_scores_high(self):
        output = """# Analysis

## Root Cause
The model tag changed.

## Evidence
- ledger shows 95% failure

## Recommended Fix
1. Update tag
2. Validate config

## Risk
- Low risk change

## Tests
- Run validate_configs
"""
        result = {"raw_output": output}
        scores = auto_score(result)
        assert scores["correctness"] >= 3
        assert scores["completeness"] >= 2
        assert scores["format_discipline"] >= 3
        assert scores["risk_awareness"] >= 2  # keyword-based, may be low for short text
        assert scores["usefulness"] >= 1  # auto-scorer based on length

    def test_all_dimensions_present(self):
        result = {"raw_output": "Some output with ## headers and - lists and risk and test"}
        scores = auto_score(result)
        for dim in ["correctness", "completeness", "instruction_following",
                     "format_discipline", "hallucination_control",
                     "risk_awareness", "usefulness"]:
            assert dim in scores, f"Missing dimension: {dim}"
            assert 0 <= scores[dim] <= 5, f"{dim}: {scores[dim]} out of range"

    def test_hallucination_detection(self):
        # Output that invents non-existent files
        output = """
        Modify tools/nonexistent_module.py
        Also change tools/fake_router_v2.py
        And tools/made_up_worker.py
        """
        result = {"raw_output": output}
        scores = auto_score(result)
        # Should penalize fabricated paths
        assert scores["hallucination_control"] <= 3

    def test_known_files_not_flagged(self):
        output = """
        Modify tools/local_llm_router.py
        Check tools/local_llm_worker.py
        """
        result = {"raw_output": output}
        scores = auto_score(result)
        # Known files should not trigger hallucination penalty
        assert scores["hallucination_control"] >= 4


# ── Role fit computation ──

class TestRoleFit:
    def test_high_scores_get_best_roles(self):
        case_scores = {
            "001": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "002": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "003": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "004": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "005": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "006": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "007": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "008": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "009": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "010": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
            "011": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 5},
        }
        role_signals = compute_role_fit(case_scores, {})
        recommendations = recommend_roles(role_signals, {})
        assert len(recommendations["best"]) >= 3, "High scores should yield multiple best roles"

    def test_low_scores_get_avoid_roles(self):
        case_scores = {
            "001": {"correctness": 1, "completeness": 1, "usefulness": 1,
                     "instruction_following": 1, "format_discipline": 1,
                     "hallucination_control": 1, "risk_awareness": 1},
        }
        role_signals = compute_role_fit(case_scores, {})
        recommendations = recommend_roles(role_signals, {})
        assert len(recommendations["best"]) == 0, "Low scores should yield no best roles"
        assert len(recommendations["avoid"]) > 0, "Low scores should yield avoid roles"

    def test_coder_get_correct_roles(self):
        """qwen3-coder style scores: good at code, weak at release."""
        case_scores = {
            "001": {"correctness": 4, "completeness": 4, "usefulness": 4,
                     "instruction_following": 4, "format_discipline": 5,
                     "hallucination_control": 4, "risk_awareness": 3},
            "004": {"correctness": 5, "completeness": 5, "usefulness": 5,
                     "instruction_following": 5, "format_discipline": 5,
                     "hallucination_control": 5, "risk_awareness": 4},
            "006": {"correctness": 4, "completeness": 4, "usefulness": 4,
                     "instruction_following": 4, "format_discipline": 4,
                     "hallucination_control": 4, "risk_awareness": 3},
            "007": {"correctness": 4, "completeness": 4, "usefulness": 4,
                     "instruction_following": 4, "format_discipline": 4,
                     "hallucination_control": 4, "risk_awareness": 3},
            "011": {"correctness": 2, "completeness": 2, "usefulness": 2,
                     "instruction_following": 2, "format_discipline": 2,
                     "hallucination_control": 2, "risk_awareness": 1},
        }
        role_signals = compute_role_fit(case_scores, {})
        recommendations = recommend_roles(role_signals, {})
        best_roles = [b["role"] for b in recommendations["best"]]
        avoid_roles = [a["role"] for a in recommendations["avoid"]]
        # coder should be in best, release_auditor in avoid
        assert "code_worker" in best_roles or "test_agent" in best_roles, \
            f"Expected code_worker or test_agent in best, got {best_roles}"
        assert "release_auditor" in avoid_roles, \
            f"Expected release_auditor in avoid, got {avoid_roles}"


# ── Result loading ──

class TestResultLoading:
    def test_load_jsonl_results(self, tmp_path):
        # Create temp JSONL
        jl = tmp_path / "test.jsonl"
        jl.write_text(json.dumps({"model": "test-model", "case_id": "001", "success": True}) + "\n" +
                      json.dumps({"model": "test-model", "case_id": "002", "success": False}) + "\n",
                      encoding="utf-8")
        results = load_results([str(jl)])
        assert len(results) == 2
        assert results[0]["case_id"] == "001"
        assert results[1]["case_id"] == "002"


# ── Save results ──

class TestSaveResults:
    def test_save_and_reload(self, tmp_path, monkeypatch):
        import model_audition
        monkeypatch.setattr(model_audition, "RESULTS_DIR", tmp_path)
        results = [
            {"model": "test", "case_id": "001", "raw_output": "hello"},
            {"model": "test", "case_id": "002", "raw_output": "world"},
        ]
        path = save_results(results, "test")
        assert path.exists()
        content = path.read_text()
        assert "hello" in content
        assert "world" in content
