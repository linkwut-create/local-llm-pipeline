#!/usr/bin/env python3
"""
User-scope global MCP launcher for local-llm-pipeline.

Registers once with Claude Code:
    claude mcp add --transport stdio --scope user local-llm -- python <this_file>

Detects the current project from CWD, then proxies all 7 MCP tools
against that project. Outputs go to <project>/.local_llm_out/.

Usage:
    python tools/local_llm_global_mcp_launcher.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()
SCRIPT_DIR = PIPELINE_ROOT

SERVER_NAME = "local-llm-pipeline"
SERVER_VERSION = "0.9.2"


def find_project_root() -> Path | None:
    """Find the git root from CWD. Returns None if not in a git repo."""
    cwd = Path.cwd()
    # Check upward for .git
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


def read_json_request() -> dict | None:
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except (json.JSONDecodeError, EOFError):
        return None


def write_json_response(response: dict):
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def make_error(msg_id, code, message):
    return {
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": code, "message": message},
    }


def handle_initialize(msg_id, project: Path):
    return {
        "jsonrpc": "2.0", "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        },
    }


def handle_tools_list(msg_id):
    # Reuse the tool definitions from the real MCP server
    sys.path.insert(0, str(SCRIPT_DIR))
    from local_llm_mcp_server import TOOLS
    tool_list = []
    for name, schema in TOOLS.items():
        tool_list.append({
            "name": name,
            "description": schema["description"],
            "inputSchema": schema["inputSchema"],
        })
    return {
        "jsonrpc": "2.0", "id": msg_id,
        "result": {"tools": tool_list},
    }


def handle_tools_call(msg_id, params: dict, project: Path):
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    sys.path.insert(0, str(SCRIPT_DIR))
    from local_llm_mcp_server import TOOL_HANDLERS

    if tool_name not in TOOL_HANDLERS:
        return make_error(msg_id, -32601, f"Unknown tool: {tool_name}")

    handler = TOOL_HANDLERS[tool_name]

    # For path-based tools, resolve relative paths against the project root
    if "path" in arguments:
        raw_path = arguments["path"]
        p = Path(raw_path)
        if not p.is_absolute():
            arguments["path"] = str(project / raw_path)

    try:
        # Override output dir to target project
        old_cwd = os.getcwd()
        os.chdir(str(project))
        try:
            output = handler(arguments)
        finally:
            os.chdir(old_cwd)

        content = json.dumps(output, ensure_ascii=False)
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {"content": [{"type": "text", "text": content}]},
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {"content": [{"type": "text", "text": json.dumps({
                "ok": False, "tool": tool_name,
                "error": f"Internal error: {e}",
                "elapsed_seconds": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False)}]},
        }


def main():
    project = find_project_root()
    if project is None:
        # No git repo — write error and exit
        resp = make_error(None, -32000, "Not in a git repository. "
                          "Navigate to a git project and restart Claude Code.")
        write_json_response(resp)
        return 1

    valid, err = validate_project(project)
    if not valid:
        resp = make_error(None, -32000, err)
        write_json_response(resp)
        return 1

    print(f"Global MCP Launcher v{SERVER_VERSION}: target={project}", file=sys.stderr)

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
            write_json_response(handle_initialize(msg_id, project))
        elif method == "tools/list":
            write_json_response(handle_tools_list(msg_id))
        elif method == "tools/call":
            tool_name = request.get("params", {}).get("name", "unknown")
            start = time.time()
            response = handle_tools_call(msg_id, request.get("params", {}), project)
            elapsed = round(time.time() - start, 2)
            print(f"  [{elapsed}s] {tool_name}", file=sys.stderr)
            write_json_response(response)
        elif method == "notifications/initialized":
            pass
        else:
            write_json_response(make_error(msg_id, -32601, f"Method not found: {method}"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
