"""P2-C1.0 — worker-side ledger env plumbing.

Covers the new LOCAL_LLM_LEDGER_EXTRA env channel introduced in
tools/local_llm_worker.py and the population of the P2-B top-level
`profile` slot via `config.profile`.

Two layers of coverage:

1. Pure helper tests on `_load_ledger_extra_from_env`. No worker run.
2. Worker integration: monkeypatch `call_model` and `call_ledger.record_call`,
   invoke `worker.run(args)` end-to-end, and inspect the captured ledger record.

P2-C1.0 itself does NOT set the env var — that is P2-C1.1 (MCP server) and
P2-C1.2 (auto hook). This file only verifies the worker side.
"""
from __future__ import annotations

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


# --------------------------------------------------------------------------- #
# Shared fixtures and helpers                                                 #
# --------------------------------------------------------------------------- #


def _mcr(text: str):
    """Wrap a string mock as a ModelCallResult (non-stream path)."""
    from model_call_result import ModelCallResult
    return ModelCallResult(content=text, usage=None, raw_provider="ollama")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ledger-related env vars so tests start from a known state."""
    for var in (
        "LOCAL_LLM_LEDGER_EXTRA",
        "LOCAL_LLM_LEDGER",
        "LOCAL_LLM_PROJECT",
        "LOCAL_LLM_PHASE",
        "LOCAL_LLM_COST_TABLE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def isolated_out_dir(tmp_path, monkeypatch):
    out_dir = tmp_path / ".local_llm_out"
    out_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_LLM_OUTPUT_DIR", str(out_dir))
    return out_dir


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


def _captured_records():
    """Return (list, capture_fn). The list collects every record passed to
    call_ledger.record_call when capture_fn is patched in."""
    captured: list[dict] = []

    def _capture(rec, path=None):
        captured.append(dict(rec))
        return True

    return captured, _capture


# --------------------------------------------------------------------------- #
# 1. Pure helper: _load_ledger_extra_from_env                                 #
# --------------------------------------------------------------------------- #


def test_load_ledger_extra_unset(clean_env):
    worker = importlib.import_module("local_llm_worker")
    assert worker._load_ledger_extra_from_env() == {}


def test_load_ledger_extra_empty_string(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", "")
    worker = importlib.import_module("local_llm_worker")
    assert worker._load_ledger_extra_from_env() == {}


def test_load_ledger_extra_malformed_json(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", "{not-json")
    worker = importlib.import_module("local_llm_worker")
    assert worker._load_ledger_extra_from_env() == {}


def test_load_ledger_extra_json_list(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", '["a", "b"]')
    worker = importlib.import_module("local_llm_worker")
    assert worker._load_ledger_extra_from_env() == {}


def test_load_ledger_extra_json_string(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", '"a string"')
    worker = importlib.import_module("local_llm_worker")
    assert worker._load_ledger_extra_from_env() == {}


def test_load_ledger_extra_json_null(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", "null")
    worker = importlib.import_module("local_llm_worker")
    assert worker._load_ledger_extra_from_env() == {}


def test_load_ledger_extra_valid_known_keys(clean_env, monkeypatch):
    payload = {
        "mcp_tool_name": "local_review_diff",
        "commit_gate": True,
        "source": "manual-mcp",
    }
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps(payload))
    worker = importlib.import_module("local_llm_worker")
    result = worker._load_ledger_extra_from_env()
    assert result == payload


def test_load_ledger_extra_drops_unknown_keys(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
        "mcp_tool_name": "local_review_diff",
        "totally_made_up_key": "should-be-dropped",
        "another_unknown": 42,
    }))
    worker = importlib.import_module("local_llm_worker")
    result = worker._load_ledger_extra_from_env()
    assert result == {"mcp_tool_name": "local_review_diff"}


@pytest.mark.parametrize("forbidden_key", [
    "api_key", "token", "password", "secret", "authorization",
])
def test_load_ledger_extra_drops_forbidden_keys(clean_env, monkeypatch, forbidden_key):
    """Defence-in-depth: forbidden secret keys must not pass the worker
    helper, even before call_ledger.build_record sanitises again."""
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
        "mcp_tool_name": "local_review_diff",
        forbidden_key: "should-be-dropped",
    }))
    worker = importlib.import_module("local_llm_worker")
    result = worker._load_ledger_extra_from_env()
    assert forbidden_key not in result
    assert result.get("mcp_tool_name") == "local_review_diff"


def test_load_ledger_extra_never_raises(clean_env, monkeypatch):
    """Best-effort contract: any malformed input returns {} silently."""
    for value in ["", "{", "}}", "{\"a\": }", "true", "0",
                  '{"mcp_tool_name": ["not", "a", "string"]}']:
        monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", value)
        worker = importlib.import_module("local_llm_worker")
        # Should never raise even if the value type for a known key is unusual.
        worker._load_ledger_extra_from_env()


def test_load_ledger_extra_does_not_mutate_environ(clean_env, monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA",
                       json.dumps({"mcp_tool_name": "local_review_diff"}))
    snapshot_before = dict(os.environ)
    worker = importlib.import_module("local_llm_worker")
    worker._load_ledger_extra_from_env()
    assert dict(os.environ) == snapshot_before


# --------------------------------------------------------------------------- #
# 2. Worker integration: env extras and top-level profile in the ledger       #
# --------------------------------------------------------------------------- #


def test_worker_records_env_extras_in_ledger(
        tmp_path, clean_env, isolated_out_dir, monkeypatch):
    # Use tempfile to avoid .local_llm_out blocking in is_blocked_path
    import tempfile as _tf
    project = Path(_tf.mkdtemp()) / "proj"
    project.mkdir(parents=True)
    (project / "alpha.py").write_text("def alpha(): return 1\n", encoding="utf-8")

    worker = importlib.import_module("local_llm_worker")
    monkeypatch.setattr(worker, "call_model",
                        lambda system, user, config: _mcr("SUMMARY-OK"))

    captured, capture_fn = _captured_records()
    call_ledger = importlib.import_module("call_ledger")
    monkeypatch.setattr(call_ledger, "record_call", capture_fn)

    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
        "mcp_tool_name": "local_summarize_tree",
        "commit_gate": False,
        "source": "manual-mcp",
    }))

    args = _make_worker_args("summarize-tree", str(project),
                             max_files=10, profile="fast_summary")
    rc = worker.run(args)
    assert rc == 0
    assert captured, "worker did not emit any ledger record"

    rec = captured[-1]
    extra = rec.get("extra") or {}
    assert extra.get("mcp_tool_name") == "local_summarize_tree"
    assert extra.get("commit_gate") is False
    assert extra.get("source") == "manual-mcp"


def test_worker_records_top_level_profile_from_config(
        tmp_path, clean_env, isolated_out_dir, monkeypatch):
    import tempfile as _tf
    project = Path(_tf.mkdtemp()) / "proj"
    project.mkdir(parents=True)
    (project / "alpha.py").write_text("def alpha(): return 1\n", encoding="utf-8")

    worker = importlib.import_module("local_llm_worker")
    monkeypatch.setattr(worker, "call_model",
                        lambda system, user, config: _mcr("SUMMARY-OK"))

    captured, capture_fn = _captured_records()
    call_ledger = importlib.import_module("call_ledger")
    monkeypatch.setattr(call_ledger, "record_call", capture_fn)

    args = _make_worker_args("summarize-tree", str(project),
                             max_files=10, profile="fast_summary")
    rc = worker.run(args)
    assert rc == 0
    assert captured

    rec = captured[-1]
    assert rec.get("profile") == "fast_summary"


def test_worker_records_with_unset_env_still_works(
        tmp_path, clean_env, isolated_out_dir, monkeypatch):
    """LOCAL_LLM_LEDGER_EXTRA unset → record still emitted; extra absent or
    empty; profile still populated from config."""
    import tempfile as _tf
    project = Path(_tf.mkdtemp()) / "proj"
    project.mkdir(parents=True)
    (project / "alpha.py").write_text("def alpha(): return 1\n", encoding="utf-8")

    worker = importlib.import_module("local_llm_worker")
    monkeypatch.setattr(worker, "call_model",
                        lambda system, user, config: _mcr("SUMMARY-OK"))

    captured, capture_fn = _captured_records()
    call_ledger = importlib.import_module("call_ledger")
    monkeypatch.setattr(call_ledger, "record_call", capture_fn)

    # Env unset (handled by clean_env fixture).
    args = _make_worker_args("summarize-tree", str(project),
                             max_files=10, profile="fast_summary")
    rc = worker.run(args)
    assert rc == 0
    assert captured

    rec = captured[-1]
    # extra absent or empty — both are acceptable backward-compatible shapes.
    assert "extra" not in rec or not rec["extra"]
    assert rec.get("profile") == "fast_summary"


def test_worker_drops_forbidden_keys_through_env_channel(
        tmp_path, clean_env, isolated_out_dir, monkeypatch):
    """Even if a caller smuggles a forbidden key into the env JSON, it must
    not appear in record extra (helper-level allowlist filter)."""
    import tempfile as _tf
    project = Path(_tf.mkdtemp()) / "proj"
    project.mkdir(parents=True)
    (project / "alpha.py").write_text("def alpha(): return 1\n", encoding="utf-8")

    worker = importlib.import_module("local_llm_worker")
    monkeypatch.setattr(worker, "call_model",
                        lambda system, user, config: _mcr("SUMMARY-OK"))

    captured, capture_fn = _captured_records()
    call_ledger = importlib.import_module("call_ledger")
    monkeypatch.setattr(call_ledger, "record_call", capture_fn)

    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({
        "mcp_tool_name": "local_summarize_tree",
        "api_key": "sk-leaked",
        "password": "p",
    }))

    args = _make_worker_args("summarize-tree", str(project),
                             max_files=10, profile="fast_summary")
    rc = worker.run(args)
    assert rc == 0
    assert captured

    rec = captured[-1]
    extra = rec.get("extra") or {}
    assert "api_key" not in extra
    assert "password" not in extra
    assert extra.get("mcp_tool_name") == "local_summarize_tree"
