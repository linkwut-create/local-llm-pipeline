"""Test router profile resolution logic."""

import json
import sys
from pathlib import Path

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
