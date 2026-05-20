"""Tests for runtime health telemetry store (MCP Health Telemetry
Isolation P1-H.1).

The helper `tools/health_store.py` is the future home of per-call
health data currently written into
`tools/local_llm_profiles.json::_health` by
`_update_model_health` in the MCP server. P1-H.1 only adds the
helper; it has no callers yet. These tests therefore validate the
helper's own behavior contract — including the critical regression
guard that it must never touch `tools/local_llm_profiles.json`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).parent.parent / "tools"
PROJECT_ROOT = Path(__file__).parent.parent
PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"

sys.path.insert(0, str(TOOLS_DIR))

from health_store import (  # noqa: E402
    HEALTH_PATH,
    SCHEMA_VERSION,
    load_health,
    load_profile_health,
    record_invocation,
)


def _today() -> str:
    return datetime.now(timezone.utc).isoformat()[:10]


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- missing file ---

def test_load_health_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_health(path=missing) == {}


def test_load_profile_health_missing_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_profile_health("commit_reviewer", path=missing) == {}


def test_load_health_invalid_json_returns_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {", encoding="utf-8")
    assert load_health(path=bad) == {}


# --- first record / round-trip ---

def test_record_invocation_creates_file(tmp_path):
    p = tmp_path / "health.json"
    assert not p.exists()
    record_invocation("fast_summary", ok=True, elapsed_s=3.5, path=p)
    assert p.exists()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert "fast_summary" in doc["profiles"]


def test_record_invocation_round_trip(tmp_path):
    p = tmp_path / "health.json"
    record_invocation("commit_reviewer", ok=True, elapsed_s=13.7, path=p)
    h = load_profile_health("commit_reviewer", path=p)
    assert "success_rate" in h
    assert "avg_latency_s" in h
    assert "consecutive_failures" in h
    assert "_updated" in h
    assert h["_updated"] == _today()


def test_first_record_sets_latency_to_observed(tmp_path):
    """On first record, avg_latency_s default = elapsed_s, so:
    new = elapsed_s * 0.9 + elapsed_s * 0.1 == elapsed_s.
    Matches `_update_model_health` line 574: `h.get("avg_latency_s", elapsed_s)`."""
    p = tmp_path / "health.json"
    record_invocation("x", ok=True, elapsed_s=12.5, path=p)
    h = load_profile_health("x", path=p)
    assert h["avg_latency_s"] == 12.5


def test_first_record_success_rate_default_one(tmp_path):
    """On first record with ok=True, success_rate = 1.0*0.9 + 1.0*0.1 = 1.0."""
    p = tmp_path / "health.json"
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)
    h = load_profile_health("x", path=p)
    assert h["success_rate"] == 1.0


# --- weighted formulas ---

def test_weighted_success_rate_drops_on_failure(tmp_path):
    """First ok=True (rate=1.0), then ok=False:
    rate = 1.0 * 0.9 + 0.0 * 0.1 = 0.9 (rounded to 3 decimals)."""
    p = tmp_path / "health.json"
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)
    record_invocation("x", ok=False, elapsed_s=1.0, path=p)
    assert load_profile_health("x", path=p)["success_rate"] == 0.9


def test_weighted_avg_latency(tmp_path):
    """First elapsed=10.0 (lat=10.0), then elapsed=20.0:
    lat = 10.0 * 0.9 + 20.0 * 0.1 = 11.0 (rounded to 1 decimal)."""
    p = tmp_path / "health.json"
    record_invocation("x", ok=True, elapsed_s=10.0, path=p)
    record_invocation("x", ok=True, elapsed_s=20.0, path=p)
    assert load_profile_health("x", path=p)["avg_latency_s"] == 11.0


# --- consecutive_failures ---

def test_consecutive_failures_increments(tmp_path):
    p = tmp_path / "health.json"
    record_invocation("x", ok=False, elapsed_s=1.0, path=p)
    record_invocation("x", ok=False, elapsed_s=1.0, path=p)
    record_invocation("x", ok=False, elapsed_s=1.0, path=p)
    assert load_profile_health("x", path=p)["consecutive_failures"] == 3


def test_consecutive_failures_resets_on_success(tmp_path):
    p = tmp_path / "health.json"
    record_invocation("x", ok=False, elapsed_s=1.0, path=p)
    record_invocation("x", ok=False, elapsed_s=1.0, path=p)
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)
    assert load_profile_health("x", path=p)["consecutive_failures"] == 0


# --- last_timeout ---

def test_timeout_sets_last_timeout(tmp_path):
    p = tmp_path / "health.json"
    record_invocation("x", ok=False, elapsed_s=60.0, error_type="timeout", path=p)
    assert load_profile_health("x", path=p)["last_timeout"] == _today()


def test_non_timeout_does_not_overwrite_existing_last_timeout(tmp_path):
    """A previous timeout's date must survive subsequent non-timeout
    invocations (so operators can see when the last timeout was)."""
    p = tmp_path / "health.json"
    record_invocation("x", ok=False, elapsed_s=60.0, error_type="timeout", path=p)
    pinned = load_profile_health("x", path=p)["last_timeout"]
    # Subsequent ok=True non-timeout calls
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)
    record_invocation("x", ok=False, elapsed_s=1.0, error_type="other", path=p)
    assert load_profile_health("x", path=p)["last_timeout"] == pinned


def test_first_record_without_timeout_initializes_last_timeout_to_none(tmp_path):
    p = tmp_path / "health.json"
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)
    assert load_profile_health("x", path=p)["last_timeout"] is None


# --- best-effort contract ---

def test_record_invocation_never_raises_on_io_error(monkeypatch, tmp_path):
    """If os.replace fails (e.g. permissions, disk full), record_invocation
    must swallow the error rather than blow up the caller."""
    p = tmp_path / "health.json"

    import os as os_module

    def boom(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(os_module, "replace", boom)
    # Must not raise
    record_invocation("x", ok=True, elapsed_s=1.0, path=p)


def test_record_invocation_never_raises_on_empty_profile_name(tmp_path):
    p = tmp_path / "health.json"
    # Empty name short-circuits before any IO; must not raise
    record_invocation("", ok=True, elapsed_s=1.0, path=p)
    assert not p.exists()


# --- CRITICAL: profiles JSON must remain byte-for-byte unchanged ---

def test_record_invocation_does_not_modify_profiles_json(tmp_path):
    """The whole point of P1-H is to stop touching profiles JSON.
    This is the regression guard: hash the file before and after a
    record_invocation call and assert byte equality."""
    before = _hash(PROFILES_PATH)
    p = tmp_path / "health.json"
    record_invocation("commit_reviewer", ok=True, elapsed_s=14.0, path=p)
    record_invocation("commit_reviewer", ok=False, elapsed_s=14.0,
                      error_type="timeout", path=p)
    record_invocation("fast_summary", ok=True, elapsed_s=3.0, path=p)
    after = _hash(PROFILES_PATH)
    assert before == after, (
        f"record_invocation modified tools/local_llm_profiles.json "
        f"(hash before {before[:16]}..., after {after[:16]}...)"
    )


# --- isolation: helper must not import runtime modules ---

def test_helper_does_not_import_runtime_modules():
    """health_store.py must not import the MCP server, router, worker,
    or debate code — those are P1-H.2 call sites and must remain
    untouched in P1-H.1."""
    src = (TOOLS_DIR / "health_store.py").read_text(encoding="utf-8")
    for forbidden in (
        "import local_llm_router",
        "import local_llm_worker",
        "import local_llm_mcp_server",
        "import local_llm_debate",
        "from local_llm_router",
        "from local_llm_worker",
        "from local_llm_mcp_server",
        "from local_llm_debate",
    ):
        assert forbidden not in src, (
            f"health_store.py must not contain {forbidden!r} "
            f"(P1-H.1 helper-only contract)"
        )


# --- defaults ---

def test_health_path_is_under_local_llm_out():
    """HEALTH_PATH must be inside the gitignored .local_llm_out/
    directory so the runtime file never enters the working tree."""
    parts = HEALTH_PATH.parts
    assert ".local_llm_out" in parts, (
        f"HEALTH_PATH {HEALTH_PATH} must be inside .local_llm_out/"
    )
    assert HEALTH_PATH.name == "local_llm_health.json"


def test_schema_version_constant():
    assert SCHEMA_VERSION == 1
