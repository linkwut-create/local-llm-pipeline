#!/usr/bin/env python3
"""
Clean old .local_llm_out/ files.

Usage:
    python tools/clean_local_llm_out.py                    # delete files older than 7 days
    python tools/clean_local_llm_out.py --days 3           # delete files older than 3 days
    python tools/clean_local_llm_out.py --all              # delete all output files
    python tools/clean_local_llm_out.py --dry-run          # show what would be deleted
    python tools/clean_local_llm_out.py --keep-latest 10   # keep the 10 most recent, delete rest
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_OUTPUT_DIR = ".local_llm_out"
DEFAULT_DAYS = 7


def find_output_dir() -> Path:
    cwd = Path.cwd()
    out = cwd / DEFAULT_OUTPUT_DIR
    if out.exists():
        return out
    # try git root
    import subprocess
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        out = Path(root) / DEFAULT_OUTPUT_DIR
        if out.exists():
            return out
    except Exception:
        pass
    return cwd / DEFAULT_OUTPUT_DIR


def get_output_files(out_dir: Path) -> list[Path]:
    if not out_dir.exists():
        return []
    files = []
    for f in out_dir.iterdir():
        if f.is_file() and f.suffix in (".json", ".md"):
            files.append(f)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def main():
    parser = argparse.ArgumentParser(description="Clean old .local_llm_out/ files")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Delete files older than N days (default: {DEFAULT_DAYS})")
    parser.add_argument("--all", action="store_true", help="Delete all output files")
    parser.add_argument("--keep-latest", type=int, default=None,
                        help="Keep the N most recent files, delete the rest")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    parser.add_argument("--dir", default=None, help="Output directory path")

    args = parser.parse_args()

    out_dir = Path(args.dir) if args.dir else find_output_dir()
    if not out_dir.exists():
        print(f"Output directory not found: {out_dir}")
        print("Nothing to clean.")
        return 0

    files = get_output_files(out_dir)
    if not files:
        print(f"No output files in: {out_dir}")
        return 0

    total_size = sum(f.stat().st_size for f in files)
    print(f"Found {len(files)} files in {out_dir} ({total_size / 1024:.1f} KB)")

    to_delete = []

    if args.all:
        to_delete = files
    elif args.keep_latest is not None:
        to_delete = files[args.keep_latest:]
    else:
        cutoff = datetime.now() - timedelta(days=args.days)
        for f in files:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                to_delete.append(f)

    if not to_delete:
        print("Nothing to delete.")
        return 0

    delete_size = sum(f.stat().st_size for f in to_delete)
    print(f"\n{'Would delete' if args.dry_run else 'Deleting'} {len(to_delete)} files ({delete_size / 1024:.1f} KB):\n")

    for f in to_delete:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        age = (datetime.now() - mtime).days
        print(f"  {'[DRY]' if args.dry_run else '[DEL]'} {f.name} ({age}d old, {f.stat().st_size / 1024:.1f} KB)")
        if not args.dry_run:
            f.unlink()

    remaining = len(files) - len(to_delete)
    print(f"\n{'Would keep' if args.dry_run else 'Kept'} {remaining} files.")

    if args.dry_run:
        print("\nRun without --dry-run to apply.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
