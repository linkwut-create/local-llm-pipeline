"""Test installer append and idempotency behavior."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from install_local_llm_pipeline import append_policy, update_gitignore, POLICY_MARKER


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
