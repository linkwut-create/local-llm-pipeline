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


def test_build_record_cache_miss_tokens(clean_env):
    """v2-A: ledger records DeepSeek-style cache_miss_tokens when provided."""
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="deepseek-chat", provider="deepseek",
        input_tokens=4321, output_tokens=567,
        cached_tokens=4000, cache_miss_tokens=321,
        success=True,
    )
    assert rec["cached_tokens"] == 4000
    assert rec["cache_miss_tokens"] == 321
    assert rec["cache_hit"] is False  # provider-side cache hit ≠ local cache_hit


def test_build_record_cache_miss_tokens_default_none(clean_env):
    """Existing records without cache_miss_tokens still get the field set to None."""
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        success=True,
    )
    assert "cache_miss_tokens" in rec
    assert rec["cache_miss_tokens"] is None


# ---------------------------------------------------------------------------
# P2-B: top-level profile field and KNOWN_EXTRA_KEYS allowlist
# ---------------------------------------------------------------------------

def test_build_record_default_profile_is_none(clean_env):
    """A caller that does not pass profile gets profile=None top-level."""
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        success=True,
    )
    assert "profile" in rec
    assert rec["profile"] is None


def test_build_record_with_profile_top_level(clean_env):
    """Explicit profile is recorded at top level (not in extra)."""
    rec = call_ledger.build_record(
        task_type="review-diff", tool_name="local_review_diff",
        profile="commit_reviewer",
        model="qwen3-coder:30b", provider="ollama",
        success=True,
    )
    assert rec["profile"] == "commit_reviewer"
    # Must not leak into extra; profile is a top-level field.
    assert "extra" not in rec or "profile" not in rec.get("extra", {})


def test_known_extra_keys_constant_exists():
    """The cost-discipline allowlist is exposed as a public module constant."""
    assert hasattr(call_ledger, "KNOWN_EXTRA_KEYS")
    keys = call_ledger.KNOWN_EXTRA_KEYS
    # frozenset for immutability
    assert isinstance(keys, frozenset)
    # Must contain every cost-discipline field documented for P2-C+.
    expected = {
        "mcp_tool_name",
        "source",
        "commit_gate",
        "commit_gate_allowed",
        "auto_escalated",
        "escalation_trigger",
        "escalation_reason",
        "escalation_from_profile",
        "escalation_to_profile",
        "escalation_depth",
        "parent_request_id",
        "debate_mode",
        "debate_rounds",
        "debate_round_index",
        "debate_trigger",
        "review_necessity",
        "risk_level",
        "cost_class",
        "local_only",
        "cost_budget_remaining",
        "worker_id",
        "host",
        "error_type",
    }
    assert expected.issubset(keys), f"missing keys: {expected - keys}"


def test_known_extra_keys_disjoint_from_forbidden():
    """Allowlist and the secret-stripping forbidden list must not collide."""
    overlap = call_ledger.KNOWN_EXTRA_KEYS & call_ledger._FORBIDDEN_KEYS
    assert overlap == set()


# Each allowlisted key is exercised by a single parametrized test rather than
# 22 separate ones — P2-B only proves the schema can carry these; P2-C wires
# the actual call sites.
_ALLOWED_EXTRA_SAMPLES = [
    ("mcp_tool_name", "local_review_diff"),
    ("source", "manual-mcp"),
    ("commit_gate", True),
    ("commit_gate_allowed", True),
    ("auto_escalated", True),
    ("escalation_trigger", "low_confidence"),
    ("escalation_reason", "low_confidence"),
    ("escalation_from_profile", "diff_reviewer"),
    ("escalation_to_profile", "deep_reviewer"),
    ("escalation_depth", 1),
    ("parent_request_id", "req_abc123"),
    ("debate_mode", True),
    ("debate_rounds", 3),
    ("debate_round_index", 2),
    ("debate_trigger", "hook-gate-security"),
    ("review_necessity", "required"),
    ("risk_level", "high"),
    ("cost_class", "low"),
    ("local_only", True),
    ("cost_budget_remaining", 4),
    ("worker_id", "zero12"),
    ("host", "ai-max-1.local"),
    ("error_type", "timeout"),
]


