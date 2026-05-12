"""Test MCP Hook Doctor diagnostic tool."""

import json
import sys
from pathlib import Path

import pytest

from tools.claude_hooks import mcp_doctor


@pytest.fixture
def healthy_dirs(tmp_path, monkeypatch):
    """Set up a minimal healthy environment."""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    # mcp_gate.py stub (minimal for import)
    gate_dir = repo / "tools" / "claude_hooks"
    gate_dir.mkdir(parents=True)
    gate_dir.joinpath("__init__.py").write_text("# package")
    gate_dir.joinpath("mcp_gate.py").write_text("""
_STATE_DEFAULTS = {
    "diff_reviewed": False, "dirty_since_review": False,
    "reviewed_at": None, "reviewed_by": None,
    "reviewed_repo": None, "reviewed_head": None,
    "reviewed_diff_hash": None, "mcp_calls": {},
    "session_id": None, "session_started_at": None,
}
def load_state(cd):
    return dict(_STATE_DEFAULTS, session_id="test-session", mcp_calls={})
def save_state(cd, s): pass
def run_git(args, cwd=None): return "fake-output"
def get_repo_fingerprint(cwd=None):
    return {"repo": "fake", "head": "abc", "diff_hash": "def"}
def get_diff_hash(cwd=None): return "abc123"
def handle_pre_tooluse(cd, p): return {"allow": True, "reason": ""}
def handle_post_tooluse(cd, p): pass
def handle_stop(cd, p): return []
def handle_session_start(cd, p): pass
def is_dangerous_command(p): return (False, "")
def is_release_command(p): return (False, "")
def review_tool_succeeded(p): return True
def main(cd): pass
""")

    # mcp server stub
    server_dir = repo / "tools"
    server_dir.joinpath("__init__.py").write_text("# package")
    server_dir.joinpath("local_llm_mcp_server.py").write_text("SERVER_NAME = 'test'")

    # .mcp.json
    repo.joinpath(".mcp.json").write_text(
        '{"mcpServers": {"local-llm": {"type": "stdio", "command": "python"}}}')

    # Hook wrapper
    claude_dir = tmp_path / "home" / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    hooks_dir.joinpath("mcp_gate.py").write_text(
        'from tools.claude_hooks.mcp_gate import main')

    # settings.json with all 4 hooks
    claude_dir.joinpath("settings.json").write_text(json.dumps({
        "hooks": {
            "SessionStart": [{"matcher": "", "command": "python wrapper.py"}],
            "PreToolUse": [{"matcher": "", "command": "python wrapper.py"}],
            "PostToolUse": [{"matcher": "", "command": "python wrapper.py"}],
            "Stop": [{"matcher": "", "command": "python wrapper.py"}],
        }
    }))

    # state.json
    config.joinpath("state.json").write_text(json.dumps({
        "session_id": "test-session",
        "mcp_calls": {},
    }))

    # hook-events.jsonl
    config.joinpath("hook-events.jsonl").write_text("")

    # Patch Path.home() to return our tmp home
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    # Ensure repo is on sys.path for import
    sys.path.insert(0, str(repo))

    return repo, config


class TestDoctorHealthy:
    def test_all_ok(self, healthy_dirs):
        repo, config = healthy_dirs
        results = mcp_doctor.run_checks(str(repo), str(config))
        statuses = {r["status"] for r in results}
        assert "FAIL" not in statuses, [r for r in results if r["status"] == "FAIL"]

    def test_json_output(self, healthy_dirs):
        repo, config = healthy_dirs
        results = mcp_doctor.run_checks(str(repo), str(config))
        json_str = json.dumps(results, indent=2, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) > 0
        for r in parsed:
            assert "check" in r
            assert "status" in r
            assert r["status"] in ("OK", "WARN", "FAIL")

    def test_has_all_check_categories(self, healthy_dirs):
        repo, config = healthy_dirs
        results = mcp_doctor.run_checks(str(repo), str(config))
        checks = {r["check"] for r in results}
        for expected in ("repo_root_exists", "mcp_gate_importable",
                         "wrapper_exists", "settings_json_valid",
                         "state_readable", "diff_hash_valid",
                         "log_readable", "session_id", "mcp_json",
                         "mcp_server_importable"):
            assert expected in checks, f"Missing check: {expected}"


