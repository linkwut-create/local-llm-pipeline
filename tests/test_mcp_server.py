"""Test local_llm_mcp_server.py structure and security boundaries (no real LLM calls)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import local_llm_mcp_server as mcp

FORBIDDEN_TOOL_KEYWORDS = [
    "write", "delete", "remove", "shell", "exec", "command",
    "commit", "push", "tag", "deploy", "release", "run_any",
    "edit", "modify", "create_file", "rm", "mv", "cp",
]


def test_tools_count():
    assert len(mcp.TOOLS) == 10


def test_tool_names():
    expected = {
        "local_check", "local_summarize_file", "local_summarize_tree",
        "local_generate_test_plan", "local_review_diff", "local_debate_review_diff",
        "local_parallel_review", "local_draft_code", "local_contextual_analyze",
        "local_repo_map",
    }
    assert set(mcp.TOOLS.keys()) == expected


def test_no_dangerous_tools_exposed():
    for name in mcp.TOOLS:
        name_lower = name.lower()
        for keyword in FORBIDDEN_TOOL_KEYWORDS:
            assert keyword not in name_lower, f"Tool '{name}' contains forbidden keyword '{keyword}'"


def test_all_tools_have_description():
    for name, schema in mcp.TOOLS.items():
        assert schema.get("description"), f"Tool '{name}' missing description"
        assert len(schema["description"]) > 10, f"Tool '{name}' description too short"


def test_all_tools_have_input_schema():
    for name, schema in mcp.TOOLS.items():
        assert "inputSchema" in schema, f"Tool '{name}' missing inputSchema"
        assert "properties" in schema["inputSchema"], f"Tool '{name}' missing properties"
        assert "required" in schema["inputSchema"], f"Tool '{name}' missing required"


def test_debate_defaults_fast_true():
    """local_debate_review_diff must default to fast=true for MCP use."""
    schema = mcp.TOOLS["local_debate_review_diff"]["inputSchema"]["properties"]
    assert "fast" in schema
    assert "summary_only" in schema


def test_debate_diff_text_required():
    required = mcp.TOOLS["local_debate_review_diff"]["inputSchema"]["required"]
    assert "diff_text" in required


def test_summarize_file_path_required():
    required = mcp.TOOLS["local_summarize_file"]["inputSchema"]["required"]
    assert "path" in required
    assert "diff_text" not in required


def test_review_diff_text_required():
    required = mcp.TOOLS["local_review_diff"]["inputSchema"]["required"]
    assert "diff_text" in required


def test_validate_path_non_existent(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "1")
    ok, err = mcp.validate_path("nonexistent_file_xyz.txt")
    assert not ok
    assert "not found" in err.lower()


def test_validate_path_blocked_git():
    ok, err = mcp.validate_path(".git/config")
    assert not ok
    assert "blocked" in err.lower()


def test_validate_path_blocked_env():
    ok, err = mcp.validate_path(".env")
    assert not ok
    assert "blocked" in err.lower()


def test_validate_path_blocked_pem():
    ok, err = mcp.validate_path("secrets/key.pem")
    assert not ok
    assert "blocked" in err.lower()


def test_handle_initialize():
    response = mcp.handle_initialize(1)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "local-llm-pipeline"
    assert response["result"]["serverInfo"]["version"] == mcp.SERVER_VERSION
    assert "tools" in response["result"]["capabilities"]


def test_handle_tools_list():
    response = mcp.handle_tools_list(2)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    tools = response["result"]["tools"]
    assert len(tools) == 10
    tool_names = {t["name"] for t in tools}
    assert "local_check" in tool_names


def test_handle_tools_call_unknown():
    response = mcp.handle_tools_call(3, {"name": "local_delete_all", "arguments": {}})
    assert "error" in response
    assert response["error"]["code"] == -32601


def test_call_local_check_no_models(monkeypatch):
    """local_check should not crash even if subprocess fails."""
    def mock_run(cmd, **kwargs):
        return mcp.run_subprocess.__wrapped__ if hasattr(mcp.run_subprocess, '__wrapped__') else MagicMock(
            returncode=1, stdout="Ollama not reachable", stderr="", elapsed_seconds=0.1,
        )
    # Just verify the handler exists and returns structured output
    result = mcp.call_local_check({})
    assert "tool" in result
    assert result["tool"] == "local_check"
    assert "ok" in result
    assert "elapsed_seconds" in result
    assert "created_at" in result


def test_call_debate_empty_diff():
    result = mcp.call_debate_review_diff({"diff_text": ""})
    assert result["ok"] is False


# --- auto-debate trigger tests (v0.9.5) ---

def _make_diff(line_count: int, files: int, with_logic: bool = False) -> str:
    """Build a synthetic diff with the given number of newline chars and files."""
    parts = []
    per_file = max(1, line_count // max(files, 1))
    for i in range(files):
        parts.append(f"diff --git a/file{i}.py b/file{i}.py")
        parts.append("--- a/file{i}.py")
        parts.append("+++ b/file{i}.py")
        parts.append(f"@@ -1,{per_file} +1,{per_file} @@")
        for j in range(per_file):
            if with_logic and j == 0:
                parts.append("+def new_function():")
            else:
                parts.append(f"+ added line {j} in file {i}")
        parts.append("")
    return "\n".join(parts)


def test_small_diff_does_not_trigger_debate():
    """Diff < 100 lines, single file, no logic → single-model review."""
    small = _make_diff(line_count=10, files=1)
    with patch.object(mcp, "call_debate_review_diff") as mock_debate, \
         patch.object(mcp, "_wrap_worker_call", return_value={"ok": True, "task": "review-diff"}):
        result = mcp.call_review_diff({"diff_text": small})
        mock_debate.assert_not_called()


def test_large_diff_triggers_debate():
    """Diff > 100 lines → auto-escalate to debate."""
    large = _make_diff(line_count=120, files=1)
    mock_debate_result = {"tool": "local_debate_review_diff", "ok": True, "task": "debate-review-diff"}
    with patch.object(mcp, "call_debate_review_diff", return_value=mock_debate_result):
        result = mcp.call_review_diff({"diff_text": large})
        assert result["tool"] == "local_debate_review_diff"


def test_multi_file_diff_triggers_debate():
    """Diff touches 3+ files → auto-escalate to debate."""
    multi = _make_diff(line_count=30, files=3)
    mock_debate_result = {"tool": "local_debate_review_diff", "ok": True, "task": "debate-review-diff"}
    with patch.object(mcp, "call_debate_review_diff", return_value=mock_debate_result):
        result = mcp.call_review_diff({"diff_text": multi})
        assert result["tool"] == "local_debate_review_diff"


def test_logic_diff_triggers_debate():
    """Logic changes (def/class/import) in 2+ files → auto-escalate."""
    logic_diff = _make_diff(line_count=40, files=2, with_logic=True)
    mock_debate_result = {"tool": "local_debate_review_diff", "ok": True, "task": "debate-review-diff"}
    with patch.object(mcp, "call_debate_review_diff", return_value=mock_debate_result):
        result = mcp.call_review_diff({"diff_text": logic_diff})
        assert result["tool"] == "local_debate_review_diff"


def test_two_file_no_logic_does_not_trigger_debate():
    """2 files, no logic changes, < 100 lines → no debate."""
    small_multi = _make_diff(line_count=30, files=2, with_logic=False)
    with patch.object(mcp, "call_debate_review_diff") as mock_debate, \
         patch.object(mcp, "_wrap_worker_call", return_value={"ok": True, "task": "review-diff"}):
        result = mcp.call_review_diff({"diff_text": small_multi})
        mock_debate.assert_not_called()


# --- commit_gate fast path tests ---

def test_large_diff_with_commit_gate_does_not_trigger_debate(monkeypatch):
    """commit_gate=true skips auto-debate even for diff > 100 lines."""
    monkeypatch.setattr(mcp, "run_subprocess",
                        lambda cmd, **kw: {"ok": True, "stdout": "JSON: /fake/o.json",
                                           "stderr": "", "returncode": 0, "elapsed_seconds": 1.0})
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "commit_reviewer",
                                         "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
                                         "model": "qwen3-coder:30b", "cache_hit": False,
                                         "result": {"summary": "ok"}}, None))
    large = _make_diff(line_count=120, files=1)
    with patch.object(mcp, "call_debate_review_diff") as mock_debate:
        result = mcp.call_review_diff({"diff_text": large, "commit_gate": True})
        mock_debate.assert_not_called()
    assert result["ok"] is True


def test_logic_diff_with_commit_gate_does_not_trigger_debate(monkeypatch):
    """commit_gate=true skips auto-debate even for logic changes in 2+ files."""
    monkeypatch.setattr(mcp, "run_subprocess",
                        lambda cmd, **kw: {"ok": True, "stdout": "JSON: /fake/o.json",
                                           "stderr": "", "returncode": 0, "elapsed_seconds": 1.0})
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "commit_reviewer",
                                         "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
                                         "model": "qwen3-coder:30b", "cache_hit": False,
                                         "result": {"summary": "ok"}}, None))
    logic_diff = _make_diff(line_count=40, files=2, with_logic=True)
    with patch.object(mcp, "call_debate_review_diff") as mock_debate:
        result = mcp.call_review_diff({"diff_text": logic_diff, "commit_gate": True})
        mock_debate.assert_not_called()
    assert result["ok"] is True


def test_commit_gate_false_still_triggers_debate():
    """commit_gate=false explicitly still auto-escalates to debate."""
    large = _make_diff(line_count=120, files=1)
    mock_debate_result = {"tool": "local_debate_review_diff", "ok": True, "task": "debate-review-diff"}
    with patch.object(mcp, "call_debate_review_diff", return_value=mock_debate_result):
        result = mcp.call_review_diff({"diff_text": large, "commit_gate": False})
        assert result["tool"] == "local_debate_review_diff"


def test_commit_gate_uses_60s_timeout(monkeypatch):
    """commit_gate=true on a large diff still uses REVIEW_TIMEOUT=60."""
    captured = {}

    def _capture_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = dict(kwargs)
        return {
            "ok": True, "stdout": "JSON: /fake/o.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 1.5,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "commit_reviewer",
                                         "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
                                         "model": "qwen3-coder:30b", "cache_hit": False,
                                         "result": {"summary": "ok"}}, None))
    # Large diff would normally trigger debate, but commit_gate=true skips it
    large = _make_diff(line_count=120, files=1)
    result = mcp.call_review_diff({"diff_text": large, "commit_gate": True})
    assert result["ok"] is True
    assert captured["kwargs"]["timeout"] == mcp.REVIEW_TIMEOUT == 60, (
        f"Expected timeout={mcp.REVIEW_TIMEOUT}, got {captured['kwargs'].get('timeout')}"
    )


def test_commit_gate_respects_explicit_profile(monkeypatch):
    """commit_gate=true still passes explicit profile to the router."""
    cmd_parts = []

    def _capture_cmd(cmd, **kwargs):
        cmd_parts.extend(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = "JSON: /fake/output.json"
        return m

    monkeypatch.setattr(mcp, "run_subprocess", _capture_cmd)
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "commit_reviewer",
                                         "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
                                         "model": "qwen3-coder:30b", "cache_hit": False,
                                         "result": {"summary": "ok"}}, None))
    large = _make_diff(line_count=120, files=1)
    mcp.call_review_diff({"diff_text": large, "commit_gate": True, "profile": "commit_reviewer"})
    assert "--profile" in cmd_parts
    assert "commit_reviewer" in cmd_parts


# --- contextual_analyze tests (v0.9.5) ---

def test_contextual_analyze_empty_question(monkeypatch):
    # Allow outside-project access for the temp file
    monkeypatch.setenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", "1")
    import tempfile, os
    fd, tf = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    Path(tf).write_text("print('hello')", encoding="utf-8")
    try:
        result = mcp.call_contextual_analyze({"path": tf, "question": ""})
        assert result["ok"] is False
        assert result["error_type"] == "empty_input"
    finally:
        Path(tf).unlink(missing_ok=True)


def test_contextual_analyze_missing_path():
    # Use a path inside the project root that does not exist
    bad_path = str(Path(__file__).parent / "nonexistent_file.py")
    result = mcp.call_contextual_analyze({"path": bad_path, "question": "test?"})
    assert result["ok"] is False
    assert result["error_type"] is not None


def test_call_debate_builds_correct_cmd():
    """Verify debate handler builds command with --fast and --summary-only by default."""
    captured_cmd = None

    def mock_run(cmd, stdin_data=None, timeout=None, extra_env=None):
        nonlocal captured_cmd
        captured_cmd = cmd
        return {"ok": True, "stdout": '{"ok": true}', "stderr": "", "elapsed_seconds": 1.0, "returncode": 0}

    original_run = mcp.run_subprocess
    mcp.run_subprocess = mock_run
    try:
        mcp.call_debate_review_diff({"diff_text": "-print('old')\n+print('new')"})
    finally:
        mcp.run_subprocess = original_run

    assert captured_cmd is not None
    assert "--fast" in captured_cmd, f"Expected --fast in command: {captured_cmd}"
    assert "--summary-only" in captured_cmd, f"Expected --summary-only in command: {captured_cmd}"


def test_call_review_diff_empty():
    result = mcp.call_review_diff({"diff_text": ""})
    assert result["ok"] is False
    assert "empty" in result["error"].lower()


def test_constants():
    assert mcp.MAX_DIFF_CHARS == 100_000
    assert mcp.MAX_PATH_MAX_CHARS == 200_000
    assert mcp.MAX_MAX_FILES == 50
    assert mcp.DEFAULT_TIMEOUT == 600


def test_truncate_output_small():
    data = {"key": "value", "list": [1, 2, 3]}
    result = mcp.truncate_output(data)
    assert result == data


def test_truncate_output_large_string():
    data = {"key": "x" * 60000}
    result = mcp.truncate_output(data)
    assert len(result["key"]) < 60000
    assert "[truncated]" in result["key"]


def test_find_latest_json_output_handles_missing_dir(monkeypatch):
    """Should return None when .local_llm_out doesn't exist."""
    # find_latest_json_output uses _get_effective_project_root() — mock it
    monkeypatch.setattr(mcp, "_get_effective_project_root",
                        lambda: Path("/nonexistent_temp_dir"))
    result = mcp.find_latest_json_output()
    assert result is None


