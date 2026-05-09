#!/usr/bin/env python3
"""
Install the local LLM pipeline into any target project.

Copies tools/, docs/, .codex/, .claude/ and appends policy sections
to AGENTS.md, CLAUDE.md, .gitignore without overwriting existing content.

Usage:
    python install_local_llm_pipeline.py C:\\path\\to\\project
    python install_local_llm_pipeline.py C:\\path\\to\\project --dry-run
    python install_local_llm_pipeline.py C:\\path\\to\\project --force
    python install_local_llm_pipeline.py C:\\path\\to\\project --skip-claude --skip-codex
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()

COPY_DIRS = ["tools", "docs"]
OPTIONAL_COPY_DIRS = {
    "claude": ".claude",
    "codex": ".codex",
}

APPEND_FILES = {
    "AGENTS.md": "AGENTS.md",
    "CLAUDE.md": "CLAUDE.md",
}

GITIGNORE_LINES = [
    "",
    "# Local LLM worker output (generated, not committed)",
    ".local_llm_out/",
]

POLICY_MARKER = "## Local Multi-Model Worker Policy"


def is_git_repo(path: Path) -> bool:
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path), stderr=subprocess.DEVNULL, text=True
        )
        return True
    except Exception:
        return False


SKIP_FILES = {"settings.local.json", "settings.json"}

def copy_dir(src: Path, dst: Path, dry_run: bool, force: bool) -> list[str]:
    actions = []
    for src_file in src.rglob("*"):
        if src_file.is_dir():
            continue
        if "__pycache__" in src_file.parts:
            continue
        if src_file.name in SKIP_FILES:
            actions.append(f"  SKIP (local config): {src_file.name}")
            continue
        rel = src_file.relative_to(src)
        dst_file = dst / rel

        if dst_file.exists() and not force:
            actions.append(f"  SKIP (exists): {dst_file}")
            continue

        action = "OVERWRITE" if dst_file.exists() else "COPY"
        actions.append(f"  {action}: {dst_file}")
        if not dry_run:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

    return actions


def append_policy(src_file: Path, dst_file: Path, dry_run: bool) -> list[str]:
    actions = []
    policy_content = src_file.read_text(encoding="utf-8")

    if dst_file.exists():
        existing = dst_file.read_text(encoding="utf-8")
        if POLICY_MARKER in existing:
            actions.append(f"  SKIP (policy already present): {dst_file}")
            return actions

        actions.append(f"  APPEND policy to: {dst_file}")
        if not dry_run:
            with open(dst_file, "a", encoding="utf-8") as f:
                f.write("\n\n")
                marker_idx = policy_content.find(POLICY_MARKER)
                if marker_idx >= 0:
                    f.write(policy_content[marker_idx:])
                else:
                    f.write(policy_content)
    else:
        actions.append(f"  CREATE: {dst_file}")
        if not dry_run:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

    return actions


def update_gitignore(target: Path, dry_run: bool) -> list[str]:
    actions = []
    gitignore = target / ".gitignore"

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if ".local_llm_out/" in content:
            actions.append(f"  SKIP (.local_llm_out already in .gitignore)")
            return actions
        actions.append(f"  APPEND .local_llm_out/ to .gitignore")
        if not dry_run:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n".join(GITIGNORE_LINES) + "\n")
    else:
        actions.append(f"  CREATE: .gitignore")
        if not dry_run:
            gitignore.write_text("\n".join(GITIGNORE_LINES).lstrip() + "\n", encoding="utf-8")

    return actions


def run_health_check(target: Path) -> bool:
    check_script = target / "tools" / "local_llm_check.py"
    if not check_script.exists():
        print("  WARNING: tools/local_llm_check.py not found in target")
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(check_script)],
            cwd=str(target), timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  WARNING: health check failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Install local LLM pipeline into a target project"
    )
    parser.add_argument("target", help="Target project root directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without making changes")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files in tools/ and docs/")
    parser.add_argument("--skip-claude", action="store_true",
                        help="Skip .claude/ directory (agents, commands)")
    parser.add_argument("--skip-codex", action="store_true",
                        help="Skip .codex/ directory")
    parser.add_argument("--skip-health-check", action="store_true",
                        help="Skip post-install health check")

    args = parser.parse_args()
    target = Path(args.target).resolve()

    if args.dry_run:
        print("=== DRY RUN MODE — no changes will be made ===\n")

    if not target.exists():
        print(f"ERROR: Target directory does not exist: {target}")
        sys.exit(1)

    if not is_git_repo(target):
        print(f"WARNING: {target} is not a git repository.")
        print("  The pipeline works best inside a git project.")
        print("  Continue anyway? (The install will proceed.)\n")

    if target.resolve() == PIPELINE_ROOT:
        print("ERROR: Cannot install into the pipeline project itself.")
        sys.exit(1)

    all_actions = []

    print(f"Installing local LLM pipeline into: {target}\n")

    # Copy tools/ and docs/
    for dirname in COPY_DIRS:
        src = PIPELINE_ROOT / dirname
        dst = target / dirname
        print(f"[{dirname}/]")
        actions = copy_dir(src, dst, args.dry_run, args.force)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        print()

    # Copy .claude/ (optional)
    if not args.skip_claude:
        src = PIPELINE_ROOT / ".claude"
        dst = target / ".claude"
        print("[.claude/]")
        actions = copy_dir(src, dst, args.dry_run, args.force)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        print()

    # Copy .codex/ (optional)
    if not args.skip_codex:
        src = PIPELINE_ROOT / ".codex"
        dst = target / ".codex"
        print("[.codex/]")
        actions = copy_dir(src, dst, args.dry_run, args.force)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        print()

    # Append to AGENTS.md and CLAUDE.md
    for name, filename in APPEND_FILES.items():
        src = PIPELINE_ROOT / filename
        dst = target / filename
        print(f"[{filename}]")
        actions = append_policy(src, dst, args.dry_run)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        print()

    # Update .gitignore
    print("[.gitignore]")
    actions = update_gitignore(target, args.dry_run)
    all_actions.extend(actions)
    for a in actions:
        print(a)
    print()

    # Summary
    copies = sum(1 for a in all_actions if "COPY:" in a or "CREATE:" in a or "APPEND" in a or "OVERWRITE:" in a)
    skips = sum(1 for a in all_actions if "SKIP" in a)

    print("=" * 60)
    if args.dry_run:
        print(f"DRY RUN: {copies} files would be written, {skips} skipped")
        print("Run without --dry-run to apply changes.")
    else:
        print(f"INSTALLED: {copies} files written, {skips} skipped")

        # Post-install health check
        if not args.skip_health_check:
            print("\nRunning post-install health check...")
            print("-" * 40)
            ok = run_health_check(target)
            print("-" * 40)
            if ok:
                print("Health check: PASSED")
            else:
                print("Health check: ISSUES FOUND (see above)")

        print(f"\nPipeline installed at: {target}")
        print("\nNext steps:")
        print(f"  cd {target}")
        print(f"  python tools/local_llm_router.py summarize-tree src --max-files 30")
        print(f"  git diff | python tools/local_llm_router.py review-diff --stdin")

    return 0


if __name__ == "__main__":
    sys.exit(main())
