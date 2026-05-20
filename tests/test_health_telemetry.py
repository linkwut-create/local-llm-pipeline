"""Integration tests for the switched health telemetry path
(MCP Health Telemetry Isolation P1-H.2).

P1-H.1 added the helper `tools/health_store.py`. P1-H.2 swung the
production call sites — `_update_model_health` and `_profile_is_healthy`
in the MCP server, and `is_profile_healthy` in the router — to read
and write the runtime health file instead of touching
`tools/local_llm_profiles.json`.

These tests prove the switch is in effect:
- profiles JSON is no longer mutated by `_update_model_health`
- the runtime file IS mutated
- router/MCP health readers honor the runtime data
- the router still accepts injected `health_data` and falls back to
  legacy `profile["_health"]` for synthetic-dict tests in
  `tests/test_layer4_quality.py`
- profiles JSON contains no `_health` blocks anymore
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).parent.parent / "tools"
PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"

sys.path.insert(0, str(TOOLS_DIR))

import health_store  # noqa: E402
import local_llm_router  # noqa: E402


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def redirect_health(monkeypatch, tmp_path):
    """Point health_store.HEALTH_PATH at a tmp file so tests neither
    read nor pollute the real .local_llm_out/local_llm_health.json."""
    tmp_health = tmp_path / "health.json"
    monkeypatch.setattr(health_store, "HEALTH_PATH", tmp_health)
    return tmp_health


# --- writer no longer touches profiles JSON ---

def test_update_model_health_does_not_modify_profiles_json(redirect_health):
    """The behavior change of P1-H.2 — proven empirically by hashing
    profiles JSON across an `_update_model_health` call."""
    import local_llm_mcp_server as mcp
    before = _hash(PROFILES_PATH)
    mcp._update_model_health("commit_reviewer", ok=True, elapsed_s=14.0)
    mcp._update_model_health("fast_summary", ok=False, elapsed_s=60.0,
                             error_type="timeout")
    mcp._update_model_health("diff_reviewer", ok=True, elapsed_s=3.6)
    after = _hash(PROFILES_PATH)
    assert before == after, (
        f"_update_model_health modified profiles JSON "
        f"(before {before[:16]}..., after {after[:16]}...)"
    )


def test_update_model_health_writes_runtime_file(redirect_health):
    import local_llm_mcp_server as mcp
    assert not redirect_health.exists()
    mcp._update_model_health("commit_reviewer", ok=True, elapsed_s=14.0)
    assert redirect_health.exists()


def test_update_model_health_runtime_contains_profile(redirect_health):
    import local_llm_mcp_server as mcp
    mcp._update_model_health("fast_summary", ok=True, elapsed_s=3.5)
    doc = json.loads(redirect_health.read_text(encoding="utf-8"))
    assert "fast_summary" in doc["profiles"]
    h = doc["profiles"]["fast_summary"]
    assert "success_rate" in h
    assert "avg_latency_s" in h
    assert "consecutive_failures" in h


# --- MCP-side _profile_is_healthy reads runtime ---

def test_profile_is_healthy_missing_runtime_returns_healthy(redirect_health):
    """No runtime data → assumed healthy. Matches legacy default."""
    import local_llm_mcp_server as mcp
    # commit_reviewer has no llama.cpp _env, so probe path is skipped
    assert mcp._profile_is_healthy("commit_reviewer") is True


def test_profile_is_healthy_unhealthy_on_consecutive_failures(redirect_health):
    import local_llm_mcp_server as mcp
    # Drive consecutive_failures to >= 2
    mcp._update_model_health("commit_reviewer", ok=False, elapsed_s=10.0)
    mcp._update_model_health("commit_reviewer", ok=False, elapsed_s=10.0)
    assert mcp._profile_is_healthy("commit_reviewer") is False


def test_profile_is_healthy_unhealthy_on_low_success_rate(redirect_health):
    """Seed the runtime file directly so we hit the
    success_rate < 0.5 branch without driving 5+ failures."""
    redirect_health.parent.mkdir(parents=True, exist_ok=True)
    redirect_health.write_text(json.dumps({
        "schema_version": 1,
        "profiles": {
            "commit_reviewer": {
                "success_rate": 0.4,
                "avg_latency_s": 14.0,
                "consecutive_failures": 0,
                "_updated": "2026-05-20"
            }
        }
    }), encoding="utf-8")
    import local_llm_mcp_server as mcp
    assert mcp._profile_is_healthy("commit_reviewer") is False


# --- router is_profile_healthy with injected health_data ---

def test_router_is_profile_healthy_with_injected_runtime_doc():
    """Inject a full runtime-shape doc `{"profiles": {name: {...}}}`."""
    profiles_data = {"profiles": {"x": {"model": "m"}}}
    health_data = {"profiles": {"x": {"consecutive_failures": 3,
                                       "success_rate": 0.9}}}
    assert local_llm_router.is_profile_healthy(
        "x", profiles_data, health_data=health_data
    ) is False


def test_router_is_profile_healthy_with_flat_health_data():
    """Inject a flat `{name: {...}}` map (shape variant accepted)."""
    profiles_data = {"profiles": {"x": {"model": "m"}}}
    health_data = {"x": {"consecutive_failures": 0, "success_rate": 0.4}}
    assert local_llm_router.is_profile_healthy(
        "x", profiles_data, health_data=health_data
    ) is False


def test_router_is_profile_healthy_injected_healthy():
    profiles_data = {"profiles": {"x": {"model": "m"}}}
    health_data = {"x": {"consecutive_failures": 0, "success_rate": 0.95}}
    assert local_llm_router.is_profile_healthy(
        "x", profiles_data, health_data=health_data
    ) is True


def test_router_is_profile_healthy_missing_health_defaults_healthy(
    redirect_health, monkeypatch
):
    """No injected data, no runtime data, no legacy `_health` → healthy."""
    profiles_data = {"profiles": {"x": {"model": "m"}}}
    # The redirect_health fixture pointed health_store.HEALTH_PATH at a
    # path that doesn't exist, so the helper returns {}. But the router
    # imports health_store inside _resolve_health, picking up the same
    # module. Verify behavior:
    assert local_llm_router.is_profile_healthy("x", profiles_data) is True


def test_router_falls_back_to_legacy_profile_health(redirect_health):
    """When no runtime data exists, the router must still honor a
    synthetic `profile["_health"]` block. Keeps existing test_layer4
    quality tests valid."""
    profiles_data = {
        "profiles": {
            "x": {
                "model": "m",
                "_health": {"consecutive_failures": 3, "success_rate": 0.95},
            }
        }
    }
    assert local_llm_router.is_profile_healthy("x", profiles_data) is False


def test_router_runtime_takes_priority_over_legacy(redirect_health):
    """If runtime data is present, it must win over the legacy
    `_health` field. Defensive: the legacy field should be gone in
    production anyway, but if both somehow exist, runtime is
    authoritative."""
    redirect_health.parent.mkdir(parents=True, exist_ok=True)
    redirect_health.write_text(json.dumps({
        "schema_version": 1,
        "profiles": {
            "x": {"consecutive_failures": 0, "success_rate": 0.95}
        }
    }), encoding="utf-8")
    profiles_data = {
        "profiles": {
            "x": {
                "model": "m",
                "_health": {"consecutive_failures": 5, "success_rate": 0.1},
            }
        }
    }
    # Reload router so its lazy import of health_store picks up the
    # redirected HEALTH_PATH (monkeypatch already applied to the
    # module object; reload not strictly needed but defensive).
    importlib.reload(local_llm_router)
    assert local_llm_router.is_profile_healthy("x", profiles_data) is True


# --- profiles JSON has no _health remaining ---

def test_profiles_json_has_no_health_blocks():
    """The one-time cleanup of `_health` in P1-H.2 must hold:
    static profile config should not carry per-call telemetry."""
    profiles = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    leaked = [
        name for name, p in profiles.get("profiles", {}).items()
        if "_health" in p
    ]
    assert leaked == [], (
        f"profiles JSON still contains _health for: {leaked}"
    )
