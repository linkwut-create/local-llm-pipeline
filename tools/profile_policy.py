"""Read-only derivation of per-profile policy metadata.

Introduced by MCP Cost Discipline P1-A.

This module derives a normalized 8-field policy view *from existing
profile fields* (`risk_level`, `_commit_gate_allowed`, profile name).
It does NOT add fields to local_llm_profiles.json, does NOT participate
in routing, model selection, gate enforcement, or any runtime decision.
Behavior is unchanged whether callers consult this helper or not — it
exists purely to make the implicit policy explicit, machine-checkable,
and ready for later phases to consume.

Public API:
    load_profiles(path=None) -> dict
    derive_policy(profile_name, profile=None, profiles=None) -> dict
    get_policy(profile_name, profiles=None) -> dict     # alias for derive_policy
    validate_policy(policy) -> list[str]                # returns issues; empty = ok

Derivation rules are documented in docs/MCP_COST_DISCIPLINE_PLAN.md §3-§5
and codified in `_derive_*` helpers below. Changing a rule changes the
derived view but does not touch any JSON file or runtime path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
DEFAULT_PROFILES_PATH = SCRIPT_DIR / "local_llm_profiles.json"

VALID_RISK_LEVELS = {"low", "medium", "medium-high", "high", "experimental"}
VALID_REVIEW_NECESSITY = {"required", "recommended", "optional", "user-forced"}

POLICY_FIELDS: tuple[str, ...] = (
    "risk_level",
    "default_review_necessity",
    "auto_allowed",
    "requires_escalation_reason",
    "debate_allowed",
    "commit_gate_allowed",
    "local_only",
    "experimental",
)


def load_profiles(path: Path | str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_PROFILES_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _derive_risk_level(profile: dict) -> str:
    rl = profile.get("risk_level")
    if isinstance(rl, str) and rl in VALID_RISK_LEVELS:
        return rl
    return "medium"


def _derive_experimental(profile_name: str, risk_level: str) -> bool:
    if risk_level == "experimental":
        return True
    return "experimental" in profile_name.lower()


def _derive_commit_gate_allowed(profile: dict) -> bool:
    return profile.get("_commit_gate_allowed") is True


def _derive_requires_escalation_reason(risk_level: str) -> bool:
    return risk_level in ("high", "experimental")


def _derive_debate_allowed(profile_name: str, risk_level: str) -> bool:
    if risk_level in ("high", "experimental"):
        return True
    return False


def _derive_auto_allowed(risk_level: str, experimental: bool) -> bool:
    if experimental:
        return False
    if risk_level in ("high",):
        return False
    return True


def _derive_local_only(profile: dict) -> bool:
    # All current profiles run locally (Ollama or llama.cpp on zero12).
    # A future external/cloud profile must explicitly set _provider="external"
    # or _local_only=False to opt out. Until then, default true.
    if profile.get("_local_only") is False:
        return False
    if str(profile.get("_provider", "")).lower() in ("external", "api", "cloud"):
        return False
    return True


_REVIEW_NECESSITY_BY_NAME: dict[str, str] = {
    "commit_reviewer": "required",
    "diff_reviewer": "recommended",
    "fast_summary": "optional",
    "smart_summary": "optional",
}


def _derive_default_review_necessity(profile_name: str, risk_level: str) -> str:
    if profile_name in _REVIEW_NECESSITY_BY_NAME:
        return _REVIEW_NECESSITY_BY_NAME[profile_name]
    if risk_level in ("high", "experimental"):
        # Heavy / experimental profiles: recommended by default — actual
        # invocation is user-forced via auto_allowed=false.
        return "recommended"
    return "optional"


def derive_policy(
    profile_name: str,
    profile: dict | None = None,
    profiles: dict | None = None,
) -> dict[str, Any]:
    """Return the derived policy view for `profile_name`.

    Looks up `profile_name` in `profiles` (or loads from disk if not
    given). If `profile` is passed directly it bypasses lookup.
    """
    if profile is None:
        if profiles is None:
            profiles = load_profiles().get("profiles", {})
        elif "profiles" in profiles and isinstance(profiles.get("profiles"), dict):
            profiles = profiles["profiles"]
        profile = profiles.get(profile_name)
        if profile is None:
            raise KeyError(f"unknown profile: {profile_name!r}")

    risk_level = _derive_risk_level(profile)
    experimental = _derive_experimental(profile_name, risk_level)
    return {
        "risk_level": risk_level,
        "default_review_necessity": _derive_default_review_necessity(
            profile_name, risk_level
        ),
        "auto_allowed": _derive_auto_allowed(risk_level, experimental),
        "requires_escalation_reason": _derive_requires_escalation_reason(risk_level),
        "debate_allowed": _derive_debate_allowed(profile_name, risk_level),
        "commit_gate_allowed": _derive_commit_gate_allowed(profile),
        "local_only": _derive_local_only(profile),
        "experimental": experimental,
    }


# Backward-compatible alias — derivation is the only mode in P1-A.
get_policy = derive_policy


def validate_policy(policy: dict) -> list[str]:
    issues: list[str] = []
    for field in POLICY_FIELDS:
        if field not in policy:
            issues.append(f"missing field: {field}")
    rl = policy.get("risk_level")
    if rl is not None and rl not in VALID_RISK_LEVELS:
        issues.append(
            f"invalid risk_level {rl!r} "
            f"(must be one of: {sorted(VALID_RISK_LEVELS)})"
        )
    rn = policy.get("default_review_necessity")
    if rn is not None and rn not in VALID_REVIEW_NECESSITY:
        issues.append(
            f"invalid default_review_necessity {rn!r} "
            f"(must be one of: {sorted(VALID_REVIEW_NECESSITY)})"
        )
    for bool_field in (
        "auto_allowed",
        "requires_escalation_reason",
        "debate_allowed",
        "commit_gate_allowed",
        "local_only",
        "experimental",
    ):
        v = policy.get(bool_field)
        if v is not None and not isinstance(v, bool):
            issues.append(f"{bool_field} must be a bool, got {type(v).__name__}")
    return issues