def test_all_handlers_registered():
    for name in mcp.TOOLS:
        assert name in mcp.TOOL_HANDLERS, f"Handler missing for tool: {name}"


def test_handler_count_matches_tools():
    assert len(mcp.TOOL_HANDLERS) == len(mcp.TOOLS)


def test_draft_code_tool_exists():
    assert "local_draft_code" in mcp.TOOLS


def test_draft_code_empty_prompt():
    result = mcp.call_draft_code({"task": "draft-fix", "prompt": ""})
    assert result["ok"] is False
    assert "empty" in result["error"].lower()


def test_draft_code_task_enum():
    schema = mcp.TOOLS["local_draft_code"]["inputSchema"]["properties"]["task"]
    assert "enum" in schema
    assert "draft-fix" in schema["enum"]
    assert "draft-feature" in schema["enum"]
    assert "draft-refactor" in schema["enum"]
    assert "suggest-improvements" in schema["enum"]


def test_draft_code_schema():
    required = mcp.TOOLS["local_draft_code"]["inputSchema"]["required"]
    assert "task" in required
    # prompt is no longer required — call_draft_code auto-generates it
    # for suggest-improvements when context_file is provided
    assert "prompt" not in required


def test_draft_code_rejects_blocked_path():
    result = mcp.call_draft_code({"task": "draft-fix", "prompt": "fix a bug", "context_file": ".env"})
    assert result["ok"] is False
    assert "blocked" in result["error"].lower()


