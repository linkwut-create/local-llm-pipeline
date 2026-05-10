"""
v0.9.5 — Version provenance fix: VERSION must be read from source repo,
not the target project.

Covers:
1. VERSION = 0.9.5
2. MCP server / global launcher version matches VERSION
3. _read_version() reads from LOCAL_LLM_SOURCE_REPO, not target project
4. Target project VERSION does NOT pollute pipeline version
5. output_dir still writes to target project .local_llm_out
6. path validation still uses target project boundary
7. _get_source_repo_root() fallback chain correct
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Phase 1: Version consistency                                                  #
# --------------------------------------------------------------------------- #

def test_version_file_is_095():
    vf = PROJECT_ROOT / "VERSION"
    assert vf.exists(), "VERSION file is missing"
    content = vf.read_text(encoding="utf-8").strip()
    assert content == "0.9.5", f"VERSION should be 0.9.5, got: {content}"


def test_mcp_server_version_matches_version_file():
    vf = PROJECT_ROOT / "VERSION"
    expected = vf.read_text(encoding="utf-8").strip()
    mcp = importlib.import_module("local_llm_mcp_server")
    assert mcp.SERVER_VERSION == expected, (
        f"MCP server version {mcp.SERVER_VERSION} != VERSION {expected}"
    )


def test_global_launcher_version_matches_version_file():
    vf = PROJECT_ROOT / "VERSION"
    expected = vf.read_text(encoding="utf-8").strip()
    launcher = importlib.import_module("local_llm_global_mcp_launcher")
    assert launcher.SERVER_VERSION == expected, (
        f"Global launcher version {launcher.SERVER_VERSION} != VERSION {expected}"
    )


# --------------------------------------------------------------------------- #
# Phase 2: _get_source_repo_root() exists                                       #
# --------------------------------------------------------------------------- #

def test_mcp_server_has_get_source_repo_root():
    mcp = importlib.import_module("local_llm_mcp_server")
    assert callable(mcp._get_source_repo_root), (
        "_get_source_repo_root must be a callable"
    )


def test_get_source_repo_root_returns_project_root_by_default(monkeypatch):
    mcp = importlib.import_module("local_llm_mcp_server")
    monkeypatch.delenv("LOCAL_LLM_SOURCE_REPO", raising=False)
    result = mcp._get_source_repo_root()
    assert result is not None
    assert result.exists()


def test_get_source_repo_root_uses_env_var(tmp_path, monkeypatch):
    mcp = importlib.import_module("local_llm_mcp_server")
    source = tmp_path / "pipeline"
    source.mkdir()
    (source / "VERSION").write_text("0.9.5", encoding="utf-8")
    monkeypatch.setenv("LOCAL_LLM_SOURCE_REPO", str(source))
    result = mcp._get_source_repo_root()
    assert result == source.resolve()


# --------------------------------------------------------------------------- #
# Phase 3: Version provenance — source repo, NOT target project                #
# --------------------------------------------------------------------------- #

def test_read_version_from_source_repo(tmp_path, monkeypatch):
    """When LOCAL_LLM_SOURCE_REPO is set, _read_version must use it."""
    mcp = importlib.import_module("local_llm_mcp_server")

    source = tmp_path / "pipeline"
    source.mkdir()
    (source / "VERSION").write_text("0.9.5", encoding="utf-8")

    target = tmp_path / "target_project"
    target.mkdir()
    (target / ".git").mkdir()

    monkeypatch.setenv("LOCAL_LLM_SOURCE_REPO", str(source))
    monkeypatch.setenv("LOCAL_LLM_TARGET_PROJECT", str(target))

    version = mcp._read_version()
    assert version == "0.9.5", f"Expected 0.9.5 from source repo, got: {version}"


def test_target_project_version_does_not_pollute(tmp_path, monkeypatch):
    """Target project VERSION must never be used as pipeline version."""
    mcp = importlib.import_module("local_llm_mcp_server")

    source = tmp_path / "pipeline"
    source.mkdir()
    (source / "VERSION").write_text("0.9.5", encoding="utf-8")

    target = tmp_path / "target_project"
    target.mkdir()
    (target / ".git").mkdir()
    # Target has a different VERSION — it must be IGNORED
    (target / "VERSION").write_text("0.1.0", encoding="utf-8")

    monkeypatch.setenv("LOCAL_LLM_SOURCE_REPO", str(source))
    monkeypatch.setenv("LOCAL_LLM_TARGET_PROJECT", str(target))

    version = mcp._read_version()
    assert version == "0.9.5", (
        f"Version must be 0.9.5 (source repo), not polluted by target VERSION 0.1.0. "
        f"Got: {version}"
    )


def test_read_version_falls_back_to_project_root(monkeypatch):
    """Without LOCAL_LLM_SOURCE_REPO, read from PROJECT_ROOT / VERSION."""
    mcp = importlib.import_module("local_llm_mcp_server")
    monkeypatch.delenv("LOCAL_LLM_SOURCE_REPO", raising=False)
    monkeypatch.delenv("LOCAL_LLM_TARGET_PROJECT", raising=False)

    version = mcp._read_version()
    assert version != "unknown", "Fallback to PROJECT_ROOT should find VERSION"
    assert version == "0.9.5"


def test_read_version_unknown_when_no_version_anywhere(tmp_path, monkeypatch):
    """When no VERSION exists anywhere, return 'unknown'."""
    mcp = importlib.import_module("local_llm_mcp_server")

    empty = tmp_path / "empty_repo"
    empty.mkdir()

    monkeypatch.setenv("LOCAL_LLM_SOURCE_REPO", str(empty))
    monkeypatch.delenv("LOCAL_LLM_TARGET_PROJECT", raising=False)
    # Also hide PROJECT_ROOT's VERSION by patching _get_source_repo_root
    monkeypatch.setattr(mcp, "PROJECT_ROOT", empty)
    monkeypatch.setattr(mcp, "_get_source_repo_root", lambda: empty)

    version = mcp._read_version()
    assert version == "unknown", f"Expected 'unknown', got: {version}"


# --------------------------------------------------------------------------- #
# Phase 4: output_dir still targets effective project                          #
# --------------------------------------------------------------------------- #

def test_output_dir_uses_target_project(tmp_path, monkeypatch):
    """find_latest_json_output must use target project's .local_llm_out."""
    mcp = importlib.import_module("local_llm_mcp_server")

    target = tmp_path / "target_project"
    target.mkdir()
    (target / ".git").mkdir()
    (target / ".local_llm_out").mkdir()

    monkeypatch.setenv("LOCAL_LLM_TARGET_PROJECT", str(target))
    monkeypatch.setenv("LOCAL_LLM_SOURCE_REPO", str(PROJECT_ROOT))

    # Patch the effective root to use the env var
    eff_root = mcp._get_effective_project_root()
    assert eff_root == target.resolve(), (
        f"Effective root should be target project, got {eff_root}"
    )


