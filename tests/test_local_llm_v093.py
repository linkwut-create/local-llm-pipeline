"""
v0.9.3 — MCP stability and heavy-work regression fix.

Covers the nine acceptance items from the v0.9.3 spec:
1. summarize-tree returns a tree summary on the happy path
2. summarize-tree returns a structured error when the tree input is broken
3. summarize-tree failure does NOT fall back to a stale summarize-file result
4. a single MCP tool raising does not kill the server
5. summarize-file completing does not disconnect the MCP wrapper
6. after one tool fails, other tools (local_check) remain callable
7. worker result, JSONL log, and cache JSON all carry
   prompt_id / prompt_version / prompt_hash
8. local_draft_code writes only to .local_llm_out/
9. the MCP server still exposes exactly 9 tools

These tests must run without contacting Ollama; the model layer is monkeypatched.
"""
import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _mcr(text: str):
    """v2-A: call_model returns ModelCallResult (non-stream). Wrap string mocks."""
    from model_call_result import ModelCallResult
    return ModelCallResult(content=text, usage=None, raw_provider="ollama")


@pytest.fixture
def isolated_out_dir(tmp_path, monkeypatch):
    """Redirect .local_llm_out, cache, and logs into a tmp dir so tests do
    not collide with real worker output and so cache hits stay deterministic.
    """
    out_dir = tmp_path / ".local_llm_out"
    out_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_LLM_OUTPUT_DIR", str(out_dir))
    return out_dir


# --------------------------------------------------------------------------- #
# Worker — summarize-tree                                                      #
# --------------------------------------------------------------------------- #


