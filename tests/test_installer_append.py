"""Test installer append, idempotency, skip-files, and manifest behavior."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from install_local_llm_pipeline import (
    append_policy, update_gitignore, copy_dir, write_manifest, read_manifest,
    is_sensitive, POLICY_MARKER, SKIP_FILES, MANIFEST_FILENAME,
)


PIPELINE_ROOT = Path(__file__).parent.parent


def test_append_to_existing_agents_md():
    """Appending to an existing AGENTS.md should preserve original content."""
    src = PIPELINE_ROOT / "AGENTS.md"
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "AGENTS.md"
        dst.write_text("# My Project Agents\n\nSome existing content.\n", encoding="utf-8")

        actions = append_policy(src, dst, dry_run=False)

        content = dst.read_text(encoding="utf-8")
        assert "My Project Agents" in content
        assert "Some existing content" in content
        assert POLICY_MARKER in content


def test_no_duplicate_append():
    """If the policy marker already exists, append should skip."""
    src = PIPELINE_ROOT / "AGENTS.md"
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "AGENTS.md"
        dst.write_text(f"# Agents\n\n{POLICY_MARKER}\n\nAlready here.\n", encoding="utf-8")

        actions = append_policy(src, dst, dry_run=False)

        content = dst.read_text(encoding="utf-8")
        assert content.count(POLICY_MARKER) == 1
        assert any("SKIP" in a for a in actions)


def test_create_if_not_exists():
    """If the target file doesn't exist, it should be created."""
    src = PIPELINE_ROOT / "CLAUDE.md"
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "CLAUDE.md"
        assert not dst.exists()

        actions = append_policy(src, dst, dry_run=False)

        assert dst.exists()
        content = dst.read_text(encoding="utf-8")
        assert POLICY_MARKER in content


def test_gitignore_append():
    """Should append .local_llm_out/ to existing .gitignore."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        gi = target / ".gitignore"
        gi.write_text("*.pyc\n__pycache__/\n", encoding="utf-8")

        actions = update_gitignore(target, dry_run=False)

        content = gi.read_text(encoding="utf-8")
        assert "*.pyc" in content
        assert ".local_llm_out/" in content


def test_gitignore_no_duplicate():
    """Should not duplicate .local_llm_out/ entry."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        gi = target / ".gitignore"
        gi.write_text(".local_llm_out/\n", encoding="utf-8")

        actions = update_gitignore(target, dry_run=False)

        content = gi.read_text(encoding="utf-8")
        assert content.count(".local_llm_out/") == 1
        assert any("SKIP" in a for a in actions)


def test_gitignore_create():
    """Should create .gitignore if it doesn't exist."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        gi = target / ".gitignore"
        assert not gi.exists()

        actions = update_gitignore(target, dry_run=False)

        assert gi.exists()
        content = gi.read_text(encoding="utf-8")
        assert ".local_llm_out/" in content


def test_skip_files_contains_local_settings():
    """SKIP_FILES must include settings.local.json and settings.json."""
    assert "settings.local.json" in SKIP_FILES
    assert "settings.json" in SKIP_FILES


def test_copy_dir_skips_local_settings():
    """copy_dir should skip settings.local.json and settings.json."""
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)

            (src_path / "normal.txt").write_text("normal", encoding="utf-8")
            (src_path / "settings.local.json").write_text("{}", encoding="utf-8")
            (src_path / "settings.json").write_text("{}", encoding="utf-8")

            actions = copy_dir(src_path, dst_path, dry_run=False, force=False)

            assert (dst_path / "normal.txt").exists()
            assert not (dst_path / "settings.local.json").exists()
            assert not (dst_path / "settings.json").exists()
            assert any("SKIP" in a and "settings.local.json" in a for a in actions)
            assert any("SKIP" in a and "settings.json" in a for a in actions)


def test_copy_dir_dry_run_reports_skipped():
    """Dry-run should report skipped files without copying them."""
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)

            (src_path / "settings.local.json").write_text("{}", encoding="utf-8")

            actions = copy_dir(src_path, dst_path, dry_run=True, force=False)

            assert any("SKIP (local config)" in a for a in actions)


def test_gitignore_no_duplicate_on_reinstall():
    """Re-running installer should not duplicate .local_llm_out/."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        gi = target / ".gitignore"
        gi.write_text("*.pyc\n.local_llm_out/\n", encoding="utf-8")

        # First call
        update_gitignore(target, dry_run=False)
        # Second call (simulating reinstall)
        actions = update_gitignore(target, dry_run=False)

        content = gi.read_text(encoding="utf-8")
        assert content.count(".local_llm_out/") == 1
        assert any("SKIP" in a for a in actions)


# --- Manifest and update mode tests (v0.5.0) ---

