"""Tests for preclassifier ledger contract (B1-B).

Covers: build_record with new fields, old record compatibility,
debate-skips CLI output (JSON/text), malformed safety_blockers,
and no source mutation.
"""

import argparse
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import call_ledger
import call_ledger_cli


# ---------------------------------------------------------------------------
# KNOWN_EXTRA_KEYS inclusion
# ---------------------------------------------------------------------------

class TestKnownExtraKeys:
    """Verify B1-B fields are in KNOWN_EXTRA_KEYS."""

    B1B_FIELDS = {
        "diff_risk_level",
        "diff_risk_confidence",
        "debate_skipped",
        "debate_skip_reason",
        "preclassifier_profile",
        "preclassifier_model",
        "preclassifier_request_id",
        "safety_blockers",
        "debate_skip_allowed",
        "skip_debate_recommended",
        "preclassifier_method",
        "changed_files_count",
    }

    def test_all_b1b_fields_in_known_extra_keys(self):
        missing = self.B1B_FIELDS - call_ledger.KNOWN_EXTRA_KEYS
        assert not missing, f"Missing from KNOWN_EXTRA_KEYS: {missing}"

    def test_existing_fields_still_present(self):
        legacy = {"mcp_tool_name", "commit_gate", "escalation_trigger",
                   "debate_mode", "review_necessity", "risk_level"}
        missing = legacy - call_ledger.KNOWN_EXTRA_KEYS
        assert not missing, f"Legacy fields accidentally removed: {missing}"


# ---------------------------------------------------------------------------
# build_record accepts new fields
# ---------------------------------------------------------------------------

class TestBuildRecordNewFields:
    """build_record must pass through B1-B fields in the extra dict."""

    def test_build_record_with_all_new_fields(self):
        extra = {
            "diff_risk_level": "low",
            "diff_risk_confidence": "high",
            "debate_skipped": True,
            "debate_skip_reason": "docs-only changes",
            "preclassifier_profile": "fast_summary",
            "preclassifier_model": "qwen3-coder:30b",
            "preclassifier_request_id": "req_test_123",
            "safety_blockers": [],
            "debate_skip_allowed": True,
            "skip_debate_recommended": True,
            "preclassifier_method": "heuristic",
            "changed_files_count": 2,
        }
        rec = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test-model",
            profile="test_profile",
            provider="ollama",
            extra=extra,
        )
        assert rec["extra"]["diff_risk_level"] == "low"
        assert rec["extra"]["diff_risk_confidence"] == "high"
        assert rec["extra"]["debate_skipped"] is True
        assert rec["extra"]["debate_skip_reason"] == "docs-only changes"
        assert rec["extra"]["preclassifier_profile"] == "fast_summary"
        assert rec["extra"]["preclassifier_model"] == "qwen3-coder:30b"
        assert rec["extra"]["preclassifier_request_id"] == "req_test_123"
        assert rec["extra"]["safety_blockers"] == []
        assert rec["extra"]["debate_skip_allowed"] is True
        assert rec["extra"]["skip_debate_recommended"] is True
        assert rec["extra"]["preclassifier_method"] == "heuristic"
        assert rec["extra"]["changed_files_count"] == 2

    def test_build_record_partial_fields(self):
        extra = {"diff_risk_level": "medium", "debate_skipped": False}
        rec = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test-model",
            profile="test",
            provider="ollama",
            extra=extra,
        )
        assert rec["extra"]["diff_risk_level"] == "medium"
        assert rec["extra"]["debate_skipped"] is False
        assert "debate_skip_reason" not in rec["extra"]

    def test_safety_blockers_as_list(self):
        extra = {"safety_blockers": ["mcp server touched", "auth file changed"]}
        rec = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test",
            profile="test",
            provider="ollama",
            extra=extra,
        )
        assert rec["extra"]["safety_blockers"] == ["mcp server touched", "auth file changed"]

    def test_safety_blockers_as_string(self):
        extra = {"safety_blockers": "single blocker"}
        rec = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test",
            profile="test",
            provider="ollama",
            extra=extra,
        )
        assert rec["extra"]["safety_blockers"] == "single blocker"


# ---------------------------------------------------------------------------
# Old record compatibility
# ---------------------------------------------------------------------------

