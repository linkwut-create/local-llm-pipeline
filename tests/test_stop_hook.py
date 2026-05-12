"""Test Stop hook session summary and commit gate (Phase 2A.1).

Imports from the repository-local module tools/claude_hooks/mcp_gate.py.
No dependency on ~/.claude/hooks/.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from tools.claude_hooks import mcp_gate


@pytest.fixture
def tmp_config_dir():
    """Create a temporary config directory for isolated state/log files."""
    with tempfile.TemporaryDirectory() as d:
        yield d


# ---------------------------------------------------------------------------
# review_tool_succeeded
# ---------------------------------------------------------------------------

class TestReviewToolSucceeded:
    def test_ok_true_with_no_error(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": True}),
            }
        }
        assert mcp_gate.review_tool_succeeded(payload) is True

    def test_ok_false(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": False}),
            }
        }
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_error_field_non_null(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": True, "error": "something broke"}),
            }
        }
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_unicode_warning_in_response(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({
                    "ok": True,
                    "warnings": ["UnicodeDecodeError in subprocess"],
                }),
            }
        }
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_no_tool_response(self):
        assert mcp_gate.review_tool_succeeded({}) is False
        assert mcp_gate.review_tool_succeeded({"tool_response": {}}) is False


# ---------------------------------------------------------------------------
# handle_stop (session summary)
# ---------------------------------------------------------------------------

class TestStopHook:
    def test_empty_session_reminders(self, tmp_config_dir):
        """Session with no MCP calls should produce reminders."""
        mcp_gate._clear_session(tmp_config_dir)
        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": ""})
        assert any("local_check" in r.lower() for r in reminders)

    def test_full_session_no_false_warnings(self, tmp_config_dir):
        """Session with check + review + summarize should not warn about missing tools."""
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["mcp_calls"] = {
            "mcp__local-llm__local_check": True,
            "mcp__local-llm__local_review_diff": True,
            "mcp__local-llm__local_summarize_file": True,
            "_last_mcp_failed": False,
        }
        state["diff_reviewed"] = True
        state["dirty_since_review"] = False
        mcp_gate.save_state(tmp_config_dir, state)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": ""})
        # Should not contain "was not called" for check or review
        assert not any("local_check was not called" in r for r in reminders)
        assert not any("No local_review_diff" in r for r in reminders)

    def test_no_mcp_calls_shows_reminders(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": ""})
        assert any("local_check was not called" in r for r in reminders)
        assert any("No local_review_diff" in r for r in reminders)

    def test_failed_mcp_shows_warning(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["mcp_calls"] = {
            "mcp__local-llm__local_check": True,
            "mcp__local-llm__local_review_diff": True,
            "_last_mcp_failed": True,
        }
        mcp_gate.save_state(tmp_config_dir, state)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": ""})
        assert any("failed" in r.lower() or "FAILED" in r for r in reminders)

    def test_dirty_tree_without_review(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)

        def _fake_git(args, cwd=None):
            if args == ["status", "--short"]:
                return " M test.txt\n M src/foo.py"
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": "/fake/repo"})
        assert any("dirty" in r.lower() for r in reminders)
        assert any("review" in r.lower() for r in reminders)

    def test_staged_diff_reminder(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["diff_reviewed"] = True
        state["mcp_calls"] = {
            "mcp__local-llm__local_check": True,
            "mcp__local-llm__local_review_diff": True,
        }
        mcp_gate.save_state(tmp_config_dir, state)

        def _fake_git(args, cwd=None):
            if args == ["status", "--short"]:
                return ""
            if args == ["diff", "--cached", "--stat"]:
                return " test.txt | 2 +-"
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": "/fake/repo"})
        assert any("staged" in r.lower() for r in reminders)


# ---------------------------------------------------------------------------
# session boundary
# ---------------------------------------------------------------------------

class TestSessionBoundary:
    def test_session_start_clears_mcp_calls(self, tmp_config_dir):
        """SessionStart must clear previous session's mcp_calls."""
        # Simulate a previous session with MCP calls
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["mcp_calls"] = {
            "mcp__local-llm__local_check": True,
            "mcp__local-llm__local_review_diff": True,
        }
        old_session_id = state["session_id"]
        mcp_gate.save_state(tmp_config_dir, state)

        # Start new session
        mcp_gate.handle_session_start(tmp_config_dir, {})

        # Verify
        new_state = mcp_gate.load_state(tmp_config_dir)
        assert new_state["session_id"] != old_session_id
        assert new_state["mcp_calls"] == {}
        assert new_state["_last_mcp_failed"] is False

    def test_session_boundary_prevents_contamination(self, tmp_config_dir):
        """Previous session's mcp_calls must not leak into Stop summary."""
        # Session 1: did local_check
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["mcp_calls"] = {"mcp__local-llm__local_check": True}
        mcp_gate.save_state(tmp_config_dir, state)

        # Session 2: fresh, no MCP calls
        mcp_gate.handle_session_start(tmp_config_dir, {})

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": ""})
        assert any("local_check was not called" in r for r in reminders), \
            "Session 2 should not see Session 1's local_check"


