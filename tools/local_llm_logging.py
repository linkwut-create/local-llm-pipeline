#!/usr/bin/env python3
"""
Metadata-only structured JSONL logging for local LLM calls.

Logs only operational metadata: never prompt, response, file content,
diff content, secrets, or API keys. Writes to .local_llm_out/logs/.

Controlled by LOCAL_LLM_LOG env var (default: enabled).
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(".local_llm_out") / "logs"
LOG_FILE = LOG_DIR / "local_llm.jsonl"

REDACTED_MARKER = "[REDACTED]"

# Fields that are always safe to log. Prompt-registry metadata (prompt_id /
# version / hash) is structural metadata, never the prompt body itself, so it
# is safe to record. The body is never logged.
SAFE_FIELDS = {
    "timestamp", "request_id", "source", "tool", "task",
    "profile", "model", "backend", "ok", "duration_sec",
    "retries", "cache_hit", "queue_wait_ms",
    "input_chars", "output_chars", "error_type", "error",
    "prompt_id", "prompt_version", "prompt_hash",
}


def is_logging_enabled() -> bool:
    val = os.environ.get("LOCAL_LLM_LOG", "1").lower()
    return val in ("1", "true", "yes", "on")


def _make_request_id() -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"req_{ts}_{short}"


def _rotate_if_large():
    """Rotate log file if > 10MB. Keep last 2 rotations."""
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 10_000_000:
        for i in range(2, 0, -1):
            old = LOG_FILE.parent / f"local_llm.{i}.jsonl"
            prev = LOG_FILE.parent / f"local_llm.{i - 1}.jsonl" if i > 1 else LOG_FILE
            if prev.exists():
                prev.replace(old)


def write_log_entry(entry: dict):
    """Write a single log entry as JSONL. Non-blocking, silent on failure."""
    if not is_logging_enabled():
        return

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_if_large()

        # Only include safe fields
        safe_entry = {k: v for k, v in entry.items() if k in SAFE_FIELDS}
        safe_entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        safe_entry.setdefault("request_id", _make_request_id())

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(safe_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never crash the caller


def log_success(source: str, tool: str, task: str, profile: str, model: str,
                backend: str, duration_sec: float, input_chars: int,
                output_chars: int, cache_hit: bool = False, retries: int = 0,
                queue_wait_ms: int = 0, request_id: str | None = None,
                prompt_id: str | None = None, prompt_version: str | None = None,
                prompt_hash: str | None = None):
    write_log_entry({
        "request_id": request_id or _make_request_id(),
        "source": source,
        "tool": tool,
        "task": task,
        "profile": profile,
        "model": model,
        "backend": backend,
        "ok": True,
        "duration_sec": round(duration_sec, 2),
        "input_chars": input_chars,
        "output_chars": output_chars,
        "cache_hit": cache_hit,
        "retries": retries,
        "queue_wait_ms": queue_wait_ms,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
    })


def log_failure(source: str, tool: str, task: str, profile: str, model: str,
                backend: str, duration_sec: float, error_type: str, error: str,
                input_chars: int, retries: int = 0, queue_wait_ms: int = 0,
                request_id: str | None = None,
                prompt_id: str | None = None, prompt_version: str | None = None,
                prompt_hash: str | None = None):
    write_log_entry({
        "request_id": request_id or _make_request_id(),
        "source": source,
        "tool": tool,
        "task": task,
        "profile": profile,
        "model": model,
        "backend": backend,
        "ok": False,
        "duration_sec": round(duration_sec, 2),
        "input_chars": input_chars,
        "output_chars": 0,
        "error_type": error_type,
        "error": error[:300] if error else None,
        "cache_hit": False,
        "retries": retries,
        "queue_wait_ms": queue_wait_ms,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
    })
