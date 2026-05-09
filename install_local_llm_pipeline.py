#!/usr/bin/env python3
"""
Install the local LLM pipeline into any target project.

Copies tools/, docs/, .codex/, .claude/ and appends policy sections
to AGENTS.md, CLAUDE.md, .gitignore without overwriting existing content.

Usage:
    python install_local_llm_pipeline.py C:\\path\\to\\project
    python install_local_llm_pipeline.py C:\\path\\to\\project --dry-run
    python install_local_llm_pipeline.py C:\\path\\to\\project --force
    python install_local_llm_pipeline.py C:\\path\\to\\project --update
    python install_local_llm_pipeline.py C:\\path\\to\\project --skip-claude --skip-codex
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()

def _read_version() -> str:
    vf = PIPELINE_ROOT / "VERSION"
    if vf.exists():
        return vf.read_text(encoding="utf-8").strip()
    return "0.5.0"

PIPELINE_VERSION = f"v{_read_version()}"

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
MANIFEST_FILENAME = ".local_llm_pipeline.json"

SKIP_FILES = {"settings.local.json", "settings.json"}
SENSITIVE_EXTS = {".pem", ".key", ".p12", ".pfx", ".jks"}
SENSITIVE_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", ".env", ".env.local",
                    ".env.production", ".env.development"}


def is_git_repo(path: Path) -> bool:
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path), stderr=subprocess.DEVNULL, text=True
        )
        return True
    except Exception:
        return False


def file_hash(path: Path) -> str:
    """SHA256 hex digest of a file's contents."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def is_sensitive(file_name: str) -> bool:
    """Check if a file name or extension indicates sensitive content."""
    name = Path(file_name).name
    ext = Path(file_name).suffix
    return ext in SENSITIVE_EXTS or name in SENSITIVE_NAMES


def read_manifest(target: Path) -> dict | None:
    """Read existing install manifest, or None."""
    mf = target / MANIFEST_FILENAME
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_manifest(target: Path, managed: list[str], skipped: list[str],
                   policy_files: list[str], dry_run: bool) -> list[str]:
    """Write .local_llm_pipeline.json. Returns action lines."""
    actions = []
    mf = target / MANIFEST_FILENAME
    existing = read_manifest(target)
    action = "UPDATE manifest" if existing else "CREATE manifest"

    manifest = {
        "installed_version": PIPELINE_VERSION,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "source_project": "local-llm-pipeline",
        "managed_files": sorted(set(managed)),
        "skipped_files": sorted(set(skipped)),
        "policy_markers": [f for f in policy_files],
    }
    actions.append(f"  {action}: {MANIFEST_FILENAME}")
    if not dry_run:
        mf.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return actions


