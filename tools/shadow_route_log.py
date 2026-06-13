#!/usr/bin/env python3
"""
Shadow Routing Log — record router_explain advisory decisions for later comparison.

Usage:
  py -3 tools/shadow_route_log.py "review current diff before commit" --actual "local-first"
  py -3 tools/shadow_route_log.py "prepare release gate" --actual "pro-review"
  py -3 tools/shadow_route_log.py --list
  py -3 tools/shadow_route_log.py --stats

Design:
  - Advisory-only: never calls DeepSeek API, never auto-executes tasks.
  - JSONL output to .local_llm_out/shadow_routes/YYYYMMDD.jsonl.
  - Router decision comes from tools/router_explain.py (mock-only).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SHADOW_DIR = PROJECT_ROOT / ".local_llm_out" / "shadow_routes"
OUTPUT_DIR = PROJECT_ROOT / ".local_llm_out"

# Ensure router_explain importable
sys.path.insert(0, str(SCRIPT_DIR))
from router_explain import RouterEngine

_engine = RouterEngine()

CANONICAL_ACTUALS = {"local", "local-first", "flash-fallback", "pro-review", "cloud-blocked", "defer"}
LEGACY_ACTUALS = {"local-only"}
VALID_ACTUALS = CANONICAL_ACTUALS | LEGACY_ACTUALS


def _ensure_dir():
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)


def _today_file() -> Path:
    return SHADOW_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def _auto_match(router_risk: str, router_cloud: bool, actual: str) -> bool:
    """Heuristic match between router suggestion and human decision."""
    a = actual.lower().strip()
    if router_risk in ("high", "critical") and ("pro" in a or "cloud" in a):
        return True
    if router_risk == "low" and ("local" in a or "docs" in a):
        return True
    if router_risk == "medium" and ("flash" in a or "local" in a):
        return True
    if not router_cloud and "blocked" in a:
        return True
    return False


def log(task: str, actual: str = "", notes: str = "", cloud_ok: bool = False) -> dict:
    """Record one shadow routing entry. Returns the record dict."""
    _ensure_dir()

    decision = _engine.analyze(task)

    actual_clean = actual.strip() if actual else ""
    if actual_clean and actual_clean not in VALID_ACTUALS:
        return {
            "error": (f"invalid actual '{actual_clean}'. "
                      f"Canonical: {', '.join(sorted(CANONICAL_ACTUALS))}. "
                      f"Legacy: {', '.join(sorted(LEGACY_ACTUALS))}."),
            "written": False,
        }
    match = _auto_match(decision.risk_level, decision.cloud_allowed, actual_clean) if actual_clean else None

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "router_task_type": decision.task_type,
        "router_risk_level": decision.risk_level,
        "router_privacy_status": decision.privacy_status,
        "router_recommended_local_profile": decision.recommended_local_profile,
        "router_flash_condition": decision.flash_escalation_condition,
        "router_pro_condition": decision.pro_escalation_condition,
        "router_cloud_allowed": decision.cloud_allowed,
        "actual_decision": actual_clean,
        "match": match,
        "notes": notes.strip(),
    }

    with open(_today_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def list_records(days: int = 7) -> list[dict]:
    """List records from the last N days."""
    records = []
    if not SHADOW_DIR.exists():
        return records
    for f in sorted(SHADOW_DIR.glob("*.jsonl"), reverse=True)[:days]:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return records


def stats(days: int = 30) -> dict:
    """Return aggregate stats from shadow records."""
    records = list_records(days)
    if not records:
        return {"total": 0}

    matched = [r for r in records if r.get("match") is True]
    unmatched = [r for r in records if r.get("match") is False]
    unknown = [r for r in records if r.get("match") is None]

    task_types = {}
    for r in records:
        t = r.get("router_task_type", "?")
        task_types[t] = task_types.get(t, 0) + 1

    risk_levels = {}
    for r in records:
        rl = r.get("router_risk_level", "?")
        risk_levels[rl] = risk_levels.get(rl, 0) + 1

    return {
        "total": len(records),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "unknown_match": len(unknown),
        "accuracy": round(len(matched) / max(len(matched) + len(unmatched), 1), 3),
        "by_task_type": task_types,
        "by_risk_level": risk_levels,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Shadow Routing Log — record router_explain advisory decisions"
    )
    parser.add_argument("task", nargs="*", help="Task description")
    parser.add_argument("--actual", default="", help="Human actual decision (e.g. local-first)")
    parser.add_argument("--notes", default="", help="Free-form notes")
    parser.add_argument("--cloud-ok", action="store_true", help="Cloud escalation permitted")
    parser.add_argument("--list", action="store_true", help="List recent shadow records")
    parser.add_argument("--stats", action="store_true", help="Show aggregate shadow stats")
    parser.add_argument("--json", action="store_true", help="Output as JSON (for --list/--stats)")
    args = parser.parse_args()

    if args.stats:
        s = stats()
        if args.json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
        else:
            print(f"Shadow Routing Stats ({s.get('total',0)} records)")
            if s.get("total", 0) > 0:
                print(f"  accuracy: {s['accuracy']:.0%} ({s['matched']}/{s['matched']+s['unmatched']})")
                print(f"  unknown:  {s['unknown_match']}")
                print(f"  by risk:  {s['by_risk_level']}")
                print(f"  by type:  {s['by_task_type']}")
        return

    if args.list:
        records = list_records()
        if args.json:
            print(json.dumps(records, ensure_ascii=False, indent=2))
        else:
            for r in records[:20]:
                m = "✓" if r.get("match") is True else ("✗" if r.get("match") is False else "?")
                print(f"[{m}] {r['router_task_type']:22s} {r['router_risk_level']:4s} | {r['task'][:60]}")
                if r.get("actual_decision"):
                    print(f"     actual: {r['actual_decision']}")
            if len(records) > 20:
                print(f"  ... and {len(records)-20} more records")
        return

    task = " ".join(args.task) if args.task else ""
    if not task:
        parser.print_help()
        sys.exit(1)

    record = log(task, actual=args.actual, notes=args.notes, cloud_ok=getattr(args, "cloud_ok", False))
    print(f"Shadow logged: {record['router_task_type']} / {record['router_risk_level']}")
    print(f"  -> {_today_file()}")


if __name__ == "__main__":
    main()
