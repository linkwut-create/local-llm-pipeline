"""P3-B / P3-C1 — env knob helpers for auto-escalation restriction.

Covers:

1. ``_parse_env_flag`` boolean parser semantics: unset / truthy / falsy /
   empty / unrecognized / case + whitespace handling.

2. The two P3 env-knob constant names exist with the expected literal
   string values.

3. P3-C1 behavioral gate (``confidence=="low"`` auto-escalation):
   - Default OFF: ``_check_quality_escalation`` no longer escalates on
     ``confidence=="low"`` alone.
   - ``LOCAL_LLM_AUTO_ESCALATE_ON_LOW_CONFIDENCE=true`` (or any truthy
     value) restores the legacy auto-escalation.
   - Falsy / empty / unrecognized values keep the gate closed.
   - ``_derive_escalation_trigger`` returns ``"low_confidence"`` only
     when the knob is ON; otherwise falls through to the uncertain /
     unknown labels so the ledger trigger matches what actually fired.

4. P3-C1 must NOT change the ``uncertain_points > 3`` branch or the
   ``timeout`` downgrade path (those remain P3-C2 / unchanged).
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
# P3-C1: confidence=="low" auto-escalation is now default OFF.                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("env_state", [None, "false", "FALSE", "0",
                                        "no", "off", "", "  ", "garbage"])
def test_p3c1_low_confidence_default_off(monkeypatch, env_state):
    """P3-C1 default: a payload with only confidence=="low" must NOT escalate
    when the env knob is unset, falsy, empty, or an unrecognized value."""
    if env_state is None:
        monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    else:
        monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, env_state)
    payload = {"confidence": "low", "uncertain_points": []}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is None, (
        f"P3-C1 regression: low-confidence escalated despite knob={env_state!r}"
    )


@pytest.mark.parametrize("env_state", ["true", "TRUE", "True",
                                        "1", "yes", "YES", "on", "ON",
                                        "  true  "])
def test_p3c1_low_confidence_env_knob_restores_legacy(monkeypatch, env_state):
    """When the env knob is truthy, confidence=="low" escalates exactly
    like the pre-P3-C1 behavior."""
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, env_state)
    payload = {"confidence": "low", "uncertain_points": []}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is not None, (
        f"P3-C1 regression: low-confidence escalation suppressed even with knob={env_state!r}"
    )
    # The escalated target is the next tier in the summarize-file chain.
    assert result in ("smart_summary", "qwen3.6_27b_mtp", "code_worker"), (
        f"Unexpected escalation target: {result}"
    )


def test_p3c1_low_confidence_plus_uncertain_still_escalates_via_uncertain(monkeypatch):
    """Dual signal: when confidence=="low" AND len(uncertain_points) > 3,
    escalation must still fire — but via the uncertain_points branch
    (since low_confidence is gated OFF by default). P3-C2 will gate
    uncertain_points too; until then this is the expected behavior."""
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    payload = {"confidence": "low",
               "uncertain_points": ["a", "b", "c", "d", "e"]}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is not None, "Dual signal should still escalate via uncertain branch"


# --------------------------------------------------------------------------- #
# P3-C1: _derive_escalation_trigger respects the same knob                    #
# --------------------------------------------------------------------------- #


def test_p3c1_derive_trigger_low_confidence_off_returns_unknown(monkeypatch):
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    assert mcp._derive_escalation_trigger({"confidence": "low"}) == "unknown"


def test_p3c1_derive_trigger_low_confidence_on_returns_low_confidence(monkeypatch):
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, "true")
    assert mcp._derive_escalation_trigger({"confidence": "low"}) == "low_confidence"


def test_p3c1_derive_trigger_dual_signal_off_returns_uncertain(monkeypatch):
    """When knob is OFF and payload has both signals, the trigger label
    must match the branch that actually fired (uncertain_points)."""
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    assert mcp._derive_escalation_trigger({
        "confidence": "low",
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "uncertain_points"


def test_p3c1_derive_trigger_dual_signal_on_returns_low_confidence(monkeypatch):
    """When knob is ON the legacy ordering wins: low_confidence over uncertain_points."""
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, "true")
    assert mcp._derive_escalation_trigger({
        "confidence": "low",
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "low_confidence"


def test_p3c1_derive_trigger_timeout_still_wins(monkeypatch):
    """timeout precedence is unchanged regardless of the low_confidence knob."""
    for env_state in (None, "true", "false"):
        if env_state is None:
            monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
        else:
            monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, env_state)
        assert mcp._derive_escalation_trigger({
            "error_type": "timeout",
            "confidence": "low",
        }) == "timeout"


# --------------------------------------------------------------------------- #
# Untouched paths (P3-C2 / unchanged territory)                               #
# --------------------------------------------------------------------------- #


def test_p3c1_uncertain_points_escalation_unchanged(monkeypatch):
    """P3-C1 must NOT touch the uncertain_points > 3 branch.
    It still auto-escalates regardless of either env knob's value."""
    for env_state in (None, "true", "false", "", "0", "1"):
        if env_state is None:
            monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
        else:
            monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, env_state)
        monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
        payload = {"confidence": "medium",
                   "uncertain_points": ["a", "b", "c", "d"]}
        result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
        assert result is not None, (
            f"P3-C1 must NOT gate uncertain_points; knob={env_state!r}, result={result!r}"
        )


def test_p3c1_timeout_downgrade_unchanged(monkeypatch):
    """Timeout downgrade is kept across all P3 phases per §4.2; not gated
    by either knob. P3-C1 must NOT touch it."""
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    payload = {"error_type": "timeout"}
    result = mcp._check_quality_escalation(payload, "smart_summary", "summarize-file")
    assert result is not None, "Timeout downgrade must remain enabled by default"