def _make_worker_args(task: str, target: str, **overrides) -> argparse.Namespace:
    base = dict(
        task=task,
        target=target,
        provider="ollama",
        model="fake-model",
        profile="fast_summary",
        base_url="http://127.0.0.1:1",
        stdin=False,
        max_files=None,
        max_chars=None,
        max_output_chars=None,
        timeout=10,
        target_language=None,
        style=None,
        output_dir=None,
        json_only=False,
        no_markdown=True,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_summarize_tree_happy_path_returns_tree_summary(tmp_path, isolated_out_dir, monkeypatch):
    """Acceptance #1 — summarize-tree on a real directory should produce a
    JSON output marked task=summarize-tree and never fall through to
    summarize-file behaviour."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "alpha.py").write_text("def alpha(): return 1\n", encoding="utf-8")
    (project / "beta.py").write_text("def beta(): return 2\n", encoding="utf-8")

    worker = importlib.import_module("local_llm_worker")
    monkeypatch.setattr(worker, "call_model",
                        lambda system, user, config: _mcr("DIRECTORY-SUMMARY-OK"))

    args = _make_worker_args("summarize-tree", str(project), max_files=10)
    rc = worker.run(args)
    assert rc == 0

    json_files = sorted(isolated_out_dir.glob("*_summarize-tree.json"))
    assert json_files, "summarize-tree did not write a tree-tagged JSON file"
    payload = json.loads(json_files[-1].read_text(encoding="utf-8"))
    assert payload["task"] == "summarize-tree"
    assert payload["ok"] is True
    assert "DIRECTORY-SUMMARY-OK" in payload["result"]


def test_summarize_tree_missing_target_returns_structured_error(tmp_path, isolated_out_dir, monkeypatch):
    """Acceptance #2 — passing a non-existent path must yield ok=false with
    error_type populated, not a traceback."""
    worker = importlib.import_module("local_llm_worker")
    # The model must NOT be invoked when input is empty.
    monkeypatch.setattr(worker, "call_model",
                        lambda *a, **kw: pytest.fail("model called on empty input"))

    args = _make_worker_args("summarize-tree", str(tmp_path / "does-not-exist"))
    rc = worker.run(args)
    assert rc != 0

    json_files = sorted(isolated_out_dir.glob("*_summarize-tree.json"))
    assert json_files
    payload = json.loads(json_files[-1].read_text(encoding="utf-8"))
    assert payload["task"] == "summarize-tree"
    assert payload["ok"] is False
    assert payload["error_type"] in {"empty_input", "internal_error"}
    assert payload["error"]


def test_summarize_tree_failure_does_not_resurface_stale_file_summary(tmp_path, isolated_out_dir):
    """Acceptance #3 — verify the MCP wrapper now keys off the worker's
    `JSON: <path>` marker rather than 'most recent file'. A stale
    summarize-file JSON in the output directory must NOT be returned when
    the worker did not actually produce a JSON marker."""
    stale = isolated_out_dir / "20000101_000000_summarize-file.json"
    stale.write_text(json.dumps({
        "task": "summarize-file",
        "ok": True,
        "result": "STALE-FILE-SUMMARY",
    }), encoding="utf-8")

    mcp = importlib.import_module("local_llm_mcp_server")

    # Worker that pretends to crash before writing any output.
    no_marker_stdout = "ERROR: simulated crash\n"
    payload, err = mcp.load_worker_output(no_marker_stdout)
    assert payload is None
    assert err and "JSON: marker" in err

    # And even when a JSON: marker is present but points elsewhere, we must
    # load THAT file, not the stale one.
    fresh = isolated_out_dir / "20300101_000000_summarize-tree.json"
    fresh.write_text(json.dumps({"task": "summarize-tree", "ok": True, "result": "FRESH"}),
                     encoding="utf-8")
    stdout = f"some preamble\nJSON: {fresh}\n"
    data, err = mcp.load_worker_output(stdout)
    assert err is None
    assert data["task"] == "summarize-tree"
    assert data["result"] == "FRESH"


# --------------------------------------------------------------------------- #
# MCP server — isolation & resilience                                          #
# --------------------------------------------------------------------------- #


def test_mcp_handler_exception_does_not_kill_server(monkeypatch):
    """Acceptance #4 — handle_tools_call must return a structured error
    response even when the underlying handler raises. No exception escapes."""
    mcp = importlib.import_module("local_llm_mcp_server")

    def boom(_args):
        raise RuntimeError("simulated handler crash")

    monkeypatch.setitem(mcp.TOOL_HANDLERS, "local_check", boom)
    response = mcp.handle_tools_call(7, {"name": "local_check", "arguments": {}})

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 7
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["ok"] is False
    assert content["error_type"] == "internal_error"
    assert "simulated handler crash" in content["error"]


def test_mcp_summarize_file_success_does_not_disconnect(monkeypatch, tmp_path):
    """Acceptance #5 — a successful summarize-file must produce a
    well-formed response. We exercise the full path through
    handle_tools_call; if it returns a valid response, the stdio loop will
    not have any reason to disconnect."""
    mcp = importlib.import_module("local_llm_mcp_server")

    fake_payload = {
        "task": "summarize-file",
        "ok": True,
        "result": "FILE-OK",
        "profile": "fast_summary",
        "model": "fake",
        "prompt_id": "summarize-file",
        "prompt_version": "v1",
        "prompt_hash": "deadbeef",
    }

    def fake_run_subprocess(cmd, stdin_data=None, timeout=mcp.DEFAULT_TIMEOUT):
        # Worker emits a JSON: marker with the path it wrote.
        out_file = tmp_path / "fake_worker_output.json"
        out_file.write_text(json.dumps(fake_payload), encoding="utf-8")
        return {"ok": True, "stdout": f"JSON: {out_file}\n", "stderr": "", "returncode": 0,
                "elapsed_seconds": 0.01}

    monkeypatch.setattr(mcp, "run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(mcp, "validate_path", lambda p: (True, ""))

    response = mcp.handle_tools_call(11, {
        "name": "local_summarize_file",
        "arguments": {"path": str(tmp_path / "anything.py")},
    })
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["ok"] is True
    assert content["prompt_id"] == "summarize-file"
    assert content["prompt_version"] == "v1"
    assert content["prompt_hash"] == "deadbeef"


def test_mcp_remains_callable_after_tool_failure(monkeypatch):
    """Acceptance #6 — once a tool has failed, the next call must still
    succeed. Lock release is the failure mode here: previously a stuck
    lock could deadlock the server."""
    mcp = importlib.import_module("local_llm_mcp_server")

    monkeypatch.setitem(mcp.TOOL_HANDLERS, "local_check",
                        lambda _args: (_ for _ in ()).throw(RuntimeError("first call boom")))
    bad = mcp.handle_tools_call(1, {"name": "local_check", "arguments": {}})
    assert json.loads(bad["result"]["content"][0]["text"])["ok"] is False

    monkeypatch.setitem(mcp.TOOL_HANDLERS, "local_check",
                        lambda _args: {"tool": "local_check", "ok": True, "task": "check",
                                       "result": {"stdout": "ok", "stderr": ""},
                                       "error": None, "elapsed_seconds": 0,
                                       "created_at": "now"})
    good = mcp.handle_tools_call(2, {"name": "local_check", "arguments": {}})
    assert json.loads(good["result"]["content"][0]["text"])["ok"] is True


# --------------------------------------------------------------------------- #
# Prompt metadata plumbing                                                     #
# --------------------------------------------------------------------------- #


def test_prompt_metadata_in_result_log_and_cache(tmp_path, isolated_out_dir, monkeypatch):
    """Acceptance #7 — after a worker run, prompt_id / prompt_version /
    prompt_hash must be visible in (a) the JSON output, (b) the structured
    log entry, and (c) the cache JSON for cacheable tasks."""
    src = tmp_path / "tiny.py"
    src.write_text("x = 1\n", encoding="utf-8")

    worker = importlib.import_module("local_llm_worker")
    cache_mod = importlib.import_module("local_llm_cache")
    logging_mod = importlib.import_module("local_llm_logging")

    monkeypatch.setattr(cache_mod, "_cache_root",
                        lambda: isolated_out_dir / "cache")
    monkeypatch.setattr(logging_mod, "LOG_DIR", isolated_out_dir / "logs")
    monkeypatch.setattr(logging_mod, "LOG_FILE",
                        isolated_out_dir / "logs" / "local_llm.jsonl")
    monkeypatch.setattr(worker, "call_model", lambda *a, **kw: _mcr("FILE-OK"))

    args = _make_worker_args("summarize-file", str(src))
    rc = worker.run(args)
    assert rc == 0

    # (a) result JSON
    result_files = sorted(isolated_out_dir.glob("*_summarize-file.json"))
    payload = json.loads(result_files[-1].read_text(encoding="utf-8"))
    assert payload["prompt_id"] == "summarize-file"
    assert payload["prompt_version"] == "v1"
    assert payload["prompt_hash"]

    # (b) JSONL log
    log_lines = (isolated_out_dir / "logs" / "local_llm.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert log_lines
    last = json.loads(log_lines[-1])
    assert last["prompt_id"] == "summarize-file"
    assert last["prompt_version"] == "v1"
    assert last["prompt_hash"]

    # (c) cache JSON
    cache_files = list((isolated_out_dir / "cache").glob("*.json"))
    assert cache_files
    cached = json.loads(cache_files[-1].read_text(encoding="utf-8"))
    assert cached["prompt_id"] == "summarize-file"
    assert cached["prompt_version"] == "v1"
    assert cached["prompt_hash"]


# --------------------------------------------------------------------------- #
# Draft scope and tool count                                                   #
# --------------------------------------------------------------------------- #


def test_draft_code_writes_only_to_local_llm_out(tmp_path, isolated_out_dir, monkeypatch):
    """Acceptance #8 — local_draft_code must only emit files under
    .local_llm_out/. Verify by snapshotting tmp_path before and after a run."""
    worker = importlib.import_module("local_llm_worker")
    monkeypatch.setattr(worker, "call_model",
                        lambda *a, **kw: _mcr("## DRAFT FIX\nDo not modify source files."))

    src = tmp_path / "needs_fix.py"
    src.write_text("# placeholder\n", encoding="utf-8")
    src_mtime = src.stat().st_mtime_ns

    snapshot = {p: p.stat().st_mtime_ns for p in tmp_path.iterdir()
                if p.name != ".local_llm_out"}

    args = _make_worker_args("draft-fix", str(src))
    rc = worker.run(args)
    assert rc == 0

    for p, mtime in snapshot.items():
        assert p.stat().st_mtime_ns == mtime, f"draft-fix mutated {p}"
    assert src.stat().st_mtime_ns == src_mtime
    assert any(isolated_out_dir.glob("*_draft-fix.json"))


def test_mcp_tool_count_is_nine():
    """Acceptance #9 — adding/removing MCP tools is a contract change. Lock
    the surface area at exactly nine (v0.9.7 added local_parallel_review)."""
    mcp = importlib.import_module("local_llm_mcp_server")
    expected = {
        "local_check", "local_summarize_file", "local_summarize_tree",
        "local_generate_test_plan", "local_review_diff",
        "local_debate_review_diff", "local_parallel_review",
        "local_draft_code", "local_contextual_analyze",
    }
    assert set(mcp.TOOLS.keys()) == expected
    assert set(mcp.TOOL_HANDLERS.keys()) == expected
    assert len(mcp.TOOLS) == 9
