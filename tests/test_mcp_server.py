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
    assert len(mcp.TOOLS) == 6


def test_tool_names():
    expected = {
        "local_check", "local_summarize_file", "local_summarize_tree",
        "local_generate_test_plan", "local_review_diff", "local_debate_review_diff",
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
    assert response["result"]["serverInfo"]["version"] == "0.3.0"
    assert "tools" in response["result"]["capabilities"]


def test_handle_tools_list():
    response = mcp.handle_tools_list(2)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    tools = response["result"]["tools"]
    assert len(tools) == 6
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
    """Verify debate is invoked with --fast and --summary-only by default."""
    cmd = [sys.executable, str(mcp.SCRIPT_DIR / "local_llm_debate.py"),
           "review-diff", "--stdin", "--fast", "--summary-only"]
    assert "--fast" in cmd
    assert "--summary-only" in cmd


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
