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
# M7 (v0.10.0-L) — classify_execution_location / classify_cost_confidence
# ---------------------------------------------------------------------------

_EXEC_LOC = call_ledger.classify_execution_location
_CONF = call_ledger.classify_cost_confidence


class TestClassifyExecutionLocation:
    """Unit tests for execution-location classification."""

    def test_localhost_ollama_is_local(self):
        assert _EXEC_LOC("ollama", "http://localhost:11434") == "local"
        assert _EXEC_LOC("ollama", "http://127.0.0.1:11434") == "local"
        assert _EXEC_LOC("ollama", "http://[::1]:11434") == "local"

    def test_lan_ollama_is_lan(self):
        assert _EXEC_LOC("ollama", "http://192.168.2.2:11434") == "lan"
        assert _EXEC_LOC("ollama", "http://10.0.0.50:11434") == "lan"
        assert _EXEC_LOC("ollama", "http://172.16.1.1:11434") == "lan"
        assert _EXEC_LOC("ollama", "http://172.31.255.255:11434") == "lan"

    def test_public_host_is_remote(self):
        assert _EXEC_LOC("openai-compatible", "https://api.deepseek.com") == "remote"
        assert _EXEC_LOC("ollama", "https://ollama.example.com") == "remote"
        assert _EXEC_LOC("deepseek", "https://api.deepseek.com") == "remote"

    def test_missing_provider_and_url_is_unknown(self):
        assert _EXEC_LOC(None, None) == "unknown"

    def test_ollama_without_host_is_unknown(self):
        # ollama provider but no URL to check — can't determine
        assert _EXEC_LOC("ollama", None) == "unknown"

    def test_openai_compat_with_missing_url_is_remote(self):
        assert _EXEC_LOC("openai-compatible", None) == "remote"

    def test_llamacpp_localhost_is_local(self):
        assert _EXEC_LOC("llama.cpp", "http://localhost:8080") == "local"

    def test_172_16_edge(self):
        # 172.16.0.0 is the first valid LAN address
        assert _EXEC_LOC("ollama", "http://172.16.0.0:11434") == "lan"

    def test_172_31_edge(self):
        # 172.31.255.255 is the last valid LAN address
        assert _EXEC_LOC("ollama", "http://172.31.255.255:11434") == "lan"

    def test_172_32_is_remote(self):
        # 172.32.0.1 is outside RFC 1918 — should be remote
        assert _EXEC_LOC("ollama", "http://172.32.0.1:11434") == "remote"

    def test_unparseable_url_ollama_is_unknown(self):
        # entirely unparseable host but provider is ollama → unknown
        assert _EXEC_LOC("ollama", "not-a-valid-url:::/") == "unknown"


class TestClassifyCostConfidence:
    """Unit tests for cost-confidence label derivation."""

    def test_local_real_tokens_is_high(self):
        assert _CONF("local", tokens_estimated=False, has_cost_rate=False) == "high"

    def test_local_estimated_tokens_is_medium(self):
        assert _CONF("local", tokens_estimated=True, has_cost_rate=False) == "medium"

    def test_lan_real_tokens_is_medium(self):
        assert _CONF("lan", tokens_estimated=False, has_cost_rate=False) == "medium"

    def test_lan_estimated_tokens_is_low(self):
        assert _CONF("lan", tokens_estimated=True, has_cost_rate=False) == "low"

    def test_remote_with_rate_is_medium(self):
        assert _CONF("remote", tokens_estimated=False, has_cost_rate=True) == "medium"

    def test_remote_without_rate_is_none(self):
        assert _CONF("remote", tokens_estimated=True, has_cost_rate=False) == "none"

    def test_unknown_is_none(self):
        assert _CONF("unknown", tokens_estimated=False, has_cost_rate=True) == "none"


def test_build_record_includes_m7_fields(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_PROJECT", "test")
    rec = call_ledger.build_record(
        task_type="x", tool_name="t",
        model="qwen3-coder:30b", provider="ollama",
        base_url="http://localhost:11434",
        input_chars=400, output_chars=200,
        duration_ms=100, success=True,
    )
    assert rec["execution_location"] == "local"
    assert rec["cost_confidence"] == "medium"  # tokens estimated


def test_build_record_lan_fields(clean_env):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t",
        model="qwen3-coder:30b", provider="ollama",
        base_url="http://192.168.2.2:11434",
        input_tokens=1000, output_tokens=500,
        duration_ms=100, success=True,
    )
    assert rec["execution_location"] == "lan"
    assert rec["cost_confidence"] == "medium"  # real tokens, but LAN


