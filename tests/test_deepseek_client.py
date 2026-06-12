"""Tests for tools/deepseek_client.py — all mocked, no real API calls."""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from deepseek_client import (
    _check_privacy,
    _build_request,
    call_deepseek,
    resolve_escalation_profile,
    should_escalate_to_cloud,
    DEEPSEEK_API_KEY_ENV,
)


# ---- privacy gate ----

class TestPrivacyGate:
    def test_clean_text_passes(self):
        ok, reason = _check_privacy("This is a normal code review request.")
        assert ok
        assert reason == ""

    def test_api_key_blocked(self):
        ok, reason = _check_privacy("api_key = 'sk-abcdefghijklmnopqrstuvwxyz123456'")
        assert not ok
        assert "forbidden pattern" in reason

    def test_bearer_token_blocked(self):
        ok, reason = _check_privacy("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnopqrstuvwxyz")
        assert not ok

    def test_private_key_blocked(self):
        ok, reason = _check_privacy("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...")
        assert not ok

    def test_env_file_blocked(self):
        ok, reason = _check_privacy("Load from .env file with DATABASE_URL=...")
        assert not ok

    def test_normal_code_passes(self):
        ok, reason = _check_privacy("def test_function():\n    assert True")
        assert ok

    def test_secret_assignment_blocked(self):
        ok, reason = _check_privacy("SECRET = 'my-secret-value'")
        assert not ok

    def test_word_secret_in_comment_passes(self):
        # "secret" in a comment without assignment should pass
        ok, reason = _check_privacy("# This is not a secret, just a comment")
        assert ok

    def test_empty_string_passes(self):
        ok, reason = _check_privacy("")
        assert ok


# ---- request builder ----

class TestBuildRequest:
    def test_non_thinking(self):
        body = _build_request("deepseek-v4-flash", [{"role": "user", "content": "hi"}])
        assert body["model"] == "deepseek-v4-flash"
        assert body["extra_body"]["thinking"]["type"] == "disabled"

    def test_thinking(self):
        body = _build_request(
            "deepseek-v4-pro", [{"role": "user", "content": "hi"}],
            thinking=True, reasoning_effort="high",
        )
        assert body["model"] == "deepseek-v4-pro"
        assert body["extra_body"]["thinking"]["type"] == "enabled"
        assert body["reasoning_effort"] == "high"


# ---- call_deepseek (no real API) ----

class TestCallDeepSeek:
    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv(DEEPSEEK_API_KEY_ENV, raising=False)
        result = call_deepseek("test prompt")
        assert not result["ok"]
        assert "not set" in result["error"]

    def test_privacy_block(self, monkeypatch):
        monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, "sk-test123")
        result = call_deepseek("api_key = 'sk-secretkey12345678901234567890'")
        assert not result["ok"]
        assert "privacy gate" in result["error"]

    def test_privacy_block_private_key(self, monkeypatch):
        monkeypatch.setenv(DEEPSEEK_API_KEY_ENV, "sk-test123")
        result = call_deepseek("-----BEGIN RSA PRIVATE KEY-----\ncontent\n-----END RSA PRIVATE KEY-----")
        assert not result["ok"]
        assert "privacy gate" in result["error"]


# ---- escalation profile resolver ----

class TestResolveEscalationProfile:
    def test_level_1_returns_flash_worker(self):
        profiles = {
            "profiles": {
                "deepseek_v4_flash_worker": {
                    "model": "deepseek-v4-flash",
                    "cloud": True,
                    "_backend_class": "cloud_deepseek",
                }
            }
        }
        result = resolve_escalation_profile("any", profiles, escalation_level=1)
        assert result is not None
        assert result["model"] == "deepseek-v4-flash"

    def test_level_3_returns_pro_reviewer(self):
        profiles = {
            "profiles": {
                "deepseek_v4_pro_reviewer": {
                    "model": "deepseek-v4-pro",
                    "cloud": True,
                    "_backend_class": "cloud_deepseek",
                }
            }
        }
        result = resolve_escalation_profile("any", profiles, escalation_level=3)
        assert result is not None
        assert result["model"] == "deepseek-v4-pro"

    def test_level_0_returns_none(self):
        result = resolve_escalation_profile("any", {"profiles": {}}, escalation_level=0)
        assert result is None

    def test_missing_profile_returns_none(self):
        result = resolve_escalation_profile("any", {"profiles": {}}, escalation_level=1)
        assert result is None

    def test_invalid_level_returns_none(self):
        result = resolve_escalation_profile("any", {"profiles": {}}, escalation_level=99)
        assert result is None


# ---- escalation decision ----

class TestShouldEscalateToCloud:
    def test_privacy_not_ok_blocks(self):
        ok, level, reason = should_escalate_to_cloud(
            "review-diff", "medium", 0, privacy_ok=False, cloud_ok=True,
        )
        assert not ok
        assert "privacy" in reason.lower()

    def test_cloud_not_ok_blocks(self):
        ok, level, reason = should_escalate_to_cloud(
            "review-diff", "medium", 0, privacy_ok=True, cloud_ok=False,
        )
        assert not ok

    def test_high_risk_escalates_to_pro(self):
        ok, level, reason = should_escalate_to_cloud(
            "review-diff", "high", 0, privacy_ok=True, cloud_ok=True,
        )
        assert ok
        assert level == 3  # Pro

    def test_two_local_failures_escalates_to_flash(self):
        ok, level, reason = should_escalate_to_cloud(
            "summarize-file", "low", 2, privacy_ok=True, cloud_ok=True,
        )
        assert ok
        assert level == 1  # Flash worker

    def test_one_failure_no_escalation_for_simple_task(self):
        ok, level, reason = should_escalate_to_cloud(
            "summarize-file", "low", 1, privacy_ok=True, cloud_ok=True,
        )
        assert not ok

    def test_no_failures_medium_risk_no_escalation(self):
        ok, level, reason = should_escalate_to_cloud(
            "review-diff", "medium", 0, privacy_ok=True, cloud_ok=True,
        )
        assert not ok
