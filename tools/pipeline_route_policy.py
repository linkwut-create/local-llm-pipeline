"""Pipeline Route Policy �?single source of truth for route permissions.

All route definitions, tool aliases, Bash classification, and validation
live here.  Both ``route_enforcer.py`` and ``local_route_committee.py``
MUST import from this module rather than maintaining their own copies.
"""

from __future__ import annotations

import re
from typing import Any

# ══════════════════════════════════════════════════════════════�?# 1. Canonical route permission table
# ══════════════════════════════════════════════════════════════�?
ROUTE_PERMISSIONS: dict[str, dict[str, Any]] = {
    "plan_only": {
        "allowed": {"Read", "Grep", "Glob", "RouteStatus", "RequestApproval",
                     "AskUserQuestion", "PushNotification", "CancelTask"},
        "denied": {"Bash", "PowerShell", "Write", "Edit", "NotebookEdit",
                    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                    "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*", "Agent"},
        "cloud_ok": False, "max_files": 3, "bash_policy": "deny_all",
        "description": "Planning only",
    },
    "direct": {
        "allowed": {"Read", "Grep", "Glob", "Edit", "Write", "Bash", "PowerShell"},
        "denied": {"NotebookEdit"},
        "cloud_ok": False, "max_files": None, "bash_policy": "allow_safe",
        "description": "User-approved full local execution",
    },
    "local_only": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "PowerShell",
                     "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                     "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*"},
        "denied": {"Edit", "Write", "NotebookEdit", "Agent"},
        "cloud_ok": False, "max_files": 10, "bash_policy": "readonly_or_test",
        "description": "Local-only execution",
    },
    "flash_direct": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "PowerShell",
                     "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                     "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*", "Agent"},
        "denied": {"Edit", "Write", "NotebookEdit"},
        "cloud_ok": True, "max_files": 20, "bash_policy": "readonly_or_test",
        "description": "Flash cloud; Pro cannot edit directly",
    },
    "flash_subagent": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "PowerShell",
                     "Write", "Edit", "TaskCreate", "TaskUpdate", "TaskGet",
                     "TaskList", "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*", "Agent"},
        "denied": {"NotebookEdit"},
        "cloud_ok": True, "max_files": 50, "bash_policy": "allow_safe",
        "description": "Flash subagent with full tool access",
    },
    "pro_decision": {
        "allowed": {"Read", "Grep", "Glob", "Bash", "PowerShell",
                     "WebSearch", "WebFetch",
                     "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                     "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*", "AskUserQuestion",
                     "mcp__local-llm__*"},
        "denied": {"Edit", "Write", "NotebookEdit", "Agent"},
        "cloud_ok": True, "max_files": None, "bash_policy": "readonly_or_test",
        "description": "Pro reads evidence and adjudicates; cannot edit",
    },
    "pro_execute_allowed": {
        "allowed": {"Read", "Grep", "Glob", "Edit", "Write", "Bash", "PowerShell",
                     "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                     "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*", "Agent",
                     "WebSearch", "WebFetch", "mcp__local-llm__*", "mcp__git__*"},
        "denied": {"NotebookEdit"},
        "cloud_ok": True, "max_files": None, "bash_policy": "allow_safe",
        "description": "Pro authorized to execute; destructive commands blocked",
    },
    "blocked": {
        "allowed": set(),
        "denied": {"Read", "Grep", "Glob", "Bash", "PowerShell",
                    "Write", "Edit", "NotebookEdit",
                    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                    "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*"},
        "cloud_ok": False, "max_files": 0, "bash_policy": "deny_all",
        "description": "Task blocked",
    },
    "ask_user": {
        "allowed": {"Read", "Grep", "Glob"},
        "denied": {"Bash", "PowerShell", "Write", "Edit", "NotebookEdit",
                    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
                    "TaskOutput", "TaskStop", "Skill", "mcp__local-llm__*", "mcp__git__*", "mcp__filesystem__*"},
        "cloud_ok": False, "max_files": 3, "bash_policy": "readonly_or_test",
        "description": "Pending human approval",
    },
}

VALID_ROUTES: set[str] = set(ROUTE_PERMISSIONS)

