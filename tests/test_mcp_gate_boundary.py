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


# ---------------------------------------------------------------------------
# P7-B C3/C4 — state load/save diagnostic logging
# ---------------------------------------------------------------------------

def _read_log_events(config_dir: str) -> list[dict]:
    log_path = Path(config_dir) / "hook-events.jsonl"
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def test_load_state_returns_defaults_on_corrupt_json():
    """Corrupt state.json => load_state returns defaults (behavior unchanged)."""
    with tempfile.TemporaryDirectory() as config_dir:
        (Path(config_dir) / "state.json").write_text(
            "{not valid json", encoding="utf-8")
        state = gate.load_state(config_dir)
        assert state == dict(gate._STATE_DEFAULTS)


def test_load_state_logs_diagnostic_on_corrupt_json():
    """P7-B C3: corrupt state.json => state_load_failed event is logged."""
    with tempfile.TemporaryDirectory() as config_dir:
        (Path(config_dir) / "state.json").write_text(
            "{not valid json", encoding="utf-8")
        gate.load_state(config_dir)
        events = _read_log_events(config_dir)
        load_failed = [e for e in events if e.get("event") == "state_load_failed"]
        assert len(load_failed) == 1
        assert load_failed[0].get("error_type") in (
            "JSONDecodeError", "ValueError")


def test_load_state_no_event_on_missing_file():
    """No file => no diagnostic event (file simply doesn't exist yet)."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate.load_state(config_dir)
        events = _read_log_events(config_dir)
        assert [e for e in events if e.get("event") == "state_load_failed"] == []


def test_save_state_logs_diagnostic_on_write_failure():
    """P7-B C4: save_state failure => state_save_failed event is logged."""
    with tempfile.TemporaryDirectory() as config_dir:
        # Point state file to a directory path so write_text raises.
        broken_state_path = Path(config_dir) / "state.json"
        broken_state_path.mkdir()  # now writing to it as a file will fail
        # save_state must still not raise.
        gate.save_state(config_dir, {"foo": "bar"})
        events = _read_log_events(config_dir)
        save_failed = [e for e in events if e.get("event") == "state_save_failed"]
        assert len(save_failed) >= 1
        assert "error_type" in save_failed[0]


# ---------------------------------------------------------------------------
# Loop guard
# ---------------------------------------------------------------------------

def test_loop_guard_allows_under_threshold():
    """Same tool + same args under threshold should be allowed."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        for i in range(gate._LOOP_THRESHOLD_DEFAULT):
            result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
            assert result["allow"] is True, f"call {i} should be allowed"


def test_loop_guard_blocks_over_threshold():
    """Same tool + same args over threshold should be blocked."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        for i in range(gate._LOOP_THRESHOLD_DEFAULT):
            result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
            assert result["allow"] is True
        result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
        assert result["allow"] is False
        assert "loop guard" in result["reason"].lower()


def test_loop_guard_different_args_resets_counter():
    """Same tool + DIFFERENT args resets counter — not a loop."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        # Many calls with different commands — should not trigger.
        for i in range(gate._LOOP_THRESHOLD_DEFAULT + 5):
            cmd = f"echo {i}"  # each call has different input → different hash
            result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", cmd))
            assert result["allow"] is True, f"call {i} with varying input should be allowed"


def test_loop_guard_resets_on_user_prompt():
    """User prompt resets loop counters and hash window."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        for i in range(gate._LOOP_THRESHOLD_DEFAULT):
            result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
            assert result["allow"] is True
        gate._reset_loop_counters(config_dir)
        result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
        assert result["allow"] is True


def test_loop_guard_audit_event_written():
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        for i in range(gate._LOOP_THRESHOLD_DEFAULT + 1):
            gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
        events = _read_log_events(config_dir)
        loop_events = [e for e in events if e.get("event_type") == "loop_detected"]
        assert len(loop_events) >= 1
        assert loop_events[0].get("tool_name") == "SomeUnlistedTool"


def test_loop_guard_alternating_tools_never_blocks():
    """Alternating tools reset each other's counters — diverse work, not a loop."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        # Alternating tools should NEVER trigger loop guard, even far above threshold.
        for i in range(gate._LOOP_THRESHOLD_DEFAULT * 3):
            assert gate.handle_pre_tooluse(config_dir, _make_payload("Bash", "git status"))["allow"] is True
            assert gate.handle_pre_tooluse(config_dir, _make_payload("PowerShell", "Get-Date"))["allow"] is True


def test_loop_guard_same_tool_mixed_args_partial_count():
    """Same tool: identical calls increment, different calls reset to 1."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        # Interleave: 2 identical, 1 different, repeat.
        # Each different call resets counter to 1, so threshold is never reached.
        for i in range(50):
            gate.handle_pre_tooluse(config_dir, _make_payload("Bash", "git status"))
            gate.handle_pre_tooluse(config_dir, _make_payload("Bash", "git status"))
            gate.handle_pre_tooluse(config_dir, _make_payload("Bash", f"echo {i}"))
        # Counter should be at most 2 (most recent identical run), well under threshold.
        state = gate.load_state(config_dir)
        assert state["_loop_counters"].get("Bash", 0) <= 2


# ---------------------------------------------------------------------------
# Blocked MCP tools
# ---------------------------------------------------------------------------

def _read_audit_events(audit_dir: str) -> list[dict]:
    # mcp_audit_logger uses MCP_AUDIT_DIR as the audit base directly.
    log_path = Path(audit_dir) / "events.jsonl"
    if not log_path.exists():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def test_blocked_mcp_git_push():
    """mcp__git__git_push is blocked and emits an mcp_tool_blocked audit event."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        audit_dir = Path(config_dir) / "audit"
        audit_dir.mkdir()
        import os
        old_env = os.environ.get("MCP_AUDIT_DIR")
        os.environ["MCP_AUDIT_DIR"] = str(audit_dir)
        try:
            payload = {
                "tool_name": "mcp__git__git_push",
                "tool_input": {"path": "C:/nonexistent/repo", "remote": "origin", "branch": "main"},
                "cwd": "C:/nonexistent/repo",
            }
            result = gate.handle_pre_tooluse(config_dir, payload)
            assert result["allow"] is False
            assert "git push via MCP" in result["reason"]

            events = _read_audit_events(str(audit_dir))
            blocked = [e for e in events if e.get("event_type") == "mcp_tool_blocked"]
            assert len(blocked) == 1
            assert blocked[0].get("tool_name") == "mcp__git__git_push"
            assert blocked[0].get("result_status") == "blocked"
        finally:
            if old_env is None:
                os.environ.pop("MCP_AUDIT_DIR", None)
            else:
                os.environ["MCP_AUDIT_DIR"] = old_env


