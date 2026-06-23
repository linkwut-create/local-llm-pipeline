"""Tests for tools/claude_hooks/route_enforcer.py — hook enforcement logic."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
CLAUDE_HOOKS_DIR = TOOLS_DIR / "claude_hooks"
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(CLAUDE_HOOKS_DIR))


@pytest.fixture(autouse=True)
def isolated_tasks_dir(monkeypatch, tmp_path):
    """Redirect task I/O to a per-test temporary directory.

    Both in-process calls (via _tasks_dir reading LOCAL_LLM_TASKS_DIR) and
    subprocess hook invocations (via _run_hook forwarding the env var) use
    tmp_path, so tests never pollute the real .local_llm_out/tasks/ tree.
    """
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCAL_LLM_TASKS_DIR", str(tasks_dir))
    yield tasks_dir


def test_create_task_session():
    import route_enforcer as re
    session = re.create_task_session("test task")
    assert session["task_id"]
    assert session["phase"] == "planning"
    assert (re._tasks_dir() / session["task_id"] / "session.json").exists()


def test_get_active_task():
    import route_enforcer as re
    s1 = re.create_task_session("task alpha")
    time.sleep(0.1)
    s2 = re.create_task_session("task beta")
    active = re.get_active_task()
    assert active is not None
    assert active["user_task"] == "task beta"


def test_save_plan():
    import route_enforcer as re
    session = re.create_task_session("plan test")
    path = re.save_plan(session["task_id"], {"phases": [{"name": "test"}]})
    assert path.exists()
    active = re.get_active_task()
    assert active["plan_json_exists"] is True  # may be from this or another task


def test_load_route_missing():
    import route_enforcer as re
    assert re.load_route("nonexistent") is None


def test_save_artifact():
    import route_enforcer as re
    session = re.create_task_session("artifact")
    path = re.save_artifact(session["task_id"], "test.log", "output")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "output"


def test_should_trigger_committee():
    import route_enforcer as re
    s1 = re.create_task_session("no plan")
    assert re.should_trigger_committee(s1["task_id"]) is False
    s2 = re.create_task_session("has plan")
    re.save_plan(s2["task_id"], {"phases": []})
    assert re.should_trigger_committee(s2["task_id"]) is True


def test_enforce_no_route_denies_edit():
    import route_enforcer as re
    session = re.create_task_session("test")
    allowed, _ = re.check_tool_allowed("Edit", session["task_id"])
    assert allowed is False


def test_enforce_no_route_allows_read():
    import route_enforcer as re
    session = re.create_task_session("test")
    allowed, _ = re.check_tool_allowed("Read", session["task_id"])
    assert allowed is True


def test_enforce_blocked_denies_all():
    import route_enforcer as re
    session = re.create_task_session("blocked")
    p = Path(".local_llm_out/tasks") / session["task_id"] / "route.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"recommended_route": "blocked"}), encoding="utf-8")
    assert re.check_tool_allowed("Read", session["task_id"])[0] is False


def test_enforce_pro_allows_all():
    import route_enforcer as re
    session = re.create_task_session("pro")
    p = Path(".local_llm_out/tasks") / session["task_id"] / "route.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"recommended_route": "pro_decision"}), encoding="utf-8")
    assert re.check_tool_allowed("Edit", session["task_id"])[0] is True


def test_all_routes_have_perms():
    from route_enforcer import ROUTE_PERMISSIONS
    assert set(ROUTE_PERMISSIONS.keys()) == {"local_only", "flash_direct",
        "flash_subagent", "pro_decision", "blocked", "ask_user"}


def test_user_prompt_short_input():
    from route_enforcer import on_user_prompt_submit
    assert on_user_prompt_submit({"prompt": "hi"}) == {}


def test_user_prompt_creates_context():
    from route_enforcer import on_user_prompt_submit
    # Explicit new-task request creates a fresh task session.
    r = on_user_prompt_submit({"prompt": "new task: fix null pointer in login"})
    assert "PLAN-ONLY" in r.get("additionalContext", "")


def test_pre_tool_allows_plan_write():
    from route_enforcer import create_task_session, on_pre_tool_use
    s = create_task_session("plan write")
    r = on_pre_tool_use({"tool_name": "Write", "tool_input": {
        "file_path": f".local_llm_out/tasks/{s['task_id']}/plan.json"}})
    assert r == {}


def test_e2e_task_flow():
    from route_enforcer import (create_task_session, save_plan,
        should_trigger_committee, check_tool_allowed)
    s = create_task_session("search feature")
    assert not check_tool_allowed("Edit", s["task_id"])[0]
    save_plan(s["task_id"], {"phases": [{"name": "impl"}]})
    assert should_trigger_committee(s["task_id"])
    assert not check_tool_allowed("Edit", s["task_id"])[0]  # still no route


def test_stop_auto_generates_route_json(monkeypatch, tmp_path):
    import route_enforcer as re
    from route_enforcer import create_task_session, save_plan, on_stop

    # Use tmp_path for task output
    monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)

    s = create_task_session("auto route")
    save_plan(s["task_id"], {"phases": [{"name": "impl"}]})
    route_file = tmp_path / s["task_id"] / "route.json"

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        route_file.parent.mkdir(parents=True, exist_ok=True)
        route_file.write_text(json.dumps({"recommended_route": "flash_subagent"}), encoding="utf-8")
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    r = on_stop({})
    assert r.get("decision") == "allow"
    assert route_file.exists()


def test_stop_falls_back_when_committee_fails(monkeypatch, tmp_path):
    import route_enforcer as re
    from route_enforcer import create_task_session, save_plan, on_stop

    monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)

    s = create_task_session("failing route")
    save_plan(s["task_id"], {"phases": [{"name": "impl"}]})

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "models unavailable"
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    r = on_stop({})
    assert r.get("decision") == "block"
    assert "route.json" in r.get("reason", "")


def test_load_route_alias(tmp_path):
    import route_enforcer as re
    route_file = tmp_path / "route.json"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    route_file.write_text(json.dumps({"route": "pro_decision"}), encoding="utf-8")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
    try:
        loaded = re.load_route("")
        assert loaded is not None
        assert loaded.get("recommended_route") == "pro_decision"
    finally:
        monkeypatch.undo()


def test_ask_user_prompt_includes_authorization_command(tmp_path):
    import route_enforcer as re
    route_file = tmp_path / "route.json"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    route_file.write_text(json.dumps({"recommended_route": "ask_user"}), encoding="utf-8")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
    try:
        allowed, reason = re.check_tool_allowed("Edit", "")
        assert allowed is False
        assert "pending human approval" in reason
        assert "local_route_committee.py" in reason
        assert "--plan" in reason
        assert "--output" in reason
    finally:
        monkeypatch.undo()


def test_auth_command_format(tmp_path):
    import route_enforcer as re
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
    try:
        cmd = re._auth_command("20260617_test")
        assert "local_route_committee.py" in cmd
        assert "20260617_test" in cmd
        assert "plan.json" in cmd
        assert "route.json" in cmd
    finally:
        monkeypatch.undo()


# ═══════════════════════════════════════════════════════════════
# Flash cloud authorization tests
# ═══════════════════════════════════════════════════════════════


def _write_route(task_dir: Path, task_id: str, route_type: str):
    """Helper: write a route.json for a task."""
    route_file = task_dir / task_id / "route.json"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    route_file.write_text(json.dumps({"recommended_route": route_type}), encoding="utf-8")


class TestSecretsProtection:
    """Verify PreToolUse hard-denies secrets before route enforcement."""

    def test_env_read_denied_without_active_task(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Read",
                "tool_input": {"file_path": ".env"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_normal_read_allowed_without_active_task(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Read",
                "tool_input": {"file_path": "README.md"},
            })
            assert r == {}
        finally:
            monkeypatch.undo()

    def test_env_template_read_allowed(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Read",
                "tool_input": {"file_path": ".env.example"},
            })
            assert r == {}
        finally:
            monkeypatch.undo()

    def test_camel_case_file_path_denied(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Read",
                "tool_input": {"filePath": "C:\\Users\\Zero\\.ssh\\id_rsa"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_path_traversal_to_env_file_denied(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Read",
                "tool_input": {"file_path": "../config/.env.local"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_filename_containing_equals_not_mangled(self):
        import route_enforcer as re
        assert re._path_basename_for_policy("config.key=value") == "config.key=value"

    def test_flash_subagent_cannot_write_env_file(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("flash secrets task")
            _write_route(tmp_path, s["task_id"], "flash_subagent")
            re.set_flash_authorized(s["task_id"])
            r = re.on_pre_tool_use({
                "tool_name": "Write",
                "tool_input": {"file_path": ".env.local"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_multiedit_cannot_edit_env_file(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "MultiEdit",
                "tool_input": {"file_path": ".env"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_grep_cannot_target_env_file(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Grep",
                "tool_input": {"path": ".env", "pattern": "TOKEN"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_glob_cannot_search_private_key_files(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Glob",
                "tool_input": {"pattern": "**/*.pem"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "Secrets/.env protection" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_shell_command_referencing_private_key_denied(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Bash",
                "tool_input": {"command": "cat ~/.ssh/id_ed25519"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "sensitive path" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_shell_redirection_referencing_env_denied(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Bash",
                "tool_input": {"command": "cat<.env; echo done"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "sensitive path" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_shell_env_file_flag_denied(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Bash",
                "tool_input": {"command": "docker run --env-file=.env image"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "sensitive path" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_powershell_command_referencing_env_denied(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "PowerShell",
                "tool_input": {"command": "Get-Content .env"},
            })
            assert r.get("permissionDecision") == "deny"
            assert "sensitive path" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_shell_command_without_sensitive_path_allowed(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            r = re.on_pre_tool_use({
                "tool_name": "Bash",
                "tool_input": {"command": "pytest tests/test_route_enforcer.py -q"},
            })
            assert r == {}
        finally:
            monkeypatch.undo()


class TestFlashAuthorization:
    """Verify flash cloud authorization flow: ask → authorize → allow."""

    def test_flash_auth_flag_default_false(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("test flash")
            assert re.is_flash_authorized(s["task_id"]) is False
        finally:
            monkeypatch.undo()

    def test_set_flash_authorized(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("test flash")
            re.set_flash_authorized(s["task_id"])
            assert re.is_flash_authorized(s["task_id"]) is True
        finally:
            monkeypatch.undo()

    def test_flash_direct_denies_write_forces_flash_subagent(self, tmp_path):
        """flash_direct on Pro session: Write is denied with model switch prompt."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        monkeypatch.setattr(re, "_is_flash_session", lambda: False)
        try:
            s = re.create_task_session("flash task")
            _write_route(tmp_path, s["task_id"], "flash_direct")
            r = re.on_pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": "test.py"}})
            # flash_direct on Pro session: Write blocked with model switch prompt
            assert r.get("permissionDecision") == "deny"
            assert "FORCES" in r.get("reason", "")
            assert "deepseek-v4-flash" in r.get("reason", "")
        finally:
            monkeypatch.undo()

    def test_flash_direct_allows_write_on_flash_session(self, tmp_path):
        """flash_direct on Flash session: Write is allowed (already on Flash)."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        monkeypatch.setattr(re, "_is_flash_session", lambda: True)
        try:
            s = re.create_task_session("flash task")
            _write_route(tmp_path, s["task_id"], "flash_direct")
            r = re.on_pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": "test.py"}})
            # flash_direct on Flash session: allowed (empty response = pass through)
            assert r == {}
        finally:
            monkeypatch.undo()

    def test_flash_direct_allows_agent_spawn(self, tmp_path):
        """flash_direct: Agent tool is allowed so Pro can spawn Flash subagent."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("flash task")
            _write_route(tmp_path, s["task_id"], "flash_direct")
            re.set_flash_authorized(s["task_id"])
            r = re.on_pre_tool_use({"tool_name": "Agent", "tool_input": {"prompt": "fix bug"}})
            # Agent tool is allowed — Pro delegates to Flash subagent
            assert r == {}
        finally:
            monkeypatch.undo()

    def test_flash_subagent_allows_write(self, tmp_path):
        """flash_subagent: Write is in allowed list, enforcement is weaker than flash_direct."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("flash task")
            _write_route(tmp_path, s["task_id"], "flash_subagent")
            re.set_flash_authorized(s["task_id"])
            r = re.on_pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": "test.py"}})
            # flash_subagent allows Write directly (full access route)
            assert r == {}
        finally:
            monkeypatch.undo()

    def test_post_tool_sets_flash_authorized(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("flash task")
            _write_route(tmp_path, s["task_id"], "flash_subagent")
            assert re.is_flash_authorized(s["task_id"]) is False
            re.on_post_tool_use({"tool_name": "Write", "tool_input": {}, "tool_response": {"output": "ok"}})
            assert re.is_flash_authorized(s["task_id"]) is True
        finally:
            monkeypatch.undo()

    def test_post_tool_always_creates_tool_call_artifact(self, tmp_path):
        """Every tool call should produce a tool_call_N.json artifact."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("artifact test")
            re.on_post_tool_use({"tool_name": "Read", "tool_input": {"file_path": "test.py"}, "tool_response": {"output": "content"}})
            # Check artifact_index.json exists and has an entry
            index_file = tmp_path / s["task_id"] / "artifacts" / "artifact_index.json"
            assert index_file.exists()
            index = json.loads(index_file.read_text(encoding="utf-8"))
            assert len(index) == 1
            assert index[0]["type"] == "tool_call"
            assert index[0]["tool"] == "Read"
        finally:
            monkeypatch.undo()

    def test_post_tool_bash_classifies_output(self, tmp_path):
        """Bash commands should be classified: pytest→test_run, git diff→git_diff."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("bash test")
            re.on_post_tool_use({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "tool_response": {"output": "3 passed"}})
            index_file = tmp_path / s["task_id"] / "artifacts" / "artifact_index.json"
            index = json.loads(index_file.read_text(encoding="utf-8"))
            types = [e["type"] for e in index]
            assert "test_run" in types
            assert "tool_call" in types
        finally:
            monkeypatch.undo()

    def test_post_tool_edit_creates_edit_record(self, tmp_path):
        """Edit/Write tools should produce edit_record_N.json artifacts."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("edit test")
            re.on_post_tool_use({"tool_name": "Edit", "tool_input": {"file_path": "src/app.py", "new_string": "fixed"}, "tool_response": {}})
            index_file = tmp_path / s["task_id"] / "artifacts" / "artifact_index.json"
            index = json.loads(index_file.read_text(encoding="utf-8"))
            types = [e["type"] for e in index]
            assert "file_edit" in types
            assert "tool_call" in types
        finally:
            monkeypatch.undo()


