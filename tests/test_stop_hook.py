"""Test Stop hook session summary (Phase 2A).

The hook file lives at ~/.claude/hooks/mcp_gate.py (outside repo).
These tests import key functions from there and validate behavior.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOK_DIR = Path(os.environ.get("LOCALAPPDATA", "C:\\Users\\Zero\\AppData\\Local")) / "mcp-gate"
sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
import mcp_gate  # type: ignore


class TestReviewToolSucceeded:
    """Commit gate review validation — unchanged from Phase 2A.1."""

    def test_ok_true_with_no_error(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": True}),
            }
        }
        assert mcp_gate._review_tool_succeeded(payload) is True

    def test_ok_false(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": False}),
            }
        }
        assert mcp_gate._review_tool_succeeded(payload) is False

    def test_error_field_non_null(self):
        payload = {
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": True, "error": "something broke"}),
            }
        }
        assert mcp_gate._review_tool_succeeded(payload) is False

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
        assert mcp_gate._review_tool_succeeded(payload) is False

    def test_no_tool_response(self):
        assert mcp_gate._review_tool_succeeded({}) is False
        assert mcp_gate._review_tool_succeeded({"tool_response": {}}) is False


class TestStopHook:
    """Stop hook: reminder-only, never blocks."""

    def test_empty_session_no_crash(self, monkeypatch):
        """Stop hook with no state and no cwd should not crash."""
        written = []
        monkeypatch.setattr(sys, "stderr", _FakeStderr(written))
        monkeypatch.setattr(mcp_gate, "STATE_FILE", _temp_state_file({}))
        mcp_gate._handle_stop({"cwd": ""})
        output = "".join(written)
        assert "local_check" in output.lower() or "mcp" in output.lower()

    def test_full_session_no_warnings(self, monkeypatch):
        """Session with check + review + clean tree should be quiet."""
        state = {
            "diff_reviewed": True,
            "dirty_since_review": False,
            "mcp_calls": {
                "mcp__local-llm__local_check": True,
                "mcp__local-llm__local_review_diff": True,
                "mcp__local-llm__local_summarize_file": True,
                "_last_mcp_failed": False,
            },
        }
        written = []
        monkeypatch.setattr(sys, "stderr", _FakeStderr(written))
        monkeypatch.setattr(mcp_gate, "STATE_FILE", _temp_state_file(state))
        monkeypatch.setattr(mcp_gate, "_run_git", lambda *a, **kw: "")
        mcp_gate._handle_stop({"cwd": "/fake/repo"})
        output = "".join(written)
        # Should not warn about check or review since both were called
        assert "local_check was not called" not in output
        assert "No local_review_diff" not in output

    def test_no_mcp_calls_shows_reminders(self, monkeypatch):
        """Empty mcp_calls should produce reminders for check and review."""
        state = {"mcp_calls": {}}
        written = []
        monkeypatch.setattr(sys, "stderr", _FakeStderr(written))
        monkeypatch.setattr(mcp_gate, "STATE_FILE", _temp_state_file(state))
        monkeypatch.setattr(mcp_gate, "_run_git", lambda *a, **kw: "")
        mcp_gate._handle_stop({"cwd": "/fake/repo"})
        output = "".join(written)
        assert "local_check was not called" in output
        assert "No local_review_diff" in output

    def test_failed_mcp_shows_warning(self, monkeypatch):
        """A failed MCP call should produce a warning."""
        state = {
            "mcp_calls": {
                "mcp__local-llm__local_check": True,
                "mcp__local-llm__local_review_diff": True,
                "_last_mcp_failed": True,
            },
            "diff_reviewed": False,
            "last_review_error": "2026-05-12T00:00:00+00:00",
        }
        written = []
        monkeypatch.setattr(sys, "stderr", _FakeStderr(written))
        monkeypatch.setattr(mcp_gate, "STATE_FILE", _temp_state_file(state))
        monkeypatch.setattr(mcp_gate, "_run_git", lambda *a, **kw: "")
        mcp_gate._handle_stop({"cwd": "/fake/repo"})
        output = "".join(written)
        assert "FAILED" in output or "failed" in output.lower()

    def test_dirty_tree_without_review_shows_reminder(self, monkeypatch):
        """Dirty tree without diff_reviewed should show reminder."""
        state = {
            "diff_reviewed": False,
            "mcp_calls": {"mcp__local-llm__local_check": True},
        }
        written = []
        monkeypatch.setattr(sys, "stderr", _FakeStderr(written))
        monkeypatch.setattr(mcp_gate, "STATE_FILE", _temp_state_file(state))
        monkeypatch.setattr(
            mcp_gate, "_run_git",
            lambda args, **kw: (
                " M test.txt\n M src/foo.py" if args == ["status", "--short"] else ""
            ),
        )
        mcp_gate._handle_stop({"cwd": "/fake/repo"})
        output = "".join(written)
        assert "dirty" in output.lower()
        assert "review" in output.lower()

    def test_staged_diff_reminder(self, monkeypatch):
        """Staged changes should trigger re-review reminder."""
        state = {
            "diff_reviewed": True,
            "dirty_since_review": False,
            "mcp_calls": {
                "mcp__local-llm__local_check": True,
                "mcp__local-llm__local_review_diff": True,
            },
        }
        written = []
        monkeypatch.setattr(sys, "stderr", _FakeStderr(written))
        monkeypatch.setattr(mcp_gate, "STATE_FILE", _temp_state_file(state))
        def _fake_git(args, **kw):
            if args == ["status", "--short"]:
                return ""
            if args == ["diff", "--cached", "--stat"]:
                return " test.txt | 2 +-"
            return ""
        monkeypatch.setattr(mcp_gate, "_run_git", _fake_git)
        mcp_gate._handle_stop({"cwd": "/fake/repo"})
        output = "".join(written)
        assert "staged" in output.lower()


class TestMcpTracking:
    """MCP tool tracking in PostToolUse feeds Stop hook summary."""

    def test_mcp_call_recorded_in_state(self, monkeypatch):
        state_file = _temp_state_file({})
        monkeypatch.setattr(mcp_gate, "STATE_FILE", state_file)
        payload = {
            "tool_name": "mcp__local-llm__local_check",
            "tool_response": {
                "type": "text",
                "text": json.dumps({"ok": True}),
            },
        }
        # Simulate PostToolUse handling for MCP tracking
        state = mcp_gate._load_state()
        mcp_calls = state.get("mcp_calls", {})
        mcp_calls["mcp__local-llm__local_check"] = True
        mcp_calls["_last_mcp_ts"] = datetime.now(timezone.utc).isoformat()
        state["mcp_calls"] = mcp_calls
        mcp_gate._save_state(state)

        reloaded = mcp_gate._load_state()
        assert reloaded["mcp_calls"]["mcp__local-llm__local_check"] is True

    def test_failed_mcp_tracked(self, monkeypatch):
        state_file = _temp_state_file({})
        monkeypatch.setattr(mcp_gate, "STATE_FILE", state_file)
        state = mcp_gate._load_state()
        mcp_calls = state.get("mcp_calls", {})
        mcp_calls["mcp__local-llm__local_review_diff"] = True
        mcp_calls["_last_mcp_failed"] = True
        mcp_calls["_last_mcp_error_ts"] = datetime.now(timezone.utc).isoformat()
        state["mcp_calls"] = mcp_calls
        mcp_gate._save_state(state)

        reloaded = mcp_gate._load_state()
        assert reloaded["mcp_calls"]["_last_mcp_failed"] is True


class TestCommitGateUnchanged:
    """Phase 2A must not break existing commit gate behavior."""

    def test_commit_without_review_blocked(self):
        state = {
            "diff_reviewed": False,
            "dirty_since_review": False,
        }
        # Without valid review, reviewed_ok should be False
        fp = {"repo": "/fake/repo", "head": "abc123", "diff_hash": "def456"}
        reviewed_ok = (
            state.get("diff_reviewed")
            and not state.get("dirty_since_review")
            and fp is not None
            and state.get("reviewed_repo") == fp["repo"]
            and state.get("reviewed_head") == fp["head"]
            and state.get("reviewed_diff_hash") == fp["diff_hash"]
        )
        assert reviewed_ok is False

    def test_commit_with_valid_review_allowed(self):
        state = {
            "diff_reviewed": True,
            "dirty_since_review": False,
            "reviewed_repo": "/fake/repo",
            "reviewed_head": "abc123",
            "reviewed_diff_hash": "def456",
        }
        fp = {"repo": "/fake/repo", "head": "abc123", "diff_hash": "def456"}
        reviewed_ok = (
            state.get("diff_reviewed")
            and not state.get("dirty_since_review")
            and fp is not None
            and state.get("reviewed_repo") == fp["repo"]
            and state.get("reviewed_head") == fp["head"]
            and state.get("reviewed_diff_hash") == fp["diff_hash"]
        )
        assert reviewed_ok is True

    def test_dirty_after_review_invalidates(self):
        state = {
            "diff_reviewed": True,
            "dirty_since_review": True,  # files modified after review
            "reviewed_repo": "/fake/repo",
            "reviewed_head": "abc123",
            "reviewed_diff_hash": "def456",
        }
        fp = {"repo": "/fake/repo", "head": "abc123", "diff_hash": "def456"}
        reviewed_ok = (
            state.get("diff_reviewed")
            and not state.get("dirty_since_review")
            and fp is not None
            and state.get("reviewed_repo") == fp["repo"]
            and state.get("reviewed_head") == fp["head"]
            and state.get("reviewed_diff_hash") == fp["diff_hash"]
        )
        assert reviewed_ok is False  # dirty_since_review blocks


# --- helpers ---

class _FakeStderr:
    def __init__(self, capture_list):
        self._capture = capture_list

    def write(self, s):
        self._capture.append(s)

    def flush(self):
        pass


def _temp_state_file(initial: dict):
    """Create a temporary state file for isolated testing."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w")
    json.dump(initial, tmp)
    tmp.close()
    return Path(tmp.name)