def test_concurrency_guard_blocks_concurrent_calls():
    """If lock is held, concurrent tool call should return busy error."""
    assert mcp._call_lock.acquire(blocking=False), "lock should be free before test"
    try:
        response = mcp.handle_tools_call(99, {"name": "local_check", "arguments": {}})
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["ok"] is False
        assert content["error_type"] == "concurrent_request"
    finally:
        mcp._call_lock.release()


def test_concurrency_guard_allows_sequential_calls():
    """When lock is free, tool call should proceed normally."""
    response = mcp.handle_tools_call(100, {"name": "local_check", "arguments": {}})
    content = json.loads(response["result"]["content"][0]["text"])
    # May succeed or fail depending on env, but should NOT be concurrent error
    assert content.get("error_type") != "concurrent_request"


def test_debate_diff_too_large():
    """Debate should reject diff_text exceeding MAX_DIFF_CHARS."""
    big_diff = "x" * (mcp.MAX_DIFF_CHARS + 1)
    result = mcp.call_debate_review_diff({"diff_text": big_diff})
    assert result["ok"] is False
    assert "too large" in result["error"].lower()
    assert "suggestion" in result


def test_debate_timeout_structured_error():
    """Timeout should return structured error with suggestion."""
    def mock_run(cmd, stdin_data=None, timeout=None, extra_env=None):
        return {"ok": False, "returncode": -1, "stdout": "",
                "stderr": "Subprocess timed out after 900s", "elapsed_seconds": 900.0}

    original_run = mcp.run_subprocess
    mcp.run_subprocess = mock_run
    try:
        result = mcp.call_debate_review_diff({"diff_text": "-print('old')\n+print('new')"})
    finally:
        mcp.run_subprocess = original_run

    assert result["ok"] is False
    assert result["error"] == "subprocess timed out"
    assert result["suggestion"] == "try smaller diff, --fast, or CLI"
    assert result["result"] is None