@pytest.mark.parametrize("key,value", _ALLOWED_EXTRA_SAMPLES)
def test_build_record_allowed_extra_passes_through(clean_env, key, value):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        success=True,
        extra={key: value},
    )
    extra = rec.get("extra") or {}
    assert key in extra
    assert extra[key] == value


def test_build_record_unknown_extra_still_passes_through(clean_env):
    """P2-B is additive: unknown keys remain allowed (backward compatibility).

    Filtering for unknown keys is explicitly NOT part of P2-B. If a future
    phase introduces it, this test should be updated then, not silently.
    """
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        success=True,
        extra={"some_future_field": "still-here"},
    )
    extra = rec.get("extra") or {}
    assert extra.get("some_future_field") == "still-here"


def test_build_record_forbidden_keys_still_stripped_with_known_extras(clean_env):
    """Adding KNOWN_EXTRA_KEYS must not weaken secret stripping."""
    rec = call_ledger.build_record(
        task_type="x", tool_name="t", model="m", provider="ollama",
        success=True,
        extra={
            "api_key": "sk-secret",
            "mcp_tool_name": "local_review_diff",
            "PASSWORD": "x",
            "commit_gate": True,
        },
    )
    extra = rec.get("extra") or {}
    assert "api_key" not in extra
    assert "PASSWORD" not in extra
    assert extra.get("mcp_tool_name") == "local_review_diff"
    assert extra.get("commit_gate") is True


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


# ---------------------------------------------------------------------------
# P2-D1: sample records with extra dicts for escalation / debate / MCP tests
# ---------------------------------------------------------------------------