def copy_dir(src: Path, dst: Path, dry_run: bool, force: bool,
             managed: list[str] | None = None, skipped: list[str] | None = None,
             update_mode: bool = False) -> list[str]:
    actions = []
    for src_file in src.rglob("*"):
        if src_file.is_dir():
            continue
        if "__pycache__" in src_file.parts:
            continue
        if src_file.name in SKIP_FILES:
            actions.append(f"  SKIP (local config): {src_file.name}")
            if skipped is not None:
                skipped.append(str(src_file.relative_to(PIPELINE_ROOT)))
            continue
        if is_sensitive(src_file.name):
            actions.append(f"  SKIP (sensitive): {src_file.name}")
            if skipped is not None:
                skipped.append(str(src_file.relative_to(PIPELINE_ROOT)))
            continue

        rel = src_file.relative_to(src)
        dst_file = dst / rel
        rel_str = str(Path(dst.name) / rel)

        if dst_file.exists() and not force:
            if update_mode:
                src_hash = file_hash(src_file)
                dst_hash = file_hash(dst_file)
                if src_hash == dst_hash:
                    actions.append(f"  SKIP (unchanged): {dst_file}")
                    if managed is not None:
                        managed.append(rel_str)
                    continue
                else:
                    actions.append(f"  CONFLICT (modified): {dst_file}")
                    continue
            else:
                actions.append(f"  SKIP (exists): {dst_file}")
                continue

        action = "OVERWRITE" if dst_file.exists() else "COPY"
        actions.append(f"  {action}: {dst_file}")
        if managed is not None:
            managed.append(rel_str)
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
    parser.add_argument("--update", action="store_true",
                        help="Update an existing installation (requires manifest)")
    parser.add_argument("--skip-claude", action="store_true",
                        help="Skip .claude/ directory (agents, commands)")
    parser.add_argument("--skip-codex", action="store_true",
                        help="Skip .codex/ directory")
    parser.add_argument("--skip-health-check", action="store_true",
                        help="Skip post-install health check")

    args = parser.parse_args()
    target = Path(args.target).resolve()
    existing_manifest = read_manifest(target)
    update_mode = args.update or (existing_manifest is not None and not args.force)

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

    if existing_manifest:
        installed = existing_manifest.get("installed_version", "unknown")
        print(f"Found existing installation: {installed}")
        if args.update:
            print(f"Update mode: comparing with source v{PIPELINE_VERSION}\n")
        elif update_mode:
            print("Existing installation detected. Use --update to update, or --force to overwrite.\n")
        print()

    all_actions = []
    managed_files = []
    skipped_files = []
    policy_files = []

    mode_str = "--update" if (args.update or update_mode) else "install"
    print(f"Pipeline {PIPELINE_VERSION} ({mode_str}) -> {target}\n")

    common_kwargs = dict(
        dry_run=args.dry_run, force=args.force,
        managed=managed_files, skipped=skipped_files,
        update_mode=(args.update or update_mode),
    )

    # Copy tools/ and docs/
    for dirname in COPY_DIRS:
        src = PIPELINE_ROOT / dirname
        dst = target / dirname
        print(f"[{dirname}/]")
        actions = copy_dir(src, dst, **common_kwargs)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        print()

    # Copy .claude/ (optional)
    if not args.skip_claude:
        src = PIPELINE_ROOT / ".claude"
        dst = target / ".claude"
        print("[.claude/]")
        actions = copy_dir(src, dst, **common_kwargs)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        print()

    # Copy .codex/ (optional)
    if not args.skip_codex:
        src = PIPELINE_ROOT / ".codex"
        dst = target / ".codex"
        print("[.codex/]")
        actions = copy_dir(src, dst, **common_kwargs)
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
        if not args.dry_run:
            policy_files.append(filename)
        print()

    # Update .gitignore
    print("[.gitignore]")
    actions = update_gitignore(target, args.dry_run)
    all_actions.extend(actions)
    for a in actions:
        print(a)
    if not args.dry_run and any("APPEND" in a or "CREATE" in a for a in actions):
        policy_files.append(".gitignore")
    print()

    # Write manifest
    print(f"[{MANIFEST_FILENAME}]")
    manifest_actions = write_manifest(target, managed_files, skipped_files,
                                       policy_files, args.dry_run)
    all_actions.extend(manifest_actions)
    for a in manifest_actions:
        print(a)
    print()

    # Summary
    copies = sum(1 for a in all_actions if "COPY:" in a or "CREATE:" in a or "APPEND" in a or "OVERWRITE:" in a)
    skips = sum(1 for a in all_actions if "SKIP" in a)
    conflicts = sum(1 for a in all_actions if "CONFLICT" in a)

    print("=" * 60)
    parts = []
    if copies:
        parts.append(f"{copies} written")
    if skips:
        parts.append(f"{skips} skipped")
    if conflicts:
        parts.append(f"{conflicts} CONFLICTS")

    if args.dry_run:
        status = "DRY RUN: "
    elif args.update or update_mode:
        status = "UPDATED: "
    else:
        status = "INSTALLED: "

    print(f"{status}{', '.join(parts)}")

    if args.dry_run:
        print("Run without --dry-run to apply changes.")
    elif conflicts:
        print("WARNING: Conflicts detected. Review CONFLICT items above.")
        print("  Use --force to overwrite all, or resolve manually.")

    if not args.dry_run and not conflicts:
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

        print(f"\nPipeline {PIPELINE_VERSION} installed at: {target}")
        if args.update or update_mode:
            if existing_manifest:
                print(f"  Updated from: {existing_manifest.get('installed_version', 'unknown')}")
            else:
                print(f"  Updated from: legacy install (no manifest) — manifest now created")
        print("\nNext steps:")
        print(f"  cd {target}")
        print(f"  python tools/local_llm_router.py summarize-tree src --max-files 30")
        print(f"  git diff | python tools/local_llm_router.py review-diff --stdin")

    return 0 if conflicts == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
