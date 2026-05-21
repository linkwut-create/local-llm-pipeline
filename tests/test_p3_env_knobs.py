"""P3-B — env knob helpers for auto-escalation restriction.

Covers:

1. ``_parse_env_flag`` boolean parser semantics: unset / truthy / falsy /
   empty / unrecognized / case + whitespace handling.

2. The two P3 env-knob constant names exist with the expected literal
   string values.

3. Smoke check: the existing P3-A.1-documented runtime escalation
   behavior is unchanged at this commit (``_check_quality_escalation``
   still escalates on ``confidence=="low"`` and ``len(uncertain_points) > 3``
   when no env knob is set — P3-B is wiring-free; P3-C1 / P3-C2 will
   flip these to default OFF behind the same knobs).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import local_llm_mcp_server as mcp  # noqa: E402


# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #


def test_env_knob_constant_names():
    """The two env knob names match the spec in docs/MCP_COST_DISCIPLINE_PLAN.md §4.2."""
    assert mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE == "LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE"
    assert mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN == "LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN"


# --------------------------------------------------------------------------- #
# _parse_env_flag: unset → default                                            #
# --------------------------------------------------------------------------- #


def test_parse_env_flag_unset_defaults_false(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_TEST_FLAG_X", raising=False)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X") is False


def test_parse_env_flag_unset_with_default_true(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_TEST_FLAG_X", raising=False)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X", default=True) is True


def test_parse_env_flag_real_knobs_default_false_when_unset(monkeypatch):
    """The P3-B knobs themselves default to OFF when not set in the env."""
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    assert mcp._parse_env_flag(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE) is False
    assert mcp._parse_env_flag(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN) is False


# --------------------------------------------------------------------------- #
# _parse_env_flag: truthy values                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "tRuE",
                                    "1",
                                    "yes", "YES", "Yes",
                                    "on", "ON", "On"])
def test_parse_env_flag_truthy(monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_TEST_FLAG_X", value)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X") is True


@pytest.mark.parametrize("value", ["  true  ", "\ttrue\n", " 1 ", " yes ", "  on  "])
def test_parse_env_flag_truthy_whitespace_trim(monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_TEST_FLAG_X", value)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X") is True


# --------------------------------------------------------------------------- #
# _parse_env_flag: falsy values (incl. empty)                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["false", "FALSE", "False",
                                    "0",
                                    "no", "NO", "No",
                                    "off", "OFF", "Off"])
def test_parse_env_flag_falsy(monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_TEST_FLAG_X", value)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X") is False


@pytest.mark.parametrize("value", ["", "   ", "\t\n", "  \t  "])
def test_parse_env_flag_empty_is_false(monkeypatch, value):
    """Per spec: empty / whitespace-only is explicitly False, even when default=True."""
    monkeypatch.setenv("LOCAL_LLM_TEST_FLAG_X", value)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X") is False
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X", default=True) is False


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_parse_env_flag_explicit_falsy_overrides_default_true(monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_TEST_FLAG_X", value)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X", default=True) is False


# --------------------------------------------------------------------------- #
# _parse_env_flag: unrecognized values → default                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", ["maybe", "2", "garbage", "True False",
                                    "y", "n", "enabled", "disabled"])
def test_parse_env_flag_unrecognized_uses_default(monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_TEST_FLAG_X", value)
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X") is False
    assert mcp._parse_env_flag("LOCAL_LLM_TEST_FLAG_X", default=True) is True


# --------------------------------------------------------------------------- #
# Runtime invariance smoke test (P3-B must NOT change current behavior)       #
# --------------------------------------------------------------------------- #


def test_p3b_low_confidence_escalation_unchanged(monkeypatch):
    """P3-B is wiring-free. ``_check_quality_escalation`` must still
    escalate on ``confidence=="low"`` regardless of whether the new env
    knob is set, unset, or explicitly OFF — the runtime flip happens in
    P3-C1, not P3-B."""
    for env_state in (None, "true", "false", "", "0", "1"):
        if env_state is None:
            monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
        else:
            monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, env_state)
        payload = {"confidence": "low", "uncertain_points": []}
        result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
        assert result is not None, (
            f"P3-B regression: low-confidence escalation disabled with env={env_state!r}; "
            f"behavioral flip must wait for P3-C1"
        )


def test_p3b_uncertain_points_escalation_unchanged(monkeypatch):
    """Same invariance for the uncertain_points > 3 path (P3-C2 territory)."""
    for env_state in (None, "true", "false", "", "0", "1"):
        if env_state is None:
            monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
        else:
            monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, env_state)
        payload = {"confidence": "medium",
                   "uncertain_points": ["a", "b", "c", "d"]}
        result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
        assert result is not None, (
            f"P3-B regression: uncertain-points escalation disabled with env={env_state!r}; "
            f"behavioral flip must wait for P3-C2"
        )


def test_p3b_timeout_downgrade_unchanged(monkeypatch):
    """Timeout downgrade is kept across all P3 phases per §4.2; not gated by either knob."""
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    payload = {"error_type": "timeout"}
    result = mcp._check_quality_escalation(payload, "smart_summary", "summarize-file")
    assert result is not None, "Timeout downgrade must remain enabled by default"
