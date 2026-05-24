"""Tests for tools/local_llm_repo_map.py — C1 repo map generator."""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Import under test
sys_path = str(Path(__file__).resolve().parent.parent / "tools")
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

import local_llm_repo_map as rm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree(base: Path, structure: dict):
    """Create a directory tree from a nested dict. Values are strings (file content)
    or nested dicts (directories)."""
    for name, content in structure.items():
        fpath = base / name
        if isinstance(content, dict):
            fpath.mkdir(parents=True, exist_ok=True)
            _make_tree(fpath, content)
        else:
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# classify_file_role
# ---------------------------------------------------------------------------

class TestClassifyFileRole:
    def test_mcp_server(self):
        assert rm.classify_file_role("tools/local_llm_mcp_server.py") == "mcp_server"

    def test_worker(self):
        assert rm.classify_file_role("tools/local_llm_worker.py") == "worker"

    def test_router(self):
        assert rm.classify_file_role("tools/local_llm_router.py") == "router"

    def test_debate(self):
        assert rm.classify_file_role("tools/local_llm_debate.py") == "debate"

    def test_ledger(self):
        assert rm.classify_file_role("tools/call_ledger.py") == "ledger"
        assert rm.classify_file_role("tools/call_ledger_cli.py") == "ledger"

    def test_cache(self):
        assert rm.classify_file_role("tools/local_llm_cache.py") == "cache"

    def test_preclassifier(self):
        assert rm.classify_file_role("tools/local_llm_preclassifier.py") == "preclassifier"

    def test_readme(self):
        assert rm.classify_file_role("README.md") == "readme"

    def test_changelog(self):
        assert rm.classify_file_role("CHANGELOG.md") == "changelog"

    def test_project_status(self):
        assert rm.classify_file_role("PROJECT_STATUS.md") == "project_status"

    def test_claude_md(self):
        assert rm.classify_file_role("CLAUDE.md") == "claude_instructions"

    def test_docs_dir(self):
        assert rm.classify_file_role("docs/some-plan.md") == "docs"
        assert rm.classify_file_role("docs/sub/deep.md") == "docs"

    def test_rst_and_txt(self):
        assert rm.classify_file_role("notes.rst") == "docs"
        assert rm.classify_file_role("notes.txt") == "docs"

    def test_test_file(self):
        assert rm.classify_file_role("tests/test_foo.py") == "test"

    def test_hook_file(self):
        assert rm.classify_file_role("tools/claude_hooks/mcp_gate.py") == "hook"
        assert rm.classify_file_role("tools/claude_hooks/mcp_doctor.py") == "hook"

    def test_config_json(self):
        assert rm.classify_file_role("tools/local_llm_profiles.json") == "config"

    def test_mcp_config(self):
        assert rm.classify_file_role(".mcp.json") == "mcp_config"

    def test_pyproject(self):
        assert rm.classify_file_role("pyproject.toml") == "config"

    def test_source_py(self):
        assert rm.classify_file_role("tools/some_util.py") == "source"

    def test_unknown(self):
        assert rm.classify_file_role("data/sample.csv") == "unknown"

    def test_windows_path(self):
        assert rm.classify_file_role("tools\\local_llm_mcp_server.py") == "mcp_server"

    def test_case_insensitive(self):
        assert rm.classify_file_role("tools/LOCAL_LLM_MCP_SERVER.PY") == "mcp_server"

    def test_health_check(self):
        assert rm.classify_file_role("tools/local_llm_check.py") == "health_check"


# ---------------------------------------------------------------------------
# detect_risk_tags
# ---------------------------------------------------------------------------

