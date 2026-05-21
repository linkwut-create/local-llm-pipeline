"""P2-C2.1 — _wrap_worker_call child escalation extra_env merge.

Covers two surfaces:

1. Pure helpers: ``_derive_escalation_trigger`` and
   ``_merge_escalation_ledger_extra_env``. No worker run.

2. ``_wrap_worker_call`` integration: monkeypatch ``run_subprocess`` /
   ``load_worker_output`` to simulate quality escalation signals, then
   capture the child call's ``extra_env`` and verify escalation context
   fields.  Does not invoke real models.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import local_llm_mcp_server as mcp  # noqa: E402


# --------------------------------------------------------------------------- #
# P3-C1 compatibility fixture: this file exercises the escalation-ledger
# plumbing (the env-stamping that happens *when* escalation fires).
# After P3-C1, ``confidence=="low"`` no longer auto-escalates by default,
# so without the env knob set the existing escalation-trigger tests would
# get no escalation hop to inspect. We restore the legacy behavior at
# module scope so these tests continue to exercise the plumbing for both
# signals (low_confidence and uncertain_points). P3-C2 will need the
# uncertain knob set too; we set both upfront for forward-compatibility.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _restore_legacy_escalation_signals(monkeypatch):
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_LOW_CONFIDENCE, "true")
    monkeypatch.setenv(mcp._ENV_AUTO_ESCALATE_ON_UNCERTAIN, "true")


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# ---------------------------------------------------------------------------


def _parse_env(env: dict) -> dict:
    return json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])


def _success_payload(**overrides) -> dict:
    """Minimal success payload for load_worker_output stub."""
    base = {
        "task": "summarize-file",
        "profile": "fast_summary",
        "prompt_id": "x",
        "prompt_version": "v1",
        "prompt_hash": "abc",
        "model": "gemma4:e4b",
        "cache_hit": False,
        "result": {"summary": "ok"},
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# 1. _derive_escalation_trigger                                               #
# --------------------------------------------------------------------------- #


def test_derive_trigger_low_confidence():
    assert mcp._derive_escalation_trigger({"confidence": "low"}) == "low_confidence"


def test_derive_trigger_uncertain_points():
    assert mcp._derive_escalation_trigger({
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "uncertain_points"


def test_derive_trigger_timeout():
    assert mcp._derive_escalation_trigger({
        "error_type": "timeout",
    }) == "timeout"


def test_derive_trigger_default_unknown():
    assert mcp._derive_escalation_trigger({}) == "unknown"


def test_derive_trigger_timeout_wins_over_low_confidence():
    """timeout is checked first; a payload with both must return timeout."""
    assert mcp._derive_escalation_trigger({
        "error_type": "timeout",
        "confidence": "low",
    }) == "timeout"


def test_derive_trigger_low_confidence_wins_over_uncertain():
    """confidence=low is checked before uncertain_points count."""
    assert mcp._derive_escalation_trigger({
        "confidence": "low",
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "low_confidence"


def test_derive_trigger_uncertain_boundary():
    """Exactly 3 uncertain -> not triggered; 4 -> triggered."""
    assert mcp._derive_escalation_trigger({
        "uncertain_points": ["a", "b", "c"],
    }) == "unknown"
    assert mcp._derive_escalation_trigger({
        "uncertain_points": ["a", "b", "c", "d"],
    }) == "uncertain_points"


# --------------------------------------------------------------------------- #
# 2. _merge_escalation_ledger_extra_env — pure helper                         #
# --------------------------------------------------------------------------- #


def test_merge_escalation_parent_none_produces_extra():
    env = mcp._merge_escalation_ledger_extra_env(
        None,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="confidence=low on fast_summary",
        escalation_from_profile="fast_summary",
        escalation_to_profile="smart_summary",
        escalation_depth=1,
        parent_request_id="req_parent_001",
    )
    assert set(env.keys()) == {"LOCAL_LLM_LEDGER_EXTRA"}
    payload = _parse_env(env)
    assert payload["auto_escalated"] is True
    assert payload["escalation_trigger"] == "low_confidence"
    assert payload["escalation_reason"] == "confidence=low on fast_summary"
    assert payload["escalation_from_profile"] == "fast_summary"
    assert payload["escalation_to_profile"] == "smart_summary"
    assert payload["escalation_depth"] == 1
    assert payload["parent_request_id"] == "req_parent_001"


def test_merge_escalation_parent_with_mcp_fields_inherits():
    parent_env = {
        "LOCAL_LLM_LEDGER_EXTRA": json.dumps({
            "mcp_tool_name": "local_summarize_file",
            "source": "manual-mcp",
            "commit_gate": False,
        }, separators=(",", ":")),
    }
    child_env = mcp._merge_escalation_ledger_extra_env(
        parent_env,
        auto_escalated=True,
        escalation_trigger="uncertain_points",
        escalation_reason="4 uncertain_points on fast_summary",
        escalation_from_profile="fast_summary",
        escalation_to_profile="smart_summary",
        escalation_depth=1,
        parent_request_id="req_parent_002",
    )
    payload = _parse_env(child_env)
    assert payload["mcp_tool_name"] == "local_summarize_file"
    assert payload["source"] == "manual-mcp"
    assert payload["commit_gate"] is False
    assert payload["auto_escalated"] is True
    assert payload["escalation_trigger"] == "uncertain_points"


def test_merge_escalation_parent_malformed_json_fail_safe():
    """Malformed JSON in parent env must not crash; child still gets
    escalation fields."""
    for bad in ["", "{not-json", "null", "[]", '"string"']:
        parent_env = {"LOCAL_LLM_LEDGER_EXTRA": bad}
        child_env = mcp._merge_escalation_ledger_extra_env(
            parent_env,
            auto_escalated=True,
            escalation_trigger="low_confidence",
            escalation_reason="test",
            escalation_from_profile="p1",
            escalation_to_profile="p2",
            escalation_depth=1,
            parent_request_id="req_x",
        )
        payload = _parse_env(child_env)
        assert payload["escalation_trigger"] == "low_confidence"


def test_merge_escalation_parent_no_ledger_key():
    """Parent env without LOCAL_LLM_LEDGER_EXTRA still works."""
    parent_env = {"PYTHONIOENCODING": "utf-8"}
    child_env = mcp._merge_escalation_ledger_extra_env(
        parent_env,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="test",
        escalation_from_profile="p1",
        escalation_to_profile="p2",
        escalation_depth=1,
        parent_request_id="req_x",
    )
    assert "LOCAL_LLM_LEDGER_EXTRA" in child_env


def test_merge_escalation_does_not_mutate_parent():
    parent_env = {
        "LOCAL_LLM_LEDGER_EXTRA": json.dumps({
            "mcp_tool_name": "local_summarize_file",
        }),
    }
    parent_snapshot = dict(parent_env)
    mcp._merge_escalation_ledger_extra_env(
        parent_env,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="test",
        escalation_from_profile="p1",
        escalation_to_profile="p2",
        escalation_depth=1,
        parent_request_id="r",
    )
    assert parent_env == parent_snapshot


def test_merge_escalation_does_not_mutate_os_environ():
    snapshot = dict(os.environ)
    mcp._merge_escalation_ledger_extra_env(
        None,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="test",
        escalation_from_profile="p1",
        escalation_to_profile="p2",
        escalation_depth=1,
        parent_request_id="r",
    )
    assert dict(os.environ) == snapshot


def test_merge_escalation_json_deterministic():
    a = mcp._merge_escalation_ledger_extra_env(
        None,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="test",
        escalation_from_profile="p1",
        escalation_to_profile="p2",
        escalation_depth=1,
        parent_request_id="r",
    )
    b = mcp._merge_escalation_ledger_extra_env(
        None,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="test",
        escalation_from_profile="p1",
        escalation_to_profile="p2",
        escalation_depth=1,
        parent_request_id="r",
    )
    assert a["LOCAL_LLM_LEDGER_EXTRA"] == b["LOCAL_LLM_LEDGER_EXTRA"]


def test_merge_escalation_all_fields_present():
    env = mcp._merge_escalation_ledger_extra_env(
        None,
        auto_escalated=True,
        escalation_trigger="low_confidence",
        escalation_reason="test",
        escalation_from_profile="p1",
        escalation_to_profile="p2",
        escalation_depth=1,
        parent_request_id="r",
    )
    payload = _parse_env(env)
    assert set(payload.keys()) == {
        "auto_escalated",
        "escalation_trigger",
        "escalation_reason",
        "escalation_from_profile",
        "escalation_to_profile",
        "escalation_depth",
        "parent_request_id",
    }


# --------------------------------------------------------------------------- #
# 3. _wrap_worker_call integration — monkeypatch                            #
# --------------------------------------------------------------------------- #


def _patch_for_escalation(monkeypatch, payload_overrides=None):
    """Patch run_subprocess, load_worker_output, and _check_quality_escalation
    to trigger a controlled escalation.  Returns (captured, fake_payload).

    ``captured`` accumulates kwargs from every run_subprocess call so the
    test can inspect the child invocation's extra_env.
    """
    captured = {"calls": [], "extra_envs": []}

    fake_payload = _success_payload(**(payload_overrides or {}))
    escalated_payload = _success_payload(
        profile="smart_summary", model="gemma4:9b",
    )

    call_count = [0]

    def _capture_run(cmd, **kwargs):
        captured["calls"].append(list(cmd))
        captured["extra_envs"].append(kwargs.get("extra_env"))
        call_count[0] += 1
        # First call: the "poor quality" parent result
        if call_count[0] == 1:
            return {
                "ok": True, "stdout": "JSON: /fake/parent.json",
                "stderr": "", "returncode": 0, "elapsed_seconds": 1.0,
            }
        # Second call: the escalated child result (success)
        return {
            "ok": True, "stdout": "JSON: /fake/child.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 2.0,
        }

    def _load_output(stdout):
        if "parent" in stdout:
            return (fake_payload, None)
        return (escalated_payload, None)

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(mcp, "load_worker_output", _load_output)

    return captured, fake_payload


def test_wrap_worker_call_low_confidence_stamps_child_extra_env(monkeypatch):
    captured, _ = _patch_for_escalation(monkeypatch, {
        "confidence": "low",
    })

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    # Should have two calls: parent + escalation child
    assert len(captured["calls"]) == 2

    child_env = captured["extra_envs"][1]
    assert child_env is not None
    payload = _parse_env(child_env)
    assert payload["auto_escalated"] is True
    assert payload["escalation_trigger"] == "low_confidence"
    assert payload["escalation_from_profile"] == "fast_summary"
    assert payload["escalation_to_profile"] == "smart_summary"
    assert payload["escalation_depth"] == 1
    assert "parent_request_id" in payload


def test_wrap_worker_call_uncertain_points_stamps_child_extra_env(monkeypatch):
    captured, _ = _patch_for_escalation(monkeypatch, {
        "uncertain_points": ["a", "b", "c", "d"],
    })

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    assert len(captured["calls"]) == 2
    child_env = captured["extra_envs"][1]
    payload = _parse_env(child_env)
    assert payload["escalation_trigger"] == "uncertain_points"
    assert payload["auto_escalated"] is True


def test_wrap_worker_call_child_inherits_mcp_fields(monkeypatch):
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    mcp._wrap_worker_call(
        "local_generate_test_plan", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_generate_test_plan"),
    )

    child_env = captured["extra_envs"][1]
    payload = _parse_env(child_env)
    assert payload["mcp_tool_name"] == "local_generate_test_plan"
    assert payload["source"] == "manual-mcp"
    assert "commit_gate" not in payload  # this tool doesn't stamp it


def test_wrap_worker_call_child_inherits_commit_gate(monkeypatch):
    """When parent has commit_gate=False, child must retain it."""
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    mcp._wrap_worker_call(
        "local_review_diff", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_review_diff", commit_gate=False),
    )

    child_env = captured["extra_envs"][1]
    payload = _parse_env(child_env)
    assert payload["commit_gate"] is False
    assert payload["escalation_trigger"] == "low_confidence"


def test_wrap_worker_call_parent_extra_env_not_mutated(monkeypatch):
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    parent_env = mcp._build_ledger_extra_env(
        mcp_tool_name="local_summarize_file")
    parent_snapshot = dict(parent_env)

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=parent_env,
    )

    assert parent_env == parent_snapshot


def test_wrap_worker_call_parent_call_has_no_escalation_fields(monkeypatch):
    """Parent (first) subprocess must NOT carry escalation fields."""
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    parent_env = captured["extra_envs"][0]
    assert parent_env is not None
    payload = _parse_env(parent_env)
    assert "auto_escalated" not in payload
    assert "escalation_trigger" not in payload
    assert payload["mcp_tool_name"] == "local_summarize_file"


def test_wrap_worker_call_no_escalation_no_escalation_fields(monkeypatch):
    """When quality is good (no escalation), no escalation fields appear."""
    captured = {"calls": [], "extra_envs": []}

    def _capture_run(cmd, **kwargs):
        captured["calls"].append(list(cmd))
        captured["extra_envs"].append(kwargs.get("extra_env"))
        return {
            "ok": True, "stdout": "JSON: /fake/ok.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 1.0,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(
        mcp, "load_worker_output",
        lambda stdout: (_success_payload(confidence="medium"), None),
    )

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    assert len(captured["calls"]) == 1  # no escalation
    env = captured["extra_envs"][0]
    payload = _parse_env(env)
    assert "auto_escalated" not in payload
    assert "escalation_trigger" not in payload


def test_wrap_worker_call_max_depth_no_escalation(monkeypatch):
    """At _depth=2 (_MAX_ESCALATION_DEPTH), no further escalation."""
    captured = {"calls": [], "extra_envs": []}

    def _capture_run(cmd, **kwargs):
        captured["calls"].append(list(cmd))
        captured["extra_envs"].append(kwargs.get("extra_env"))
        return {
            "ok": True, "stdout": "JSON: /fake/depth.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 1.0,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(
        mcp, "load_worker_output",
        lambda stdout: (_success_payload(confidence="low"), None),
    )

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        _depth=2,
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    assert len(captured["calls"]) == 1


def test_wrap_worker_call_escalation_parent_request_id_traceable(monkeypatch):
    """child's parent_request_id is a valid request_id and differs from
    the child's own request_id (returned in result)."""
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    result = mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    child_env = captured["extra_envs"][1]
    payload = _parse_env(child_env)
    parent_req_id = payload["parent_request_id"]
    # parent_request_id must start with "req_" (valid format)
    assert parent_req_id.startswith("req_")
    # parent_request_id must differ from child's own request_id
    child_req_id = result.get("request_id")
    assert child_req_id is not None
    assert child_req_id != parent_req_id