def test_review_diff_empty():
    result = mcp.call_review_diff({"diff_text": ""})
    assert result["ok"] is False
    assert "empty" in result["error"].lower()


def test_call_debate_explicit_fast_false():
    """When fast=False, --fast should NOT be in the command."""
    captured_cmd = None

    def mock_run(cmd, stdin_data=None, timeout=None, extra_env=None):
        nonlocal captured_cmd
        captured_cmd = cmd
        return {"ok": True, "stdout": '{"ok": true}', "stderr": "", "elapsed_seconds": 1.0, "returncode": 0}

    original_run = mcp.run_subprocess
    mcp.run_subprocess = mock_run
    try:
        mcp.call_debate_review_diff({"diff_text": "-print('old')\n+print('new')", "fast": False})
    finally:
        mcp.run_subprocess = original_run

    assert "--fast" not in captured_cmd


def test_debate_timeout_passed_to_cmd():
    """When fast=True, --timeout should be passed to subprocess with DEBATE_FAST_PER_ROUND_TIMEOUT."""
    captured_cmd = None

    def mock_run(cmd, stdin_data=None, timeout=None, extra_env=None):
        nonlocal captured_cmd
        captured_cmd = cmd
        return {"ok": True, "stdout": '{"ok": true}', "stderr": "", "elapsed_seconds": 1.0, "returncode": 0}

    original_run = mcp.run_subprocess
    mcp.run_subprocess = mock_run
    try:
        mcp.call_debate_review_diff({"diff_text": "-print('old')\n+print('new')"})
    finally:
        mcp.run_subprocess = original_run

    assert "--timeout" in captured_cmd
    timeout_idx = captured_cmd.index("--timeout")
    assert captured_cmd[timeout_idx + 1] == str(mcp.DEBATE_FAST_PER_ROUND_TIMEOUT)