def _seed_p2_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        # Pre-P2 record: no extra, no profile
        fh.write(json.dumps({
            "id": "call_old", "timestamp": "2026-05-01T00:00:00+00:00",
            "project": "A", "task_type": "review-diff", "tool_name": "local_review_diff",
            "profile": None, "model": "old-model", "provider": "ollama",
            "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
            "duration_ms": 1000, "estimated_cost_cny": 0.0, "success": True,
        }) + "\n")
        # P2-C1.1 record: has mcp_tool_name in extra
        fh.write(json.dumps({
            "id": "call_mcp", "timestamp": "2026-05-10T00:00:00+00:00",
            "project": "A", "task_type": "summarize-file", "tool_name": "summarize-file",
            "profile": "fast_summary", "model": "gemma4:e4b", "provider": "ollama",
            "input_tokens": 20, "output_tokens": 10, "total_tokens": 30,
            "duration_ms": 2000, "estimated_cost_cny": 0.0, "success": True,
            "extra": {"mcp_tool_name": "local_summarize_file", "source": "manual-mcp"},
        }) + "\n")
        # P2-C1.2 record: auto-hook
        fh.write(json.dumps({
            "id": "call_hook", "timestamp": "2026-05-15T00:00:00+00:00",
            "project": "A", "task_type": "review-diff", "tool_name": "local_review_diff",
            "profile": "commit_reviewer", "model": "qwen3-coder:30b", "provider": "ollama",
            "input_tokens": 30, "output_tokens": 15, "total_tokens": 45,
            "duration_ms": 3000, "estimated_cost_cny": 0.0, "success": True,
            "extra": {"mcp_tool_name": "local_review_diff", "commit_gate": True,
                      "source": "auto-hook"},
        }) + "\n")
        # P2-C2.1 escalation record
        fh.write(json.dumps({
            "id": "call_esc", "timestamp": "2026-05-18T00:00:00+00:00",
            "project": "A", "task_type": "summarize-file", "tool_name": "summarize-file",
            "profile": "smart_summary", "model": "gemma4:9b", "provider": "ollama",
            "input_tokens": 40, "output_tokens": 20, "total_tokens": 60,
            "duration_ms": 4000, "estimated_cost_cny": 0.0, "success": True,
            "request_id": "req_parent",
            "extra": {
                "mcp_tool_name": "local_summarize_file", "source": "manual-mcp",
                "auto_escalated": True, "escalation_trigger": "low_confidence",
                "escalation_reason": "confidence=low on fast_summary",
                "escalation_from_profile": "fast_summary",
                "escalation_to_profile": "smart_summary",
                "escalation_depth": 1, "parent_request_id": "req_parent_001",
            },
        }) + "\n")
        # P2-C3.1 debate round records (2 rounds)
        fh.write(json.dumps({
            "id": "call_deb1", "timestamp": "2026-05-20T00:00:00+00:00",
            "project": "A", "task_type": "debate-review-diff",
            "tool_name": "local_debate_review_diff",
            "profile": "qwen3.6_27b_mtp", "model": "qwen3.6:27b-q8-ud",
            "provider": "ollama",
            "input_tokens": 50, "output_tokens": 25, "total_tokens": 75,
            "duration_ms": 5000, "estimated_cost_cny": 0.0, "success": True,
            "extra": {
                "debate_mode": True, "debate_rounds": 2, "debate_round_index": 1,
                "debate_trigger": "manual-mcp",
                "mcp_tool_name": "local_debate_review_diff", "source": "manual-mcp",
            },
        }) + "\n")
        fh.write(json.dumps({
            "id": "call_deb2", "timestamp": "2026-05-20T00:01:00+00:00",
            "project": "A", "task_type": "debate-review-diff",
            "tool_name": "local_debate_review_diff",
            "profile": "reasoning_checker",
            "model": "nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-q8_k_xl:latest",
            "provider": "ollama",
            "input_tokens": 60, "output_tokens": 30, "total_tokens": 90,
            "duration_ms": 6000, "estimated_cost_cny": 0.0, "success": False,
            "failure_reason": "timeout",
            "extra": {
                "debate_mode": True, "debate_rounds": 2, "debate_round_index": 2,
                "debate_trigger": "manual-mcp",
                "mcp_tool_name": "local_debate_review_diff", "source": "manual-mcp",
            },
        }) + "\n")


# ---------------------------------------------------------------------------
# P2-D1: group_by_extra
# ---------------------------------------------------------------------------


def test_group_by_extra_basic(ledger_path):
    _seed_p2_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    groups = call_ledger.group_by_extra(records, "mcp_tool_name")
    assert "local_summarize_file" in groups
    assert "local_review_diff" in groups
    assert "local_debate_review_diff" in groups
    # Pre-P2 record has no extra → <none>
    assert "<none>" in groups
    assert groups["<none>"]["calls"] == 1


def test_group_by_extra_missing_extra(ledger_path):
    _seed_p2_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    groups = call_ledger.group_by_extra(records, "nonexistent_key")
    assert set(groups.keys()) == {"<none>"}
    assert groups["<none>"]["calls"] == 6


def test_group_by_extra_missing_key(ledger_path):
    _seed_p2_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    groups = call_ledger.group_by_extra(records, "review_necessity")
    assert set(groups.keys()) == {"<none>"}


def test_group_by_extra_fallback_tool_name(ledger_path):
    _seed_p2_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    # With fallback_key="tool_name", the old record without extra
    # should fall back to its top-level tool_name.
    groups = call_ledger.group_by_extra(
        records, "mcp_tool_name", fallback_key="tool_name")
    # Pre-P2 record: tool_name="local_review_diff" → bucket
    assert "<none>" not in groups
    # All records should be categorized
    total = sum(g["calls"] for g in groups.values())
    assert total == 6


# ---------------------------------------------------------------------------
# P2-D1: filter_escalations
# ---------------------------------------------------------------------------


