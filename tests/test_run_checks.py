"""Test that run_checks.py executes successfully and covers key checks."""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RUN_CHECKS = PROJECT_ROOT / "tools" / "run_checks.py"


def test_run_checks_exits_zero():
    result = subprocess.run(
        [sys.executable, str(RUN_CHECKS)],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"run_checks.py failed:\n{result.stdout}\n{result.stderr}"


def test_run_checks_reports_pass():
    result = subprocess.run(
        [sys.executable, str(RUN_CHECKS)],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    assert "ALL CHECKS PASSED" in result.stdout


def test_run_checks_covers_expected_sections():
    result = subprocess.run(
        [sys.executable, str(RUN_CHECKS)],
        capture_output=True, text=True, timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    for section in ["[Environment]", "[Tests]", "[Tool Files]", "[JSON Config]", "[Policy & Gitignore]"]:
        assert section in result.stdout, f"Missing section: {section}"
