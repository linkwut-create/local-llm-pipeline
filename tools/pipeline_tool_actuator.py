"""Pipeline Tool Actuator — mechanical, verified, traceable tool operations.

Operations are scoped to a task and NEVER destroy user work. Every
mutation is captured as a diff artifact.

Usage::

    py -3 tools/pipeline_tool_actuator.py apply-patch <task_id> <patch_file>
    py -3 tools/pipeline_tool_actuator.py run-tests <task_id>
    py -3 tools/pipeline_tool_actuator.py capture-diff <task_id> <label>
    py -3 tools/pipeline_tool_actuator.py rollback <task_id>
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=30, check=False,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════
# Diff capture
# ═══════════════════════════════════════════════════════════════

def capture_diff(task_id: str, label: str) -> Path | None:
    """Capture current git diff as an artifact. Returns artifact path."""
    r = _git("diff")
    if not r.stdout.strip():
        return None

    from pipeline_artifact_store import save_artifact
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    return save_artifact(
        task_id, f"git_diff_{label}_{ts}.diff",
        r.stdout,
        artifact_type="git_diff", tool_name="pipeline_tool_actuator",
        creator="controller",
        metadata={"label": label, "timestamp": _now()},
    )


# ═══════════════════════════════════════════════════════════════
# Patch application
# ═══════════════════════════════════════════════════════════════

def apply_patch(task_id: str, patch_path: str | Path,
                target_dir: str | Path = ".") -> dict:
    """Apply a unified diff patch safely.

    1. Capture pre-patch diff
    2. Validate patch safety
    3. Apply with git apply --check first
    4. Capture post-patch diff
    5. Return result with rollback info
    """
    patch_file = Path(patch_path)
    target = Path(target_dir).resolve()

    result = {
        "ok": False,
        "task_id": task_id,
        "patch": str(patch_file),
        "pre_diff_artifact": None,
        "post_diff_artifact": None,
        "error": None,
        "rollback_command": None,
        "applied_at": _now(),
    }

    if not patch_file.exists():
        result["error"] = f"patch file not found: {patch_file}"
        return result

    patch_text = patch_file.read_text(encoding="utf-8")

    # Validate patch
    from pipeline_flash_worker import validate_patch
    valid, reason = validate_patch(patch_text)
    if not valid:
        result["error"] = f"patch validation failed: {reason}"
        return result

    # Capture pre-patch diff
    pre = capture_diff(task_id, "pre_patch")
    result["pre_diff_artifact"] = str(pre) if pre else None

    # Check if patch applies cleanly
    r = _git("apply", "--check", str(patch_file), cwd=target)
    if r.returncode != 0:
        result["error"] = f"patch does not apply cleanly: {r.stderr[:500]}"
        return result

    # Apply
    r = _git("apply", str(patch_file), cwd=target)
    if r.returncode != 0:
        result["error"] = f"git apply failed: {r.stderr[:500]}"
        return result

    result["ok"] = True
    result["rollback_command"] = f"git apply -R {patch_file}"

    # Save as artifact
    from pipeline_artifact_store import save_artifact, mark_accepted
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    save_artifact(
        task_id, f"applied_patch_{ts}.diff",
        patch_text,
        artifact_type="patch_candidate", tool_name="pipeline_tool_actuator",
        creator="controller", accepted=True,
        metadata={"applied_at": _now(), "pre_diff": result["pre_diff_artifact"]},
    )

    # Capture post-patch diff
    post = capture_diff(task_id, "post_patch")
    result["post_diff_artifact"] = str(post) if post else None

    return result


# ═══════════════════════════════════════════════════════════════
# Test runner
# ═══════════════════════════════════════════════════════════════

def detect_test_command(repo_root: str | Path = ".") -> str | None:
    """Detect the project's test command."""
    root = Path(repo_root)
    candidates = [
        ("pytest", "python -m pytest tests/ -v"),
        ("tox", "tox"),
        ("Makefile", None),  # check targets below
        ("package.json", None),
    ]

    for filename, default in candidates:
        if (root / filename).exists() or filename == "pytest":
            if filename == "pytest" and (root / "tests").exists():
                return "python -m pytest tests/ -v"
            if filename == "package.json":
                try:
                    pkg = json.loads((root / "package.json").read_text())
                    if "test" in pkg.get("scripts", {}):
                        return "npm test"
                except Exception:
                    pass
            if filename == "Makefile":
                try:
                    content = (root / "Makefile").read_text()
                    if "test:" in content or "test " in content:
                        return "make test"
                except Exception:
                    pass
            if filename == "tox" and (root / "tox.ini").exists():
                return "tox"

    # Fallback: look for test directory
    if (root / "tests").exists() or (root / "test").exists():
        return "python -m pytest tests/ -v"

    return None


