"""P2-C3.1 — debate round ledger emission.

Covers:

1. ``_emit_debate_round_ledger`` ledger helper — success / failure / usage.
2. ``run_round()`` integration — captures ``ModelCallResult`` fully,
   writes one ledger record per round, does not change return shape.
3. Output format unchanged — no ledger metadata in return dict or stdout.

Does not invoke real models — monkeypatches ``call_model``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import local_llm_debate as debate  # noqa: E402
from model_call_result import ModelCallResult  # noqa: E402


# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# ---------------------------------------------------------------------------


def _stub_profiles() -> dict:
    return {
        "qwen3.6_27b_mtp": {"model": "qwen3.6:27b-q8-ud", "max_output_chars": 8000},
        "reasoning_checker": {
            "model": "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-q8_k_xl:latest",
            "max_output_chars": 8000,
        },
        "qwen3.6_35b_moe_mtp": {"model": "qwen3.6:35b-q8-ud", "max_output_chars": 8000},
    }


_UNSET = object()


def _fake_model_result(content="review result", usage=_UNSET):
    if usage is _UNSET:
        usage = {"input_tokens": 100, "output_tokens": 50}
    return ModelCallResult(content=content, usage=usage, raw_provider="ollama")


# --------------------------------------------------------------------------- #
# 1. Success record                                                           #
# --------------------------------------------------------------------------- #


def test_run_round_writes_ledger_on_success(monkeypatch):
    captured = []

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("review ok"))

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    monkeypatch.setattr(debate, "_ledger_record", _capture)
    monkeypatch.setattr(debate, "_ledger_build", lambda **kw: {"mock": True})
    # Override with real build_record so extra is populated
    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)

    result = debate.run_round(
        round_num=1, task="review-diff", original_input="diff content",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
        total_rounds=3, debate_trigger="manual-mcp",
    )

    assert result["ok"] is True
    assert result["round"] == 1
    assert len(captured) == 1
    rec = captured[0]
    assert rec["success"] is True
    assert rec["task_type"] == "debate-review-diff"
    assert rec["tool_name"] == "local_debate_review_diff"
    assert rec["profile"] == "qwen3.6_27b_mtp"
    assert rec["model"] == "qwen3.6:27b-q8-ud"
    assert rec["provider"] == "ollama"
    assert rec["input_tokens"] == 100
    assert rec["output_tokens"] == 50
    extra = rec.get("extra") or {}
    assert extra.get("debate_mode") is True
    assert extra.get("debate_rounds") == 3
    assert extra.get("debate_round_index") == 1
    assert extra.get("debate_trigger") == "manual-mcp"
    assert extra.get("mcp_tool_name") == "local_debate_review_diff"
    assert extra.get("source") == "manual-mcp"


def test_run_round_ledger_has_input_output_chars(monkeypatch):
    captured = []

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("OK"))

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    debate.run_round(
        round_num=2, task="review-diff", original_input="x" * 100,
        prior_outputs=["prev"], profile_name="reasoning_checker",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )

    assert len(captured) == 1
    rec = captured[0]
    assert rec["input_chars"] > 0
    assert rec["output_chars"] == 2  # "OK"


# --------------------------------------------------------------------------- #
# 2. Failure record                                                           #
# --------------------------------------------------------------------------- #


def test_run_round_writes_ledger_on_failure(monkeypatch):
    captured = []

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: (_ for _ in ()).throw(RuntimeError("boom")))

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    result = debate.run_round(
        round_num=1, task="review-diff", original_input="diff",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )

    assert result["ok"] is False
    assert "boom" in result["error"]
    assert len(captured) == 1
    rec = captured[0]
    assert rec["success"] is False
    assert rec["failure_reason"] is not None
    assert "boom" in rec["failure_reason"]
    assert rec["output_chars"] == 0


# --------------------------------------------------------------------------- #
# 3. No duplicate records                                                     #
# --------------------------------------------------------------------------- #


def test_run_round_exactly_one_record_call(monkeypatch):
    call_count = [0]

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("ok"))

    def _capture(rec, path=None):
        call_count[0] += 1
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert call_count[0] == 1

    # Failure path also exactly one call
    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: (_ for _ in ()).throw(ValueError("fail")))
    call_count[0] = 0
    debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert call_count[0] == 1


# --------------------------------------------------------------------------- #
# 4. Usage fallback                                                           #
# --------------------------------------------------------------------------- #


def test_run_round_usage_none_fallback(monkeypatch):
    """When ModelCallResult.usage is None, ledger falls back to chars//4."""
    captured = []

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("text", usage=None))

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    debate.run_round(
        round_num=1, task="review-diff", original_input="x" * 100,
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert len(captured) == 1
    rec = captured[0]
    # With usage=None, build_record uses chars//4 estimation
    assert rec["tokens_estimated"] is True


def test_run_round_usage_missing_attribute(monkeypatch):
    """ModelCallResult without .usage attribute still works (defensive)."""
    captured = []

    class BareResult:
        content = "result"

    monkeypatch.setattr(debate, "call_model", lambda s, u, c: BareResult())

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    result = debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert result["ok"] is True
    assert len(captured) == 1


# --------------------------------------------------------------------------- #
# 5. Ledger failure does not break debate                                     #
# --------------------------------------------------------------------------- #


def test_ledger_failure_does_not_break_debate(monkeypatch):
    def _crash(*args, **kwargs):
        raise RuntimeError("ledger disk full")

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("good output"))
    monkeypatch.setattr(debate, "_ledger_record", _crash)
    # _ledger_build still works so _emit_debate_round_ledger can reach
    # _ledger_record (which then raises).
    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)

    result = debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert result["ok"] is True
    assert result["raw_output"] == "good output"

    # Failure path with ledger crash
    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: (_ for _ in ()).throw(ValueError("model error")))
    result = debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert result["ok"] is False
    assert "model error" in result["error"]


