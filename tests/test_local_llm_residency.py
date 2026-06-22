"""Tests for tools/local_llm_residency.py"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import local_llm_residency as residency


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Keep residency state inside a temp directory for every test."""
    monkeypatch.setenv("LOCAL_LLM_RESIDENCY_DIR", str(tmp_path / "residency"))
    monkeypatch.setattr(residency, "DEFAULT_MODELS", ["test-model"])
    yield
    # Best-effort cleanup of any stale state
    sf = residency._state_file()
    if sf.exists():
        try:
            sf.unlink()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Model / keepalive resolution
# --------------------------------------------------------------------------- #

def test_resolve_models_from_args():
    args = SimpleNamespace(models="a:7b,b:13b", force=False)
    assert residency._resolve_models(args.models) == ["a:7b", "b:13b"]


def test_resolve_models_from_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_RESIDENT_MODELS", "x:1b,y:2b")
    assert residency._resolve_models(None) == ["x:1b", "y:2b"]


def test_resolve_models_defaults_to_default_list():
    assert residency._resolve_models(None) == ["test-model"]


def test_resolve_keep_alive_default():
    args = SimpleNamespace(force=False)
    assert residency._resolve_keep_alive(args.force) == "30m"


def test_resolve_keep_alive_force():
    args = SimpleNamespace(force=True)
    assert residency._resolve_keep_alive(args.force) == "-1"


