"""End-to-end MCP stdio handshake test for the local-llm server."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SERVER_CMD = [sys.executable, str(PROJECT_ROOT / "tools" / "local_llm_mcp_server.py")]


def _send(stdin, msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)
    stdin.write(line.encode("utf-8") + b"\n")
    stdin.flush()


def _recv(stdout, timeout: float = 10.0) -> dict:
    stdout.timeout = timeout
    line = stdout.readline()
    if not line:
        raise TimeoutError("No response from MCP server")
    return json.loads(line.decode("utf-8"))


@pytest.fixture
def server():
    proc = subprocess.Popen(
        SERVER_CMD,
        cwd=str(PROJECT_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        yield proc
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_initialize(server):
    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    })
    resp = _recv(server.stdout)
    assert resp.get("id") == 1
    assert "result" in resp
    assert resp["result"].get("protocolVersion") == "2024-11-05"
    assert "tools" in resp["result"].get("capabilities", {})
    server_name = resp["result"].get("serverInfo", {}).get("name")
    assert "local-llm" in server_name


def test_tools_list(server):
    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    })
    _recv(server.stdout)

    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    })
    resp = _recv(server.stdout)
    assert resp.get("id") == 2
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "local_route_explain" in names
    assert "local_check" in names
    assert "local_review_diff" in names


def test_tools_call_route_explain(server):
    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    })
    _recv(server.stdout)

    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "local_route_explain",
            "arguments": {"task": "review current diff"},
        },
    })
    resp = _recv(server.stdout, timeout=30)
    assert resp.get("id") == 3
    assert "result" in resp
    content = resp["result"]["content"]
    assert len(content) >= 1
    text = content[0]["text"]
    data = json.loads(text)
    assert data["ok"] is True
    assert data["task_type"] == "review-diff"
    assert data["advisory_only"] is True
    assert "cloud_allowed" in data
