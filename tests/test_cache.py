"""Test local_llm_cache.py — cache key computation, hit/miss, and safety."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from local_llm_cache import (
    compute_file_key, compute_tree_key, get_cache, put_cache, clear_cache,
    is_cache_enabled, _should_skip_path, CACHEABLE_TASKS,
)
import local_llm_cache as cache_mod


def test_cacheable_tasks_only_summarize():
    """Only summarize-file and summarize-tree should be cacheable."""
    assert "summarize-file" in CACHEABLE_TASKS
    assert "summarize-tree" in CACHEABLE_TASKS
    assert "review-diff" not in CACHEABLE_TASKS
    assert "draft-fix" not in CACHEABLE_TASKS
    assert "benchmark" not in CACHEABLE_TASKS


def test_compute_file_key_differs_on_size():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(b"hello world")
        path = f.name
    try:
        k1 = compute_file_key(path, "fast_summary", "gemma4:e4b")
        Path(path).write_text("hello world, more content")
        k2 = compute_file_key(path, "fast_summary", "gemma4:e4b")
        assert k1 != k2
    finally:
        os.unlink(path)


def test_compute_file_key_differs_on_profile():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(b"test")
        path = f.name
    try:
        k1 = compute_file_key(path, "fast_summary", "gemma4:e4b")
        k2 = compute_file_key(path, "smart_summary", "gemma4:e4b")
        assert k1 != k2
    finally:
        os.unlink(path)


def test_compute_file_key_differs_on_model():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(b"test")
        path = f.name
    try:
        k1 = compute_file_key(path, "fast_summary", "gemma4:e4b")
        k2 = compute_file_key(path, "fast_summary", "qwen3.5-9b")
        assert k1 != k2
    finally:
        os.unlink(path)


def test_compute_file_key_same_for_unchanged():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(b"test content")
        path = f.name
    try:
        k1 = compute_file_key(path, "fast_summary", "gemma4:e4b")
        k2 = compute_file_key(path, "fast_summary", "gemma4:e4b")
        assert k1 == k2
    finally:
        os.unlink(path)


def test_compute_tree_key_differs_on_file_count():
    files1 = [{"path": "a.py", "size": 100, "mtime_ns": 1}]
    files2 = [{"path": "a.py", "size": 100, "mtime_ns": 1},
              {"path": "b.py", "size": 200, "mtime_ns": 2}]
    k1 = compute_tree_key("/root", 10, files1, "fast_summary", "m")
    k2 = compute_tree_key("/root", 10, files2, "fast_summary", "m")
    assert k1 != k2


def test_compute_tree_key_differs_on_max_files():
    files = [{"path": "a.py", "size": 100, "mtime_ns": 1}]
    k1 = compute_tree_key("/root", 10, files, "fast_summary", "m")
    k2 = compute_tree_key("/root", 20, files, "fast_summary", "m")
    assert k1 != k2


def test_get_put_cache():
    with tempfile.TemporaryDirectory() as tmp:
        # Override cache root
        original_root = cache_mod._cache_root
        cache_mod._cache_root = lambda: Path(tmp)
        try:
            key = "testkey123"
            assert get_cache(key) is None
            put_cache(key, {"task": "summarize-file", "result": "cached"})
            cached = get_cache(key)
            assert cached is not None
            assert cached["cache_hit"] is True
            assert cached["result"] == "cached"
        finally:
            cache_mod._cache_root = original_root


def test_cache_disabled_when_env_off(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_CACHE", "0")
    assert not is_cache_enabled()


def test_cache_enabled_by_default(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_CACHE", raising=False)
    assert is_cache_enabled()


def test_skip_path_secrets():
    assert _should_skip_path(".env") is True
    assert _should_skip_path("key.pem") is True
    assert _should_skip_path("settings.local.json") is True
    assert _should_skip_path(".claude/settings.local.json") is True
    assert _should_skip_path("README.md") is False


def test_secrets_not_cached():
    assert compute_file_key(".env", "fast_summary", "m") is None
    assert compute_file_key("secrets/key.pem", "fast_summary", "m") is None


def test_clear_cache():
    with tempfile.TemporaryDirectory() as tmp:
        original_root = cache_mod._cache_root
        cache_mod._cache_root = lambda: Path(tmp)
        try:
            put_cache("k1", {"task": "summarize-file", "result": "x"})
            put_cache("k2", {"task": "summarize-file", "result": "y"})
            assert get_cache("k1") is not None
            count = clear_cache()
            assert count == 2
            assert get_cache("k1") is None
        finally:
            cache_mod._cache_root = original_root