ROUTE_NAME_MIGRATIONS: dict[str, str] = {
    "claude_code_pro": "pro_execute_allowed",
    "manual_confirm": "ask_user",
    "pro_only": "pro_decision",
}

def resolve_route_name(name: str) -> str:
    if not name or not isinstance(name, str):
        return "ask_user"
    canonical = ROUTE_NAME_MIGRATIONS.get(name)
    if canonical is not None:
        return canonical
    if name in VALID_ROUTES:
        return name
    return "ask_user"

_TOOL_FAMILIES: dict[str, set[str]] = {
    "Task": {"TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
             "TaskOutput", "TaskStop"},
}

def _expand_tool_name(name: str) -> set[str]:
    return _TOOL_FAMILIES.get(name, {name})

ROUTE_JSON_SCHEMA = {
    "type": "object",
    "required": ["recommended_route"],
    "properties": {
        "recommended_route": {"type": "string", "enum": sorted(VALID_ROUTES)},
        "route": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "privacy_status": {"type": "string", "enum": ["safe", "needs_review", "blocked"]},
        "delegability": {"type": "string", "enum": ["high", "medium", "low", "blocked"]},
        "allowed_tools": {"type": "array", "items": {"type": "string"}},
        "blocked_tools": {"type": "array", "items": {"type": "string"}},
        "bash_policy": {"type": "string", "enum": ["deny_all", "readonly_or_test", "allow_safe", "allow_all"]},
        "plan_sha256": {"type": "string"},
        "task_id": {"type": "string"},
        "created_at": {"type": "string"},
        "_enforcement": {"type": "object"},
    },
}

def get_permissions(route_type: str) -> dict[str, Any]:
    canonical = resolve_route_name(route_type)
    return ROUTE_PERMISSIONS.get(canonical, ROUTE_PERMISSIONS["ask_user"])

