"""Test MCP gate boundary hardening (MCP-GATE-1B).

Tests: git commit detection, bypass risk detection, per-repo state isolation,
audit event wiring.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "claude_hooks"))

import mcp_gate as gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(tool_name="Bash", command="", cwd=""):
    return {
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "cwd": cwd,
    }


def _make_temp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing. Returns repo root."""
    import subprocess
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
    (repo / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# Direct git commit detection
# ---------------------------------------------------------------------------

def test_detects_direct_git_commit_bash():
    p = _make_payload("Bash", "git commit -m 'test'")
    assert gate.is_git_commit(p) is True


def test_detects_git_c_commit():
    p = _make_payload("Bash", "git -C /tmp/repo commit -m 'test'")
    assert gate.is_git_commit(p) is True


def test_detects_chained_git_commit():
    p = _make_payload("Bash", "echo 'before' && git commit -m 'test' && echo 'after'")
    assert gate.is_git_commit(p) is True


def test_does_not_detect_git_status():
    p = _make_payload("Bash", "git status")
    assert gate.is_git_commit(p) is False


def test_does_not_detect_git_log():
    p = _make_payload("Bash", "git log --oneline")
    assert gate.is_git_commit(p) is False


def test_does_not_detect_git_diff():
    p = _make_payload("Bash", "git diff")
    assert gate.is_git_commit(p) is False


def test_does_not_detect_git_commit_tree():
    p = _make_payload("Bash", "git commit-tree abc123")
    assert gate.is_git_commit(p) is False


def test_detects_powershell_git_commit():
    p = _make_payload("PowerShell", "git commit -m 'test'")
    assert gate.is_git_commit(p) is True


def test_does_not_detect_non_bash_powershell():
    p = _make_payload("Write", "git commit -m 'test'")
    assert gate.is_git_commit(p) is False


# ---------------------------------------------------------------------------
# Subprocess bypass risk detection
# ---------------------------------------------------------------------------

def test_detects_python_subprocess_git_commit_list():
    p = _make_payload("Bash",
        "python -c \"import subprocess; subprocess.run(['git', 'commit', '-m', 'msg'])\"")
    is_risk, desc, lang = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True
    assert lang == "python"


def test_detects_python_subprocess_git_commit_string():
    p = _make_payload("Bash",
        'python -c "import subprocess; subprocess.run(\'git commit -m msg\', shell=True)"')
    is_risk, desc, lang = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True
    assert lang == "python"


def test_detects_python_os_system_git_commit():
    p = _make_payload("Bash",
        'python3.14 -c "import os; os.system(\'git commit -m msg\')"')
    is_risk, desc, lang = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True
    assert lang == "python"


def test_detects_python_popen_git():
    p = _make_payload("Bash",
        'python -c "import subprocess; p = subprocess.Popen([\'git\', \'commit\', \'-m\', \'msg\'])"')
    is_risk, _, _ = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True


def test_detects_node_child_process_git_commit_list():
    p = _make_payload("Bash",
        "node -e \"const {execSync} = require('child_process'); execSync('git commit -m msg')\"")
    is_risk, desc, lang = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True
    assert lang == "node"


def test_detects_ruby_system_git_commit():
    p = _make_payload("Bash",
        "ruby -e \"system('git', 'commit', '-m', 'msg')\"")
    is_risk, desc, lang = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True
    assert lang == "ruby"


def test_detects_ruby_backtick_git_commit():
    p = _make_payload("Bash",
        "ruby -e \"`git commit -m msg`\"")
    is_risk, _, _ = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True


def test_detects_perl_system_git_commit():
    p = _make_payload("Bash",
        "perl -e \"system('git commit -m msg')\"")
    is_risk, desc, lang = gate.is_git_commit_bypass_risk(p)
    assert is_risk is True
    assert lang == "perl"


def test_does_not_detect_python_test():
    """Normal Python test should NOT trigger bypass risk."""
    p = _make_payload("Bash", "python -m pytest tests/ -q")
    is_risk, _, _ = gate.is_git_commit_bypass_risk(p)
    assert is_risk is False


def test_does_not_detect_python_subprocess_without_git_commit():
    """subprocess.run without git commit should NOT trigger."""
    p = _make_payload("Bash",
        "python -c \"import subprocess; subprocess.run(['echo', 'hello'])\"")
    is_risk, _, _ = gate.is_git_commit_bypass_risk(p)
    assert is_risk is False


def test_bypass_risk_only_on_bash_powershell():
    """Bypass risk only applies to Bash/PowerShell tools."""
    p = _make_payload("Write",
        "python -c \"import subprocess; subprocess.run(['git', 'commit'])\"")
    is_risk, _, _ = gate.is_git_commit_bypass_risk(p)
    assert is_risk is False


# ---------------------------------------------------------------------------
# Per-repo state isolation
# ---------------------------------------------------------------------------

def test_repo_state_key_is_stable():
    key1 = gate._repo_state_key("/home/user/project-a")
    key2 = gate._repo_state_key("/home/user/project-a")
    assert key1 == key2
    key3 = gate._repo_state_key("/home/user/project-b")
    assert key1 != key3


def test_repo_state_is_per_repo():
    """Per-repo state isolation: swapping repos preserves each repo's state."""
    state = {}

    # Set up state for project A
    gate._ensure_repo_state(state, "C:/repos/project-a")
    state["diff_reviewed"] = True
    state["dirty_since_review"] = False
    state["reviewed_repo"] = "C:/repos/project-a"
    state["reviewed_head"] = "aaa"
    state["reviewed_diff_hash"] = "hash_a"

    # Switch to project B — this should save A's state and restore B's
    gate._ensure_repo_state(state, "C:/repos/project-b")
    # B should start with defaults (first access)
    assert state["diff_reviewed"] is False
    assert state["reviewed_repo"] is None

    # Set B's state
    state["diff_reviewed"] = True
    state["reviewed_repo"] = "C:/repos/project-b"
    state["reviewed_head"] = "bbb"
    state["reviewed_diff_hash"] = "hash_b"

    # Switch back to A
    gate._ensure_repo_state(state, "C:/repos/project-a")
    assert state["diff_reviewed"] is True
    assert state["reviewed_repo"] == "C:/repos/project-a"
    assert state["reviewed_head"] == "aaa"

    # Switch back to B
    gate._ensure_repo_state(state, "C:/repos/project-b")
    assert state["diff_reviewed"] is True
    assert state["reviewed_repo"] == "C:/repos/project-b"
    assert state["reviewed_head"] == "bbb"


def test_repo_state_first_access_preserves_current():
    """First access to a repo should preserve current flat state."""
    state = {}
    # Manually set state (simulating a test or manual setup)
    state["diff_reviewed"] = True
    state["reviewed_repo"] = "/my/repo"
    state["reviewed_head"] = "abc123"
    state["reviewed_diff_hash"] = "hash_xyz"

    # First access should NOT clear existing state
    gate._ensure_repo_state(state, "/my/repo")
    assert state["diff_reviewed"] is True
    assert state["reviewed_repo"] == "/my/repo"
    assert state["reviewed_head"] == "abc123"


# ---------------------------------------------------------------------------
# PreToolUse block scenarios
# ---------------------------------------------------------------------------

def test_handle_pre_tooluse_allows_non_commit():
    result = gate.handle_pre_tooluse("/tmp/config", _make_payload("Bash", "echo hello"))
    assert result["allow"] is True


def test_handle_pre_tooluse_blocks_commit_without_review():
    with tempfile.TemporaryDirectory() as config_dir:
        result = gate.handle_pre_tooluse(config_dir, _make_payload("Bash", "git commit -m 'test'"))
        assert result["allow"] is False
        assert "BLOCKED" in result["reason"]


def test_handle_pre_tooluse_blocks_subprocess_bypass():
    with tempfile.TemporaryDirectory() as config_dir:
        result = gate.handle_pre_tooluse(
            config_dir,
            _make_payload("Bash",
                "python -c \"import subprocess; subprocess.run(['git', 'commit', '-m', 'msg'])\"")
        )
        assert result["allow"] is False
        assert "subprocess" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Audit wiring (best-effort, tests that events are attempted)
# ---------------------------------------------------------------------------

def test_try_audit_event_does_not_crash():
    """_try_audit_event should never raise, even with no audit logger available."""
    gate._try_audit_event({"event_type": "test_event"})


def test_try_audit_failure_does_not_crash():
    """_try_audit_failure should never raise."""
    gate._try_audit_failure({"failure_type": "test_failure"})


def test_audit_event_wired_on_commit_block():
    """Verify that commit_gate_blocked triggers an audit event attempt (no crash)."""
    with tempfile.TemporaryDirectory() as config_dir:
        result = gate.handle_pre_tooluse(config_dir, _make_payload("Bash", "git commit -m 'test'"))
        assert result["allow"] is False
        # Audit wiring is best-effort; just verify no exception was raised


def test_audit_event_wired_on_bypass_risk():
    """Verify that bypass risk triggers an audit event attempt (no crash)."""
    with tempfile.TemporaryDirectory() as config_dir:
        result = gate.handle_pre_tooluse(
            config_dir,
            _make_payload("Bash",
                "python -c \"import subprocess; subprocess.run(['git', 'commit', '-m', 'msg'])\"")
        )
        assert result["allow"] is False
        assert "python" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Windows paths
# ---------------------------------------------------------------------------

def test_windows_paths_supported():
    """is_git_commit should work with Windows paths."""
    p = _make_payload("Bash", "git -C C:\\Users\\Zero\\project commit -m 'test'")
    assert gate.is_git_commit(p) is True


def test_extract_git_c_path_windows():
    """extract_git_c_path should handle Windows paths."""
    path = gate.extract_git_c_path("git -C C:\\Users\\Zero\\repo commit -m test")
    assert path == "C:\\Users\\Zero\\repo"
