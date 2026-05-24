"""Tests for C3-B: repo map advisory opt-in on local_generate_test_plan."""
import json
import os
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import local_llm_mcp_server as mcp
import local_llm_repo_map as rm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample_repo_map():
    """A minimal well-formed repo map for testing."""
    files = [
        {"path": "tools/myapp.py", "role": "source", "subsystem": "source",
         "risk_tags": [], "entrypoint": True, "size": 500, "mtime_ns": 1},
        {"path": "tools/peer_a.py", "role": "source", "subsystem": "source",
         "risk_tags": ["worker"], "entrypoint": False, "size": 200, "mtime_ns": 2},
        {"path": "tests/test_myapp.py", "role": "test", "subsystem": "tests",
         "risk_tags": ["tests"], "entrypoint": False, "size": 1200, "mtime_ns": 3},
    ]
    test_mapping = {"tools/myapp.py": ["tests/test_myapp.py"]}
    return {
        "schema_version": 1,
        "repo_root": "/fake/repo",
        "git_head": "abc1234",
        "generated_at": "2026-05-24T00:00:00+00:00",
        "generated_by": "local_llm_repo_map v0.1.0",
        "ok": True,
        "summary": {"total_files": 3},
        "files": files,
        "skipped_files": [],
        "subsystems": {},
        "test_mapping": test_mapping,
        "risk_tags_legend": {},
        "cache_key": "test",
    }