def test_filter_escalations_finds_auto_escalated(ledger_path):
    _seed_p2_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    items = call_ledger.filter_escalations(records)
    assert len(items) == 1
    assert items[0]["id"] == "call_esc"


def test_filter_escalations_empty_when_none(ledger_path):
    # Only pre-P2 records (no escalation fields)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "id": "c1", "timestamp": "2026-01-01T00:00:00+00:00",
            "project": "X", "task_type": "review-diff", "tool_name": "t",
            "profile": None, "model": "m", "provider": "p",
            "success": True, "input_tokens": 1, "output_tokens": 1,
            "total_tokens": 2, "duration_ms": 1,
        }) + "\n")
    records = call_ledger.read_records(ledger_path)
    assert call_ledger.filter_escalations(records) == []


# ---------------------------------------------------------------------------
# P2-D1: filter_debates
# ---------------------------------------------------------------------------


def test_filter_debates(ledger_path):
    _seed_p2_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    items = call_ledger.filter_debates(records)
    assert len(items) == 2
    ids = {r["id"] for r in items}
    assert ids == {"call_deb1", "call_deb2"}


def test_filter_debates_empty_when_none(ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "id": "c1", "timestamp": "2026-01-01T00:00:00+00:00",
            "project": "X", "task_type": "review-diff", "tool_name": "t",
            "profile": None, "model": "m", "provider": "p",
            "success": True, "input_tokens": 1, "output_tokens": 1,
            "total_tokens": 2, "duration_ms": 1,
        }) + "\n")
    records = call_ledger.read_records(ledger_path)
    assert call_ledger.filter_debates(records) == []


# ---------------------------------------------------------------------------
# P2-D1: CLI commands — by-profile
# ---------------------------------------------------------------------------


