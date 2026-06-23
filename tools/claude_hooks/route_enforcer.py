"""Route Enforcer — enforce route.json in Claude Code hooks.

UserPromptSubmit → create task session, require plan-only
PreToolUse      → deny tools not allowed by route.json
PostToolUse     → save artifacts (test results, diffs, logs)
Stop            → trigger local route committee if plan exists

Design: Minimal, deterministic, never blocks the session itself.
         "Deny" means return a blocking response; "allow" means pass through.

Route permissions, Bash classification, and validation are defined in
``pipeline_route_policy.py`` — the single source of truth.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure the tools/ directory is on sys.path so we can import
# pipeline_route_policy regardless of how this script is invoked.
_TOOLS_DIR = str(Path(__file__).resolve().parent.parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from pipeline_route_policy import (
    ROUTE_PERMISSIONS,
    VALID_ROUTES,
    resolve_route_name,
    get_permissions,
    validate_route_json,
    classify_bash_command,
    check_bash_allowed,
    is_tool_permitted,
    get_model_for_phase,
    get_switch_target,
    MODEL_ROLES,
)


# ═══════════════════════════════════════════════════════════════
# Task lifecycle management
# ═══════════════════════════════════════════════════════════════

TASK_STATUS_ACTIVE = "active"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_CANCELLED = "cancelled"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_DISCARDED = "discarded"
TERMINAL_STATUSES = {
    TASK_STATUS_COMPLETED, TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED, TASK_STATUS_DISCARDED,
}

_CONTINUATION_KEYWORDS = (
    "继续", "请继续", "接着", "往下", "推进",
    "approve", "approved", "continue", "proceed", "go on", "move on", "carry on",
)

_CONTROL_STATEMENTS = {
    "run_tests": ("运行测试", "run tests", "跑测试", "执行测试"),
    "retry": ("重试", "retry", "再试一次"),
    "accept": ("接受", "accept", "approved", "approve", "批准"),
    "reject": ("拒绝", "reject", "decline"),
    "stop": ("停止", "stop", "halt", "pause"),
    "cancel": ("取消任务", "cancel", "cancel task", "abort"),
    "new_task": ("新建任务", "new task", "start new task", "newtask"),
}


# ═══════════════════════════════════════════════════════════════
# Task session management
# ═══════════════════════════════════════════════════════════════

def _tasks_dir() -> Path:
    override = os.environ.get("LOCAL_LLM_TASKS_DIR")
    if override:
        return Path(override)
    return Path(".local_llm_out/tasks")


def _project_root() -> str:
    return str(Path.cwd().resolve())


def _claude_session_id() -> str | None:
    return os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("PID")


def create_task_session(
    user_task: str,
    *,
    project_root: str | None = None,
    claude_session_id: str | None = None,
    parent_task_id: str | None = None,
    is_test_task: bool = False,
) -> dict:
    task_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    session_dir = _tasks_dir() / task_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "artifacts").mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "task_id": task_id, "created_at": now, "updated_at": now,
        "user_task": user_task[:2000], "phase": "planning",
        "status": TASK_STATUS_ACTIVE,
        "project_root": project_root if project_root is not None else _project_root(),
        "claude_session_id": claude_session_id if claude_session_id is not None else _claude_session_id(),
        "parent_task_id": parent_task_id, "is_test_task": bool(is_test_task),
        "plan_json_exists": False, "route_json_exists": False,
        "artifacts": [], "messages": [],
    }
    # Record initial model state (read from settings, never mutated)
    current_model = _read_current_model()
    session["model_state"] = {
        "initial_model": current_model,
        "current_model": current_model,
        "target_model": None,
        "model_switch_reason": None,
        "model_switches": [],
    }
    (session_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    (session_dir / "user_task.md").write_text(
        f"# Task\n\n{user_task}\n\nCreated: {session['created_at']}", encoding="utf-8")
    return session


def get_active_task(
    project_root: str | None = None,
    claude_session_id: str | None = None,
) -> dict | None:
    tasks_dir = _tasks_dir()
    if not tasks_dir.exists():
        return None
    target_project = project_root if project_root is not None else _project_root()
    target_session = claude_session_id if claude_session_id is not None else _claude_session_id()
    sessions = []
    for sd in tasks_dir.iterdir():
        session_file = sd / "session.json"
        if not session_file.exists():
            continue
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if not all(k in data for k in ("task_id", "user_task", "created_at", "status")):
            continue
        if data.get("is_test_task"):
            continue
        if data.get("status") in TERMINAL_STATUSES:
            continue
        if data.get("project_root", target_project) != target_project:
            continue
        if claude_session_id is not None and data.get("claude_session_id") != target_session:
            continue
        sessions.append(data)
    if not sessions:
        return None
    sessions.sort(
        key=lambda s: (s.get("updated_at") or s.get("created_at"), s.get("created_at", "")),
        reverse=True)
    return sessions[0]


def _load_session(task_id: str) -> dict | None:
    session_file = _tasks_dir() / task_id / "session.json"
    if not session_file.exists():
        return None
    try:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def append_task_message(task_id: str, role: str, content: str) -> dict | None:
    session = _load_session(task_id)
    if session is None:
        return None
    messages = session.get("messages", [])
    messages.append({
        "role": role, "content": content[:5000],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _update_session(task_id, {
        "messages": messages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return _load_session(task_id)


def set_task_status(task_id: str, status: str) -> dict | None:
    if status not in ({TASK_STATUS_ACTIVE} | TERMINAL_STATUSES):
        raise ValueError(f"Unknown task status: {status}")
    session = _load_session(task_id)
    if session is None:
        return None
    updates = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status in TERMINAL_STATUSES:
        updates["phase"] = "complete"
    _update_session(task_id, updates)
    return _load_session(task_id)


def complete_task(task_id: str) -> dict | None:
    return set_task_status(task_id, TASK_STATUS_COMPLETED)


def cancel_task(task_id: str) -> dict | None:
    return set_task_status(task_id, TASK_STATUS_CANCELLED)


def resume_task(task_id: str) -> dict | None:
    return set_task_status(task_id, TASK_STATUS_ACTIVE)


def _is_continuation_prompt(prompt: str) -> bool:
    text = prompt.strip().lower()
    if not text:
        return False
    if text in _CONTINUATION_KEYWORDS:
        return True
    for keywords in _CONTROL_STATEMENTS.values():
        for kw in keywords:
            if text == kw or text.startswith(kw + " ") or text.startswith(kw + ":") or text.startswith(kw + "："):
                return True
    return False


def _detect_control_statement(prompt: str) -> str | None:
    text = prompt.strip().lower()
    if not text:
        return None
    for intent, keywords in _CONTROL_STATEMENTS.items():
        for kw in keywords:
            if (text == kw or text.startswith(kw + " ")
                or text.startswith(kw + ":") or text.startswith(kw + "：")
                or text.endswith(" " + kw)):
                return intent
    if text in _CONTINUATION_KEYWORDS:
        return "continue"
    return None


def load_route(task_id: str) -> dict | None:
    route_file = _tasks_dir() / task_id / "route.json"
    if route_file.exists():
        try:
            data = json.loads(route_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "route" in data and "recommended_route" not in data:
                    data["recommended_route"] = data["route"]
                return data
        except Exception:
            pass
    return None


def save_plan(task_id: str, plan: dict) -> Path:
    plan_file = _tasks_dir() / task_id / "plan.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_session(task_id, {"plan_json_exists": True, "phase": "routing"})
    return plan_file


def _mark_plan_written(task_id: str) -> None:
    plan_file = _tasks_dir() / task_id / "plan.json"
    if plan_file.exists():
        _update_session(task_id, {"plan_json_exists": True, "phase": "routing"})


def save_artifact(task_id: str, name: str, content: str) -> Path:
    art_file = _tasks_dir() / task_id / "artifacts" / name
    art_file.write_text(content, encoding="utf-8")
    _update_session(task_id, {"artifacts": _get_artifacts(task_id) + [name]})
    return art_file


def save_artifact_indexed(task_id: str, name: str, content: str,
                          artifact_type: str = "generic",
                          tool_name: str = "",
                          metadata: dict | None = None) -> Path:
    art_path = save_artifact(task_id, name, content)
    entry = {
        "name": name, "type": artifact_type, "tool": tool_name,
        "size_bytes": len(content.encode("utf-8")),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        entry["meta"] = metadata
    _update_artifact_index(task_id, entry)
    return art_path


def _update_artifact_index(task_id: str, entry: dict) -> None:
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
        pass


def _classify_bash_artifact(command: str) -> str:
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
    _update_session(task_id, {"flash_authorized": True})


def is_flash_authorized(task_id: str) -> bool:
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
    plan = _tasks_dir() / task_id / "plan.json"
    route = _tasks_dir() / task_id / "route.json"
    return f"py -3 tools/local_route_committee.py --plan {plan} --json --output {route}"


_FILE_PATH_INPUT_KEYS = (
    "file", "filePath", "file_path", "files", "glob", "newPath", "path",
    "pattern", "oldPath", "notebookPath", "notebook_path", "source",
    "sourcePath", "target", "targetPath",
)

_SENSITIVE_EXACT_NAMES = {
    ".env", ".env.local", ".env.development", ".env.test",
    ".env.production", ".envrc", ".netrc", ".npmrc", ".pypirc",
    "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa",
}

_SAFE_ENV_TEMPLATE_NAMES = {
    ".env.defaults", ".env.example", ".env.sample", ".env.template",
}

_SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


def _path_basename_for_policy(path_value: object) -> str:
    if not isinstance(path_value, str):
        return ""
    value = path_value.strip().strip("\"'`;,(){}[]<>|&")
    if not value:
        return ""
    if "=" in value and value.startswith("-"):
        value = value.rsplit("=", 1)[-1]
        value = value.strip().strip("\"'`;,(){}[]<>|&")
    return value.replace("\\", "/").rstrip("/").split("/")[-1].lower()


def _is_sensitive_path(path_value: object) -> bool:
    name = _path_basename_for_policy(path_value)
    if not name or name in _SAFE_ENV_TEMPLATE_NAMES:
        return False
    if name in _SENSITIVE_EXACT_NAMES:
        return True
    if name.startswith(".env.") and name not in _SAFE_ENV_TEMPLATE_NAMES:
        return True
    if name.endswith(_SENSITIVE_SUFFIXES):
        return True
    return name in {"credentials", "credentials.json", "token", "token.json"}


def _iter_tool_paths(tool_input: dict):
    if not isinstance(tool_input, dict):
        return
    for key in _FILE_PATH_INPUT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield item


def _bash_mentions_sensitive_path(command: object) -> bool:
    if not isinstance(command, str):
        return False
    for token in re.split(r"[\s\"'`;&|<>(){}\[\]]+", command):
        if _is_sensitive_path(token):
            return True
    return False


def _secret_access_reason(tool_name: str, tool_input: dict) -> str:
    path_tools = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep", "Glob"}
    if tool_name in path_tools:
        for path_value in _iter_tool_paths(tool_input):
            if _is_sensitive_path(path_value):
                return (
                    "Secrets/.env protection: hard-deny access to sensitive "
                    f"path '{path_value}' via {tool_name}."
                )
    if tool_name in {"Bash", "PowerShell"}:
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if _bash_mentions_sensitive_path(command):
            return (
                "Secrets/.env protection: hard-deny shell command that references "
                "a sensitive path."
            )
    return ""


def check_tool_allowed(tool_name: str, task_id: str,
                       tool_input: dict | None = None) -> tuple[bool, str]:
    """Check if a tool is allowed by the current route.

    Delegates to ``pipeline_route_policy.is_tool_permitted`` for the
    canonical permission check, then adds plan-hash validation and
    ask_user special handling.
    """
    route = load_route(task_id)
    if route is None:
        if tool_name in ("Edit", "Write", "NotebookEdit"):
            return False, (
                "No route.json exists yet. Plan must be created before editing. "
                "Use Read/Grep/Glob to understand the codebase first."
            )
        return True, ""

    # Plan hash validation
    plan_file = _tasks_dir() / task_id / "plan.json"
    expected_sha = route.get("plan_sha256")
    if expected_sha and plan_file.exists():
        import hashlib
        actual_sha = hashlib.sha256(plan_file.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            if tool_name in ("Edit", "Write", "NotebookEdit", "Bash", "PowerShell"):
                return False, (
                    f"Plan has changed since approval (SHA-256 mismatch). "
                    f"Expected {expected_sha[:16]}..., got {actual_sha[:16]}..."
                )
            return True, ""

    route_type = route.get("recommended_route", "ask_user")

    # ask_user special handling (enforcer-specific, not in policy module)
    if route_type == "ask_user":
        enforcement = route.get("_enforcement", {})
        pro_audit = enforcement.get("pro_audit_requested", False)
        if pro_audit and tool_name in ("Read", "Grep", "Glob", "Bash", "PowerShell",
                                        "WebSearch", "WebFetch", "Task", "Skill"):
            return True, ""
        if tool_name in ("Edit", "Write", "NotebookEdit"):
            msg = "Pro audit requested. Edit/Write blocked." if pro_audit else (
                f"This task is pending human approval (route: ask_user). "
                f"To authorize: {_auth_command(task_id)}")
            return False, msg
        if pro_audit:
            return False, "Pro audit in progress."
        return False, f"Route 'ask_user' blocks '{tool_name}'."

    # Flash direct special handling
    if route_type == "flash_direct" and tool_name in ("Edit", "Write", "NotebookEdit"):
        if _is_flash_session():
            return True, ""
        return False, (
            f"Route 'flash_direct' FORCES execution on DeepSeek v4 Flash. "
            f"You cannot {tool_name} directly — use Agent(model='deepseek-v4-flash')."
        )

    # Agent restriction (enforcer layer)
    if tool_name == "Agent":
        if route_type in ("blocked", "local_only"):
            return False, f"Agent calls not allowed under route '{route_type}'."
        if route_type == "pro_decision":
            return False, (
                "Agent calls not allowed under route 'pro_decision'. "
                "Pro adjudicates — elevation to 'pro_execute_allowed' required."
            )

    # Delegate to canonical policy module
    allowed_tools = route.get("allowed_tools")
    return is_tool_permitted(
        tool_name, route_type, tool_input,
        allowed_tools_override=allowed_tools if isinstance(allowed_tools, list) and allowed_tools else None,
    )


def should_trigger_committee(task_id: str) -> bool:
    session_file = _tasks_dir() / task_id / "session.json"
    if not session_file.exists():
        return False
    s = json.loads(session_file.read_text(encoding="utf-8"))
    if s.get("route_json_exists"):
        return False
    if s.get("plan_json_exists"):
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# Hook response builders
# ═══════════════════════════════════════════════════════════════

def on_user_prompt_submit(payload: dict) -> dict:
    prompt_text = payload.get("prompt", "") or payload.get("text", "") or ""
    project_root = payload.get("project_root") or payload.get("projectRoot")
    claude_session_id = payload.get("claude_session_id") or payload.get("claudeSessionId")
    control_intent = _detect_control_statement(prompt_text)
    is_too_short = not prompt_text or len(prompt_text) < 10
    if is_too_short and control_intent is None:
        return {}
    active_task = get_active_task(project_root=project_root,
                                  claude_session_id=claude_session_id)
    if control_intent == "new_task" or active_task is None:
        session = create_task_session(prompt_text, project_root=project_root,
                                      claude_session_id=claude_session_id)
        append_task_message(session["task_id"], "user", prompt_text)
        initial_model = session.get("model_state", {}).get("initial_model", "claude-fable-5")
        return {
            "additionalContext": (
                f"[TASK SESSION: {session['task_id']}]\n"
                f"Model: {initial_model} | Phase: planning\n"
                f"You are in PLAN-ONLY mode. Before any code changes, output:\n"
                f"1. A plan.json describing what you will do\n"
                f"2. Save it with: Write .local_llm_out/tasks/{session['task_id']}/plan.json\n"
                f"After plan.json exists, the route committee will decide execution.\n"
                f"Do NOT edit/write source files until route is approved."
            ),
        }
    task_id = active_task["task_id"]
    append_task_message(task_id, "user", prompt_text)

    # Model-aware context: check if a model switch is pending
    model_hint = ""
    ms = active_task.get("model_state", {})
    target = ms.get("target_model")
    if target and target != _read_current_model():
        model_hint = (
            f"\nModel switch pending: {ms.get('previous_model', '?')} -> {target} "
            f"({ms.get('model_switch_reason', 'route requirement')}). "
            f"Consider running /model to switch."
        )

    if control_intent in ("stop", "cancel"):
        cancel_task(task_id)
        return {"additionalContext": f"[TASK SESSION: {task_id}]\nTask cancelled.{model_hint}"}
    if control_intent == "accept":
        return {"additionalContext": f"[TASK SESSION: {task_id}]\nApproval recorded.{model_hint}"}
    return {"additionalContext": f"[TASK SESSION: {task_id}]\nContinuing active task.{model_hint}"}


def on_pre_tool_use(payload: dict) -> dict:
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})

    secret_reason = _secret_access_reason(tool_name, tool_input)
    if secret_reason:
        return {"permissionDecision": "deny", "reason": secret_reason}

    task = get_active_task()
    if task is None:
        return {}

    task_id = task["task_id"]

    file_path = tool_input.get("file_path", "") or ""
    if "plan.json" in file_path and str(task_id) in file_path:
        return {}

    allowed, reason = check_tool_allowed(tool_name, task_id, tool_input)
    if not allowed:
        return {"permissionDecision": "deny", "reason": reason}

    route = load_route(task_id)
    if route is not None:
        route_type = route.get("recommended_route", "")
        perms = ROUTE_PERMISSIONS.get(route_type, {})
        if perms.get("cloud_ok") and route_type.startswith("flash_"):
            if _is_flash_session():
                return {}
            if not is_flash_authorized(task_id):
                return {
                    "permissionDecision": "ask",
                    "reason": (
                        f"Route '{route_type}' requires DeepSeek v4 Flash. "
                        f"Approve to authorize (once per task)."
                    ),
                }

    return {}


def on_post_tool_use(payload: dict):
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})
    tool_response = payload.get("tool_response", {}) or payload.get("toolResponse", {})

    task = get_active_task()
    if task is None:
        return
    task_id = task["task_id"]

    if tool_name == "Write":
        fp = str(tool_input.get("file_path", "") or "")
        if "plan.json" in fp and str(task_id) in fp:
            _mark_plan_written(task_id)

    ts = datetime.now(timezone.utc).strftime("%H%M%S")

    call_meta = {
        "tool": tool_name,
        "input_summary": _summarize_input(tool_name, tool_input),
        "output_summary": _summarize_output(tool_response),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    save_artifact_indexed(
        task_id, f"tool_call_{ts}.json",
        json.dumps(call_meta, ensure_ascii=False, indent=2),
        artifact_type="tool_call", tool_name=tool_name,
    )

    if tool_name == "Bash":
        command = str(tool_input.get("command", "") or "")
        output = tool_response.get("output", "") or str(tool_response)
        if output.strip():
            atype = _classify_bash_artifact(command)
            ext = "diff" if atype == "git_diff" else "log"
            save_artifact_indexed(
                task_id, f"{atype}_{ts}.{ext}",
                _truncate_output(output),
                artifact_type=atype, tool_name=tool_name,
                metadata={"command": command[:500]},
            )

    if tool_name in ("Edit", "Write", "NotebookEdit"):
        fp = str(tool_input.get("file_path", "") or "")
        content_preview = _truncate_output(
            str(tool_input.get("content", "") or
                tool_input.get("new_string", "") or ""), max_chars=500)
        save_artifact_indexed(
            task_id, f"edit_record_{ts}.json",
            json.dumps({"tool": tool_name, "file_path": fp,
                         "content_preview": content_preview,
                         "output_ok": bool(tool_response) and
                         "error" not in str(tool_response).lower()[:200]},
                        ensure_ascii=False, indent=2),
            artifact_type="file_edit", tool_name=tool_name,
            metadata={"file": fp},
        )

    route = load_route(task_id)
    if route is not None:
        route_type = route.get("recommended_route", "")
        perms = ROUTE_PERMISSIONS.get(route_type, {})
        if perms.get("cloud_ok") and route_type.startswith("flash_"):
            if not is_flash_authorized(task_id):
                set_flash_authorized(task_id)


def _summarize_input(tool_name: str, tool_input: dict) -> dict:
    summary = {}
    if tool_name in ("Bash",):
        summary["command"] = str(tool_input.get("command", "") or "")[:200]
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
    output_str = ""
    if isinstance(tool_response, dict):
        output_str = tool_response.get("output", "") or str(tool_response)
    else:
        output_str = str(tool_response)
    return {
        "size_chars": len(output_str),
        "ok": "error" not in output_str.lower()[:200] if output_str else True,
    }


def _run_route_committee(task_id: str, user_task: str) -> bool:
    tasks_dir = _tasks_dir()
    plan_file = tasks_dir / task_id / "plan.json"
    route_file = tasks_dir / task_id / "route.json"
    if not plan_file.exists():
        return False
    committee_script = Path(__file__).resolve().parent.parent / "local_route_committee.py"
    if not committee_script.exists():
        committee_script = Path("tools/local_route_committee.py")
    cmd = [sys.executable, str(committee_script), user_task[:2000],
           "--plan", str(plan_file), "--json", "--output", str(route_file)]
    try:
        result = subprocess.run(cmd, cwd=str(Path.cwd()),
                                capture_output=True, text=True,
                                timeout=180, check=False)
        if result.returncode != 0:
            return False
        if not route_file.exists():
            return False
        _update_session(task_id, {"route_json_exists": True, "phase": "executing"})
        return True
    except Exception:
        return False


def _read_current_model() -> str:
    """Read the current session model from settings (read-only, never mutates)."""
    try:
        sf = Path('.claude/settings.local.json')
        if sf.exists():
            settings = json.loads(sf.read_text(encoding='utf-8'))
            if isinstance(settings, dict):
                return settings.get('model', '') or 'claude-fable-5'
    except Exception:
        pass
    return 'claude-fable-5'


def _is_flash_session() -> bool:
    """Check if the current session is already on Flash."""
    return _read_current_model() == 'deepseek-v4-flash'


def _record_model_switch(task_id: str, target_model: str, reason: str) -> None:
    """Record a pending model switch in session.json (never mutates global settings)."""
    session = _load_session(task_id)
    if session is None:
        return
    ms = session.get("model_state", {})
    switches = ms.get("model_switches", [])
    switches.append({
        "from": ms.get("current_model", "unknown"),
        "to": target_model, "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    ms["previous_model"] = ms.get("current_model")
    ms["current_model"] = target_model
    ms["target_model"] = target_model
    ms["model_switch_reason"] = reason
    ms["model_switches"] = switches
    _update_session(task_id, {"model_state": ms})


def on_stop(payload: dict) -> dict:
    task = get_active_task()
    if task is None:
        return {}
    task_id = task["task_id"]
    if should_trigger_committee(task_id):
        if _run_route_committee(task_id, task.get("user_task", "")):
            return {
                "decision": "allow",
                "reason": f"route.json generated: .local_llm_out/tasks/{task_id}/route.json",
            }
        return {
            "decision": "block",
            "reason": (
                f"Plan exists but no route.json. Run:\n"
                f"  py -3 tools/local_route_committee.py --plan "
                f".local_llm_out/tasks/{task_id}/plan.json --json --output "
                f".local_llm_out/tasks/{task_id}/route.json"
            ),
        }
    route = load_route(task_id)
    if route is not None:
        route_type = route.get("recommended_route", "")
        target = get_switch_target(route_type)
        if target is not None:
            _record_model_switch(task_id, target, f"route '{route_type}' requires Flash")
            return {
                "decision": "allow",
                "reason": (
                    f"Route '{route_type}' requests model switch to {target}. "
                    f"Use /model to switch, or restart the session. "
                    f"Model switch recorded in session.json."
                ),
            }
    return {}


# ═══════════════════════════════════════════════════════════════
# Main dispatcher
# ═══════════════════════════════════════════════════════════════

_HOOK_DISPATCH = {
    "UserPromptSubmit": on_user_prompt_submit,
    "PreToolUse": on_pre_tool_use,
    "PostToolUse": on_post_tool_use,
    "Stop": on_stop,
}


def main():
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
        hook_event = (
            payload.get("hook_event_name")
            or payload.get("event")
            or "")
        handler = _HOOK_DISPATCH.get(hook_event)
        result = handler(payload) if handler is not None else {}
        json.dump(result or {}, sys.stdout, ensure_ascii=False)
        sys.stdout.flush()
    except Exception:
        json.dump({}, sys.stdout)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
