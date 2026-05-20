"""Tests for the P1-H.3 switch of `cmd_health_report` (router) and
`auto_tune_recommendations` (update_profiles_from_ollama).

After P1-H.2 the production health data lives in
`.local_llm_out/local_llm_health.json`, not in
`tools/local_llm_profiles.json`. P1-H.3 swings the two remaining
consumers — the `health-report` CLI command and the `--auto-tune`
recommendation logic — onto the runtime store, while keeping a
synthetic-dict fallback for backward-compatible tests.

These tests assert:
- cmd_health_report reads runtime success_rate / avg_latency_s /
  consecutive_failures and tolerates a missing runtime file
- auto_tune_recommendations uses runtime health and falls back to
  legacy `profile["_health"]` for synthetic-dict callers
- Running either function leaves `tools/local_llm_profiles.json`
  byte-for-byte unchanged
- `tools/local_llm_profiles.json` still has no `_health` blocks
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).parent.parent / "tools"
PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"

sys.path.insert(0, str(TOOLS_DIR))

import health_store  # noqa: E402
import local_llm_router  # noqa: E402
import update_profiles_from_ollama as upo  # noqa: E402


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def redirect_health(monkeypatch, tmp_path):
    """Point health_store.HEALTH_PATH at a tmp file so tests neither
    read nor pollute the real runtime health file."""
    tmp_health = tmp_path / "health.json"
    monkeypatch.setattr(health_store, "HEALTH_PATH", tmp_health)
    return tmp_health


def _seed_runtime(path: Path, profiles_health: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "_updated": "2026-05-20",
        "profiles": profiles_health,
    }), encoding="utf-8")


# --- cmd_health_report: runtime data ---

def test_health_report_uses_runtime_data(redirect_health, capsys):
    _seed_runtime(redirect_health, {
        "commit_reviewer": {
            "success_rate": 0.95,
            "avg_latency_s": 14.0,
            "last_timeout": None,
            "consecutive_failures": 0,
            "_updated": "2026-05-20",
        },
    })
    rc = local_llm_router.cmd_health_report()
    assert rc == 0
    out = capsys.readouterr().out
    # Profile listed; success rate from runtime; not "No health data"
    assert "commit_reviewer" in out
    assert "95.0%" in out
    assert "14s" in out


def test_health_report_status_degrades_with_consecutive_failures(
    redirect_health, capsys
):
    _seed_runtime(redirect_health, {
        "commit_reviewer": {
            "success_rate": 0.6,
            "avg_latency_s": 14.0,
            "consecutive_failures": 4,
            "_updated": "2026-05-20",
        },
    })
    local_llm_router.cmd_health_report()
    out = capsys.readouterr().out
    # success_rate < 0.7 → DEGRADED label
    assert "DEGRADED" in out


def test_health_report_tolerates_missing_runtime(redirect_health, capsys):
    """No runtime file → all profiles report as 'No health data', no crash."""
    assert not redirect_health.exists()
    rc = local_llm_router.cmd_health_report()
    assert rc == 0
    out = capsys.readouterr().out
    # Look for the summary line; every profile should be in no_data bucket
    # because profiles JSON has no `_health` blocks after P1-H.2.
    assert "No health data:" in out


def test_health_report_does_not_modify_profiles_json(redirect_health):
    """Byte-equality regression guard — the report must be read-only
    against `tools/local_llm_profiles.json`."""
    _seed_runtime(redirect_health, {
        "fast_summary": {"success_rate": 1.0, "avg_latency_s": 3.0,
                          "consecutive_failures": 0, "_updated": "2026-05-20"}
    })
    before = _hash(PROFILES_PATH)
    local_llm_router.cmd_health_report()
    after = _hash(PROFILES_PATH)
    assert before == after


def test_health_report_runtime_presence_wins_over_legacy(
    redirect_health, capsys, monkeypatch
):
    """Runtime should win by *presence* of the key, not truthiness.
    If the runtime explicitly carries an empty dict for a profile,
    the report should NOT silently fall back to stale legacy
    `_health` data. (Empty runtime is rare in practice but the
    fallback rule must be unambiguous.)"""
    _seed_runtime(redirect_health, {"synthetic_legacy": {}})
    fake_profiles = {
        "profiles": {
            "synthetic_legacy": {
                "model": "test:legacy",
                # Stale legacy data that must NOT be displayed once the
                # profile is present in runtime (even if empty).
                "_health": {
                    "success_rate": 0.92,
                    "avg_latency_s": 5.0,
                    "consecutive_failures": 0,
                },
            }
        }
    }
    monkeypatch.setattr(local_llm_router, "load_json",
                        lambda _p: fake_profiles)
    local_llm_router.cmd_health_report()
    out = capsys.readouterr().out
    # Stale legacy must NOT be picked up
    assert "92.0%" not in out
    # Profile shows up in the "no data" count
    assert "No health data: 1" in out


def test_health_report_falls_back_to_legacy_profile_health(
    redirect_health, capsys, monkeypatch
):
    """If runtime data is missing for a profile but the legacy
    `_health` block is present (synthetic test scenario), the report
    must still display it."""
    fake_profiles = {
        "profiles": {
            "synthetic_legacy": {
                "model": "test:legacy",
                "_health": {
                    "success_rate": 0.92,
                    "avg_latency_s": 5.0,
                    "consecutive_failures": 0,
                },
            }
        }
    }
    monkeypatch.setattr(local_llm_router, "load_json",
                        lambda _p: fake_profiles)
    rc = local_llm_router.cmd_health_report()
    assert rc == 0
    out = capsys.readouterr().out
    assert "synthetic_legacy" in out
    assert "92.0%" in out


# --- auto_tune_recommendations: runtime data ---

# PROFILE_SPECS["fast_summary"]["keywords"] includes "gemma4:e4b", so
# the candidate model name must contain that substring to be picked up.
_CURRENT = "gemma4:e4b"
_CANDIDATE = "gemma4:e4b-fast"


def test_auto_tune_uses_injected_health_data():
    """Pass a flat `{name: {...}}` map — recommendation triggers when
    a candidate's runtime latency is lower than the current's."""
    existing = {
        "fast_summary": {"model": _CURRENT},
        # The candidate model must live under SOME profile so the
        # candidate-health lookup loop can find it.
        "smart_summary": {"model": _CANDIDATE},
    }
    health = {
        "fast_summary": {"avg_latency_s": 30.0, "success_rate": 1.0},
        "smart_summary": {"avg_latency_s": 10.0, "success_rate": 1.0},
    }
    recs = upo.auto_tune_recommendations(
        existing,
        all_models=[_CURRENT, _CANDIDATE],
        base_models=[_CURRENT, _CANDIDATE],
        health_data=health,
    )
    fast = [r for r in recs if r["profile"] == "fast_summary"]
    assert fast, f"expected recommendation for fast_summary, got {recs}"
    assert fast[0]["candidate"] == _CANDIDATE
    assert fast[0]["improvement_pct"] > 0


def test_auto_tune_accepts_full_runtime_doc_shape():
    """Pass `{"profiles": {name: {...}}}` shape — same outcome as flat."""
    existing = {
        "fast_summary": {"model": _CURRENT},
        "smart_summary": {"model": _CANDIDATE},
    }
    health = {
        "schema_version": 1,
        "profiles": {
            "fast_summary": {"avg_latency_s": 30.0, "success_rate": 1.0},
            "smart_summary": {"avg_latency_s": 10.0, "success_rate": 1.0},
        },
    }
    recs = upo.auto_tune_recommendations(
        existing,
        all_models=[_CURRENT, _CANDIDATE],
        base_models=[_CURRENT, _CANDIDATE],
        health_data=health,
    )
    assert any(r["profile"] == "fast_summary" for r in recs)


def test_auto_tune_falls_back_to_legacy_health():
    """When runtime data is missing for the current profile but the
    legacy `_health` is present, the function still works."""
    existing = {
        "fast_summary": {
            "model": _CURRENT,
            "_health": {"avg_latency_s": 30.0, "success_rate": 1.0},
        },
        "smart_summary": {
            "model": _CANDIDATE,
            "_health": {"avg_latency_s": 8.0, "success_rate": 1.0},
        },
    }
    recs = upo.auto_tune_recommendations(
        existing,
        all_models=[_CURRENT, _CANDIDATE],
        base_models=[_CURRENT, _CANDIDATE],
        health_data={},  # explicit empty — forces legacy fallback
    )
    assert any(r["profile"] == "fast_summary" for r in recs)


def test_auto_tune_skips_unreliable_candidate():
    """A candidate with success_rate < 0.8 must NOT be recommended."""
    existing = {
        "fast_summary": {"model": _CURRENT},
        "smart_summary": {"model": _CANDIDATE},
    }
    health = {
        "fast_summary": {"avg_latency_s": 30.0, "success_rate": 1.0},
        "smart_summary": {"avg_latency_s": 5.0, "success_rate": 0.5},
    }
    recs = upo.auto_tune_recommendations(
        existing,
        all_models=[_CURRENT, _CANDIDATE],
        base_models=[_CURRENT, _CANDIDATE],
        health_data=health,
    )
    assert not [r for r in recs if r["profile"] == "fast_summary"]


def test_auto_tune_skips_when_no_health_for_current():
    """Profile with no runtime data and no legacy data → skipped, no crash."""
    existing = {
        "fast_summary": {"model": _CURRENT},
        "smart_summary": {"model": _CANDIDATE},
    }
    recs = upo.auto_tune_recommendations(
        existing,
        all_models=[_CURRENT, _CANDIDATE],
        base_models=[_CURRENT, _CANDIDATE],
        health_data={},
    )
    # Nothing recommended for fast_summary because no current_latency
    assert not [r for r in recs if r["profile"] == "fast_summary"]


def test_auto_tune_does_not_modify_profiles_json(redirect_health):
    """Byte-equality regression — auto_tune is read-only against
    profiles JSON."""
    existing = {
        "fast_summary": {"model": _CURRENT},
        "smart_summary": {"model": _CANDIDATE},
    }
    health = {
        "fast_summary": {"avg_latency_s": 30.0, "success_rate": 1.0},
        "smart_summary": {"avg_latency_s": 10.0, "success_rate": 1.0},
    }
    before = _hash(PROFILES_PATH)
    upo.auto_tune_recommendations(
        existing,
        all_models=[_CURRENT, _CANDIDATE],
        base_models=[_CURRENT, _CANDIDATE],
        health_data=health,
    )
    after = _hash(PROFILES_PATH)
    assert before == after


# --- profiles JSON still has no _health blocks ---

def test_profiles_json_still_has_no_health_blocks():
    """Regression guard: P1-H.3 must not have re-introduced `_health`
    into profiles JSON. The static config remains static."""
    profiles = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    leaked = [
        name for name, p in profiles.get("profiles", {}).items()
        if "_health" in p
    ]
    assert leaked == [], (
        f"profiles JSON contains _health for: {leaked}"
    )
