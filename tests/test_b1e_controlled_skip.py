"""Tests for B1-E controlled low-risk auto-debate skip.

Covers: env knob behavior, skip conditions, non-skippable conditions,
forced debate override, ledger records, and existing B1-C regression.
All tests monkeypatch to avoid real model calls.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_mcp_server
import local_llm_preclassifier as pc


# ---------------------------------------------------------------------------
# env knob names (mirror server constants)
# ---------------------------------------------------------------------------
_ENV_SKIP = "LOCAL_LLM_ENABLE_LOW_RISK_DEBATE_SKIP"
_ENV_FORCE = "LOCAL_LLM_FORCE_DEBATE_REVIEW"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clear_env():
    """Remove B1-E env knobs so tests start from a known state."""
    for k in (_ENV_SKIP, _ENV_FORCE):
        os.environ.pop(k, None)


def _set_env(key: str, value: str):
    os.environ[key] = value


def _make_diff(files, *, body="", large=False):
    """Build a git diff with the given file list (one diff --git entry per file)."""
    lines = []
    for f in files:
        lines.append(f"diff --git a/{f} b/{f}")
        lines.append(f"--- a/{f}")
        lines.append(f"+++ b/{f}")
        if body:
            lines.append(body)
        elif large:
            # Generate enough lines to exceed the auto-debate line_count>100 threshold
            lines.append("@@ -1,200 +1,200 @@")
            for i in range(160):
                lines.append(f" unchanged line {i}")
        else:
            lines.append("@@ -1,1 +1,1 @@")
            lines.append("-old status wording")
            lines.append("+new status wording")
    return "\n".join(lines)


def _make_large_docs_diff(files):
    """Make a docs-only diff large enough to trigger auto-debate (>100 lines)."""
    return _make_diff(files, large=True)


# A minimal fake review output from the worker:
_FAKE_REVIEW_OUTPUT = {
    "task": "review-diff",
    "tool": "review-diff",
    "profile": "commit_reviewer",
    "ok": True,
    "summary": "docs-only change, no issues.",
    "high_confidence_findings": [],
    "candidate_findings": [],
    "controller_must_verify": [],
}


def _fake_run_subprocess_ok(cmd, stdin_data=None, timeout=None, extra_env=None):
    return {
        "ok": True,
        "stdout": json.dumps(_FAKE_REVIEW_OUTPUT),
        "stderr": "",
        "returncode": 0,
        "elapsed_seconds": 0.5,
    }


def _fake_debate_subprocess_ok(cmd, stdin_data=None, timeout=None, extra_env=None):
    """Fake debate subprocess result (used by call_debate_review_diff)."""
    return {
        "ok": True,
        "stdout": json.dumps({
            "task": "review-diff",
            "mode": "debate",
            "profiles": ["test"],
            "models": {"test": "test-model"},
            "ok": True,
            "input": {"source": "stdin", "chars": 500},
            "high_confidence_findings": [],
            "candidate_findings": [],
            "controller_must_verify": [],
            "not_verified": [],
            "warnings": [],
            "error": None,
            "elapsed_seconds": 0.1,
            "created_at": "2026-01-01T00:00:00+00:00",
        }),
        "stderr": "",
        "returncode": 0,
        "elapsed_seconds": 0.1,
    }


# ---------------------------------------------------------------------------
# _should_skip_auto_debate_for_low_risk_docs — env knob tests
# ---------------------------------------------------------------------------

class TestShouldSkipEnvKnobs:
    """Test that env knobs gate the skip correctly."""

    def setup_method(self):
        _clear_env()

    def teardown_method(self):
        _clear_env()

    def test_env_off_returns_false_docs_only(self):
        """Env unset → skip disabled."""
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False
        assert adv["skipped"] is False
        assert "opt-in disabled" in adv["reason"]

    def test_env_off_falsy_returns_false(self):
        """Env set to falsy → skip disabled."""
        _set_env(_ENV_SKIP, "false")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_env_on_docs_only_returns_true(self):
        """Env ON + docs-only → skip allowed."""
        _set_env(_ENV_SKIP, "true")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is True
        assert adv["skipped"] is True
        assert adv["safe_to_commit"] is False
        assert adv["requires_commit_gate_review"] is True
        assert adv["manual_debate_still_available"] is True
        assert adv["policy"] == "b1-d-v1"
        assert adv["policy_version"] == 1

    def test_force_debate_overrides_skip_env(self):
        """Force debate ON overrides skip env ON."""
        _set_env(_ENV_SKIP, "true")
        _set_env(_ENV_FORCE, "true")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False
        assert "LOCAL_LLM_FORCE_DEBATE_REVIEW" in adv["reason"]

    def test_force_debate_alone_no_skip(self):
        """Force debate ON → no skip even without opt-in."""
        _set_env(_ENV_FORCE, "true")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_commit_gate_true_no_skip(self):
        """commit_gate=true → never skip."""
        _set_env(_ENV_SKIP, "true")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=True)
        assert should is False
        assert "commit gate" in adv["reason"].lower()


# ---------------------------------------------------------------------------
# _should_skip_auto_debate_for_low_risk_docs — non-skippable conditions
# ---------------------------------------------------------------------------

class TestShouldSkipNonSkippable:
    """Files/conditions that must NEVER be skipped."""

    def setup_method(self):
        _clear_env()
        _set_env(_ENV_SKIP, "true")

    def teardown_method(self):
        _clear_env()

    def test_version_file_no_skip(self):
        diff = _make_large_docs_diff(["VERSION"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_mcp_server_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/local_llm_mcp_server.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_ledger_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/call_ledger.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_hook_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/claude_hooks/mcp_gate.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_worker_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/local_llm_worker.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_debate_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/local_llm_debate.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_router_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/local_llm_router.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_cache_file_no_skip(self):
        diff = _make_large_docs_diff(["tools/local_llm_cache.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_runtime_code_no_skip(self):
        diff = _make_large_docs_diff(["src/main.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_tests_only_no_skip(self):
        diff = _make_large_docs_diff(["tests/test_main.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_mixed_docs_runtime_no_skip(self):
        diff = _make_large_docs_diff(["CHANGELOG.md", "src/main.py"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_security_pattern_in_body_no_skip(self):
        _set_env(_ENV_SKIP, "true")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        diff += "\n+ eval(some_untrusted_input)"
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_empty_diff_no_skip(self):
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            "", commit_gate=False)
        assert should is False

    def test_malformed_diff_no_skip(self):
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            "   ", commit_gate=False)
        assert should is False

    def test_preclassifier_exception_no_skip(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise RuntimeError("simulated crash")
        monkeypatch.setattr(local_llm_mcp_server, "_preclassify", _raise)
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False

    def test_preclassifier_none_no_skip(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "_preclassify", None)
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is False


# ---------------------------------------------------------------------------
# _should_skip_auto_debate_for_low_risk_docs — skippable conditions
# ---------------------------------------------------------------------------

class TestShouldSkipSkippable:
    """Files that ARE eligible for skip under the right conditions."""

    def setup_method(self):
        _clear_env()
        _set_env(_ENV_SKIP, "true")

    def teardown_method(self):
        _clear_env()

    def test_changelog_only_skip(self):
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        should, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is True
        assert adv["skipped"] is True

    def test_project_status_only_skip(self):
        diff = _make_large_docs_diff(["PROJECT_STATUS.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is True

    def test_docs_dir_skip(self):
        diff = _make_large_docs_diff(["docs/plan.md", "docs/design.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is True

    def test_mixed_docs_only_skip(self):
        diff = _make_large_docs_diff(
            ["CHANGELOG.md", "PROJECT_STATUS.md", "docs/notes.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is True

    def test_release_notes_md_is_docs(self):
        """RELEASE_NOTES.md is a documentation file, not a release script."""
        diff = _make_large_docs_diff(["RELEASE_NOTES.md"])
        should, _ = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        assert should is True


# ---------------------------------------------------------------------------
# Advisory shape invariant
# ---------------------------------------------------------------------------

class TestSkipAdvisoryShape:
    """Verify the skip advisory always has the correct shape."""

    def test_advisory_always_has_safe_to_commit_false(self):
        """safe_to_commit must always be false regardless of skip result."""
        skipped, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            _make_large_docs_diff(["CHANGELOG.md"]), commit_gate=False)
        # env is off → skipped=False
        assert adv["safe_to_commit"] is False
        assert adv["requires_commit_gate_review"] is True
        assert adv["manual_debate_still_available"] is True
        assert "force_circuit_breaker" in adv

    def test_skip_advisory_has_all_required_keys(self):
        _set_env(_ENV_SKIP, "true")
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        _, adv = local_llm_mcp_server._should_skip_auto_debate_for_low_risk_docs(
            diff, commit_gate=False)
        required = [
            "ok", "skipped", "reason", "preclassifier_advisory",
            "requires_commit_gate_review", "safe_to_commit",
            "manual_debate_still_available", "force_circuit_breaker",
            "policy", "policy_version",
        ]
        for key in required:
            assert key in adv, f"missing key: {key}"


# ---------------------------------------------------------------------------
# call_review_diff integration — skip fires (env ON + docs-only)
# ---------------------------------------------------------------------------

class TestCallReviewDiffSkipIntegration:
    """Integration tests: call_review_diff with env ON + docs-only diff."""

    def setup_method(self):
        _clear_env()

    def teardown_method(self):
        _clear_env()

    def test_docs_only_with_env_on_skips_auto_debate(self, monkeypatch):
        """Env ON + docs-only large diff → auto-debate skipped, single review runs."""
        _set_env(_ENV_SKIP, "true")
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        result = local_llm_mcp_server.call_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        # Must have the skip advisory injected
        skip = result.get("debate_auto_escalation_skipped")
        assert skip is not None, "debate_auto_escalation_skipped must be present"
        assert skip["skipped"] is True
        assert skip["safe_to_commit"] is False

    def test_docs_only_with_env_off_auto_debate_still_fires(self, monkeypatch):
        """Env OFF → auto-debate should still fire (call_debate_review_diff)."""
        # Track whether call_debate_review_diff was called
        debate_called = []

        def _track_debate(params):
            debate_called.append(True)
            return {
                "ok": True,
                "result": {
                    "task": "review-diff",
                    "mode": "debate",
                    "ok": True,
                    "high_confidence_findings": [],
                    "candidate_findings": [],
                    "controller_must_verify": [],
                    "preclassifier_advisory": {"risk_level": "low"},
                },
                "elapsed_seconds": 1.0,
                "request_id": "req_test",
            }

        monkeypatch.setattr(local_llm_mcp_server, "call_debate_review_diff",
                           _track_debate)
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        result = local_llm_mcp_server.call_review_diff({
            "diff_text": diff,
        })
        assert len(debate_called) == 1, "auto-debate should still fire when env is off"
        # No skip advisory when debate runs
        assert result.get("debate_auto_escalation_skipped") is None

    def test_manual_debate_review_diff_never_skipped(self, monkeypatch):
        """Manual call_debate_review_diff always executes debate regardless of env."""
        _set_env(_ENV_SKIP, "true")
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_debate_subprocess_ok)
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        # preclassifier_advisory must be present
        adv = result["result"].get("preclassifier_advisory")
        assert adv is not None
        # debate_skipped must be FALSE for manual debate
        assert adv.get("debate_skipped") is False
        assert adv.get("skip_debate_allowed") is False

    def test_commit_gate_docs_diff_no_skip(self, monkeypatch):
        """commit_gate=true → auto-debate escalation is never reached."""
        _set_env(_ENV_SKIP, "true")
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_large_docs_diff(["CHANGELOG.md"])
        result = local_llm_mcp_server.call_review_diff({
            "diff_text": diff,
            "commit_gate": True,
        })
        assert result["ok"] is True
        # commit_gate skips auto-escalation entirely → no skip advisory
        assert result.get("debate_auto_escalation_skipped") is None

    def test_small_docs_diff_no_auto_escalation(self, monkeypatch):
        """A small docs diff (< 100 lines) doesn't trigger auto-escalation at all."""
        _set_env(_ENV_SKIP, "true")
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_run_subprocess_ok)
        diff = _make_diff(["CHANGELOG.md"])  # small, non-escalating
        result = local_llm_mcp_server.call_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        # Not large enough for auto-escalation → no advisory
        assert result.get("debate_auto_escalation_skipped") is None