# --------------------------------------------------------------------------- #
# 6. Output format unchanged                                                  #
# --------------------------------------------------------------------------- #


_RUN_ROUND_RETURN_KEYS = {"round", "profile", "model", "summary",
                           "raw_output", "elapsed_seconds", "ok", "error"}


def test_run_round_return_keys_on_success(monkeypatch):
    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("ok output"))

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)

    result = debate.run_round(
        round_num=2, task="risk-analysis", original_input="input",
        prior_outputs=["r1"], profile_name="reasoning_checker",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert set(result.keys()) == _RUN_ROUND_RETURN_KEYS
    assert result["ok"] is True
    assert result["raw_output"] == "ok output"
    assert result["summary"] == "ok output"


def test_run_round_return_keys_on_failure(monkeypatch):
    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: (_ for _ in ()).throw(RuntimeError("fail")))

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)

    result = debate.run_round(
        round_num=3, task="architecture-review", original_input="input",
        prior_outputs=["r1", "r2"], profile_name="qwen3.6_35b_moe_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert set(result.keys()) == _RUN_ROUND_RETURN_KEYS
    assert result["ok"] is False
    assert "fail" in result["error"]


# --------------------------------------------------------------------------- #
# 7. Multi-debate round variation                                             #
# --------------------------------------------------------------------------- #


def test_different_round_index_and_total(monkeypatch):
    captured = []

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("r2 result"))

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    debate.run_round(
        round_num=2, task="review-diff", original_input="diff",
        prior_outputs=["r1 output"], profile_name="reasoning_checker",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
        total_rounds=2, debate_trigger="auto-escalate",
    )
    extra = (captured[0].get("extra") or {})
    assert extra.get("debate_rounds") == 2
    assert extra.get("debate_round_index") == 2
    assert extra.get("debate_trigger") == "auto-escalate"
    assert extra.get("source") == "auto-escalate"


def test_debate_trigger_default_cli(monkeypatch):
    captured = []

    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("ok"))

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    import call_ledger
    monkeypatch.setattr(debate, "_ledger_build", call_ledger.build_record)
    monkeypatch.setattr(debate, "_ledger_record", _capture)

    debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    extra = (captured[0].get("extra") or {})
    assert extra.get("debate_trigger") == "cli"


# --------------------------------------------------------------------------- #
# 8. Legacy callers (no total_rounds / debate_trigger kwargs)                 #
# --------------------------------------------------------------------------- #


def test_run_round_backward_compat_no_new_kwargs(monkeypatch):
    """Callers that don't pass total_rounds/debate_trigger still work."""
    monkeypatch.setattr(debate, "call_model",
                        lambda s, u, c: _fake_model_result("ok"))

    result = debate.run_round(
        round_num=1, task="review-diff", original_input="x",
        prior_outputs=[], profile_name="qwen3.6_27b_mtp",
        profiles=_stub_profiles(), provider="ollama", timeout=60,
        max_output_chars=5000,
    )
    assert result["ok"] is True
    assert result["raw_output"] == "ok"
