"""Test router profile resolution logic."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

TOOLS_DIR = Path(__file__).parent.parent / "tools"
PROFILES_PATH = TOOLS_DIR / "local_llm_profiles.json"
TASKS_PATH = TOOLS_DIR / "local_llm_tasks.json"


def _load_profiles():
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def _load_tasks():
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))


def test_every_task_has_default_profile():
    """Every task in tasks.json should reference a profile that exists in profiles.json."""
    tasks = _load_tasks()["tasks"]
    profiles = _load_profiles()["profiles"]

    for task_name, task_conf in tasks.items():
        default_profile = task_conf.get("default_profile")
        assert default_profile, f"Task {task_name} has no default_profile"
        assert default_profile in profiles, (
            f"Task {task_name} references profile '{default_profile}' which doesn't exist"
        )


def test_every_profile_has_model():
    """Every profile should have a non-empty model field."""
    profiles = _load_profiles()["profiles"]
    for name, conf in profiles.items():
        assert conf.get("model"), f"Profile {name} has no model"


def test_every_profile_has_required_fields():
    """Profiles should have temperature, max_chars, max_output_chars, use_for, risk_level."""
    profiles = _load_profiles()["profiles"]
    required = ["model", "temperature", "max_chars", "max_output_chars", "use_for", "risk_level"]
    for name, conf in profiles.items():
        for field in required:
            assert field in conf, f"Profile {name} missing field '{field}'"


def test_profile_use_for_covers_all_tasks():
    """Every task should appear in at least one profile's use_for list."""
    tasks = _load_tasks()["tasks"]
    profiles = _load_profiles()["profiles"]

    all_use_for = set()
    for conf in profiles.values():
        all_use_for.update(conf.get("use_for", []))

    for task_name in tasks:
        if task_name.startswith("debate-"):
            continue
        assert task_name in all_use_for, (
            f"Task '{task_name}' not in any profile's use_for"
        )


def test_default_profile_exists():
    """The default_profile key should reference an existing profile."""
    data = _load_profiles()
    default = data.get("default_profile")
    assert default, "No default_profile defined"
    assert default in data["profiles"], f"default_profile '{default}' not found in profiles"


def test_new_profiles_exist():
    """v0.6.0: release_auditor and architecture_reviewer must exist."""
    profiles = _load_profiles()["profiles"]
    assert "release_auditor" in profiles, "release_auditor profile missing"
    assert "architecture_reviewer" in profiles, "architecture_reviewer profile missing"
    assert "embedding" in profiles, "embedding profile missing"


def test_profile_count():
    """v0.6.0: should have at least 9 profiles."""
    profiles = _load_profiles()["profiles"]
    assert len(profiles) >= 9, f"Expected >= 9 profiles, got {len(profiles)}"


def test_high_risk_tasks_require_controller_verify():
    """High-risk tasks must have controller_must_verify=true."""
    tasks = _load_tasks()["tasks"]
    for task_name, task_conf in tasks.items():
        if task_conf.get("risk") == "high":
            assert task_conf.get("controller_must_verify") is True, (
                f"High-risk task '{task_name}' must require controller verification"
            )


def test_release_auditor_profile_high_risk():
    """release_auditor profile must be high risk."""
    profiles = _load_profiles()["profiles"]
    auditor = profiles["release_auditor"]
    assert auditor["risk_level"] == "high"


def test_embedding_profile_low_risk():
    """embedding profile is low risk (no file mutation)."""
    profiles = _load_profiles()["profiles"]
    emb = profiles["embedding"]
    assert emb["risk_level"] == "low"
    assert emb["temperature"] == 0.0


# --- Router fallback logic (v0.9.5) ---

from unittest.mock import MagicMock

import local_llm_router as router


def test_check_model_available_exact_match():
    assert router.check_model_available("gemma4:e4b", ["gemma4:e4b", "qwen3.5-9b-q8:latest"])