def test_loop_guard_escalates_after_timeout():
    """If blocking persists, a loop_escalated event is emitted."""
    with tempfile.TemporaryDirectory() as config_dir:
        gate._clear_session(config_dir)
        # Lower escalation threshold so the test doesn't have to sleep.
        original_threshold = gate._LOOP_ESCALATION_SECONDS
        gate._LOOP_ESCALATION_SECONDS = 0
        try:
            for i in range(gate._LOOP_THRESHOLD_DEFAULT + 2):
                result = gate.handle_pre_tooluse(config_dir, _make_payload("SomeUnlistedTool", "do thing"))
            assert result["allow"] is False
            events = _read_log_events(config_dir)
            escalated = [e for e in events if e.get("event_type") == "loop_escalated"]
            assert len(escalated) >= 1
            assert escalated[0].get("tool_name") == "SomeUnlistedTool"
            assert "ESCALATION" in result["reason"]
        finally:
            gate._LOOP_ESCALATION_SECONDS = original_threshold


def test_extract_read_info_known_shape_no_event():
    """Recognized list-of-text shape => no shape_unknown event."""
    with tempfile.TemporaryDirectory() as config_dir:
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x.py"},
            "tool_response": [{"type": "text", "text": "line1\nline2\n"}],
        }
        fp, nl = gate._extract_read_info(payload, config_dir)
        assert fp == "/tmp/x.py"
        assert nl == 2
        events = _read_log_events(config_dir)
        assert [e for e in events if e.get("event") == "mcp_shape_unknown"] == []


def test_extract_read_info_unknown_shape_logs_event_and_preserves_return():
    """P7-B M5: unknown shape => same return + mcp_shape_unknown event."""
    with tempfile.TemporaryDirectory() as config_dir:
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x.py"},
            # Non-empty but unrecognized: a dict with unrelated keys
            "tool_response": {"unrelated": "value", "weird": 42},
        }
        fp, nl = gate._extract_read_info(payload, config_dir)
        # Same as before: file_path comes from tool_input, num_lines unknown
        assert fp == "/tmp/x.py"
        assert nl is None
        events = _read_log_events(config_dir)
        unknown = [e for e in events if e.get("event") == "mcp_shape_unknown"]
        assert len(unknown) == 1
        assert unknown[0].get("reason") == "no_known_read_shape"
        assert unknown[0].get("tool_name") == "Read"


def test_extract_read_info_no_config_dir_does_not_log():
    """Without config_dir, helper stays purely passive (legacy callers)."""
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x.py"},
        "tool_response": {"unrelated": "value"},
    }
    fp, nl = gate._extract_read_info(payload)
    assert fp == "/tmp/x.py"
    assert nl is None


def test_review_tool_succeeded_text_not_json_logs_event():
    """P7-B M6: non-JSON text in response => same False + diagnostic."""
    with tempfile.TemporaryDirectory() as config_dir:
        payload = {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": [{"type": "text", "text": "not json at all"}],
        }
        assert gate.review_tool_succeeded(payload, config_dir) is False
        events = _read_log_events(config_dir)
        unknown = [e for e in events if e.get("event") == "mcp_shape_unknown"]
        assert len(unknown) == 1
        assert unknown[0].get("reason") == "text_not_json"


def test_review_tool_succeeded_result_not_dict_logs_event():
    """P7-B M6: JSON result is not a dict => same False + diagnostic."""
    with tempfile.TemporaryDirectory() as config_dir:
        payload = {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": [{"type": "text", "text": "[1, 2, 3]"}],
        }
        assert gate.review_tool_succeeded(payload, config_dir) is False
        events = _read_log_events(config_dir)
        unknown = [e for e in events if e.get("event") == "mcp_shape_unknown"]
        assert len(unknown) == 1
        assert unknown[0].get("reason") == "result_not_dict"


def test_review_tool_succeeded_known_success_no_event():
    """Recognized successful payload => no shape_unknown."""
    with tempfile.TemporaryDirectory() as config_dir:
        payload = {
            "tool_name": "mcp__local-llm__local_review_diff",
            "tool_response": [{"type": "text", "text": '{"ok": true}'}],
        }
        assert gate.review_tool_succeeded(payload, config_dir) is True
        events = _read_log_events(config_dir)
        assert [e for e in events if e.get("event") == "mcp_shape_unknown"] == []


def test_review_tool_succeeded_legacy_signature_still_works():
    """Calling without config_dir must continue to work (compat)."""
    payload = {
        "tool_name": "mcp__local-llm__local_review_diff",
        "tool_response": [{"type": "text", "text": '{"ok": true}'}],
    }
    assert gate.review_tool_succeeded(payload) is True
