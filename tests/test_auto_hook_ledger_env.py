"""P2-C1.2 — auto-hook env replacement.

Covers two surfaces:

1. The hook-local ``_build_ledger_extra_env`` helper. The hook intentionally
   does not import from ``tools/local_llm_mcp_server.py`` — the MCP server
   has a structurally identical helper but the two stay decoupled because
   the hook runs synchronously inside the Claude Code process and must not
   pull in MCP-server imports. Both helpers MUST produce the same JSON
   schema, but they are tested separately.

2. ``spawn_review_diff`` no longer ships the broken ``--commit_gate true``
   CLI passthrough (the router never had a ``--commit_gate`` flag) and now
   stamps the subprocess env with ``LOCAL_LLM_LEDGER_EXTRA`` instead.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.claude_hooks.mcp_auto_worker import (  # noqa: E402
    _build_ledger_extra_env,
    spawn_review_diff,
)


# --------------------------------------------------------------------------- #
# 1. Pure helper: _build_ledger_extra_env                                     #
# --------------------------------------------------------------------------- #


def _parse_env(env: dict) -> dict:
    return json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])


def test_helper_returns_only_ledger_extra_key():
    env = _build_ledger_extra_env()
    assert set(env.keys()) == {"LOCAL_LLM_LEDGER_EXTRA"}


def test_helper_json_is_parseable():
    env = _build_ledger_extra_env()
    assert isinstance(_parse_env(env), dict)


def test_helper_defaults_to_review_diff():
    payload = _parse_env(_build_ledger_extra_env())
    assert payload["mcp_tool_name"] == "local_review_diff"


def test_helper_default_commit_gate_is_true():
    payload = _parse_env(_build_ledger_extra_env())
    assert payload["commit_gate"] is True


def test_helper_default_source_is_auto_hook():
    payload = _parse_env(_build_ledger_extra_env())
    assert payload["source"] == "auto-hook"


def test_helper_commit_gate_can_be_false():
    payload = _parse_env(_build_ledger_extra_env(commit_gate=False))
    assert payload["commit_gate"] is False


def test_helper_mcp_tool_name_override():
    payload = _parse_env(_build_ledger_extra_env(
        mcp_tool_name="local_summarize_file"))
    assert payload["mcp_tool_name"] == "local_summarize_file"


def test_helper_source_override():
    payload = _parse_env(_build_ledger_extra_env(source="manual-mcp"))
    assert payload["source"] == "manual-mcp"


def test_helper_payload_keys_are_allowlisted():
    """Helper must never emit unknown keys — the P2-B allowlist is the
    integration contract with the worker."""
    payload = _parse_env(_build_ledger_extra_env())
    assert set(payload.keys()) <= {"mcp_tool_name", "commit_gate", "source"}


def test_helper_does_not_mutate_os_environ():
    snapshot = dict(os.environ)
    _build_ledger_extra_env()
    assert dict(os.environ) == snapshot


def test_helper_json_is_deterministic():
    """Compact + sort_keys → byte-identical output between calls. Lets
    downstream tooling cache or fingerprint env payloads safely."""
    raw_a = _build_ledger_extra_env()["LOCAL_LLM_LEDGER_EXTRA"]
    raw_b = _build_ledger_extra_env()["LOCAL_LLM_LEDGER_EXTRA"]
    assert raw_a == raw_b


def test_helper_payload_matches_worker_allowlist_schema():
    """Spot-check that the three emitted keys are exactly the ones P2-C
    cost-discipline allocated for MCP routing identity. Drift between this
    helper and ``call_ledger.KNOWN_EXTRA_KEYS`` would silently lose data,
    so guard the names explicitly."""
    payload = _parse_env(_build_ledger_extra_env())
    assert payload == {
        "mcp_tool_name": "local_review_diff",
        "commit_gate": True,
        "source": "auto-hook",
    }


# --------------------------------------------------------------------------- #
# 2. spawn_review_diff integration                                            #
# --------------------------------------------------------------------------- #


def _capture_spawn_background():
    """Return (captured, _capture_fn) for monkeypatching spawn_background."""
    captured = {}

    def _capture(cmd, env=None, cwd=None, stdin_path=None, log_path=None):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(env) if env is not None else None
        captured["cwd"] = cwd
        captured["stdin_path"] = stdin_path

    return captured, _capture


def test_spawn_review_diff_does_not_pass_commit_gate_cli_flag(monkeypatch, tmp_path):
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    cmd = captured["cmd"]
    # The bug: previously the hook shipped ``--commit_gate true`` which the
    # router never accepted. Regression-guard the removal.
    assert "--commit_gate" not in cmd
    assert "commit_gate" not in cmd  # No re-introduction via alternate spelling


def test_spawn_review_diff_env_contains_ledger_extra(monkeypatch, tmp_path):
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    env = captured["env"]
    assert env is not None
    assert "LOCAL_LLM_LEDGER_EXTRA" in env


def test_spawn_review_diff_env_payload_fields(monkeypatch, tmp_path):
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    payload = json.loads(captured["env"]["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["mcp_tool_name"] == "local_review_diff"
    assert payload["commit_gate"] is True
    assert payload["source"] == "auto-hook"


def test_spawn_review_diff_env_overrides_stale_inherited_value(
        monkeypatch, tmp_path):
    """If LOCAL_LLM_LEDGER_EXTRA was already set in the parent process (e.g.
    a nested MCP-tool invocation that did not clean up), the auto-hook stamp
    must overwrite it so the ledger sees auto-hook attribution, not the
    parent's."""
    monkeypatch.setenv("LOCAL_LLM_LEDGER_EXTRA",
                       json.dumps({"source": "stale-parent",
                                   "mcp_tool_name": "stale-tool"}))
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    payload = json.loads(captured["env"]["LOCAL_LLM_LEDGER_EXTRA"])
    assert payload["source"] == "auto-hook"
    assert payload["mcp_tool_name"] == "local_review_diff"
    assert payload["commit_gate"] is True