# ---------------------------------------------------------------------------
# Existing B1-C regression: env off preserves all existing behavior
# ---------------------------------------------------------------------------

class TestB1CRegression:
    """Env OFF must preserve all existing B1-C behavior."""

    def setup_method(self):
        _clear_env()

    def teardown_method(self):
        _clear_env()

    def test_debate_skipped_always_false_env_off(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_debate_subprocess_ok)
        diff = _make_diff(["CHANGELOG.md", "PROJECT_STATUS.md"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        adv = result["result"].get("preclassifier_advisory")
        assert adv["debate_skipped"] is False
        assert adv["skip_debate_allowed"] is False

    def test_sensitive_diff_still_debates_env_off(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_debate_subprocess_ok)
        diff = _make_diff(["tools/local_llm_mcp_server.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        assert result["ok"] is True
        adv = result["result"].get("preclassifier_advisory")
        assert adv["risk_level"] == "high"

    def test_tests_only_still_debates_env_off(self, monkeypatch):
        monkeypatch.setattr(local_llm_mcp_server, "run_subprocess",
                           _fake_debate_subprocess_ok)
        diff = _make_diff(["tests/test_main.py"])
        result = local_llm_mcp_server.call_debate_review_diff({
            "diff_text": diff,
        })
        adv = result["result"].get("preclassifier_advisory")
        assert adv["debate_skipped"] is False
