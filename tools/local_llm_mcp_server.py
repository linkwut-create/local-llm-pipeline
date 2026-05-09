#!/usr/bin/env python3
"""
Local LLM MCP Server — exposes read-only CLI tools as MCP (Model Context Protocol) tools.

Transport: stdio JSON-RPC 2.0.
Read-only: never modifies source files, never runs arbitrary commands.

Usage:
    python tools/local_llm_mcp_server.py
"""

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from local_llm_worker import is_blocked_path

def _read_version() -> str:
    vf = PROJECT_ROOT / "VERSION"
    if vf.exists():
        return vf.read_text(encoding="utf-8").strip()
    return "0.5.0"

SERVER_NAME = "local-llm-pipeline"
SERVER_VERSION = _read_version()

MAX_DIFF_CHARS = 100_000
MAX_PATH_MAX_CHARS = 200_000
MAX_MAX_FILES = 50
DEFAULT_TIMEOUT = 600
DEBATE_TIMEOUT = 900
DEBATE_FAST_PER_ROUND_TIMEOUT = 350

TOOLS = {
    "local_check": {
        "description": "Run local LLM environment health check. Returns Ollama connectivity, model availability, and profile recommendations. Fast (~5s), no LLM call. Use before other local tools to verify the environment is ready.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "local_summarize_file": {
        "description": "Summarize a single file using a local LLM. Returns purpose, key functions, dependencies, and potential issues. Typical time: 20-60s. Use for understanding unfamiliar source files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to summarize (must exist, must not be blocked).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override (e.g. fast_summary, code_worker).",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
            },
            "required": ["path"],
        },
    },
    "local_summarize_tree": {
        "description": "Summarize a directory tree using a local LLM. Returns directory purpose, main modules, and suggested reading order. Typical time: 30-90s.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to summarize (must exist, must not be blocked).",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Max files to read (default: 20, max: 50).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
            },
            "required": ["path"],
        },
    },
    "local_generate_test_plan": {
        "description": "Generate a test plan for a source file using a local LLM. Returns test categories, edge cases, and coverage suggestions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the source file (must exist, must not be blocked).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
            },
            "required": ["path"],
        },
    },
    "local_review_diff": {
        "description": "Review a git diff using a local LLM (single model). Returns problems, test gaps, compatibility risks, and security concerns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {
                    "type": "string",
                    "description": "The diff text to review (max 100000 chars).",
                },
                "profile": {
                    "type": "string",
                    "description": "Optional profile name override.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model name override.",
                },
            },
            "required": ["diff_text"],
        },
    },
    "local_debate_review_diff": {
        "description": "Cross-review a git diff using multiple local models in debate mode. Defaults to fast mode (2 rounds) with summary-only output. Full 3-round debate available for large/risky diffs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {
                    "type": "string",
                    "description": "The diff text to review (max 100000 chars).",
                },
                "fast": {
                    "type": "boolean",
                    "description": "Use fast mode (2 rounds instead of 3). Default: true.",
                },
                "summary_only": {
                    "type": "boolean",
                    "description": "Return only findings summary, no per-round details. Default: true.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max input characters (default: profile default or 60000, max: 200000).",
                },
            },
            "required": ["diff_text"],
        },
    },
    "local_draft_code": {
        "description": "Draft code (fix, feature, refactor) or suggest improvements using a local LLM. Output goes to .local_llm_out/ only — NEVER modifies source files. Controller must review, decide, and apply manually.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Draft task: draft-fix, draft-feature, draft-refactor, or suggest-improvements.",
                    "enum": ["draft-fix", "draft-feature", "draft-refactor", "suggest-improvements"],
                },
                "prompt": {
                    "type": "string",
                    "description": "Description of the issue, feature, refactoring goal, or code to improve.",
                },
                "context_file": {
                    "type": "string",
                    "description": "Optional path to a file to include as context.",
                },
                "profile": {"type": "string", "description": "Optional profile override."},
                "model": {"type": "string", "description": "Optional model override."},
            },
            "required": ["task", "prompt"],
        },
    },
}


