"""Mock tests for tools/shadow_route_log.py — no DeepSeek API calls, no profile changes."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from shadow_route_log import log, list_records, stats, _auto_match, SHADOW_DIR


# ── Auto-match logic ──

def test_match_high_risk_pro():
    assert _auto_match("high", True, "pro-review") is True


def test_match_low_risk_local():
    assert _auto_match("low", False, "local-only") is True


def test_match_medium_flash():
    assert _auto_match("medium", True, "flash-fallback") is True


def test_match_blocked():
    assert _auto_match("medium", False, "cloud-blocked") is True


def test_match_no_actual():
    assert _auto_match("medium", True, "") is False


# ── JSONL record ──

def test_log_writes_jsonl(tmp_path, monkeypatch):
    """Log writes a valid JSONL record under the output dir."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")

    record = log("review current diff before commit", actual="local-first", notes="test")

    assert record["task"] == "review current diff before commit"
    assert record["actual_decision"] == "local-first"
    assert record["notes"] == "test"
    assert record["router_task_type"] == "review-diff"
    assert record["router_risk_level"] == "medium"
    assert record["router_privacy_status"] == "safe"
    assert "timestamp" in record
    assert record["match"] is True  # medium + local


def test_log_privacy_blocked_record(tmp_path, monkeypatch):
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    record = log("fix the API key sk-abc123 in .env", actual="local-only")
    assert record["router_privacy_status"] == "blocked"
    assert record["router_cloud_allowed"] is False
    assert record["match"] is True


def test_log_mismatch_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    record = log("prepare release gate", actual="local-only")
    assert record["router_risk_level"] == "high"
    assert record["match"] is False  # high risk but human chose local-only


def test_log_no_actual(tmp_path, monkeypatch):
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    record = log("review current diff")
    assert record["actual_decision"] == ""
    assert record["match"] is None


# ── Output path ──

def test_output_under_local_llm_out(tmp_path, monkeypatch):
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    log("test task")
    assert (tmp_path / "shadow_routes").exists()
    files = list((tmp_path / "shadow_routes").glob("*.jsonl"))
    assert len(files) == 1


# ── No DeepSeek call ──

def test_no_api_call():
    """Verify log() completes without network — pure in-process."""
    record = log("explain what this function does", actual="local")
    assert record["router_task_type"] is not None
    assert record["router_risk_level"] is not None


# ── List / Stats ──

def test_list_returns_records(tmp_path, monkeypatch):
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    log("task one", actual="local")
    log("task two", actual="flash")

    records = list_records(days=1)
    assert len(records) == 2
    assert records[0]["task"] in ("task one", "task two")


def test_stats_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    log("review diff", actual="local-first")       # medium + local → match
    log("release gate", actual="pro-review")        # high + pro → match
    log("release gate 2", actual="local-only")       # high + local → mismatch

    s = stats(days=1)
    assert s["total"] == 3
    assert s["matched"] == 2
    assert s["unmatched"] == 1
    assert s["accuracy"] == 0.667


def test_stats_empty():
    # Use a non-existent dir to guarantee empty
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        # patch SHADOW_DIR to empty temp dir
        import shadow_route_log
        old = shadow_route_log.SHADOW_DIR
        try:
            shadow_route_log.SHADOW_DIR = Path(td) / "nonexistent"
            s = stats()
            assert s == {"total": 0}
        finally:
            shadow_route_log.SHADOW_DIR = old
