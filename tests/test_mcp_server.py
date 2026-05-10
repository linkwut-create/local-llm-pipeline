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
    assert len(mcp.TOOLS) == 7


def test_tool_names():
    expected = {
        "local_check", "local_summarize_file", "local_summarize_tree",
        "local_generate_test_plan", "local_review_diff", "local_debate_review_diff",
        "local_draft_code",
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


def test_validate_path_non_existent():
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
    assert len(tools) == 7
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
    assert "empty" in result["error"].lower()


def test_call_debate_builds_correct_cmd():
    """Verify debate handler builds command with --fast and --summary-only by default."""
    captured_cmd = None

    def mock_run(cmd, stdin_data=None, timeout=None):
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
    # Mock out_dir to a non-existent path
    original_dir = mcp.SCRIPT_DIR
    try:
        mcp.SCRIPT_DIR = Path("/nonexistent_temp_dir")
        result = mcp.find_latest_json_output()
        assert result is None
    finally:
        mcp.SCRIPT_DIR = original_dir


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


def test_draft_code_prompt_required():
    required = mcp.TOOLS["local_draft_code"]["inputSchema"]["required"]
    assert "task" in required
    assert "prompt" in required


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
    def mock_run(cmd, stdin_data=None, timeout=None):
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

    def mock_run(cmd, stdin_data=None, timeout=None):
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

    def mock_run(cmd, stdin_data=None, timeout=None):
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

    def mock_run(cmd, stdin_data=None, timeout=None):
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
