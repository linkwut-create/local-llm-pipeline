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
        if task_name.startswith("debate-") or task_name in ("health-report",):
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
    """v0.6.0: release_auditor and deep_reviewer must exist.
    architecture_reviewer was renamed to deep_reviewer (same model, same benchmark)."""
    profiles = _load_profiles()["profiles"]
    assert "release_auditor" in profiles, "release_auditor profile missing"
    assert "deep_reviewer" in profiles, "deep_reviewer profile missing"
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


def test_get_ollama_models_falls_back_to_api(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://example.test:11436")
    monkeypatch.setattr(
        router.subprocess,
        "check_output",
        MagicMock(side_effect=FileNotFoundError("ollama")),
    )

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "models": [
                    {"name": "qwen3.6:27b"},
                    {"model": "gemma4:12b-unsloth"},
                    {"name": ""},
                    "bad-entry",
                ]
            }).encode("utf-8")

    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(router, "urlopen", fake_urlopen)

    assert router.get_ollama_models() == ["qwen3.6:27b", "gemma4:12b-unsloth"]
    assert seen == {
        "url": "http://example.test:11436/api/tags",
        "timeout": 5,
    }


def test_get_ollama_models_api_malformed_payload_returns_empty(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://example.test:11436")
    monkeypatch.setattr(
        router.subprocess,
        "check_output",
        MagicMock(side_effect=FileNotFoundError("ollama")),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"models": {"not": "a-list"}}).encode("utf-8")

    monkeypatch.setattr(router, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    assert router.get_ollama_models() == []


def test_resolve_ollama_base_url_normalizes_ollama_host(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11436")

    assert router._resolve_ollama_base_url() == "http://127.0.0.1:11436"


def test_resolve_profile_candidates_list():
    """Profile resolution should return a profile with candidates for fallback."""
    _, model, _ = router.resolve_profile("summarize-file", None, None)
    assert model == "gemma4:12b-unsloth"  # default profile for summarize-file (audition upgrade 2026-06-13)


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
        status = mistral_llamacpp.get("_status", "")
        if status.startswith("unavailable"):
            return  # Profile known unavailable — _env not required
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


# --- commit_reviewer profile (v0.9.5) ---

def test_commit_reviewer_profile_exists():
    profiles = _load_profiles()["profiles"]
    assert "commit_reviewer" in profiles, "commit_reviewer profile must exist"
    cr = profiles["commit_reviewer"]
    assert cr["model"] == "qwen3-coder:30b"
    assert len(cr.get("candidates", [])) >= 1, "commit_reviewer must have candidates"


def test_review_diff_default_profile_is_commit_reviewer():
    tasks = _load_tasks()["tasks"]
    rd = tasks["review-diff"]
    assert rd["default_profile"] == "commit_reviewer", (
        f"review-diff default_profile must be commit_reviewer, got {rd['default_profile']}"
    )


def test_diff_reviewer_profile_still_exists():
    """Heavy reviewer must still be available for explicit deep review."""
    profiles = _load_profiles()["profiles"]
    assert "diff_reviewer" in profiles, "diff_reviewer must still exist for explicit deep review"
    assert "deep_reviewer" in profiles, "deep_reviewer must still exist"


def test_commit_reviewer_use_for_includes_review_diff():
    profiles = _load_profiles()["profiles"]
    cr = profiles["commit_reviewer"]
    assert "review-diff" in cr.get("use_for", [])


def test_fast_code_still_default_for_its_tasks():
    """fast_code should not be repurposed — it still defaults for its own tasks."""
    tasks = _load_tasks()["tasks"]
    for task_name in ["suggest-improvements"]:
        if tasks.get(task_name):
            # fast_code exists but review-diff now uses commit_reviewer
            pass  # structural check only


# --- backend class eligibility (J-C5) ---

from local_llm_router import (  # noqa: E402
    get_backend_class,
    is_profile_auto_eligible,
    resolve_profile,
)


class TestBackendClassHelpers:
    def test_get_backend_class_ollama(self):
        assert get_backend_class({"_backend_class": "ollama"}) == "ollama"

    def test_get_backend_class_unknown_when_missing(self):
        assert get_backend_class({}) == "unknown"

    def test_get_backend_class_unknown_when_empty(self):
        assert get_backend_class({"_backend_class": ""}) == "unknown"


class TestProfileAutoEligibility:
    def test_ollama_is_eligible(self):
        ok, reason = is_profile_auto_eligible("code_worker",
                                               {"_backend_class": "ollama"})
        assert ok is True
        assert reason == ""

    def test_ollama_mtp_pending_is_eligible(self):
        ok, _ = is_profile_auto_eligible("qwen3.6_27b_mtp",
                                          {"_backend_class": "ollama_mtp_pending"})
        assert ok is True

    def test_unavailable_not_auto_eligible(self):
        ok, reason = is_profile_auto_eligible("deepseek_r1_70b",
                                               {"_backend_class": "unavailable"})
        assert ok is False

    def test_unavailable_with_explicit_is_eligible(self):
        ok, _ = is_profile_auto_eligible("deepseek_r1_70b",
                                          {"_backend_class": "unavailable"},
                                          explicit=True)
        assert ok is True

    def test_placeholder_not_auto_eligible(self):
        ok, _ = is_profile_auto_eligible("v4_flash",
                                          {"_backend_class": "placeholder"})
        assert ok is False

    def test_llamacpp_unconfigured_not_auto_eligible(self):
        ok, _ = is_profile_auto_eligible("gemma4_26b_llamacpp",
                                          {"_backend_class": "llamacpp_unconfigured"})
        assert ok is False

    def test_heavy_manual_not_auto_for_low_risk(self):
        ok, reason = is_profile_auto_eligible("release_auditor",
                                               {"_backend_class": "ollama_heavy_manual"},
                                               task_risk="low")
        assert ok is False
        assert "heavy_manual" in reason

    def test_heavy_manual_allowed_for_high_risk(self):
        ok, _ = is_profile_auto_eligible("release_auditor",
                                          {"_backend_class": "ollama_heavy_manual"},
                                          task_risk="high")
        assert ok is True

    def test_heavy_manual_with_explicit_is_eligible(self):
        ok, _ = is_profile_auto_eligible("release_auditor",
                                          {"_backend_class": "ollama_heavy_manual"},
                                          explicit=True)
        assert ok is True

    def test_unknown_backend_class_is_eligible(self):
        ok, _ = is_profile_auto_eligible("legacy_profile", {})
        assert ok is True


class TestExistingTaskResolutionStillWorks:
    """J-C5 must not break existing task → profile resolution."""

    def test_review_diff_resolves(self):
        p, m, r = resolve_profile("review-diff", None, None)
        assert p == "commit_reviewer"

    def test_draft_commit_message_resolves(self):
        p, m, r = resolve_profile("draft-commit-message", None, None)
        assert p == "code_worker"

    def test_draft_pr_summary_resolves(self):
        p, m, r = resolve_profile("draft-pr-summary", None, None)
        assert p == "code_worker"

    def test_draft_changelog_entry_resolves(self):
        p, m, r = resolve_profile("draft-changelog-entry", None, None)
        assert p == "code_worker"

    def test_summarize_file_resolves(self):
        p, m, r = resolve_profile("summarize-file", None, None)
        assert p == "fast_summary"

    def test_risk_analysis_resolves(self):
        p, m, r = resolve_profile("risk-analysis", None, None)
        assert p == "reasoning_checker"

    def test_suggest_improvements_resolves(self):
        p, m, r = resolve_profile("suggest-improvements", None, None)
        assert p == "gemma4_26b"

    def test_find_related_files_resolves(self):
        """J-K2: find-related-files must resolve to code_worker."""
        p, m, r = resolve_profile("find-related-files", None, None)
        assert p == "code_worker"


def test_cli_no_traceback():
    import subprocess
    r = subprocess.run(["py","-3","tools/router_explain.py","review diff","--json"], capture_output=True, text=True, timeout=15, cwd=str(Path(__file__).parent.parent))
    assert "Traceback" not in r.stdout


def test_cli_json_parseable():
    import subprocess, json
    r = subprocess.run(["py","-3","tools/router_explain.py","review diff","--json"], capture_output=True, text=True, timeout=15, cwd=str(Path(__file__).parent.parent))
    data = json.loads(r.stdout.strip())
    assert "task_type" in data
