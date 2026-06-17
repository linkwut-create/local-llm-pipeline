#!/usr/bin/env python3
"""Local LLM Session Residency — keep development models resident during a Claude Code session.

This is a global workflow module: it can be invoked from any project directory
and is not tied to the local-llm-pipeline repository's own development.

Usage:
    # Start keeping models warm (default 30m keepalive, ping every 60s)
    py -3 /path/to/local_llm_residency.py start

    # Force permanent residency until explicit stop
    py -3 /path/to/local_llm_residency.py start --force

    # Check status
    py -3 /path/to/local_llm_residency.py status

    # Stop and return to default Ollama behavior
    py -3 /path/to/local_llm_residency.py stop

    # Stop and force immediate unload
    py -3 /path/to/local_llm_residency.py stop --force

Environment variables:
    LOCAL_LLM_RESIDENT_MODELS   comma-separated model names
    LOCAL_LLM_KEEP_ALIVE        duration string, e.g. 30m, 2h, -1
    LOCAL_LLM_RESIDENCY_INTERVAL seconds between keepalive pings
    OLLAMA_HOST                 Ollama endpoint (default http://localhost:11434)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Defaults
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_MODELS = ["qwen3.6:27b", "nemotron:30b", "gemma4:31b-unsloth"]
DEFAULT_KEEP_ALIVE = "30m"
DEFAULT_INTERVAL = 60
DEFAULT_OLLAMA_HOST = "http://localhost:11434"


# ═══════════════════════════════════════════════════════════════════════════════
# State persistence
# ═══════════════════════════════════════════════════════════════════════════════

def _state_dir() -> Path:
    """Global state directory for residency (not tied to any project)."""
    env = os.environ.get("LOCAL_LLM_RESIDENCY_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".local_llm_residency"


def _state_file() -> Path:
    return _state_dir() / "state.json"


def _load_state() -> dict[str, Any] | None:
    sf = _state_file()
    if not sf.exists():
        return None
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "pid" in data:
            return data
    except Exception:
        pass
    return None


def _save_state(state: dict[str, Any]) -> None:
    sd = _state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    sf = _state_file()
    sf.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _clear_state() -> None:
    sf = _state_file()
    if sf.exists():
        try:
            sf.unlink()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Process helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _is_process_alive(pid: int) -> bool:
    """Cross-platform lightweight process-alive check."""
    if sys.platform == "win32":
        try:
            import ctypes
        except ImportError:
            return False
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def _terminate_process(pid: int) -> bool:
    """Cross-platform terminate. Returns True if successful."""
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait briefly, escalate to SIGKILL if needed
        for _ in range(20):
            if not _is_process_alive(pid):
                return True
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Ollama helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _ollama_base_url() -> str:
    """Resolve Ollama endpoint, mirroring local_llm_worker logic."""
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if host:
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return host.rstrip("/")
    return DEFAULT_OLLAMA_HOST


def _send_keepalive(model: str, keep_alive: str, base_url: str | None = None) -> dict[str, Any]:
    """Ping a model to keep it loaded. Returns {ok, model, keep_alive, error}."""
    base = (base_url or _ollama_base_url()).rstrip("/")
    url = f"{base}/api/generate"
    payload = {
        "model": model,
        "prompt": " ",
        "stream": False,
        "options": {"num_predict": 1, "temperature": 0.0},
        "keep_alive": keep_alive,
    }
    try:
        if requests is not None:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            return {"ok": True, "model": model, "keep_alive": keep_alive, "error": None}
        # Fallback to urllib
        import urllib.request as _ur
        data = json.dumps(payload).encode("utf-8")
        req = _ur.Request(url, data=data, headers={"Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"ok": True, "model": model, "keep_alive": keep_alive, "error": None}
    except Exception as exc:
        return {"ok": False, "model": model, "keep_alive": keep_alive, "error": str(exc)}


def _unload_model(model: str, base_url: str | None = None) -> dict[str, Any]:
    """Force a model to unload by sending keep_alive=0."""
    return _send_keepalive(model, "0", base_url=base_url)


# ═══════════════════════════════════════════════════════════════════════════════
# Daemon loop
# ═══════════════════════════════════════════════════════════════════════════════

def _daemon_loop(models: list[str], keep_alive: str, interval: int) -> None:
    """Background keepalive loop. Never returns."""
    state = {
        "pid": os.getpid(),
        "models": models,
        "keep_alive": keep_alive,
        "interval": interval,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_ping": None,
        "force": keep_alive == "-1",
        "state_dir": str(_state_dir()),
    }
    _save_state(state)

    while True:
        results = []
        for model in models:
            result = _send_keepalive(model, keep_alive)
            results.append(result)

        state["last_ping"] = datetime.now(timezone.utc).isoformat()
        state["last_results"] = results
        _save_state(state)

        # If every ping failed with connection error, back off but keep trying.
        all_failed = all(not r["ok"] for r in results)
        sleep_interval = interval * 2 if all_failed else interval
        time.sleep(max(sleep_interval, 5))


# ═══════════════════════════════════════════════════════════════════════════════
# CLI commands
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_models(args_models: list[str] | None) -> list[str]:
    """Resolve resident models from CLI args or env."""
    if args_models:
        if isinstance(args_models, str):
            return [m.strip() for m in args_models.split(",") if m.strip()]
        return [m.strip() for m in args_models if m.strip()]
    env = os.environ.get("LOCAL_LLM_RESIDENT_MODELS", "")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    return DEFAULT_MODELS


def _resolve_keep_alive(args_force: bool) -> str:
    """Resolve keep_alive value."""
    if args_force or os.environ.get("LOCAL_LLM_RESIDENCY_FORCE", "").lower() in ("1", "true", "yes", "on"):
        return "-1"
    return os.environ.get("LOCAL_LLM_KEEP_ALIVE", DEFAULT_KEEP_ALIVE).strip() or DEFAULT_KEEP_ALIVE


def _resolve_interval() -> int:
    env = os.environ.get("LOCAL_LLM_RESIDENCY_INTERVAL", "")
    if env:
        try:
            return max(5, int(env))
        except ValueError:
            pass
    return DEFAULT_INTERVAL


def cmd_start(args: argparse.Namespace) -> int:
    """Start the residency daemon."""
    state = _load_state()
    if state and _is_process_alive(state.get("pid", 0)):
        print(f"Residency already running (pid {state['pid']}).", file=sys.stderr)
        cmd_status(args)
        return 0

    models = _resolve_models(args.models)
    keep_alive = _resolve_keep_alive(args.force)
    interval = _resolve_interval()

    # Clear any stale state before starting
    _clear_state()

    # Prepare the daemon command: same script, internal --daemon flag
    daemon_args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "__daemon__",
        "--models",
        ",".join(models),
        "--keep-alive",
        keep_alive,
        "--interval",
        str(interval),
    ]

    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True

    log_path = _daemon_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")
    kwargs["stdin"] = subprocess.DEVNULL
    kwargs["stdout"] = log_file
    kwargs["stderr"] = subprocess.STDOUT

    try:
        proc = subprocess.Popen(daemon_args, **kwargs)
    except Exception as exc:
        log_file.close()
        print(f"ERROR: failed to start residency daemon: {exc}", file=sys.stderr)
        return 1
    finally:
        # The child process received its own duplicate of the log handle.
        try:
            log_file.close()
        except Exception:
            pass

    # Wait a moment for the daemon to write its state file
    for _ in range(30):
        time.sleep(0.1)
        state = _load_state()
        if state and state.get("pid") == proc.pid:
            break

    print(f"Started residency daemon (pid {proc.pid}).")
    print(f"Models: {', '.join(models)}")
    print(f"Keep-alive: {keep_alive}")
    print(f"Ping interval: {interval}s")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop the residency daemon."""
    state = _load_state()
    if not state:
        print("No residency daemon is running.", file=sys.stderr)
        return 0

    pid = state.get("pid", 0)
    models = state.get("models", [])
    alive = _is_process_alive(pid)

    if alive:
        if args.force:
            print(f"Stopping daemon (pid {pid}) and forcing unload for {len(models)} model(s)...")
            for model in models:
                result = _unload_model(model)
                if not result["ok"]:
                    print(f"  unload warning for {model}: {result['error']}", file=sys.stderr)
        else:
            print(f"Stopping daemon (pid {pid}); models will follow Ollama's default keepalive.")
        _terminate_process(pid)
    else:
        print(f"Daemon pid {pid} is not running; cleaning up stale state.")

    _clear_state()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show residency status."""
    state = _load_state()
    if not state:
        print("Residency: not running")
        return 0

    pid = state.get("pid", 0)
    alive = _is_process_alive(pid)
    status = "running" if alive else "stopped (stale state)"
    print(f"Residency: {status}")
    print(f"  pid:        {pid}")
    print(f"  models:     {', '.join(state.get('models', []))}")
    print(f"  keep_alive: {state.get('keep_alive', 'unknown')}")
    print(f"  interval:   {state.get('interval', 'unknown')}s")
    print(f"  started:    {state.get('started_at', 'unknown')}")
    print(f"  last_ping:  {state.get('last_ping', 'never')}")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Internal entry point for the background daemon."""
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    keep_alive = args.keep_alive or DEFAULT_KEEP_ALIVE
    interval = max(5, int(args.interval or DEFAULT_INTERVAL))
    _daemon_loop(models, keep_alive, interval)
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
# Public helpers for integration
# ═══════════════════════════════════════════════════════════════════════════════

