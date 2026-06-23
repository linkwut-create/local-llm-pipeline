#!/usr/bin/env python3
"""Pipeline Hook Manager — install, status, uninstall, doctor.

Usage:
  py -3 tools/pipeline_hooks.py install   [--local] [--dry-run]
  py -3 tools/pipeline_hooks.py status    [--json]
  py -3 tools/pipeline_hooks.py uninstall [--local] [--dry-run]
  py -3 tools/pipeline_hooks.py doctor

Idempotent install. Safe uninstall (removes only pipeline hooks).
Always backs up settings before modifying.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

SCRIPT_NAME = "tools/claude_hooks/route_enforcer.py"

# Canonical hook configuration
PIPELINE_HOOKS: dict[str, list[dict]] = {
    "UserPromptSubmit": [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": "{python} " + SCRIPT_NAME}],
        }
    ],
    "PreToolUse": [
        {
            "matcher": "Edit|Write|NotebookEdit|Bash|PowerShell|Agent",
            "hooks": [{"type": "command", "command": "{python} " + SCRIPT_NAME}],
        }
    ],
    "PostToolUse": [
        {
            "matcher": "Edit|Write|NotebookEdit|Bash|PowerShell",
            "hooks": [{"type": "command", "command": "{python} " + SCRIPT_NAME}],
        }
    ],
    "Stop": [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": "{python} " + SCRIPT_NAME}],
        }
    ],
}

# Hook events managed by the pipeline
PIPELINE_EVENTS = set(PIPELINE_HOOKS)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _find_python() -> str:
    """Return the best available Python command for this environment."""
    # Try current interpreter first
    if sys.executable:
        exe = Path(sys.executable)
        if exe.exists():
            return str(exe)
    # Try common names
    for cmd in ("python3", "python", "py -3"):
        try:
            subprocess.run(
                [cmd, "--version"], capture_output=True, timeout=5, check=False,
                shell=(" " in cmd),
            )
            return cmd
        except Exception:
            continue
    return "python3"


def _settings_path(local: bool = False) -> Path:
    """Return the path to settings.local.json or settings.json."""
    if local:
        return Path(".claude/settings.local.json")
    return Path(".claude/settings.json")


def _read_settings(local: bool = False) -> dict:
    """Read current settings, returning {} if none exist."""
    path = _settings_path(local)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _backup_settings(local: bool = False) -> Path | None:
    """Create a timestamped backup of the current settings file."""
    path = _settings_path(local)
    if not path.exists():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.backup-{ts}")
    shutil.copy2(path, backup)
    return backup


def _write_settings(settings: dict, local: bool = False) -> Path:
    """Write settings dict to file, creating parent dir if needed."""
    path = _settings_path(local)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _is_pipeline_hook(hook_entry: dict) -> bool:
    """Return True if a hook entry belongs to the pipeline."""
    if not isinstance(hook_entry, dict):
        return False
    sub_hooks = hook_entry.get("hooks", [])
    if not isinstance(sub_hooks, list):
        return False
    for h in sub_hooks:
        if isinstance(h, dict) and SCRIPT_NAME in h.get("command", ""):
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════

def install(local: bool = False, dry_run: bool = False) -> str:
    """Install pipeline hooks. Idempotent: re-running is safe."""
    python = _find_python()
    settings = _read_settings(local)
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    changed = False
    report_lines = []

    for event, new_entries in PIPELINE_HOOKS.items():
        existing = hooks.get(event, [])
        if not isinstance(existing, list):
            existing = []
        # Check if pipeline hook already present
        has_pipeline = any(_is_pipeline_hook(e) for e in existing)
        if has_pipeline:
            report_lines.append(f"  {event}: already installed (skipped)")
            continue
        # Build entries with resolved python path
        resolved = []
        for entry in new_entries:
            entry_copy = json.loads(json.dumps(entry))  # deep copy
            for h in entry_copy.get("hooks", []):
                if isinstance(h, dict):
                    h["command"] = h["command"].replace("{python}", python)
            resolved.append(entry_copy)
        hooks[event] = existing + resolved
        changed = True
        report_lines.append(f"  {event}: installed")

    if not changed:
        return "Pipeline hooks already installed.\n" + "\n".join(report_lines)

    settings["hooks"] = hooks

    if dry_run:
        return "DRY RUN — would install:\n" + "\n".join(report_lines)

    backup = _backup_settings(local)
    path = _write_settings(settings, local)
    lines = [
        f"Pipeline hooks installed to {path}",
    ]
    if backup:
        lines.append(f"Backup: {backup}")
    lines.extend(report_lines)
    return "\n".join(lines)


def status(local: bool = False, json_output: bool = False) -> str:
    """Show current hook installation status."""
    settings = _read_settings(local)
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    result = {
        "file": str(_settings_path(local)),
        "file_exists": _settings_path(local).exists(),
        "events": {},
        "pipeline_installed": False,
    }

    for event in PIPELINE_EVENTS:
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            entries = []
        pipeline_entries = [e for e in entries if _is_pipeline_hook(e)]
        other_entries = [e for e in entries if not _is_pipeline_hook(e)]
        result["events"][event] = {
            "pipeline_hooks": len(pipeline_entries),
            "other_hooks": len(other_entries),
            "installed": len(pipeline_entries) > 0,
        }
        if pipeline_entries:
            result["pipeline_installed"] = True

    if json_output:
        return json.dumps(result, ensure_ascii=False, indent=2)

    lines = [f"Hook status: {result['file']}"]
    if not result["file_exists"]:
        lines.append("  (file does not exist)")
        return "\n".join(lines)

    for event, info in result["events"].items():
        status_icon = "[OK]" if info["installed"] else "[--]"
        lines.append(
            f"  {status_icon} {event}: pipeline={info['pipeline_hooks']}, "
            f"other={info['other_hooks']}"
        )

    if result["pipeline_installed"]:
        lines.append("\nPipeline hooks: INSTALLED")
    else:
        lines.append("\nPipeline hooks: NOT INSTALLED")
    return "\n".join(lines)


def uninstall(local: bool = False, dry_run: bool = False) -> str:
    """Remove pipeline hooks. Leaves other hooks intact."""
    settings = _read_settings(local)
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    changed = False
    report_lines = []

    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        pipeline_entries = [e for e in entries if _is_pipeline_hook(e)]
        other_entries = [e for e in entries if not _is_pipeline_hook(e)]
        if pipeline_entries:
            hooks[event] = other_entries
            changed = True
            report_lines.append(f"  {event}: removed {len(pipeline_entries)} hook(s)")
        if not hooks[event]:
            del hooks[event]

    if not changed:
        return "No pipeline hooks found to remove."

    settings["hooks"] = hooks

    if dry_run:
        return "DRY RUN — would remove:\n" + "\n".join(report_lines)

    backup = _backup_settings(local)
    path = _write_settings(settings, local)
    lines = [f"Pipeline hooks uninstalled from {path}"]
    if backup:
        lines.append(f"Backup: {backup}")
    lines.extend(report_lines)
    return "\n".join(lines)


def doctor() -> str:
    """Verify hook health: script exists, Python works, settings valid."""
    lines = ["Pipeline Hook Doctor", "=" * 20]

    # 1. Check Python
    python = _find_python()
    try:
        r = subprocess.run(
            [python, "--version"], capture_output=True, text=True, timeout=10,
            shell=(" " in python),
        )
        if r.returncode == 0:
            lines.append(f"[OK] Python: {r.stdout.strip()}")
        else:
            lines.append(f"[FAIL] Python: {r.stderr.strip()}")
    except Exception as e:
        lines.append(f"[FAIL] Python not found: {e}")
        return "\n".join(lines)

    # 2. Check enforcer script
    enforcer = Path(SCRIPT_NAME)
    if enforcer.exists():
        lines.append(f"[OK] Enforcer script: {enforcer}")
    else:
        lines.append(f"[FAIL] Enforcer script not found: {enforcer}")

    # 3. Check import
    try:
        r = subprocess.run(
            [python, "-c", f"import sys; sys.path.insert(0, 'tools'); "
             f"from claude_hooks.route_enforcer import main; print('OK')"],
            capture_output=True, text=True, timeout=15,
            shell=(" " in python),
        )
        if r.returncode == 0:
            lines.append("[OK] route_enforcer imports successfully")
        else:
            lines.append(f"[WARN] route_enforcer import: {r.stderr.strip()[:200]}")
    except Exception as e:
        lines.append(f"[WARN] Could not test import: {e}")

    # 4. Check hook settings
    for loc_flag, name in ((False, "project"), (True, "local")):
        path = _settings_path(local=loc_flag)
        if path.exists():
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
                hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
                installed = 0
                for event in PIPELINE_EVENTS:
                    entries = hooks.get(event, [])
                    if isinstance(entries, list):
                        if any(_is_pipeline_hook(e) for e in entries):
                            installed += 1
                if installed == len(PIPELINE_EVENTS):
                    lines.append(f"[OK] {name} hooks: all {installed} events installed")
                elif installed > 0:
                    lines.append(f"[WARN] {name} hooks: {installed}/{len(PIPELINE_EVENTS)} events installed")
                else:
                    lines.append(f"[INFO] {name} hooks: not installed")
            except Exception as e:
                lines.append(f"[FAIL] {name} settings: {e}")
        else:
            lines.append(f"[INFO] {name} settings: file not found")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Pipeline Hook Manager — install, status, uninstall, doctor")
    parser.add_argument("command", choices=["install", "status", "uninstall", "doctor"])
    parser.add_argument("--local", action="store_true",
                        help="Use settings.local.json instead of settings.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without doing it")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (status only)")
    args = parser.parse_args()

    try:
        if args.command == "install":
            print(install(local=args.local, dry_run=args.dry_run))
        elif args.command == "status":
            print(status(local=args.local, json_output=args.json))
        elif args.command == "uninstall":
            print(uninstall(local=args.local, dry_run=args.dry_run))
        elif args.command == "doctor":
            print(doctor())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