class TestDetectRiskTags:
    def test_mcp_tags(self):
        tags = rm.detect_risk_tags("tools/local_llm_mcp_server.py")
        assert "mcp" in tags

    def test_worker_tag(self):
        tags = rm.detect_risk_tags("tools/local_llm_worker.py")
        assert "worker" in tags

    def test_router_tag(self):
        tags = rm.detect_risk_tags("tools/local_llm_router.py")
        assert "routing" in tags

    def test_debate_tag(self):
        tags = rm.detect_risk_tags("tools/local_llm_debate.py")
        assert "debate" in tags

    def test_ledger_tag(self):
        tags = rm.detect_risk_tags("tools/call_ledger.py")
        assert "ledger" in tags

    def test_hook_tag(self):
        tags = rm.detect_risk_tags("tools/claude_hooks/mcp_gate.py")
        assert "hooks" in tags
        assert "safety" in tags

    def test_config_tag(self):
        tags = rm.detect_risk_tags("tools/local_llm_profiles.json")
        assert "config" in tags
        assert "routing" in tags

    def test_docs_tag(self):
        tags = rm.detect_risk_tags("docs/plan.md")
        assert "docs" in tags

    def test_test_tag(self):
        tags = rm.detect_risk_tags("tests/test_foo.py")
        assert "tests" in tags

    def test_no_tag_for_unknown(self):
        tags = rm.detect_risk_tags("data/something.csv")
        assert tags == []

    def test_deduplication(self):
        tags = rm.detect_risk_tags("docs/config-guide.md")
        assert tags == sorted(tags)

    def test_auto_invocation(self):
        tags = rm.detect_risk_tags("tools/claude_hooks/mcp_auto_worker.py")
        assert "auto_invocation" in tags

    def test_diagnostic(self):
        tags = rm.detect_risk_tags("tools/claude_hooks/mcp_doctor.py")
        assert "diagnostic" in tags


# ---------------------------------------------------------------------------
# detect_entrypoint
# ---------------------------------------------------------------------------

