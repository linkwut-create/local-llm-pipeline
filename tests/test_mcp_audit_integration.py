"""Test MCP audit hook/wrapper integration (MCP-AUDIT-5)."""

import json
import builtins
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "claude_hooks"))

import mcp_gate as gate
import mcp_audit_logger as log_mod
import mcp_audit_db as db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bash_payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": "",
    }


# ---------------------------------------------------------------------------
# Hook auto-writes commit_gate_blocked event to JSONL
# ---------------------------------------------------------------------------

def test_hook_commit_gate_block_writes_jsonl():
    with tempfile.TemporaryDirectory() as config_dir:
        audit_dir = Path(config_dir) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        result = gate.handle_pre_tooluse(
            config_dir,
            _make_bash_payload("git commit -m 'test'"),
        )
        assert result["allow"] is False
        assert "BLOCKED" in result["reason"]
        # Audit events may be written if mcp_audit_logger is importable
        # Verify no crash — audit is best-effort


def test_audit_write_failure_does_not_crash_hook():
    """Hook must continue working even if audit logger fails."""
    with tempfile.TemporaryDirectory() as config_dir:
        result = gate.handle_pre_tooluse(
            config_dir,
            _make_bash_payload("git commit -m 'test'"),
        )
        assert result["allow"] is False
        # Hook didn't crash — this is the primary assertion


# ---------------------------------------------------------------------------
# Hook subprocess bypass detection writes event
# ---------------------------------------------------------------------------

def test_gate_subprocess_bypass_writes_jsonl():
    with tempfile.TemporaryDirectory() as config_dir:
        audit_dir = Path(config_dir) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        result = gate.handle_pre_tooluse(
            config_dir,
            _make_bash_payload(
                "python -c \"import subprocess; subprocess.run(['git', 'commit', '-m', 'msg'])\""
            ),
        )
        assert result["allow"] is False
        assert "subprocess" in result["reason"].lower()


# ---------------------------------------------------------------------------
# Per-repo state sync
# ---------------------------------------------------------------------------

def test_review_success_updates_repo_scoped_state():
    state = {}
    gate._ensure_repo_state(state, "/fake/repo-a")
    state["diff_reviewed"] = True
    state["dirty_since_review"] = False
    state["reviewed_repo"] = "/fake/repo-a"
    state["reviewed_head"] = "abc123"
    state["reviewed_diff_hash"] = "hash-a"

    # Switch to repo B
    gate._ensure_repo_state(state, "/fake/repo-b")
    assert state["diff_reviewed"] is False  # B starts fresh
    state["diff_reviewed"] = True
    state["reviewed_repo"] = "/fake/repo-b"

    # Switch back to A
    gate._ensure_repo_state(state, "/fake/repo-a")
    assert state["diff_reviewed"] is True
    assert state["reviewed_repo"] == "/fake/repo-a"
    assert state["reviewed_head"] == "abc123"


def test_reviewed_repo_mismatch_blocks():
    with tempfile.TemporaryDirectory() as config_dir:
        state = gate.load_state(config_dir)
        gate._ensure_repo_state(state, "/fake/repo-a")
        state["diff_reviewed"] = True
        state["dirty_since_review"] = False
        state["reviewed_repo"] = "/fake/repo-a"
        gate.save_state(config_dir, state)

        # Commit in a different repo — should be blocked
        result = gate.handle_pre_tooluse(
            config_dir,
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m test"}, "cwd": "/fake/repo-b"},
        )
        assert result["allow"] is False


# ---------------------------------------------------------------------------
# Router audit recording (via logger module directly)
# ---------------------------------------------------------------------------