def test_find_latest_json_output_targets_effective_root(tmp_path, monkeypatch):
    """find_latest_json_output should look in target project's .local_llm_out."""
    mcp = importlib.import_module("local_llm_mcp_server")

    target = tmp_path / "target_project"
    target.mkdir()
    (target / ".git").mkdir()
    out_dir = target / ".local_llm_out"
    out_dir.mkdir()

    monkeypatch.setenv("LOCAL_LLM_TARGET_PROJECT", str(target))
    monkeypatch.setenv("LOCAL_LLM_SOURCE_REPO", str(PROJECT_ROOT))

    result = mcp.find_latest_json_output()
    assert result is None, f"Empty output dir should return None, got: {result}"


# --------------------------------------------------------------------------- #
# Phase 5: Path validation uses target project boundary                        #
# --------------------------------------------------------------------------- #

def test_path_validation_uses_target_boundary(tmp_path, monkeypatch):
    """Paths outside target project must be rejected."""
    mcp = importlib.import_module("local_llm_mcp_server")

    target = tmp_path / "target_project"
    target.mkdir()
    (target / ".git").mkdir()

    monkeypatch.setenv("LOCAL_LLM_TARGET_PROJECT", str(target))
    monkeypatch.delenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", raising=False)

    outside = tmp_path / "outside_file.txt"
    outside.write_text("hi", encoding="utf-8")

    ok, err = mcp.validate_path(str(outside))
    assert not ok, f"Path outside target project should be rejected: {err}"
    assert "outside" in err.lower()