class TestDetectEntrypoint:
    def test_name_based(self):
        assert rm.detect_entrypoint(Path("tools/local_llm_mcp_server.py")) is True

    def test_cli_name(self):
        assert rm.detect_entrypoint(Path("tools/call_ledger_cli.py")) is True

    def test_content_main_block(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text('if __name__ == "__main__":\n    main()')
        assert rm.detect_entrypoint(f) is True

    def test_content_argparse(self, tmp_path):
        f = tmp_path / "cli.py"
        f.write_text("import argparse\nparser = argparse.ArgumentParser()")
        assert rm.detect_entrypoint(f) is True  # name ends in _cli

    def test_content_main_func(self, tmp_path):
        f = tmp_path / "runner.py"
        f.write_text("def main(args):\n    pass\n")
        assert rm.detect_entrypoint(f) is True

    def test_not_entrypoint(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text("def helper():\n    return 42\n")
        assert rm.detect_entrypoint(f) is False

    def test_non_py_file(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# Title")
        assert rm.detect_entrypoint(f) is False

    def test_content_sample_override(self, tmp_path):
        f = tmp_path / "app.py"
        # Don't write the file — use content_sample
        assert rm.detect_entrypoint(f, content_sample='if __name__ == "__main__":') is True

    def test_missing_file_no_crash(self, tmp_path):
        f = tmp_path / "nonexistent.py"
        assert rm.detect_entrypoint(f) is False

    def test_run_checks(self):
        assert rm.detect_entrypoint(Path("tools/run_checks.py")) is True


# ---------------------------------------------------------------------------
# infer_test_mapping
# ---------------------------------------------------------------------------

class TestInferTestMapping:
    def test_basic_mapping(self):
        files = [
            {"path": "tools/local_llm_preclassifier.py", "role": "preclassifier"},
            {"path": "tests/test_preclassifier.py", "role": "test"},
        ]
        mapping = rm.infer_test_mapping(files)
        assert "tools/local_llm_preclassifier.py" in mapping
        assert "tests/test_preclassifier.py" in mapping["tools/local_llm_preclassifier.py"]

    def test_multiple_tests(self):
        files = [
            {"path": "tools/app_core.py", "role": "source"},
            {"path": "tests/test_app_core.py", "role": "test"},
            {"path": "tests/test_app_core_edge_cases.py", "role": "test"},
        ]
        mapping = rm.infer_test_mapping(files)
        assert len(mapping["tools/app_core.py"]) == 1  # only test_app_core stem matches

    def test_no_mapping_for_docs(self):
        files = [
            {"path": "PROJECT_STATUS.md", "role": "project_status"},
            {"path": "tests/test_status.py", "role": "test"},
        ]
        mapping = rm.infer_test_mapping(files)
        assert "PROJECT_STATUS.md" not in mapping

    def test_empty_input(self):
        assert rm.infer_test_mapping([]) == {}

    def test_no_tests(self):
        files = [{"path": "tools/app.py", "role": "source"}]
        assert rm.infer_test_mapping(files) == {}

    def test_normalized_name_match(self):
        files = [
            {"path": "tools/my_module.py", "role": "source"},
            {"path": "tests/test_my_module.py", "role": "test"},
        ]
        mapping = rm.infer_test_mapping(files)
        assert "tools/my_module.py" in mapping

    def test_test_without_prefix(self):
        files = [
            {"path": "tools/helper.py", "role": "source"},
            {"path": "tests/helper_test.py", "role": "test"},
        ]
        mapping = rm.infer_test_mapping(files)
        assert "tools/helper.py" in mapping


# ---------------------------------------------------------------------------
# generate_cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_stable_for_same_map(self):
        m1 = {"schema_version": 1, "git_head": "abc", "files": [
            {"path": "a.py", "size": 100, "mtime_ns": 1},
        ]}
        assert rm.generate_cache_key(m1) == rm.generate_cache_key(dict(m1))

    def test_changes_with_git_head(self):
        m1 = {"schema_version": 1, "git_head": "abc", "files": []}
        m2 = {"schema_version": 1, "git_head": "def", "files": []}
        assert rm.generate_cache_key(m1) != rm.generate_cache_key(m2)

    def test_changes_with_file_list(self):
        m1 = {"schema_version": 1, "git_head": "abc", "files": [
            {"path": "a.py", "size": 100, "mtime_ns": 1},
        ]}
        m2 = {"schema_version": 1, "git_head": "abc", "files": [
            {"path": "a.py", "size": 100, "mtime_ns": 2},
        ]}
        assert rm.generate_cache_key(m1) != rm.generate_cache_key(m2)

    def test_empty_files(self):
        m = {"schema_version": 1, "git_head": "", "files": []}
        key = rm.generate_cache_key(m)
        assert len(key) == 20
        assert key == rm.generate_cache_key(dict(m))

    def test_schema_version_bump_changes_key(self):
        m1 = {"schema_version": 1, "git_head": "abc", "files": []}
        m2 = {"schema_version": 2, "git_head": "abc", "files": []}
        assert rm.generate_cache_key(m1) != rm.generate_cache_key(m2)


# ---------------------------------------------------------------------------
# scan_repo — integration tests
# ---------------------------------------------------------------------------

class TestScanRepo:
    def test_missing_root(self):
        result = rm.scan_repo(Path("/nonexistent/path/xyz"))
        assert result["ok"] is False
        assert len(result["warnings"]) > 0

    def test_empty_repo(self, tmp_path):
        result = rm.scan_repo(tmp_path)
        assert result["ok"] is True
        assert result["files"] == []
        assert result["summary"]["total_files"] == 0

    def test_ignores_git_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]")
        (tmp_path / "README.md").write_text("# Hello")
        result = rm.scan_repo(tmp_path)
        paths = [f["path"] for f in result["files"]]
        assert ".git/config" not in paths
        assert "README.md" in paths

    def test_ignores_venv(self, tmp_path):
        (tmp_path / "venv").mkdir()
        (tmp_path / "venv" / "lib.py").write_text("x=1")
        (tmp_path / "app.py").write_text("print(1)")
        result = rm.scan_repo(tmp_path)
        paths = [f["path"] for f in result["files"]]
        assert "venv/lib.py" not in paths
        assert "app.py" in paths

    def test_ignores_local_llm_out(self, tmp_path):
        (tmp_path / ".local_llm_out").mkdir()
        (tmp_path / ".local_llm_out" / "result.json").write_text("{}")
        (tmp_path / "src.py").write_text("x=1")
        result = rm.scan_repo(tmp_path)
        paths = [f["path"] for f in result["files"]]
        assert ".local_llm_out/result.json" not in paths
        assert "src.py" in paths

    def test_ignores_env_files(self, tmp_path):
        (tmp_path / ".env").write_text("SECRET=1")
        (tmp_path / ".env.production").write_text("KEY=2")
        (tmp_path / "secrets.txt").write_text("x")
        (tmp_path / "normal.txt").write_text("ok")
        result = rm.scan_repo(tmp_path)
        paths = [f["path"] for f in result["files"]]
        for blocked in (".env", ".env.production", "secrets.txt"):
            assert blocked not in paths, f"{blocked} should be ignored"
        assert "normal.txt" in paths

    def test_classifies_docs(self, tmp_path):
        (tmp_path / "README.md").write_text("# Hi")
        (tmp_path / "CHANGELOG.md").write_text("## v1")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["README.md"] == "readme"
        assert roles["CHANGELOG.md"] == "changelog"

    def test_classifies_tests(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test(): pass")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("def main(): pass")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["tests/test_app.py"] == "test"
        assert roles["src/app.py"] == "source"

    def test_classifies_hooks(self, tmp_path):
        (tmp_path / "tools" / "claude_hooks").mkdir(parents=True)
        (tmp_path / "tools" / "claude_hooks" / "mcp_gate.py").write_text("# gate")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["tools/claude_hooks/mcp_gate.py"] == "hook"

    def test_classifies_config(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool]")
        (tmp_path / ".mcp.json").write_text("{}")
        (tmp_path / "config.yaml").write_text("key: val")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["pyproject.toml"] == "config"
        assert roles[".mcp.json"] == "mcp_config"
        assert roles["config.yaml"] == "config"

    def test_detects_mcp_server(self, tmp_path):
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "local_llm_mcp_server.py").write_text("# mcp")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["tools/local_llm_mcp_server.py"] == "mcp_server"

    def test_detects_ledger_files(self, tmp_path):
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "call_ledger.py").write_text("# ledger")
        (tmp_path / "tools" / "call_ledger_cli.py").write_text("# cli")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["tools/call_ledger.py"] == "ledger"
        assert roles["tools/call_ledger_cli.py"] == "ledger"

    def test_detects_router_worker_debate(self, tmp_path):
        (tmp_path / "tools").mkdir()
        for fn in ("local_llm_router.py", "local_llm_worker.py", "local_llm_debate.py"):
            (tmp_path / "tools" / fn).write_text("# tool")
        result = rm.scan_repo(tmp_path)
        roles = {f["path"]: f["role"] for f in result["files"]}
        assert roles["tools/local_llm_router.py"] == "router"
        assert roles["tools/local_llm_worker.py"] == "worker"
        assert roles["tools/local_llm_debate.py"] == "debate"

    def test_output_order_deterministic(self, tmp_path):
        (tmp_path / "c.py").write_text("c")
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        r1 = rm.scan_repo(tmp_path)
        r2 = rm.scan_repo(tmp_path)
        assert [f["path"] for f in r1["files"]] == [f["path"] for f in r2["files"]]
        assert r1["files"][0]["path"] == "a.py"

    def test_skips_binary(self, tmp_path):
        (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        (tmp_path / "text.py").write_text("print(1)")
        result = rm.scan_repo(tmp_path)
        paths = [f["path"] for f in result["files"]]
        assert "img.png" not in paths
        assert "text.py" in paths
        skipped = [s["path"] for s in result["skipped_files"]]
        assert "img.png" in skipped

    def test_skip_null_byte_file(self, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"abc\x00def")
        result = rm.scan_repo(tmp_path)
        paths = [f["path"] for f in result["files"]]
        assert "data.bin" not in paths

    def test_exclude_tests(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test(): pass")
        (tmp_path / "app.py").write_text("x=1")
        result = rm.scan_repo(tmp_path, include_tests=False)
        paths = [f["path"] for f in result["files"]]
        assert "tests/test_x.py" not in paths
        assert "app.py" in paths

    def test_exclude_docs(self, tmp_path):
        (tmp_path / "README.md").write_text("# Hi")
        (tmp_path / "app.py").write_text("x=1")
        result = rm.scan_repo(tmp_path, include_docs=False)
        paths = [f["path"] for f in result["files"]]
        assert "README.md" not in paths
        assert "app.py" in paths

    def test_max_files_limit(self, tmp_path):
        for i in range(10):
            (tmp_path / f"file_{i:02d}.py").write_text(f"# {i}")
        result = rm.scan_repo(tmp_path, max_files=5)
        assert len(result["files"]) == 5
        assert len(result["skipped_files"]) == 5
        assert result["files"][0]["path"] < result["files"][-1]["path"]

    def test_no_sensitive_content_read(self, tmp_path):
        (tmp_path / ".env").write_text("SECRET_KEY=abc123")
        result = rm.scan_repo(tmp_path)
        # .env is fully ignored, not present in any list
        paths = [f["path"] for f in result["files"]]
        skipped = [s["path"] for s in result["skipped_files"]]
        assert ".env" not in paths
        assert ".env" not in skipped

    def test_entrypoint_in_result(self, tmp_path):
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "local_llm_mcp_server.py").write_text("# mcp")
        (tmp_path / "lib.py").write_text("def helper(): pass")
        result = rm.scan_repo(tmp_path)
        entrypoints = {f["path"]: f["entrypoint"] for f in result["files"]}
        assert entrypoints.get("tools/local_llm_mcp_server.py") is True

    def test_summary_counts(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "plan.md").write_text("# Plan")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test(): pass")
        (tmp_path / "app.py").write_text("x=1")
        (tmp_path / "config.json").write_text("{}")
        result = rm.scan_repo(tmp_path)
        s = result["summary"]
        assert s["total_files"] == 4
        assert s["docs_files"] == 1
        assert s["test_files"] == 1
        assert s["source_files"] == 1
        assert s["config_files"] == 1

    def test_skipped_files_reason(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test(): pass")
        result = rm.scan_repo(tmp_path, include_tests=False)
        skipped = {s["path"]: s["reason"] for s in result["skipped_files"]}
        assert "tests/test_x.py" in skipped
        assert "include_tests=false" in skipped["tests/test_x.py"]


# ---------------------------------------------------------------------------
# build_repo_map
# ---------------------------------------------------------------------------

class TestBuildRepoMap:
    def test_schema_version(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        repo_map = rm.build_repo_map(tmp_path)
        assert repo_map["schema_version"] == 1
        assert repo_map["ok"] is True

    def test_has_git_head_field(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        repo_map = rm.build_repo_map(tmp_path)
        assert "git_head" in repo_map

    def test_has_cache_key(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        repo_map = rm.build_repo_map(tmp_path)
        assert len(repo_map["cache_key"]) == 20

    def test_has_all_schema_keys(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        repo_map = rm.build_repo_map(tmp_path)
        for key in ("schema_version", "repo_root", "git_head", "generated_at",
                     "generated_by", "cache_key", "ok", "summary", "files",
                     "skipped_files", "subsystems", "test_mapping", "risk_tags_legend"):
            assert key in repo_map, f"Missing key: {key}"

    def test_files_sorted_by_path(self, tmp_path):
        (tmp_path / "z.py").write_text("z")
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "m.py").write_text("m")
        repo_map = rm.build_repo_map(tmp_path)
        paths = [f["path"] for f in repo_map["files"]]
        assert paths == sorted(paths)
        assert paths[0] == "a.py"

    def test_subsystems_present(self, tmp_path):
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "local_llm_mcp_server.py").write_text("# mcp")
        (tmp_path / "README.md").write_text("# Hi")
        repo_map = rm.build_repo_map(tmp_path)
        assert "mcp" in repo_map["subsystems"]
        assert "docs" in repo_map["subsystems"]

    def test_test_mapping_in_schema(self, tmp_path):
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "preclassifier.py").write_text("# p")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_preclassifier.py").write_text("# test")
        repo_map = rm.build_repo_map(tmp_path)
        assert "tools/preclassifier.py" in repo_map["test_mapping"]

    def test_missing_root_returns_ok_false(self, tmp_path):
        repo_map = rm.build_repo_map(Path("/nonexistent/path/xyz"))
        assert repo_map["ok"] is False
        assert repo_map["files"] == []

    def test_risk_tags_legend_present(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        repo_map = rm.build_repo_map(tmp_path)
        assert isinstance(repo_map["risk_tags_legend"], dict)
        assert "mcp" in repo_map["risk_tags_legend"]

    def test_file_has_required_fields(self, tmp_path):
        (tmp_path / "app.py").write_text("print(1)")
        repo_map = rm.build_repo_map(tmp_path)
        f = repo_map["files"][0]
        for key in ("path", "role", "subsystem", "risk_tags", "entrypoint", "size", "mtime_ns"):
            assert key in f, f"Missing field: {key}"


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCLI:
    def test_json_flag_outputs_valid_json(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        import subprocess, sys
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(repo_root / "tools" / "local_llm_repo_map.py"),
             "--root", str(tmp_path), "--json"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["schema_version"] == 1

    def test_write_flag(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        out = tmp_path / "out" / "repo_map.json"
        import subprocess, sys
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, str(repo_root / "tools" / "local_llm_repo_map.py"),
             "--root", str(tmp_path), "--write", str(out)],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        assert result.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["ok"] is True
