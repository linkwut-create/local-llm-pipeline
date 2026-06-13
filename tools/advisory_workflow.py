#!/usr/bin/env python3
"""
Advisory Workflow Preflight — route-aware task advisor.

Wraps router_explain + shadow_route_log into a single preflight check.
Outputs a recommended controller decision. Advisory-only:
never calls DeepSeek, never auto-executes, never modifies profiles.

Usage:
  py -3 tools/advisory_workflow.py "review current diff before commit"
  py -3 tools/advisory_workflow.py "prepare release gate v0.13.0"
  py -3 tools/advisory_workflow.py "check .env.production for credentials"
  py -3 tools/advisory_workflow.py --json "task description"

Decision rules (advisory-only):
  privacy=blocked              → cloud-blocked
  risk=high/critical + cloud   → pro-review
  medium + multi-file/feature  → flash-fallback
  low + local_profile          → local
  medium + local_profile       → local-first
  unknown                      → defer
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from router_explain import RouterEngine
from shadow_route_log import log as _shadow_log, SHADOW_DIR

_engine = RouterEngine()

# ── Decision engine ──

def _has_multi_file_signal(task: str, flash_cond: str) -> bool:
    """Heuristic: does the task or flash condition suggest multi-file scope?"""
    signals = ["across", "multi", "several", "multiple", "cross-cut",
               "service", "module", "layer", "tier"]
    lower = task.lower()
    if any(s in lower for s in signals):
        return True
    if flash_cond and any(s in flash_cond.lower() for s in
                          ["task_type=draft-feature", "task_type=draft-refactor",
                           "multi-file", "medium complexity"]):
        return True
    return False


def recommend_decision(task: str, cloud_ok: bool = False,
                       local_failures: int = 0) -> dict:
    """
    Analyze a task and return an advisory decision.

    Returns dict with all router fields plus:
      - recommended_controller_decision: str
      - advisory_only: True
    """
    decision = _engine.analyze(task)

    risk = decision.risk_level
    privacy = decision.privacy_status
    task_type = decision.task_type
    local_profile = decision.recommended_local_profile
    cloud = decision.cloud_allowed and cloud_ok
    flash_cond = decision.flash_escalation_condition or ""

    # ── Apply decision rules ──
    if privacy == "blocked":
        rec = "cloud-blocked"
    elif task_type == "unknown":
        rec = "defer"
    elif risk in ("high", "critical") and cloud:
        rec = "pro-review"
    elif local_failures >= 2 and cloud:
        rec = "flash-fallback"
    elif risk == "medium" and _has_multi_file_signal(task, flash_cond) and cloud:
        rec = "flash-fallback"
    elif risk == "low" and local_profile:
        rec = "local"
    elif risk == "medium" and local_profile:
        rec = "local-first"
    elif risk == "low" and not local_profile:
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


def run(task: str, cloud_ok: bool = False, local_failures: int = 0,
        notes: str = "", actual: str = "") -> dict:
    """Preflight: analyze, recommend, log to shadow routes, return result."""
    result = recommend_decision(task, cloud_ok=cloud_ok, local_failures=local_failures)

    # Record to shadow log
    _shadow_log(task,
                actual=actual,
                notes=f"preflight: {result['recommended_controller_decision']}"
                      f"{' ' + notes if notes else ''}",
                cloud_ok=cloud_ok)

    # Inject log path
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    result["log_path"] = str(SHADOW_DIR / f"{today}.jsonl")

    return result


# ── CLI ──

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Advisory Workflow Preflight — route-aware task advisor"
    )
    parser.add_argument("task", nargs="*", help="Task description")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--cloud-ok", action="store_true", help="Cloud escalation permitted")
    parser.add_argument("--local-failures", type=int, default=0,
                        help="Consecutive local model failures")
    parser.add_argument("--notes", default="", help="Free-form notes")
    parser.add_argument("--actual", default="",
                        help="Actual human decision (e.g. local-first, pro-review)")
    args = parser.parse_args()

    task = " ".join(args.task) if args.task else ""
    if not task:
        parser.print_help()
        sys.exit(1)

    result = run(task, cloud_ok=getattr(args, "cloud_ok", False),
                 local_failures=args.local_failures, notes=args.notes,
                 actual=args.actual)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        rec = result["recommended_controller_decision"]
        print(f"recommendation: {rec}")
        print(f"  type:     {result['router_task_type']}")
        print(f"  risk:     {result['router_risk_level']}")
        print(f"  privacy:  {result['router_privacy_status']}")
        print(f"  local:    {result['recommended_local_profile'] or '(none)'}")
        print(f"  cloud:    {result['cloud_allowed']}")
        print(f"  log:      {result['log_path']}")
        if result["flash_escalation_condition"]:
            print(f"  flash:    {result['flash_escalation_condition'][:100]}")
        if result["pro_escalation_condition"]:
            print(f"  pro:      {result['pro_escalation_condition'][:100]}")


if __name__ == "__main__":
    main()
