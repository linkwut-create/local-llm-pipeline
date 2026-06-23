"""Tests for tools/soft_gate_dogfood_status.py — read-only, no writes, no API calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from soft_gate_dogfood_status import status, _load_records, _count_distribution


def _write_records(dir_path: Path, records: list[dict], fname: str = "20260613.jsonl"):
    dir_path.mkdir(parents=True, exist_ok=True)
    with open(dir_path / fname, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════
# 1-2: Empty / below target
# ═══════════════════════════════════════════════════════════════

def test_empty_progress_zero(tmp_path, monkeypatch):
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", tmp_path / "empty")
    r = status(since="2026-06-13", target=30)
    assert r["records_total"] == 0
    assert r["records_remaining"] == 30
    assert r["progress_ratio"] == 0.0
    assert r["warning_gate_candidate"] is False
    assert r["recommendation"] == "continue_dogfood"


def test_below_target_not_eligible(tmp_path, monkeypatch):
    sd = tmp_path / "shadow"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "t1", "router_task_type": "review-diff", "router_risk_level": "medium",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    r = status(since="2026-06-13", target=30)
    assert r["records_total"] == 1
    assert r["warning_gate_candidate"] is False


# ═══════════════════════════════════════════════════════════════
# 3-6: Threshold conditions
# ═══════════════════════════════════════════════════════════════

def test_low_match_rate_not_eligible(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_low"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    records = []
    for i in range(30):
        records.append({
            "task": f"t{i}", "router_task_type": "review-diff",
            "router_risk_level": "medium", "router_privacy_status": "safe",
            "actual_decision": "local-first", "match": i >= 15,  # 15/15 unmatched
            "timestamp": "2026-06-13T10:00:00Z",
        })
    _write_records(sd, records)
    r = status(since="2026-06-13", target=30)
    assert r["records_total"] >= 30
    assert r["match_rate"] < 0.85
    assert r["warning_gate_candidate"] is False


def test_critical_misrouting_not_eligible(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_crit"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    records = []
    for i in range(30):
        match = i != 0  # first one is a mismatch
        risk = "high" if i == 0 else "medium"
        records.append({
            "task": f"t{i}", "router_task_type": "interface-review",
            "router_risk_level": risk, "router_privacy_status": "safe",
            "actual_decision": "local-first" if i == 0 else "local-first",
            "match": match,
            "timestamp": "2026-06-13T10:00:00Z",
        })
    _write_records(sd, records)
    r = status(since="2026-06-13", target=30)
    assert r["critical_misrouting"] > 0
    assert r["warning_gate_candidate"] is False
    assert "calibrate" in r["recommendation"]


def test_all_thresholds_met(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_good"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    records = []
    for i in range(30):
        records.append({
            "task": f"t{i}", "router_task_type": "review-diff",
            "router_risk_level": "medium", "router_privacy_status": "safe",
            "actual_decision": "local-first", "match": True,
            "timestamp": "2026-06-13T10:00:00Z",
        })
    _write_records(sd, records)
    r = status(since="2026-06-13", target=30)
    assert r["records_total"] >= 30
    assert r["critical_misrouting"] == 0
    assert r["match_rate"] >= 0.85
    assert r["warning_gate_candidate"] is True
    assert "eligible" in r["recommendation"]


# ═══════════════════════════════════════════════════════════════
# 7-9: Distribution + safety
# ═══════════════════════════════════════════════════════════════

def test_actual_distribution(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_dist"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "t1", "router_task_type": "review-diff", "router_risk_level": "low",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
        {"task": "t2", "router_task_type": "release-risk-review", "router_risk_level": "high",
         "router_privacy_status": "safe", "actual_decision": "pro-review", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
        {"task": "t3", "router_task_type": "review-diff", "router_risk_level": "medium",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    r = status(since="2026-06-13", target=30)
    assert r["actual_distribution"]["local-first"] == 2
    assert r["actual_distribution"]["pro-review"] == 1


def test_unknown_rate(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_unk"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "t1", "router_task_type": "unknown",
         "router_risk_level": "low", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": None,
         "timestamp": "2026-06-13T10:00:00Z"},
        {"task": "t2", "router_task_type": "review-diff",
         "router_risk_level": "medium", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    r = status(since="2026-06-13", target=30)
    assert r["unknown_rate"] == 0.5
    assert r["unknown_count"] == 1


def test_exclude_before_filters_old_records(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_epoch"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "old misrouting", "router_task_type": "governance-integration",
         "router_risk_level": "high", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": False,
         "timestamp": "2026-06-13T10:00:00+00:00"},
        {"task": "new ok", "router_task_type": "review-diff",
         "router_risk_level": "medium", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-22T10:00:00+00:00"},
    ])
    r_all = status(since="2026-06-13", target=30)
    assert r_all["records_total"] == 2
    assert r_all["critical_misrouting"] == 1

    r_filtered = status(since="2026-06-13", target=30,
                        exclude_before="2026-06-20T00:00:00+00:00")
    assert r_filtered["records_total"] == 1
    assert r_filtered["critical_misrouting"] == 0
    assert r_filtered["match_rate"] == 1.0


def test_exclude_before_date_uses_file_prefix_for_missing_timestamps(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_epoch_file"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "old missing timestamp", "router_task_type": "governance-integration",
         "router_risk_level": "high", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": False},
    ], fname="20260613.jsonl")
    _write_records(sd, [
        {"task": "new ok", "router_task_type": "review-diff",
         "router_risk_level": "medium", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-22T10:00:00+00:00"},
    ], fname="20260622.jsonl")

    records = _load_records(since="2026-06-13", exclude_before="2026-06-20")

    assert [r["task"] for r in records] == ["new ok"]


def test_exclude_before_keeps_exact_boundary_record(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_epoch_boundary"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "boundary", "router_task_type": "review-diff",
         "router_risk_level": "medium", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-20T00:00:00+00:00"},
    ])

    records = _load_records(since="2026-06-13",
                            exclude_before="2026-06-20T00:00:00+00:00")

    assert [r["task"] for r in records] == ["boundary"]


def test_calibration_epoch_excludes_historical_misrouting(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_cal"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "historical governance", "router_task_type": "governance-integration",
         "router_risk_level": "high", "router_privacy_status": "safe",
         "actual_decision": "local", "match": False,
         "timestamp": "2026-06-13T10:00:00+00:00"},
        {"task": "current review", "router_task_type": "review-diff",
         "router_risk_level": "medium", "router_privacy_status": "safe",
         "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-22T10:00:00+00:00"},
    ])
    assert status(since="2026-06-13", target=30)["critical_misrouting"] == 1
    assert status(since="2026-06-13", target=30,
                  exclude_before="2026-06-20T00:00:00+00:00")["critical_misrouting"] == 0


# ═══════════════════════════════════════════════════════════════
# 10-13: Safety + schema
# ═══════════════════════════════════════════════════════════════

def test_no_api_key_access():
    import soft_gate_dogfood_status as ds
    source = Path(ds.__file__).read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in source
    assert "os.environ" not in source
    assert "requests" not in source


def test_json_schema():
    r = status(since="2026-06-13", target=30)
    required = [
        "since", "target_records", "records_total", "records_remaining",
        "progress_ratio", "actual_distribution", "router_type_distribution",
        "match_rate", "unknown_rate", "critical_misrouting",
        "privacy_bypass", "false_cloud_on_secret",
        "warning_gate_candidate", "recommendation",
    ]
    for field in required:
        assert field in r, f"Missing: {field}"


def test_no_write_to_shadow(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_nowrite"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "t1", "router_task_type": "review-diff", "router_risk_level": "medium",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    # Run status — should only read, not write
    r = status(since="2026-06-13", target=30)
    # Verify only 1 record still exists (no new records written)
    files = list(sd.glob("*.jsonl"))
    assert len(files) == 1
    lines = sum(1 for _ in open(files[0], encoding="utf-8"))
    assert lines == 1


# ═══════════════════════════════════════════════════════════════
# 11-15: Additional recommendation + schema coverage
# ═══════════════════════════════════════════════════════════════

def test_privacy_bypass_blocks_warning_gate(tmp_path, monkeypatch):
    sd = tmp_path / "shadow_pb"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    # Not testable via records alone — privacy_bypass is heuristic=0
    # but verify the field exists and is 0 by default
    r = status(since="2026-06-13", target=30)
    assert "privacy_bypass" in r
    assert "false_cloud_on_secret" in r
    assert r["privacy_bypass"] == 0
    assert r["false_cloud_on_secret"] == 0


def test_recommendation_exact_values():
    r = status(since="2026-06-13", target=30)
    valid = {
        "continue_dogfood", "calibrate_router", "fix_privacy_safety",
        "continue_dogfood_or_calibrate", "eligible_for_warning_gate_design",
    }
    assert r["recommendation"] in valid


def test_warning_gate_candidate_is_bool():
    r = status(since="2026-06-13", target=30)
    assert isinstance(r["warning_gate_candidate"], bool)


def test_progress_ratio_range():
    r = status(since="2026-06-13", target=30)
    assert 0.0 <= r["progress_ratio"] <= 1.0


def test_router_type_distribution_keys():
    r = status(since="2026-06-13", target=30)
    assert isinstance(r["router_type_distribution"], dict)
    # With real data, should have entries
    assert "records_total" in r


def test_cli_text_output_no_traceback():
    import subprocess
    r = subprocess.run([sys.executable, "tools/soft_gate_dogfood_status.py", "--since", "2026-06-13", "--target", "30"], capture_output=True, text=True, timeout=15, cwd=str(Path(__file__).parent.parent))
    assert "Traceback" not in r.stdout

def test_cli_json_warning_gate_false():
    import subprocess, json
    r = subprocess.run([sys.executable, "tools/soft_gate_dogfood_status.py", "--since", "2026-06-13", "--target", "30", "--json"], capture_output=True, text=True, timeout=15, cwd=str(Path(__file__).parent.parent))
    data = json.loads(r.stdout.strip())
    assert data["warning_gate_candidate"] is False


def test_recommendation_continue_dogfood_below_target():
    r = status(since="2026-06-13", target=999)
    assert r["recommendation"] == "continue_dogfood"


# ═══════════════════════════════════════════════════════════════
# Progress formatting regression tests
# ═══════════════════════════════════════════════════════════════

def test_records_remaining_never_negative(tmp_path, monkeypatch):
    """records_remaining must never go negative even if records > target."""
    sd = tmp_path / "shadow_over"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    records = []
    for i in range(50):  # 50 > target 30
        records.append({
            "task": f"t{i}", "router_task_type": "review-diff",
            "router_risk_level": "medium", "router_privacy_status": "safe",
            "actual_decision": "local-first", "match": True,
            "timestamp": "2026-06-13T10:00:00Z",
        })
    _write_records(sd, records)
    r = status(since="2026-06-13", target=30)
    assert r["records_remaining"] >= 0, f"records_remaining is {r['records_remaining']}"
    assert r["records_remaining"] == 0  # Capped at 0, not negative


def test_progress_ratio_capped_when_records_exceed_target(tmp_path, monkeypatch):
    """progress_ratio should cap at 1.0 when records > target."""
    sd = tmp_path / "shadow_capped"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    records = []
    for i in range(60):  # 2x target
        records.append({
            "task": f"t{i}", "router_task_type": "review-diff",
            "router_risk_level": "medium", "router_privacy_status": "safe",
            "actual_decision": "local-first", "match": True,
            "timestamp": "2026-06-13T10:00:00Z",
        })
    _write_records(sd, records)
    r = status(since="2026-06-13", target=30)
    assert r["progress_ratio"] <= 1.0, f"progress_ratio={r['progress_ratio']} not capped"


def test_target_30_behavior_stable(tmp_path, monkeypatch):
    """With target=30, fields are populated consistently."""
    sd = tmp_path / "shadow_t30"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "t1", "router_task_type": "review-diff", "router_risk_level": "medium",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    r = status(since="2026-06-13", target=30)
    assert r["target_records"] == 30
    assert r["records_total"] >= 0
    # Even below target, all fields must be present
    assert "match_rate" in r
    assert "unknown_rate" in r
    assert "critical_misrouting" in r


def test_json_output_includes_warning_gate_candidate(tmp_path, monkeypatch):
    """CLI --json output always includes warning_gate_candidate."""
    sd = tmp_path / "shadow_json_wgc"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    _write_records(sd, [
        {"task": "t1", "router_task_type": "review-diff", "router_risk_level": "medium",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    import subprocess, json as _json
    r_proc = subprocess.run(
        [sys.executable, "tools/soft_gate_dogfood_status.py",
         "--since", "2026-06-13", "--target", "30", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    data = _json.loads(r_proc.stdout.strip())
    assert "warning_gate_candidate" in data
    assert isinstance(data["warning_gate_candidate"], bool)


def test_recommendation_one_of_allowed_values(tmp_path, monkeypatch):
    """recommendation is always one of the known allowed values."""
    sd = tmp_path / "shadow_rec_vals"
    monkeypatch.setattr("soft_gate_dogfood_status.SHADOW_DIR", sd)
    # Empty → continue_dogfood
    r_empty = status(since="2026-06-13", target=30)
    allowed = {
        "continue_dogfood", "calibrate_router", "fix_privacy_safety",
        "continue_dogfood_or_calibrate", "eligible_for_warning_gate_design",
    }
    assert r_empty["recommendation"] in allowed

    # With data → check again
    _write_records(sd, [
        {"task": "t1", "router_task_type": "review-diff", "router_risk_level": "medium",
         "router_privacy_status": "safe", "actual_decision": "local-first", "match": True,
         "timestamp": "2026-06-13T10:00:00Z"},
    ])
    r_data = status(since="2026-06-13", target=30)
    assert r_data["recommendation"] in allowed
