r"""MCP gate hook — repository-local source of truth (Phase 2A.1).

All core logic lives here so tests can import without depending on
~/.claude/hooks/mcp_gate.py. The user-level hook file is a thin wrapper
that imports this module and calls main() with a config dir.

Session boundary: SessionStart clears per-session state (mcp_calls)
so previous sessions don't contaminate the Stop hook summary.

Hook events:
- SessionStart: clear per-session MCP tracking, set session_id.
- PreToolUse:  block git commit without prior local review.
- PostToolUse: track review state, dirty flag, MCP usage.
- Stop:        advisory session summary via stderr (never blocks).
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REVIEW_TOOLS = {
    "mcp__local-llm__local_review_diff",
    "mcp__local-llm__local_debate_review_diff",
}

_DIRTY_TOOLS = {"Edit", "Write", "MultiEdit"}

_MCP_TOOLS = {
    "mcp__local-llm__local_check",
    "mcp__local-llm__local_summarize_file",
    "mcp__local-llm__local_summarize_tree",
    "mcp__local-llm__local_review_diff",
    "mcp__local-llm__local_debate_review_diff",
    "mcp__local-llm__local_generate_test_plan",
    "mcp__local-llm__local_draft_code",
    "mcp__local-llm__local_contextual_analyze",
}

_REDACT_RE = re.compile(
    r'(sk-[a-zA-Z0-9_-]{20,})'
    r'|(Bearer\s+[a-zA-Z0-9_\-\.]+)'
    r'|(api_key[=:]\s*["\']?[a-zA-Z0-9_\-]+)'
    r'|("token"\s*:\s*"[a-zA-Z0-9_\-]{10,}")'
    r'|("api_key"\s*:\s*"[a-zA-Z0-9_\-]{10,}")'
    r'|("password"\s*:\s*"[^"]+")'
    r'|("secret"\s*:\s*"[^"]+")'
)

_GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

_STATE_DEFAULTS = {
    "diff_reviewed": False,
    "dirty_since_review": False,
    "reviewed_at": None,
    "reviewed_by": None,
    "reviewed_repo": None,
    "reviewed_head": None,
    "reviewed_diff_hash": None,
    "mcp_calls": {},
    "session_id": None,
    "session_started_at": None,
}


# ---------------------------------------------------------------------------
# public helpers (imported by tests and user-level wrapper)
# ---------------------------------------------------------------------------

def review_tool_succeeded(payload: dict) -> bool:
    """Return True only if the MCP review tool call clearly succeeded."""
    resp = payload.get("tool_response")
    if not isinstance(resp, dict):
        return False
    text = resp.get("text", "")
    if not text:
        return False
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return False
    if result.get("is_error") is True:
        return False
    if result.get("error"):
        return False
    error_type = result.get("error_type")
    if error_type and str(error_type) != "none" and str(error_type) != "":
        return False
    warnings = result.get("warnings", [])
    if isinstance(warnings, list):
        for w in warnings:
            w_str = str(w).lower()
            if any(kw in w_str for kw in (
                "traceback", "unicode", "decodeerror", "encodeerror",
                "can't decode", "can't encode",
            )):
                return False
    return result.get("ok") is True


def is_git_commit(payload: dict) -> bool:
    """Detect git commit even with global options and chained commands."""
    name = payload.get("tool_name", "")
    if name not in ("Bash", "PowerShell"):
        return False
    cmd = str(payload.get("tool_input", {}).get("command", ""))
    if not re.search(r"\bgit\b", cmd) or not re.search(r"\bcommit\b", cmd):
        return False
    if "git commit-tree" in cmd:
        return False
    for sub in _split_command_chain(cmd):
        if _single_cmd_is_git_commit(sub):
            return True
    return False


def run_git(args, cwd=None):
    """Run a git command, return stripped stdout or None on failure."""
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True,
            timeout=10, cwd=cwd,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def get_repo_root(cwd=None):
    return run_git(["rev-parse", "--show-toplevel"], cwd=cwd)


def get_head(cwd=None):
    return run_git(["rev-parse", "HEAD"], cwd=cwd)


def get_diff_hash(cwd=None):
    """SHA256 hex of staged diff (falls back to unstaged if nothing staged)."""
    diff = run_git(["diff", "--cached"], cwd=cwd)
    if diff is None:
        return None
    if not diff:
        diff = run_git(["diff"], cwd=cwd) or ""
    return hashlib.sha256(diff.encode()).hexdigest()


def get_repo_fingerprint(cwd=None):
    """Return {repo, head, diff_hash} or None if git rev-parse fails."""
    repo = get_repo_root(cwd)
    if not repo:
        return None
    return {
        "repo": repo,
        "head": get_head(cwd),
        "diff_hash": get_diff_hash(cwd),
    }


def extract_git_c_path(cmd: str):
    """Extract the -C <path> argument from a git command, or None."""
    try:
        tokens = shlex.split(cmd, posix=False)
    except ValueError:
        return None
    tokens = [t.strip('"').strip("'") for t in tokens]
    if not tokens or tokens[0] != "git":
        return None
    i = 1
    while i < len(tokens) - 1:
        if tokens[i] == "-C":
            return tokens[i + 1]
        if tokens[i] in _GIT_ARG_OPTS:
            i += 2
        elif tokens[i].startswith("-"):
            i += 1
        else:
            break
    return None


def tool_name(payload: dict) -> str:
    return payload.get("tool_name", "")


# ---------------------------------------------------------------------------
# state file helpers
# ---------------------------------------------------------------------------

def _state_file_path(config_dir: str) -> Path:
    return Path(config_dir) / "state.json"


def _log_file_path(config_dir: str) -> Path:
    return Path(config_dir) / "hook-events.jsonl"


def load_state(config_dir: str) -> dict:
    state = dict(_STATE_DEFAULTS)
    try:
        sf = _state_file_path(config_dir)
        if sf.exists():
            raw = json.loads(sf.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state.update(raw)
    except Exception:
        pass
    return state


def save_state(config_dir: str, state: dict):
    try:
        _state_file_path(config_dir).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def log_event(config_dir: str, payload: dict):
    try:
        with open(_log_file_path(config_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# per-session state helpers
# ---------------------------------------------------------------------------

def _ensure_session(config_dir: str):
    """If no session is active, create one (clear mcp_calls, set session_id)."""
    state = load_state(config_dir)
    if not state.get("session_id"):
        state["session_id"] = uuid.uuid4().hex[:12]
        state["session_started_at"] = datetime.now(timezone.utc).isoformat()
        state["mcp_calls"] = {}
        state["_last_mcp_failed"] = False
        save_state(config_dir, state)


def _clear_session(config_dir: str):
    """Start a fresh session: new id, clear per-session tracking."""
    state = load_state(config_dir)
    # Keep persistent fields (commit gate state crosses sessions)
    # Clear only per-session MCP tracking
    state["session_id"] = uuid.uuid4().hex[:12]
    state["session_started_at"] = datetime.now(timezone.utc).isoformat()
    state["mcp_calls"] = {}
    state["_last_mcp_failed"] = False
    save_state(config_dir, state)


# ---------------------------------------------------------------------------
# hook event handlers
# ---------------------------------------------------------------------------

def handle_post_tooluse(config_dir: str, payload: dict):
    """Track review state, dirty flag, and MCP tool usage."""
    _ensure_session(config_dir)
    name = tool_name(payload)

    if name in _REVIEW_TOOLS:
        if review_tool_succeeded(payload):
            state = load_state(config_dir)
            cwd = payload.get("cwd", "")
            fp = get_repo_fingerprint(cwd=cwd) if cwd else None
            state["diff_reviewed"] = True
            state["dirty_since_review"] = False
            state["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            state["reviewed_by"] = name
            state["reviewed_repo"] = fp["repo"] if fp else None
            state["reviewed_head"] = fp["head"] if fp else None
            state["reviewed_diff_hash"] = fp["diff_hash"] if fp else None
            state.pop("last_review_error", None)
            save_state(config_dir, state)
        else:
            state = load_state(config_dir)
            state["last_review_error"] = datetime.now(timezone.utc).isoformat()
            state["diff_reviewed"] = False
            save_state(config_dir, state)

    if name in _DIRTY_TOOLS:
        state = load_state(config_dir)
        state["dirty_since_review"] = True
        save_state(config_dir, state)

    if name in _MCP_TOOLS:
        state = load_state(config_dir)
        mcp_calls = state.get("mcp_calls", {})
        mcp_calls[name] = True
        mcp_calls["_last_mcp_ts"] = datetime.now(timezone.utc).isoformat()
        if not review_tool_succeeded(payload):
            mcp_calls["_last_mcp_failed"] = True
            mcp_calls["_last_mcp_error_ts"] = datetime.now(timezone.utc).isoformat()
        state["mcp_calls"] = mcp_calls
        save_state(config_dir, state)


def handle_pre_tooluse(config_dir: str, payload: dict) -> dict:
    """Check commit gate. Returns {"allow": bool, "reason": str}."""
    _ensure_session(config_dir)
    if is_git_commit(payload):
        state = load_state(config_dir)
        cmd = str(payload.get("tool_input", {}).get("command", ""))
        c_path = extract_git_c_path(cmd)
        target_cwd = c_path or payload.get("cwd", "")
        fp = get_repo_fingerprint(cwd=target_cwd) if target_cwd else None

        reviewed_ok = (
            state.get("diff_reviewed")
            and not state.get("dirty_since_review")
            and fp is not None
            and state.get("reviewed_repo") == fp["repo"]
            and state.get("reviewed_head") == fp["head"]
            and state.get("reviewed_diff_hash") == fp["diff_hash"]
        )

        if reviewed_ok:
            return {"allow": True, "reason": ""}
        else:
            parts = [
                "BLOCKED: git commit requires prior local model review.",
                "Call mcp__local-llm__local_review_diff with commit_gate=true.",
            ]
            if state.get("diff_reviewed"):
                if state.get("dirty_since_review"):
                    parts.append("Reason: files modified after review.")
                elif fp is None:
                    parts.append("Reason: cannot determine current repo/HEAD.")
                elif state.get("reviewed_repo") != fp["repo"]:
                    parts.append(
                        f"Reason: review was for {state.get('reviewed_repo')}, "
                        f"current is {fp['repo']}."
                    )
                elif state.get("reviewed_head") != fp["head"]:
                    parts.append("Reason: HEAD has changed since review.")
                elif state.get("reviewed_diff_hash") != fp["diff_hash"]:
                    parts.append("Reason: staged diff has changed since review.")
                else:
                    parts.append("Reason: review state mismatch.")
            parts.append(
                f"State: diff_reviewed={state.get('diff_reviewed')}, "
                f"dirty_since_review={state.get('dirty_since_review')}"
            )
            return {"allow": False, "reason": "\n".join(parts)}
    return {"allow": True, "reason": ""}


def handle_stop(config_dir: str, payload: dict) -> list:
    """Stop hook: return list of reminder strings. Never blocks.

    Returns empty list if nothing to report.
    """
    state = load_state(config_dir)
    cwd = payload.get("cwd", "")
    mcp_calls = state.get("mcp_calls", {})
    reminders = []

    # MCP tool usage
    if not mcp_calls.get("mcp__local-llm__local_check"):
        reminders.append("local_check was not called this session.")

    has_review = (
        mcp_calls.get("mcp__local-llm__local_review_diff")
        or mcp_calls.get("mcp__local-llm__local_debate_review_diff")
    )
    if not has_review:
        reminders.append("No local_review_diff or local_debate_review_diff called this session.")

    has_summarize = (
        mcp_calls.get("mcp__local-llm__local_summarize_file")
        or mcp_calls.get("mcp__local-llm__local_summarize_tree")
    )
    if not has_summarize:
        reminders.append("No local_summarize_file/tree called this session.")

    # Failed MCP
    if mcp_calls.get("_last_mcp_failed"):
        reminders.append("WARNING: at least one MCP call failed this session. "
                         "Do not commit without a successful review.")

    # Review failure
    if state.get("last_review_error") and not state.get("diff_reviewed"):
        reminders.append("Last MCP review FAILED (not marked as reviewed).")

    # Git tree state
    if cwd:
        dirty_output = run_git(["status", "--short"], cwd=cwd)
        if dirty_output:
            dirty_files = dirty_output.strip().split("\n")
            reminders.append(f"Working tree dirty ({len(dirty_files)} file(s)):")
            for f in dirty_files[:10]:
                reminders.append(f"  {f}")
            if len(dirty_files) > 10:
                reminders.append(f"  ... and {len(dirty_files) - 10} more")
            if not state.get("diff_reviewed"):
                reminders.append("REMINDER: dirty tree without successful "
                                 "local_review_diff. Run review before commit.")
            elif state.get("dirty_since_review"):
                reminders.append("REMINDER: files modified after last review. "
                                 "Re-run review before commit.")

        staged = run_git(["diff", "--cached", "--stat"], cwd=cwd)
        if staged:
            reminders.append("Staged changes exist — remember to re-review "
                             "staged diff before commit.")

    return reminders


def handle_session_start(config_dir: str, payload: dict):
    """Start a fresh session, clearing per-session MCP tracking."""
    _clear_session(config_dir)


# ---------------------------------------------------------------------------
# main entry point (for user-level wrapper)
# ---------------------------------------------------------------------------

def _redact(text: str) -> str:
    return _REDACT_RE.sub("***REDACTED***", text)


def _redact_recursive(obj):
    if isinstance(obj, dict):
        return {k: _redact_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_recursive(v) for v in obj]
    if isinstance(obj, str):
        return _redact(obj)
    return obj


def main(config_dir: str):
    """Main hook entry point. Reads payload from stdin, executes, writes result.

    config_dir: directory for state.json and hook-events.jsonl.
    """
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not raw.strip():
            sys.exit(0)
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    if not isinstance(payload, dict):
        sys.exit(0)

    payload["_audit_ts"] = datetime.now(timezone.utc).isoformat()
    log_event(config_dir, _redact_recursive(dict(payload)))

    event = payload.get("hook_event_name", "")

    if event == "SessionStart":
        handle_session_start(config_dir, payload)

    elif event == "PostToolUse":
        handle_post_tooluse(config_dir, payload)

    elif event == "PreToolUse":
        result = handle_pre_tooluse(config_dir, payload)
        if not result["allow"]:
            sys.stdout.write(json.dumps({
                "continue": False,
                "decision": "block",
                "reason": result["reason"],
            }))
            sys.stdout.flush()
            sys.exit(1)

    elif event == "Stop":
        reminders = handle_stop(config_dir, payload)
        if reminders:
            summary = "=== MCP Session Summary ===\n" + "\n".join(f"  {r}" for r in reminders)
            try:
                sys.stderr.write(summary + "\n")
                sys.stderr.flush()
            except Exception:
                pass

    sys.stdout.write(json.dumps({"continue": True}))
    sys.stdout.flush()
    sys.exit(0)


# ---------------------------------------------------------------------------
# internal helpers (not exported)
# ---------------------------------------------------------------------------

def _split_command_chain(cmd: str):
    parts = []
    current = []
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == '"':
            current.append(ch)
            i += 1
            while i < n and cmd[i] != '"':
                current.append(cmd[i])
                i += 1
            if i < n:
                current.append(cmd[i])
            i += 1
        elif ch == "'":
            current.append(ch)
            i += 1
            while i < n and cmd[i] != "'":
                current.append(cmd[i])
                i += 1
            if i < n:
                current.append(cmd[i])
            i += 1
        elif cmd[i:i + 2] == "&&":
            parts.append("".join(current).strip())
            current = []
            i += 2
        elif cmd[i:i + 2] == "||":
            parts.append("".join(current).strip())
            current = []
            i += 2
        elif ch == ";":
            parts.append("".join(current).strip())
            current = []
            i += 1
        else:
            current.append(ch)
            i += 1
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _single_cmd_is_git_commit(cmd: str) -> bool:
    try:
        raw_tokens = shlex.split(cmd, posix=False)
    except ValueError:
        return False
    tokens = [t.strip('"').strip("'") for t in raw_tokens]
    if not tokens or tokens[0] != "git":
        return False
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in _GIT_ARG_OPTS:
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            break
    return i < len(tokens) and tokens[i] == "commit"