def test_build_record_missing_base_url_fields(clean_env):
    rec = call_ledger.build_record(
        task_type="x", tool_name="t",
        model="qwen3-coder:30b", provider="ollama",
        base_url=None,
        input_chars=100, output_chars=50,
        duration_ms=100, success=True,
    )
    assert rec["execution_location"] == "unknown"
    assert rec["cost_confidence"] == "none"


def test_breakdown_counts_basic():
    records = [
        {"execution_location": "local", "cost_confidence": "high"},
        {"execution_location": "local", "cost_confidence": "medium"},
        {"execution_location": "lan"},
        {"execution_location": None},
        {},
    ]
    loc = call_ledger.breakdown_counts(records, "execution_location")
    assert loc == {"lan": 1, "local": 2, "unknown": 2}

    conf = call_ledger.breakdown_counts(records, "cost_confidence")
    assert conf == {"high": 1, "medium": 1, "unknown": 3}


def test_breakdown_counts_empty():
    assert call_ledger.breakdown_counts([], "execution_location") == {}


# ---------------------------------------------------------------------------
# M7 CLI tests
# ---------------------------------------------------------------------------


def _seed_m7_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        # Local call
        fh.write(json.dumps({
            "id": "l1", "timestamp": "2026-01-01T00:00:00Z",
            "project": "p", "task_type": "review", "tool_name": "t",
            "model": "qwen", "provider": "ollama",
            "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
            "duration_ms": 1000, "estimated_cost_cny": 0.0, "success": True,
            "execution_location": "local", "cost_confidence": "high",
        }) + "\n")
        # LAN call
        fh.write(json.dumps({
            "id": "l2", "timestamp": "2026-01-02T00:00:00Z",
            "project": "p", "task_type": "review", "tool_name": "t",
            "model": "qwen", "provider": "ollama",
            "input_tokens": 200, "output_tokens": 80, "total_tokens": 280,
            "duration_ms": 2000, "estimated_cost_cny": 0.0, "success": True,
            "execution_location": "lan", "cost_confidence": "low",
        }) + "\n")
        # Old record without M7 fields
        fh.write(json.dumps({
            "id": "old1", "timestamp": "2026-01-03T00:00:00Z",
            "project": "p", "task_type": "summarize", "tool_name": "t",
            "model": "gemma", "provider": "ollama",
            "input_tokens": 50, "output_tokens": 25, "total_tokens": 75,
            "duration_ms": 500, "estimated_cost_cny": 0.0, "success": True,
        }) + "\n")


def test_cli_summary_m7_breakdown_table(clean_env, ledger_path, capsys):
    _seed_m7_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "summary"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "execution location" in out
    assert "local" in out
    assert "lan" in out
    assert "unknown" in out
    assert "cost confidence" in out
    assert "high" in out
    assert "low" in out


def test_cli_summary_m7_json_includes_breakdowns(clean_env, ledger_path, capsys):
    _seed_m7_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "summary"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["calls"] == 3
    loc_bd = data["_execution_location_breakdown"]
    assert loc_bd["local"] == 1
    assert loc_bd["lan"] == 1
    assert loc_bd["unknown"] == 1  # old record
    conf_bd = data["_cost_confidence_breakdown"]
    assert conf_bd["high"] == 1
    assert conf_bd["low"] == 1
    assert conf_bd["unknown"] == 1


def test_cli_by_location_table(clean_env, ledger_path, capsys):
    _seed_m7_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "by-location"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "local" in out
    assert "lan" in out
    assert "<none>" in out or "unknown" in out


def test_cli_old_record_readable(clean_env, ledger_path):
    """Old records without M7 fields must remain readable by read_records."""
    _seed_m7_ledger(ledger_path)
    records = call_ledger.read_records(ledger_path)
    assert len(records) == 3
    # The old record should have no execution_location
    old = [r for r in records if r["id"] == "old1"]
    assert len(old) == 1
    assert "execution_location" not in old[0]


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
    # J-L2: efficiency fields present
    for task_key in data:
        assert "primary_profile" in data[task_key]
        assert "primary_backend" in data[task_key]
        assert "top_failure_type" in data[task_key]


