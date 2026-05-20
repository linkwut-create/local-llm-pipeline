"""Tests for tools/call_ledger.py — per-call JSONL ledger."""

import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import call_ledger  # noqa: E402
import call_ledger_cli  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "calls.jsonl"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ledger-related env vars so tests start from a known state."""
    for var in ("LOCAL_LLM_LEDGER", "LOCAL_LLM_PROJECT", "LOCAL_LLM_PHASE",
                "LOCAL_LLM_COST_TABLE"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# is_ledger_enabled
# ---------------------------------------------------------------------------

def test_ledger_enabled_default(clean_env):
    assert call_ledger.is_ledger_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", "", "none"])
def test_ledger_disabled_by_falsy_env(clean_env, monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_LEDGER", value)
    assert call_ledger.is_ledger_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_ledger_enabled_by_truthy_env(clean_env, monkeypatch, value):
    monkeypatch.setenv("LOCAL_LLM_LEDGER", value)
    assert call_ledger.is_ledger_enabled() is True


# ---------------------------------------------------------------------------
# detect_project / detect_phase
# ---------------------------------------------------------------------------

def test_detect_project_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_PROJECT", "translator-agent")
    assert call_ledger.detect_project() == "translator-agent"


def test_detect_project_empty_env_falls_back_to_cwd(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_PROJECT", "   ")
    assert call_ledger.detect_project(tmp_path) == tmp_path.resolve().name


def test_detect_project_unset_uses_cwd(clean_env, tmp_path):
    assert call_ledger.detect_project(tmp_path) == tmp_path.resolve().name


def test_detect_phase_unset(clean_env):
    assert call_ledger.detect_phase() is None


def test_detect_phase_empty(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_PHASE", "   ")
    assert call_ledger.detect_phase() is None


def test_detect_phase_set(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_PHASE", "TM-2A.3F")
    assert call_ledger.detect_phase() == "TM-2A.3F"


# ---------------------------------------------------------------------------
# git_state
# ---------------------------------------------------------------------------

def test_git_state_outside_repo(tmp_path):
    commit, dirty = call_ledger.git_state(tmp_path)
    assert commit is None
    assert dirty is None


def test_git_state_in_repo_returns_hash():
    # We are inside this project's git repo when running tests.
    commit, dirty = call_ledger.git_state(Path(__file__).parent.parent)
    # commit may be None if git is missing in the test env; only assert
    # mutual consistency: either both are None or commit is a hex string.
    if commit is not None:
        assert isinstance(commit, str) and len(commit) >= 4
        assert dirty in (True, False)


# ---------------------------------------------------------------------------
# estimate_tokens / estimate_cost_cny
# ---------------------------------------------------------------------------

def test_estimate_tokens_basic():
    assert call_ledger.estimate_tokens(0) == 0
    assert call_ledger.estimate_tokens(None) == 0
    assert call_ledger.estimate_tokens(4) == 1
    assert call_ledger.estimate_tokens(4001) == 1000


def test_cost_zero_for_local_provider(clean_env):
    assert call_ledger.estimate_cost_cny("ollama", None, "qwen3-coder:30b", 1000, 500) == 0.0
    assert call_ledger.estimate_cost_cny(None, "http://localhost:11434", "x", 100, 100) == 0.0
    assert call_ledger.estimate_cost_cny(None, "http://192.168.2.2:11434", "x", 0, 0) == 0.0


def test_cost_none_when_no_table(clean_env):
    assert call_ledger.estimate_cost_cny("deepseek", None, "deepseek-chat", 1000, 500) is None


def test_cost_from_env_table(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_COST_TABLE",
                       json.dumps({"deepseek-chat": {"in_per_1k": 0.001, "out_per_1k": 0.002}}))
    cost = call_ledger.estimate_cost_cny("deepseek", "https://api.deepseek.com",
                                          "deepseek-chat", 2000, 500)
    # 2 * 0.001 + 0.5 * 0.002 = 0.003
    assert cost == pytest.approx(0.003)


def test_cost_malformed_table_returns_none(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_COST_TABLE", "not-json")
    assert call_ledger.estimate_cost_cny("deepseek", None, "deepseek-chat", 100, 100) is None


# ---------------------------------------------------------------------------
# build_record
# ---------------------------------------------------------------------------

def test_build_record_basic(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_PROJECT", "test-proj")
    monkeypatch.setenv("LOCAL_LLM_PHASE", "v0.1")
    rec = call_ledger.build_record(
        task_type="review-diff",
        tool_name="local_review_diff",
        model="qwen3-coder:30b",
        provider="ollama",
        input_chars=400,
        output_chars=200,
        duration_ms=15000,
        success=True,
        result_summary="no blockers",
        files_referenced=["a.py", "b.py"],
    )
    assert rec["project"] == "test-proj"
    assert rec["phase"] == "v0.1"
    assert rec["task_type"] == "review-diff"
    assert rec["tool_name"] == "local_review_diff"
    assert rec["model"] == "qwen3-coder:30b"
    assert rec["provider"] == "ollama"
    assert rec["input_chars"] == 400
    assert rec["output_chars"] == 200
    assert rec["input_tokens"] == 100  # 400 // 4
    assert rec["output_tokens"] == 50
    assert rec["total_tokens"] == 150
    assert rec["tokens_estimated"] is True
    assert rec["estimated_cost_cny"] == 0.0  # local provider
    assert rec["duration_ms"] == 15000
    assert rec["success"] is True
    assert rec["failure_reason"] is None
    assert rec["result_summary"] == "no blockers"
    assert rec["files_referenced"] == ["a.py", "b.py"]
    assert "id" in rec
    assert rec["id"].startswith("call_")
    assert "timestamp" in rec


def test_build_record_failure(clean_env):
    rec = call_ledger.build_record(
        task_type="diff_review",
        tool_name="local_review_diff",
        model="qwen3-coder:30b",
        provider="ollama",
        input_chars=100,
        output_chars=0,
        duration_ms=60000,
        success=False,
        failure_reason="timeout",
    )
    assert rec["success"] is False
    assert rec["failure_reason"] == "timeout"
    assert rec["output_chars"] == 0
    assert rec["output_tokens"] == 0
    assert rec["total_tokens"] == 25  # 100/4 + 0


def test_build_record_with_explicit_tokens(clean_env):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="p",
        input_chars=400, output_chars=200,
        input_tokens=120, output_tokens=80,
        cached_tokens=90,
        duration_ms=100, success=True,
    )
    assert rec["input_tokens"] == 120
    assert rec["output_tokens"] == 80
    assert rec["total_tokens"] == 200
    assert rec["cached_tokens"] == 90
    assert rec["tokens_estimated"] is False


def test_build_record_strips_forbidden_extra(clean_env):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="p",
        success=True,
        extra={"api_key": "sk-secret", "useful": "ok", "PASSWORD": "x"},
    )
    extra = rec.get("extra") or {}
    assert "api_key" not in extra
    assert "PASSWORD" not in extra
    assert extra.get("useful") == "ok"


def test_build_record_default_cache_hit_false(clean_env):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        input_chars=100, output_chars=50, success=True,
    )
    assert rec["cache_hit"] is False


def test_build_record_cache_hit_zeroes_cost_even_with_table(clean_env, monkeypatch):
    # Cost table that would otherwise charge non-zero on a remote provider.
    monkeypatch.setenv(
        "LOCAL_LLM_COST_TABLE",
        json.dumps({"deepseek-chat": {"in_per_1k": 0.001, "out_per_1k": 0.002}}),
    )
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="deepseek-chat", provider="deepseek",
        base_url="https://api.deepseek.com",
        input_chars=4000, output_chars=2000,
        duration_ms=0, success=True, cache_hit=True,
    )
    assert rec["cache_hit"] is True
    assert rec["estimated_cost_cny"] == 0.0
    # tokens still recorded so post-hoc savings can be computed.
    assert rec["input_tokens"] == 1000
    assert rec["output_tokens"] == 500


def test_build_record_truncates_summary_and_reason(clean_env):
    long_text = "x" * 1000
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="p",
        success=False,
        failure_reason=long_text,
        result_summary=long_text,
    )
    assert len(rec["failure_reason"]) <= 300
    assert len(rec["result_summary"]) <= 300


# ---------------------------------------------------------------------------
# record_call
# ---------------------------------------------------------------------------

def test_record_call_writes_jsonl_line(clean_env, ledger_path):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        input_chars=10, output_chars=10, duration_ms=1, success=True,
    )
    assert call_ledger.record_call(rec, path=ledger_path) is True
    text = ledger_path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["task_type"] == "x"


def test_record_call_appends_multiple_lines(clean_env, ledger_path):
    for i in range(3):
        rec = call_ledger.build_record(
            task_type=f"task_{i}", tool_name="t", model="m", provider="ollama",
            success=True,
        )
        assert call_ledger.record_call(rec, path=ledger_path) is True
    lines = ledger_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    assert json.loads(lines[2])["task_type"] == "task_2"


def test_record_call_creates_missing_dir(clean_env, tmp_path):
    target = tmp_path / "deep" / "nested" / "calls.jsonl"
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama", success=True,
    )
    assert call_ledger.record_call(rec, path=target) is True
    assert target.exists()


def test_record_call_disabled_returns_false(clean_env, monkeypatch, ledger_path):
    monkeypatch.setenv("LOCAL_LLM_LEDGER", "0")
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama", success=True,
    )
    assert call_ledger.record_call(rec, path=ledger_path) is False
    assert not ledger_path.exists()


def test_record_call_never_raises(clean_env, monkeypatch):
    # Force json.dumps to fail by passing an unserializable value via extra.
    # Default=str should rescue it; record_call should not raise either way.
    class Weird:
        def __repr__(self):
            raise RuntimeError("nope")

    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama", success=True,
        extra={"weird": Weird()},
    )
    # Use a path that points to an invalid location (existing file as parent).
    # Should silently return False, never raise.
    with monkeypatch.context() as m:
        m.setattr(call_ledger, "_resolve_path",
                  lambda p: Path("/!/!/!/this/path/cannot/exist/calls.jsonl"))
        result = call_ledger.record_call(rec)
        assert result is False


# ---------------------------------------------------------------------------
# read_records
# ---------------------------------------------------------------------------

def test_read_records_missing_file(clean_env, ledger_path):
    assert call_ledger.read_records(ledger_path) == []


def test_read_records_skips_malformed_lines(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        '{"task_type": "good", "success": true}\n'
        'this is not json\n'
        '\n'
        '{"task_type": "good2", "success": false}\n',
        encoding="utf-8",
    )
    out = call_ledger.read_records(ledger_path)
    assert len(out) == 2
    assert out[0]["task_type"] == "good"
    assert out[1]["task_type"] == "good2"


# ---------------------------------------------------------------------------
# summarize / group_by / filter_failures / recent
# ---------------------------------------------------------------------------

def _sample_records() -> list[dict]:
    return [
        {"project": "A", "task_type": "review", "success": True,
         "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
         "duration_ms": 1000, "estimated_cost_cny": 0.0},
        {"project": "A", "task_type": "summarize", "success": True,
         "input_tokens": 200, "output_tokens": 80, "total_tokens": 280,
         "duration_ms": 2000, "estimated_cost_cny": 0.01},
        {"project": "B", "task_type": "review", "success": False,
         "input_tokens": 50, "output_tokens": 0, "total_tokens": 50,
         "duration_ms": 60000, "estimated_cost_cny": None,
         "failure_reason": "timeout"},
    ]


def test_summarize_empty():
    s = call_ledger.summarize([])
    assert s["calls"] == 0
    assert s["successes"] == 0
    assert s["failures"] == 0
    assert s["total_cost_cny"] == 0.0


def test_summarize_aggregates():
    s = call_ledger.summarize(_sample_records())
    assert s["calls"] == 3
    assert s["successes"] == 2
    assert s["failures"] == 1
    assert s["total_input_tokens"] == 350
    assert s["total_output_tokens"] == 130
    assert s["total_tokens"] == 480
    assert s["total_duration_ms"] == 63000
    assert s["total_cost_cny"] == pytest.approx(0.01)
    assert s["cost_known_calls"] == 2
    assert s["cost_unknown_calls"] == 1


def test_group_by_project():
    groups = call_ledger.group_by(_sample_records(), "project")
    assert set(groups.keys()) == {"A", "B"}
    assert groups["A"]["calls"] == 2
    assert groups["A"]["successes"] == 2
    assert groups["B"]["calls"] == 1
    assert groups["B"]["failures"] == 1


def test_group_by_task():
    groups = call_ledger.group_by(_sample_records(), "task_type")
    assert set(groups.keys()) == {"review", "summarize"}
    assert groups["review"]["calls"] == 2
    assert groups["summarize"]["calls"] == 1


def test_group_by_missing_key_uses_none_bucket():
    records = [{"task_type": "x", "success": True},
               {"success": True}]
    groups = call_ledger.group_by(records, "project")
    assert "<none>" in groups
    assert groups["<none>"]["calls"] == 2


def test_filter_failures():
    fails = call_ledger.filter_failures(_sample_records())
    assert len(fails) == 1
    assert fails[0]["project"] == "B"
    assert fails[0]["failure_reason"] == "timeout"


def test_recent_returns_last_n():
    records = [{"i": i, "success": True} for i in range(10)]
    out = call_ledger.recent(records, limit=3)
    assert [r["i"] for r in out] == [7, 8, 9]


def test_recent_limit_zero_returns_empty():
    records = [{"i": 1, "success": True}]
    assert call_ledger.recent(records, limit=0) == []


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def _seed_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in _sample_records():
            fh.write(json.dumps(rec) + "\n")


def test_cli_summary_table(clean_env, ledger_path, capsys):
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "summary"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "calls:" in captured
    assert "3" in captured


def test_cli_summary_json(clean_env, ledger_path, capsys):
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "--format", "json", "summary"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["calls"] == 3
    assert data["failures"] == 1


def test_cli_by_project_json(clean_env, ledger_path, capsys):
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "by-project"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data.keys()) == {"A", "B"}


def test_cli_by_task_json(clean_env, ledger_path, capsys):
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "by-task"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data.keys()) == {"review", "summarize"}


def test_cli_failures(clean_env, ledger_path, capsys):
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "failures"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["failure_reason"] == "timeout"


def test_cli_recent_limit(clean_env, ledger_path, capsys):
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "recent", "--limit", "2"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2
    # Sample order: A/review, A/summarize, B/review → last 2 = A/summarize, B/review
    assert data[0]["project"] == "A"
    assert data[1]["project"] == "B"


def test_cli_missing_file_empty_output(clean_env, tmp_path, capsys):
    rc = call_ledger_cli.main(["--path", str(tmp_path / "does-not-exist.jsonl"),
                                "--format", "json", "summary"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["calls"] == 0