def test_write_manifest_creates_file():
    """write_manifest should create .local_llm_pipeline.json."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        write_manifest(target, ["tools/x.py"], [".claude/settings.local.json"],
                       ["AGENTS.md"], dry_run=False)

        mf = target / MANIFEST_FILENAME
        assert mf.exists()

        data = json.loads(mf.read_text(encoding="utf-8"))
        assert "installed_version" in data
        assert "installed_at" in data
        assert data["source_project"] == "local-llm-pipeline"


def test_manifest_contains_managed_files():
    """Manifest should record managed files."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        write_manifest(target,
                       ["tools/local_llm_worker.py", "docs/local-llm-mcp.md"],
                       [], ["AGENTS.md"], dry_run=False)

        data = read_manifest(target)
        assert data is not None
        assert "tools/local_llm_worker.py" in data["managed_files"]
        assert "docs/local-llm-mcp.md" in data["managed_files"]


def test_manifest_contains_skipped_files():
    """Manifest should record skipped files."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        write_manifest(target, [],
                       [".claude/settings.local.json", ".claude/settings.json"],
                       ["AGENTS.md"], dry_run=False)

        data = read_manifest(target)
        assert ".claude/settings.local.json" in data["skipped_files"]


def test_dry_run_does_not_write_manifest():
    """--dry-run should not write manifest file."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        write_manifest(target, ["tools/x.py"], [], ["AGENTS.md"], dry_run=True)

        mf = target / MANIFEST_FILENAME
        assert not mf.exists()


def test_read_manifest_missing():
    """read_manifest should return None when manifest doesn't exist."""
    with tempfile.TemporaryDirectory() as tmp:
        result = read_manifest(Path(tmp))
        assert result is None


def test_read_manifest_valid():
    """read_manifest should parse an existing manifest correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        mf = target / MANIFEST_FILENAME
        mf.write_text(json.dumps({"installed_version": "v0.4.0",
                                   "source_project": "local-llm-pipeline"}),
                      encoding="utf-8")

        data = read_manifest(target)
        assert data is not None
        assert data["installed_version"] == "v0.4.0"


def test_update_mode_conflict_detection():
    """In update mode, user-modified files should be flagged as CONFLICT."""
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)

            src_file = src_path / "test.py"
            src_file.write_text("source content", encoding="utf-8")

            dst_sub = dst_path / "dst"
            dst_sub.mkdir()
            dst_file = dst_sub / "test.py"
            dst_file.write_text("user-modified content", encoding="utf-8")

            actions = copy_dir(src_path, dst_sub, dry_run=True, force=False,
                              update_mode=True, managed=[], skipped=[])

            assert any("CONFLICT (modified)" in a for a in actions)


def test_update_mode_unchanged_is_skipped():
    """In update mode, unchanged files should be skipped."""
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)

            content = "same content"
            src_file = src_path / "test.py"
            src_file.write_text(content, encoding="utf-8")

            dst_sub = dst_path / "dst"
            dst_sub.mkdir()
            dst_file = dst_sub / "test.py"
            dst_file.write_text(content, encoding="utf-8")

            actions = copy_dir(src_path, dst_sub, dry_run=True, force=False,
                              update_mode=True, managed=[], skipped=[])

            assert any("SKIP (unchanged)" in a for a in actions)


def test_is_sensitive_detects_env():
    assert is_sensitive(".env")
    assert is_sensitive(".env.local")
    assert is_sensitive("key.pem")
    assert not is_sensitive("normal.py")


def test_sensitive_files_skipped():
    """Sensitive files should be skipped during copy."""
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)

            (src_path / ".env").write_text("secret", encoding="utf-8")
            (src_path / "id_rsa").write_text("key", encoding="utf-8")
            (src_path / "normal.py").write_text("code", encoding="utf-8")

            actions = copy_dir(src_path, dst_path, dry_run=False, force=False)

            assert not (dst_path / ".env").exists()
            assert not (dst_path / "id_rsa").exists()
            assert (dst_path / "normal.py").exists()
            assert any("SKIP (sensitive)" in a for a in actions)


def test_legacy_install_update_without_manifest():
    """Update mode on a project without manifest (v0.4.x legacy) should
    correctly identify unchanged files by content hash."""
    with tempfile.TemporaryDirectory() as src:
        with tempfile.TemporaryDirectory() as dst:
            src_path = Path(src)
            dst_path = Path(dst)
            # Set up source file
            (src_path / "test.py").write_text("v0.5.0 content", encoding="utf-8")
            # Set up destination with a file that was installed by v0.4.0
            (dst_path / "test.py").write_text("v0.5.0 content", encoding="utf-8")

            # No manifest in dst — simulating legacy v0.4.x install
            assert not (dst_path / MANIFEST_FILENAME).exists()

            actions = copy_dir(src_path, dst_path, dry_run=True, force=False,
                              update_mode=True, managed=[], skipped=[])

            # Same content should be SKIP unchanged, not CONFLICT
            assert any("SKIP (unchanged)" in a for a in actions)
            assert not any("CONFLICT" in a for a in actions)