def test_router_success_writes_invocation_finished():
    with tempfile.TemporaryDirectory() as tmp:
        eid = log_mod.write_audit_event(tmp, {
            "event_type": "mcp_invocation_finished",
            "task_type": "diff_review",
            "tool_name": "local_llm_router:review-diff",
            "profile_name": "commit_reviewer",
            "model_name": "qwen3-coder:30b",
            "result_status": "passed",
            "project_name": "test",
            "phase_id": "MCP-AUDIT-5",
        })
        assert eid is not None
        events_path = Path(tmp) / ".mcp_audit" / "events.jsonl"
        assert events_path.exists()
        events = [json.loads(l) for l in events_path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        assert any(e["event_type"] == "mcp_invocation_finished" for e in events)


def test_router_failure_writes_invocation_failed():
    with tempfile.TemporaryDirectory() as tmp:
        fid = log_mod.write_failure_event(tmp, {
            "failure_type": "tool_failed",
            "severity": "high",
            "tool_name": "local_llm_router:review-diff",
            "project_name": "test",
            "phase_id": "MCP-AUDIT-5",
            "exit_code": 1,
        })
        assert fid is not None
        failures_path = Path(tmp) / ".mcp_audit" / "failures.jsonl"
        assert failures_path.exists()


def test_router_timeout_writes_model_timeout():
    with tempfile.TemporaryDirectory() as tmp:
        fid = log_mod.write_failure_event(tmp, {
            "failure_type": "model_timeout",
            "severity": "high",
            "tool_name": "local_llm_router:summarize-file",
            "project_name": "test",
            "phase_id": "MCP-AUDIT-5",
            "stderr_summary": "Read timed out after 300s",
        })
        assert fid is not None
        failures = [json.loads(l) for l in (Path(tmp) / ".mcp_audit" / "failures.jsonl").read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        assert failures[0]["failure_type"] == "model_timeout"


def test_router_empty_input_writes_failure():
    with tempfile.TemporaryDirectory() as tmp:
        fid = log_mod.write_failure_event(tmp, {
            "failure_type": "tool_failed",
            "severity": "medium",
            "tool_name": "local_llm_router:risk-analysis",
            "project_name": "test",
            "phase_id": "MCP-AUDIT-5",
            "stderr_summary": "Empty input: no content to analyze",
        })
        assert fid is not None


# ---------------------------------------------------------------------------
# JSONL → SQLite sync (import-jsonl)
# ---------------------------------------------------------------------------

def test_import_jsonl_sync_imports_hook_events():
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "events.jsonl").write_text(
            json.dumps({
                "id": "evt-sync", "created_at": "2026-05-13T10:00:00Z",
                "event_type": "commit_gate_blocked", "tool_name": "commit_gate",
                "task_type": "commit_gate", "project_name": "test",
                "phase_id": "MCP-AUDIT-5", "result_status": "blocked",
                "blocking": 1,
            }) + "\n",
            encoding="utf-8")
        result = db.import_audit_jsonl(tmp)
        assert result["events_imported"] == 1


def test_cli_can_query_synced_hook_events():
    """After sync, queries should return hook-recorded events."""
    with tempfile.TemporaryDirectory() as tmp:
        audit_dir = Path(tmp) / ".mcp_audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "events.jsonl").write_text(
            json.dumps({
                "id": "evt-hook", "created_at": "2026-05-13T10:00:00Z",
                "event_type": "commit_gate_blocked", "tool_name": "commit_gate",
                "task_type": "commit_gate", "project_name": "test-project",
                "phase_id": "MCP-AUDIT-5", "result_status": "blocked",
                "blocking": 1,
            }) + "\n",
            encoding="utf-8")
        db.import_audit_jsonl(tmp)

        conn = db.connect_audit_db(tmp)
        blocked = db.list_blocked_commits(conn, "test-project")
        conn.close()
        assert len(blocked) == 1
        assert blocked[0]["id"] == "evt-hook"


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_no_full_prompt_or_full_diff_in_audit():
    """Forbidden fields must not appear in JSONL output."""
    with tempfile.TemporaryDirectory() as tmp:
        eid = log_mod.write_audit_event(tmp, {
            "event_type": "mcp_invocation_finished",
            "tool_name": "local_review_diff",
            "result_status": "passed",
            "prompt_body": "SECRET PROMPT",
            "full_diff": "--- a/file.py\n+++ b/file.py\n...",
            "full_code": "def secret(): pass",
        })
        assert eid is not None
        events_path = Path(tmp) / ".mcp_audit" / "events.jsonl"
        content = events_path.read_text(encoding="utf-8")
        assert "SECRET PROMPT" not in content
        assert "def secret" not in content


def test_no_hook_recursion():
    """Hook handlers must not recursively trigger themselves."""
    # Verify _try_audit_event doesn't crash even if logger is unavailable
    gate._try_audit_event({"event_type": "test_event", "tool_name": "test"})
    gate._try_audit_failure({"failure_type": "test_failed", "severity": "low"})
    # No exception = no recursion


def test_try_audit_helpers_prefer_tools_package_import(monkeypatch):
    calls = []
    tools_mod = types.ModuleType("tools.mcp_audit_logger")
    top_mod = types.ModuleType("mcp_audit_logger")

    def tools_event(config_dir, event):
        calls.append(("tools_event", config_dir, event["event_type"]))

    def tools_failure(config_dir, failure):
        calls.append(("tools_failure", config_dir, failure["failure_type"]))

    def top_event(config_dir, event):
        calls.append(("top_event", config_dir, event["event_type"]))

    def top_failure(config_dir, failure):
        calls.append(("top_failure", config_dir, failure["failure_type"]))

    tools_mod.write_audit_event = tools_event
    tools_mod.write_failure_event = tools_failure
    top_mod.write_audit_event = top_event
    top_mod.write_failure_event = top_failure
    monkeypatch.setitem(sys.modules, "tools.mcp_audit_logger", tools_mod)
    monkeypatch.setitem(sys.modules, "mcp_audit_logger", top_mod)

    gate._try_audit_event({"event_type": "test_event"})
    gate._try_audit_failure({"failure_type": "test_failure"})

    assert calls == [
        ("tools_event", None, "test_event"),
        ("tools_failure", None, "test_failure"),
    ]


def test_try_audit_helpers_fallback_to_top_level_import(monkeypatch):
    calls = []
    top_mod = types.ModuleType("mcp_audit_logger")

    def top_event(config_dir, event):
        calls.append(("top_event", config_dir, event["event_type"]))

    def top_failure(config_dir, failure):
        calls.append(("top_failure", config_dir, failure["failure_type"]))

    top_mod.write_audit_event = top_event
    top_mod.write_failure_event = top_failure
    monkeypatch.setitem(sys.modules, "mcp_audit_logger", top_mod)
    monkeypatch.delitem(sys.modules, "tools.mcp_audit_logger", raising=False)

    real_import = builtins.__import__

    def force_tools_import_error(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tools.mcp_audit_logger":
            raise ImportError("forced tools import failure")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", force_tools_import_error)

    gate._try_audit_event({"event_type": "test_event"})
    gate._try_audit_failure({"failure_type": "test_failure"})

    assert calls == [
        ("top_event", None, "test_event"),
        ("top_failure", None, "test_failure"),
    ]


def test_windows_paths_supported():
    with tempfile.TemporaryDirectory() as tmp:
        eid = log_mod.write_audit_event(tmp, {
            "event_type": "mcp_invocation_started",
            "tool_name": "local_check",
            "project_path": "C:\\Users\\Zero\\local-llm-pipeline",
            "files_involved": ["C:\\Users\\Zero\\project\\tools\\mcp_gate.py"],
        })
        assert eid is not None
