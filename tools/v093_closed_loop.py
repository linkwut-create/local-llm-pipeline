#!/usr/bin/env python3
"""v0.9.3 closed-loop regression driver.

Spawns the MCP server, drives the same 8-step heavy-work sequence that v0.9.2
failed on, and reports per-step success plus end-state liveness. This is a
one-shot dev script, not a unit test — it actually contacts Ollama.

Usage:
    python tools/v093_closed_loop.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "tools" / "local_llm_mcp_server.py"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def send(proc: subprocess.Popen, msg: dict, *, expect_response: bool = True) -> dict | None:
    line = json.dumps(msg, ensure_ascii=False) + "\n"
    method = msg.get("method", "?")
    msg_id = msg.get("id", "<notif>")
    _log(f"  >>> [{msg_id}] {method}")
    proc.stdin.write(line)
    proc.stdin.flush()
    if not expect_response:
        return None
    raw = proc.stdout.readline()
    if not raw:
        _log(f"  <<< [{msg_id}] {method} — EOF / no response")
        return None
    _log(f"  <<< [{msg_id}] {method} — {len(raw)} bytes")
    return json.loads(raw)


def call_tool(proc: subprocess.Popen, msg_id: int, name: str, arguments: dict,
              label: str) -> dict:
    t0 = time.time()
    response = send(proc, {
        "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    elapsed = time.time() - t0
    if response is None:
        return {"label": label, "ok": False, "elapsed": elapsed,
                "error": "no response — server disconnected"}
    try:
        content = json.loads(response["result"]["content"][0]["text"])
    except Exception as exc:
        return {"label": label, "ok": False, "elapsed": elapsed,
                "error": f"malformed response: {exc}", "raw": response}
    return {
        "label": label,
        "ok": content.get("ok", False),
        "elapsed": elapsed,
        "error_type": content.get("error_type"),
        "error": content.get("error"),
        "prompt_id": content.get("prompt_id"),
        "prompt_version": content.get("prompt_version"),
        "prompt_hash": content.get("prompt_hash"),
        "cache_hit": content.get("cache_hit", False),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-heavy", action="store_true",
                    help="only run local_check + tools/list + a fast review-diff fake")
    args = ap.parse_args()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env, cwd=str(ROOT),
    )

    results: list[dict] = []
    try:
        _log("driver: server PID=" + str(proc.pid))
        # 1. initialize
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05",
                               "clientInfo": {"name": "v093-driver", "version": "0.0.1"},
                               "capabilities": {}}})
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"},
             expect_response=False)

        # 2. tools/list
        tools_resp = send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools_listed = [t["name"] for t in tools_resp["result"]["tools"]]
        results.append({"label": "tools/list", "ok": len(tools_listed) == 7,
                        "tools": tools_listed})

        # 3. local_check
        results.append(call_tool(proc, 3, "local_check", {}, "local_check"))

        if not args.skip_heavy:
            # 4. summarize_tree on services/
            results.append(call_tool(proc, 4, "local_summarize_tree",
                                     {"path": "services", "max_files": 6},
                                     "summarize_tree services"))
            # 5. summarize_file app.py
            results.append(call_tool(proc, 5, "local_summarize_file",
                                     {"path": "app.py"},
                                     "summarize_file app.py"))
            # 6. summarize_file services/subtitle_service.py
            results.append(call_tool(proc, 6, "local_summarize_file",
                                     {"path": "services/subtitle_service.py"},
                                     "summarize_file subtitle_service.py"))
            # 7. generate_test_plan
            results.append(call_tool(proc, 7, "local_generate_test_plan",
                                     {"path": "services/file_io.py"},
                                     "generate_test_plan file_io.py"))
            # 8. draft_code (writes only to .local_llm_out/)
            results.append(call_tool(proc, 8, "local_draft_code", {
                "task": "draft-fix",
                "prompt": "Add threading.Lock around _active_jobs and _cancel_flags.",
                "context_file": "app.py",
            }, "draft_code threading-lock"))
            # 9. review_diff (small fake diff)
            results.append(call_tool(proc, 9, "local_review_diff", {
                "diff_text": (
                    "diff --git a/app.py b/app.py\n"
                    "@@ -1,3 +1,5 @@\n"
                    "+import threading\n"
                    "+_jobs_lock = threading.Lock()\n"
                    " _active_jobs = {}\n"
                ),
            }, "review_diff fake"))

        # 10. liveness probe — list tools again, must still respond
        live_resp = send(proc, {"jsonrpc": "2.0", "id": 99, "method": "tools/list"})
        results.append({"label": "post-loop tools/list",
                        "ok": live_resp is not None and "result" in live_resp})
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))

    failed = [r for r in results if not r.get("ok")]
    if failed:
        print(f"\nFAILED steps: {[r['label'] for r in failed]}", file=sys.stderr)
        return 1
    print("\nALL STEPS OK — server stayed alive throughout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