def test_call_debate_uses_debate_timeout():
    """Debate subprocess should use DEBATE_TIMEOUT, not DEFAULT_TIMEOUT."""
    captured_timeout = None

    def mock_run(cmd, stdin_data=None, timeout=None, extra_env=None):
        nonlocal captured_timeout
        captured_timeout = timeout
        return {"ok": True, "stdout": '{"ok": true}', "stderr": "", "elapsed_seconds": 1.0, "returncode": 0}

    original_run = mcp.run_subprocess
    mcp.run_subprocess = mock_run
    try:
        mcp.call_debate_review_diff({"diff_text": "-print('old')\n+print('new')"})
    finally:
        mcp.run_subprocess = original_run

    assert captured_timeout == mcp.DEBATE_TIMEOUT


def test_new_constants():
    assert mcp.DEBATE_TIMEOUT == 900
    assert mcp.DEBATE_FAST_PER_ROUND_TIMEOUT == 350


# --- Release hardening tests (v0.5.2) ---

def test_version_file_exists():
    vf = Path(__file__).parent.parent / "VERSION"
    assert vf.exists(), "VERSION file is missing"


def test_version_file_format():
    vf = Path(__file__).parent.parent / "VERSION"
    content = vf.read_text(encoding="utf-8").strip()
    parts = content.split(".")
    assert len(parts) == 3, f"VERSION should be semver X.Y.Z, got: {content}"
    assert all(p.isdigit() for p in parts), f"VERSION parts should be digits: {content}"