class TestOldRecordCompatibility:
    """Old records without B1-B fields must still be readable and summarizable."""

    def _make_old_record(self):
        return call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test",
            profile="test",
            provider="ollama",
            extra={"mcp_tool_name": "local_review_diff"},
        )

    def _make_skip_record(self):
        return call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test",
            profile="preclassifier",
            provider="ollama",
            extra={
                "mcp_tool_name": "local_review_diff",
                "debate_skipped": True,
                "diff_risk_level": "low",
                "diff_risk_confidence": "high",
                "debate_skip_reason": "docs-only",
                "preclassifier_profile": "fast_summary",
                "debate_skip_allowed": True,
                "skip_debate_recommended": True,
                "changed_files_count": 2,
            },
        )

    def test_old_record_reads_and_summarizes(self):
        old = self._make_old_record()
        assert "diff_risk_level" not in old.get("extra", {})
        summary = call_ledger.summarize([old])
        assert summary["calls"] == 1

    def test_mixed_old_and_new_records(self):
        old = self._make_old_record()
        new = self._make_skip_record()
        summary = call_ledger.summarize([old, new])
        assert summary["calls"] == 2

    def test_filter_debate_skips_empty_on_old_records(self):
        old = self._make_old_record()
        skips = call_ledger.filter_debate_skips([old])
        assert skips == []

    def test_filter_debate_skips_finds_new_records(self):
        old = self._make_old_record()
        skipped = self._make_skip_record()
        skips = call_ledger.filter_debate_skips([old, skipped])
        assert len(skips) == 1
        assert skips[0]["extra"]["debate_skipped"] is True

    def test_summarize_debate_skips_counts_correctly(self):
        s1 = self._make_skip_record()
        s2 = self._make_skip_record()
        non = self._make_old_record()
        summary = call_ledger.summarize_debate_skips([s1, s2, non])
        assert summary["total_skipped"] == 2
        assert summary["estimated_debate_seconds_saved"] == 1000
        assert summary["estimated_tokens_saved"] == 200_000
        assert summary["by_risk_level"]["low"] == 2

    def test_summarize_debate_skips_zero_when_none(self):
        old = self._make_old_record()
        summary = call_ledger.summarize_debate_skips([old])
        assert summary["total_skipped"] == 0
        assert summary["estimated_debate_seconds_saved"] == 0
        assert summary["estimated_tokens_saved"] == 0


# ---------------------------------------------------------------------------
# debate-skips CLI
# ---------------------------------------------------------------------------

class TestDebateSkipsCLI:
    """Test debate-skips subcommand with a temp ledger file."""

    @pytest.fixture
    def tmp_ledger(self, tmp_path):
        """Create a temp ledger with 2 skip records and 1 non-skip record."""
        ledger_path = tmp_path / "calls.jsonl"
        # Non-skip record
        non_skip = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_review_diff",
            model="test-model",
            profile="commit_reviewer",
            provider="ollama",
            extra={"mcp_tool_name": "local_review_diff", "commit_gate": True},
        )
        # Skip records
        skip1 = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_debate_review_diff",
            model="qwen3-coder:30b",
            profile="fast_summary",
            provider="ollama",
            extra={
                "mcp_tool_name": "local_debate_review_diff",
                "debate_skipped": True,
                "diff_risk_level": "low",
                "diff_risk_confidence": "high",
                "debate_skip_reason": "docs-only changes",
                "preclassifier_profile": "fast_summary",
                "debate_skip_allowed": True,
                "skip_debate_recommended": True,
                "changed_files_count": 2,
            },
        )
        skip2 = call_ledger.build_record(
            task_type="review-diff",
            tool_name="local_debate_review_diff",
            model="qwen3-coder:30b",
            profile="fast_summary",
            provider="ollama",
            extra={
                "mcp_tool_name": "local_debate_review_diff",
                "debate_skipped": True,
                "diff_risk_level": "low",
                "diff_risk_confidence": "medium",
                "debate_skip_reason": "tests-only changes",
                "preclassifier_profile": "fast_summary",
                "debate_skip_allowed": True,
                "skip_debate_recommended": True,
                "changed_files_count": 1,
            },
        )
        non_skip_extra = call_ledger.build_record(
            task_type="summarize-file",
            tool_name="local_summarize_file",
            model="test",
            profile="fast_summary",
            provider="ollama",
            extra={"mcp_tool_name": "local_summarize_file"},
        )
        for rec in [non_skip, skip1, skip2, non_skip_extra]:
            call_ledger.record_call(rec, path=ledger_path)
        return ledger_path

    def test_json_output(self, tmp_ledger):
        """JSON output must have correct counts."""
        records = call_ledger.read_records(tmp_ledger)
        summary = call_ledger.summarize_debate_skips(records)
        assert summary["total_skipped"] == 2
        assert summary["estimated_debate_seconds_saved"] == 1000
        assert summary["estimated_tokens_saved"] == 200_000
        assert summary["by_risk_level"]["low"] == 2
        assert summary["by_confidence"]["high"] == 1
        assert summary["by_confidence"]["medium"] == 1

    def test_text_output_no_crash(self, tmp_ledger):
        """Text output must not crash."""
        records = call_ledger.read_records(tmp_ledger)
        summary = call_ledger.summarize_debate_skips(records)
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            call_ledger_cli._print_debate_skips(summary, "table")
            out = sys.stdout.getvalue()
            assert "2 total" in out
            assert "estimated debate seconds saved" in out
        finally:
            sys.stdout = old_stdout

    def test_json_output_no_crash(self, tmp_ledger):
        """JSON output must not crash."""
        records = call_ledger.read_records(tmp_ledger)
        summary = call_ledger.summarize_debate_skips(records)
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            call_ledger_cli._print_debate_skips(summary, "json")
            out = sys.stdout.getvalue()
            data = json.loads(out)
            assert data["total_skipped"] == 2
            assert "recent_skips" in data
            assert len(data["recent_skips"]) <= 5
        finally:
            sys.stdout = old_stdout

    def test_zero_skips_text(self, tmp_path):
        """Zero skips must print a clean message."""
        ledger_path = tmp_path / "empty.jsonl"
        ledger_path.write_text("", encoding="utf-8")
        records = call_ledger.read_records(ledger_path)
        summary = call_ledger.summarize_debate_skips(records)
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            call_ledger_cli._print_debate_skips(summary, "table")
            out = sys.stdout.getvalue()
            assert "none" in out.lower()
        finally:
            sys.stdout = old_stdout

    def test_zero_skips_json(self, tmp_path):
        """Zero skips in JSON must be valid."""
        ledger_path = tmp_path / "empty.jsonl"
        ledger_path.write_text("", encoding="utf-8")
        records = call_ledger.read_records(ledger_path)
        summary = call_ledger.summarize_debate_skips(records)
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            call_ledger_cli._print_debate_skips(summary, "json")
            out = sys.stdout.getvalue()
            data = json.loads(out)
            assert data["total_skipped"] == 0
        finally:
            sys.stdout = old_stdout

    def test_cli_entry_point(self, tmp_ledger):
        """cmd_debate_skips must return 0."""
        args = argparse.Namespace(path=str(tmp_ledger), format="json")
        rc = call_ledger_cli.cmd_debate_skips(args)
        assert rc == 0

    def test_subcommand_registered(self):
        """debate-skips must be a known subcommand."""
        parser = call_ledger_cli.build_parser()
        # Just check the subcommand is listed in choices
        subparsers = [a for a in parser._actions
                      if isinstance(a, argparse._SubParsersAction)]
        assert len(subparsers) == 1
        assert "debate-skips" in subparsers[0].choices


