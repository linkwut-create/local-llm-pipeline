"""End-to-end test for the global MCP launcher project detection."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).parent.parent / "tools" / "local_llm_global_mcp_launcher.py"


def _send(stdin, msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)
    stdin.write(line.encode("utf-8") + b"\n")
    stdin.flush()


def _recv(stdout, timeout: float = 10.0) -> dict:
    import os
    import threading

    result = {}

    def _read():
        try:
            # Buffering can combine stderr/stdout on some Windows pipe setups; use
            # errors='replace' so stray non-UTF-8 bytes (e.g. GBK locale messages)
            # do not crash the test. Then split the stream into JSON-RPC lines.
            text_stream = os.fdopen(stdout.fileno(), "r", encoding="utf-8", errors="replace", closefd=False)
            line = text_stream.readline()
            if not line:
                result["exc"] = TimeoutError("No response from launcher")
                return
            line = line.strip()
            # The global launcher may emit log banners or empty lines; skip them.
            while line and not line.startswith("{"):
                line = text_stream.readline().strip()
                if not line:
                    result["exc"] = TimeoutError("No JSON response from launcher")
                    return
            result["resp"] = json.loads(line)
        except Exception as exc:
            result["exc"] = exc

    t = threading.Thread(target=_read)
    t.daemon = True
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError("No complete response from launcher")
    if "exc" in result:
        raise result["exc"]
    return result["resp"]


import os
import shutil
import tempfile
import threading
import time


@pytest.fixture
def git_project(tmp_path):
    project = tmp_path / "fake-project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=str(project), check=True, capture_output=True)
    (project / "README.md").write_text("# fake\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=str(project), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(project), check=True, capture_output=True,
    )
    return project


def test_launcher_detects_target_project(git_project):
    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER)],
        cwd=str(git_project),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _send(proc.stdin, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        })
        resp = _recv(proc.stdout, timeout=30)
        assert resp.get("id") == 1
        assert "result" in resp

        _send(proc.stdin, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        resp = _recv(proc.stdout, timeout=30)
        assert resp.get("id") == 2
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "local_route_explain" in names

        # Check stderr banner names the target project.
        stderr = proc.stderr.read1(4096).decode("utf-8", errors="replace")
        assert str(git_project) in stderr or "fake-project" in stderr
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_launcher_outside_git_repo():
    # The system TEMP directory lives under C:\Users\Zero, which contains a
    # .git directory in this environment. Use the project's parent directory
    # to ensure the launcher genuinely sees no git repository.
    base = Path(__file__).resolve().parent.parent.parent
    tmp = tempfile.mkdtemp(dir=base)
    proc = subprocess.Popen(
        [sys.executable, str(LAUNCHER)],
        cwd=tmp,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _send(proc.stdin, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        })
        resp = _recv(proc.stdout, timeout=10)
        assert resp.get("id") in (0, 1)
        assert "result" in resp
        content = resp["result"]["content"]
        text = content[0]["text"]
        data = json.loads(text)
        assert data.get("error_type") == "no_git_repository"
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)
