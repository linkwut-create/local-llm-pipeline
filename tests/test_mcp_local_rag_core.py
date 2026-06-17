"""End-to-end MCP stdio handshake test for the local-rag-core server."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

try:
    import mcp  # noqa: F401
except ModuleNotFoundError:
    pytest.skip(
        "mcp package not installed; local-rag-core tests skipped",
        allow_module_level=True,
    )

RAG_CORE_ROOT = Path(__file__).parent.parent.parent / "local-rag-core"
SERVER_CMD = [sys.executable, "-m", "local_rag_core.interfaces.mcp_server"]


def _send(stdin, msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)
    stdin.write(line.encode("utf-8") + b"\n")
    stdin.flush()


def _recv(stdout, timeout: float = 10.0) -> dict:
    import os
    if hasattr(os, "set_blocking"):
        os.set_blocking(stdout.fileno(), False)
    start = time.time()
    line = b""
    while not line.endswith(b"\n"):
        chunk = stdout.read(1)
        if chunk:
            line += chunk
        elif time.time() - start > timeout:
            raise TimeoutError("No complete response from rag server")
    return json.loads(line.decode("utf-8"))


@pytest.fixture
def server():
    if not (RAG_CORE_ROOT / "src" / "local_rag_core" / "interfaces" / "mcp_server.py").exists():
        pytest.skip("local-rag-core server not present")
    proc = subprocess.Popen(
        SERVER_CMD,
        cwd=str(RAG_CORE_ROOT),
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
    resp = _recv(server.stdout, timeout=30)
    assert resp.get("id") == 1
    assert "result" in resp
    assert resp["result"].get("protocolVersion") == "2024-11-05"
    assert resp["result"].get("serverInfo", {}).get("name") == "local-rag-core"


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
    _recv(server.stdout, timeout=30)

    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    })
    resp = _recv(server.stdout, timeout=30)
    assert resp.get("id") == 2
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "kb.health" in names
    assert "kb.list_packs" in names
    assert "kb.search" in names
    assert "kb.get_chunk" in names


def test_kb_health(server):
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
    _recv(server.stdout, timeout=30)

    _send(server.stdin, {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "kb.health",
            "arguments": {},
        },
    })
    resp = _recv(server.stdout, timeout=30)
    assert resp.get("id") == 3
    assert "result" in resp
    content = resp["result"]["content"]
    assert len(content) >= 1
    text = content[0]["text"]
    data = json.loads(text)
    assert data.get("status") == "OK"
    assert "db_path" in data
    assert "registered_packs" in data
    assert "indexed_chunks" in data