def read_json_request() -> dict | None:
    """Read a single JSON-RPC request from stdin."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    except EOFError:
        return None


def write_json_response(response: dict):
    """Write a JSON-RPC response to stdout."""
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_initialize(msg_id: int | str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
            },
        },
    }


def handle_tools_list(msg_id: int | str) -> dict:
    tool_list = []
    for name, schema in TOOLS.items():
        tool_list.append({
            "name": name,
            "description": schema["description"],
            "inputSchema": schema["inputSchema"],
        })
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"tools": tool_list},
    }


def validate_path(path_str: str) -> tuple[bool, str]:
    """Validate a file/directory path. Returns (ok, error_message).

    Always resolves to absolute path to prevent symlink and '..' bypasses.
    Blocked paths are rejected regardless of existence.
    """
    path = Path(path_str)
    resolved = path.resolve()
    if is_blocked_path(path) or is_blocked_path(resolved):
        return False, f"Path is blocked (secrets/system dirs): {path_str}"
    if not path.exists():
        return False, f"Path not found: {path_str}"
    return True, ""


def build_router_cmd(task: str, path: str | None, max_files: int | None,
                     max_chars: int | None, profile: str | None, model: str | None) -> list[str]:
    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), task]
    if path:
        cmd.append(path)
    if max_files is not None:
        cmd.extend(["--max-files", str(max_files)])
    if max_chars is not None:
        cmd.extend(["--max-chars", str(max_chars)])
    if profile:
        cmd.extend(["--profile", profile])
    if model:
        cmd.extend(["--model", model])
    return cmd


def run_subprocess(cmd: list[str], stdin_data: str | None = None,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a subprocess and return structured result."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SCRIPT_DIR.parent),
        )
        elapsed = round(time.time() - start, 2)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[:50000],
            "stderr": result.stderr[:10000],
            "returncode": result.returncode,
            "elapsed_seconds": elapsed,
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Subprocess timed out after {timeout}s",
            "returncode": -1,
            "elapsed_seconds": elapsed,
        }
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Subprocess error: {e}",
            "returncode": -1,
            "elapsed_seconds": elapsed,
        }


def find_latest_json_output() -> dict | None:
    """Find the most recent JSON output file in .local_llm_out."""
    out_dir = SCRIPT_DIR.parent / ".local_llm_out"
    if not out_dir.exists():
        return None
    json_files = sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jf in json_files:
        try:
            return json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return None


def truncate_output(data: dict, max_keys: int = 500) -> dict:
    """Truncate large outputs to keep MCP responses manageable."""
    raw = json.dumps(data, ensure_ascii=False)
    if len(raw) <= 50000:
        return data
    truncated = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > 5000:
            truncated[k] = v[:5000] + "... [truncated]"
        elif isinstance(v, list) and len(v) > 50:
            truncated[k] = v[:50] + ["... [truncated]"]
        else:
            truncated[k] = v
    return truncated


def call_local_check(params: dict) -> dict:
    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_check.py")]
    result = run_subprocess(cmd)
    return {
        "tool": "local_check",
        "ok": result["ok"],
        "result": {
            "stdout": result["stdout"][:10000],
            "stderr": result["stderr"][:5000],
        },
        "error": None if result["ok"] else result["stderr"][:500],
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_summarize_file(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return {"tool": "local_summarize_file", "ok": False, "result": None, "error": err,
                "error_type": "blocked_path", "suggestion": "use a file path that is not in the blocked list",
                "elapsed_seconds": 0, "created_at": datetime.now(timezone.utc).isoformat()}

    max_chars = params.get("max_chars")
    if max_chars is not None:
        max_chars = min(int(max_chars), MAX_PATH_MAX_CHARS)

    cmd = build_router_cmd("summarize-file", path_str, None, max_chars,
                           params.get("profile"), params.get("model"))
    result = run_subprocess(cmd)
    latest = find_latest_json_output()
    return {
        "tool": "local_summarize_file",
        "ok": result["ok"],
        "result": truncate_output(latest) if latest else {"stdout": result["stdout"][:5000]},
        "error": None if result["ok"] else result["stderr"][:500],
        "error_type": None if result["ok"] else "subprocess_failed",
        "suggestion": None if result["ok"] else "check that Ollama is running and the model is available",
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_summarize_tree(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return {"tool": "local_summarize_tree", "ok": False, "result": None, "error": err,
                "error_type": "blocked_path", "suggestion": "use a directory path that is not in the blocked list",
                "elapsed_seconds": 0, "created_at": datetime.now(timezone.utc).isoformat()}

    max_files = min(int(params.get("max_files", 20)), MAX_MAX_FILES)
    max_chars = params.get("max_chars")
    if max_chars is not None:
        max_chars = min(int(max_chars), MAX_PATH_MAX_CHARS)

    cmd = build_router_cmd("summarize-tree", path_str, max_files, max_chars,
                           params.get("profile"), params.get("model"))
    result = run_subprocess(cmd)
    latest = find_latest_json_output()
    return {
        "tool": "local_summarize_tree",
        "ok": result["ok"],
        "result": truncate_output(latest) if latest else {"stdout": result["stdout"][:5000]},
        "error": None if result["ok"] else result["stderr"][:500],
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_generate_test_plan(params: dict) -> dict:
    path_str = params.get("path", "")
    ok, err = validate_path(path_str)
    if not ok:
        return {"tool": "local_generate_test_plan", "ok": False, "result": None, "error": err,
                "elapsed_seconds": 0, "created_at": datetime.now(timezone.utc).isoformat()}

    cmd = build_router_cmd("generate-test-plan", path_str, None, None,
                           params.get("profile"), params.get("model"))
    result = run_subprocess(cmd)
    latest = find_latest_json_output()
    return {
        "tool": "local_generate_test_plan",
        "ok": result["ok"],
        "result": truncate_output(latest) if latest else {"stdout": result["stdout"][:5000]},
        "error": None if result["ok"] else result["stderr"][:500],
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_review_diff(params: dict) -> dict:
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return {"tool": "local_review_diff", "ok": False, "result": None,
                "error": "diff_text is empty", "elapsed_seconds": 0,
                "created_at": datetime.now(timezone.utc).isoformat()}
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS]

    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), "review-diff", "--stdin"]
    if params.get("profile"):
        cmd.extend(["--profile", params["profile"]])
    if params.get("model"):
        cmd.extend(["--model", params["model"]])

    result = run_subprocess(cmd, stdin_data=diff_text)
    latest = find_latest_json_output()
    return {
        "tool": "local_review_diff",
        "ok": result["ok"],
        "result": truncate_output(latest) if latest else {"stdout": result["stdout"][:5000]},
        "error": None if result["ok"] else result["stderr"][:500],
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_debate_review_diff(params: dict) -> dict:
    diff_text = params.get("diff_text", "")
    if not diff_text.strip():
        return {"tool": "local_debate_review_diff", "ok": False, "result": None,
                "error": "diff_text is empty", "elapsed_seconds": 0,
                "created_at": datetime.now(timezone.utc).isoformat()}

    if len(diff_text) > MAX_DIFF_CHARS:
        return {"tool": "local_debate_review_diff", "ok": False, "result": None,
                "error": f"diff_text too large ({len(diff_text)} chars, max {MAX_DIFF_CHARS}). "
                         f"Use CLI debate directly or pass a smaller diff.",
                "suggestion": "try smaller diff, --fast, or CLI",
                "elapsed_seconds": 0,
                "created_at": datetime.now(timezone.utc).isoformat()}
    diff_text = diff_text[:MAX_DIFF_CHARS]

    use_fast = params.get("fast", True)
    use_summary_only = params.get("summary_only", True)

    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_debate.py"), "review-diff", "--stdin"]
    if use_fast:
        cmd.append("--fast")
        cmd.extend(["--timeout", str(DEBATE_FAST_PER_ROUND_TIMEOUT)])
    if use_summary_only:
        cmd.append("--summary-only")
    if params.get("max_chars"):
        cmd.extend(["--max-chars", str(min(int(params["max_chars"]), MAX_PATH_MAX_CHARS))])

    result = run_subprocess(cmd, stdin_data=diff_text, timeout=DEBATE_TIMEOUT)

    if not result["ok"] and "timed out" in result["stderr"].lower():
        return {
            "tool": "local_debate_review_diff",
            "ok": False,
            "result": None,
            "error": "subprocess timed out",
            "suggestion": "try smaller diff, --fast, or CLI",
            "elapsed_seconds": result["elapsed_seconds"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    output = None
    if result["ok"]:
        try:
            output = json.loads(result["stdout"])
        except (json.JSONDecodeError, TypeError):
            pass
    if output is None and result["ok"]:
        output = find_latest_json_output()

    return {
        "tool": "local_debate_review_diff",
        "ok": result["ok"],
        "result": truncate_output(output) if output else {"stdout": result["stdout"][:5000],
                                                           "stderr": result["stderr"][:1000]},
        "error": None if result["ok"] else result["stderr"][:500],
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def call_draft_code(params: dict) -> dict:
    task = params.get("task", "draft-fix")
    prompt = params.get("prompt", "")
    context_file = params.get("context_file", "")

    if not prompt.strip():
        return {"tool": "local_draft_code", "ok": False, "result": None,
                "error": "prompt is empty", "elapsed_seconds": 0,
                "created_at": datetime.now(timezone.utc).isoformat()}

    cmd = [sys.executable, str(SCRIPT_DIR / "local_llm_router.py"), task]

    if context_file:
        ok, err = validate_path(context_file)
        if not ok:
            return {"tool": "local_draft_code", "ok": False, "result": None,
                    "error": err, "elapsed_seconds": 0,
                    "created_at": datetime.now(timezone.utc).isoformat()}
        cmd.append(context_file)

    if params.get("profile"):
        cmd.extend(["--profile", params["profile"]])
    if params.get("model"):
        cmd.extend(["--model", params["model"]])

    result = run_subprocess(cmd, stdin_data=prompt)
    latest = find_latest_json_output()
    return {
        "tool": "local_draft_code",
        "ok": result["ok"],
        "result": truncate_output(latest) if latest else {"stdout": result["stdout"][:5000]},
        "error": None if result["ok"] else result["stderr"][:500],
        "elapsed_seconds": result["elapsed_seconds"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


TOOL_HANDLERS = {
    "local_check": call_local_check,
    "local_summarize_file": call_summarize_file,
    "local_summarize_tree": call_summarize_tree,
    "local_generate_test_plan": call_generate_test_plan,
    "local_review_diff": call_review_diff,
    "local_debate_review_diff": call_debate_review_diff,
    "local_draft_code": call_draft_code,
}


def handle_tools_call(msg_id: int | str, params: dict) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name not in TOOL_HANDLERS:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Unknown tool: {tool_name}",
            },
        }

    handler = TOOL_HANDLERS[tool_name]
    try:
        output = handler(arguments)
        content = json.dumps(output, ensure_ascii=False)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": content}],
            },
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "ok": False,
                        "tool": tool_name,
                        "error": f"Internal error: {e}",
                        "elapsed_seconds": 0,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False),
                }],
            },
        }


def main():
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"local-llm-mcp-server v{SERVER_VERSION}")
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python tools/local_llm_mcp_server.py [--version]")
        print("")
        print("MCP (Model Context Protocol) server for local LLM pipeline.")
        print("Communicates via stdio JSON-RPC 2.0.")
        print("")
        print("Tools exposed (source-non-mutating; may write only to .local_llm_out/):")
        for name in sorted(TOOLS):
            print(f"  {name}")
        return 0

    print(f"MCP Server '{SERVER_NAME}' v{SERVER_VERSION} starting on stdio", file=sys.stderr)

    try:
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
                write_json_response(handle_initialize(msg_id))
            elif method == "tools/list":
                write_json_response(handle_tools_list(msg_id))
            elif method == "tools/call":
                tool_name = request.get("params", {}).get("name", "unknown")
                start = time.time()
                response = handle_tools_call(msg_id, request.get("params", {}))
                elapsed = round(time.time() - start, 2)
                print(f"  [{elapsed}s] {tool_name}", file=sys.stderr)
                write_json_response(response)
            elif method == "notifications/initialized":
                pass  # ack silently
            else:
                write_json_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })
    except KeyboardInterrupt:
        pass

    print("MCP Server shutting down", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
