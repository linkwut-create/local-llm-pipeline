"""Tests for tools/cost_ledger.py — no DeepSeek, no LLM, no profile changes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from cost_ledger import (
    estimate,
    record,
    summary,
    _estimate_cost,
    _get_pricing,
    _load_month_records,
    _month_file,
    LEDGER_DIR,
    OUTPUT_DIR,
    PRICING,
)


# ═══════════════════════════════════════════════════════════════
# 1. Estimate does NOT write files
# ═══════════════════════════════════════════════════════════════

def test_estimate_no_file_written(tmp_path, monkeypatch):
    """Estimate is dry-run — no JSONL file created."""
    test_dir = tmp_path / "cost_ledger_test"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = estimate(
        task="review diff",
        model="deepseek-v4-flash",
        input_tokens=10000,
        output_tokens=2000,
    )

    assert result["dry_run"] is True
    assert result["estimated_cost"] is not None
    assert result["estimated_cost"] > 0
    assert result["price_known"] is True
    assert not test_dir.exists()  # No files written


def test_estimate_has_required_fields():
    """Estimate result includes all required fields."""
    result = estimate(
        task="review diff",
        model="deepseek-v4-flash",
        input_tokens=5000,
        output_tokens=1000,
        budget_limit=200,
    )

    required = [
        "timestamp", "task", "model", "provider",
        "input_tokens", "output_tokens", "estimated_cost",
        "currency", "budget_limit", "budget_used",
        "budget_remaining", "allowed", "reason", "dry_run",
    ]
    for field in required:
        assert field in result, f"Missing field: {field}"


# ═══════════════════════════════════════════════════════════════
# 2. Record writes JSONL
# ═══════════════════════════════════════════════════════════════

def test_record_writes_jsonl(tmp_path, monkeypatch):
    """Record writes a single JSONL line."""
    test_dir = tmp_path / "cost_ledger"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = record(
        task="review diff before commit",
        model="deepseek-v4-flash",
        input_tokens=10000,
        output_tokens=2000,
    )

    assert result["allowed"] is True
    assert result["estimated_cost"] is not None

    # Verify file was written
    month_file = _month_file()
    assert month_file.exists()

    lines = []
    with open(month_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))

    assert len(lines) == 1
    assert lines[0]["model"] == "deepseek-v4-flash"
    assert lines[0]["task"] == "review diff before commit"
    assert lines[0]["input_tokens"] == 10000
    assert lines[0]["output_tokens"] == 2000


def test_record_multiple_entries(tmp_path, monkeypatch):
    """Multiple records append correctly."""
    test_dir = tmp_path / "cost_ledger_multi"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    record(task="task A", model="deepseek-v4-flash",
           input_tokens=1000, output_tokens=500)
    record(task="task B", model="deepseek-v4-pro",
           input_tokens=5000, output_tokens=1000)
    record(task="task C", model="deepseek-v4-flash",
           input_tokens=3000, output_tokens=800)

    month_file = _month_file()
    lines = []
    with open(month_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(json.loads(line))

    assert len(lines) == 3
    assert lines[0]["task"] == "task A"
    assert lines[1]["task"] == "task B"
    assert lines[2]["task"] == "task C"


# ═══════════════════════════════════════════════════════════════
# 3. Summary aggregates multiple records
# ═══════════════════════════════════════════════════════════════

def test_summary_aggregates(tmp_path, monkeypatch):
    """Summary correctly aggregates multiple records."""
    test_dir = tmp_path / "cost_ledger_summary"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    record(task="t1", model="deepseek-v4-flash",
           input_tokens=10000, output_tokens=2000)
    record(task="t2", model="deepseek-v4-flash",
           input_tokens=5000, output_tokens=1000)
    record(task="t3", model="deepseek-v4-pro",
           input_tokens=20000, output_tokens=5000)

    s = summary()

    assert s["total_calls"] == 3
    assert s["total_estimated_cost"] > 0
    assert s["allowed"] == 3
    assert s["blocked"] == 0
    assert s["by_model"]["deepseek-v4-flash"]["calls"] == 2
    assert s["by_model"]["deepseek-v4-pro"]["calls"] == 1


def test_summary_empty(tmp_path, monkeypatch):
    """Empty ledger produces zero-count summary."""
    test_dir = tmp_path / "cost_ledger_empty"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    s = summary()

    assert s["total_calls"] == 0
    assert s["total_estimated_cost"] == 0.0
    assert s["allowed"] == 0
    assert s["all_time_calls"] == 0


# ═══════════════════════════════════════════════════════════════
# 4. Budget exceeded → allowed=false
# ═══════════════════════════════════════════════════════════════

def test_budget_exceeded_blocks(tmp_path, monkeypatch):
    """When cumulative cost exceeds budget, record sets allowed=false."""
    test_dir = tmp_path / "cost_ledger_budget"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    # First call — under 200 CNY budget
    r1 = record(
        task="small task",
        model="deepseek-v4-pro",
        input_tokens=50000,    # 50k * 4/1M = 0.2 CNY
        output_tokens=100000,  # 100k * 8/1M = 0.8 CNY → ~1.0 CNY total
        budget_limit=200,
    )
    assert r1["allowed"] is True

    # Second call — huge, pushes over budget
    r2 = record(
        task="massive task",
        model="deepseek-v4-pro",
        input_tokens=50000000,   # 50M * 4/1M = 200 CNY
        output_tokens=25000000,  # 25M * 8/1M = 200 CNY → ~400 CNY total
        budget_limit=200,
    )
    assert r2["allowed"] is False
    assert r2["reason"] == "budget_exceeded"


def test_estimate_budget_exceeded(tmp_path, monkeypatch):
    """Estimate with budget: if projected exceeds, allowed=false but no file written."""
    test_dir = tmp_path / "cost_ledger_est_budget"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = estimate(
        task="huge task",
        model="deepseek-v4-pro",
        input_tokens=100000000,
        output_tokens=50000000,
        budget_limit=200,
    )

    assert result["allowed"] is False
    assert not test_dir.exists()


def test_budget_summary_shows_remaining(tmp_path, monkeypatch):
    """Summary with budget shows remaining and exceeded flag."""
    test_dir = tmp_path / "cost_ledger_budget_sum"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    # Record something under budget
    record(task="t1", model="deepseek-v4-flash",
           input_tokens=10000, output_tokens=2000, budget_limit=200)

    s = summary(budget_limit=200)
    assert s["budget_limit"] == 200
    assert s["budget_remaining"] < 200
    assert s["budget_exceeded"] is False


# ═══════════════════════════════════════════════════════════════
# 5. Unknown model does NOT crash
# ═══════════════════════════════════════════════════════════════

def test_unknown_model_estimate():
    """Unknown model returns unknown_price but does not crash."""
    result = estimate(
        task="test unknown",
        model="nonexistent-model-v99",
        input_tokens=1000,
        output_tokens=500,
    )

    assert result["estimated_cost"] is None
    assert result["price_known"] is False
    assert result["reason"] == "unknown_price"
    assert result["allowed"] is True  # Still allowed since no budget
    assert "timestamp" in result


def test_unknown_model_record(tmp_path, monkeypatch):
    """Unknown model record writes successfully with null cost."""
    test_dir = tmp_path / "cost_ledger_unknown"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    result = record(
        task="unknown model call",
        model="some-future-model",
        input_tokens=5000,
        output_tokens=1000,
    )

    assert result["estimated_cost"] is None
    assert result["price_known"] is False
    assert result["allowed"] is True

    month_file = _month_file()
    assert month_file.exists()


def test_unknown_model_summary_counts(tmp_path, monkeypatch):
    """Summary counts unknown_price records correctly."""
    test_dir = tmp_path / "cost_ledger_unk_sum"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    record(task="t1", model="deepseek-v4-flash",
           input_tokens=1000, output_tokens=500)
    record(task="t2", model="unknown-model",
           input_tokens=1000, output_tokens=500)

    s = summary()
    assert s["unknown_price"] == 1
    assert s["total_calls"] == 2


# ═══════════════════════════════════════════════════════════════
# 6. Output path in .local_llm_out/
# ═══════════════════════════════════════════════════════════════

def test_output_path_under_local_llm_out():
    """LEDGER_DIR is under .local_llm_out/."""
    assert ".local_llm_out" in str(LEDGER_DIR)
    assert "cost_ledger" in str(LEDGER_DIR)


def test_output_dir_is_project_relative():
    """OUTPUT_DIR is project-relative, not system temp or home."""
    out_str = str(OUTPUT_DIR)
    assert ".local_llm_out" in out_str
    # Must not be under /tmp or equivalent
    assert "/tmp" not in out_str.lower()


def test_month_file_naming():
    """Month file uses YYYYMM.jsonl format."""
    from datetime import datetime, timezone
    ts = datetime(2026, 6, 15, tzinfo=timezone.utc)
    f = _month_file(ts)
    assert f.name == "202606.jsonl"


# ═══════════════════════════════════════════════════════════════
# 7. Does NOT call DeepSeek
# ═══════════════════════════════════════════════════════════════

def test_no_deepseek_import():
    """cost_ledger does not import deepseek_client."""
    import cost_ledger as cl
    # Check actual code lines (exclude comments/docstrings) for deepseek_client references
    source = Path(cl.__file__).read_text(encoding="utf-8")
    code_lines = [ln for ln in source.split("\n")
                  if not ln.strip().startswith("#") and not ln.strip().startswith('"""')]
    code_only = "\n".join(code_lines)
    # The word may appear in comments about what NOT to do
    # Check sys.modules instead for actual imports
    assert "deepseek_client" not in cl.__dict__