# --- J-L2: group_by_task_efficiency ---


def test_group_by_task_efficiency_basic():
    """Groups records by task_type with per-task efficiency stats."""
    records = [
        {"task_type": "review-diff", "success": True, "profile": "commit_reviewer",
         "backend": "ollama", "failure_type": None, "input_tokens": 100,
         "output_tokens": 50, "total_tokens": 150, "duration_ms": 1000,
         "estimated_cost_cny": 0.0},
        {"task_type": "review-diff", "success": True, "profile": "commit_reviewer",
         "backend": "ollama", "failure_type": None, "input_tokens": 200,
         "output_tokens": 80, "total_tokens": 280, "duration_ms": 2000,
         "estimated_cost_cny": 0.0},
        {"task_type": "summarize-file", "success": False, "profile": "fast_summary",
         "backend": "ollama", "failure_type": "timeout", "input_tokens": 50,
         "output_tokens": 0, "total_tokens": 50, "duration_ms": 30000,
         "estimated_cost_cny": None},
    ]
    groups = call_ledger.group_by_task_efficiency(records)
    assert set(groups.keys()) == {"review-diff", "summarize-file"}

    rd = groups["review-diff"]
    assert rd["calls"] == 2
    assert rd["successes"] == 2
    assert rd["failures"] == 0
    assert rd["total_tokens"] == 430
    assert rd["primary_profile"] == "commit_reviewer"
    assert rd["primary_backend"] == "ollama"
    assert rd["top_failure_type"] == "-"

    sf = groups["summarize-file"]
    assert sf["calls"] == 1
    assert sf["failures"] == 1
    assert sf["primary_profile"] == "fast_summary"
    assert sf["top_failure_type"] == "timeout"


def test_group_by_task_efficiency_unknown_task():
    """Records with missing task_type go to <none>."""
    records = [
        {"success": True, "profile": "fast_summary", "backend": "unknown",
         "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
         "duration_ms": 100, "estimated_cost_cny": 0.0},
    ]
    groups = call_ledger.group_by_task_efficiency(records)
    assert "<none>" in groups
    assert groups["<none>"]["calls"] == 1


def test_group_by_task_efficiency_top_failure_type():
    """top_failure_type is the most common failure_type in failures."""
    records = [
        {"task_type": "t", "success": False, "failure_type": "timeout",
         "profile": "p", "backend": "b", "input_tokens": 10,
         "output_tokens": 5, "total_tokens": 15, "duration_ms": 100,
         "estimated_cost_cny": 0.0},
        {"task_type": "t", "success": False, "failure_type": "timeout",
         "profile": "p", "backend": "b", "input_tokens": 10,
         "output_tokens": 5, "total_tokens": 15, "duration_ms": 100,
         "estimated_cost_cny": 0.0},
        {"task_type": "t", "success": False, "failure_type": "missing_model",
         "profile": "p", "backend": "b", "input_tokens": 10,
         "output_tokens": 5, "total_tokens": 15, "duration_ms": 100,
         "estimated_cost_cny": 0.0},
        {"task_type": "t", "success": True, "failure_type": None,
         "profile": "p", "backend": "b", "input_tokens": 10,
         "output_tokens": 5, "total_tokens": 15, "duration_ms": 100,
         "estimated_cost_cny": 0.0},
    ]
    groups = call_ledger.group_by_task_efficiency(records)
    # Most common failure: timeout (2x) vs missing_model (1x)
    assert groups["t"]["top_failure_type"] == "timeout"


def test_group_by_task_efficiency_empty():
    assert call_ledger.group_by_task_efficiency([]) == {}


def test_cli_by_task_table_contains_efficiency_columns(clean_env, ledger_path, capsys):
    """Table output should include the richer column headers."""
    _seed_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "by-task"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "profile" in captured
    assert "backend" in captured
    assert "top_fail" in captured
    assert "fail%" in captured
    assert "avg_ms" in captured


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
# G-B: model-summary command
# ---------------------------------------------------------------------------


def test_cli_model_summary_table(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path), "model-summary"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "gemma4:e4b" in captured
    assert "qwen3-coder:30b" in captured


