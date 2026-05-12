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

    # Phase 2B.1: MCP array-format tool_response (real Claude Code MCP payloads)

    def test_mcp_array_format_ok_true(self):
        """Real MCP PostToolUse payloads have tool_response as a LIST of
        content blocks: [{"type": "text", "text": "{...}"}]."""
        payload = {
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": True})},
            ]
        }
        assert mcp_gate.review_tool_succeeded(payload) is True

    def test_mcp_array_format_ok_false(self):
        payload = {
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": False})},
            ]
        }
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_mcp_array_format_with_error(self):
        payload = {
            "tool_response": [
                {"type": "text", "text": json.dumps({
                    "ok": True, "error": "worker failed",
                })},
            ]
        }
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_mcp_array_format_empty_list(self):
        payload = {"tool_response": []}
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_mcp_array_format_no_text_items(self):
        payload = {
            "tool_response": [
                {"type": "image", "data": "base64..."},
                {"type": "resource", "uri": "file:///..."},
            ]
        }
        assert mcp_gate.review_tool_succeeded(payload) is False

    def test_mcp_array_format_multiple_items_first_is_text(self):
        """Should use the first text-type content block."""
        payload = {
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": True})},
                {"type": "text", "text": "some extra output"},
            ]
        }
        assert mcp_gate.review_tool_succeeded(payload) is True

    def test_mcp_array_format_review_state_updated(self, tmp_config_dir, monkeypatch):
        """handle_post_tooluse must correctly update review state when
        tool_response is in MCP array format."""
        mcp_gate._clear_session(tmp_config_dir)
        fp = {"repo": "/fake/repo", "head": "abc123", "diff_hash": "def456"}
        monkeypatch.setattr(mcp_gate, "get_repo_fingerprint", lambda cwd=None: fp)

        # Simulate a real MCP review_diff PostToolUse with array-format response
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_input": {"diff_text": "...", "commit_gate": True},
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": True})},
            ],
            "cwd": "/fake/repo",
        })

        state = mcp_gate.load_state(tmp_config_dir)
        assert state["diff_reviewed"] is True
        assert state["dirty_since_review"] is False
        assert state["reviewed_repo"] == "/fake/repo"
        assert state["reviewed_head"] == "abc123"
        assert state["reviewed_diff_hash"] == "def456"
        assert "last_review_error" not in state

    def test_mcp_array_format_failed_review_clears_state(self, tmp_config_dir):
        """A failed review must clear diff_reviewed."""
        mcp_gate._clear_session(tmp_config_dir)
        # Pre-set as reviewed
        state = mcp_gate.load_state(tmp_config_dir)
        state["diff_reviewed"] = True
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_input": {"diff_text": "...", "commit_gate": True},
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": False})},
            ],
        })

        state = mcp_gate.load_state(tmp_config_dir)
        assert state["diff_reviewed"] is False
        assert "last_review_error" in state


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

    def test_mcp_failure_cleared_by_success(self, tmp_config_dir):
        """Phase 2F: _last_mcp_failed must be cleared after a successful MCP call."""
        mcp_gate._clear_session(tmp_config_dir)
        # Simulate a failed MCP call
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_check",
            "tool_response": {"type": "text", "text": json.dumps({"ok": False})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["mcp_calls"]["_last_mcp_failed"] is True

        # A subsequent successful call must clear the failure flag
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_check",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["mcp_calls"]["_last_mcp_failed"] is False
        assert "_last_mcp_error_ts" not in state["mcp_calls"]


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

    # Phase 2B.1: regression tests for dangerous guard false positives

    def test_git_commit_message_mentioning_reset_not_dangerous(self, tmp_config_dir):
        """git commit -m mentioning git reset --hard must NOT be blocked by
        dangerous guard. It should fall through to the commit gate instead."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "docs: mention git reset --hard"'},
        })
        # Should not be blocked by dangerous guard
        # (commit gate will block it, but for lack of review, not danger)
        assert result["allow"] is False
        assert "review" in result["reason"].lower()
        assert "dangerous" not in result["reason"].lower()

    def test_git_commit_message_mentioning_del_not_dangerous(self, tmp_config_dir):
        """git commit -m mentioning del /s /q must NOT be blocked by
        dangerous guard."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "docs: mention del /s /q"'},
        })
        assert result["allow"] is False
        assert "review" in result["reason"].lower()
        assert "dangerous" not in result["reason"].lower()

    def test_echo_dangerous_text_not_blocked(self, tmp_config_dir):
        """Echo of dangerous-looking text must not be blocked."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'echo "git reset --hard is dangerous"'},
        })
        assert result["allow"] is True

    def test_real_git_reset_still_blocked(self, tmp_config_dir):
        """Real git reset --hard must still be blocked after refactoring."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~1"},
        })
        assert result["allow"] is False
        assert "dangerous" in result["reason"].lower()

    def test_real_del_still_blocked(self, tmp_config_dir):
        """Real del /s /q must still be blocked after refactoring."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "PowerShell",
            "tool_input": {"command": "del /s /q *.tmp"},
        })
        assert result["allow"] is False
        assert "dangerous" in result["reason"].lower()

    def test_no_tool_name_allowed(self, tmp_config_dir):
        """Non-Bash/PowerShell tools never match dangerous patterns."""
        result = mcp_gate.is_dangerous_command({
            "tool_name": "Edit",
            "tool_input": {"command": "rm -rf /"},
        })
        assert result == (False, "")

    # Phase 2C: safe commands must not trigger release guard

    def test_git_fetch_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git fetch"},
        })
        assert result["allow"] is True

    def test_git_pull_ff_only_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git pull --ff-only"},
        })
        assert result["allow"] is True

    def test_git_remote_v_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git remote -v"},
        })
        assert result["allow"] is True

    def test_git_tag_listing_allowed(self, tmp_config_dir):
        """git tag (no args, listing) must not be blocked."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git tag"},
        })
        assert result["allow"] is True

    def test_git_tag_list_l_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git tag -l"},
        })
        assert result["allow"] is True

    def test_git_tag_list_pattern_allowed(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git tag -l "v0.1*"'},
        })
        assert result["allow"] is True


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