def test_wrap_worker_call_escalation_reason_contains_context(monkeypatch):
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    child_env = captured["extra_envs"][1]
    payload = _parse_env(child_env)
    assert "confidence=low" in payload["escalation_reason"]
    assert "fast_summary" in payload["escalation_reason"]


def test_wrap_worker_call_child_has_unique_request_id(monkeypatch):
    """Parent and child must have different request_ids in their responses."""
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    # Capture the response from the first (parent) call pattern.
    # _wrap_worker_call returns the child's response (since child succeeds).
    # We can't get the parent response directly, but we can verify that
    # child's parent_request_id != child's own request_id by checking the
    # response structure.
    result = mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    child_env = captured["extra_envs"][1]
    payload = _parse_env(child_env)
    # child has its own request_id (in the result) and parent_request_id (in env)
    child_req_id = result.get("request_id")
    parent_req_id = payload["parent_request_id"]
    assert child_req_id != parent_req_id


def test_wrap_worker_call_no_escalation_failure_path(monkeypatch):
    """Non-timeout failure does NOT escalate (only success escalates)."""
    captured = {"calls": [], "extra_envs": []}

    def _capture_run(cmd, **kwargs):
        captured["calls"].append(list(cmd))
        captured["extra_envs"].append(kwargs.get("extra_env"))
        return {
            "ok": False, "stdout": "JSON: /fake/fail.json",
            "stderr": "model error", "returncode": 1,
            "elapsed_seconds": 1.0,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(
        mcp, "load_worker_output",
        lambda stdout: (_success_payload(confidence="low"), None),
    )

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
        extra_env=mcp._build_ledger_extra_env(
            mcp_tool_name="local_summarize_file"),
    )

    # Failure → no escalation, single call
    assert len(captured["calls"]) == 1


def test_wrap_worker_call_without_extra_env_still_escalates(monkeypatch):
    """Extra_env=None should not block escalation; child gets escalation fields."""
    captured, _ = _patch_for_escalation(monkeypatch, {"confidence": "low"})

    mcp._wrap_worker_call(
        "local_summarize_file", ["dummy"], task="summarize-file",
    )

    assert len(captured["calls"]) == 2
    child_env = captured["extra_envs"][1]
    assert child_env is not None
    payload = _parse_env(child_env)
    assert payload["auto_escalated"] is True
    assert payload["escalation_trigger"] == "low_confidence"
    # No parent stamp — child still gets escalation fields standalone