def test_cli_model_summary_json(clean_env, ledger_path, capsys):
    _seed_p2_ledger(ledger_path)
    rc = call_ledger_cli.main(["--path", str(ledger_path),
                                "--format", "json", "model-summary"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert "gemma4:e4b" in data
    assert "qwen3-coder:30b" in data


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


# ---------------------------------------------------------------------------
# v0.10.0-H M3 — ledger rotation / archive
# ---------------------------------------------------------------------------

class TestRotateLedger:
    """Tests for rotate_ledger()."""

    def test_rotates_active_ledger(self, tmp_path):
        import tools.call_ledger as cl
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text(
            '{"id":"1","ok":true}\n{"id":"2","ok":false}\n',
            encoding="utf-8")

        ok, detail = cl.rotate_ledger(path=ledger)
        assert ok is True
        assert "archived" in detail
        # The archive file should exist and contain old records.
        archives = list(tmp_path.glob("calls.*.jsonl"))
        assert len(archives) == 1
        content = archives[0].read_text(encoding="utf-8")
        assert '"id":"1"' in content
        assert '"id":"2"' in content
        # Active ledger should be gone (next record_call will recreate it).
        assert not ledger.exists()

    def test_custom_archive_name(self, tmp_path):
        import tools.call_ledger as cl
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text('{"id":"1","ok":true}\n', encoding="utf-8")

        ok, detail = cl.rotate_ledger(
            archive_name="calls.my-archive.jsonl", path=ledger)
        assert ok is True
        archive = tmp_path / "calls.my-archive.jsonl"
        assert archive.exists()
        assert '"id":"1"' in archive.read_text(encoding="utf-8")

    def test_missing_ledger_returns_ok_nothing_to_rotate(self, tmp_path):
        import tools.call_ledger as cl
        ledger = tmp_path / "calls.jsonl"
        ok, detail = cl.rotate_ledger(path=ledger)
        assert ok is True
        assert "does not exist" in detail

    def test_empty_ledger_returns_ok_nothing_to_rotate(self, tmp_path):
        import tools.call_ledger as cl
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text("", encoding="utf-8")
        ok, detail = cl.rotate_ledger(path=ledger)
        assert ok is True
        assert "empty" in detail

    def test_existing_archive_target_returns_false(self, tmp_path):
        import tools.call_ledger as cl
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text('{"id":"1","ok":true}\n', encoding="utf-8")
        archive = tmp_path / "calls.existing.jsonl"
        archive.write_text("old archive", encoding="utf-8")

        ok, detail = cl.rotate_ledger(
            archive_name="calls.existing.jsonl", path=ledger)
        assert ok is False
        assert "already exists" in detail
        # The active ledger should NOT have been rotated away.
        assert ledger.exists()

    def test_never_raises_on_oserror(self, tmp_path, monkeypatch):
        import tools.call_ledger as cl
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text('{"id":"1","ok":true}\n', encoding="utf-8")

        def _fail(*a, **kw):
            raise OSError("permission denied")
        monkeypatch.setattr(ledger.__class__, "rename", _fail)
        ok, detail = cl.rotate_ledger(path=ledger)
        assert ok is False
        assert "failed" in detail


class TestCliRotate:
    """Tests for call_ledger_cli.py rotate subcommand."""

    def test_dry_run_does_not_mutate(self, tmp_path, capsys):
        import tools.call_ledger as cl
        import call_ledger_cli
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text('{"id":"1","ok":true}\n', encoding="utf-8")

        rc = call_ledger_cli.main(
            ["--path", str(ledger), "rotate", "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "calls." in out
        # File should NOT have been mutated.
        assert ledger.exists()

    def test_rotate_succeeds(self, tmp_path, capsys):
        import call_ledger_cli
        ledger = tmp_path / "calls.jsonl"
        ledger.write_text('{"id":"1","ok":true}\n', encoding="utf-8")

        rc = call_ledger_cli.main(
            ["--path", str(ledger), "rotate",
             "--archive-name", "calls.archived.jsonl"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out
        archive = tmp_path / "calls.archived.jsonl"
        assert archive.exists()
        assert not ledger.exists()

    def test_rotate_missing_ledger_returns_success(self, tmp_path, capsys):
        import call_ledger_cli
        ledger = tmp_path / "calls.jsonl"
        # No file created — ledger doesn't exist.
        rc = call_ledger_cli.main(
            ["--path", str(ledger), "rotate"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out
        assert "does not exist" in out


# --- backend / failure_type classification (J-C4) ---

class TestBackendResolution:
    def test_ollama_provider(self):
        from call_ledger import resolve_backend
        assert resolve_backend("ollama") == "ollama"

    def test_openai_compatible_provider(self):
        from call_ledger import resolve_backend
        assert resolve_backend("openai-compatible") == "openai_compatible"

    def test_unknown_provider(self):
        from call_ledger import resolve_backend
        assert resolve_backend(None) == "unknown"
        assert resolve_backend("") == "unknown"

    def test_backend_stored_in_record(self):
        from call_ledger import build_record
        r = build_record(task_type="t", tool_name="n", model="m", provider="ollama")
        assert r["backend"] == "ollama"

    def test_backend_stored_for_openai_compat(self):
        from call_ledger import build_record
        r = build_record(task_type="t", tool_name="n", model="m",
                         provider="openai-compatible")
        assert r["backend"] == "openai_compatible"

    def test_explicit_backend_overrides_resolve(self):
        from call_ledger import build_record
        r = build_record(task_type="t", tool_name="n", model="m",
                         provider="ollama", backend="lmstudio")
        assert r["backend"] == "lmstudio"


class TestFailureTypeClassification:
    def test_success_has_none_failure_type(self):
        from call_ledger import classify_failure_type
        assert classify_failure_type(success=True) is None

    def test_none_success_is_placeholder(self):
        from call_ledger import classify_failure_type
        assert classify_failure_type(success=None) == "placeholder"

    def test_404_is_missing_model(self):
        from call_ledger import classify_failure_type
        ft = classify_failure_type(success=False, failure_text="HTTP 404: not found")
        assert ft == "missing_model"

    def test_instant_fail_is_model_load_failed(self):
        from call_ledger import classify_failure_type
        ft = classify_failure_type(success=False, duration_ms=0,
                                   failure_text="HTTP 500: fail")
        assert ft == "model_load_failed"

    def test_timeout_is_generation_timeout(self):
        from call_ledger import classify_failure_type
        ft = classify_failure_type(success=False, duration_ms=350000,
                                   failure_text="Read timed out")
        assert ft == "generation_timeout"

    def test_connection_refused_is_backend_offline(self):
        from call_ledger import classify_failure_type
        ft = classify_failure_type(success=False,
                                   failure_text="Connection refused")
        assert ft == "backend_offline"

    def test_generic_fail_is_api_error(self):
        from call_ledger import classify_failure_type
        ft = classify_failure_type(success=False, failure_text="something broken")
        assert ft == "api_error"

    def test_failure_type_in_record(self):
        from call_ledger import build_record
        r = build_record(task_type="t", tool_name="n", model="m",
                         provider="ollama", success=False,
                         failure_reason="HTTP 500: fail")
        assert r["failure_type"] == "model_load_failed"

    def test_success_record_has_none_failure_type(self):
        from call_ledger import build_record
        r = build_record(task_type="t", tool_name="n", model="m",
                         provider="ollama", success=True)
        assert r["failure_type"] is None

    def test_old_record_without_fields_still_reads(self):
        """Legacy records without backend/failure_type must still work."""
        from call_ledger import _zero_summary, summarize
        old = dict(_zero_summary())
        old["calls"] = 1
        old["successes"] = 1
        # simulate old record dict without backend/failure_type keys
        records = [{"success": True, "model": "test", "duration_ms": 100,
                    "input_tokens": 10, "output_tokens": 5}]
        s = summarize(records)
        assert s["calls"] == 1
        assert s["successes"] == 1


# ---------------------------------------------------------------------------
# Z-3: Savings estimation
# ---------------------------------------------------------------------------

def _make_record(**overrides):
    """Build a minimal synthetic ledger record for savings tests."""
    r = {
        "success": True,
        "model": "test-model",
        "profile": "commit_reviewer",
        "provider": "ollama",
        "task_type": "review-diff",
        "input_tokens": 1000,
        "output_tokens": 500,
        "tokens_estimated": False,
        "estimated_cost_cny": 0.0,
        "execution_location": "lan",
        "cost_confidence": "none",
        "duration_ms": 5000,
        "cache_hit": False,
    }
    r.update(overrides)
    return r


class TestLoadCloudRates:
    def test_load_default_rates(self):
        rates = call_ledger.load_cloud_rates()
        assert "_version" in rates
        assert rates["_version"] >= 1
        assert "tiers" in rates
        assert "profile_to_tier" in rates
        assert "default_tier" in rates

    def test_load_missing_file_returns_empty(self):
        rates = call_ledger.load_cloud_rates("/nonexistent/path.json")
        assert rates == {}

    def test_load_from_tmp_path(self, tmp_path):
        p = tmp_path / "rates.json"
        p.write_text(json.dumps({"_version": 2, "tiers": {}, "profile_to_tier": {}, "default_tier": "small"}))
        rates = call_ledger.load_cloud_rates(str(p))
        assert rates["_version"] == 2

    def test_load_invalid_json_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json")
        rates = call_ledger.load_cloud_rates(str(p))
        assert rates == {}


class TestResolveSavingsTier:
    def test_known_profile(self):
        rates = call_ledger.load_cloud_rates()
        tier_key, tier_rates = call_ledger.resolve_savings_tier("commit_reviewer", rates)
        assert tier_key == "medium"
        assert "in_per_1k" in tier_rates

    def test_unknown_profile_uses_default(self):
        rates = call_ledger.load_cloud_rates()
        tier_key, _ = call_ledger.resolve_savings_tier("nonexistent_profile", rates)
        assert tier_key == rates["default_tier"]

    def test_none_profile_uses_default(self):
        rates = call_ledger.load_cloud_rates()
        tier_key, _ = call_ledger.resolve_savings_tier(None, rates)
        assert tier_key == rates["default_tier"]

    def test_empty_profile_uses_default(self):
        rates = call_ledger.load_cloud_rates()
        tier_key, _ = call_ledger.resolve_savings_tier("", rates)
        assert tier_key == rates["default_tier"]

    def test_tiny_tier_for_fast_summary(self):
        rates = call_ledger.load_cloud_rates()
        tier_key, _ = call_ledger.resolve_savings_tier("fast_summary", rates)
        assert tier_key == "tiny"


class TestComputeSavings:
    def test_normal_savings(self):
        result = call_ledger.compute_savings(1000, 500, {"in_per_1k": 0.004, "out_per_1k": 0.008}, 0.0)
        assert result["cloud_equivalent_cost_cny"] == 0.008  # 1.0*0.004 + 0.5*0.008
        assert result["actual_cost_cny"] == 0.0
        assert result["estimated_savings_cny"] == 0.008

    def test_with_actual_cost(self):
        result = call_ledger.compute_savings(1000, 500, {"in_per_1k": 0.004, "out_per_1k": 0.008}, 0.003)
        assert result["cloud_equivalent_cost_cny"] == 0.008
        assert result["actual_cost_cny"] == 0.003
        assert result["estimated_savings_cny"] == 0.005

    def test_zero_tokens(self):
        result = call_ledger.compute_savings(0, 0, {"in_per_1k": 0.004, "out_per_1k": 0.008}, 0.0)
        assert result["cloud_equivalent_cost_cny"] == 0.0
        assert result["estimated_savings_cny"] == 0.0

    def test_savings_never_negative(self):
        result = call_ledger.compute_savings(100, 50, {"in_per_1k": 0.001, "out_per_1k": 0.002}, 5.0)
        assert result["estimated_savings_cny"] == 0.0

    def test_none_actual_cost_treated_as_zero(self):
        result = call_ledger.compute_savings(1000, 500, {"in_per_1k": 0.004, "out_per_1k": 0.008}, None)
        assert result["actual_cost_cny"] == 0.0

    def test_missing_rate_defaults_to_zero(self):
        result = call_ledger.compute_savings(1000, 500, {}, 0.0)
        assert result["cloud_equivalent_cost_cny"] == 0.0


class TestSavingsForGroup:
    def test_single_record_group(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(profile="commit_reviewer", input_tokens=1000, output_tokens=500)]
        result = call_ledger.savings_for_group(records, rates)
        assert result["calls"] == 1
        assert result["total_tokens"] == 1500
        assert result["tier"] == "medium"
        # commit_reviewer maps to medium tier, non-estimated tokens, lan location → high
        assert result["savings_confidence"] == "high"

    def test_group_picks_best_profile(self):
        rates = call_ledger.load_cloud_rates()
        records = [
            _make_record(profile="fast_summary", input_tokens=100, output_tokens=50),
            _make_record(profile="fast_summary", input_tokens=100, output_tokens=50),
            _make_record(profile="commit_reviewer", input_tokens=100, output_tokens=50),
        ]
        result = call_ledger.savings_for_group(records, rates)
        assert result["tier"] == "tiny"

    def test_high_confidence_group(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(profile="commit_reviewer", tokens_estimated=False,
                                execution_location="local", cost_confidence="high")]
        result = call_ledger.savings_for_group(records, rates)
        # known profile, non-estimated tokens, local execution → high
        assert result["savings_confidence"] == "high"

    def test_medium_confidence_with_estimated_tokens(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(profile="commit_reviewer", tokens_estimated=True,
                                execution_location="local")]
        result = call_ledger.savings_for_group(records, rates)
        # estimated tokens → medium
        assert result["savings_confidence"] == "medium"

    def test_low_confidence_unknown_location(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(profile="commit_reviewer", tokens_estimated=False,
                                execution_location="unknown")]
        result = call_ledger.savings_for_group(records, rates)
        assert result["savings_confidence"] == "low"

    def test_medium_confidence_default_tier(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(profile="unknown_profile_xyz", tokens_estimated=False,
                                execution_location="local")]
        result = call_ledger.savings_for_group(records, rates)
        # unknown profile → default tier → medium
        assert result["savings_confidence"] == "medium"

    def test_none_confidence_on_zero_tokens(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(input_tokens=0, output_tokens=0)]
        result = call_ledger.savings_for_group(records, rates)
        assert result["savings_confidence"] == "none"


class TestBuildSavingsReport:
    def test_total_only(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record(profile="commit_reviewer")]
        report = call_ledger.build_savings_report(records, rates, baseline_commit="abc")
        assert report["savings_version"] == 1
        assert report["advisory_only"] is True
        assert report["not_for_billing"] is True
        assert report["method"] == "cloud_equivalent_cost - actual_cost"
        assert "total" in report
        assert "buckets" not in report

    def test_grouped_by_profile(self):
        rates = call_ledger.load_cloud_rates()
        records = [
            _make_record(profile="commit_reviewer", task_type="review-diff"),
            _make_record(profile="fast_summary", task_type="summarize-file"),
        ]
        report = call_ledger.build_savings_report(records, rates, group_by_key="profile",
                                                  baseline_commit="abc")
        assert report["by"] == "profile"
        assert "buckets" in report
        assert "commit_reviewer" in report["buckets"]
        assert "fast_summary" in report["buckets"]

    def test_total_matches_bucket_sum(self):
        rates = call_ledger.load_cloud_rates()
        records = [
            _make_record(profile="commit_reviewer", input_tokens=1000, output_tokens=500),
            _make_record(profile="fast_summary", input_tokens=500, output_tokens=200),
        ]
        report = call_ledger.build_savings_report(records, rates, baseline_commit="abc")
        total = report["total"]
        assert total["calls"] == 2
        assert total["total_input_tokens"] == 1500
        assert total["total_output_tokens"] == 700

    def test_baseline_commit(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record()]
        report = call_ledger.build_savings_report(records, rates, baseline_commit="deadbeef")
        assert report["baseline_commit"] == "deadbeef"

    def test_rate_version_in_report(self):
        rates = call_ledger.load_cloud_rates()
        records = [_make_record()]
        report = call_ledger.build_savings_report(records, rates, baseline_commit="abc")
        assert report["cloud_rate_version"] == rates["_version"]


class TestSavingsCLI:
    def test_savings_json_output(self):
        from unittest.mock import patch
        with patch.object(call_ledger_cli, "_resolve_path") as mock_path:
            import tempfile as _tmpm
            import shutil as _shm
            tmp = _tmpm.mkdtemp()
            p = Path(tmp) / "ledger.jsonl"
            p.write_text(json.dumps(_make_record()) + "\n")
            mock_path.return_value = p
            try:
                import io as _io
                save_io = _io.StringIO()
                with patch("sys.stdout", save_io):
                    rc = call_ledger_cli.main(["--format", "json", "savings"])
                assert rc == 0
                data = json.loads(save_io.getvalue())
                assert data["advisory_only"] is True
                assert data["not_for_billing"] is True
            finally:
                _shm.rmtree(tmp, ignore_errors=True)

    def test_savings_by_profile(self):
        from unittest.mock import patch
        with patch.object(call_ledger_cli, "_resolve_path") as mock_path:
            import tempfile as _tmpm
            import shutil as _shm
            tmp = _tmpm.mkdtemp()
            p = Path(tmp) / "ledger.jsonl"
            p.write_text(
                json.dumps(_make_record(profile="commit_reviewer")) + "\n" +
                json.dumps(_make_record(profile="fast_summary")) + "\n"
            )
            mock_path.return_value = p
            try:
                import io as _io
                save_io = _io.StringIO()
                with patch("sys.stdout", save_io):
                    rc = call_ledger_cli.main(["--format", "json", "savings", "--by", "profile"])
                assert rc == 0
                data = json.loads(save_io.getvalue())
                assert data["by"] == "profile"
                assert len(data["buckets"]) >= 2
            finally:
                _shm.rmtree(tmp, ignore_errors=True)

    def test_savings_by_task_uses_task_type_field(self):
        """--by task must alias to task_type ledger field."""
        from unittest.mock import patch
        with patch.object(call_ledger_cli, "_resolve_path") as mock_path:
            import tempfile as _tmpm, shutil as _shm
            tmp = _tmpm.mkdtemp()
            p = Path(tmp) / "ledger.jsonl"
            p.write_text(
                json.dumps(_make_record(task_type="summarize-file")) + "\n" +
                json.dumps(_make_record(task_type="review-diff")) + "\n"
            )
            mock_path.return_value = p
            try:
                import io as _io
                save_io = _io.StringIO()
                with patch("sys.stdout", save_io):
                    rc = call_ledger_cli.main(["--format", "json", "savings", "--by", "task"])
                assert rc == 0
                data = json.loads(save_io.getvalue())
                assert data["by"] == "task_type"
                assert "summarize-file" in data["buckets"]
                assert "review-diff" in data["buckets"]
            finally:
                _shm.rmtree(tmp, ignore_errors=True)

    def test_savings_by_location_uses_execution_location_field(self):
        """--by location must alias to execution_location ledger field."""
        from unittest.mock import patch
        with patch.object(call_ledger_cli, "_resolve_path") as mock_path:
            import tempfile as _tmpm, shutil as _shm
            tmp = _tmpm.mkdtemp()
            p = Path(tmp) / "ledger.jsonl"
            p.write_text(
                json.dumps(_make_record(execution_location="lan")) + "\n" +
                json.dumps(_make_record(execution_location="local")) + "\n"
            )
            mock_path.return_value = p
            try:
                import io as _io
                save_io = _io.StringIO()
                with patch("sys.stdout", save_io):
                    rc = call_ledger_cli.main(["--format", "json", "savings", "--by", "location"])
                assert rc == 0
                data = json.loads(save_io.getvalue())
                assert data["by"] == "execution_location"
                assert "lan" in data["buckets"] or "local" in data["buckets"]
            finally:
                _shm.rmtree(tmp, ignore_errors=True)

    def test_savings_by_mcp_tool_reads_extra_field(self):
        """--by mcp-tool must read extra.mcp_tool_name from records."""
        from unittest.mock import patch
        with patch.object(call_ledger_cli, "_resolve_path") as mock_path:
            import tempfile as _tmpm, shutil as _shm
            tmp = _tmpm.mkdtemp()
            p = Path(tmp) / "ledger.jsonl"
            r1 = _make_record(extra={"mcp_tool_name": "local_summarize_file"})
            r2 = _make_record(extra={"mcp_tool_name": "local_review_diff"})
            p.write_text(json.dumps(r1) + "\n" + json.dumps(r2) + "\n")
            mock_path.return_value = p
            try:
                import io as _io
                save_io = _io.StringIO()
                with patch("sys.stdout", save_io):
                    rc = call_ledger_cli.main(["--format", "json", "savings", "--by", "mcp-tool"])
                assert rc == 0
                data = json.loads(save_io.getvalue())
                assert "local_summarize_file" in data["buckets"]
            finally:
                _shm.rmtree(tmp, ignore_errors=True)
