"""Local-only tests for DeepSeek V4 Flash/Pro tiering policy — no API calls."""

import pytest


# ── Tier classification rules ──

FLASH_TASKS = [
    "summarize this Python file for me",
    "classify this test failure from stderr",
    "rewrite the README introduction paragraph",
    "suggest a better variable name for this function",
    "draft a changelog entry from these commits",
    "aggregate shadow route checkpoint findings",
]

PRO_TASKS = [
    "propose architecture for splitting this module",
    "review provider checker code for credential leakage",
    "validate release checklist before v0.14.0",
    "propose cross-file patch plan for TM schema migration",
    "analyze critical shadow route mismatch patterns",
    "audit security boundary around DeepSeek adapter",
    "final pro-review before manual approval",
]

SECRET_TASKS = [
    "fix the API key sk-abc123 in .env",
    "check if this bearer token is valid",
]


def classify_tier(task: str) -> str:
    """Simplified tiering logic matching the policy doc rules."""
    task_lower = task.lower()

    # Secret-bearing → cloud-blocked
    secret_signals = ["sk-", "api key", "bearer token", ".env", "credentials"]
    for signal in secret_signals:
        if signal in task_lower:
            return "cloud-blocked"

    # Pro indicators
    pro_signals = [
        "architecture", "release", "security", "privacy",
        "provider", "api key", "patch plan", "critical",
        "pro-review", "audit", "cross-file",
    ]
    for signal in pro_signals:
        if signal in task_lower:
            return "pro"

    # Default → flash
    return "flash"


# ── Flash route tests ──

@pytest.mark.parametrize("task", FLASH_TASKS)
def test_low_risk_task_routes_to_flash(task):
    assert classify_tier(task) == "flash"


# ── Pro route tests ──

@pytest.mark.parametrize("task", PRO_TASKS)
def test_high_risk_task_routes_to_pro(task):
    assert classify_tier(task) == "pro"


# ── Secret-bearing → blocked ──

@pytest.mark.parametrize("task", SECRET_TASKS)
def test_secret_bearing_task_cloud_blocked(task):
    assert classify_tier(task) == "cloud-blocked"


# ── Edge cases ──

def test_empty_task_defaults_flash():
    assert classify_tier("") == "flash"


def test_unknown_gibberish_defaults_flash():
    assert classify_tier("xyzzy flurbo gronk") == "flash"


def test_summary_task_is_flash():
    assert classify_tier("summarize the diff for commit message") == "flash"


def test_release_gate_is_pro():
    assert classify_tier("validate release gate for production deployment") == "pro"


def test_privacy_review_is_pro():
    assert classify_tier("audit privacy boundary for user data storage") == "pro"


def test_api_key_in_text_is_cloud_blocked():
    assert classify_tier("use api_key=sk-abc for testing") == "cloud-blocked"


# ── No API calls ──

def test_classify_tier_no_network():
    """classify_tier is pure function — no imports, no I/O."""
    import inspect
    source = inspect.getsource(classify_tier)
    assert "requests" not in source
    assert "http" not in source
    assert "openai" not in source.lower()
    assert "deepseek" not in source.lower()
    assert "urllib" not in source


def test_no_api_key_access():
    """classify_tier is pure: no API keys, no env reads, no cloud calls.

    Uses source inspection (not sys.modules) to avoid cross-test isolation.
    The function under test is classify_tier — that's the security boundary.
    """
    import inspect

    source = inspect.getsource(classify_tier)
    assert "os.environ" not in source
    assert "getenv" not in source
    assert "DEEPSEEK_API_KEY" not in source
    assert "requests" not in source
    assert "http" not in source
    assert "urllib" not in source
    assert "subprocess" not in source
