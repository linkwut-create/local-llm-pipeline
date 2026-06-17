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
        "allowed": {"Read", "Grep", "Glob", "Bash", "Task", "Skill", "Agent"},
        "denied": {"Edit", "Write", "NotebookEdit"},
        "cloud_ok": True,
        "max_files": 20,
        "_note": "Pro cannot edit/write directly. Must use Agent(model='deepseek-v4-flash') for implementation.",
    },
    "flash_subagent": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "Write", "Edit", "Task", "Skill", "Agent"},
        "denied": {"NotebookEdit"},
        "cloud_ok": True,
        "max_files": 50,
        "_note": "Flash subagent has full access. Pro delegates implementation via Agent.",
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


def _mark_plan_written(task_id: str) -> None:
    """Update session state to reflect that plan.json exists on disk.

    Called from on_post_tool_use when a Write tool writes plan.json.
    Does NOT re-write plan.json — only updates the session metadata.
    """
    plan_file = _tasks_dir() / task_id / "plan.json"
    if plan_file.exists():
        _update_session(task_id, {"plan_json_exists": True, "phase": "routing"})


def save_artifact(task_id: str, name: str, content: str) -> Path:
    """Save an artifact file and update the artifact index."""
    art_file = _tasks_dir() / task_id / "artifacts" / name
    art_file.write_text(content, encoding="utf-8")
    _update_session(task_id, {
        "artifacts": _get_artifacts(task_id) + [name],
    })
    return art_file


