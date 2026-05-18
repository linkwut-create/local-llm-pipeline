"""E2E tests for release guard: tag, push, publish blocking and bypass."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the gate module directly
import tools.claude_hooks.mcp_gate as mcp_gate

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temp config dir with clean state."""
    d = tmp_path / "mcp_gate"
    d.mkdir()
    return str(d)


@pytest.fixture
def fake_git_repo(tmp_path, monkeypatch):
    """Mock git to return consistent fingerprints."""
    repo = str(tmp_path / "fake_repo")
    monkeypatch.setattr(mcp_gate, "get_repo_root", lambda cwd=None: repo)
    monkeypatch.setattr(mcp_gate, "get_head", lambda cwd=None: "abc123def456")
    monkeypatch.setattr(mcp_gate, "get_diff_hash", lambda cwd=None: "hash123")
    return repo


class TestReleaseCommandDetection:
    def test_git_tag_creation_detected(self):
        ok, desc = mcp_gate.is_release_command({
            "tool_name": "Bash",
            "tool_input": {"command": "git tag v1.0"},
        })
        assert ok
        assert "tag" in desc.lower()

    def test_git_tag_listing_not_detected(self):
        ok, _ = mcp_gate.is_release_command({
            "tool_name": "Bash",
            "tool_input": {"command": "git tag -l"},
        })
        assert not ok

    def test_git_push_detected(self):
        ok, desc = mcp_gate.is_release_command({
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        })
        assert ok
        assert "push" in desc.lower()

    def test_npm_publish_detected(self):
        ok, _ = mcp_gate.is_release_command({
            "tool_name": "Bash",
            "tool_input": {"command": "npm publish"},
        })
        assert ok

    def test_twine_upload_detected(self):
        ok, _ = mcp_gate.is_release_command({
            "tool_name": "Bash",
            "tool_input": {"command": "twine upload dist/*"},
        })
        assert ok

    def test_regular_git_commit_not_detected(self):
        ok, _ = mcp_gate.is_release_command({
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'fix'"},
        })
        assert not ok

    def test_non_bash_tool_not_detected(self):
        ok, _ = mcp_gate.is_release_command({
            "tool_name": "Read",
            "tool_input": {"file_path": "foo.py"},
        })
        assert not ok


class TestReleaseGuardBlocking:
    def test_blocks_git_tag_without_debate(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """git tag should be blocked when no debate review exists."""
        mcp_gate._clear_session(tmp_config_dir)
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git tag v1.0"},
            "cwd": fake_git_repo,
        })
        assert result["allow"] is False
        assert "debate review" in result["reason"].lower()

    def test_blocks_git_push_without_debate(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """git push should be blocked when no debate review exists."""
        mcp_gate._clear_session(tmp_config_dir)
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "cwd": fake_git_repo,
        })
        assert result["allow"] is False

    def test_allows_with_debate_state(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """After a debate review is completed, release should be allowed."""
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["debate_reviewed"] = True
        state["debate_head"] = "abc123def456"
        state["dirty_since_debate"] = False
        mcp_gate.save_state(tmp_config_dir, state)

        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git tag v1.0"},
            "cwd": fake_git_repo,
        })
        assert result.get("allow") is not False, f"Expected allowed, got: {result}"

    def test_blocks_when_head_changed_after_debate(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """Release should be blocked if HEAD changed since debate review."""
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["debate_reviewed"] = True
        state["debate_head"] = "old_head_999"
        state["dirty_since_debate"] = False
        mcp_gate.save_state(tmp_config_dir, state)

        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "cwd": fake_git_repo,
        })
        assert result["allow"] is False
        assert "head" in result["reason"].lower()

    def test_blocks_when_dirty_after_debate(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """Release should be blocked if files modified since debate review."""
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["debate_reviewed"] = True
        state["debate_head"] = "abc123def456"
        state["dirty_since_debate"] = True
        mcp_gate.save_state(tmp_config_dir, state)

        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "cwd": fake_git_repo,
        })
        assert result["allow"] is False


class TestEmergencyBypass:
    def test_bypass_allows_release_without_debate(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """--emergency-release flag bypasses debate review prerequisite."""
        mcp_gate._clear_session(tmp_config_dir)
        # No debate state set
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main --emergency-release"},
            "cwd": fake_git_repo,
        })
        assert result.get("allow") is not False, (
            f"Emergency bypass should allow push, got: {result}"
        )

    def test_bypass_not_allowed_on_dangerous_commands(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """Emergency bypass does NOT override dangerous command guard."""
        mcp_gate._clear_session(tmp_config_dir)
        # rm -rf / should still be blocked even with --emergency-release
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf / --emergency-release"},
            "cwd": fake_git_repo,
        })
        # Dangerous guard runs FIRST, so this should be blocked before release check
        assert result["allow"] is False

    def test_regular_push_without_bypass_still_blocked(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """Without --emergency-release flag, push is still blocked."""
        mcp_gate._clear_session(tmp_config_dir)
        result = mcp_gate.handle_pre_tooluse(tmp_config_dir, {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "cwd": fake_git_repo,
        })
        assert result["allow"] is False


class TestDebateStateTracking:
    def test_post_tooluse_sets_debate_state(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """After a successful debate review, release state should be set."""
        mcp_gate._clear_session(tmp_config_dir)
        fp = {"repo": fake_git_repo, "head": "abc123def456", "diff_hash": "hash123"}
        monkeypatch.setattr(mcp_gate, "get_repo_fingerprint", lambda cwd=None: fp)

        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "hook_event_name": "PostToolUse",
            "tool_name": "mcp__local-llm__local_debate_review_diff",
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": True})}
            ],
            "cwd": fake_git_repo,
        })

        state = mcp_gate.load_state(tmp_config_dir)
        assert state.get("debate_reviewed") is True
        assert state.get("debate_head") == "abc123def456"
        assert state.get("dirty_since_debate") is False

    def test_edit_after_debate_sets_dirty(self, tmp_config_dir, fake_git_repo, monkeypatch):
        """Editing a file after debate should mark dirty_since_debate."""
        mcp_gate._clear_session(tmp_config_dir)
        fp = {"repo": fake_git_repo, "head": "abc123def456", "diff_hash": "hash123"}
        monkeypatch.setattr(mcp_gate, "get_repo_fingerprint", lambda cwd=None: fp)

        # First complete debate
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "hook_event_name": "PostToolUse",
            "tool_name": "mcp__local-llm__local_debate_review_diff",
            "tool_response": [
                {"type": "text", "text": json.dumps({"ok": True})}
            ],
            "cwd": fake_git_repo,
        })

        # Then edit a file
        mcp_gate.handle_post_tooluse(tmp_config_dir, {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/main.py"},
            "cwd": fake_git_repo,
        })

        state = mcp_gate.load_state(tmp_config_dir)
        assert state.get("dirty_since_debate") is True


class TestReleaseCheckPrerequisites:
    def test_empty_state_returns_false(self, tmp_config_dir, fake_git_repo, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        ok, reason = mcp_gate._check_release_prerequisites(tmp_config_dir, fake_git_repo)
        assert not ok

    def test_matching_head_returns_true(self, tmp_config_dir, fake_git_repo, monkeypatch):
        mcp_gate._clear_session(tmp_config_dir)
        state = mcp_gate.load_state(tmp_config_dir)
        state["debate_reviewed"] = True
        state["debate_head"] = "abc123def456"
        state["dirty_since_debate"] = False
        mcp_gate.save_state(tmp_config_dir, state)
        ok, _ = mcp_gate._check_release_prerequisites(tmp_config_dir, fake_git_repo)
        assert ok
