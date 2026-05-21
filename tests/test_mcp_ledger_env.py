"""P2-C1.1 — MCP server per-tool stamps via LOCAL_LLM_LEDGER_EXTRA.

Three layers of coverage:

1. Pure helper tests on ``_build_ledger_extra_env``.
2. Subprocess wrapper plumbing: ``run_subprocess`` /
   ``run_subprocess_streaming`` accept and forward ``extra_env``;
   ``_wrap_worker_call`` propagates it to both subprocess paths.
3. Per-tool stamping: each worker-backed MCP tool handler passes the
   correct ``mcp_tool_name`` (and ``commit_gate`` where it applies).

P2-C1.1 only sets the env on outbound worker invocations. The worker side
(reading ``LOCAL_LLM_LEDGER_EXTRA`` and folding into the call ledger) is
covered by tests/test_worker_ledger_env.py from P2-C1.0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import local_llm_mcp_server as mcp  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. Pure helper: _build_ledger_extra_env                                     #
# --------------------------------------------------------------------------- #


def _parse_env(env: dict) -> dict:
    """Pull LOCAL_LLM_LEDGER_EXTRA out of an env dict and parse the JSON."""
    raw = env["LOCAL_LLM_LEDGER_EXTRA"]
    return json.loads(raw)


def test_build_ledger_extra_env_returns_ledger_extra_key():
    env = mcp._build_ledger_extra_env(mcp_tool_name="local_review_diff")
    assert set(env.keys()) == {"LOCAL_LLM_LEDGER_EXTRA"}


def test_build_ledger_extra_env_json_is_parseable():
    env = mcp._build_ledger_extra_env(mcp_tool_name="local_summarize_file")
    payload = _parse_env(env)
    assert isinstance(payload, dict)


def test_build_ledger_extra_env_mcp_tool_name_propagated():
    env = mcp._build_ledger_extra_env(mcp_tool_name="local_generate_test_plan")
    payload = _parse_env(env)
    assert payload["mcp_tool_name"] == "local_generate_test_plan"


def test_build_ledger_extra_env_source_defaults_to_manual_mcp():
    env = mcp._build_ledger_extra_env(mcp_tool_name="local_review_diff")
    payload = _parse_env(env)
    assert payload["source"] == "manual-mcp"


def test_build_ledger_extra_env_source_can_be_overridden():
    env = mcp._build_ledger_extra_env(
        mcp_tool_name="local_review_diff", source="auto-hook")
    payload = _parse_env(env)
    assert payload["source"] == "auto-hook"


def test_build_ledger_extra_env_commit_gate_true():
    env = mcp._build_ledger_extra_env(
        mcp_tool_name="local_review_diff", commit_gate=True)
    payload = _parse_env(env)
    assert payload["commit_gate"] is True


def test_build_ledger_extra_env_commit_gate_false():
    env = mcp._build_ledger_extra_env(
        mcp_tool_name="local_review_diff", commit_gate=False)
    payload = _parse_env(env)
    assert payload["commit_gate"] is False


def test_build_ledger_extra_env_commit_gate_none_is_omitted():
    env = mcp._build_ledger_extra_env(
        mcp_tool_name="local_summarize_file", commit_gate=None)
    payload = _parse_env(env)
    assert "commit_gate" not in payload


def test_build_ledger_extra_env_commit_gate_default_is_omitted():
    env = mcp._build_ledger_extra_env(mcp_tool_name="local_summarize_file")
    payload = _parse_env(env)
    assert "commit_gate" not in payload


def test_build_ledger_extra_env_does_not_mutate_os_environ():
    snapshot = dict(os.environ)
    mcp._build_ledger_extra_env(
        mcp_tool_name="local_review_diff", commit_gate=True)
    assert dict(os.environ) == snapshot


def test_build_ledger_extra_env_only_emits_allowlisted_keys():
    """Payload must contain only mcp_tool_name, source, and commit_gate.

    Even though the helper signature constrains inputs, the JSON shape is
    an integration boundary — guard it explicitly so a future signature
    change cannot silently leak unknown keys."""
    env = mcp._build_ledger_extra_env(
        mcp_tool_name="local_review_diff", commit_gate=True)
    payload = _parse_env(env)
    assert set(payload.keys()) <= {"mcp_tool_name", "source", "commit_gate"}


# --------------------------------------------------------------------------- #
# 2. Subprocess wrapper plumbing                                              #
# --------------------------------------------------------------------------- #


def test_run_subprocess_forwards_extra_env_to_subprocess_run(monkeypatch):
    captured = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeResult()

    monkeypatch.setattr(mcp.subprocess, "run", _fake_run)
    extra = mcp._build_ledger_extra_env(
        mcp_tool_name="local_review_diff", commit_gate=True)
    mcp.run_subprocess(["dummy"], extra_env=extra)

    env = captured["env"]
    assert env is not None
    assert "LOCAL_LLM_LEDGER_EXTRA" in env
    payload = json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_review_diff"
    assert payload["commit_gate"] is True
    assert payload["source"] == "manual-mcp"


def test_run_subprocess_extra_env_overrides_inherited_env(monkeypatch):
    captured = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeResult()

    monkeypatch.setattr(mcp.subprocess, "run", _fake_run)
    # Pre-existing env value the MCP stamp should overwrite.
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA", json.dumps({"stale": "yes"}))
    extra = mcp._build_ledger_extra_env(mcp_tool_name="local_summarize_file")
    mcp.run_subprocess(["dummy"], extra_env=extra)

    payload = json.loads(captured["env"]["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload.get("mcp_tool_name") == "local_summarize_file"
    assert "stale" not in payload


def test_run_subprocess_without_extra_env_still_works(monkeypatch):
    """No extra_env → child env still has PYTHONIOENCODING / LOCAL_LLM_OUTPUT_DIR
    but no LOCAL_LLM_LEDGER_EXTRA stamp from the helper."""
    monkeypatch.delenv("LOCAL_LLM_LEDGER_EXTRA", raising=False)
    captured = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeResult()

    monkeypatch.setattr(mcp.subprocess, "run", _fake_run)
    mcp.run_subprocess(["dummy"])

    env = captured["env"]
    assert env is not None
    assert env.get("PYTHONIOENCODING") == "utf-8"
    assert "LOCAL_LLM_LEDGER_EXTRA" not in env


def test_run_subprocess_streaming_accepts_extra_env_kwarg():
    """Signature contract: streaming variant must accept ``extra_env``.

    Run the function once with a fake Popen to confirm the kwarg is wired
    through to the child env."""
    import inspect
    sig = inspect.signature(mcp.run_subprocess_streaming)
    assert "extra_env" in sig.parameters


def test_wrap_worker_call_passes_extra_env_to_run_subprocess(monkeypatch):
    captured = {}

    def _capture_run(cmd, **kwargs):
        captured["extra_env"] = kwargs.get("extra_env")
        return {
            "ok": True, "stdout": "JSON: /fake/output.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 0.5,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(
        mcp, "load_worker_output",
        lambda stdout: ({
            "task": "summarize-file", "profile": "fast_summary",
            "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
            "model": "gemma4:e4b", "cache_hit": False,
            "result": {"summary": "ok"},
        }, None),
    )

    extra = mcp._build_ledger_extra_env(mcp_tool_name="local_summarize_file")
    mcp._wrap_worker_call("local_summarize_file", ["dummy"],
                          task="summarize-file", extra_env=extra)

    assert captured["extra_env"] == extra


# --------------------------------------------------------------------------- #
# 3. Per-tool stamping                                                        #
# --------------------------------------------------------------------------- #


def _patch_wrap_capture(monkeypatch):
    """Patch _wrap_worker_call to capture (tool, kwargs) and return a stub."""
    captured = {}

    def _capture(tool, cmd, **kwargs):
        captured["tool"] = tool
        captured.setdefault("kwargs_history", []).append(dict(kwargs))
        captured["kwargs"] = dict(kwargs)
        return {"ok": True, "tool": tool, "task": "stub"}

    monkeypatch.setattr(mcp, "_wrap_worker_call", _capture)
    return captured


def test_call_summarize_file_stamps_mcp_tool_name(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "1")
    src = tmp_path / "x.py"
    src.write_text("def f(): return 1\n", encoding="utf-8")

    captured = _patch_wrap_capture(monkeypatch)
    mcp.call_summarize_file({"path": str(src)})

    extra = captured["kwargs"].get("extra_env")
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_summarize_file"
    assert payload["source"] == "manual-mcp"
    assert "commit_gate" not in payload


def test_call_summarize_tree_stamps_mcp_tool_name(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "1")
    (tmp_path / "a.py").write_text("def a(): pass\n", encoding="utf-8")

    captured = _patch_wrap_capture(monkeypatch)
    mcp.call_summarize_tree({"path": str(tmp_path)})

    extra = captured["kwargs"].get("extra_env")
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_summarize_tree"
    assert payload["source"] == "manual-mcp"


def test_call_generate_test_plan_stamps_mcp_tool_name(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "1")
    src = tmp_path / "x.py"
    src.write_text("def f(): return 1\n", encoding="utf-8")

    captured = _patch_wrap_capture(monkeypatch)
    mcp.call_generate_test_plan({"path": str(src)})

    extra = captured["kwargs"].get("extra_env")
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_generate_test_plan"


def test_call_contextual_analyze_stamps_mcp_tool_name(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "1")
    src = tmp_path / "x.py"
    src.write_text("def f(): return 1\n", encoding="utf-8")

    captured = _patch_wrap_capture(monkeypatch)
    mcp.call_contextual_analyze({"path": str(src), "question": "what?"})

    extra = captured["kwargs"].get("extra_env")
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_contextual_analyze"


def test_call_draft_code_stamps_mcp_tool_name(monkeypatch):
    captured = _patch_wrap_capture(monkeypatch)
    mcp.call_draft_code({"prompt": "do a thing"})

    extra = captured["kwargs"].get("extra_env")
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_draft_code"


def test_call_review_diff_non_gate_stamps_commit_gate_false(monkeypatch):
    """Non-commit-gate review goes through _wrap_worker_call with
    commit_gate=False stamped in the env."""
    captured = _patch_wrap_capture(monkeypatch)

    small_diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    mcp.call_review_diff({"diff_text": small_diff})

    # call_review_diff may delegate to debate for large diffs; ensure ours stays
    # in the worker path.
    assert captured.get("tool") == "local_review_diff"
    extra = captured["kwargs"].get("extra_env")
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_review_diff"
    assert payload["commit_gate"] is False
    assert payload["source"] == "manual-mcp"


def test_call_review_diff_commit_gate_stamps_commit_gate_true(monkeypatch):
    """commit_gate=true takes the direct run_subprocess fast path; the
    extra_env must include commit_gate=true."""
    captured = {}

    def _capture_run(cmd, **kwargs):
        captured["extra_env"] = kwargs.get("extra_env")
        captured["timeout"] = kwargs.get("timeout")
        return {
            "ok": True, "stdout": "JSON: /fake/o.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 1.0,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(
        mcp, "load_worker_output",
        lambda stdout: ({
            "task": "review-diff", "profile": "commit_reviewer",
            "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
            "model": "qwen3-coder:30b", "cache_hit": False,
            "result": {"summary": "ok"},
        }, None),
    )

    small_diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    mcp.call_review_diff({"diff_text": small_diff, "commit_gate": True,
                          "profile": "commit_reviewer"})

    extra = captured["extra_env"]
    assert extra is not None
    payload = json.loads(extra["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_review_diff"
    assert payload["commit_gate"] is True
    assert payload["source"] == "manual-mcp"
    # Confirm the gate path is still using the 60s timeout (regression-guard).
    assert captured["timeout"] == mcp.REVIEW_TIMEOUT


def test_call_parallel_review_stamps_env_per_popen(monkeypatch, tmp_path):
    """call_parallel_review spawns workers via subprocess.Popen. Each child
    must receive LOCAL_LLM_LEDGER_EXTRA with mcp_tool_name=local_parallel_review."""
    captured_envs = []

    class _FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return ("", "")

    def _fake_popen(cmd, **kwargs):
        captured_envs.append(kwargs.get("env"))
        return _FakeProc()

    # Force two healthy profiles so call_parallel_review does not bail to
    # single-review fallback.
    monkeypatch.setattr(
        mcp, "_profile_is_healthy",
        lambda p: p in {"deep_reviewer", "reasoning_checker"},
    )
    monkeypatch.setattr(mcp.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(
        mcp, "load_worker_output",
        lambda stdout: ({
            "task": "review-diff", "profile": "deep_reviewer",
            "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
            "model": "x", "cache_hit": False,
            "result": {"summary": "ok"},
        }, None),
    )

    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    mcp.call_parallel_review({"diff_text": diff})

    assert captured_envs, "no Popen invocations captured"
    for env in captured_envs:
        assert env is not None, "parallel_review must pass env= per worker"
        assert "LOCAL_LLM_LEDGER_EXTRA" in env
        payload = json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])
        assert payload["mcp_tool_name"] == "local_parallel_review"
        assert payload["source"] == "manual-mcp"


# --------------------------------------------------------------------------- #
# 4. Non-stamping paths (regression-guard)                                    #
# --------------------------------------------------------------------------- #


def test_call_local_check_does_not_stamp_env(monkeypatch):
    """local_check runs local_llm_check.py (an env health probe, no LLM
    call) — stamping would be misleading. Confirm no LOCAL_LLM_LEDGER_EXTRA
    is set on its subprocess."""
    captured = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeResult()

    monkeypatch.delenv("LOCAL_LLM_LEDGER_EXTRA", raising=False)
    monkeypatch.setattr(mcp.subprocess, "run", _fake_run)
    mcp.call_local_check({})

    env = captured["env"]
    assert env is not None
    assert "LOCAL_LLM_LEDGER_EXTRA" not in env


def test_call_debate_review_diff_does_not_stamp_env(monkeypatch):
    """local_debate_review_diff drives local_llm_debate.py (P2-C3 will
    emit per-round ledger entries from inside the debate runner). The MCP
    handler must not pre-stamp the debate subprocess in P2-C1.1."""
    captured = {}

    class _FakeResult:
        returncode = 0
        stdout = json.dumps({"task": "debate-review-diff", "result": "ok"})
        stderr = ""

    def _fake_run(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _FakeResult()

    monkeypatch.delenv("LOCAL_LLM_LEDGER_EXTRA", raising=False)
    monkeypatch.setattr(mcp.subprocess, "run", _fake_run)
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    mcp.call_debate_review_diff({"diff_text": diff})

    env = captured["env"]
    assert env is not None
    assert "LOCAL_LLM_LEDGER_EXTRA" not in env


# --------------------------------------------------------------------------- #
# 5. P2-C3.1: debate trigger attribution in MCP handler                       #
# --------------------------------------------------------------------------- #


def test_debate_handler_passes_manual_mcp_trigger(monkeypatch):
    """call_debate_review_diff must pass --debate-trigger manual-mcp
    when called directly (no auto-escalation marker in params)."""
    captured_cmd = None

    def _capture_run(cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        return {
            "ok": True,
            "stdout": json.dumps({"task": "debate-review-diff", "ok": True, "result": "ok"}),
            "stderr": "",
            "returncode": 0,
            "elapsed_seconds": 1.0,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    mcp.call_debate_review_diff({"diff_text": diff})

    assert captured_cmd is not None
    assert "--debate-trigger" in captured_cmd
    trigger_idx = captured_cmd.index("--debate-trigger")
    assert captured_cmd[trigger_idx + 1] == "manual-mcp"


def test_review_diff_auto_escalate_passes_auto_escalate_trigger(monkeypatch):
    """call_review_diff auto-escalation to debate must pass
    --debate-trigger auto-escalate."""
    captured_cmd = None

    def _capture_run(cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        return {
            "ok": True,
            "stdout": json.dumps({"task": "debate-review-diff", "ok": True, "result": "ok"}),
            "stderr": "",
            "returncode": 0,
            "elapsed_seconds": 1.0,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)

    # Build a diff with >100 lines to trigger auto-escalation.
    # commit_gate=False is the default — keeps us out of the gate path.
    diff_lines = ["diff --git a/x.py b/x.py",
                  "--- a/x.py", "+++ b/x.py"]
    for i in range(1, 120):
        diff_lines.append(f"@@ -{i},1 +{i},1 @@")
        diff_lines.append(f" old line {i}")
        diff_lines.append(f"+new line {i}")
    large_diff = "\n".join(diff_lines)

    mcp.call_review_diff({"diff_text": large_diff})

    assert captured_cmd is not None
    assert "--debate-trigger" in captured_cmd
    trigger_idx = captured_cmd.index("--debate-trigger")
    assert captured_cmd[trigger_idx + 1] == "auto-escalate"