def test_path_inside_target_project_is_allowed(tmp_path, monkeypatch):
    """Paths inside target project must be accepted."""
    mcp = importlib.import_module("local_llm_mcp_server")

    target = tmp_path / "target_project"
    target.mkdir()
    (target / ".git").mkdir()
    inside = target / "app.py"
    inside.write_text("print('hello')", encoding="utf-8")

    monkeypatch.setenv("LOCAL_LLM_TARGET_PROJECT", str(target))
    monkeypatch.delenv("LOCAL_LLM_ALLOW_OUTSIDE_PROJECT", raising=False)

    ok, err = mcp.validate_path(str(inside))
    assert ok, f"Path inside target project should be allowed: {err}"


# --------------------------------------------------------------------------- #
# Phase 6: Global launcher sets both env vars                                  #
# --------------------------------------------------------------------------- #

def test_global_launcher_sets_both_env_vars(tmp_path, monkeypatch):
    """Global launcher must set LOCAL_LLM_SOURCE_REPO and LOCAL_LLM_TARGET_PROJECT."""
    launcher = importlib.import_module("local_llm_global_mcp_launcher")

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    project = launcher.find_project_root()
    assert project == tmp_path

    valid, _ = launcher.validate_project(project)
    assert valid

    os.environ["LOCAL_LLM_TARGET_PROJECT"] = str(project)
    os.environ["LOCAL_LLM_SOURCE_REPO"] = str(launcher.PIPELINE_ROOT)

    assert os.environ["LOCAL_LLM_TARGET_PROJECT"] == str(project)
    assert os.environ["LOCAL_LLM_SOURCE_REPO"] == str(launcher.PIPELINE_ROOT)


def test_global_launcher_has_source_repo_env_reference():
    """Global launcher source code must reference LOCAL_LLM_SOURCE_REPO."""
    src = (TOOLS_DIR / "local_llm_global_mcp_launcher.py").read_text(encoding="utf-8")
    assert "LOCAL_LLM_SOURCE_REPO" in src, (
        "Global launcher must set LOCAL_LLM_SOURCE_REPO"
    )


# --------------------------------------------------------------------------- #
# Phase 7: SERVER_VERSION set at module load time                              #
# --------------------------------------------------------------------------- #

def test_mcp_server_version_not_hardcoded():
    """SERVER_VERSION must not be a hardcoded string literal in source."""
    src = (TOOLS_DIR / "local_llm_mcp_server.py").read_text(encoding="utf-8")
    assert "SERVER_VERSION = _read_version()" in src


def test_no_hardcoded_094_in_server_source():
    """MCP server source must not have hardcoded version 0.9.4."""
    src = (TOOLS_DIR / "local_llm_mcp_server.py").read_text(encoding="utf-8")
    assert 'SERVER_VERSION = "0.9.4"' not in src
    assert 'SERVER_VERSION = "0.9.5"' not in src


# --------------------------------------------------------------------------- #
# Phase 8: call_local_check includes version                                   #
# --------------------------------------------------------------------------- #

def test_call_local_check_includes_version():
    """call_local_check result must include pipeline version."""
    mcp = importlib.import_module("local_llm_mcp_server")
    result = mcp.call_local_check({})
    assert "version" in result, (
        f"call_local_check must include 'version' field. Keys: {list(result.keys())}"
    )
    assert result["version"] == mcp.SERVER_VERSION, (
        f"call_local_check version {result['version']} != {mcp.SERVER_VERSION}"
    )
