"""MCP Auto-Worker — fire-and-forget background LLM task spawning.

Hooks run synchronously inside the Claude process. To avoid blocking user
interaction, LLM invocations are spawned as background subprocesses via Popen.
Results land in .local_llm_out/auto/ and are collected by the Stop hook.

Writes only to .local_llm_out/auto/ — never touches source files.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_DEDUP_WINDOW_SEC = 60
_MAX_WORKERS_PER_SESSION = 10

SCRIPT_DIR = Path(__file__).parent.parent
_ROUTER_PATH = SCRIPT_DIR / "local_llm_router.py"
_CHECK_PATH = SCRIPT_DIR / "local_llm_check.py"


def auto_output_dir(repo_root: str | None = None) -> Path:
    """Return the auto/ subdirectory under .local_llm_out/."""
    if repo_root:
        base = Path(repo_root) / ".local_llm_out"
    else:
        base = Path.cwd() / ".local_llm_out"
    auto_dir = base / "auto"
    auto_dir.mkdir(parents=True, exist_ok=True)
    return auto_dir


def _task_cache_key(task: str, target: str) -> str:
    """Stable dedup key from task type + target identity."""
    return f"auto_{task}:{target}"


def _is_deduped(state: dict, cache_key: str, window_sec: int = _DEDUP_WINDOW_SEC) -> bool:
    """Return True if this task+target was spawned within window_sec."""
    spawned = state.get("_auto_spawned", {})
    last = spawned.get(cache_key)
    if last is None:
        return False
    return (time.time() - last) < window_sec


def _mark_spawned(state: dict, cache_key: str):
    """Record that a task was spawned at the current time."""
    spawned = state.get("_auto_spawned", {})
    spawned[cache_key] = time.time()
    state["_auto_spawned"] = spawned


def _worker_count(state: dict) -> int:
    return state.get("_auto_worker_count", 0)


def _increment_worker_count(state: dict) -> int:
    count = state.get("_auto_worker_count", 0) + 1
    state["_auto_worker_count"] = count
    return count


def spawn_background(cmd: list[str], env: dict | None = None,
                     cwd: str | None = None, stdin_path: str | None = None,
                     log_path: str | None = None):
    """Fire-and-forget subprocess. Never raises, never blocks."""
    try:
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if cwd:
            kwargs["cwd"] = cwd
        if env:
            kwargs["env"] = env

        if stdin_path:
            with open(stdin_path, "r", encoding="utf-8") as f:
                kwargs["stdin"] = f
                subprocess.Popen(cmd, **kwargs)
        else:
            subprocess.Popen(cmd, **kwargs)
    except Exception:
        pass


def spawn_local_check(config_dir: str, repo_root: str | None = None):
    """Fire-and-forget local_check. Writes to .local_llm_out/auto/."""
    auto_dir = auto_output_dir(repo_root)
    log_path = auto_dir / "_local_check.log"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"[{ts}] spawn_local_check\n")
    except OSError:
        pass

    cmd = [
        sys.executable,
        str(_CHECK_PATH),
    ]

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    # Capture output to log file
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=repo_root,
                env=env,
            )
    except Exception:
        pass


def spawn_summarize_file(config_dir: str, file_path: str,
                         repo_root: str | None = None):
    """Fire-and-forget summarize-file for a single file.

    Prefers llama.cpp backend (gemma4_26b_llamacpp) for speed when available.
    Router handles cross-backend fallback if llama.cpp is down.
    """
    auto_dir = auto_output_dir(repo_root)
    log_path = auto_dir / "_summarize.log"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"[{ts}] spawn_summarize_file {file_path}\n")
    except OSError:
        pass

    # Prefer llama.cpp for fast background tasks — router falls back to Ollama
    cmd = [
        sys.executable,
        str(_ROUTER_PATH),
        "summarize-file",
        file_path,
        "--profile", "gemma4_26b_llamacpp",
        "--json-only",
        "--output-dir", str(auto_dir),
    ]

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    spawn_background(cmd, env=env, cwd=repo_root)


def spawn_review_diff(config_dir: str, diff_text: str,
                      repo_root: str | None = None):
    """Fire-and-forget review-diff. Writes diff to temp file for stdin."""
    auto_dir = auto_output_dir(repo_root)
    log_path = auto_dir / "_review.log"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not diff_text.strip():
        return

    stdin_path = auto_dir / f"{ts}_review_stdin.txt"
    try:
        stdin_path.write_text(diff_text, encoding="utf-8")
    except OSError:
        return

    try:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"[{ts}] spawn_review_diff ({len(diff_text)} chars)\n")
    except OSError:
        pass

    cmd = [
        sys.executable,
        str(_ROUTER_PATH),
        "review-diff",
        "--stdin",
        "--commit_gate", "true",
        "--json-only",
        "--output-dir", str(auto_dir),
    ]

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    spawn_background(cmd, env=env, cwd=repo_root, stdin_path=str(stdin_path))


def collect_auto_results(repo_root: str | None = None) -> list[dict]:
    """Scan .local_llm_out/auto/ for JSON result files.

    Returns list of {file, created, data} dicts sorted by creation time.
    """
    auto_dir = auto_output_dir(repo_root)
    if not auto_dir.exists():
        return []

    results = []
    for f in sorted(auto_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "file": str(f),
                "created": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "data": data,
            })
        except (json.JSONDecodeError, OSError):
            continue
    return results


def cleanup_auto_results(repo_root: str | None = None,
                         max_age_hours: int = 24):
    """Remove auto result files older than max_age_hours."""
    auto_dir = auto_output_dir(repo_root)
    if not auto_dir.exists():
        return

    now = time.time()
    for f in auto_dir.iterdir():
        if f.is_file():
            try:
                if (now - f.stat().st_mtime) > max_age_hours * 3600:
                    f.unlink()
            except OSError:
                pass


def needs_auto_summarize(state: dict, file_path: str) -> bool:
    """Check if a file needs background summarization."""
    cache_key = _task_cache_key("summarize", file_path)
    if _is_deduped(state, cache_key):
        return False
    if _worker_count(state) >= _MAX_WORKERS_PER_SESSION:
        return False
    return True


def needs_auto_review(state: dict) -> bool:
    """Check if we should spawn a background review."""
    cache_key = "auto_review:self"
    if _is_deduped(state, cache_key, window_sec=120):
        return False
    if _worker_count(state) >= _MAX_WORKERS_PER_SESSION:
        return False
    return True


def mark_auto_summarize(state: dict, file_path: str):
    """Mark a summarize as spawned."""
    cache_key = _task_cache_key("summarize", file_path)
    _mark_spawned(state, cache_key)
    _increment_worker_count(state)


def mark_auto_review(state: dict):
    """Mark a review as spawned."""
    _mark_spawned(state, "auto_review:self")
    _increment_worker_count(state)
