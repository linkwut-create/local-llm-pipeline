"""Test validate_configs.py schema checks."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from validate_configs import validate_profiles, validate_tasks, VALID_RISK_LEVELS

VALIDATOR_PATH = Path(__file__).parent.parent / "tools" / "validate_configs.py"


def _make_profile(name="test_prof", model="test-model:latest", risk="medium",
                  use_for=None):
    return {
        name: {
            "model": model, "risk_level": risk,
            "use_for": use_for or ["summarize-file"],
            "temperature": 0.2,
        }
    }


def _make_task(name="test-task", profile="test_prof", risk="low",
               may_modify=False, must_verify=True):
    return {
        name: {
            "risk": risk, "default_profile": profile,
            "may_modify_code": may_modify,
            "controller_must_verify": must_verify,
            "max_output_chars": 3000,
            "allowed_use": "test task",
            "forbidden_use": "test only",
        }
    }


def test_valid_profiles_pass():
    profiles = _make_profile()
    errors, warnings = validate_profiles({"profiles": profiles})
    assert len(errors) == 0


def test_missing_model_fails():
    profiles = _make_profile(model="")
    errors, _ = validate_profiles({"profiles": profiles})
    assert any("model" in e.lower() for e in errors)


def test_invalid_risk_level_fails():
    profiles = _make_profile(risk="critical")
    errors, _ = validate_profiles({"profiles": profiles})
    assert any("risk_level" in e.lower() for e in errors)


def test_missing_required_fields_fails():
    profiles = {"test_prof": {"model": "x"}}
    errors, _ = validate_profiles({"profiles": profiles})
    assert len(errors) >= 2  # missing risk_level and use_for


def test_valid_tasks_pass():
    profiles = _make_profile()
    tasks = _make_task()
    errors = validate_tasks({"tasks": tasks}, profiles)
    assert len(errors) == 0


def test_task_missing_profile_fails():
    tasks = _make_task(profile="nonexistent")
    errors = validate_tasks({"tasks": tasks}, {"test_prof": {"model": "x"}})
    assert any("default_profile" in e.lower() and "does not exist" in e.lower()
              for e in errors)


def test_draft_task_may_modify_fails():
    tasks = _make_task(name="draft-fix", may_modify=True)
    errors = validate_tasks({"tasks": tasks}, {"test_prof": {"model": "x"}})
    assert any("may_modify_code" in e for e in errors)


def test_draft_task_no_verify_fails():
    tasks = _make_task(name="draft-fix", must_verify=False)
    errors = validate_tasks({"tasks": tasks}, {"test_prof": {"model": "x"}})
    assert any("controller_must_verify" in e for e in errors)


def test_high_risk_no_verify_fails():
    tasks = _make_task(name="release-risk-review", risk="high", must_verify=False)
    errors = validate_tasks({"tasks": tasks}, {"test_prof": {"model": "x"}})
    assert any("controller_must_verify" in e for e in errors)


def test_embedding_profile_rejects_code_tasks():
    profiles = {
        "embedding": {"model": "nomic-embed:latest", "risk_level": "low",
                       "use_for": ["review-diff", "embedding"],
                       "temperature": 0.0},
    }
    errors, _ = validate_profiles({"profiles": profiles})
    assert any("embedding" in e.lower() and "review-diff" in e
              for e in errors)


def test_cli_nonzero_on_error():
    """validate_configs.py should return non-zero when config is invalid."""
    with tempfile.TemporaryDirectory() as tmp:
        bad_profiles = Path(tmp) / "profiles.json"
        bad_profiles.write_text(json.dumps({"profiles": {"p": {"model": ""}}}))
        bad_tasks = Path(tmp) / "tasks.json"
        bad_tasks.write_text(json.dumps({"tasks": {}}))

        # Use a script that patches the paths
        code = (
            "import sys; sys.path.insert(0, 'tools'); "
            "from validate_configs import PROFILES_PATH, TASKS_PATH, main; "
            f"import validate_configs; "
            f"validate_configs.PROFILES_PATH = Path('{bad_profiles.as_posix()}'); "
            f"validate_configs.TASKS_PATH = Path('{bad_tasks.as_posix()}'); "
            "sys.exit(main())"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode != 0


def test_cli_json_output():
    """--json should produce valid JSON."""
    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--json"],
        capture_output=True, text=True, timeout=10,
        cwd=str(Path(__file__).parent.parent),
    )
    data = json.loads(result.stdout)
    assert "ok" in data
    assert "profiles_count" in data
    assert "tasks_count" in data
    assert "errors" in data
    assert "warnings" in data


# ═══════════════════════════════════════════════════════════════
# CLI regression tests
# ═══════════════════════════════════════════════════════════════

def test_cli_runs_without_error():
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/validate_configs.py"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert r.returncode == 0


def test_cli_json_output_parseable():
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/validate_configs.py", "--json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    data = json.loads(r.stdout.strip())
    assert "ok" in data


def test_cli_missing_file_fails():
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/validate_configs.py", "--profiles", "nonexistent.json"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert r.returncode != 0


def test_cli_no_traceback_in_output():
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/validate_configs.py"],
        capture_output=True, text=True, timeout=15,
        cwd=str(Path(__file__).parent.parent),
    )
    assert "Traceback" not in r.stdout