class TestDebateSkipsByRiskBreakdown:
    """Verify per-risk, per-confidence, per-profile breakdowns."""

    def test_mixed_risk_levels(self):
        extra_high = {"debate_skipped": True, "diff_risk_level": "high",
                       "debate_skip_reason": "for coverage"}
        extra_low1 = {"debate_skipped": True, "diff_risk_level": "low"}
        extra_low2 = {"debate_skipped": True, "diff_risk_level": "low"}
        extra_none = {"debate_skipped": True}

        recs = []
        for extra in [extra_high, extra_low1, extra_low2, extra_none]:
            recs.append(call_ledger.build_record(
                task_type="review-diff", tool_name="local_debate_review_diff",
                model="t", profile="t", provider="ollama", extra=extra,
            ))
        summary = call_ledger.summarize_debate_skips(recs)
        assert summary["total_skipped"] == 4
        assert summary["by_risk_level"]["high"] == 1
        assert summary["by_risk_level"]["low"] == 2
        assert summary["by_risk_level"]["unknown"] == 1

    def test_empty_extra_not_crashing(self):
        rec = call_ledger.build_record(
            task_type="review-diff", tool_name="local_review_diff",
            model="t", profile="t", provider="ollama",
        )
        # No extra at all
        assert call_ledger.filter_debate_skips([rec]) == []

    def test_filter_debate_skips_excludes_debate_mode_records(self):
        debate_rec = call_ledger.build_record(
            task_type="review-diff", tool_name="local_debate_review_diff",
            model="t", profile="t", provider="ollama",
            extra={"debate_mode": True, "debate_rounds": 3, "debate_round_index": 1},
        )
        skips = call_ledger.filter_debate_skips([debate_rec])
        assert skips == []


# ---------------------------------------------------------------------------
# No source mutation
# ---------------------------------------------------------------------------

class TestNoSourceMutation:
    def test_build_record_returns_new_dict(self):
        extra = {"diff_risk_level": "low"}
        rec = call_ledger.build_record(
            task_type="t", tool_name="t", model="t", profile="t",
            provider="ollama", extra=extra,
        )
        # Mutating the returned dict must not affect original extra
        rec["extra"]["diff_risk_level"] = "mutated"
        assert extra["diff_risk_level"] == "low"

    def test_filter_debate_skips_returns_new_dicts(self):
        rec = call_ledger.build_record(
            task_type="t", tool_name="t", model="t", profile="t",
            provider="ollama",
            extra={"debate_skipped": True},
        )
        filtered = call_ledger.filter_debate_skips([rec])
        assert filtered[0] is not rec
