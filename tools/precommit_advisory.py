#!/usr/bin/env python3
"""
Non-blocking precommit advisory — route-aware commit preflight.

Reads the current git diff, calls advisory_workflow to get a routing
recommendation, prints it, and records a shadow log entry.

ALWAYS exits 0. Never blocks commit. Never calls DeepSeek.
Never calls any LLM. Never modifies profiles.

Usage:
  py -3 tools/precommit_advisory.py
  py -3 tools/precommit_advisory.py --json
  py -3 tools/precommit_advisory.py --cloud-ok
  py -3 tools/precommit_advisory.py --task "review current diff before commit"
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from router_explain import RouterEngine
from shadow_route_log import log as _shadow_log, SHADOW_DIR

_engine = RouterEngine()


# ── Git helpers ──

def _run_git(args: list[str], cwd: Path = None) -> str:
    """Run a git command, return stdout or ''."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True,
            cwd=str(cwd or PROJECT_ROOT),
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _diff_summary() -> str:
    """Return a summary of the current working-tree diff."""
    stat = _run_git(["diff", "--stat"])
    if stat:
        # Extract just the changed file list
        lines = stat.split("\n")
        if len(lines) >= 2:
            # Last line is summary "N files changed...", preceding lines are files
            files = [l.split("|")[0].strip() for l in lines[:-1] if "|" in l]
            if files:
                return "review current diff: " + ", ".join(files[:8])
            return "review current git diff before commit"
        return "review current git diff before commit"

    # Try staged diff
    staged = _run_git(["diff", "--cached", "--stat"])
    if staged:
        return "review staged git diff before commit"

    return ""


def _build_task(override: str = "") -> str:
    """Build the task description. Prefers explicit --task, else git diff."""
    if override:
        return override
    diff_task = _diff_summary()
    if diff_task:
        return diff_task
    return "review current git diff before commit (no diff detected)"


# ── From advisory_workflow, inlined to avoid circular import risk ──

def _recommend(task: str, cloud_ok: bool = False,
               local_failures: int = 0) -> dict:
    """Minimal inline decision engine (mirrors advisory_workflow rules)."""
    decision = _engine.analyze(task)
    risk = decision.risk_level
    privacy = decision.privacy_status
    task_type = decision.task_type
    local_profile = decision.recommended_local_profile
    cloud = decision.cloud_allowed and cloud_ok

    if privacy == "blocked":
        rec = "cloud-blocked"
    elif task_type == "unknown":
        rec = "defer"
    elif risk in ("high", "critical") and cloud:
        rec = "pro-review"
    elif local_failures >= 2 and cloud:
        rec = "flash-fallback"
    elif risk == "medium" and cloud:
        rec = "flash-fallback"
    elif risk == "low" and local_profile:
        rec = "local"
    elif risk == "medium" and local_profile:
        rec = "local-first"
    else:
        rec = "local-first"

    return {
        "task": task,
        "router_task_type": task_type,
        "router_risk_level": risk,
        "router_privacy_status": privacy,
        "recommended_local_profile": local_profile,
        "recommended_controller_decision": rec,
        "flash_escalation_condition": decision.flash_escalation_condition,
        "pro_escalation_condition": decision.pro_escalation_condition,
        "cloud_allowed": cloud,
        "advisory_only": True,
        "local_failures": local_failures,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ──

def run(cloud_ok: bool = False, task_override: str = "") -> dict:
    """Run precommit advisory and return the result dict."""
    task = _build_task(task_override)

    # Check for no-diff early
    if not task_override and _diff_summary() == "":
        no_diff_task = task  # "no diff detected" task
    else:
        no_diff_task = ""

    result = _recommend(task, cloud_ok=cloud_ok)

    # Write shadow log
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_path = str(SHADOW_DIR / f"{today}.jsonl")

    _shadow_log(
        task,
        actual="",
        notes=f"precommit: {result['recommended_controller_decision']}"
              f"{' (no diff)' if no_diff_task else ''}",
        cloud_ok=cloud_ok,
    )

    result["log_path"] = log_path
    result["has_diff"] = bool(_diff_summary())
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Precommit advisory — non-blocking route check before commit"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Allow cloud escalation suggestions")
    parser.add_argument("--task", default="",
                        help="Override auto-generated task description")
    args = parser.parse_args()

    result = run(cloud_ok=args.cloud_ok, task_override=args.task)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        rec = result["recommended_controller_decision"]
        has_diff = " (no diff)" if not result.get("has_diff") else ""
        print(f"precommit advisory: {rec}{has_diff}")
        print(f"  type:     {result['router_task_type']}")
        print(f"  risk:     {result['router_risk_level']}")
        print(f"  privacy:  {result['router_privacy_status']}")
        print(f"  local:    {result['recommended_local_profile'] or '(none)'}")
        print(f"  cloud:    {result['cloud_allowed']}")
        print(f"  log:      {result['log_path']}")
        if result.get("flash_escalation_condition"):
            print(f"  flash:    {result['flash_escalation_condition'][:120]}")
        if result.get("pro_escalation_condition"):
            print(f"  pro:      {result['pro_escalation_condition'][:120]}")

    # ALWAYS exit 0 — this is non-blocking advisory
    sys.exit(0)


if __name__ == "__main__":
    main()
