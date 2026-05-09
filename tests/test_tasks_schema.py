"""Test tasks.json schema integrity."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

TASKS_PATH = Path(__file__).parent.parent / "tools" / "local_llm_tasks.json"


def _load_tasks():
    return json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]


def test_all_tasks_have_required_fields():
    """Every task must have risk, default_profile, may_modify_code, controller_must_verify."""
    tasks = _load_tasks()
    required = ["risk", "default_profile", "may_modify_code", "controller_must_verify"]
    for name, conf in tasks.items():
        for field in required:
            assert field in conf, f"Task '{name}' missing field '{field}'"


def test_no_task_may_modify_code():
    """All tasks must have may_modify_code=false."""
    tasks = _load_tasks()
    for name, conf in tasks.items():
        assert conf["may_modify_code"] is False, (
            f"Task '{name}' has may_modify_code={conf['may_modify_code']}, must be false"
        )


def test_all_tasks_require_controller_verify():
    """All tasks must have controller_must_verify=true."""
    tasks = _load_tasks()
    for name, conf in tasks.items():
        assert conf["controller_must_verify"] is True, (
            f"Task '{name}' has controller_must_verify={conf['controller_must_verify']}, must be true"
        )


def test_risk_levels_valid():
    """Risk levels should be from a known set."""
    valid_risks = {"low", "medium", "medium-high", "high"}
    tasks = _load_tasks()
    for name, conf in tasks.items():
        assert conf["risk"] in valid_risks, (
            f"Task '{name}' has unknown risk '{conf['risk']}'"
        )


def test_minimum_task_count():
    """There should be at least 18 tasks defined."""
    tasks = _load_tasks()
    assert len(tasks) >= 18, f"Expected at least 18 tasks, got {len(tasks)}"


def test_draft_tasks_dont_modify_code():
    """v0.7.0: All draft tasks must have may_modify_code=false."""
    tasks = _load_tasks()
    for name in ["draft-fix", "draft-feature", "draft-refactor", "suggest-improvements"]:
        assert name in tasks, f"Draft task '{name}' missing"
        assert tasks[name]["may_modify_code"] is False, f"{name} must not modify code"
        assert tasks[name]["controller_must_verify"] is True