def validate_route_json(route: dict | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(route, dict):
        errors.append("route must be a JSON object")
        return errors
    if "route" in route and "recommended_route" not in route:
        route = dict(route)
        route["recommended_route"] = route.pop("route")
    route_type = route.get("recommended_route")
    if not route_type:
        errors.append("missing required field: recommended_route")
    elif not isinstance(route_type, str):
        errors.append("recommended_route must be a string")
    elif route_type not in VALID_ROUTES and route_type not in ROUTE_NAME_MIGRATIONS:
        errors.append(f"unknown route '{route_type}'. Valid: {sorted(VALID_ROUTES)}")
    allowed = route.get("allowed_tools")
    if allowed is not None:
        if not isinstance(allowed, list):
            errors.append("allowed_tools must be a list")
        elif not all(isinstance(t, str) for t in allowed):
            errors.append("allowed_tools must contain only strings")
    blocked = route.get("blocked_tools")
    if blocked is not None:
        if not isinstance(blocked, list):
            errors.append("blocked_tools must be a list")
    enforcement = route.get("_enforcement")
    if enforcement is not None:
        if not isinstance(enforcement, dict):
            errors.append("_enforcement must be an object")
    return errors

# ══════════════════════════════════════════════════════════════�?# Bash command classification
# ══════════════════════════════════════════════════════════════�?
_BASH_DESTRUCTIVE = [
    r'\brm\s+-rf\b', r'\brm\s+-r\s+/', r'\bgit\s+reset\s+--hard\b',
    r'\bgit\s+clean\s+-f[dx]', r'\bformat\s+[a-zA-Z]:', r'\bdiskpart\b',
    r'\bdel\s+/[fF]\s+/[sS]', r'>\s*/dev/(?!null)', r'\bdd\s+if=',
    r'\bchmod\s+777\b', r'\bicacls\s+.*\/grant.*F\b',
]
_BASH_NETWORK = [
    r'\bgit\s+push\b', r'\bgit\s+pull\b',
    r'\bcurl\b.*\|.*\b(ba)?sh\b', r'\bwget\b.*\|.*\b(ba)?sh\b',
    r'\bscp\b\s', r'\brsync\b\s', r'\bssh\b\s+\w+@',
    r'\bgh\s+release\b', r'\bgh\s+pr\s+merge\b',
]
_BASH_DEPENDENCY = [
    r'\bpip\d*\s+install\b', r'\bnpm\s+i(nstall)?\b',
    r'\bcargo\s+install\b', r'\bgem\s+install\b',
    r'\bapt\b.*\binstall\b', r'\bbrew\s+install\b',
    r'\bchoco\s+install\b', r'\byarn\s+add\b',
]
_BASH_WORKSPACE_WRITE = [
    r'\bsed\b\s', r'\bperl\b\s+-pi', r'\btee\b\s',
    r'>[>]?\s*(?![&/])[^\s]', r'\bcp\b\s', r'\bmv\b\s', r'\brm\b\s',
    r'\bmkdir\b\s', r'\bgit\s+checkout\b', r'\bgit\s+add\b',
    r'\bgit\s+commit\b', r'\bgit\s+stash\b',
    r'\bgit\s+cherry-pick\b', r'\bgit\s+rebase\b', r'\bgit\s+merge\b',
    r'\bgit\s+tag\b', r'\bgit\s+branch\b',
    r'\bNew-Item\b', r'\bRemove-Item\b', r'\bRename-Item\b',
    r'\bSet-Content\b', r'\bOut-File\b', r'\bAdd-Content\b',
]
_BASH_TEST = [
    r'\bpytest\b', r'\bpython\s+-m\s+pytest\b',
    r'\bnpm\s+test\b', r'\bnpm\s+run\s+test\b',
    r'\bcargo\s+test\b', r'\bgo\s+test\b',
    r'\bpython\s+\S+\.py\b', r'\bpy\s+-3\s+\S+\.py\b',
    r'\btox\b', r'\bmake\s+test\b', r'\bjust\s+test\b',
    r'\bpython\s+-m\s+unittest\b',
]
_BASH_SAFE_READONLY = [
    r'^(git|cd\s+\S+\s*&&\s*git)\s+(status|diff|log|show|branch|tag|blame|stash\s+list|remote\s+-v|ls-files|rev-parse|config\s+-l|describe|rev-list|shortlog|whatchanged)',
    r'^(ls|dir)\b', r'^find\b', r'^(rg|grep)\b',
    r'^(cat|type)\s', r'^(echo|printf)\s',
    r'^(python|py)\s+--version', r'^(which|where|Get-Command)\b',
    r'^(head|tail|wc|sort|uniq|tree|du)\b',
    r'\bgit\s+log\b.*--oneline',
    r'^ssh\s+\S+\s+(echo|systemctl|curl|ls|cat|hostname|whoami|python3?)\b',
    r'^(Get-ChildItem|Get-Content|Get-Location|Test-Path|Resolve-Path)\b',
    r'(pip|npm|cargo|gem)\s+(list|show|info|freeze|outdated|audit)\b',
]

def _compile(patterns):
    return [re.compile(p, re.IGNORECASE) for p in patterns]

_DESTRUCTIVE_RE = _compile(_BASH_DESTRUCTIVE)
_NETWORK_RE = _compile(_BASH_NETWORK)
_DEPENDENCY_RE = _compile(_BASH_DEPENDENCY)
_WORKSPACE_WRITE_RE = _compile(_BASH_WORKSPACE_WRITE)
_TEST_RE = _compile(_BASH_TEST)
_READONLY_RE = _compile(_BASH_SAFE_READONLY)

def classify_bash_command(command: str) -> str:
    if not command or not isinstance(command, str):
        return "unknown"
    cmd = command.strip()
    for pat in _DESTRUCTIVE_RE:
        if pat.search(cmd): return "destructive"
    for pat in _NETWORK_RE:
        if pat.search(cmd): return "network_or_remote"
    for pat in _DEPENDENCY_RE:
        if pat.search(cmd): return "dependency_change"
    for pat in _WORKSPACE_WRITE_RE:
        if pat.search(cmd): return "workspace_write"
    for pat in _TEST_RE:
        if pat.search(cmd): return "safe_test"
    for pat in _READONLY_RE:
        if pat.search(cmd): return "safe_readonly"
    return "unknown"

_BASH_POLICY_ALLOWED: dict[str, set[str]] = {
    "deny_all": set(),
    "readonly_or_test": {"safe_readonly", "safe_test"},
    "allow_safe": {"safe_readonly", "safe_test", "workspace_write", "dependency_change"},
    "allow_all": {"safe_readonly", "safe_test", "workspace_write", "dependency_change",
                   "network_or_remote", "destructive", "unknown"},
}

def check_bash_allowed(command: str, bash_policy: str) -> tuple[bool, str]:
    if bash_policy == "allow_all":
        return True, ""
    tier = classify_bash_command(command)
    allowed_tiers = _BASH_POLICY_ALLOWED.get(bash_policy, set())
    if tier in allowed_tiers:
        return True, ""
    return False, (
        f"Bash command classified as '{tier}' not allowed under "
        f"bash_policy '{bash_policy}'. Allowed: {sorted(allowed_tiers)}"
    )

# ══════════════════════════════════════════════════════════════�?# Unified tool permission check
# ══════════════════════════════════════════════════════════════�?
def is_tool_permitted(
    tool_name: str,
    route_type: str,
    tool_input: dict | None = None,
    *,
    allowed_tools_override: list[str] | None = None,
) -> tuple[bool, str]:
    route_type = resolve_route_name(route_type)
    perms = get_permissions(route_type)

    if isinstance(allowed_tools_override, list) and allowed_tools_override:
        if tool_name in allowed_tools_override:
            return True, ""
        # Wildcard matching for override list too
        override_prefixes = [a[:-1] for a in allowed_tools_override if a.endswith("*")]
        if any(tool_name.startswith(p) for p in override_prefixes):
            return True, ""
        return False, (
            f"Tool '{tool_name}' not in route.json allowed_tools. "
            f"Allowed: {allowed_tools_override}"
        )

    if perms["allowed"]:
        allowed_expanded = set(perms["allowed"])
        for family in list(perms["allowed"]):
            allowed_expanded |= _expand_tool_name(family)
        # Wildcard prefix matching: "mcp__local-llm__*" matches any tool
        # starting with "mcp__local-llm__"
        allowed_prefixes = [a[:-1] for a in allowed_expanded if a.endswith("*")]
        if tool_name not in allowed_expanded and not any(
            tool_name.startswith(prefix) for prefix in allowed_prefixes
        ):
            return False, (
                f"Tool '{tool_name}' not allowed for route '{route_type}'. "
                f"Allowed: {sorted(perms['allowed'])}"
            )

    if tool_name in perms["denied"]:
        return False, f"Tool '{tool_name}' denied for route '{route_type}'."

    if tool_name in ("Bash", "PowerShell") and tool_input is not None:
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        bash_policy = perms.get("bash_policy", "deny_all")
        ok, reason = check_bash_allowed(command, bash_policy)
        if not ok:
            return False, reason

    return True, ""


# ══════════════════════════════════════════════════════════════�?# 7. Model roles and switch rules
# ══════════════════════════════════════════════════════════════�?
MODEL_ROLES: dict[str, str] = {
    "planner": "claude-fable-5",
    "router_qwen": "qwen3.6-deep",
    "router_gemma": "gemma4-31b",
    "worker_local": "qwen3-coder:30b",
    "worker_flash": "deepseek-v4-flash",
    "adjudicator": "claude-fable-5",
    "default": "claude-fable-5",
}

MODEL_SWITCH_RULES: dict[str, str | None] = {
    "flash_direct": "deepseek-v4-flash",
    "flash_subagent": None,
    "plan_only": None, "direct": None, "local_only": None,
    "pro_decision": None, "pro_execute_allowed": None,
    "blocked": None, "ask_user": None,
}

PHASE_MODEL_ROLES: dict[str, str] = {
    "planning": "planner",
    "routing": "router_qwen",
    "executing": "worker_local",
    "adjudicating": "adjudicator",
    "complete": "default",
}


def get_model_for_phase(phase: str) -> str:
    role = PHASE_MODEL_ROLES.get(phase, "default")
    return MODEL_ROLES.get(role, MODEL_ROLES["default"])


def get_switch_target(route_type: str) -> str | None:
    return MODEL_SWITCH_RULES.get(route_type)