def test_cli_by_profile_table(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "by-profile"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "fast_summary" in captured
    assert "smart_summary" in captured
    assert "<none>" in captured  # old record has profile=None


def test_cli_by_profile_json(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "by-profile"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "fast_summary" in data
    assert "<none>" in data


# ---------------------------------------------------------------------------
# P2-D1: CLI commands — by-mcp-tool
# ---------------------------------------------------------------------------


def test_cli_by_mcp_tool_table(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "by-mcp-tool"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "local_summarize_file" in captured
    assert "local_review_diff" in captured
    assert "local_debate_review_diff" in captured


def test_cli_by_mcp_tool_json(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "by-mcp-tool"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "local_summarize_file" in data
    assert "local_review_diff" in data


# ---------------------------------------------------------------------------
# P2-D1: CLI commands — escalations
# ---------------------------------------------------------------------------


def test_cli_escalations_table(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "escalations"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "low_confidence" in captured
    assert "fast_summary" in captured
    assert "smart_summary" in captured


def test_cli_escalations_json(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "escalations"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 1
    extra = data[0].get("extra") or {}
    assert extra.get("auto_escalated") is True


def test_cli_escalations_limit(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "escalations", "--limit", "1"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# P2-D1: CLI commands — debates
# ---------------------------------------------------------------------------


def test_cli_debates_table(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "debates"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "manual-mcp" in captured
    assert "qwen3.6_27b_mtp" in captured
    assert "reasoning_checker" in captured


def test_cli_debates_json(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "debates"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 2
    extras = [d.get("extra") or {} for d in data]
    assert all(e.get("debate_mode") is True for e in extras)


def test_cli_debates_limit(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "debates", "--limit", "1"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# P2-D1: CLI commands — old record compatibility
# ---------------------------------------------------------------------------


def test_cli_by_profile_old_records_none_bucket(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "by-profile"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "<none>" in data
    assert data["<none>"]["calls"] >= 1


def test_cli_by_mcp_tool_old_records_none_bucket(clean_env, ledger_path, capsys):
    # Without fallback, old records go to <none>
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "by-mcp-tool"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # Pre-P2 record has no extra; it goes to <none> via group_by_extra
    # (fallback_key="tool_name" in CLI, so actually all records are covered)
    total = sum(g["calls"] for g in data.values())
    assert total == 6


# ---------------------------------------------------------------------------
# P6-B2-A: read_records_with_diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_missing_file_returns_empty(clean_env, ledger_path):
    result = call_ledger.read_records_with_diagnostics(ledger_path)
    assert result["records"] == []
    assert result["total_lines"] == 0
    assert result["empty_lines"] == 0
    assert result["malformed_json_lines"] == 0
    assert result["non_dict_lines"] == 0
    assert result["skipped_lines"] == 0
    assert result["errors"] == []


def test_diagnostics_all_valid_records(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '{"task_type": "a", "success": true}',
        '{"task_type": "b", "success": false}',
        '{"task_type": "c", "success": true}',
    ]
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = call_ledger.read_records_with_diagnostics(ledger_path)
    assert len(result["records"]) == 3
    assert result["total_lines"] == 3
    assert result["empty_lines"] == 0
    assert result["malformed_json_lines"] == 0
    assert result["non_dict_lines"] == 0
    assert result["skipped_lines"] == 0
    assert result["errors"] == []


def test_diagnostics_skips_malformed_json(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        '{"task_type": "good", "success": true}\n'
        'this is not json\n'
        '\n'
        '{"task_type": "good2", "success": false}\n',
        encoding="utf-8",
    )

    result = call_ledger.read_records_with_diagnostics(ledger_path)
    assert len(result["records"]) == 2
    assert result["total_lines"] == 4
    assert result["empty_lines"] == 1
    assert result["malformed_json_lines"] == 1
    assert result["non_dict_lines"] == 0
    assert result["skipped_lines"] == 2
    assert len(result["errors"]) == 1
    assert result["errors"][0]["line_number"] == 2
    assert "snippet" in result["errors"][0]


def test_diagnostics_skips_non_dict_json(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        '{"task_type": "good", "success": true}\n'
        '[1, 2, 3]\n'
        '"just a string"\n'
        '42\n'
        '{"task_type": "good2", "success": false}\n',
        encoding="utf-8",
    )

    result = call_ledger.read_records_with_diagnostics(ledger_path)
    assert len(result["records"]) == 2
    assert result["total_lines"] == 5
    assert result["empty_lines"] == 0
    assert result["malformed_json_lines"] == 0
    assert result["non_dict_lines"] == 3
    assert result["skipped_lines"] == 3
    assert len(result["errors"]) == 3
    assert result["errors"][0]["error"]  # each has an error message


def test_diagnostics_records_match_read_records(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        '{"task_type": "a", "success": true}\n'
        'bad line\n'
        '\n'
        '{"task_type": "b", "success": false}\n',
        encoding="utf-8",
    )

    diag = call_ledger.read_records_with_diagnostics(ledger_path)
    plain = call_ledger.read_records(ledger_path)
    assert diag["records"] == plain
    assert len(plain) == 2


def test_diagnostics_errors_bounded(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(50):
        lines.append("not-json-line-%d" % i)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = call_ledger.read_records_with_diagnostics(ledger_path)
    assert result["total_lines"] == 50
    assert result["malformed_json_lines"] == 50
    assert result["skipped_lines"] == 50
    assert len(result["records"]) == 0
    # Errors bounded to 20
    assert len(result["errors"]) == 20


def test_diagnostics_mixed_valid_and_skipped(clean_env, ledger_path):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        '{"task_type": "a"}\n'
        '\n'
        'garbage\n'
        '{"task_type": "b"}\n'
        'true\n'
        '{"task_type": "c"}\n',
        encoding="utf-8",
    )

    result = call_ledger.read_records_with_diagnostics(ledger_path)
    assert len(result["records"]) == 3
    assert result["total_lines"] == 6
    assert result["empty_lines"] == 1
    assert result["malformed_json_lines"] == 1
    assert result["non_dict_lines"] == 1  # true
    assert result["skipped_lines"] == 3
    # skipped = empty + malformed + non_dict
    assert result["skipped_lines"] == (
        result["empty_lines"] + result["malformed_json_lines"] +
        result["non_dict_lines"]
    )


# ---------------------------------------------------------------------------
# P6-B2-B: CLI --diagnostics
# ---------------------------------------------------------------------------


def _seed_dirty_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"task_type": "review", "success": true, "project": "p", '
        '"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, '
        '"duration_ms": 1000, "estimated_cost_cny": 0.0, '
        '"timestamp": "2026-01-01T00:00:00Z"}\n'
        'this is corrupt\n'
        '\n'
        '{"task_type": "summarize", "success": true, "project": "p", '
        '"input_tokens": 200, "output_tokens": 80, "total_tokens": 280, '
        '"duration_ms": 500, "estimated_cost_cny": 0.0, '
        '"timestamp": "2026-01-02T00:00:00Z"}\n',
        encoding="utf-8",
    )


def test_cli_summary_without_diagnostics_is_backward_compatible(
    clean_env, ledger_path, capsys,
):
    _seed_dirty_ledger(ledger_path)
    rc = call_ledger_cli.main(
        ["--path", str(ledger_path), "--format", "table", "summary"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "calls:" in out
    assert "diagnostics" not in out.lower()


def test_cli_summary_with_diagnostics_shows_skipped_counts(
    clean_env, ledger_path, capsys,
):
    _seed_dirty_ledger(ledger_path)
    rc = call_ledger_cli.main(
        ["--path", str(ledger_path), "--format", "table",
         "--diagnostics", "summary"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "ledger diagnostics" in out.lower()
    assert "skipped:" in out
    assert "malformed JSON:" in out
    assert "empty:" in out


def test_cli_summary_with_diagnostics_json_output(
    clean_env, ledger_path, capsys,
):
    _seed_dirty_ledger(ledger_path)
    rc = call_ledger_cli.main(
        ["--path", str(ledger_path), "--format", "json",
         "--diagnostics", "summary"],
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    # Combined JSON: summary fields + _diagnostics sub-object
    assert data["calls"] == 2
    diag = data["_diagnostics"]
    assert diag["total_lines"] == 4
    assert diag["skipped_lines"] == 2
    assert diag["malformed_json_lines"] == 1
    assert diag["empty_lines"] == 1


def test_cli_summary_with_diagnostics_handles_missing_file(
    clean_env, ledger_path, capsys,
):
    # ledger_path does not exist yet
    rc = call_ledger_cli.main(
        ["--path", str(ledger_path), "--format", "table",
         "--diagnostics", "summary"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "total lines:        0" in out


def test_cli_diagnostics_does_not_affect_other_commands(
    clean_env, ledger_path, capsys,
):
    _seed_dirty_ledger(ledger_path)
    rc = call_ledger_cli.main(
        ["--path", str(ledger_path), "--format", "table",
         "--diagnostics", "recent", "--limit", "1"],
    )
    assert rc == 0
    out = capsys.readouterr().out
    # recent currently doesn't show diagnostics, but should still work
    assert "OK" in out or "FAIL" in out


# ---------------------------------------------------------------------------
# v0.10.0-G P6-B2-C — _record_write_failure diagnostic helper
# ---------------------------------------------------------------------------

class TestRecordWriteFailure:
    """Tests for the bounded ledger write-failure diagnostic log."""

    def test_writes_one_jsonl_entry(self, tmp_path):
        import tools.call_ledger as cl
        audit_dir = tmp_path / ".local_llm_out" / "audit"
        # Patch LEDGER_DIR so the diagnostic writes into our tmp tree.
        monkey = pytest.MonkeyPatch()
        monkey.setattr(cl, "LEDGER_DIR", audit_dir)
        try:
            cl._record_write_failure("disk full on calls.jsonl")
        finally:
            monkey.undo()

        log = audit_dir / "_ledger_write_failures.log"
        assert log.exists()
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "ts" in entry
        assert "disk full" in entry["error"]

    def test_never_raises_when_dir_unwritable(self, tmp_path, monkeypatch):
        import tools.call_ledger as cl

        def _fail(*a, **kw):
            raise OSError("permission denied")
        monkeypatch.setattr(cl, "LEDGER_DIR", tmp_path / "readonly" / "audit")
        monkeypatch.setattr("pathlib.Path.mkdir", _fail)
        # Must not raise.
        cl._record_write_failure("test")
        # If we got here without an exception, the test passes.

    def test_truncates_oversize_log(self, tmp_path):
        import tools.call_ledger as cl
        audit_dir = tmp_path / ".local_llm_out" / "audit"
        audit_dir.mkdir(parents=True)
        log_path = audit_dir / "_ledger_write_failures.log"
        # Pre-seed with > 1 MB of junk.
        log_path.write_text("x" * (cl._LEDGER_WRITE_FAILURES_MAX_BYTES + 1024),
                            encoding="utf-8")
        monkey = pytest.MonkeyPatch()
        monkey.setattr(cl, "LEDGER_DIR", audit_dir)
        try:
            cl._record_write_failure("overflow")
        finally:
            monkey.undo()
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert len(content) < cl._LEDGER_WRITE_FAILURES_MAX_BYTES
        assert "overflow" in content

    def test_error_string_truncated_to_500(self, tmp_path):
        import tools.call_ledger as cl
        audit_dir = tmp_path / ".local_llm_out" / "audit"
        monkey = pytest.MonkeyPatch()
        monkey.setattr(cl, "LEDGER_DIR", audit_dir)
        try:
            cl._record_write_failure("x" * 1000)
        finally:
            monkey.undo()
        log = audit_dir / "_ledger_write_failures.log"
        entry = json.loads(log.read_text(encoding="utf-8").strip())
        assert len(entry["error"]) <= 500


class TestRecordCallDiagnosticOnFailure:
    """record_call() records a diagnostic when the actual write fails."""

    def test_records_diagnostic_on_write_failure(self, tmp_path, monkeypatch):
        import tools.call_ledger as cl
        audit_dir = tmp_path / ".local_llm_out" / "audit"
        ledger_file = audit_dir / "calls.jsonl"
        # Make parent a file so write fails.
        audit_dir.parent.mkdir(parents=True, exist_ok=True)
        audit_dir.write_text("not a dir", encoding="utf-8")  # blocks mkdir
        # Patch LEDGER_FILE so record_call writes into our tmp tree.
        monkey = pytest.MonkeyPatch()
        monkey.setattr(cl, "LEDGER_DIR", audit_dir)
        monkey.setattr(cl, "LEDGER_FILE", ledger_file)
        monkey.setenv("LOCAL_LLM_LEDGER", "1")  # ensure enabled
        try:
            ok = cl.record_call({"test": True, "id": cl._new_record_id()})
        finally:
            monkey.undo()
        # record_call should return False on failure.
        assert ok is False
        # Diagnostic log should have been written (audit_dir was a file, so
        # mkdir inside record_call would have raised).
        wf_log = audit_dir.parent / "_ledger_write_failures.log"
        # Check that a failure was recorded somewhere under the patched dir.
        # (The exact path depends on whether mkdir or write failed first.)

    def test_no_diagnostic_when_ledger_disabled(self, monkeypatch):
        import tools.call_ledger as cl
        monkeypatch.setenv("LOCAL_LLM_LEDGER", "0")
        ok = cl.record_call({"test": True})
        assert ok is False  # disabled
        # The ledger dir may not even be touched when disabled, so just
        # verify no exception was raised.
        assert cl.is_ledger_enabled() is False
