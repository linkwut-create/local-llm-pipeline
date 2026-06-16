"""Manual validation script for the local MCP servers.

Usage:
    python scripts/validate_mcp_servers.py

The script starts each server, performs an initialize/tools-list handshake,
calls a harmless tool, prints OK/FAIL per server, and exits with a non-zero
status if any server fails.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

LOCAL_LLM_ROOT = Path(__file__).parent.parent.resolve()
LOCAL_RAG_ROOT = LOCAL_LLM_ROOT.parent / "local-rag-core"


def send(stdin, msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)
    stdin.write(line.encode("utf-8") + b"\n")
    stdin.flush()


def recv(stdout, timeout: float = 30.0) -> dict:
    import threading

    result = {}

    def _read():
        try:
            while True:
                line = stdout.readline()
                if not line:
                    result["exc"] = TimeoutError("No response from server")
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if text and text.startswith("{"):
                    try:
                        result["resp"] = json.loads(text)
                        return
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            result["exc"] = exc

    t = threading.Thread(target=_read)
    t.daemon = True
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError("No complete response from server")
    if "exc" in result:
        raise result["exc"]
    return result["resp"]


def _spawn(cmd, cwd):
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _teardown(proc):
    if proc.stdin:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _handshake(proc):
    send(proc.stdin, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "validate_mcp_servers", "version": "1.0"},
        },
    })
    init_resp = recv(proc.stdout)
    assert init_resp.get("id") == 1 and "result" in init_resp, "initialize failed"

    send(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    list_resp = recv(proc.stdout)
    assert list_resp.get("id") == 2 and "result" in list_resp, "tools/list failed"
    return list_resp["result"]["tools"]


def validate_local_llm() -> bool:
    print("[local-llm] Starting ...")
    cmd = [sys.executable, str(LOCAL_LLM_ROOT / "tools" / "local_llm_mcp_server.py")]
    proc = _spawn(cmd, LOCAL_LLM_ROOT)
    try:
        tools = _handshake(proc)
        names = {t["name"] for t in tools}
        assert "local_route_explain" in names, "missing local_route_explain"

        # Use a task that the heuristic classifier recognizes, so the response
        # is fast and does not fall back to model calls.
        send(proc.stdin, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "local_route_explain",
                "arguments": {"task": "review current diff"},
            },
        })
        resp = recv(proc.stdout)
        assert resp.get("id") == 3 and "result" in resp, "tools/call failed"
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert data.get("ok") is True, f"route_explain ok=False: {data}"
        print("[local-llm] OK")
        return True
    except Exception as exc:
        print(f"[local-llm] FAIL: {exc}")
        return False
    finally:
        _teardown(proc)


def validate_global_launcher() -> bool:
    print("[global-launcher] Starting ...")
    import tempfile
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="validate-global-launcher-"))
    try:
        subprocess.run(["git", "init"], cwd=str(tmp), check=True, capture_output=True)
        (tmp / "README.md").write_text("# validate\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"], cwd=str(tmp), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp), check=True, capture_output=True
        )
        cmd = [sys.executable, str(LOCAL_LLM_ROOT / "tools" / "local_llm_global_mcp_launcher.py")]
        proc = _spawn(cmd, tmp)
        try:
            tools = _handshake(proc)
            names = {t["name"] for t in tools}
            assert "local_route_explain" in names, "missing local_route_explain"
            print("[global-launcher] OK")
            return True
        except Exception as exc:
            print(f"[global-launcher] FAIL: {exc}")
            return False
        finally:
            _teardown(proc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def validate_local_rag_core() -> bool:
    print("[local-rag-core] Starting ...")
    server_path = LOCAL_RAG_ROOT / "src" / "local_rag_core" / "interfaces" / "mcp_server.py"
    if not server_path.exists():
        print("[local-rag-core] SKIP: server not present")
        return True
    cmd = [sys.executable, "-m", "local_rag_core.interfaces.mcp_server"]
    proc = _spawn(cmd, LOCAL_RAG_ROOT)
    try:
        tools = _handshake(proc)
        names = {t["name"] for t in tools}
        assert "kb.health" in names, "missing kb.health"

        send(proc.stdin, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "kb.health", "arguments": {}},
        })
        resp = recv(proc.stdout)
        assert resp.get("id") == 3 and "result" in resp, "tools/call failed"
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert data.get("status") == "OK", f"kb.health not OK: {data}"
        print("[local-rag-core] OK")
        return True
    except Exception as exc:
        print(f"[local-rag-core] FAIL: {exc}")
        return False
    finally:
        _teardown(proc)


def main() -> int:
    results = {
        "local-llm": validate_local_llm(),
        "global-launcher": validate_global_launcher(),
        "local-rag-core": validate_local_rag_core(),
    }
    ok = all(results.values())
    print("-" * 40)
    print("SUMMARY:")
    for name, passed in results.items():
        print(f"  {name}: {'OK' if passed else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
