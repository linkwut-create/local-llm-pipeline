"""Route Enforcer — enforce route.json in Claude Code hooks.

UserPromptSubmit → create task session, require plan-only
PreToolUse      → deny tools not allowed by route.json
PostToolUse     → save artifacts (test results, diffs, logs)
Stop            → trigger local route committee if plan exists

Design: Minimal, deterministic, never blocks the session itself.
         "Deny" means return a blocking response; "allow" means pass through.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Route permissions (same as local_route_committee.ROUTE_PERMISSIONS)
# ═══════════════════════════════════════════════════════════════

ROUTE_PERMISSIONS = {
    "local_only": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "Task", "Skill"},
        "denied": {"Edit", "Write", "NotebookEdit"},
        "cloud_ok": False,
        "max_files": 10,
    },
    "flash_direct": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "Write", "Task", "Skill"},
        "denied": {"Edit", "NotebookEdit"},
        "cloud_ok": True,
        "max_files": 20,
    },
    "flash_subagent": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "Write", "Edit", "Task", "Skill"},
        "denied": set(),
        "cloud_ok": True,
        "max_files": 50,
    },
    "pro_decision": {
        "allowed": set(),
        "denied": set(),
        "cloud_ok": True,
        "max_files": None,
    },
    "blocked": {
        "allowed": set(),
        "denied": {"Read", "Grep", "Glob", "Bash", "Write", "Edit",
                    "NotebookEdit", "Task", "Skill"},
        "cloud_ok": False,
        "max_files": 0,
    },
    "ask_user": {
        "allowed": {"Read", "Grep", "Glob"},
        "denied": {"Bash", "Write", "Edit", "NotebookEdit", "Task", "Skill"},
        "cloud_ok": False,
        "max_files": 3,
    },
}


# ═══════════════════════════════════════════════════════════════
# Task session management
# ═══════════════════════════════════════════════════════════════

def _tasks_dir() -> Path:
    return Path(".local_llm_out/tasks")


def create_task_session(user_task: str) -> dict:
    """Create a new task session. Returns {task_id, session_path, ...}."""
    task_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    session_dir = _tasks_dir() / task_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "artifacts").mkdir(exist_ok=True)

    session = {
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_task": user_task[:2000],
        "phase": "planning",  # planning → routing → executing → complete
        "plan_json_exists": False,
        "route_json_exists": False,
        "artifacts": [],
    }
    (session_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (session_dir / "user_task.md").write_text(
        f"# Task\n\n{user_task}\n\nCreated: {session['created_at']}",
        encoding="utf-8",
    )
    return session


def get_active_task() -> dict | None:
    """Find the most recent active task session by created_at."""
    tasks_dir = _tasks_dir()
    if not tasks_dir.exists():
        return None
    sessions = []
    for sd in tasks_dir.iterdir():
        session_file = sd / "session.json"
        if session_file.exists():
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and "user_task" in data
                    and "task_id" in data
                    and "created_at" in data
                ):
                    sessions.append(data)
            except Exception:
                continue
    if not sessions:
        return None
    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return sessions[0]


def load_route(task_id: str) -> dict | None:
    """Load route.json for a task.

    Accepts both `recommended_route` and the shorthand `route` field.
    """
    route_file = _tasks_dir() / task_id / "route.json"
    if route_file.exists():
        try:
            data = json.loads(route_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Allow the shorthand `route` field used in manual files
                if "route" in data and "recommended_route" not in data:
                    data["recommended_route"] = data["route"]
                return data
        except Exception:
            pass
    return None


def save_plan(task_id: str, plan: dict) -> Path:
    """Save plan.json artifact."""
    plan_file = _tasks_dir() / task_id / "plan.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_session(task_id, {"plan_json_exists": True, "phase": "routing"})
    return plan_file


def save_artifact(task_id: str, name: str, content: str) -> Path:
    """Save an artifact file."""
    art_file = _tasks_dir() / task_id / "artifacts" / name
    art_file.write_text(content, encoding="utf-8")
    _update_session(task_id, {
        "artifacts": _get_artifacts(task_id) + [name],
    })
    return art_file


def _get_artifacts(task_id: str) -> list:
    session_file = _tasks_dir() / task_id / "session.json"
    if session_file.exists():
        s = json.loads(session_file.read_text(encoding="utf-8"))
        return s.get("artifacts", [])
    return []


def _update_session(task_id: str, updates: dict):
    session_file = _tasks_dir() / task_id / "session.json"
    if session_file.exists():
        s = json.loads(session_file.read_text(encoding="utf-8"))
        s.update(updates)
        session_file.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# Route enforcement
# ═══════════════════════════════════════════════════════════════

def _auth_command(task_id: str) -> str:
    """Return the exact command a user can run to re-run the route committee."""
    plan = _tasks_dir() / task_id / "plan.json"
    route = _tasks_dir() / task_id / "route.json"
    return (
        f"py -3 tools/local_route_committee.py --plan {plan} --json --output {route}"
    )


def check_tool_allowed(tool_name: str, task_id: str) -> tuple[bool, str]:
    """Check if a tool is allowed by the current route.

    Returns (allowed, reason).
    """
    route = load_route(task_id)
    if route is None:
        # No route yet — limited to read-only exploration
        if tool_name in ("Edit", "Write", "NotebookEdit"):
            return False, (
                "No route.json exists yet. Plan must be created before editing. "
                "Use Read/Grep/Glob to understand the codebase first."
            )
        return True, ""

    route_type = route.get("recommended_route", "ask_user")
    perms = ROUTE_PERMISSIONS.get(route_type, ROUTE_PERMISSIONS["ask_user"])

    if route_type == "ask_user":
        # Provide an actionable next step instead of a generic denial
        if tool_name in ("Edit", "Write", "NotebookEdit"):
            return False, (
                f"This task is pending human approval (route: ask_user). "
                f"Tool '{tool_name}' is blocked until the route committee authorizes execution.\n\n"
                f"To authorize, run:\n  {_auth_command(task_id)}\n\n"
                f"Then reply with a clear approval message such as 'approved' or 'continue'."
            )
        return False, (
            f"This task is pending human approval (route: ask_user). "
            f"Tool '{tool_name}' is not allowed.\n\n"
            f"To authorize execution, run:\n  {_auth_command(task_id)}\n\n"
            f"Then reply with a clear approval message such as 'approved' or 'continue'."
        )

    if perms["allowed"] and tool_name not in perms["allowed"]:
        return False, (
            f"Tool '{tool_name}' not allowed for route '{route_type}'. "
            f"Allowed: {perms['allowed']}"
        )
    if tool_name in perms["denied"]:
        return False, (
            f"Tool '{tool_name}' denied for route '{route_type}'."
        )
    return True, ""


def should_trigger_committee(task_id: str) -> bool:
    """Check if conditions are met to trigger the route committee."""
    session_file = _tasks_dir() / task_id / "session.json"
    if not session_file.exists():
        return False
    s = json.loads(session_file.read_text(encoding="utf-8"))
    if s.get("route_json_exists"):
        return False  # already routed
    if s.get("plan_json_exists"):
        return True   # plan exists, need route
    return False


# ═══════════════════════════════════════════════════════════════
# Hook response builders
# ═══════════════════════════════════════════════════════════════

def on_user_prompt_submit(payload: dict) -> dict:
    """UserPromptSubmit hook: create task session, inject plan-only context."""
    prompt_text = payload.get("prompt", "") or payload.get("text", "") or ""
    if not prompt_text or len(prompt_text) < 20:
        return {}  # too short, don't intercept

    session = create_task_session(prompt_text)

    return {
        "additionalContext": (
            f"[TASK SESSION: {session['task_id']}]\n"
            f"You are in PLAN-ONLY mode. Before any code changes, output:\n"
            f"1. A plan.json describing what you will do (phases, files, approach)\n"
            f"2. Save it with: Write .local_llm_out/tasks/{session['task_id']}/plan.json\n"
            f"After plan.json exists, the route committee will decide execution model.\n"
            f"Do NOT edit/write source files until route is approved."
        ),
    }


def on_pre_tool_use(payload: dict) -> dict:
    """PreToolUse hook: enforce route.json tool permissions."""
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})

    task = get_active_task()
    if task is None:
        return {}  # no active task, allow

    task_id = task["task_id"]

    # Check: is this a Write to plan.json?
    file_path = tool_input.get("file_path", "") or ""
    if "plan.json" in file_path and str(task_id) in file_path:
        return {}  # always allow plan.json writes

    allowed, reason = check_tool_allowed(tool_name, task_id)
    if not allowed:
        return {
            "permissionDecision": "deny",
            "reason": reason,
        }

    return {}  # allow


def on_post_tool_use(payload: dict):
    """PostToolUse hook: save artifacts from tool executions."""
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_response = payload.get("tool_response", {}) or payload.get("toolResponse", {})

    task = get_active_task()
    if task is None:
        return

    task_id = task["task_id"]

    # Save test results
    if tool_name == "Bash" and "pytest" in str(tool_input := payload.get("tool_input", {})):
        output = tool_response.get("output", "") or str(tool_response)
        save_artifact(task_id, f"test_run_{datetime.now(timezone.utc).strftime('%H%M%S')}.log", output)

    # Save git diffs
    if tool_name == "Bash" and "git diff" in str(payload.get("tool_input", {})):
        output = tool_response.get("output", "") or str(tool_response)
        if output.strip():
            save_artifact(task_id, f"git_diff_{datetime.now(timezone.utc).strftime('%H%M%S')}.diff", output)


def _run_route_committee(task_id: str, user_task: str) -> bool:
    """Run the local route committee to generate route.json.

    Returns True if route.json was written successfully.
    """
    tasks_dir = _tasks_dir()
    plan_file = tasks_dir / task_id / "plan.json"
    route_file = tasks_dir / task_id / "route.json"

    if not plan_file.exists():
        return False

    # Locate committee script relative to this file
    committee_script = Path(__file__).resolve().parent.parent / "local_route_committee.py"
    if not committee_script.exists():
        # Fallback: look in repo tools/ relative to cwd
        committee_script = Path("tools/local_route_committee.py")

    cmd = [
        sys.executable,
        str(committee_script),
        user_task[:2000],
        "--plan", str(plan_file),
        "--json",
        "--output", str(route_file),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            return False
        if not route_file.exists():
            return False
        _update_session(task_id, {"route_json_exists": True, "phase": "executing"})
        return True
    except Exception:
        return False


def on_stop(payload: dict) -> dict:
    """Stop hook: trigger route committee if plan exists but no route yet."""
    task = get_active_task()
    if task is None:
        return {}

    task_id = task["task_id"]

    if should_trigger_committee(task_id):
        if _run_route_committee(task_id, task.get("user_task", "")):
            return {
                "decision": "allow",
                "reason": (
                    f"route.json generated by the local route committee. "
                    f"Next session may execute with route enforcement: "
                    f".local_llm_out/tasks/{task_id}/route.json"
                ),
            }
        return {
            "decision": "block",
            "reason": (
                f"Plan exists but no route.json. The local route committee "
                f"(Qwen 27B + Gemma 31B) must evaluate the plan before execution.\n"
                f"Run: py -3 tools/local_route_committee.py --plan "
                f".local_llm_out/tasks/{task_id}/plan.json --json --output "
                f".local_llm_out/tasks/{task_id}/route.json"
            ),
        }

    return {}