# ---------------------------------------------------------------------------
# Phase 2C: release / tag / push guard
# ---------------------------------------------------------------------------

class TestReleaseCommandGuard:
    """Release/publish commands must be blocked."""

    def test_git_tag_lightweight_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git tag v0.1.0"},
        })
        assert result["allow"] is False
        assert "tag" in result["reason"].lower()

    def test_git_tag_annotated_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git tag -a v0.1.0 -m "release"'},
        })
        assert result["allow"] is False
        assert "tag" in result["reason"].lower()

    def test_git_push_master_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin master"},
        })
        assert result["allow"] is False
        assert "push" in result["reason"].lower()

    def test_git_push_main_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        })
        assert result["allow"] is False
        assert "push" in result["reason"].lower()

    def test_git_push_tags_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --tags"},
        })
        assert result["allow"] is False
        assert "push" in result["reason"].lower()

    def test_git_push_specific_tag_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin v0.1.0"},
        })
        assert result["allow"] is False
        assert "push" in result["reason"].lower()

    def test_git_push_bare_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push"},
        })
        assert result["allow"] is False
        assert "push" in result["reason"].lower()

    def test_npm_publish_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "npm publish"},
        })
        assert result["allow"] is False
        assert "publish" in result["reason"].lower()

    def test_twine_upload_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "twine upload dist/*"},
        })
        assert result["allow"] is False
        assert "twine" in result["reason"].lower()

    def test_python_m_twine_upload_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "python -m twine upload dist/*"},
        })
        assert result["allow"] is False
        assert "twine" in result["reason"].lower()

    def test_npm_run_release_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run release"},
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()