# ---------------------------------------------------------------------------
# MCP tracking in PostToolUse
# ---------------------------------------------------------------------------

class TestMcpTracking:
    def test_mcp_call_recorded(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_check",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["mcp_calls"]["mcp__local-llm__local_check"] is True

    def test_failed_mcp_tracked(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": {"type": "text", "text": json.dumps({"ok": False})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["mcp_calls"]["_last_mcp_failed"] is True
        assert state["diff_reviewed"] is False


# ---------------------------------------------------------------------------
# commit gate unchanged
# ---------------------------------------------------------------------------

class TestCommitGateUnchanged:
    def test_commit_without_review_blocked(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
        })
        assert result["allow"] is False

    def test_commit_with_valid_review_allowed(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        fp = {"repo": "/fake/repo", "head": "abc123", "diff_hash": "def456"}
        monkeypatch.setattr(mcp_gate, "get_repo_fingerprint", lambda cwd=None: fp)
        state = mcp_gate.load_state(tmp_config_dir)
        state.update({
            "diff_reviewed": True,
            "dirty_since_review": False,
            "reviewed_repo": "/fake/repo",
            "reviewed_head": "abc123",
            "reviewed_diff_hash": "def456",
        })
        mcp_gate.save_state(tmp_config_dir, state)

        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
            "cwd": "/fake/repo",
        })
        assert result["allow"] is True

    def test_dirty_after_review_invalidates(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        fp = {"repo": "/fake/repo", "head": "abc123", "diff_hash": "def456"}
        monkeypatch.setattr(mcp_gate, "get_repo_fingerprint", lambda cwd=None: fp)
        state = mcp_gate.load_state(tmp_config_dir)
        state.update({
            "diff_reviewed": True,
            "dirty_since_review": True,
            "reviewed_repo": "/fake/repo",
            "reviewed_head": "abc123",
            "reviewed_diff_hash": "def456",
        })
        mcp_gate.save_state(tmp_config_dir, state)

        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
            "cwd": "/fake/repo",
        })
        assert result["allow"] is False

    def test_cross_repo_review_rejected(self, tmp_config_dir, monkeypatch):
        """Review from a different repo must not be accepted."""
        mcp_gate._clear_session(tmp_config_dir)
        fp_current = {"repo": "/fake/repo-B", "head": "xyz", "diff_hash": "999"}
        monkeypatch.setattr(mcp_gate, "get_repo_fingerprint", lambda cwd=None: fp_current)
        state = mcp_gate.load_state(tmp_config_dir)
        state.update({
            "diff_reviewed": True,
            "dirty_since_review": False,
            "reviewed_repo": "/fake/repo-A",
            "reviewed_head": "abc123",
            "reviewed_diff_hash": "def456",
        })
        mcp_gate.save_state(tmp_config_dir, state)

        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
            "cwd": "/fake/repo-B",
        })
        assert result["allow"] is False


# ---------------------------------------------------------------------------
# handle_session_start
# ---------------------------------------------------------------------------

class TestSessionStart:
    def test_creates_session_id(self, tmp_config_dir):
        mcp_gate.handle_session_start(tmp_config_dir, {})
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["session_id"] is not None
        assert len(state["session_id"]) == 12

    def test_does_not_clear_commit_gate_state(self, tmp_config_dir):
        """SessionStart clears mcp_calls but preserves commit gate fields."""
        state = mcp_gate.load_state(tmp_config_dir)
        state["diff_reviewed"] = True
        state["reviewed_repo"] = "/some/repo"
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_session_start(tmp_config_dir, {})

        new_state = mcp_gate.load_state(tmp_config_dir)
        assert new_state["diff_reviewed"] is True
        assert new_state["reviewed_repo"] == "/some/repo"
        assert new_state["mcp_calls"] == {}