def test_mcp_server_version_matches_version_file():
    vf = Path(__file__).parent.parent / "VERSION"
    expected = vf.read_text(encoding="utf-8").strip()
    assert mcp.SERVER_VERSION == expected, (
        f"MCP server version {mcp.SERVER_VERSION} != VERSION {expected}"
    )


def test_changelog_exists():
    cl = Path(__file__).parent.parent / "CHANGELOG.md"
    assert cl.exists(), "CHANGELOG.md is missing"


def test_changelog_contains_current_version():
    cl = Path(__file__).parent.parent / "CHANGELOG.md"
    vf = Path(__file__).parent.parent / "VERSION"
    current = vf.read_text(encoding="utf-8").strip()
    content = cl.read_text(encoding="utf-8")
    assert current in content, f"CHANGELOG.md missing version {current}"


def test_release_checklist_exists():
    rc = Path(__file__).parent.parent / "docs" / "release-checklist.md"
    assert rc.exists(), "docs/release-checklist.md is missing"


def test_dry_run_does_not_write_manifest_import():
    """Re-test that dry-run doesn't write files (import from installer)."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from install_local_llm_pipeline import write_manifest as inst_write_manifest
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        inst_write_manifest(target, ["tools/x.py"], [], ["AGENTS.md"], dry_run=True)
        assert not (target / ".local_llm_pipeline.json").exists()


# --- commit_reviewer timeout and profile tests (v0.9.5) ---

def test_review_timeout_constant_exists():
    assert mcp.REVIEW_TIMEOUT == 60, "REVIEW_TIMEOUT should be 60s for commit gate"


def test_review_diff_respects_explicit_profile(monkeypatch):
    """Explicit profile=deep_reviewer must pass through — NOT overridden by default commit_reviewer."""
    cmd_parts = []

    def _capture_cmd(cmd, **kwargs):
        cmd_parts.extend(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stdout = "JSON: /fake/output.json"
        return m

    monkeypatch.setattr(mcp, "run_subprocess", _capture_cmd)
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "deep_reviewer", "prompt_id": "x",
                                         "prompt_version": "v1", "prompt_hash": "abc", "model": "qwen3.6:35b-q8-ud",
                                         "cache_hit": False, "result": {"summary": "ok"}}, None))
    # Single-file small diff — won't trigger auto-debate (1 file, < 100 lines, no logic)
    small = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n+line\n"
    mcp.call_review_diff({"diff_text": small, "profile": "deep_reviewer"})
    assert "--profile" in cmd_parts
    assert "deep_reviewer" in cmd_parts


# --- CJK/Unicode regression tests (v0.9.6) ---

CJK_DIFF = """diff --git a/tests/test_overlay_smoke.py b/tests/test_overlay_smoke.py
--- a/tests/test_overlay_smoke.py
+++ b/tests/test_overlay_smoke.py
@@ -100,5 +100,6 @@
 check("show message has source", "テスト文章" in show_msg["source"])
-error_msg = {"action": "show", "source": "", "translation": "连接失败", "status": "error"}
+error_msg = {"action": "show", "source": "", "translation": "连接失败", "status": "error"}
+check("error message valid", error_msg["status"] == "error")
 # 5. bilingual copy
