"""P3-B / P3-C1 / P3-C2 — env knob helpers for auto-escalation restriction.

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

4. P3-C2 behavioral gate (``len(uncertain_points) > 3`` auto-escalation):
   - Default OFF: ``_check_quality_escalation`` no longer escalates on
     ``uncertain_points > 3`` alone.
   - ``LOCAL_LLM_AUTO_ESCALATE_ON_UNCERTAIN=true`` (or any truthy value)
     restores the legacy auto-escalation.

5. ``_derive_escalation_trigger`` mirrors both gates so the ledger
   ``escalation_trigger`` label always matches the branch that actually
   fired (or ``"unknown"`` when neither branch can fire because both
   knobs are OFF). ``timeout`` precedence remains unconditional.

6. The ``timeout`` downgrade path is intentionally never gated.
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


# --------------------------------------------------------------------------- #
# P3-C2: uncertain_points > 3 auto-escalation is now default OFF.             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("env_state", [None, "false", "FALSE", "0",
                                        "no", "off", "", "  ", "garbage"])
def test_p3c2_uncertain_points_default_off(monkeypatch, env_state):
    """P3-C2 default: a payload with only uncertain_points > 3 must NOT
    escalate when the env knob is unset, falsy, empty, or unrecognized."""
    if env_state is None:
        monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    else:
        monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, env_state)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    payload = {"confidence": "medium",
               "uncertain_points": ["a", "b", "c", "d"]}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is None, (
        f"P3-C2 regression: uncertain_points escalated despite knob={env_state!r}"
    )


@pytest.mark.parametrize("env_state", ["true", "TRUE", "True",
                                        "1", "yes", "YES", "on", "ON",
                                        "  true  "])
def test_p3c2_uncertain_points_env_knob_restores_legacy(monkeypatch, env_state):
    """When the env knob is truthy, uncertain_points > 3 escalates exactly
    like the pre-P3-C2 behavior."""
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, env_state)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    payload = {"confidence": "medium",
               "uncertain_points": ["a", "b", "c", "d"]}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is not None, (
        f"P3-C2 regression: uncertain_points escalation suppressed even with knob={env_state!r}"
    )
    assert result in ("smart_summary", "qwen3.6_27b_mtp", "code_worker"), (
        f"Unexpected escalation target: {result}"
    )


def test_p3c2_uncertain_count_exactly_three_does_not_escalate_even_with_knob_on(monkeypatch):
    """The threshold is strictly > 3; count of 3 must not escalate even
    when the knob is ON. P3-C2 must not change this threshold."""
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, "true")
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    payload = {"confidence": "medium",
               "uncertain_points": ["a", "b", "c"]}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is None, "uncertain_count == 3 must not trigger; threshold is > 3"


# --------------------------------------------------------------------------- #
# Dual-signal matrix (P3-C1 + P3-C2 interaction)                              #
# --------------------------------------------------------------------------- #
#
# Payload: {"confidence": "low", "uncertain_points": ["a","b","c","d"]}
#
# | low knob | uncertain knob | _check_quality_escalation | _derive_escalation_trigger |
# |----------|----------------|----------------------------|----------------------------|
# | OFF      | OFF            | None (no escalation)       | "unknown"                  |
# | ON       | OFF            | escalate via low branch    | "low_confidence"           |
# | OFF      | ON             | escalate via uncertain     | "uncertain_points"         |
# | ON       | ON             | escalate via low branch    | "low_confidence" (legacy)  |
#
# --------------------------------------------------------------------------- #


_DUAL_PAYLOAD = {"confidence": "low",
                 "uncertain_points": ["a", "b", "c", "d"]}


def _set_knobs(monkeypatch, low: bool, uncertain: bool) -> None:
    if low:
        monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, "true")
    else:
        monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    if uncertain:
        monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, "true")
    else:
        monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)


def test_dual_signal_both_off_no_escalation(monkeypatch):
    _set_knobs(monkeypatch, low=False, uncertain=False)
    result = mcp._check_quality_escalation(
        _DUAL_PAYLOAD, "fast_summary", "summarize-file")
    assert result is None
    assert mcp._derive_escalation_trigger(_DUAL_PAYLOAD) == "unknown"


def test_dual_signal_low_on_uncertain_off_via_low(monkeypatch):
    _set_knobs(monkeypatch, low=True, uncertain=False)
    result = mcp._check_quality_escalation(
        _DUAL_PAYLOAD, "fast_summary", "summarize-file")
    assert result is not None
    assert mcp._derive_escalation_trigger(_DUAL_PAYLOAD) == "low_confidence"


def test_dual_signal_low_off_uncertain_on_via_uncertain(monkeypatch):
    _set_knobs(monkeypatch, low=False, uncertain=True)
    result = mcp._check_quality_escalation(
        _DUAL_PAYLOAD, "fast_summary", "summarize-file")
    assert result is not None
    assert mcp._derive_escalation_trigger(_DUAL_PAYLOAD) == "uncertain_points"


def test_dual_signal_both_on_low_wins(monkeypatch):
    _set_knobs(monkeypatch, low=True, uncertain=True)
    result = mcp._check_quality_escalation(
        _DUAL_PAYLOAD, "fast_summary", "summarize-file")
    assert result is not None
    assert mcp._derive_escalation_trigger(_DUAL_PAYLOAD) == "low_confidence"


# --------------------------------------------------------------------------- #
# _derive_escalation_trigger: knob-by-knob coverage                           #
# --------------------------------------------------------------------------- #


def test_derive_trigger_low_off_only_returns_unknown(monkeypatch):
    _set_knobs(monkeypatch, low=False, uncertain=False)
    assert mcp._derive_escalation_trigger({"confidence": "low"}) == "unknown"


def test_derive_trigger_low_on_returns_low_confidence(monkeypatch):
    _set_knobs(monkeypatch, low=True, uncertain=False)
    assert mcp._derive_escalation_trigger({"confidence": "low"}) == "low_confidence"


def test_derive_trigger_uncertain_off_only_returns_unknown(monkeypatch):
    _set_knobs(monkeypatch, low=False, uncertain=False)
    assert mcp._derive_escalation_trigger({
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "unknown"


def test_derive_trigger_uncertain_on_returns_uncertain_points(monkeypatch):
    _set_knobs(monkeypatch, low=False, uncertain=True)
    assert mcp._derive_escalation_trigger({
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "uncertain_points"


def test_derive_trigger_empty_payload_returns_unknown(monkeypatch):
    """A payload with no quality signals returns 'unknown' regardless of
    knob state (no branch fires)."""
    for low, uncertain in ((False, False), (True, False),
                           (False, True), (True, True)):
        _set_knobs(monkeypatch, low=low, uncertain=uncertain)
        assert mcp._derive_escalation_trigger({}) == "unknown", (
            f"empty payload should be 'unknown' regardless of knobs "
            f"(low={low}, uncertain={uncertain})"
        )


# --------------------------------------------------------------------------- #
# timeout: unconditional precedence regardless of either knob                  #
# --------------------------------------------------------------------------- #


def test_timeout_precedence_across_all_knob_combinations(monkeypatch):
    """timeout is not gated by either knob and wins over both low and
    uncertain in the trigger label, across the full 4x4 knob matrix."""
    for low_state in (None, "true", "false", ""):
        for uncertain_state in (None, "true", "false", ""):
            if low_state is None:
                monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
            else:
                monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, low_state)
            if uncertain_state is None:
                monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
            else:
                monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, uncertain_state)
            assert mcp._derive_escalation_trigger({
                "error_type": "timeout",
                "confidence": "low",
                "uncertain_points": ["a", "b", "c", "d"],
            }) == "timeout", (
                f"timeout must win regardless of knobs "
                f"(low={low_state!r}, uncertain={uncertain_state!r})"
            )


def test_timeout_downgrade_unchanged(monkeypatch):
    """Timeout downgrade in _check_quality_escalation is not gated by
    either knob — even with both OFF, timeout still downgrades."""
    _set_knobs(monkeypatch, low=False, uncertain=False)
    payload = {"error_type": "timeout"}
    result = mcp._check_quality_escalation(payload, "smart_summary", "summarize-file")
    assert result is not None, "Timeout downgrade must remain enabled by default"


# --------------------------------------------------------------------------- #
# P3-C1 low_confidence behavior must still hold after P3-C2                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("env_state", [None, "false", "0", "no", "off", ""])
def test_p3c1_low_confidence_still_default_off_after_p3c2(monkeypatch, env_state):
    """Regression guard: P3-C2 must not accidentally re-enable low_confidence
    auto-escalation. With only the low knob OFF, no escalation fires."""
    if env_state is None:
        monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, raising=False)
    else:
        monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, env_state)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    payload = {"confidence": "low", "uncertain_points": []}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is None


@pytest.mark.parametrize("env_state", ["true", "1", "yes", "on"])
def test_p3c1_low_confidence_still_restorable_after_p3c2(monkeypatch, env_state):
    """Regression guard: P3-C2 must not break the P3-C1 env-knob restore path."""
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, env_state)
    monkeypatch.delenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, raising=False)
    payload = {"confidence": "low", "uncertain_points": []}
    result = mcp._check_quality_escalation(payload, "fast_summary", "summarize-file")
    assert result is not None