def test_spawn_review_diff_preserves_pythonioencoding(monkeypatch, tmp_path):
    """Env stamping must not regress existing UTF-8 plumbing."""
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    assert captured["env"].get("PYTHONIOENCODING") == "utf-8"


def test_spawn_review_diff_keeps_required_cli_args(monkeypatch, tmp_path):
    """The fix must not regress the legitimate CLI surface: review-diff
    --stdin --json-only --output-dir <auto_dir>."""
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    cmd = captured["cmd"]
    assert "review-diff" in cmd
    assert "--stdin" in cmd
    assert "--json-only" in cmd
    assert "--output-dir" in cmd
    assert any("auto" in str(c) for c in cmd), (
        "expected an output-dir path containing 'auto'"
    )


def test_spawn_review_diff_does_not_pollute_global_environ(monkeypatch, tmp_path):
    """The hook copies os.environ but must not mutate it. A subsequent
    read of LOCAL_LLM_LEDGER_EXTRA in the parent must return whatever it
    was before (here, unset)."""
    monkeypatch.delenv("LOCAL_LLM_LEDGER_EXTRA", raising=False)
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config",
                      "diff --git a/x b/x\n+change\n",
                      str(tmp_path))

    assert os.environ.get("LOCAL_LLM_LEDGER_EXTRA") is None


def test_spawn_review_diff_remains_fire_and_forget(monkeypatch, tmp_path):
    """spawn_review_diff must return None synchronously without waiting on
    the spawned subprocess. Guard against accidental conversion to a
    blocking call (subprocess.run / proc.communicate)."""
    spawned = {}

    def _track_spawn(cmd, env=None, cwd=None, stdin_path=None, log_path=None):
        spawned["called"] = True

    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", _track_spawn)

    # If this hangs or blocks, pytest would never get here.
    result = spawn_review_diff("fake_config",
                               "diff --git a/x b/x\n+change\n",
                               str(tmp_path))
    assert result is None
    assert spawned.get("called") is True


def test_spawn_review_diff_empty_diff_does_not_stamp_env(monkeypatch, tmp_path):
    """Empty diff returns early without spawning — env stamping should not
    occur and spawn_background should not be called."""
    captured, capture_fn = _capture_spawn_background()
    monkeypatch.setattr(
        "tools.claude_hooks.mcp_auto_worker.spawn_background", capture_fn)

    spawn_review_diff("fake_config", "   \n  ", str(tmp_path))
    assert captured == {}
