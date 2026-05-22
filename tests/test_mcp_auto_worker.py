"""Tests for MCP auto-worker background spawning module."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tools.claude_hooks.mcp_auto_worker import (
    _is_deduped,
    _task_cache_key,
    auto_output_dir,
    _MAX_WORKERS_PER_SESSION,
    needs_auto_summarize,
    needs_auto_review,
    mark_auto_summarize,
    mark_auto_review,
    _worker_count,
    _increment_worker_count,
    collect_auto_results,
    cleanup_auto_results,
    spawn_background,
    spawn_local_check,
    spawn_summarize_file,
    spawn_review_diff,
)


class TestDedup:
    def test_dedup_same_key_within_window(self):
        state = {"_auto_spawned": {
            "auto_summarize:/repo/big.py": time.time() - 10
        }}
        assert _is_deduped(state, "auto_summarize:/repo/big.py", 60) is True

    def test_dedup_expired_window(self):
        state = {"_auto_spawned": {
            "auto_summarize:/repo/big.py": time.time() - 120
        }}
        assert _is_deduped(state, "auto_summarize:/repo/big.py", 60) is False

    def test_dedup_missing_key(self):
        state = {"_auto_spawned": {}}
        assert _is_deduped(state, "nonexistent", 60) is False

    def test_dedup_no_spawned_key(self):
        state = {}
        assert _is_deduped(state, "nonexistent", 60) is False


class TestCacheKey:
    def test_cache_key_format(self):
        key = _task_cache_key("summarize", "/path/to/file.py")
        assert key.startswith("auto_")
        assert "summarize" in key
        assert "/path/to/file.py" in key

    def test_cache_key_different_tasks(self):
        k1 = _task_cache_key("summarize", "/f.py")
        k2 = _task_cache_key("review", "/f.py")
        assert k1 != k2


class TestOutputDir:
    def test_auto_dir_creation(self, tmp_path):
        result = auto_output_dir(str(tmp_path))
        assert result.exists()
        assert result.name == "auto"
        assert result.parent.name == ".local_llm_out"

    def test_auto_dir_cwd_fallback(self):
        result = auto_output_dir(None)
        assert result.name == "auto"


class TestWorkerCount:
    def test_worker_count_default(self):
        assert _worker_count({}) == 0

    def test_worker_count_returns_value(self):
        assert _worker_count({"_auto_worker_count": 5}) == 5

    def test_increment_from_zero(self):
        state = {}
        assert _increment_worker_count(state) == 1
        assert state["_auto_worker_count"] == 1

    def test_increment_accumulates(self):
        state = {"_auto_worker_count": 3}
        assert _increment_worker_count(state) == 4


class TestNeedsAutoSummarize:
    def test_allows_when_not_deduped_and_under_limit(self):
        state = {"_auto_spawned": {}, "_auto_worker_count": 0}
        assert needs_auto_summarize(state, "/f.py") is True

    def test_denies_when_deduped(self):
        state = {"_auto_spawned": {
            "auto_summarize:/f.py": time.time() - 10
        }, "_auto_worker_count": 0}
        assert needs_auto_summarize(state, "/f.py") is False

    def test_denies_when_over_limit(self):
        state = {"_auto_spawned": {},
                 "_auto_worker_count": _MAX_WORKERS_PER_SESSION}
        assert needs_auto_summarize(state, "/f.py") is False


class TestNeedsAutoReview:
    def test_allows_when_not_deduped_and_under_limit(self):
        state = {"_auto_spawned": {}, "_auto_worker_count": 0}
        assert needs_auto_review(state) is True

    def test_denies_when_deduped(self):
        state = {"_auto_spawned": {
            "auto_review:self": time.time() - 10
        }, "_auto_worker_count": 0}
        assert needs_auto_review(state) is False

    def test_denies_when_over_limit(self):
        state = {"_auto_spawned": {},
                 "_auto_worker_count": _MAX_WORKERS_PER_SESSION}
        assert needs_auto_review(state) is False


class TestMark:
    def test_mark_summarize_sets_spawned(self):
        state = {"_auto_spawned": {}, "_auto_worker_count": 0}
        mark_auto_summarize(state, "/f.py")
        assert "auto_summarize:/f.py" in state["_auto_spawned"]
        assert state["_auto_worker_count"] == 1

    def test_mark_review_sets_spawned(self):
        state = {"_auto_spawned": {}, "_auto_worker_count": 0}
        mark_auto_review(state)
        assert "auto_review:self" in state["_auto_spawned"]
        assert state["_auto_worker_count"] == 1


class TestCollectResults:
    def test_empty_dir_returns_empty(self, tmp_path):
        results = collect_auto_results(str(tmp_path))
        assert results == []

    def test_collects_valid_json(self, tmp_path):
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        (auto_dir / "test.json").write_text(json.dumps({
            "task": "summarize-file", "ok": True, "summary": "test summary"
        }))
        results = collect_auto_results(str(tmp_path))
        assert len(results) == 1
        assert results[0]["data"]["ok"] is True
        assert results[0]["data"]["task"] == "summarize-file"

    def test_skips_invalid_json(self, tmp_path):
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        (auto_dir / "bad.json").write_text("not valid json")
        results = collect_auto_results(str(tmp_path))
        assert len(results) == 0

    def test_mixed_valid_and_invalid(self, tmp_path):
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        (auto_dir / "good.json").write_text(json.dumps({"ok": True}))
        (auto_dir / "bad.json").write_text("garbage")
        results = collect_auto_results(str(tmp_path))
        assert len(results) == 1

    def test_sorted_by_mtime(self, tmp_path):
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        f1 = auto_dir / "first.json"
        f1.write_text(json.dumps({"n": 1}))
        time.sleep(0.1)
        f2 = auto_dir / "second.json"
        f2.write_text(json.dumps({"n": 2}))
        results = collect_auto_results(str(tmp_path))
        assert len(results) == 2
        assert results[0]["data"]["n"] == 1
        assert results[1]["data"]["n"] == 2


class TestCleanupResults:
    def test_removes_old_files(self, tmp_path):
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        f = auto_dir / "old.json"
        f.write_text(json.dumps({"ok": True}))
        # Fake old mtime
        old_time = time.time() - 25 * 3600  # 25 hours ago
        os_utime = __import__("os").utime
        os_utime(str(f), (old_time, old_time))
        cleanup_auto_results(str(tmp_path), max_age_hours=24)
        assert not f.exists()

    def test_keeps_recent_files(self, tmp_path):
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        f = auto_dir / "recent.json"
        f.write_text(json.dumps({"ok": True}))
        cleanup_auto_results(str(tmp_path), max_age_hours=24)
        assert f.exists()


class TestSpawnBackground:
    def test_spawn_does_not_raise(self):
        # Should not raise even with invalid args
        spawn_background(["nonexistent_command_xyz"])
        # The function is designed to silently fail

    @patch("subprocess.Popen")
    def test_spawn_passes_args(self, mock_popen):
        spawn_background(["python", "-c", "print(1)"])
        assert mock_popen.called

    @patch("subprocess.Popen")
    def test_spawn_with_stdin_file(self, mock_popen, tmp_path):
        stdin_file = tmp_path / "stdin.txt"
        stdin_file.write_text("test data")
        spawn_background(["cat"], stdin_path=str(stdin_file))
        assert mock_popen.called


class TestSpawnLocalCheck:
    @patch("tools.claude_hooks.mcp_auto_worker.spawn_background")
    def test_creates_log(self, mock_spawn, tmp_path):
        spawn_local_check("fake_config", str(tmp_path))
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        assert auto_dir.exists()
        log_file = auto_dir / "_local_check.log"
        assert log_file.exists()

    @patch("tools.claude_hooks.mcp_auto_worker.subprocess.Popen")
    def test_spawns_process(self, mock_popen, tmp_path):
        spawn_local_check("fake_config", str(tmp_path))
        assert mock_popen.called


class TestSpawnSummarizeFile:
    @patch("tools.claude_hooks.mcp_auto_worker.spawn_background")
    def test_logs_and_spawns(self, mock_spawn, tmp_path):
        spawn_summarize_file("fake_config", "/some/file.py", str(tmp_path))
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        assert auto_dir.exists()
        log_file = auto_dir / "_summarize.log"
        assert log_file.exists()
        assert mock_spawn.called


class TestSpawnReviewDiff:
    @patch("tools.claude_hooks.mcp_auto_worker.spawn_background")
    def test_writes_stdin_and_spawns(self, mock_spawn, tmp_path):
        diff = "diff --git a/x b/x\n+change"
        spawn_review_diff("fake_config", diff, str(tmp_path))
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        # Should have created stdin file
        stdin_files = list(auto_dir.glob("*_review_stdin.txt"))
        assert len(stdin_files) == 1
        assert stdin_files[0].read_text() == diff
        assert mock_spawn.called

    @patch("tools.claude_hooks.mcp_auto_worker.spawn_background")
    def test_skips_empty_diff(self, mock_spawn, tmp_path):
        spawn_review_diff("fake_config", "   \n  ", str(tmp_path))
        assert not mock_spawn.called


# ---------------------------------------------------------------------------
# P7-B C5/C6 — spawn failure diagnostic log
# ---------------------------------------------------------------------------

def _read_failure_lines(tmp_path: Path) -> list[dict]:
    p = tmp_path / ".local_llm_out" / "auto" / "_spawn_failures.log"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


class TestSpawnFailureDiagnostics:
    @patch("tools.claude_hooks.mcp_auto_worker.subprocess.Popen",
           side_effect=OSError("fake popen failure"))
    def test_spawn_background_failure_logs_entry(self, mock_popen, tmp_path):
        """Popen raises => spawn_background still returns silently AND logs."""
        spawn_background(
            ["some_missing_binary", "arg"], cwd=str(tmp_path))
        entries = _read_failure_lines(tmp_path)
        assert len(entries) >= 1
        entry = entries[-1]
        assert entry["fn"] == "spawn_background"
        assert entry["error_type"] == "OSError"
        assert "fake popen failure" in entry["error"]

    @patch("tools.claude_hooks.mcp_auto_worker.subprocess.Popen",
           side_effect=OSError("local_check spawn boom"))
    def test_spawn_local_check_failure_logs_entry(self, mock_popen, tmp_path):
        spawn_local_check("fake_config", str(tmp_path))
        entries = _read_failure_lines(tmp_path)
        assert any(e["fn"] == "spawn_local_check" for e in entries)
        for e in entries:
            if e["fn"] == "spawn_local_check":
                assert e["error_type"] == "OSError"
                assert "local_check spawn boom" in e["error"]

    def test_record_spawn_failure_truncates_oversize_log(self, tmp_path):
        """Oversize _spawn_failures.log is truncated before appending."""
        from tools.claude_hooks.mcp_auto_worker import (
            _record_spawn_failure, _SPAWN_FAILURES_MAX_BYTES,
        )
        auto_dir = tmp_path / ".local_llm_out" / "auto"
        auto_dir.mkdir(parents=True)
        log_path = auto_dir / "_spawn_failures.log"
        # Pre-seed an oversized log.
        log_path.write_text(
            "x" * (_SPAWN_FAILURES_MAX_BYTES + 1024), encoding="utf-8")
        _record_spawn_failure(
            str(tmp_path), "spawn_background", ["py", "thing.py"],
            OSError("boom"))
        # The pre-seed should have been deleted and replaced with a single
        # JSON line.
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert len(content) < _SPAWN_FAILURES_MAX_BYTES
        assert "boom" in content

    def test_record_spawn_failure_never_raises(self, tmp_path, monkeypatch):
        """Even when the dir is unreachable the helper must not raise."""
        from tools.claude_hooks import mcp_auto_worker as aw
        def _fail_dir(_repo_root=None):
            raise OSError("disk gone")
        monkeypatch.setattr(aw, "auto_output_dir", _fail_dir)
        # Must not raise.
        aw._record_spawn_failure(
            str(tmp_path), "spawn_background", ["py"], OSError("x"))
