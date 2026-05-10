#!/usr/bin/env python3
"""
User-scope global MCP launcher for local-llm-pipeline.

Registers once with Claude Code:
    claude mcp add --transport stdio --scope user local-llm -- python <this_file>

Detects the current project from CWD, sets LOCAL_LLM_TARGET_PROJECT so the
MCP server's run_subprocess / output-dir / path resolution all target the
caller's project, then delegates to local_llm_mcp_server for core handling.

Usage:
    python tools/local_llm_global_mcp_launcher.py
"""

import json
import os
import sys
import time
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.parent.resolve()
SCRIPT_DIR = Path(__file__).parent.resolve()

SERVER_NAME = "local-llm-pipeline"


def _read_version() -> str:
    vf = PIPELINE_ROOT / "VERSION"
    if vf.exists():
        return vf.read_text(encoding="utf-8").strip()
    return "unknown"


SERVER_VERSION = _read_version()


def find_project_root() -> Path | None:
    """Find the git root from CWD. Returns None if not in a git repo."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists():
            return parent
    return None


def validate_project(project: Path) -> tuple[bool, str]:
    """Check that the project is valid for pipeline operations."""
    if not project.exists():
        return False, f"Project directory does not exist: {project}"
    git_dir = project / ".git"
    if not git_dir.exists():
        return False, f"Not a git repository: {project}"
    return True, ""


def make_error(msg_id, code: int, message: str) -> dict:
    """Build a JSON-RPC error response. msg_id may be None (pre-initialize)."""
    resp = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if msg_id is not None:
        resp["id"] = msg_id
    else:
        resp["id"] = 0
    return resp


def build_structured_error(msg_id, error_type: str, error: str,
                           suggestion: str = "") -> dict:
    """Build a structured error as a tools/call content response."""
    from datetime import datetime, timezone
    content = json.dumps({
        "ok": False,
        "error_type": error_type,
        "error": error,
        "suggestion": suggestion,
        "elapsed_seconds": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False)
    return {
        "jsonrpc": "2.0",
        "id": msg_id or 0,
        "result": {"content": [{"type": "text", "text": content}]},
    }


def main():
    project = find_project_root()
    if project is None:
        resp = build_structured_error(
            None, "no_git_repository",
            "Not in a git repository. Navigate to a git project and restart Claude Code.",
            "cd to any git project and Claude Code will auto-connect the local-llm MCP server.",
        )
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 1

    valid, err = validate_project(project)
    if not valid:
        resp = build_structured_error(
            None, "invalid_project", err,
            "Verify the project directory exists and contains a .git folder.",
        )
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 1

    # Set env vars so the MCP server resolves paths, output, and subprocess
    # cwd against the target project, not the pipeline source repo.
    os.environ["LOCAL_LLM_TARGET_PROJECT"] = str(project)
    os.environ["LOCAL_LLM_SOURCE_REPO"] = str(PIPELINE_ROOT)

    print(f"Global MCP Launcher v{SERVER_VERSION}: target={project}", file=sys.stderr)

    # Import MCP server modules AFTER env is set so _get_effective_project_root
    # picks up LOCAL_LLM_TARGET_PROJECT on first call.
    sys.path.insert(0, str(SCRIPT_DIR))
    from local_llm_mcp_server import (
        handle_initialize as mcp_handle_initialize,
        handle_tools_list as mcp_handle_tools_list,
        handle_tools_call as mcp_handle_tools_call,
    )
    from local_llm_logging import write_log_entry
    from datetime import datetime, timezone

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = request.get("id", 0)
        method = request.get("method", "")

        if method == "initialize":
            resp = mcp_handle_initialize(msg_id)
            # Override serverInfo version with the launcher's own
            resp["result"]["serverInfo"]["name"] = f"{SERVER_NAME} (global)"
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        elif method == "tools/list":
            resp = mcp_handle_tools_list(msg_id)
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        elif method == "tools/call":
            tool_name = request.get("params", {}).get("name", "unknown")
            start = time.time()
            resp = mcp_handle_tools_call(msg_id, request.get("params", {}))
            elapsed = round(time.time() - start, 2)
            print(f"  [{elapsed}s] {tool_name}", file=sys.stderr)
            # Structured log with source="global-mcp"
            try:
                content = json.loads(resp["result"]["content"][0]["text"])
                write_log_entry({
                    "source": "global-mcp",
                    "tool": tool_name,
                    "task": content.get("task") or tool_name.replace("local_", ""),
                    "profile": content.get("profile"),
                    "model": content.get("model"),
                    "ok": content.get("ok", False),
                    "duration_sec": elapsed,
                    "error_type": content.get("error_type"),
                    "error": (content.get("error") or "")[:200] if content.get("error") else None,
                    "request_id": content.get("request_id"),
                    "prompt_id": content.get("prompt_id"),
                    "prompt_version": content.get("prompt_version"),
                    "prompt_hash": content.get("prompt_hash"),
                    "cache_hit": content.get("cache_hit", False),
                })
            except Exception:
                pass
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        elif method == "notifications/initialized":
            pass
        elif method.startswith("notifications/"):
            pass
        else:
            resp = make_error(msg_id, -32601, f"Method not found: {method}")
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