class TestArtifactHelpers:
    """Unit tests for artifact helper functions."""

    def test_classify_pytest(self):
        from route_enforcer import _classify_bash_artifact
        assert _classify_bash_artifact("pytest -q tests/") == "test_run"
        assert _classify_bash_artifact("python -m unittest") == "test_run"

    def test_classify_git(self):
        from route_enforcer import _classify_bash_artifact
        assert _classify_bash_artifact("git diff HEAD~1") == "git_diff"
        assert _classify_bash_artifact("git log --oneline") == "git_log"
        assert _classify_bash_artifact("git status") == "git_status"

    def test_classify_generic(self):
        from route_enforcer import _classify_bash_artifact
        assert _classify_bash_artifact("npm run build") == "bash_output"
        assert _classify_bash_artifact("ls -la") == "bash_output"

    def test_truncate_output(self):
        from route_enforcer import _truncate_output
        short = "hello"
        assert _truncate_output(short, max_chars=10) == "hello"
        long = "x" * 20000
        result = _truncate_output(long, max_chars=100)
        assert len(result) < 200
        assert "truncated" in result

    def test_summarize_input_bash(self):
        from route_enforcer import _summarize_input
        s = _summarize_input("Bash", {"command": "pytest -q tests/"})
        assert s["command"] == "pytest -q tests/"

    def test_summarize_input_edit(self):
        from route_enforcer import _summarize_input
        s = _summarize_input("Edit", {"file_path": "src/main.py", "new_string": "fixed bug"})
        assert s["file_path"] == "src/main.py"
        assert s["content_len"] == 9

    def test_summarize_input_agent(self):
        from route_enforcer import _summarize_input
        s = _summarize_input("Agent", {"prompt": "fix the bug", "subagent_type": "code-worker"})
        assert s["prompt_len"] == 11
        assert s["subagent_type"] == "code-worker"

    def test_summarize_output(self):
        from route_enforcer import _summarize_output
        s = _summarize_output({"output": "success"})
        assert s["size_chars"] == 7
        assert s["ok"] is True

    def test_artifact_index_multiple_entries(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("multi artifact")
            re.save_artifact_indexed(s["task_id"], "a.txt", "A", artifact_type="test_run", tool_name="Bash")
            re.save_artifact_indexed(s["task_id"], "b.txt", "B", artifact_type="git_diff", tool_name="Bash")
            index_file = tmp_path / s["task_id"] / "artifacts" / "artifact_index.json"
            index = json.loads(index_file.read_text(encoding="utf-8"))
            assert len(index) == 2
            assert index[0]["name"] == "a.txt"
            assert index[1]["name"] == "b.txt"
        finally:
            monkeypatch.undo()

    def test_non_flash_route_does_not_ask(self, tmp_path):
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("local task")
            _write_route(tmp_path, s["task_id"], "local_only")
            r = re.on_pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": "test.py"}})
            # local_only denies Write, but NOT via ask — via deny
            assert r.get("permissionDecision") == "deny"
        finally:
            monkeypatch.undo()

    def test_flash_auth_only_for_flash_routes(self, tmp_path):
        """pro_decision is cloud_ok but not flash_ — should not trigger auth popup."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("pro task")
            _write_route(tmp_path, s["task_id"], "pro_decision")
            r = re.on_pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": "test.py"}})
            # pro_decision may deny or allow but should NOT ask for flash auth
            assert r.get("permissionDecision") != "ask" or "Flash" not in r.get("reason", "")
        finally:
            monkeypatch.undo()


# ═══════════════════════════════════════════════════════════════
# Subprocess-level tests — verify the script runs as a real
# Claude Code hook (stdin JSON → stdout JSON).
# ═══════════════════════════════════════════════════════════════

ROUTE_ENFORCER = Path(__file__).resolve().parent.parent / "tools" / "claude_hooks" / "route_enforcer.py"


def _run_hook(payload):
    """Pipe *payload* as JSON to the route_enforcer subprocess, return
    the parsed stdout JSON object."""
    if isinstance(payload, dict):
        payload_str = json.dumps(payload)
    else:
        payload_str = str(payload)
    env = os.environ.copy()
    if "LOCAL_LLM_TASKS_DIR" in os.environ:
        env["LOCAL_LLM_TASKS_DIR"] = os.environ["LOCAL_LLM_TASKS_DIR"]
    r = subprocess.run(
        [sys.executable, str(ROUTE_ENFORCER)],
        input=payload_str,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    if not r.stdout.strip():
        return {}
    return json.loads(r.stdout)


class TestRouteEnforcerSubprocess:
    """Verify route_enforcer.py works as a standalone hook script."""

    def test_user_prompt_submit_yields_plan_only(self):
        result = _run_hook({
            "hook_event_name": "UserPromptSubmit",
            "prompt": "new task: fix null pointer in the login handler",
        })
        assert "PLAN-ONLY" in result.get("additionalContext", "")

    def test_pre_tool_use_edit_no_route_denies(self):
        result = _run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/main.py"},
        })
        assert result.get("permissionDecision") == "deny"
        assert "route.json" in result.get("reason", "")

    def test_pre_tool_use_read_no_route_allows(self):
        result = _run_hook({
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        })
        # No active task → allows; with active task + no route → still allows Read
        assert result.get("permissionDecision") != "deny"

    def test_unknown_event_returns_empty(self):
        result = _run_hook({
            "hook_event_name": "SomeFutureEvent",
            "data": "irrelevant",
        })
        assert result == {}

    def test_empty_stdin_returns_empty(self):
        r = subprocess.run(
            [sys.executable, str(ROUTE_ENFORCER)],
            input="",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout) if r.stdout.strip() else {}
        assert result == {}

    def test_invalid_json_returns_empty_no_crash(self):
        r = subprocess.run(
            [sys.executable, str(ROUTE_ENFORCER)],
            input="this is not json {{{",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout) if r.stdout.strip() else {}
        assert result == {}

    def test_non_dict_json_returns_empty(self):
        result = _run_hook("just a string")
        assert result == {}

    def test_post_tool_use_returns_empty(self):
        result = _run_hook({
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q"},
            "tool_response": {"output": "3 passed"},
        })
        # PostToolUse never blocks — always returns {}
        assert result == {}

    def test_missing_hook_event_name_returns_empty(self):
        result = _run_hook({
            "prompt": "some task without an event name",
        })
        assert result == {}


# ═══════════════════════════════════════════════════════════════
# Phase 1 — Task lifecycle hardening
# ═══════════════════════════════════════════════════════════════

class TestTaskLifecycle:
    """Verify task session reuse, isolation, and status rules."""

    def test_first_substantive_prompt_creates_task(self):
        import route_enforcer as re
        r = re.on_user_prompt_submit({
            "prompt": "implement user authentication",
            "claude_session_id": "session-A",
        })
        assert "PLAN-ONLY" in r.get("additionalContext", "")
        assert "TASK SESSION:" in r.get("additionalContext", "")

    def test_continuation_prompt_appends_to_active_task(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement user authentication",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]

        second = re.on_user_prompt_submit({
            "prompt": "continue with the implementation and add tests",
            "claude_session_id": "session-A",
        })
        assert second.get("additionalContext", "").startswith(f"[TASK SESSION: {task_id}]")
        assert "Continuing active task" in second.get("additionalContext", "")

        session = re._load_session(task_id)
        assert len(session["messages"]) == 2
        assert session["messages"][0]["role"] == "user"
        assert "authentication" in session["messages"][0]["content"]
        assert session["messages"][1]["role"] == "user"
        assert "tests" in session["messages"][1]["content"]

    def test_new_task_keyword_creates_separate_task(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "fix the login bug",
            "claude_session_id": "session-A",
        })
        first_id = re.get_active_task(claude_session_id="session-A")["task_id"]

        second = re.on_user_prompt_submit({
            "prompt": "new task: refactor the database layer",
            "claude_session_id": "session-A",
        })
        second_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        assert first_id != second_id
        assert "PLAN-ONLY" in second.get("additionalContext", "")

    def test_completed_task_is_excluded_from_active(self):
        import route_enforcer as re
        s1 = re.create_task_session("completed task", claude_session_id="session-A")
        re.complete_task(s1["task_id"])

        s2 = re.create_task_session("active task", claude_session_id="session-A")
        active = re.get_active_task(claude_session_id="session-A")
        assert active is not None
        assert active["task_id"] == s2["task_id"]

    def test_cancelled_task_is_excluded_from_active(self):
        import route_enforcer as re
        s1 = re.create_task_session("cancelled task", claude_session_id="session-A")
        re.cancel_task(s1["task_id"])

        s2 = re.create_task_session("active task", claude_session_id="session-A")
        active = re.get_active_task(claude_session_id="session-A")
        assert active["task_id"] == s2["task_id"]

    def test_project_root_isolation(self):
        import route_enforcer as re
        s1 = re.create_task_session(
            "project one task",
            claude_session_id="session-A",
            project_root="/tmp/project-one",
        )
        s2 = re.create_task_session(
            "project two task",
            claude_session_id="session-A",
            project_root="/tmp/project-two",
        )
        active = re.get_active_task(
            claude_session_id="session-A",
            project_root="/tmp/project-one",
        )
        assert active["task_id"] == s1["task_id"]

    def test_claude_session_isolation(self):
        import route_enforcer as re
        s1 = re.create_task_session(
            "session alpha task",
            claude_session_id="session-alpha",
        )
        re.create_task_session(
            "session beta task",
            claude_session_id="session-beta",
        )
        active = re.get_active_task(claude_session_id="session-alpha")
        assert active["task_id"] == s1["task_id"]

    def test_test_tasks_do_not_pollute_active_selection(self):
        import route_enforcer as re
        re.create_task_session(
            "test task",
            claude_session_id="session-A",
            is_test_task=True,
        )
        active = re.get_active_task(claude_session_id="session-A")
        assert active is None


class TestUserPromptControlStatements:
    """Verify control statement detection and task actions."""

    def test_continue_keyword_appends_message(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement login",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        r = re.on_user_prompt_submit({
            "prompt": "继续",
            "claude_session_id": "session-A",
        })
        assert f"[TASK SESSION: {task_id}]" in r.get("additionalContext", "")
        assert "Continuing active task" in r.get("additionalContext", "")

    def test_chinese_new_task_creates_session(self):
        import route_enforcer as re
        r = re.on_user_prompt_submit({
            "prompt": "新建任务：实现 OAuth2 登录",
            "claude_session_id": "session-A",
        })
        assert "PLAN-ONLY" in r.get("additionalContext", "")

    def test_cancel_stops_active_task(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement login",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        r = re.on_user_prompt_submit({
            "prompt": "取消任务",
            "claude_session_id": "session-A",
        })
        assert "cancelled" in r.get("additionalContext", "").lower()
        assert re.get_active_task(claude_session_id="session-A") is None
        session = re._load_session(task_id)
        assert session["status"] == "cancelled"

    def test_stop_stops_active_task(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement login",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        r = re.on_user_prompt_submit({
            "prompt": "stop",
            "claude_session_id": "session-A",
        })
        assert "cancelled" in r.get("additionalContext", "").lower()
        session = re._load_session(task_id)
        assert session["status"] == "cancelled"

    def test_accept_records_approval(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement login",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        r = re.on_user_prompt_submit({
            "prompt": "接受",
            "claude_session_id": "session-A",
        })
        assert "Approval recorded" in r.get("additionalContext", "")
        session = re._load_session(task_id)
        assert session["status"] == "active"

    def test_run_tests_control_statement_appends(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement login",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        r = re.on_user_prompt_submit({
            "prompt": "运行测试",
            "claude_session_id": "session-A",
        })
        assert f"[TASK SESSION: {task_id}]" in r.get("additionalContext", "")
        assert "Continuing active task" in r.get("additionalContext", "")

    def test_retry_control_statement_appends(self):
        import route_enforcer as re
        re.on_user_prompt_submit({
            "prompt": "implement login",
            "claude_session_id": "session-A",
        })
        task_id = re.get_active_task(claude_session_id="session-A")["task_id"]
        r = re.on_user_prompt_submit({
            "prompt": "retry",
            "claude_session_id": "session-A",
        })
        assert f"[TASK SESSION: {task_id}]" in r.get("additionalContext", "")
        assert "Continuing active task" in r.get("additionalContext", "")

    def test_short_prompt_ignored(self):
        import route_enforcer as re
        r = re.on_user_prompt_submit({
            "prompt": "hi",
            "claude_session_id": "session-A",
        })
        assert r == {}

    def test_no_active_task_and_short_prompt_returns_empty(self):
        import route_enforcer as re
        r = re.on_user_prompt_submit({
            "prompt": "ok",
            "claude_session_id": "session-A",
        })
        assert r == {}