def is_residency_active() -> bool:
    """Return True if the residency daemon is currently running."""
    state = _load_state()
    if not state:
        return False
    return _is_process_alive(state.get("pid", 0))


def get_resident_models() -> list[str]:
    """Return the list of models currently being kept resident."""
    state = _load_state()
    if not state:
        return []
    return state.get("models", [])


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Keep local LLM models resident during a Claude Code session"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start keeping models resident")
    start.add_argument("--models", default=None, help="Comma-separated model names")
    start.add_argument("--force", action="store_true", help="Keep resident until explicit stop (keep_alive=-1)")

    stop = subparsers.add_parser("stop", help="Stop residency and return to default Ollama behavior")
    stop.add_argument("--force", action="store_true", help="Also force unload models now")

    subparsers.add_parser("status", help="Show residency status")

    # Hidden internal daemon command
    daemon = subparsers.add_parser("__daemon__", help=argparse.SUPPRESS)
    daemon.add_argument("--models", default="")
    daemon.add_argument("--keep-alive", default=DEFAULT_KEEP_ALIVE)
    daemon.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)

    return parser


def _daemon_log_path() -> Path:
    return _state_dir() / "daemon.log"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        return cmd_start(args)
    if args.command == "stop":
        return cmd_stop(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "__daemon__":
        return cmd_daemon(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