def run_tests(task_id: str, command: str | None = None,
              repo_root: str | Path = ".", timeout: int = 300) -> dict:
    """Run tests and capture results as artifacts.

    Returns structured result with pass/fail counts and log paths.
    """
    root = Path(repo_root)

    if command is None:
        command = detect_test_command(root)
    if command is None:
        return {"ok": False, "error": "no test command detected"}

    t0 = subprocess.timeout if hasattr(subprocess, 'timeout') else __import__('time').monotonic()
    import time as _time
    t0 = _time.monotonic()

    try:
        r = subprocess.run(
            command, shell=True, cwd=str(root),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"tests timed out after {timeout}s",
                "command": command}
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command}

    elapsed = round(_time.monotonic() - t0, 1)

    # Parse pytest-style summary
    stdout = r.stdout or ""
    passed = failed = skipped = 0
    m = re.search(r'(\d+)\s+passed', stdout)
    if m: passed = int(m.group(1))
    m = re.search(r'(\d+)\s+failed', stdout)
    if m: failed = int(m.group(1))
    m = re.search(r'(\d+)\s+skipped', stdout)
    if m: skipped = int(m.group(1))

    # Save logs
    from pipeline_artifact_store import save_artifact
    ts = datetime.now(timezone.utc).strftime("%H%M%S")

    log_text = f"STDOUT:\n{stdout}\n\nSTDERR:\n{r.stderr or ''}"
    log_path = save_artifact(
        task_id, f"test_run_{ts}.log",
        log_text,
        artifact_type="test_run", tool_name="pipeline_tool_actuator",
        creator="controller",
        metadata={"command": command, "passed": passed, "failed": failed,
                  "skipped": skipped, "exit_code": r.returncode,
                  "duration_sec": elapsed},
    )

    # Also record in AgentDB if available
    try:
        from agentdb import insert_test_run
        insert_test_run(task_id, {
            "command": command, "passed": passed, "failed": failed,
            "skipped": skipped, "duration_sec": elapsed,
            "log_artifact": str(log_path),
            "timestamp": _now(),
        })
    except Exception:
        pass

    return {
        "ok": r.returncode == 0,
        "command": command,
        "passed": passed, "failed": failed, "skipped": skipped,
        "exit_code": r.returncode,
        "duration_sec": elapsed,
        "log_artifact": str(log_path),
    }


# ═══════════════════════════════════════════════════════════════
# Rollback
# ═══════════════════════════════════════════════════════════════

def rollback(task_id: str, patch_file: str | Path | None = None) -> dict:
    """Roll back task changes.

    If patch_file is given, reverse-apply it.
    Otherwise, use git to restore files modified by the task.
    """
    result = {"ok": False, "task_id": task_id, "method": "unknown"}

    if patch_file:
        pf = Path(patch_file)
        if not pf.exists():
            result["error"] = f"patch file not found: {pf}"
            return result
        r = _git("apply", "-R", str(pf))
        result["method"] = "reverse_patch"
        result["ok"] = r.returncode == 0
        if not result["ok"]:
            result["error"] = r.stderr[:500]
        return result

    # No patch given — capture diff and revert unstaged changes
    pre = capture_diff(task_id, "pre_rollback")
    r = _git("checkout", "--", ".")
    result["method"] = "git_checkout"
    result["ok"] = r.returncode == 0
    if not result["ok"]:
        result["error"] = r.stderr[:500]
    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Pipeline Tool Actuator — mechanical, verified operations")
    sub = parser.add_subparsers(dest="cmd")

    ap = sub.add_parser("apply-patch", help="Safely apply a unified diff patch")
    ap.add_argument("task_id")
    ap.add_argument("patch_file")

    rt = sub.add_parser("run-tests", help="Detect and run project tests")
    rt.add_argument("task_id")
    rt.add_argument("--command", default=None)
    rt.add_argument("--timeout", type=int, default=300)

    cd = sub.add_parser("capture-diff", help="Capture current git diff")
    cd.add_argument("task_id")
    cd.add_argument("label")

    rb = sub.add_parser("rollback", help="Roll back task changes")
    rb.add_argument("task_id")
    rb.add_argument("--patch", default=None)

    args = parser.parse_args()

    try:
        if args.cmd == "apply-patch":
            result = apply_patch(args.task_id, args.patch_file)
        elif args.cmd == "run-tests":
            result = run_tests(args.task_id, args.command, timeout=args.timeout)
        elif args.cmd == "capture-diff":
            path = capture_diff(args.task_id, args.label)
            result = {"ok": path is not None, "artifact": str(path) if path else None}
        elif args.cmd == "rollback":
            result = rollback(args.task_id, args.patch)
        else:
            parser.print_help()
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok", True) else 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