def test_resolve_keep_alive_env_override(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_KEEP_ALIVE", "2h")
    args = SimpleNamespace(force=False)
    assert residency._resolve_keep_alive(args.force) == "2h"


def test_resolve_keep_alive_force_env_wins(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_RESIDENCY_FORCE", "true")
    args = SimpleNamespace(force=False)
    assert residency._resolve_keep_alive(args.force) == "-1"


def test_resolve_interval_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_RESIDENCY_INTERVAL", "120")
    assert residency._resolve_interval() == 120


def test_resolve_interval_invalid_env_fallback():
    assert residency._resolve_interval() == 60


# --------------------------------------------------------------------------- #
# Ollama keepalive ping
# --------------------------------------------------------------------------- #

def test_send_keepalive_success(monkeypatch):
    calls = []

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResp()

    monkeypatch.setattr(residency.requests, "post", fake_post)
    result = residency._send_keepalive("mymodel", "45m", base_url="http://ollama:11434")

    assert result["ok"] is True
    assert result["model"] == "mymodel"
    assert result["keep_alive"] == "45m"
    assert len(calls) == 1
    assert calls[0][0] == "http://ollama:11434/api/generate"
    assert calls[0][1]["model"] == "mymodel"
    assert calls[0][1]["keep_alive"] == "45m"
    assert calls[0][1]["stream"] is False
    assert calls[0][2] == 30


def test_send_keepalive_normalizes_force_keep_alive(monkeypatch):
    calls = []

    class FakeResp:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        residency.requests,
        "post",
        lambda url, json, timeout: calls.append(json) or FakeResp(),
    )
    result = residency._send_keepalive(
        "mymodel", "-1", base_url="http://ollama:11434"
    )

    assert result["ok"] is True
    assert calls[0]["keep_alive"] == -1


def test_send_keepalive_failure(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(residency.requests, "post", fake_post)
    result = residency._send_keepalive("mymodel", "30m")
    assert result["ok"] is False
    assert "connection refused" in result["error"]


def test_unload_model_sends_zero_keepalive(monkeypatch):
    calls = []

    class FakeResp:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(residency.requests, "post", lambda url, json, timeout: calls.append(json) or FakeResp())
    residency._unload_model("mymodel")
    assert len(calls) == 1
    assert calls[0]["keep_alive"] == 0


# --------------------------------------------------------------------------- #
# Daemon / CLI
# --------------------------------------------------------------------------- #

def test_cmd_start_spawns_daemon_and_writes_state(monkeypatch, tmp_path):
    captured = {}

    class FakeProc:
        pid = 12345

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(residency, "_is_process_alive", lambda pid: False)

    args = SimpleNamespace(models="a:7b,b:13b", force=True)
    rc = residency.cmd_start(args)
    assert rc == 0

    # The daemon writes state in a separate process normally; here we simulate it
    # by writing the state our fixture expects.
    residency._save_state({
        "pid": 12345,
        "models": ["a:7b", "b:13b"],
        "keep_alive": "-1",
        "interval": 60,
        "started_at": "now",
        "last_ping": None,
        "force": True,
    })

    state = residency._load_state()
    assert state["pid"] == 12345
    assert state["models"] == ["a:7b", "b:13b"]
    assert state["keep_alive"] == "-1"


def test_cmd_start_reports_existing_daemon(monkeypatch, capsys):
    residency._save_state({
        "pid": 111,
        "models": ["x"],
        "keep_alive": "30m",
        "interval": 60,
        "started_at": "now",
        "last_ping": None,
    })
    monkeypatch.setattr(residency, "_is_process_alive", lambda pid: True)

    args = SimpleNamespace(models=None, force=False)
    rc = residency.cmd_start(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "already running" in captured.err


def test_cmd_stop_terminates_and_clears_state(monkeypatch):
    residency._save_state({
        "pid": 222,
        "models": ["m1", "m2"],
        "keep_alive": "30m",
        "interval": 60,
        "started_at": "now",
        "last_ping": None,
    })
    terminated = []
    monkeypatch.setattr(residency, "_is_process_alive", lambda pid: True)
    monkeypatch.setattr(residency, "_terminate_process", lambda pid: terminated.append(pid) or True)

    args = SimpleNamespace(force=False)
    rc = residency.cmd_stop(args)
    assert rc == 0
    assert terminated == [222]
    assert residency._load_state() is None


def test_cmd_stop_force_unloads_models(monkeypatch):
    residency._save_state({
        "pid": 333,
        "models": ["m1"],
        "keep_alive": "-1",
        "interval": 60,
        "started_at": "now",
        "last_ping": None,
    })
    unloads = []
    monkeypatch.setattr(residency, "_is_process_alive", lambda pid: True)
    monkeypatch.setattr(residency, "_terminate_process", lambda pid: True)
    monkeypatch.setattr(residency, "_unload_model", lambda model, base_url=None: unloads.append(model) or {"ok": True})

    args = SimpleNamespace(force=True)
    rc = residency.cmd_stop(args)
    assert rc == 0
    assert unloads == ["m1"]


def test_cmd_status_running(monkeypatch, capsys):
    residency._save_state({
        "pid": 444,
        "models": ["m1", "m2"],
        "keep_alive": "30m",
        "interval": 60,
        "started_at": "2026-06-16T12:00:00",
        "last_ping": "2026-06-16T12:01:00",
    })
    monkeypatch.setattr(residency, "_is_process_alive", lambda pid: True)
    residency.cmd_status(SimpleNamespace())
    captured = capsys.readouterr()
    assert "running" in captured.out
    assert "444" in captured.out
    assert "m1, m2" in captured.out


def test_is_residency_active_and_get_resident_models(monkeypatch):
    residency._save_state({
        "pid": 555,
        "models": ["m1"],
        "keep_alive": "30m",
        "interval": 60,
        "started_at": "now",
        "last_ping": None,
    })
    monkeypatch.setattr(residency, "_is_process_alive", lambda pid: True)
    assert residency.is_residency_active() is True
    assert residency.get_resident_models() == ["m1"]


# --------------------------------------------------------------------------- #
# Worker integration
# --------------------------------------------------------------------------- #

import local_llm_worker as worker


def test_worker_call_ollama_includes_keep_alive_env(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_KEEP_ALIVE", "1h")
    captured = {}

    class FakeResult:
        content = "ok"
        usage = None

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    def fake_post(url, json, timeout, **kwargs):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(worker.requests, "post", fake_post)

    config = worker.WorkerConfig(
        provider="ollama",
        model="test",
        base_url="http://localhost:11434",
        timeout=120,
        max_output_chars=100,
    )
    result = worker.call_ollama("system", "user", config)
    assert captured["payload"]["keep_alive"] == "1h"
    assert result.content == "ok"


def test_worker_call_ollama_normalizes_force_keep_alive(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_KEEP_ALIVE", "-1")
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    def fake_post(url, json, timeout, **kwargs):
        captured["payload"] = json
        return FakeResp()

    monkeypatch.setattr(worker.requests, "post", fake_post)

    config = worker.WorkerConfig(
        provider="ollama",
        model="test",
        base_url="http://localhost:11434",
        timeout=120,
        max_output_chars=100,
    )
    worker.call_ollama("system", "user", config)
    assert captured["payload"]["keep_alive"] == -1


def test_worker_call_ollama_omits_keep_alive_without_env(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_KEEP_ALIVE", raising=False)
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(worker.requests, "post", lambda url, json, timeout, **kwargs: captured.update({"payload": json}) or FakeResp())

    config = worker.WorkerConfig(
        provider="ollama",
        model="test",
        base_url="http://localhost:11434",
        timeout=120,
        max_output_chars=100,
    )
    worker.call_ollama("system", "user", config)
    assert "keep_alive" not in captured["payload"]


def test_worker_resolve_config_reads_local_llm_request_timeout(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_REQUEST_TIMEOUT", "900")
    args = SimpleNamespace(
        task="summarize-file",
        provider=None,
        model=None,
        profile=None,
        base_url=None,
        timeout=None,
        max_chars=None,
        max_output_chars=None,
        output_dir=None,
        target_language=None,
        style=None,
        json_only=False,
        no_markdown=False,
    )
    config = worker.resolve_config(args)
    assert config.timeout == 900


def test_worker_resolve_config_request_timeout_overrides_arg(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_REQUEST_TIMEOUT", "600")
    args = SimpleNamespace(
        task="summarize-file",
        provider=None,
        model=None,
        profile=None,
        base_url=None,
        timeout=30,
        max_chars=None,
        max_output_chars=None,
        output_dir=None,
        target_language=None,
        style=None,
        json_only=False,
        no_markdown=False,
    )
    config = worker.resolve_config(args)
    assert config.timeout == 600
