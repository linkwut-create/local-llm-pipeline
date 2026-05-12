"""Phase 3F: cross-project dry-run verification.

All tests use temporary directories. No dependency on the real
local-llm-pipeline repo path or user ~/.claude directory.
"""

import json
import tempfile
from pathlib import Path

from tools.claude_hooks import mcp_doctor, mcp_gate


def _make_external_repo(tmp_path):
    """Create a minimal external git repo simulating local-translator-agent."""
    repo = tmp_path / "translator-project"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / "tools").mkdir()
    (repo / "src" / "main.py").write_text("def translate(): pass\n" * 50)
    (repo / "src" / "db.py").write_text("import sqlite3\n" * 80)
    (repo / "tests" / "test_main.py").write_text("def test(): pass\n" * 10)
    (repo / "docs" / "readme.md").write_text("# Translator\n" * 5)

    # git init
    import subprocess
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)

    return repo


class TestCrossProjectDoctor:
    """mcp_doctor must work with an external repo root and config dir."""

    def test_doctor_external_repo(self, tmp_path, monkeypatch):
        repo = _make_external_repo(tmp_path)
        config = tmp_path / "mcp-config"
        config.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

        results = mcp_doctor.run_checks(str(repo), str(config))
        statuses = {r["status"] for r in results}
        # Should not have fundamental FAILs from repo name
        fails = [r for r in results if r["status"] == "FAIL"]
        # Only FAILs should be about missing wrapper/settings in fake home
        for f in fails:
            assert f["check"] in ("wrapper_exists", "settings_json_valid",
                                  "mcp_gate_module_exists",
                                  "hook_SessionStart", "hook_PreToolUse",
                                  "hook_PostToolUse", "hook_Stop",
                                  "mcp_json", "mcp_server_importable",
                                  "key_functions", "mcp_gate_importable",
                                  "state_readable"), \
                f"Unexpected FAIL: {f['check']}"

    def test_doctor_does_not_require_pipeline_name(self, tmp_path, monkeypatch):
        """Doctor must not hardcode 'local-llm-pipeline' as repo name."""
        repo = _make_external_repo(tmp_path)
        config = tmp_path / "cfg"
        config.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

        # Should not crash or produce name-related errors
        results = mcp_doctor.run_checks(str(repo), str(config))
        messages = " ".join(r["message"] for r in results)
        assert "local-llm-pipeline" not in messages


class TestCrossProjectLifecycle:
    """Full hook lifecycle must work in an external project context."""

    def _setup(self, tmp_path, monkeypatch):
        repo = _make_external_repo(tmp_path)
        config = tmp_path / "mcp-config"
        config.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        return repo, config

    def test_session_start_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate.handle_session_start(str(config), {})
        state = mcp_gate.load_state(str(config))
        assert state["session_needs_local_check"] is True

    def test_read_large_file_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate._clear_session(str(config))

        big_file = repo / "src" / "big_module.py"
        big_file.write_text("line\n" * 500)

        mcp_gate.handle_post_tooluse(str(config), {
            "tool_name": "Read",
            "tool_input": {"file_path": str(big_file)},
            "tool_response": {
                "type": "text",
                "file": {"filePath": str(big_file), "numLines": 500},
            },
        })
        state = mcp_gate.load_state(str(config))
        assert str(big_file) in state["needs_summarize"]

    def test_edit_ordinary_file_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate._clear_session(str(config))

        def _fake_git(args, cwd=None):
            if args == ["diff", "--numstat"]:
                return "3\t2\tsrc/main.py"
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        mcp_gate.handle_post_tooluse(str(config), {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(repo / "src" / "main.py")},
        })
        state = mcp_gate.load_state(str(config))
        assert state["needs_review"] is True
        assert "local_review_diff" in state["session_recommendations"]

    def test_edit_test_file_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate._clear_session(str(config))

        mcp_gate.handle_post_tooluse(str(config), {
            "tool_name": "Write",
            "tool_input": {"file_path": str(repo / "tests" / "test_main.py")},
        })
        state = mcp_gate.load_state(str(config))
        assert state["needs_test_plan"] is True

    def test_stop_recommendations_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate._clear_session(str(config))

        def _fake_git(args, cwd=None):
            if args == ["status", "--short"]:
                return " M src/main.py"
            return ""
        monkeypatch.setattr(mcp_gate, "run_git", _fake_git)

        state = mcp_gate.load_state(str(config))
        state["touched_files"] = [str(repo / "src" / "main.py")]
        state["needs_review"] = True
        state["session_recommendations"] = ["local_review_diff"]
        mcp_gate.save_state(str(config), state)

        reminders = mcp_gate.handle_stop(str(config), {"cwd": str(repo)})
        assert any("needs_review" in r.lower() or "review" in r.lower()
                   for r in reminders)

    def test_commit_blocked_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate._clear_session(str(config))

        state = mcp_gate.load_state(str(config))
        state["needs_review"] = True
        mcp_gate.save_state(str(config), state)

        result = mcp_gate.handle_pre_tooluse(str(config), {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"},
            "cwd": str(repo),
        })
        assert result["allow"] is False
        assert "local_review_diff" in result["reason"]

    def test_mcp_success_clears_flags_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        mcp_gate._clear_session(str(config))

        state = mcp_gate.load_state(str(config))
        state["needs_review"] = True
        state["session_needs_local_check"] = True
        mcp_gate.save_state(str(config), state)

        mcp_gate.handle_post_tooluse(str(config), {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": {"type": "text", "text": json.dumps({"ok": True})},
            "cwd": str(repo),
        })
        state = mcp_gate.load_state(str(config))
        assert state["needs_review"] is False

    def test_dangerous_command_blocked_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        result = mcp_gate.handle_pre_tooluse(str(config), {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD"},
            "cwd": str(repo),
        })
        assert result["allow"] is False
        assert "dangerous" in result["reason"].lower()

    def test_release_command_blocked_in_external_repo(self, tmp_path, monkeypatch):
        repo, config = self._setup(tmp_path, monkeypatch)
        result = mcp_gate.handle_pre_tooluse(str(config), {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
            "cwd": str(repo),
        })
        assert result["allow"] is False
        assert "release" in result["reason"].lower()