class TestReleaseGuardFalsePositives:
    """Release guard must not trigger on commit messages, echo, or tag listing."""

    def test_echo_release_text_not_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'echo "git push origin main is dangerous"'},
        })
        assert result["allow"] is True

    def test_commit_message_mentioning_push_not_release_blocked(self, tmp_config_dir):
        """git commit -m mentioning push must fall through to commit gate,
        not be blocked by release guard."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "docs: mention git push origin main"'},
        })
        assert result["allow"] is False
        assert "review" in result["reason"].lower()
        assert "release" not in result["reason"].lower()
        assert "push" not in result["reason"].lower()

    def test_commit_message_mentioning_tag_not_release_blocked(self, tmp_config_dir):
        """git commit -m mentioning tag must fall through to commit gate."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "docs: mention git tag v0.1.0"'},
        })
        assert result["allow"] is False
        assert "review" in result["reason"].lower()
        assert "release" not in result["reason"].lower()
        assert "tag" not in result["reason"].lower()

    def test_tag_message_with_push_keyword_still_tag_blocked(self, tmp_config_dir):
        """git tag -a with 'push' in message must be blocked as tag creation,
        not confused by the message content."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git tag -a v0.1.0 -m "push notes"'},
        })
        assert result["allow"] is False
        assert "tag" in result["reason"].lower()


class TestReleaseGuardGuardOrdering:
    """Release guard must layer correctly with dangerous guard and commit gate."""

    def test_dangerous_blocked_before_release(self, tmp_config_dir):
        """git push --force must be blocked by dangerous guard (first),
        not by release guard."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        })
        assert result["allow"] is False
        assert "dangerous" in result["reason"].lower()

    def test_release_blocked_before_commit_check(self, tmp_config_dir):
        """Chained release + commit must be blocked by release guard first."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": 'git push origin main && git commit -m "test"'},
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()

    def test_release_guard_does_not_affect_commit_gate(self, tmp_config_dir):
        """Plain git commit without review must still be blocked by commit gate."""
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
        })
        assert result["allow"] is False
        assert "review" in result["reason"].lower()
        assert "release" not in result["reason"].lower()


# ---------------------------------------------------------------------------
# Phase 2C.1: PowerShell here-string commit message false positive fix
# ---------------------------------------------------------------------------

class TestHereStringCommitMessages:
    """git commit with PowerShell here-string @'...'@ must not trigger
    dangerous or release guards. These must fall through to commit gate."""

    def _assert_commit_gate_blocks(self, result):
        assert result["allow"] is False
        reason = result["reason"].lower()
        assert "review" in reason or "commit" in reason
        assert "dangerous" not in reason
        assert "release" not in reason

    def test_herestring_mentioning_twine_upload(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m @'\ndocs: mention twine upload\n'@"},
        })
        self._assert_commit_gate_blocks(result)

    def test_herestring_mentioning_npm_publish(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m @'\ndocs: mention npm publish\n'@"},
        })
        self._assert_commit_gate_blocks(result)

    def test_herestring_mentioning_push_origin_main(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m @'\ndocs: mention git push origin main\n'@"},
        })
        self._assert_commit_gate_blocks(result)

    def test_herestring_mentioning_git_tag(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m @'\ndocs: mention git tag v0.1.0\n'@"},
        })
        self._assert_commit_gate_blocks(result)

    def test_herestring_mentioning_git_reset_hard(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m @'\ndocs: mention git reset --hard\n'@"},
        })
        self._assert_commit_gate_blocks(result)

    def test_herestring_mentioning_del(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m @'\ndocs: mention del /s /q\n'@"},
        })
        self._assert_commit_gate_blocks(result)


class TestHereStringRealCommandsStillBlocked:
    """Real commands must still be blocked after here-string fix."""

    def test_git_push_still_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()

    def test_npm_publish_still_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "npm publish"},
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()

    def test_git_tag_still_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git tag v0.1.0"},
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()

    def test_git_reset_hard_still_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD"},
        })
        assert result["allow"] is False
        assert "dangerous" in result["reason"].lower()

    def test_del_still_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "PowerShell",
            "tool_input": {"command": "del /s /q *.tmp"},
        })
        assert result["allow"] is False
        assert "dangerous" in result["reason"].lower()

    def test_twine_upload_still_blocked(self, tmp_config_dir):
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": "twine upload dist/*"},
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Phase 3A: default MCP participation reminders
# ---------------------------------------------------------------------------

class TestPhase3ATouchedFiles:
    """PostToolUse must track files modified by Edit/Write/MultiEdit."""

    def test_dirty_tool_records_touched_file(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/src/main.py"},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["dirty_since_review"] is True
        assert "/repo/src/main.py" in state["touched_files"]

    def test_dirty_tool_skips_hook_files(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/.claude/hooks/mcp_gate.py"},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["dirty_since_review"] is False
        assert state["touched_files"] == []

    def test_session_start_clears_touched_files(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["touched_files"] = ["/repo/old.py"]
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_session_start(tmp_config_dir, {})
        new_state = mcp_gate.load_state(tmp_config_dir)
        assert new_state["touched_files"] == []


# ---------------------------------------------------------------------------
# Phase 3B: risk routing
# ---------------------------------------------------------------------------

class TestClassifyDiffRisk:
    def test_small_diff_low(self):
        assert mcp_gate.classify_diff_risk("one line", []) == "low"

    def test_large_diff_medium(self):
        diff = "\n".join(f"line {i}" for i in range(150))
        assert mcp_gate.classify_diff_risk(diff, []) == "medium"

    def test_hook_files_high(self):
        assert mcp_gate.classify_diff_risk("one line", ["tools/claude_hooks/mcp_gate.py"]) == "high"

    def test_doctor_files_high(self):
        assert mcp_gate.classify_diff_risk("one line", ["tools/claude_hooks/mcp_doctor.py"]) == "high"

    def test_release_files_high(self):
        assert mcp_gate.classify_diff_risk("one line", ["scripts/release.sh"]) == "high"


class TestRecommendMcpAction:
    def test_low_risk_recommends_review(self):
        actions = mcp_gate.recommend_mcp_action("low", [], "")
        assert "local_review_diff" in actions
        assert "local_debate_review_diff" not in actions

    def test_high_risk_recommends_debate(self):
        actions = mcp_gate.recommend_mcp_action("high", [], "")
        assert "local_debate_review_diff" in actions

    def test_test_files_recommends_test_plan(self):
        actions = mcp_gate.recommend_mcp_action("low", ["tests/test_main.py"], "")
        assert "local_generate_test_plan" in actions

    def test_docs_only_recommends_summarize(self):
        actions = mcp_gate.recommend_mcp_action("low", ["docs/readme.md"], "")
        assert "local_summarize_file" in actions

    def test_hook_files_triggers_debate(self):
        actions = mcp_gate.recommend_mcp_action("medium", ["tools/claude_hooks/mcp_gate.py"], "")
        assert "local_debate_review_diff" in actions

    def test_never_returns_empty(self):
        actions = mcp_gate.recommend_mcp_action("low", [], "")
        assert len(actions) > 0


class TestPhase3AStopRecommendations:
    """Stop hook must recommend MCP actions based on diff size and file risk."""

    def test_large_diff_recommends_debate(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["touched_files"] = ["/repo/src/big.py"]
        mcp_gate.save_state(tmp_config_dir, state)

        def _fake_git(args, cwd=None):
            if args == ["status", "--short"]:
                return " M src/big.py"
            if args == ["diff", "--stat"]:
                return " src/big.py | 150 ++\n 1 file, 150 insertions(+), 0 deletions(-)"
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": "/repo"})
        assert any("debate" in r.lower() for r in reminders)

    def test_hook_files_touched_recommends_debate(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["touched_files"] = ["/repo/tools/claude_hooks/mcp_gate.py"]
        mcp_gate.save_state(tmp_config_dir, state)

        def _fake_git(args, cwd=None):
            if args == ["status", "--short"]:
                return ""
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": "/repo"})
        assert any("debate" in r.lower() for r in reminders)

    def test_test_files_touched_recommends_test_plan(self, tmp_config_dir, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["touched_files"] = ["/repo/tests/test_main.py"]
        mcp_gate.save_state(tmp_config_dir, state)

        def _fake_git(args, cwd=None):
            if args == ["status", "--short"]:
                return ""
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        reminders = mcp_gate.handle_stop(tmp_config_dir, {"cwd": "/repo"})
        assert any("test_plan" in r.lower() for r in reminders)


# ---------------------------------------------------------------------------
# Phase 3E: real-time default participation
# ---------------------------------------------------------------------------

class TestPhase3ESessionStart:
    def test_session_start_sets_local_check_flag(self, tmp_config_dir):
        mcp_gate.handle_session_start(tmp_config_dir, {})
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["session_needs_local_check"] is True
        assert state["local_check_done"] is False

    def test_local_check_clears_flag(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_check",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["local_check_done"] is True
        assert state["session_needs_local_check"] is False

    def test_failed_local_check_does_not_clear_flag(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_check",
            "tool_response": {"type": "text", "text": json.dumps({"ok": False})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["session_needs_local_check"] is True


class TestPhase3EEditWriteRealTime:
    def test_edit_sets_needs_review(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/src/main.py"},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_review"] is True
        assert "local_review_diff" in state["session_recommendations"]

    def test_edit_hook_file_sets_needs_debate(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/tools/claude_hooks/mcp_gate.py"},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_debate"] is True
        assert "local_debate_review_diff" in state["session_recommendations"]

    def test_edit_test_file_sets_needs_test_plan(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/tests/test_new.py"},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_test_plan"] is True
        assert "local_generate_test_plan" in state["session_recommendations"]

    def test_session_touched_files_accumulates(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/a.py"},
        })
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/b.py"},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert len(state["session_touched_files"]) == 2


class TestPhase3EMcpClearsRecs:
    def test_review_success_clears_needs_review(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        # Set needs_review first
        state = mcp_gate.load_state(tmp_config_dir)
        state["needs_review"] = True
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_review"] is False
        assert state["diff_reviewed"] is True

    def test_debate_success_clears_needs_debate(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["needs_debate"] = True
        state["needs_review"] = True
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_debate_review_diff",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_debate"] is False
        assert state["needs_review"] is False

    def test_summarize_success_clears_needs_summarize(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["needs_summarize"] = ["/repo/big.py"]
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_summarize_file",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_summarize"] == []

    def test_test_plan_success_clears_needs_test_plan(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["needs_test_plan"] = True
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_generate_test_plan",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_test_plan"] is False

    def test_failed_mcp_does_not_clear_flags(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["needs_review"] = True
        mcp_gate.save_state(tmp_config_dir, state)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": {"type": "text", "text": json.dumps({"ok": False})},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_review"] is True


class TestPhase3EReadDetection:
    def test_small_read_no_summarize(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": "/repo/small.py", "limit": 50},
            "tool_response": {"type": "text", "text": "short\n" * 10},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert state["needs_summarize"] == []

    def test_large_read_triggers_summarize(self, tmp_config_dir):
        mcp_gate._clear_session(tmp_config_dir)
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "tool_name": "Read",
            "tool_input": {"file_path": "/repo/big.py"},
            "tool_response": {"type": "text", "text": "line\n" * 400},
        })
        state = mcp_gate.load_state(tmp_config_dir)
        assert "/repo/big.py" in state["needs_summarize"]
        assert "/repo/big.py" in state["session_large_reads"]
        assert "local_summarize_file" in state["session_recommendations"]
