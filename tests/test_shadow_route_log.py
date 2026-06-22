"""Mock tests for tools/shadow_route_log.py — no DeepSeek API calls, no profile changes."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from shadow_route_log import log, list_records, stats, _auto_match, SHADOW_DIR


@pytest.fixture(autouse=True)
def _isolated_shadow_dir(tmp_path, monkeypatch):
    """Keep unit-test probe records out of the production shadow-route log."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")


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
    log("task two", actual="flash-fallback")

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


# ═══════════════════════════════════════════════════════════════
# Actual enum validation tests
# ═══════════════════════════════════════════════════════════════

def test_valid_actual_local():
    r = log(task="test local", actual="local")
    assert "error" not in r


def test_valid_actual_pro_review():
    r = log(task="test pro", actual="pro-review")
    assert "error" not in r


def test_invalid_actual_rejected():
    r = log(task="test bad", actual="invalid-value")
    assert "error" in r
    assert r["written"] is False


def test_empty_actual_allowed():
    r = log(task="test empty", actual="")
    assert "error" not in r


def test_invalid_not_written_to_jsonl(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_val"
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", sd)
    log(task="test bad write", actual="garbage-actual")
    # Verify no file was created
    assert not sd.exists() or not list(sd.glob("*.jsonl"))


def test_canonical_local_accepted():
    r = log(task="canon local", actual="local")
    assert "error" not in r


def test_legacy_local_only_accepted():
    r = log(task="legacy", actual="local-only")
    assert "error" not in r


def test_invalid_error_mentions_canonical():
    r = log(task="bad", actual="wrong-value")
    assert "Canonical" in r["error"]
    assert "Legacy" in r["error"]


def test_invalid_error_includes_local_first():
    r = log(task="bad2", actual="nope")
    assert "local-first" in r["error"]


# ═══════════════════════════════════════════════════════════════
# External task privacy tests
# ═══════════════════════════════════════════════════════════════

def test_external_task_logged_without_secrets(tmp_path, monkeypatch):
    """External project task can be logged without secret fields."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    r = log(task="Google Play: review store listing for release", actual="pro-review")
    # Must not include secret-related fields
    assert "api_key" not in r
    assert "secret" not in r
    assert "token" not in r
    # Record was written successfully
    assert "error" not in r


def test_shadow_record_excludes_api_key(tmp_path, monkeypatch):
    """Shadow route record must not contain API key field."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    log(task="translator: fix subtitle regression", actual="local-first")
    shadow_dir = tmp_path / "shadow_routes"
    for f in shadow_dir.glob("*.jsonl"):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                assert "api_key" not in data


def test_shadow_record_excludes_raw_file_contents(tmp_path, monkeypatch):
    """Shadow record must not contain raw file contents."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    log(task="game-dev: review save system design", actual="pro-review")
    shadow_dir = tmp_path / "shadow_routes"
    for f in shadow_dir.glob("*.jsonl"):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                assert "file_content" not in data
                assert "raw_text" not in data


def test_actual_enum_validated_on_external_tasks(tmp_path, monkeypatch):
    """Actual enum validation still works for external project tasks."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    r1 = log(task="browser-plugin: review content script permissions", actual="pro-review")
    assert "error" not in r1
    r2 = log(task="browser-plugin: audit manifest", actual="bad-actual")
    assert "error" in r2
    assert r2["written"] is False


def test_malformed_external_task_no_crash(tmp_path, monkeypatch):
    """Malformed external task name does not crash the logger."""
    monkeypatch.setattr("shadow_route_log.SHADOW_DIR", tmp_path / "shadow_routes")
    weird_tasks = [
        "",
        "  ",
        "a" * 500,  # very long task name
    ]
    for task in weird_tasks:
        r = log(task=task, actual="local-first")
        assert isinstance(r, dict)  # Always returns a dict, never throws