def save_artifact_indexed(task_id: str, name: str, content: str,
                          artifact_type: str = "generic",
                          tool_name: str = "",
                          metadata: dict | None = None) -> Path:
    """Save an artifact AND update artifact_index.json with metadata."""
    art_path = save_artifact(task_id, name, content)
    entry = {
        "name": name,
        "type": artifact_type,
        "tool": tool_name,
        "size_bytes": len(content.encode("utf-8")),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        entry["meta"] = metadata
    _update_artifact_index(task_id, entry)
    return art_path


def _update_artifact_index(task_id: str, entry: dict) -> None:
    """Append an entry to the artifact index file."""
    index_file = _tasks_dir() / task_id / "artifacts" / "artifact_index.json"
    try:
        if index_file.exists():
            index = json.loads(index_file.read_text(encoding="utf-8"))
            if not isinstance(index, list):
                index = []
        else:
            index = []
        index.append(entry)
        index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # never crash on artifact housekeeping


def _classify_bash_artifact(command: str) -> str:
    """Classify a Bash command's artifact type from its command string."""
    cmd_lower = command.lower()
    if "pytest" in cmd_lower or "unittest" in cmd_lower:
        return "test_run"
    if "git diff" in cmd_lower:
        return "git_diff"
    if "git log" in cmd_lower:
        return "git_log"
    if "git status" in cmd_lower:
        return "git_status"
    if "pip install" in cmd_lower or "npm install" in cmd_lower:
        return "package_install"
    if "python" in cmd_lower or "py -3" in cmd_lower:
        return "script_run"
    return "bash_output"


def _truncate_output(output: str, max_chars: int = 10000) -> str:
    """Truncate output to max_chars, adding a truncation note."""
    if len(output) <= max_chars:
        return output
    return output[:max_chars] + f"\n\n... [truncated: {len(output)} total chars, showing first {max_chars}]"


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


def set_flash_authorized(task_id: str) -> None:
    """Record that the user has authorized Flash cloud execution for this task."""
    _update_session(task_id, {"flash_authorized": True})


def is_flash_authorized(task_id: str) -> bool:
    """Check if Flash cloud execution has been authorized for this task."""
    session_file = _tasks_dir() / task_id / "session.json"
    if not session_file.exists():
        return False
    try:
        s = json.loads(session_file.read_text(encoding="utf-8"))
        return s.get("flash_authorized", False)
    except Exception:
        return False


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
        # Pro audit: when committee disagrees, Pro audits but does NOT vote.
        # Pro can read files to form an opinion, then presents to user.
        enforcement = route.get("_enforcement", {})
        pro_audit = enforcement.get("pro_audit_requested", False)

        if pro_audit and tool_name in ("Read", "Grep", "Glob", "Bash", "PowerShell", "WebSearch", "WebFetch", "Task", "Skill"):
            return True, ""  # Pro reads and forms audit opinion

        if tool_name in ("Edit", "Write", "NotebookEdit"):
            if pro_audit:
                return False, (
                    f"Pro audit requested (committee disagreement). "
                    f"Edit/Write blocked — present your audit opinion first, "
                    f"then wait for user approval before editing."
                )
            return False, (
                f"This task is pending human approval (route: ask_user). "
                f"Tool '{tool_name}' is blocked until the route committee authorizes execution.\n\n"
                f"To authorize, run:\n  {_auth_command(task_id)}\n\n"
                f"Then reply with a clear approval message such as 'approved' or 'continue'."
            )
        if pro_audit:
            return False, (
                f"Pro audit in progress (committee disagreement). "
                f"Tool '{tool_name}' blocked. Use Read/Grep/Glob to gather context, "
                f"then present your audit opinion. User approval required for edits."
            )
        return False, (
            f"This task is pending human approval (route: ask_user). "
            f"Tool '{tool_name}' is not allowed.\n\n"
            f"To authorize execution, run:\n  {_auth_command(task_id)}\n\n"
            f"Then reply with a clear approval message such as 'approved' or 'continue'."
        )

    if perms["allowed"] and tool_name not in perms["allowed"]:
        # Special message for flash_direct: forced model switch
        if route_type == "flash_direct" and tool_name in ("Edit", "Write", "NotebookEdit"):
            if _is_flash_session():
                return True, ""  # Already on Flash — allow direct editing
            return False, (
                f"Route '{route_type}' FORCES execution on DeepSeek v4 Flash. "
                f"You cannot {tool_name} directly — the main session model must switch. "
                f"Use Agent(model='deepseek-v4-flash') to delegate implementation, "
                f"or run /model to switch the session model to Flash."
            )
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

    # Flash cloud authorization — skip if already on Flash session
    route = load_route(task_id)
    if route is not None:
        route_type = route.get("recommended_route", "")
        perms = ROUTE_PERMISSIONS.get(route_type, {})
        if perms.get("cloud_ok") and route_type.startswith("flash_"):
            if _is_flash_session():
                return {}  # Already on Flash — cloud auth implicit
            if not is_flash_authorized(task_id):
                return {
                    "permissionDecision": "ask",
                    "reason": (
                        f"Route '{route_type}' requires execution on DeepSeek v4 Flash. "
                        f"This will send task context to a cloud API. "
                        f"Approve to authorize Flash for this task (once per task)."
                    ),
                }

    return {}  # allow


def on_post_tool_use(payload: dict):
    """PostToolUse hook: capture all tool outputs as indexed artifacts.

    Always saves:
      - tool_call_N.json  — tool name, input summary, output size, timestamp
    Additionally for Bash:
      - bash_output_N.log — stdout/stderr (classified: test_run, git_diff, etc.)
    Additionally for Edit/Write:
      - edit_record_N.json — file path, output summary
    Maintains:
      - artifact_index.json — all artifacts with type, tool, size, timestamp
    """
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})
    tool_response = payload.get("tool_response", {}) or payload.get("toolResponse", {})

    task = get_active_task()
    if task is None:
        return

    task_id = task["task_id"]

    # --- Detect plan.json writes and update session state ---
    if tool_name == "Write":
        file_path = str(tool_input.get("file_path", "") or "")
        if "plan.json" in file_path and str(task_id) in file_path:
            _mark_plan_written(task_id)

    ts = datetime.now(timezone.utc).strftime("%H%M%S")

    # --- 1. Always save tool call metadata ---
    input_summary = _summarize_input(tool_name, tool_input)
    output_summary = _summarize_output(tool_response)
    call_meta = {
        "tool": tool_name,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    save_artifact_indexed(
        task_id, f"tool_call_{ts}.json",
        json.dumps(call_meta, ensure_ascii=False, indent=2),
        artifact_type="tool_call",
        tool_name=tool_name,
    )

    # --- 2. Bash: save classified output ---
    if tool_name == "Bash":
        command = str(tool_input.get("command", "") or "")
        output = tool_response.get("output", "") or str(tool_response)
        if output.strip():
            atype = _classify_bash_artifact(command)
            ext = "diff" if atype == "git_diff" else "log"
            save_artifact_indexed(
                task_id, f"{atype}_{ts}.{ext}",
                _truncate_output(output),
                artifact_type=atype,
                tool_name=tool_name,
                metadata={"command": command[:500]},
            )

    # --- 3. Edit/Write: record file changes ---
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path = str(tool_input.get("file_path", "") or "")
        content_preview = _truncate_output(
            str(tool_input.get("content", "") or
                tool_input.get("new_string", "") or ""),
            max_chars=500,
        )
        edit_meta = {
            "tool": tool_name,
            "file_path": file_path,
            "content_preview": content_preview,
            "output_ok": bool(tool_response) and "error" not in str(tool_response).lower()[:200],
        }
        save_artifact_indexed(
            task_id, f"edit_record_{ts}.json",
            json.dumps(edit_meta, ensure_ascii=False, indent=2),
            artifact_type="file_edit",
            tool_name=tool_name,
            metadata={"file": file_path},
        )

    # --- 4. Flash authorization ---
    route = load_route(task_id)
    if route is not None:
        route_type = route.get("recommended_route", "")
        perms = ROUTE_PERMISSIONS.get(route_type, {})
        if perms.get("cloud_ok") and route_type.startswith("flash_"):
            if not is_flash_authorized(task_id):
                set_flash_authorized(task_id)


def _summarize_input(tool_name: str, tool_input: dict) -> dict:
    """Create a compact summary of tool input for the artifact index."""
    summary = {}
    if tool_name in ("Bash",):
        cmd = str(tool_input.get("command", "") or "")
        summary["command"] = cmd[:200]
    elif tool_name in ("Edit", "Write", "NotebookEdit"):
        summary["file_path"] = str(tool_input.get("file_path", "") or "")[:500]
        content = str(tool_input.get("content", "") or tool_input.get("new_string", "") or "")
        summary["content_len"] = len(content)
    elif tool_name in ("Read", "Grep", "Glob"):
        summary["path"] = str(tool_input.get("file_path", "") or tool_input.get("pattern", "") or "")[:200]
    elif tool_name == "Agent":
        prompt = str(tool_input.get("prompt", "") or "")
        summary["prompt_len"] = len(prompt)
        summary["subagent_type"] = str(tool_input.get("subagent_type", "") or "")
    return summary


def _summarize_output(tool_response) -> dict:
    """Create a compact summary of tool output for the artifact index."""
    if isinstance(tool_response, dict):
        output_str = tool_response.get("output", "") or str(tool_response)
    else:
        output_str = str(tool_response)
    return {
        "size_chars": len(output_str),
        "ok": "error" not in output_str.lower()[:200] if output_str else True,
    }


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


def _is_flash_session() -> bool:
    """Check if the current session is already running on Flash.
    
    Reads .claude/settings.local.json to check if model is set to Flash.
    Settings are loaded at session start, so this reflects the session's
    starting model.
    """
    try:
        sf = Path('.claude/settings.local.json')
        if sf.exists():
            settings = json.loads(sf.read_text(encoding='utf-8'))
            if isinstance(settings, dict):
                return settings.get('model', '') == 'deepseek-v4-flash'
    except Exception:
        pass
    return False


def _apply_model_switch(route_type: str) -> None:
    """Switch the main session model in Claude Code settings.
    
    Writes ``model`` to .claude/settings.local.json. The new model
    takes effect on the next Claude Code session start (or /model reload).
    
    Only switches for flash routes that require a different model than
    the default Pro/Opus tier.
    """
    _ROUTE_MODEL_MAP = {
        'flash_direct': 'deepseek-v4-flash',
        'flash_subagent': 'deepseek-v4-flash',
    }
    target_model = _ROUTE_MODEL_MAP.get(route_type)
    if target_model is None:
        return

    settings_file = Path('.claude/settings.local.json')
    try:
        if settings_file.exists():
            settings = json.loads(settings_file.read_text(encoding='utf-8'))
        else:
            settings = {}
        if not isinstance(settings, dict):
            settings = {}

        current = settings.get('model', '')
        if current == target_model:
            return  # already set

        settings['model'] = target_model
        settings_file.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
    except Exception:
        pass  # never crash the hook


def on_stop(payload: dict) -> dict:

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

    # Flash route: auto-switch model for next session
    route = load_route(task_id)
    if route is not None:
        route_type = route.get("recommended_route", "")
        if route_type.startswith("flash_"):
            _apply_model_switch(route_type)
            return {
                "decision": "allow",
                "reason": (
                    f"Route '{route_type}' → model set to deepseek-v4-flash. "
                    f"Next session will start on Flash. "
                    f"Pro remains available for planning/adjudication via /model."
                ),
            }

    return {}


# ═══════════════════════════════════════════════════════════════
# Main: stdin JSON dispatcher for Claude Code hook integration
# ═══════════════════════════════════════════════════════════════

# Canonical Claude Code hook event names.
_HOOK_DISPATCH = {
    "UserPromptSubmit": on_user_prompt_submit,
    "PreToolUse": on_pre_tool_use,
    "PostToolUse": on_post_tool_use,
    "Stop": on_stop,
}


def main():
    """Read a Claude Code hook payload from stdin, dispatch to the
    correct handler, and write the JSON result to stdout.

    Never raises — invalid payloads, unknown events, and internal
    errors all produce ``{}`` so the hook never crashes Claude Code.
    """
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            json.dump({}, sys.stdout)
            sys.stdout.flush()
            return

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            json.dump({}, sys.stdout)
            sys.stdout.flush()
            return

        # Resolve hook event name — Claude Code uses ``hook_event_name``.
        hook_event = (
            payload.get("hook_event_name")
            or payload.get("event")
            or ""
        )

        handler = _HOOK_DISPATCH.get(hook_event)
        if handler is not None:
            result = handler(payload) or {}
        else:
            result = {}

        json.dump(result, sys.stdout, ensure_ascii=False)
        sys.stdout.flush()
    except Exception:
        json.dump({}, sys.stdout)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
