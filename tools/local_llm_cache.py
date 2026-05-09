#!/usr/bin/env python3
"""
Cache for summarize-file and summarize-tree results.

Avoids redundant Ollama calls for unchanged files.
Cache is in .local_llm_out/cache/ (gitignored).
Controlled by LOCAL_LLM_CACHE env var (default: enabled).

Usage:
    from local_llm_cache import get_cache, put_cache, is_cache_enabled
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR_NAME = ".local_llm_out"
CACHE_SUBDIR = "cache"

CACHEABLE_TASKS = {"summarize-file", "summarize-tree"}

SKIP_CACHE_PATHS = {
    ".env", ".env.local", ".env.production", ".env.development",
    "settings.local.json", "settings.json",
}
SKIP_CACHE_EXTS = {".pem", ".key", ".p12", ".pfx"}


def _cache_root() -> Path:
    return Path(CACHE_DIR_NAME) / CACHE_SUBDIR


def is_cache_enabled() -> bool:
    val = os.environ.get("LOCAL_LLM_CACHE", "1").lower()
    return val in ("1", "true", "yes", "on")


def _prompt_hash(task: str) -> str:
    """Stable hash of the task prompt. Uses task name as proxy for now."""
    return hashlib.sha256(f"task:{task}".encode()).hexdigest()[:12]


def _should_skip_path(path_str: str) -> bool:
    """Check if a path should not be cached (secrets, local config)."""
    p = Path(path_str)
    if p.name in SKIP_CACHE_PATHS:
        return True
    if p.suffix in SKIP_CACHE_EXTS:
        return True
    return False


def compute_file_key(path_str: str, profile: str, model: str) -> str | None:
    """Compute cache key for summarize-file. Returns None if path should be skipped."""
    if _should_skip_path(path_str):
        return None

    p = Path(path_str)
    try:
        stat = p.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns
    except (OSError, FileNotFoundError):
        return None

    ph = _prompt_hash("summarize-file")
    raw = f"sf:{path_str}:{size}:{mtime_ns}:{profile}:{model}:{ph}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def compute_tree_key(root_path: str, max_files: int, file_list: list[dict],
                     profile: str, model: str) -> str | None:
    """Compute cache key for summarize-tree. file_list = [{path, size, mtime_ns}, ...]."""
    ph = _prompt_hash("summarize-tree")
    parts = [f"st:{root_path}:{max_files}:{profile}:{model}:{ph}"]
    for f in sorted(file_list, key=lambda x: x.get("path", "")):
        if _should_skip_path(f.get("path", "")):
            continue
        parts.append(f"{f.get('path','')}:{f.get('size',0)}:{f.get('mtime_ns',0)}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def get_cache(key: str) -> dict | None:
    """Retrieve a cached result. Returns None on miss or if cache disabled."""
    if not is_cache_enabled() or not key:
        return None

    cache_file = _cache_root() / f"{key}.json"
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data["cache_hit"] = True
        return data
    except (json.JSONDecodeError, OSError):
        return None


def put_cache(key: str, data: dict):
    """Store a result in the cache."""
    if not is_cache_enabled() or not key:
        return

    cache_dir = _cache_root()
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_data = dict(data)
    cache_data["cache_hit"] = False
    cache_data["cached_at"] = datetime.now(timezone.utc).isoformat()
    cache_data["cache_key"] = key

    cache_file = cache_dir / f"{key}.json"
    cache_file.write_text(json.dumps(cache_data, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def clear_cache(task: str | None = None) -> int:
    """Clear cache entries. Returns number of files removed."""
    cache_dir = _cache_root()
    if not cache_dir.exists():
        return 0

    removed = 0
    if task:
        # Only clear entries for a specific task
        for f in cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("task") == task:
                    f.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError):
                f.unlink()
                removed += 1
    else:
        for f in cache_dir.glob("*.json"):
            f.unlink()
            removed += 1

    return removed
