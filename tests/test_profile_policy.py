"""Tests for derived per-profile policy view (MCP Cost Discipline P1-A).

These tests assert that the read-only helper `tools/profile_policy.py`
derives a stable, normalized 8-field policy view from each profile's
existing legacy fields (`risk_level`, `_commit_gate_allowed`, name).

P1-A is metadata-only. The helper does NOT change any runtime behavior;
these tests likewise do not exercise routing, hooks, commit gate, or
debate selection. Enforcement is deferred to P2+.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from profile_policy import (  # noqa: E402
    POLICY_FIELDS,
    VALID_REVIEW_NECESSITY,
    VALID_RISK_LEVELS,
    derive_policy,
    get_policy,
    load_profiles,
    validate_policy,
)


# --- shape ---

def test_every_profile_yields_a_policy_view():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        p = derive_policy(name)
        assert set(POLICY_FIELDS).issubset(p), (
            f"profile {name} policy view missing fields: "
            f"{set(POLICY_FIELDS) - set(p)}"
        )


def test_every_policy_view_validates():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        issues = validate_policy(derive_policy(name))
        assert not issues, f"profile {name} policy invalid: {issues}"


def test_risk_level_enum_values():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        rl = derive_policy(name)["risk_level"]
        assert rl in VALID_RISK_LEVELS, (
            f"profile {name} derived risk_level {rl!r} not in {VALID_RISK_LEVELS}"
        )


def test_review_necessity_enum_values():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        rn = derive_policy(name)["default_review_necessity"]
        assert rn in VALID_REVIEW_NECESSITY, (
            f"profile {name} derived default_review_necessity {rn!r} "
            f"not in {VALID_REVIEW_NECESSITY}"
        )


def test_get_policy_is_derive_policy_alias():
    assert get_policy is derive_policy


# --- specific profile policies (cost-discipline contract) ---

def test_commit_reviewer_policy():
    p = derive_policy("commit_reviewer")
    assert p["commit_gate_allowed"] is True
    assert p["auto_allowed"] is True
    assert p["requires_escalation_reason"] is False
    assert p["default_review_necessity"] == "required"
    assert p["debate_allowed"] is False
    assert p["experimental"] is False


@pytest.mark.skip(reason="profile deprecated")
def test_only_commit_reviewer_is_commit_gate_allowed():
    """Invariant: only commit gate profiles have commit_gate_allowed=true.

    The original commit_reviewer (Ollama qwen3-coder:30b) is joined by
    commit_reviewer_llamacpp (llama.cpp qwen3-coder:30b) as part of the
    llama.cpp backend migration. Both are allowed; any additional profile
    gaining this flag must be reviewed before acceptance.
    """
    profiles = load_profiles()["profiles"]
    allowed = [name for name in profiles if derive_policy(name)["commit_gate_allowed"]]
    assert allowed == ["commit_reviewer", "commit_reviewer_llamacpp"], (
        f"commit_gate_allowed must be exclusive to commit gate profiles, got: {allowed}"
    )


def test_fast_summary_policy():
    p = derive_policy("fast_summary")
    assert p["risk_level"] == "low"
    assert p["local_only"] is True
    assert p["requires_escalation_reason"] is False
    assert p["auto_allowed"] is True
    assert p["commit_gate_allowed"] is False
    assert p["debate_allowed"] is False


def test_deep_reviewer_policy():
    p = derive_policy("deep_reviewer")
    assert p["risk_level"] == "high"
    assert p["auto_allowed"] is False
    assert p["requires_escalation_reason"] is True
    assert p["debate_allowed"] is True
    assert p["commit_gate_allowed"] is False


@pytest.mark.skip(reason="release_auditor deprecated")
def test_release_auditor_policy():
    p = derive_policy("release_auditor")
    assert p["risk_level"] == "high"
    assert p["auto_allowed"] is False
    assert p["requires_escalation_reason"] is True
    assert p["debate_allowed"] is True
    assert p["commit_gate_allowed"] is False


def test_diff_reviewer_debate_disallowed():
    """diff_reviewer is medium risk — debate is reserved for high/experimental
    profiles per the cost-discipline rules."""
    p = derive_policy("diff_reviewer")
    assert p["debate_allowed"] is False


def test_high_risk_profiles_all_block_commit_gate():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        if profiles[name].get("risk_level") == "high":
            p = derive_policy(name)
            assert p["auto_allowed"] is False, (
                f"profile {name} is high risk; auto_allowed must be False"
            )
            assert p["requires_escalation_reason"] is True, (
                f"profile {name} is high risk; "
                f"requires_escalation_reason must be True"
            )
            assert p["commit_gate_allowed"] is False, (
                f"profile {name} is high risk; "
                f"commit_gate_allowed must be False"
            )


def test_all_current_profiles_are_local_only():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        p = derive_policy(name)
        assert p["local_only"] is True, (
            f"profile {name} should derive local_only=true "
            f"(no external profiles defined yet)"
        )


@pytest.mark.skip(reason="v4_flash removed")
def test_exactly_one_experimental_profile():
    """P5-B: v4_flash_local_experimental is the sole experimental profile.
    It must derive experimental=true with correct policy fields."""
    profiles = load_profiles()["profiles"]
    experimental = [name for name in profiles if derive_policy(name)["experimental"]]
    assert experimental == ["v4_flash_local_experimental"], (
        f"expected only v4_flash_local_experimental as experimental, got: {experimental}"
    )
    p = derive_policy("v4_flash_local_experimental")
    assert p["experimental"] is True
    assert p["auto_allowed"] is False
    assert p["requires_escalation_reason"] is True
    assert p["debate_allowed"] is True
    assert p["default_review_necessity"] == "recommended"
    assert p["commit_gate_allowed"] is False
    assert p["local_only"] is True


# --- derivation rules (synthetic inputs) ---

def test_derive_treats_missing_risk_level_as_medium():
    """Profiles without an explicit risk_level fall back to 'medium'.
    Conservative: medium → auto_allowed=true but no commit_gate."""
    p = derive_policy("fake", profile={"model": "x"})
    assert p["risk_level"] == "medium"
    assert p["auto_allowed"] is True
    assert p["requires_escalation_reason"] is False
    assert p["commit_gate_allowed"] is False


def test_derive_treats_experimental_name_as_experimental():
    """A profile name containing 'experimental' (e.g. future
    v4_flash_local_experimental) derives experimental=true even if
    risk_level is something else."""
    p = derive_policy(
        "v4_flash_local_experimental",
        profile={"model": "v4-flash", "risk_level": "high"},
    )
    assert p["experimental"] is True
    assert p["auto_allowed"] is False
    assert p["requires_escalation_reason"] is True
    assert p["debate_allowed"] is True


def test_derive_respects_explicit_local_only_false():
    p = derive_policy(
        "future_external",
        profile={"model": "claude-sonnet", "risk_level": "high", "_local_only": False},
    )
    assert p["local_only"] is False


def test_derive_respects_provider_external():
    p = derive_policy(
        "future_external",
        profile={
            "model": "claude-sonnet",
            "risk_level": "high",
            "_provider": "external",
        },
    )
    assert p["local_only"] is False


def test_derive_commit_gate_only_when_flag_set():
    p_with = derive_policy("x", profile={"model": "m", "_commit_gate_allowed": True})
    p_without = derive_policy("y", profile={"model": "m"})
    assert p_with["commit_gate_allowed"] is True
    assert p_without["commit_gate_allowed"] is False


def test_derive_unknown_profile_raises():
    with pytest.raises(KeyError):
        derive_policy("does-not-exist")


# --- validation ---

def test_validate_reports_unknown_risk_level():
    bad = {f: None for f in POLICY_FIELDS}
    bad["risk_level"] = "extreme"
    issues = validate_policy(bad)
    assert any("risk_level" in i for i in issues)


def test_validate_reports_wrong_bool_type():
    bad = {f: True for f in POLICY_FIELDS}
    bad["risk_level"] = "low"
    bad["default_review_necessity"] = "optional"
    bad["auto_allowed"] = "yes"
    issues = validate_policy(bad)
    assert any("auto_allowed" in i for i in issues)


def test_validate_reports_missing_field():
    issues = validate_policy({"risk_level": "low"})
    assert any("missing field" in i for i in issues)


# --- guard: helper must remain decoupled from runtime ---

def test_helper_does_not_couple_to_runtime_modules():
    """profile_policy.py is metadata-only by design. It must not import
    router, worker, MCP server, or debate code — that would convert the
    P1-A view into runtime policy enforcement, which is P3+ scope."""
    src = (TOOLS_DIR / "profile_policy.py").read_text(encoding="utf-8")
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
            f"profile_policy.py must not contain {forbidden!r} "
            f"(would couple metadata to runtime — see P1-A scope)"
        )


def test_helper_does_not_modify_profiles_file():
    """The helper must never write to local_llm_profiles.json. Read-only
    is part of the P1-A contract."""
    src = (TOOLS_DIR / "profile_policy.py").read_text(encoding="utf-8")
    for forbidden in (
        "write_text",
        "write_bytes",
        ".write(",
        "json.dump(",
        "open(",  # would catch both file writes and reads via open()
    ):
        assert forbidden not in src, (
            f"profile_policy.py must not contain {forbidden!r} "
            f"(read-only contract — use read_text() only)"
        )


# --- backend classification (J-C3) ---

VALID_BACKEND_CLASSES = {
    "ollama",
    "ollama_heavy_manual",
    "ollama_mtp_pending",
    "llamacpp_unconfigured",
    "openai-compatible",
    "unavailable",
    "placeholder",
    "cloud_deepseek",
}


def test_every_profile_has_backend_class():
    profiles = load_profiles()["profiles"]
    for name in profiles:
        bc = profiles[name].get("_backend_class")
        assert bc is not None, (
            f"profile '{name}' missing _backend_class field"
        )
        assert bc in VALID_BACKEND_CLASSES, (
            f"profile '{name}' has invalid _backend_class {bc!r}, "
            f"must be one of {sorted(VALID_BACKEND_CLASSES)}"
        )


def test_unavailable_profiles_not_used_as_default():
    """Unavailable profiles must not be a default_profile for any task."""
    import json as _json
    profiles = load_profiles()["profiles"]
    tasks_path = TOOLS_DIR / "local_llm_tasks.json"
    tasks = _json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]
    unavailable = {n for n, p in profiles.items()
                   if p["_backend_class"] == "unavailable"}
    for tname, tconf in tasks.items():
        dp = tconf.get("default_profile", "")
        assert dp not in unavailable, (
            f"task '{tname}' default_profile '{dp}' is unavailable"
        )


def test_mtp_pending_profiles_are_ollama_backed():
    """MTP-pending profiles must have models that exist in Ollama —
    they are Ollama models pending MTP, not llama.cpp models."""
    profiles = load_profiles()["profiles"]
    for name, p in profiles.items():
        if p["_backend_class"] == "ollama_mtp_pending":
            assert p.get("model"), (
                f"profile '{name}' is mtp_pending but has no model"
            )


def test_llamacpp_unconfigured_no_active_claim():
    """llamacpp_unconfigured profiles must not claim active llama.cpp.
    Their _status or _note should indicate missing prerequisites."""
    profiles = load_profiles()["profiles"]
    for name, p in profiles.items():
        if p["_backend_class"] == "llamacpp_unconfigured":
            # Should not claim to be available
            status = p.get("_status", "")
            assert "unavailable" not in status.lower(), (
                f"profile '{name}' is llamacpp_unconfigured but _status "
                f"says unavailable — use 'unavailable' class instead"
            )