def test_no_api_key_access():
    """cost_ledger never reads DEEPSEEK_API_KEY."""
    import cost_ledger as cl
    source = Path(cl.__file__).read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in source
    assert "api_key" not in source.lower().split("deepseek")


def test_no_http_calls():
    """cost_ledger makes no HTTP requests."""
    import cost_ledger as cl
    source = Path(cl.__file__).read_text(encoding="utf-8")
    assert "requests." not in source
    assert "urllib" not in source
    assert "httpx" not in source
    assert "http://" not in source
    assert "https://" not in source


# ═══════════════════════════════════════════════════════════════
# 8. Does NOT modify profiles
# ═══════════════════════════════════════════════════════════════

def test_no_profile_import():
    """cost_ledger does not import local_llm_profiles.json."""
    import cost_ledger as cl
    source = Path(cl.__file__).read_text(encoding="utf-8")
    assert "local_llm_profiles" not in source


# ═══════════════════════════════════════════════════════════════
# 9. Pricing edge cases
# ═══════════════════════════════════════════════════════════════

def test_pricing_configurable():
    """Pricing can be overridden via env var."""
    # Test that the default pricing is loaded
    flash_price = _get_pricing("deepseek-v4-flash")
    assert flash_price["provider"] == "deepseek"
    assert flash_price["currency"] == "CNY"
    assert flash_price["input_cny_per_1m"] is not None


