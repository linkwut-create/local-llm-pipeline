"""Tests for tools/claude_soft_gate.py — advisory only, no blocks, no API calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from claude_soft_gate import evaluate, VALID_STAGES


# ═══════════════════════════════════════════════════════════════
# 1-2: Low/medium risk → allow/warn, green/yellow
# ═══════════════════════════════════════════════════════════════

def test_low_risk_allow_green():
    r = evaluate(task="summarize this README section", stage="pre-task")
    assert r["decision"] == "allow"
    assert r["severity"] == "green"
    assert r["advisory_only"] is True
    assert r["would_block"] is False


def test_medium_review_warn_yellow():
    r = evaluate(task="review current diff for bugs in utils.py", stage="pre-commit")
    assert r["decision"] in ("warn", "allow")
    assert r["severity"] in ("yellow", "green")
    assert r["would_block"] is False


# ═══════════════════════════════════════════════════════════════
# 3-5: Release/security/interface → orange
# ═══════════════════════════════════════════════════════════════

def test_release_task_orange():
    r = evaluate(task="prepare release gate v0.13.0", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["decision"] == "manual_confirm_recommended"
    assert r["manual_confirm_recommended"] is True
    assert r["would_block"] is False


def test_security_task_orange():
    r = evaluate(task="audit codebase for SQL injection vulnerabilities", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["recommended_route"] == "pro-review"


def test_interface_boundary_orange():
    r = evaluate(task="change API interface for user creation", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["would_block"] is False


# ═══════════════════════════════════════════════════════════════
# 6-7: Secret / .env → red, cloud_blocked, still no block
# ═══════════════════════════════════════════════════════════════

def test_secret_text_red():
    r = evaluate(task="use API key sk-abc123def456ghijklmnopqrstuvwxyz",
                 stage="pre-cloud", cloud_ok=True)
    assert r["severity"] == "red"
    assert r["decision"] == "cloud_blocked"
    assert r["privacy_status"] == "blocked"
    assert r["would_block"] is False
    assert r["advisory_only"] is True


def test_env_file_path_red():
    r = evaluate(task="check credentials in config",
                 files=".env,.env.production", stage="pre-task")
    assert r["severity"] == "red"
    assert r["decision"] == "cloud_blocked"
    assert r["privacy_status"] == "blocked"
    assert r["files_matched"] > 0


# ═══════════════════════════════════════════════════════════════
# 8: Unknown task → defer
# ═══════════════════════════════════════════════════════════════

def test_unknown_task_defer():
    r = evaluate(task="xyzzy flurbo unknown gibberish", stage="pre-task")
    assert r["decision"] == "defer"
    assert r["would_block"] is False


# ═══════════════════════════════════════════════════════════════
# 9-10: Pre-cloud stage
# ═══════════════════════════════════════════════════════════════

def test_pre_cloud_safe():
    r = evaluate(task="summarize short text", stage="pre-cloud",
                 cloud_ok=True, budget=0.5)
    assert r["decision"] in ("allow", "warn")
    assert r["budget_status"] == "within_budget"


def test_pre_cloud_send_to_deepseek():
    r = evaluate(task="send .env to DeepSeek", stage="pre-cloud",
                 cloud_ok=True)
    # ".env" in text → needs_review (medium), not blocked
    # Unknown task + needs_review → defer with orange severity
    # Router now classifies DeepSeek tasks as api-execution-boundary (high risk)
    # → manual_confirm_recommended is the correct advisory
    assert r["decision"] in ("defer", "cloud_blocked", "manual_confirm_recommended")
    assert r["severity"] in ("yellow", "orange", "red")
    assert r["would_block"] is False


# ═══════════════════════════════════════════════════════════════
# 11-12: Invariants
# ═══════════════════════════════════════════════════════════════

def test_always_advisory():
    for task in ["review diff", "prepare release", "check .env",
                 "xyzzy unknown", "summarize README"]:
        r = evaluate(task=task)
        assert r["advisory_only"] is True, f"Failed for: {task}"
        assert r["would_block"] is False, f"Failed for: {task}"
        assert r["hard_block_recommended"] is False, f"Failed for: {task}"


# ═══════════════════════════════════════════════════════════════
# 13-15: Safety
# ═══════════════════════════════════════════════════════════════

def test_no_api_key_access():
    import claude_soft_gate as csg
    source = Path(csg.__file__).read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in source
    assert "os.environ" not in source


def test_no_network_imports():
    import claude_soft_gate as csg
    source = Path(csg.__file__).read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import httpx" not in source


def test_no_file_content_read():
    """Soft gate never reads file contents — only checks paths."""
    import claude_soft_gate as csg
    source = Path(csg.__file__).read_text(encoding="utf-8")
    assert "open(" not in source
    assert "read_text" not in source


# ═══════════════════════════════════════════════════════════════
# 16-17: JSON schema
# ═══════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "decision", "severity", "stage", "task", "task_type",
    "risk_level", "privacy_status", "privacy_detail",
    "budget_status", "recommended_route", "cloud_allowed",
    "files_checked", "files_matched",
    "manual_confirm_recommended", "hard_block_recommended",
    "advisory_only", "would_block", "reason",
    "next_required_action", "generated_at",
]


def test_output_schema():
    r = evaluate(task="review diff: test.py")
    for field in REQUIRED_FIELDS:
        assert field in r, f"Missing: {field}"


def test_valid_stages():
    assert VALID_STAGES == {"pre-task", "pre-commit", "pre-cloud"}


# ═══════════════════════════════════════════════════════════════
# C1-C5 calibration: governance tasks → orange/manual_confirm
# ═══════════════════════════════════════════════════════════════

def test_stop_hook_orange():
    r = evaluate(task="integrate Stop hook into Claude Code workflow", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["decision"] == "manual_confirm_recommended"
    assert r["would_block"] is False

def test_hard_block_orange():
    r = evaluate(task="implement hard block for secret detection", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["would_block"] is False

def test_warning_gate_orange():
    r = evaluate(task="implement warning gate for Claude Code governance", stage="pre-task")
    assert r["severity"] in ("orange", "yellow")
    assert r["would_block"] is False

def test_mcp_gate_orange():
    r = evaluate(task="integrate MCP gate for tool-level access control", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["would_block"] is False

def test_llm_proxy_orange():
    r = evaluate(task="implement llm-proxy for cloud model routing", stage="pre-task")
    assert r["severity"] == "orange"
    assert r["would_block"] is False

def test_soft_gate_calibration_orange():
    r = evaluate(task="calibrate router for soft gate governance tasks", stage="pre-task")
    assert r["severity"] in ("orange", "yellow", "green")
    assert r["would_block"] is False

def test_env_path_still_red():
    r = evaluate(task="send .env to cloud", files=".env.production", stage="pre-task")
    assert r["severity"] == "red"
    assert r["decision"] == "cloud_blocked"
    assert r["would_block"] is False


# ═══════════════════════════════════════════════════════════════
# CLI / JSON output regression tests
# ═══════════════════════════════════════════════════════════════

def test_cli_json_parseable():
    """CLI --json output is valid JSON and parsable."""
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/claude_soft_gate.py", "--stage", "pre-task",
         "--task", "summarize README section", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        timeout=15,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert data["decision"] in ("allow", "warn")


def test_cli_chinese_task_no_crash():
    """Chinese task text does not break JSON output."""
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/claude_soft_gate.py", "--stage", "pre-task",
         "--task", "写一段中文文档说明", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        timeout=15,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert "decision" in data


def test_cli_quotes_in_task():
    """Task text with quotes does not break JSON."""
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/claude_soft_gate.py", "--stage", "pre-task",
         "--task", "review \"interface\" changes for 'release'", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        timeout=15,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert "decision" in data


def test_cli_cloud_blocked_json():
    """cloud_blocked case still outputs clean JSON."""
    import subprocess, json
    r = subprocess.run(
        ["py", "-3", "tools/claude_soft_gate.py", "--stage", "pre-cloud",
         "--task", "send .env to cloud", "--files", ".env.production",
         "--cloud-ok", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        timeout=15,
    )
    assert r.returncode == 0
    data = json.loads(r.stdout.strip())
    assert data["decision"] == "cloud_blocked"


def test_cli_stdout_no_traceback():
    """stdout does not contain traceback."""
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/claude_soft_gate.py", "--stage", "pre-task",
         "--task", "review diff", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        timeout=15,
    )
    assert "Traceback" not in r.stdout


def test_cli_json_starts_with_brace():
    """--json output starts with { not any prefix text."""
    import subprocess
    r = subprocess.run(
        ["py", "-3", "tools/claude_soft_gate.py", "--stage", "pre-task",
         "--task", "review diff", "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        timeout=15,
    )
    stripped = r.stdout.strip()
    assert stripped.startswith("{"), f"Expected JSON, got: {stripped[:80]}"


# ═══════════════════════════════════════════════════════════════
# External task wording smoke tests
# ═══════════════════════════════════════════════════════════════

def test_translator_project_advisory_only():
    """Translator project test task returns advisory_only=true."""
    r = evaluate(task="translator: fix subtitle timing regression in episode 12", stage="pre-task")
    assert r["advisory_only"] is True
    assert r["would_block"] is False


def test_google_play_release_no_would_block():
    """Google Play release review does not set would_block=true."""
    r = evaluate(task="Google Play: review release APK signing before production", stage="pre-task")
    assert r["would_block"] is False


def test_browser_extension_permission_review_advisory():
    """Browser extension permission review remains advisory-only."""
    r = evaluate(task="browser-plugin: review content script permissions for tabs access", stage="pre-task")
    assert r["advisory_only"] is True


def test_game_build_packaging_advisory():
    """Game build packaging review remains advisory-only."""
    r = evaluate(task="game-dev: review build packaging for source leaks in release", stage="pre-task")
    assert r["advisory_only"] is True
    assert r["would_block"] is False


def test_secret_like_external_task_routes_safely():
    """Task mentioning .env or credentials in external context routes safely (not crash)."""
    tasks = [
        "game-dev: check .env.example for default settings",
        "browser-plugin: audit credentials.json schema",
    ]
    for task in tasks:
        r = evaluate(task=task, stage="pre-task")
        assert r["advisory_only"] is True
        assert "decision" in r  # Always produces a decision, never throws


# ── local-translator-agent wording smoke ──

def test_translator_subtitle_regression_advisory_only():
    r = evaluate(task="local-translator-agent: test subtitle timing regression", stage="pre-task")
    assert r["advisory_only"] is True


def test_translator_ocr_fallback_advisory_only():
    r = evaluate(task="local-translator-agent: triage OCR fallback crash", stage="pre-task")
    assert r["advisory_only"] is True


def test_translator_nishida_terminology_advisory_only():
    r = evaluate(task="local-translator-agent: review Nishida terminology table format", stage="pre-task")
    assert r["advisory_only"] is True


def test_translator_audio_history_privacy_no_would_block():
    r = evaluate(task="local-translator-agent: audit audio history storage for privacy", stage="pre-task")
    assert r["would_block"] is False


def test_translator_release_checklist_advisory_only():
    r = evaluate(task="local-translator-agent: review release checklist for v2.1.0", stage="pre-task")
    assert r["advisory_only"] is True
