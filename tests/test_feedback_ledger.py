"""Tests for Z-4: cross-project feedback ledger.

All tests use synthetic temp JSONL files — no real ledger dependency.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(SCRIPT_DIR))

import feedback_ledger as fb


# ── Helpers ───────────────────────────────────────────────────────────

def _make_record(**overrides) -> dict:
    r = {
        "target_project": "local-translator-agent",
        "suggestion_type": "review_flag",
        "suggestion_summary": "duplicated import in tm_service.py",
        "disposition": "accepted",
    }
    r.update(overrides)
    return fb.build_record(**r)


# ── Record validation ──────────────────────────────────────────────────

class TestValidateRecord:
    def test_valid_record(self):
        r = fb.build_record(
            target_project="test-project",
            suggestion_type="review_flag",
            suggestion_summary="a valid entry",
            disposition="accepted",
        )
        ok, errors = fb.validate_record(r)
        assert ok
        assert not errors

    def test_missing_required_fields(self):
        r = fb.build_record(
            target_project="",
            suggestion_type="review_flag",
            suggestion_summary="",
            disposition="",
        )
        r["target_project"] = ""
        r["suggestion_summary"] = ""
        r["disposition"] = ""
        ok, errors = fb.validate_record(r)
        assert not ok
        assert any("target_project" in e for e in errors)
        assert any("suggestion_summary" in e for e in errors)
        assert any("disposition" in e for e in errors)

    def test_invalid_disposition(self):
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary="summary",
            disposition="bogus",
        )
        ok, errors = fb.validate_record(r)
        assert not ok
        assert any("disposition" in e for e in errors)

    def test_invalid_suggestion_type(self):
        r = fb.build_record(
            target_project="test",
            suggestion_type="not_a_type",
            suggestion_summary="summary",
            disposition="accepted",
        )
        ok, errors = fb.validate_record(r)
        assert not ok
        assert any("suggestion_type" in e for e in errors)

    def test_all_valid_dispositions(self):
        for d in fb.VALID_DISPOSITIONS:
            r = fb.build_record(
                target_project="test", suggestion_type="docs_gap",
                suggestion_summary="s", disposition=d)
            ok, _ = fb.validate_record(r)
            assert ok, f"disposition {d} should be valid"

    def test_all_valid_suggestion_types(self):
        for st in fb.VALID_SUGGESTION_TYPES:
            r = fb.build_record(
                target_project="test", suggestion_type=st,
                suggestion_summary="s", disposition="deferred")
            ok, _ = fb.validate_record(r)
            assert ok, f"suggestion_type {st} should be valid"


# ── Record creation ───────────────────────────────────────────────────

class TestBuildRecord:
    def test_has_required_top_level_fields(self):
        r = _make_record()
        assert "id" in r
        assert r["id"].startswith("fb_")
        assert "timestamp" in r
        assert "source_project" in r
        assert "target_project" in r
        assert "source_commit" in r
        assert "disposition" in r
        assert "suggestion_type" in r
        assert "suggestion_summary" in r

    def test_id_is_unique(self):
        ids = {_make_record()["id"] for _ in range(20)}
        assert len(ids) == 20

    def test_custom_fields_preserved(self):
        r = fb.build_record(
            target_project="local-durable-agent",
            suggestion_type="baseline_audit",
            suggestion_summary="audit finding",
            disposition="converted_to_fix",
            evidence="commit abc1234 fixed it",
            target_commit="abc1234",
            feedback_impact="docs",
            controller_notes="verified manually",
        )
        assert r["evidence"] == "commit abc1234 fixed it"
        assert r["target_commit"] == "abc1234"
        assert r["feedback_impact"] == "docs"


# ── Privacy / sanitization ─────────────────────────────────────────────

class TestPrivacy:
    def test_api_key_redacted(self):
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary="summary",
            disposition="accepted",
            controller_notes="token=sk-abc123def4567890ghijklmnopqrstuvwxyz",
        )
        assert "sk-" not in r.get("controller_notes", "")

    def test_private_key_pattern_redacted(self):
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary="summary",
            disposition="accepted",
            evidence="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAA...",
        )
        assert "PRIVATE KEY" not in r.get("evidence", "")

    def test_suggestion_summary_truncated(self):
        long_text = "x" * 500
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary=long_text,
            disposition="accepted",
        )
        assert len(r["suggestion_summary"]) <= 300

    def test_controller_notes_truncated(self):
        long_text = "y" * 600
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary="summary",
            disposition="accepted",
            controller_notes=long_text,
        )
        assert len(r["controller_notes"]) <= 500

    def test_forbidden_top_level_key_rejected(self):
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary="summary",
            disposition="accepted",
        )
        r["api_key"] = "secret123"
        clean = fb._sanitize_record(r)
        assert "api_key" not in clean
        assert "_redacted_keys" in clean


# ── JSONL I/O ──────────────────────────────────────────────────────────

class TestJSONLIO:
    def test_record_and_read(self, tmp_path):
        p = tmp_path / "feedback.jsonl"
        r = _make_record()
        ok, msg = fb.record_feedback(r, p)
        assert ok
        records = fb.read_feedback(p)
        assert len(records) == 1
        assert records[0]["id"] == r["id"]

    def test_append_multiple(self, tmp_path):
        p = tmp_path / "feedback.jsonl"
        fb.record_feedback(_make_record(), p)
        fb.record_feedback(_make_record(target_project="other"), p)
        fb.record_feedback(_make_record(disposition="false_positive"), p)
        records = fb.read_feedback(p)
        assert len(records) == 3

    def test_empty_ledger(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        records = fb.read_feedback(p)
        assert records == []

    def test_malformed_lines_tolerated(self, tmp_path):
        p = tmp_path / "feedback.jsonl"
        r = _make_record()
        ok, _ = fb.record_feedback(r, p)
        assert ok
        # Append garbage between valid records
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("not valid json\n")
            fh.write("\n")
        fb.record_feedback(_make_record(target_project="other"), p)
        records = fb.read_feedback(p)
        assert len(records) == 2

    def test_validation_blocks_write(self, tmp_path):
        p = tmp_path / "feedback.jsonl"
        r = fb.build_record(
            target_project="test",
            suggestion_type="review_flag",
            suggestion_summary="summary",
            disposition="invalid_disposition",
        )
        ok, msg = fb.record_feedback(r, p)
        assert not ok
        assert "validation failed" in msg
        assert not p.exists() or p.stat().st_size == 0


# ── Summary ────────────────────────────────────────────────────────────

class TestSummary:
    def test_empty_summary(self):
        s = fb.summarize_feedback([])
        assert s["total_entries"] == 0
        assert s["by_disposition"] == {}
        assert s["by_suggestion_type"] == {}
        assert s["by_target_project"] == {}

    def test_counts_dispositions(self):
        records = [
            _make_record(disposition="accepted"),
            _make_record(disposition="accepted"),
            _make_record(disposition="false_positive"),
            _make_record(disposition="converted_to_fix"),
        ]
        s = fb.summarize_feedback(records)
        assert s["total_entries"] == 4
        assert s["by_disposition"]["accepted"] == 2
        assert s["by_disposition"]["false_positive"] == 1
        assert s["by_disposition"]["converted_to_fix"] == 1

    def test_counts_suggestion_types(self):
        records = [
            _make_record(suggestion_type="review_flag"),
            _make_record(suggestion_type="review_flag"),
            _make_record(suggestion_type="docs_gap"),
        ]
        s = fb.summarize_feedback(records)
        assert s["by_suggestion_type"]["review_flag"] == 2
        assert s["by_suggestion_type"]["docs_gap"] == 1

    def test_counts_target_projects(self):
        records = [
            _make_record(target_project="local-translator-agent"),
            _make_record(target_project="local-llm-pipeline"),
            _make_record(target_project="local-translator-agent"),
        ]
        s = fb.summarize_feedback(records)
        assert s["by_target_project"]["local-translator-agent"] == 2
        assert s["by_target_project"]["local-llm-pipeline"] == 1


# ── By-target ──────────────────────────────────────────────────────────

class TestByTarget:
    def test_empty(self):
        buckets = fb.by_target([])
        assert buckets == {}

    def test_groups_by_target(self):
        records = [
            _make_record(target_project="local-translator-agent",
                          disposition="converted_to_fix"),
            _make_record(target_project="local-translator-agent",
                          disposition="accepted"),
            _make_record(target_project="local-durable-agent",
                          disposition="deferred"),
        ]
        buckets = fb.by_target(records)
        assert buckets["local-translator-agent"]["total"] == 2
        assert buckets["local-translator-agent"]["by_disposition"]["converted_to_fix"] == 1
        assert buckets["local-durable-agent"]["total"] == 1

    def test_sorted_by_total_desc(self):
        records = [
            _make_record(target_project="a"),
            _make_record(target_project="c"),
            _make_record(target_project="c"),
            _make_record(target_project="b"),
            _make_record(target_project="c"),
        ]
        buckets = fb.by_target(records)
        keys = list(buckets.keys())
        assert keys[0] == "c"
        assert buckets["c"]["total"] == 3


# ── CLI integration ────────────────────────────────────────────────────

class TestCLI:
    def test_record_and_summary(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        rc = fb.main([
            "--path", str(p), "--format", "json",
            "record",
            "--target-project", "test-project",
            "--suggestion-type", "docs_gap",
            "--suggestion-summary", "missing README section",
            "--disposition", "deferred",
        ])
        assert rc == 0
        records = fb.read_feedback(p)
        assert len(records) == 1
        assert records[0]["target_project"] == "test-project"

    def test_record_invalid_disposition_rejected(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        rc = fb.main([
            "--path", str(p), "--format", "json",
            "record",
            "--target-project", "test",
            "--suggestion-type", "review_flag",
            "--suggestion-summary", "summary",
            "--disposition", "nonsense",
        ])
        assert rc == 1

    def test_summary_json(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        from unittest.mock import patch
        import io
        save_io = io.StringIO()
        with patch("sys.stdout", save_io):
            rc = fb.main(["--path", str(p), "--format", "json", "summary"])
        assert rc == 0
        data = json.loads(save_io.getvalue())
        assert data["total_entries"] == 0

    def test_by_target_json(self, tmp_path):
        p = tmp_path / "fb.jsonl"
        from unittest.mock import patch
        import io
        save_io = io.StringIO()
        with patch("sys.stdout", save_io):
            rc = fb.main(["--path", str(p), "--format", "json", "by-target"])
        assert rc == 0
        data = json.loads(save_io.getvalue())
        assert data == {}


# ── Boundary invariants ────────────────────────────────────────────────

class TestBoundaries:
    def test_no_mcp_import(self):
        source = (SCRIPT_DIR / "feedback_ledger.py").read_text(encoding="utf-8")
        assert "local_llm_mcp_server" not in source
        assert "TOOLS" not in source
        assert "TOOL_HANDLERS" not in source

    def test_no_hook_import(self):
        source = (SCRIPT_DIR / "feedback_ledger.py").read_text(encoding="utf-8")
        assert "claude_hooks" not in source
        assert "mcp_gate" not in source

    def test_valid_dispositions_set(self):
        assert fb.VALID_DISPOSITIONS == frozenset({
            "accepted", "rejected", "false_positive", "converted_to_fix", "deferred",
        })

    def test_valid_suggestion_types_set(self):
        assert "review_flag" in fb.VALID_SUGGESTION_TYPES
        assert "quality_finding" in fb.VALID_SUGGESTION_TYPES
        assert len(fb.VALID_SUGGESTION_TYPES) == 8

    def test_output_dir_is_under_local_llm_out(self):
        assert ".local_llm_out" in str(fb.FEEDBACK_DIR)
        assert "feedback" in str(fb.FEEDBACK_DIR)
