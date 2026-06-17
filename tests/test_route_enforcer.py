"""Tests for tools/claude_hooks/route_enforcer.py — hook enforcement logic."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
CLAUDE_HOOKS_DIR = TOOLS_DIR / "claude_hooks"
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(CLAUDE_HOOKS_DIR))


def test_create_task_session():
    import route_enforcer as re
    session = re.create_task_session("test task")
    assert session["task_id"]
    assert session["phase"] == "planning"
    assert (Path(".local_llm_out/tasks") / session["task_id"] / "session.json").exists()


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
    r = on_user_prompt_submit({"prompt": "fix null pointer in login"})
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
        """flash_direct: Pro cannot Write directly — must use Agent(model='deepseek-v4-flash')."""
        import route_enforcer as re
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(re, "_tasks_dir", lambda: tmp_path)
        try:
            s = re.create_task_session("flash task")
            _write_route(tmp_path, s["task_id"], "flash_direct")
            r = re.on_pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": "test.py"}})
            # flash_direct FORCES model switch — Pro cannot Write directly
            assert r.get("permissionDecision") == "deny"
            assert "FORCES" in r.get("reason", "")
            assert "deepseek-v4-flash" in r.get("reason", "")
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
    r = subprocess.run(
        [sys.executable, str(ROUTE_ENFORCER)],
        input=payload_str,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if not r.stdout.strip():
        return {}
    return json.loads(r.stdout)


class TestRouteEnforcerSubprocess:
    """Verify route_enforcer.py works as a standalone hook script."""

    def test_user_prompt_submit_yields_plan_only(self):
        result = _run_hook({
            "hook_event_name": "UserPromptSubmit",
            "prompt": "fix null pointer in the login handler",
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