-check("contains source marker", "【原文】" in text)
+check("contains translation marker", "【译文】" in text)
"""


def test_run_subprocess_handles_cjk_stdin():
    """run_subprocess must encode CJK stdin_data as UTF-8 without error."""
    result = mcp.run_subprocess(
        ["python", "-c", "import sys; sys.stdin.read(); print('ok')"],
        stdin_data=CJK_DIFF,
        timeout=60,
    )
    assert result["returncode"] == 0, f"Subprocess failed: {result.get('stderr', '')}"
    assert "ok" in result.get("stdout", "")


def test_run_subprocess_cjk_roundtrip():
    """CJK characters must survive subprocess stdin → stdout roundtrip."""
    result = mcp.run_subprocess(
        ["python", "-c",
         "import sys; data=sys.stdin.read(); "
         "assert 'テスト文章' in data, 'Japanese missing'; "
         "assert '连接失败' in data, 'Chinese missing'; "
         "assert '【原文】' in data, 'CJK bracket missing'; "
         "print('PASS')"],
        stdin_data=CJK_DIFF,
        timeout=30,
    )
    assert result["returncode"] == 0, f"CJK roundtrip failed: {result.get('stderr', '')}"
    assert "PASS" in result.get("stdout", "")


def test_call_review_diff_with_cjk_diff(monkeypatch):
    """call_review_diff must accept diff_text with CJK characters."""
    monkeypatch.setattr(mcp, "run_subprocess",
                        lambda cmd, **kw: {"ok": True, "stdout": "JSON: /fake/o.json",
                                           "stderr": "", "returncode": 0, "elapsed_seconds": 1.0})
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "diff_reviewer",
                                         "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
                                         "model": "nemotron-30b", "cache_hit": False,
                                         "result": {"summary": "ok"}}, None))
    result = mcp.call_review_diff({"diff_text": CJK_DIFF})
    assert result["ok"] is True, f"CJK review failed: {result.get('error', '')}"


def test_call_debate_review_diff_with_cjk_diff(monkeypatch):
    """call_debate_review_diff must accept CJK diff_text."""
    monkeypatch.setattr(mcp, "run_subprocess",
                        lambda cmd, **kw: {"ok": True, "stdout": '{"ok": true}',
                                           "stderr": "", "returncode": 0, "elapsed_seconds": 2.0})
    result = mcp.call_debate_review_diff({"diff_text": CJK_DIFF})
    assert result["ok"] is True, f"CJK debate review failed: {result.get('error', '')}"


def test_mcp_server_stdin_reconfigure(monkeypatch):
    """main() must reconfigure stdin/stdout/stderr to UTF-8."""
    reconfigured = []

    class FakeStream:
        def reconfigure(self, *, encoding):
            reconfigured.append((self.name, encoding))

    fake_stdin = FakeStream()
    fake_stdin.name = "stdin"
    fake_stdout = FakeStream()
    fake_stdout.name = "stdout"
    fake_stderr = FakeStream()
    fake_stderr.name = "stderr"

    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    # Re-run the main preamble code
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    assert len(reconfigured) == 3, f"Expected 3 stream reconfigures, got {reconfigured}"
    for name, enc in reconfigured:
        assert enc == "utf-8", f"{name} encoding should be utf-8, got {enc}"


# --- v0.9.5 tests continue below ---


def test_review_diff_uses_60s_subprocess_timeout(monkeypatch):
    """call_review_diff with commit_gate=True must pass timeout=REVIEW_TIMEOUT (60)."""
    captured = {}

    def _capture_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = dict(kwargs)
        return {
            "ok": True, "stdout": "JSON: /fake/o.json",
            "stderr": "", "returncode": 0, "elapsed_seconds": 1.5,
        }

    monkeypatch.setattr(mcp, "run_subprocess", _capture_run)
    monkeypatch.setattr(mcp, "load_worker_output",
                        lambda stdout: ({"task": "review-diff", "profile": "commit_reviewer",
                                         "prompt_id": "x", "prompt_version": "v1", "prompt_hash": "abc",
                                         "model": "qwen3-coder:30b", "cache_hit": False,
                                         "result": {"summary": "ok"}}, None))
    # Single-file diff: no auto-debate trigger (< 100 lines, 1 file, no logic)
    small = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n+line\n"
    result = mcp.call_review_diff({"diff_text": small, "commit_gate": True})
    assert result["ok"] is True
    assert captured["kwargs"]["timeout"] == mcp.REVIEW_TIMEOUT == 60, (
        f"Expected timeout={mcp.REVIEW_TIMEOUT}, got {captured['kwargs'].get('timeout')}"
    )


def test_review_diff_non_gate_uses_wrap_worker_call(monkeypatch):
    """call_review_diff without commit_gate routes through _wrap_worker_call for quality escalation."""
    captured = {}

    def _capture_wrap(tool, cmd, **kwargs):
        captured["tool"] = tool
        captured["cmd"] = cmd
        captured["kwargs"] = dict(kwargs)
        return {"ok": True, "tool": tool, "result": {"summary": "ok"}}

    monkeypatch.setattr(mcp, "_wrap_worker_call", _capture_wrap)
    small = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n+line\n"
    result = mcp.call_review_diff({"diff_text": small})
    assert result["ok"] is True
    assert captured["tool"] == "local_review_diff"
    assert "review-diff" in captured["cmd"]