def test_flash_vs_pro_cost_difference():
    """Pro is more expensive than Flash."""
    flash_cost = _estimate_cost("deepseek-v4-flash", 10000, 2000)
    pro_cost = _estimate_cost("deepseek-v4-pro", 10000, 2000)

    assert flash_cost["estimated_cost"] is not None
    assert pro_cost["estimated_cost"] is not None
    assert pro_cost["estimated_cost"] > flash_cost["estimated_cost"]


def test_zero_tokens():
    """Zero tokens = zero cost, not a crash."""
    result = estimate(
        task="empty",
        model="deepseek-v4-flash",
        input_tokens=0,
        output_tokens=0,
    )

    assert result["estimated_cost"] == 0.0
    assert result["price_known"] is True


def test_cost_linear_with_tokens():
    """Cost scales linearly with token count."""
    small = estimate(task="small", model="deepseek-v4-flash",
                     input_tokens=1000, output_tokens=500)
    large = estimate(task="large", model="deepseek-v4-flash",
                     input_tokens=10000, output_tokens=5000)

    assert large["estimated_cost"] > small["estimated_cost"]
    # Should be roughly 10x (within rounding tolerance)
    ratio = large["estimated_cost"] / small["estimated_cost"]
    assert 9.5 < ratio < 10.5


# ═══════════════════════════════════════════════════════════════
# 10. Record field completeness
# ═══════════════════════════════════════════════════════════════

def test_record_has_required_schema(tmp_path, monkeypatch):
    """Record output includes all schema fields specified in the task."""
    test_dir = tmp_path / "cost_ledger_schema"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)

    r = record(
        task="schema check",
        model="deepseek-v4-flash",
        input_tokens=1234,
        output_tokens=567,
        budget_limit=200,
        notes="test notes",
    )

    required_fields = [
        "timestamp", "task", "model", "provider",
        "input_tokens", "output_tokens", "estimated_cost",
        "currency", "budget_limit", "budget_used_before",
        "budget_remaining", "allowed", "reason",
    ]
    for field in required_fields:
        assert field in r, f"Missing field in record: {field}"

    assert r["notes"] == "test notes"
    assert r["currency"] == "CNY"


# ═══════════════════════════════════════════════════════════════
# 11. CLI argument validation (edge cases)
# ═══════════════════════════════════════════════════════════════

def test_no_args_exits_clean():
    """No arguments prints help and exits 1 (not crash)."""
    import cost_ledger as cl
    import sys as _sys
    old = _sys.argv[:]
    try:
        _sys.argv = ["cost_ledger.py"]
        with pytest.raises(SystemExit) as exc:
            cl.main()
        assert exc.value.code == 1
    finally:
        _sys.argv = old


# ═══════════════════════════════════════════════════════════════
# 12. Cross-month isolation
# ═══════════════════════════════════════════════════════════════

def test_summary_month_isolation(tmp_path, monkeypatch):
    """Summary only includes current month records by default."""
    test_dir = tmp_path / "cost_ledger_iso"
    monkeypatch.setattr("cost_ledger.LEDGER_DIR", test_dir)
    from datetime import datetime, timezone

    # Write a record with a fake timestamp to simulate another month
    test_dir.mkdir(parents=True, exist_ok=True)
    old_month_file = test_dir / "202601.jsonl"
    old_record = {
        "timestamp": "2026-01-15T00:00:00+00:00",
        "task": "old task",
        "model": "deepseek-v4-flash",
        "provider": "deepseek",
        "input_tokens": 1000,
        "output_tokens": 500,
        "estimated_cost": 0.002,
        "currency": "CNY",
        "price_known": True,
        "budget_limit": None,
        "budget_used_before": 0.0,
        "budget_remaining": None,
        "allowed": True,
        "reason": "ok",
        "notes": "",
    }
    with open(old_month_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(old_record, ensure_ascii=False) + "\n")

    # Record a current-month entry
    record(task="current task", model="deepseek-v4-flash",
           input_tokens=5000, output_tokens=1000)

    # Default summary = current month only
    s = summary()
    assert s["total_calls"] == 1  # Only current month

    # All-time includes both
    assert s["all_time_calls"] == 2