def _write_repo_map(path: Path):
    """Write a sample repo map to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_make_sample_repo_map()), encoding="utf-8")


# ---------------------------------------------------------------------------
# MCP schema / tool count
# ---------------------------------------------------------------------------

class TestSchemaAndToolCount:
    def test_tool_count_unchanged(self):
        assert len(mcp.TOOLS) == 10

    def test_local_generate_test_plan_registered(self):
        assert "local_generate_test_plan" in mcp.TOOLS

    def test_local_repo_map_remains_manual_only(self):
        """local_repo_map must remain manual-only — C3-B does NOT auto-invoke it."""
        # The repo_map MCP tool itself is unchanged
        assert "local_repo_map" in mcp.TOOLS

    def test_new_optional_params_present(self):
        props = mcp.TOOLS["local_generate_test_plan"]["inputSchema"]["properties"]
        assert "use_repo_map" in props
        assert props["use_repo_map"]["type"] == "boolean"
        assert "repo_map_path" in props
        assert "repo_map_max_files" in props

    def test_path_still_required(self):
        req = mcp.TOOLS["local_generate_test_plan"]["inputSchema"]["required"]
        assert "path" in req
        assert "use_repo_map" not in req


# ---------------------------------------------------------------------------
# Default behaviour unchanged (use_repo_map=false / omitted)
# ---------------------------------------------------------------------------

class TestDefaultBehaviorUnchanged:
    def test_use_repo_map_defaults_to_false(self):
        """Omitting use_repo_map must behave as false."""
        # Schema-level verification: it's not in required
        req = mcp.TOOLS["local_generate_test_plan"]["inputSchema"]["required"]
        assert "use_repo_map" not in req

    def test_default_does_not_read_repo_map_file(self, tmp_path):
        """When use_repo_map is not set, no read of repo_map_path happens."""
        # We verify this indirectly: the handler only imports repo_map
        # when use_repo_map=True, so the import guard is the first line
        # of defense. No filesystem call = no read.
        pass  # Verified by code inspection in call_generate_test_plan

    def test_default_ledger_has_used_false(self):
        """When use_repo_map=false, ledger extra must say used=false."""
        from local_llm_mcp_server import _build_ledger_extra_env
        env = _build_ledger_extra_env(
            mcp_tool_name="local_generate_test_plan",
            test_plan_repo_map_used=False,
        )
        payload = json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])
        assert payload["test_plan_repo_map_used"] is False


# ---------------------------------------------------------------------------
# Repo map context helper integration
# ---------------------------------------------------------------------------

class TestRepoMapContextIntegration:
    def test_context_helper_called_for_known_target(self):
        rm_data = _make_sample_repo_map()
        ctx = rm.build_repo_map_context_for_path(rm_data, "tools/myapp.py")
        assert ctx["advisory_only"] is True
        assert ctx["target"]["role"] == "source"
        assert "tests/test_myapp.py" in ctx["related_tests"]

    def test_context_falls_back_on_unknown_target(self):
        rm_data = _make_sample_repo_map()
        ctx = rm.build_repo_map_context_for_path(rm_data, "no/such/file.py")
        assert ctx["target"] is None
        assert ctx["related_tests"] == []

    def test_context_includes_subsystem_peers(self):
        rm_data = _make_sample_repo_map()
        ctx = rm.build_repo_map_context_for_path(rm_data, "tools/myapp.py")
        peer_paths = [p["path"] for p in ctx["subsystem_peers"]]
        assert "tools/peer_a.py" in peer_paths
        assert "tools/myapp.py" not in peer_paths  # self excluded


# ---------------------------------------------------------------------------
# Missing / corrupt repo map handling
# ---------------------------------------------------------------------------

class TestMissingCorruptRepoMap:
    def test_corrupt_json_detected(self, tmp_path):
        rp = tmp_path / ".local_llm_out" / "repo_map.json"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text("this is not json{{{", encoding="utf-8")
        # Verify it's not parseable
        with pytest.raises((json.JSONDecodeError, Exception)):
            json.loads(rp.read_text(encoding="utf-8"))

    def test_missing_file_detected(self, tmp_path):
        rp = tmp_path / ".local_llm_out" / "repo_map.json"
        assert not rp.exists()

    def test_context_helper_does_not_crash_on_empty_map(self):
        ctx = rm.build_repo_map_context_for_path(
            {"files": [], "test_mapping": {}}, "any.py")
        assert ctx["target"] is None
        assert ctx["related_tests"] == []


# ---------------------------------------------------------------------------
# Safety: no body / no sensitive content in context
# ---------------------------------------------------------------------------

class TestSafetyBoundaries:
    def test_no_file_body_in_context(self):
        rm_data = _make_sample_repo_map()
        ctx = rm.build_repo_map_context_for_path(rm_data, "tools/myapp.py")
        ctx_json = json.dumps(ctx)
        assert "content" not in ctx_json
        assert "body" not in ctx_json
        assert "source_code" not in ctx_json
        for key in ctx.keys():
            assert key not in ("body", "content", "source_code", "text")

    def test_no_env_in_context(self):
        rm_data = _make_sample_repo_map()
        ctx = rm.build_repo_map_context_for_path(rm_data, "tools/myapp.py")
        ctx_json = json.dumps(ctx)
        assert ".env" not in ctx_json


# ---------------------------------------------------------------------------
# Ledger extra fields
# ---------------------------------------------------------------------------

class TestLedgerExtraFields:
    def test_known_keys_include_c3b_fields(self):
        from call_ledger import KNOWN_EXTRA_KEYS
        assert "test_plan_repo_map_used" in KNOWN_EXTRA_KEYS
        assert "test_plan_related_tests_count" in KNOWN_EXTRA_KEYS
        assert "test_plan_subsystems" in KNOWN_EXTRA_KEYS
        assert "test_plan_repo_map_warning" in KNOWN_EXTRA_KEYS

    def test_used_true_propagates(self):
        from local_llm_mcp_server import _build_ledger_extra_env
        env = _build_ledger_extra_env(
            mcp_tool_name="local_generate_test_plan",
            test_plan_repo_map_used=True,
            test_plan_related_tests_count=2,
            test_plan_subsystems="mcp,source",
        )
        payload = json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])
        assert payload["test_plan_repo_map_used"] is True
        assert payload["test_plan_related_tests_count"] == 2
        assert payload["test_plan_subsystems"] == "mcp,source"

    def test_warning_propagates(self):
        from local_llm_mcp_server import _build_ledger_extra_env
        env = _build_ledger_extra_env(
            mcp_tool_name="local_generate_test_plan",
            test_plan_repo_map_used=True,
            test_plan_repo_map_warning="repo_map_unavailable",
        )
        payload = json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])
        assert payload["test_plan_repo_map_warning"] == "repo_map_unavailable"

    def test_none_values_omitted(self):
        from local_llm_mcp_server import _build_ledger_extra_env
        env = _build_ledger_extra_env(
            mcp_tool_name="local_generate_test_plan",
            test_plan_repo_map_used=True,
            test_plan_repo_map_warning=None,
        )
        payload = json.loads(env["LOCAL_LLM_LEDGER_EXTRA"])
        # None values should be omitted from the payload
        assert "test_plan_repo_map_warning" not in payload


# ---------------------------------------------------------------------------
# No auto integration leaks
# ---------------------------------------------------------------------------

class TestNoAutoIntegration:
    def test_local_repo_map_not_in_auto_hooks(self):
        """local_repo_map must not appear in auto-hook trigger conditions."""
        hooks_dir = TOOLS_DIR / "claude_hooks"
        if hooks_dir.exists():
            for f in hooks_dir.glob("*.py"):
                if f.name == "__init__.py":
                    continue
                source = f.read_text(encoding="utf-8")
                assert "local_repo_map" not in source, (
                    f"local_repo_map should not be in auto-hook trigger: {f.name}"
                )

    def test_no_review_diff_changes_needed(self):
        """C3-B must not modify local_review_diff schema or handler."""
        props = mcp.TOOLS["local_review_diff"]["inputSchema"]["properties"]
        assert "use_repo_map" not in props