class TestDoctorFailures:
    def test_missing_repo_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        results = mcp_doctor.run_checks(str(tmp_path / "noexist"), str(tmp_path / "cfg"))
        repo_check = [r for r in results if r["check"] == "repo_root_exists"]
        assert repo_check and repo_check[0]["status"] == "FAIL"

    def test_missing_module(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        repo = tmp_path / "repo"
        repo.mkdir()
        config = tmp_path / "cfg"
        config.mkdir()
        results = mcp_doctor.run_checks(str(repo), str(config))
        mod_check = [r for r in results if r["check"] == "mcp_gate_module_exists"]
        assert mod_check and mod_check[0]["status"] == "FAIL"

    def test_bad_state_json(self, healthy_dirs, monkeypatch):
        repo, config = healthy_dirs
        import tools.claude_hooks.mcp_gate as mg

        def _raise(*a, **kw):
            raise RuntimeError("corrupt")

        monkeypatch.setattr(mg, "load_state", _raise)
        results = mcp_doctor.run_checks(str(repo), str(config))
        state_check = [r for r in results if r["check"] == "state_readable"]
        assert state_check and state_check[0]["status"] == "FAIL"

    def test_missing_settings(self, healthy_dirs, monkeypatch):
        repo, config = healthy_dirs
        # Remove settings.json
        home = Path.home()
        (home / ".claude" / "settings.json").unlink()
        results = mcp_doctor.run_checks(str(repo), str(config))
        settings_check = [r for r in results if r["check"] == "settings_json_valid"]
        assert settings_check and settings_check[0]["status"] == "FAIL"

    def test_missing_wrapper(self, healthy_dirs, monkeypatch):
        repo, config = healthy_dirs
        # Remove wrapper
        home = Path.home()
        (home / ".claude" / "hooks" / "mcp_gate.py").unlink()
        results = mcp_doctor.run_checks(str(repo), str(config))
        wrapper_check = [r for r in results if r["check"] == "wrapper_exists"]
        assert wrapper_check and wrapper_check[0]["status"] == "FAIL"

    def test_missing_hook_events(self, healthy_dirs, monkeypatch):
        repo, config = healthy_dirs
        # Overwrite settings.json with empty hooks
        home = Path.home()
        (home / ".claude" / "settings.json").write_text('{"hooks": {}}')
        results = mcp_doctor.run_checks(str(repo), str(config))
        hook_checks = [r for r in results if r["check"].startswith("hook_")]
        assert all(c["status"] == "FAIL" for c in hook_checks), hook_checks

    def test_custom_paths(self, healthy_dirs):
        repo, config = healthy_dirs
        results = mcp_doctor.run_checks(str(repo), str(config))
        # All checks should run without error with custom paths
        statuses = {r["status"] for r in results}
        assert "FAIL" not in statuses

    def test_large_log_file_warns(self, healthy_dirs):
        """Phase 2F: log > 5 MB should produce a WARN."""
        repo, config = healthy_dirs
        log_file = config / "hook-events.jsonl"
        # Write 6 MB of data
        log_file.write_text("x" * (6 * 1024 * 1024))
        results = mcp_doctor.run_checks(str(repo), str(config))
        size_check = [r for r in results if r["check"] == "log_size"]
        assert size_check and size_check[0]["status"] == "WARN"

    def test_very_large_log_file_fails(self, healthy_dirs):
        """Phase 2F: log > 20 MB should produce a FAIL."""
        repo, config = healthy_dirs
        log_file = config / "hook-events.jsonl"
        # Write 21 MB of data
        log_file.write_text("x" * (21 * 1024 * 1024))
        results = mcp_doctor.run_checks(str(repo), str(config))
        size_check = [r for r in results if r["check"] == "log_size"]
        assert size_check and size_check[0]["status"] == "FAIL"
