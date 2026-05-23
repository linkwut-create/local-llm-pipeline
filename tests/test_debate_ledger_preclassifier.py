"""Tests for debate ledger preclassifier propagation (B1-C3).

Covers: env fields merging, authoritative field override,
debate_skipped forced false, malformed env, no-env backward compat.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_debate as debate


# ---------------------------------------------------------------------------
# _load_ledger_env_extra_for_debate
# ---------------------------------------------------------------------------

class TestLoadLedgerEnvExtra:
    def test_valid_env_returns_mergeable_fields(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
            "diff_risk_level": "low",
            "diff_risk_confidence": "high",
            "debate_skipped": False,
            "debate_skip_allowed": False,
            "skip_debate_recommended": True,
            "preclassifier_method": "heuristic",
            "preclassifier_profile": "fast_summary",
            "preclassifier_model": "none",
            "preclassifier_request_id": "req_123",
            "safety_blockers": [],
            "debate_skip_reason": "",
            "changed_files_count": 1,
            # These must NOT appear (debate-authoritative)
            "debate_mode": False,
            "debate_rounds": 99,
            "debate_round_index": 99,
            "debate_trigger": "evil",
            "mcp_tool_name": "evil_tool",
            "source": "evil_source",
        }, separators=(",", ":")))
        result = debate._load_ledger_env_extra_for_debate()
        assert result["diff_risk_level"] == "low"
        assert result["diff_risk_confidence"] == "high"
        assert result["debate_skipped"] is False
        assert result["debate_skip_allowed"] is False
        assert result["preclassifier_method"] == "heuristic"
        assert result["changed_files_count"] == 1
        # Debate-authoritative fields filtered out
        assert "debate_mode" not in result
        assert "debate_rounds" not in result
        assert "debate_round_index" not in result
        assert "debate_trigger" not in result
        assert "mcp_tool_name" not in result
        assert "source" not in result

    def test_empty_env_returns_empty_dict(self, monkeypatch):
        monkeypatch.delenv("LOCAL_LLM_LEDGER_EXTRA", raising=False)
        assert debate._load_ledger_env_extra_for_debate() == {}

    def test_malformed_json_returns_empty(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", "{bad json")
        assert debate._load_ledger_env_extra_for_debate() == {}

    def test_non_dict_returns_empty(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", '["x"]')
        assert debate._load_ledger_env_extra_for_debate() == {}

    def test_empty_string_returns_empty(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", "")
        assert debate._load_ledger_env_extra_for_debate() == {}

    def test_partial_fields_returned(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
            "diff_risk_level": "medium",
            "diff_risk_confidence": "low",
        }))
        result = debate._load_ledger_env_extra_for_debate()
        assert result["diff_risk_level"] == "medium"
        assert result["diff_risk_confidence"] == "low"
        assert "debate_skipped" not in result

    def test_none_values_filtered_out(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
            "diff_risk_level": None,
            "diff_risk_confidence": "high",
        }))
        result = debate._load_ledger_env_extra_for_debate()
        assert "diff_risk_level" not in result
        assert result["diff_risk_confidence"] == "high"

    def test_unknown_keys_ignored(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
            "unknown_field": "should_be_ignored",
            "diff_risk_level": "low",
        }))
        result = debate._load_ledger_env_extra_for_debate()
        assert "unknown_field" not in result
        assert result["diff_risk_level"] == "low"


# ---------------------------------------------------------------------------
# _emit_debate_round_ledger with env merging
# ---------------------------------------------------------------------------

class TestEmitDebateRoundLedgerMerging:
    """Verify env fields are merged and authoritative fields override."""

    def _build_env_with_dangerous_overrides(self):
        """Env that tries to override debate-authoritative fields AND
        set debate_skipped=true."""
        return json.dumps({
            "diff_risk_level": "low",
            "diff_risk_confidence": "high",
            "debate_skipped": True,
            "debate_skip_allowed": True,
            "preclassifier_method": "heuristic",
            "changed_files_count": 2,
            # Malicious overrides
            "debate_mode": False,
            "debate_rounds": 0,
            "debate_round_index": 999,
            "debate_trigger": "evil_trigger",
            "mcp_tool_name": "evil_mcp",
            "source": "evil_source",
        }, separators=(",", ":"))

    def test_authoritative_fields_cannot_be_overridden(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA",
                           self._build_env_with_dangerous_overrides())

        captured_extra = None

        def capture(rec):
            nonlocal captured_extra
            captured_extra = rec.get("extra", {})

        monkeypatch.setattr(debate, "_ledger_record", capture)
        # _ledger_build is the real function
        assert debate._ledger_build is not None

        debate._emit_debate_round_ledger(
            task_type="debate-review-diff",
            profile="test",
            provider="ollama",
            model="test-model",
            success=True,
            elapsed_seconds=1.0,
            input_text="input",
            output_text="output",
            usage=None,
            error=None,
            debate_round_index=2,
            debate_rounds=3,
            debate_trigger="manual-mcp",
        )

        assert captured_extra is not None
        # Debate authoritative fields preserved
        assert captured_extra["debate_mode"] is True
        assert captured_extra["debate_rounds"] == 3
        assert captured_extra["debate_round_index"] == 2
        assert captured_extra["debate_trigger"] == "manual-mcp"
        assert captured_extra["mcp_tool_name"] == "local_debate_review_diff"
        assert captured_extra["source"] == "manual-mcp"
        # Preclassifier fields merged
        assert captured_extra["diff_risk_level"] == "low"
        assert captured_extra["diff_risk_confidence"] == "high"
        assert captured_extra["preclassifier_method"] == "heuristic"
        assert captured_extra["changed_files_count"] == 2

    def test_debate_skipped_forced_false(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA",
                           self._build_env_with_dangerous_overrides())

        captured_extra = None

        def capture(rec):
            nonlocal captured_extra
            captured_extra = rec.get("extra", {})

        monkeypatch.setattr(debate, "_ledger_record", capture)

        debate._emit_debate_round_ledger(
            task_type="debate-review-diff",
            profile="test",
            provider="ollama",
            model="test-model",
            success=True,
            elapsed_seconds=1.0,
            input_text="input",
            output_text="output",
            usage=None,
            error=None,
            debate_round_index=1,
            debate_rounds=2,
            debate_trigger="manual-mcp",
        )

        assert captured_extra["debate_skipped"] is False
        assert captured_extra["debate_skip_allowed"] is False

    def test_no_env_preserves_behavior(self, monkeypatch):
        monkeypatch.delenv("LOCAL_LLM_LEDGER_EXTRA", raising=False)

        captured_extra = None

        def capture(rec):
            nonlocal captured_extra
            captured_extra = rec.get("extra", {})

        monkeypatch.setattr(debate, "_ledger_record", capture)

        debate._emit_debate_round_ledger(
            task_type="debate-review-diff",
            profile="test",
            provider="ollama",
            model="test-model",
            success=True,
            elapsed_seconds=1.0,
            input_text="input",
            output_text="output",
            usage=None,
            error=None,
            debate_round_index=1,
            debate_rounds=2,
            debate_trigger="cli",
        )

        # Core debate fields always present
        assert captured_extra["debate_mode"] is True
        assert captured_extra["debate_rounds"] == 2
        assert captured_extra["debate_round_index"] == 1
        assert captured_extra["debate_trigger"] == "cli"
        # B1-C3 invariants
        assert captured_extra["debate_skipped"] is False
        assert captured_extra["debate_skip_allowed"] is False
        # No preclassifier fields present (no env set)
        assert "diff_risk_level" not in captured_extra

    def test_empty_env_does_not_add_fields(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", "")

        captured_extra = None

        def capture(rec):
            nonlocal captured_extra
            captured_extra = rec.get("extra", {})

        monkeypatch.setattr(debate, "_ledger_record", capture)

        debate._emit_debate_round_ledger(
            task_type="debate-review-diff",
            profile="test",
            provider="ollama",
            model="test-model",
            success=True,
            elapsed_seconds=1.0,
            input_text="input",
            output_text="output",
            usage=None,
            error=None,
            debate_round_index=1,
            debate_rounds=2,
            debate_trigger="cli",
        )

        assert "diff_risk_level" not in captured_extra

    def test_ledger_failure_never_raises(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA",
                           self._build_env_with_dangerous_overrides())

        def crash(*args, **kwargs):
            raise RuntimeError("simulated ledger crash")

        monkeypatch.setattr(debate, "_ledger_record", crash)

        # Must not raise
        debate._emit_debate_round_ledger(
            task_type="debate-review-diff",
            profile="test",
            provider="ollama",
            model="test-model",
            success=True,
            elapsed_seconds=1.0,
            input_text="input",
            output_text="output",
            usage=None,
            error=None,
            debate_round_index=1,
            debate_rounds=2,
            debate_trigger="cli",
        )

    def test_ledger_unavailable_no_crash(self, monkeypatch):
        monkeypatch.setattr(debate, "_ledger_build", None)
        monkeypatch.setattr(debate, "_ledger_record", None)

        # Must not raise
        debate._emit_debate_round_ledger(
            task_type="debate-review-diff",
            profile="test",
            provider="ollama",
            model="test-model",
            success=True,
            elapsed_seconds=1.0,
            input_text="input",
            output_text="output",
            usage=None,
            error=None,
            debate_round_index=1,
            debate_rounds=2,
            debate_trigger="cli",
        )


# ---------------------------------------------------------------------------
# Mock round ledger emission through run_round
# ---------------------------------------------------------------------------

class TestRunRoundLedgerPropagation:
    """Verify run_round passes preclassifier fields through to ledger."""

    def _fake_call_model(self, system, user, config):
        """Return a minimal fake ModelCallResult."""
        class FakeResult:
            content = "ok"
            usage = {"input_tokens": 10, "output_tokens": 5}
        return FakeResult()

    def test_run_round_ledger_includes_env_fields(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
            "diff_risk_level": "low",
            "diff_risk_confidence": "high",
            "debate_skipped": False,
            "debate_skip_allowed": False,
            "preclassifier_method": "heuristic",
            "changed_files_count": 1,
        }, separators=(",", ":")))

        captured_extra = None

        def capture(rec):
            nonlocal captured_extra
            captured_extra = rec.get("extra", {})

        monkeypatch.setattr(debate, "_ledger_record", capture)
        monkeypatch.setattr(debate, "call_model", self._fake_call_model)

        profiles = {"test_profile": {"model": "test-model", "max_output_chars": 100}}
        debate.run_round(
            round_num=1,
            task="review-diff",
            original_input="test input",
            prior_outputs=[],
            profile_name="test_profile",
            profiles=profiles,
            provider="ollama",
            timeout=5,
            max_output_chars=100,
            total_rounds=2,
            debate_trigger="manual-mcp",
        )

        assert captured_extra is not None
        assert captured_extra.get("diff_risk_level") == "low"
        assert captured_extra.get("diff_risk_confidence") == "high"
        assert captured_extra.get("preclassifier_method") == "heuristic"
        assert captured_extra.get("changed_files_count") == 1
        assert captured_extra.get("debate_skipped") is False
        assert captured_extra.get("debate_skip_allowed") is False
        # Debate fields preserved
        assert captured_extra.get("debate_mode") is True
        assert captured_extra.get("debate_rounds") == 2
        assert captured_extra.get("debate_round_index") == 1
