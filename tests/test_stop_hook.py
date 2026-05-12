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


# ---------------------------------------------------------------------------
# Phase 2B: dangerous command guard
# ---------------------------------------------------------------------------

class TestDangerousCommandGuard:
    """Dangerous shell commands must be blocked."""

    def test_git_reset_hard_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~1"},
        })
        assert result["allow"] is False
        assert "reset" in result["reason"].lower()

    def test_git_clean_fd_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git clean -fd"},
        })
        assert result["allow"] is False

    def test_git_clean_xdf_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git clean -xdf"},
        })
        assert result["allow"] is False

    def test_rm_rf_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/build"},
        })
        assert result["allow"] is False

    def test_windows_del_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "PowerShell",
            "tool_input": {"command": "del /s /q *.tmp"},
        })
        assert result["allow"] is False

    def test_remove_item_recurse_force_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "PowerShell",
            "tool_input": {"command": "Remove-Item -Recurse -Force build/"},
        })
        assert result["allow"] is False

    def test_git_push_force_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        })
        assert result["allow"] is False

    def test_git_push_f_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push -f"},
        })
        assert result["allow"] is False


class TestSafeCommandsNotBlocked:
    """Safe commands must pass through."""

    def test_git_status_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        })
        assert result["allow"] is True

    def test_git_diff_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git diff"},
        })
        assert result["allow"] is True

    def test_git_log_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline"},
        })
        assert result["allow"] is True

    def test_pytest_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "python -m pytest tests/ -q"},
        })
        assert result["allow"] is True

    def test_git_branch_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git branch"},
        })
        assert result["allow"] is True

    def test_echo_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'rm -rf is dangerous'"},
        })
        assert result["allow"] is True

    def test_no_tool_name_allowed(self, tmp_config_dir):
        """Non-Bash/PowerShell tools never match dangerous patterns."""
        result = mcp_gate.is_dangerous_command({
            "tool_name": "Edit",
            "tool_input": {"command": "rm -rf /"},
        })
        assert result == (False, "")


class TestDangerousCommandDoesNotBreakCommitGate:
    """Dangerous command guard must not affect commit gate behavior."""

    def test_commit_still_blocked_without_review(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
        })
        assert result["allow"] is False
        assert "review" in result["reason"].lower()

    def test_dangerous_blocked_before_commit_check(self, tmp_config_dir):
        """Dangerous command should be blocked before we even check review state."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD"},
        })
        assert result["allow"] is False
        # Reason should mention dangerous command, not commit gate
        assert "dangerous" in result["reason"].lower()