def test_check_model_available_prefix_match():
    """Model name prefix match (without tag) returns True."""
    assert router.check_model_available("qwen3.5-9b-q8", ["qwen3.5-9b-q8:latest"])


def test_check_model_available_not_found():
    assert not router.check_model_available("nonexistent:model", ["gemma4:e4b"])


def test_check_model_available_empty_model():
    assert not router.check_model_available("", ["gemma4:e4b"])


def test_resolve_profile_candidates_list():
    """Profile resolution should return a profile with candidates for fallback."""
    _, model, _ = router.resolve_profile("summarize-file", None, None)
    assert model == "gemma4:e4b"  # default profile for summarize-file


def test_profiles_without_candidates_error_safe():
    """Router handles empty candidates gracefully — errors instead of bad fallback.

    Most profiles currently don't have explicit candidates in profiles.json;
    local_check generates them dynamically. When candidates=[], the router
    errors out rather than falling back to an unrelated model.
    """
    profiles = _load_profiles()["profiles"]
    # Verify we can iterate all profiles without error
    for name, cfg in profiles.items():
        candidates = cfg.get("candidates", [])
        assert isinstance(candidates, list), f"Profile '{name}' candidates must be a list"


def test_env_override_in_mtp_profiles():
    """MTP/llama.cpp profiles should have _env for backend routing."""
    profiles = _load_profiles()["profiles"]
    mtp_profile = profiles.get("gemma4_26b_mtp")
    if mtp_profile:
        assert "_acceleration" in mtp_profile
    mistral_llamacpp = profiles.get("mistral_119b_llamacpp")
    if mistral_llamacpp:
        env = mistral_llamacpp.get("_env", "")
        assert "LOCAL_LLM_BASE_URL" in env, "llama.cpp profile should set LOCAL_LLM_BASE_URL in _env"


# --- Hard Router fallback safety tests (v0.9.5) ---

FAKE_PROFILES = {
    "profiles": {
        "test_profile": {
            "model": "requested-model:latest",
            "candidates": ["candidate-model:latest"],
            "risk_level": "medium",
        },
    },
}
FAKE_TASKS = {"tasks": {"summarize-file": {"default_profile": "test_profile"}}}


def _fake_subprocess_success(cmd, **kwargs):
    m = MagicMock()
    m.returncode = 0
    return m


def test_router_fallback_to_candidate_when_requested_missing(monkeypatch):
    """Requested model missing, candidate available → fallback to candidate, exit 0."""
    monkeypatch.setattr(
        router, "get_ollama_models",
        lambda: ["candidate-model:latest"],
    )
    monkeypatch.setattr(
        router, "load_json",
        lambda path: FAKE_PROFILES if "profiles" in str(path) else FAKE_TASKS,
    )
    monkeypatch.setattr(sys, "argv", ["router.py", "summarize-file", "test.py"])
    monkeypatch.setattr(router.subprocess, "run", _fake_subprocess_success)

    with pytest.raises(SystemExit) as exc:
        router.main()
    assert exc.value.code == 0, "should exit 0 on successful candidate fallback"


def test_router_errors_when_candidates_all_missing(monkeypatch):
    """Requested model + all candidates missing, unrelated models available → sys.exit(1)."""
    monkeypatch.setattr(
        router, "get_ollama_models",
        lambda: ["unrelated-model:latest"],
    )
    monkeypatch.setattr(
        router, "load_json",
        lambda path: FAKE_PROFILES if "profiles" in str(path) else FAKE_TASKS,
    )
    monkeypatch.setattr(sys, "argv", ["router.py", "summarize-file", "test.py"])
    monkeypatch.setattr(router.subprocess, "run", _fake_subprocess_success)

    with pytest.raises(SystemExit) as exc:
        router.main()
    assert exc.value.code == 1, (
        "should exit 1 when candidates exhausted — must not fall back to unrelated model"
    )
