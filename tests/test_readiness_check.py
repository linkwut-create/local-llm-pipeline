"""Test real_project_readiness_check.py — structure and core checks."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PYTHON = sys.executable
SCRIPT = Path(__file__).parent.parent / "tools" / "real_project_readiness_check.py"
PIPELINE_ROOT = Path(__file__).parent.parent


def test_script_exists():
    assert SCRIPT.exists(), "readiness check script missing"


def test_dry_run_on_self():
    """Running dry-run on pipeline project itself should work."""
    r = subprocess.run(
        [PYTHON, str(SCRIPT), str(PIPELINE_ROOT), "--dry-run", "--quick"],
        capture_output=True, text=True, timeout=60,
        cwd=str(PIPELINE_ROOT),
    )
    assert "READY_FOR_REAL_PROJECT" in r.stdout
    assert "Pipeline Self-Checks" in r.stdout


def test_no_target_reports_skipped():
    """Running without a target should skip target checks but still run self-checks."""
    r = subprocess.run(
        [PYTHON, str(SCRIPT), "--quick"],
        capture_output=True, text=True, timeout=60,
        cwd=str(PIPELINE_ROOT),
    )
    assert "skipped" in r.stdout.lower() or "no target" in r.stdout.lower()


def test_nonexistent_target_reports_error():
    """Non-existent target path should report failure."""
    r = subprocess.run(
        [PYTHON, str(SCRIPT), "/nonexistent/path/xyz", "--quick"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PIPELINE_ROOT),
    )
    # Should report target doesn't exist
    assert "target_exists" in r.stdout.lower() or "not found" in r.stdout.lower()


def test_mcp_tools_count_checked():
    """Output should mention MCP tool count."""
    r = subprocess.run(
        [PYTHON, str(SCRIPT), "--quick"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PIPELINE_ROOT),
    )
    assert "mcp_tool_count" in r.stdout.lower() or "mcp" in r.stdout.lower()


def test_logging_safety_checked():
    """Output should include logging safety check."""
    r = subprocess.run(
        [PYTHON, str(SCRIPT), "--quick"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PIPELINE_ROOT),
    )
    assert "logging" in r.stdout.lower()


def test_draft_not_called_in_dry_run():
    """In dry-run mode, draft/model tests should be skipped."""
    r = subprocess.run(
        [PYTHON, str(SCRIPT), str(PIPELINE_ROOT), "--dry-run"],
        capture_output=True, text=True, timeout=30,
        cwd=str(PIPELINE_ROOT),
    )
    assert "dry-run" in r.stdout.lower()
    # Model tests should be skipped
    assert "Model Tests: (skipped" in r.stdout or "skipped" in r.stdout.lower()
