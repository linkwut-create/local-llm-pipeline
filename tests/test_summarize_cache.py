"""v0.11.0-A1 — worker cache is authoritative for summarize-file/-tree.

After removing the redundant MCP-layer cache from call_summarize_file,
these tests confirm:
- worker cache hit is correctly reflected in MCP response
- old MCP cache files are not consumed
- blocked paths are rejected before any cache logic
- response schema is compatible with cache_hit paths
"""

import json
import os
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import local_llm_cache as cache_mod
import local_llm_mcp_server as mcp


# ---------------------------------------------------------------------------
# Worker cache unit tests (local_llm_cache.py)
# ---------------------------------------------------------------------------


class TestWorkerCacheKeys:
    def test_compute_file_key_includes_all_factors(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello world")
        key1 = cache_mod.compute_file_key(str(f), "fast_summary", "gemma4:e4b")
        # Same inputs → same key
        key2 = cache_mod.compute_file_key(str(f), "fast_summary", "gemma4:e4b")
        assert key1 == key2
        assert key1 is not None

    def test_compute_file_key_changes_with_content(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello")
        key1 = cache_mod.compute_file_key(str(f), "fast_summary", "gemma4:e4b")
        f.write_text("hello world")  # different content → different mtime
        key2 = cache_mod.compute_file_key(str(f), "fast_summary", "gemma4:e4b")
        assert key1 != key2

    def test_compute_file_key_changes_with_profile(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello")
        key1 = cache_mod.compute_file_key(str(f), "fast_summary", "gemma4:e4b")
        key2 = cache_mod.compute_file_key(str(f), "smart_summary", "gemma4:e4b")
        assert key1 != key2

    def test_compute_file_key_changes_with_model(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello")
        key1 = cache_mod.compute_file_key(str(f), "fast_summary", "gemma4:e4b")
        key2 = cache_mod.compute_file_key(str(f), "fast_summary", "other-model")
        assert key1 != key2

    def test_blocked_path_returns_none(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("SECRET=1")
        key = cache_mod.compute_file_key(str(f), "fast_summary", "x")
        assert key is None

    def test_missing_file_returns_none(self, tmp_path):
        key = cache_mod.compute_file_key(str(tmp_path / "nope.txt"), "fast", "x")
        assert key is None


class TestWorkerCacheReadWrite:
    def test_put_and_get_roundtrip(self, tmp_path, monkeypatch):
        cache_sub = tmp_path / ".local_llm_out" / "cache"
        monkeypatch.setattr(cache_mod, "_cache_root", lambda: cache_sub)
        monkeypatch.setenv("LOCAL_LLM_CACHE", "1")

        key = "test_key_abc123"
        data = {"result": "summary text", "summary": "short", "prompt_id": "p1"}
        cache_mod.put_cache(key, data)

        cached = cache_mod.get_cache(key)
        assert cached is not None
        assert cached["result"] == "summary text"
        assert cached["cache_hit"] is True  # get_cache adds this

    def test_get_cache_miss(self, tmp_path, monkeypatch):
        cache_sub = tmp_path / ".local_llm_out" / "cache"
        monkeypatch.setattr(cache_mod, "_cache_root", lambda: cache_sub)
        monkeypatch.setenv("LOCAL_LLM_CACHE", "1")
        assert cache_mod.get_cache("no_such_key") is None

    def test_get_cache_disabled(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_CACHE", "0")
        assert cache_mod.get_cache("any") is None

    def test_is_cache_enabled(self, monkeypatch):
        monkeypatch.setenv("LOCAL_LLM_CACHE", "1")
        assert cache_mod.is_cache_enabled()
        monkeypatch.setenv("LOCAL_LLM_CACHE", "0")
        assert not cache_mod.is_cache_enabled()

    def test_corrupt_cache_file_returns_none(self, tmp_path, monkeypatch):
        cache_sub = tmp_path / ".local_llm_out" / "cache"
        cache_sub.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(cache_mod, "_cache_root", lambda: cache_sub)
        monkeypatch.setenv("LOCAL_LLM_CACHE", "1")
        (cache_sub / "corrupt.json").write_text("not json", encoding="utf-8")
        assert cache_mod.get_cache("corrupt") is None


# ---------------------------------------------------------------------------
# MCP layer: old MCP cache must NOT be consumed
# ---------------------------------------------------------------------------


class TestMcpCacheRemoved:
    def test_mcp_cache_code_removed_from_source(self):
        """The old MCP-level summarize cache block must not exist in the
        current call_summarize_file source."""
        import inspect
        src = inspect.getsource(mcp.call_summarize_file)
        # The old cache code wrote cache files under the name
        # summarize_{cache_key}.json — that file-path pattern must be gone.
        assert 'summarize_{cache_key}' not in src, (
            "MCP-level summarize cache (summarize_{key}.json) must be removed")
        assert "MCP: cache hit" not in src, (
            "MCP-level cache hit log message must be removed")
        assert "Output cache" not in src, (
            "Output cache comment/block must be removed")

    def test_blocked_env_path_rejected_before_any_cache(self, tmp_path):
        """Blocked path must be rejected by validate_path before any
        cache or worker code runs."""
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=x")

        result = mcp.call_summarize_file({
            "path": str(env_file),
        })
        assert result.get("ok") is False
        assert "blocked" in str(result.get("error", "")).lower()


# ---------------------------------------------------------------------------
# CACHEABLE_TASKS contract
# ---------------------------------------------------------------------------


def test_cacheable_tasks_includes_summarize():
    assert "summarize-file" in cache_mod.CACHEABLE_TASKS
    assert "summarize-tree" in cache_mod.CACHEABLE_TASKS
    assert "review-diff" not in cache_mod.CACHEABLE_TASKS
    assert "draft-fix" not in cache_mod.CACHEABLE_TASKS


# ---------------------------------------------------------------------------
# Response schema compat: cache_hit field exists
# ---------------------------------------------------------------------------


def test_build_success_response_includes_cache_hit():
    """build_success_response surfaces cache_hit at top level."""
    payload = {"ok": True, "summary": "test", "cache_hit": True}
    resp = mcp.build_success_response("local_summarize_file", payload, 1500, "req_1")
    assert resp["cache_hit"] is True
    assert resp["ok"] is True
    assert resp["tool"] == "local_summarize_file"


def test_success_response_without_cache_hit_defaults_to_false():
    """When cache_hit is absent from the payload it defaults to False."""
    payload = {"ok": True, "summary": "test"}
    resp = mcp.build_success_response("local_summarize_file", payload, 1500, "req_2")
    assert resp["cache_hit"] is False
