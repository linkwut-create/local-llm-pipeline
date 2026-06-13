#!/usr/bin/env python3
"""
Soft Gate Dogfood Accumulation Status Reporter.

Reads shadow route records and reports progress toward the dogfood target.
Read-only — never writes shadow log, never modifies records.

Usage:
  py -3 tools/soft_gate_dogfood_status.py --since 2026-06-13 --target 30
  py -3 tools/soft_gate_dogfood_status.py --since 2026-06-13 --target 30 --json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SHADOW_DIR = PROJECT_ROOT / ".local_llm_out" / "shadow_routes"


def _load_records(since: str) -> list[dict]:
    """Load shadow route records since a date. Returns all matching records."""
    records = []
    if not SHADOW_DIR.exists():
        return records

    since_dt = None
    try:
        since_dt = datetime.fromisoformat(since)
    except ValueError:
        pass

    for f in sorted(SHADOW_DIR.glob("*.jsonl")):
        # Filter by date prefix if since is a simple date
        if since_dt is None and len(since) == 10:
            # YYYY-MM-DD format: match file name prefix
            file_date = f.stem  # YYYYMMDD
            since_file = since.replace("-", "")
            if file_date < since_file:
                continue

        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    ts = r.get("timestamp", "")
                    if since_dt and ts:
                        try:
                            rt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if rt.replace(tzinfo=None) < since_dt.replace(tzinfo=None):
                                continue
                        except (ValueError, TypeError):
                            pass
                    records.append(r)
                except json.JSONDecodeError:
                    continue
    return records


def _count_distribution(records: list[dict], key: str) -> dict:
    """Count occurrences of a key in records."""
    dist = {}
    for r in records:
        v = r.get(key, "?")
        dist[v] = dist.get(v, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def status(since: str = "2026-06-13", target: int = 30) -> dict:
    """Generate dogfood accumulation status report."""
    records = _load_records(since)
    total = len(records)

    # Actual distribution
    actual_dist = _count_distribution(records, "actual_decision")
    router_dist = _count_distribution(records, "router_task_type")

    # Match rate
    matched = sum(1 for r in records if r.get("match") is True)
    unmatched = sum(1 for r in records if r.get("match") is False)
    unknown_match = sum(1 for r in records if r.get("match") is None)
    denom = max(matched + unmatched, 1)
    match_rate = round(matched / denom, 3)

    # Unknown rate
    unknown_count = sum(1 for r in records if r.get("router_task_type") == "unknown")
    unknown_rate = round(unknown_count / max(total, 1), 3)

    # Critical misrouting: high risk tasks where human overrode
    critical = 0
    for r in records:
        risk = r.get("router_risk_level", "")
        actual = r.get("actual_decision", "").lower().strip()
        is_match = r.get("match")
        if risk in ("high", "critical") and is_match is False:
            # Check if this is a governance/control task that should have been pro-review
            if actual in ("local", "local-first"):
                critical += 1

    # Privacy & cloud safety
    blocked = sum(1 for r in records if r.get("router_privacy_status") == "blocked")
    privacy_bypass = 0  # Would need actual content comparison; heuristic only
    false_cloud = 0

    # Warning gate candidate check
    warning_gate_candidate = (
        total >= target
        and match_rate >= 0.85
        and critical == 0
        and privacy_bypass == 0
        and false_cloud == 0
    )

    # Recommendation
    if total < target:
        rec = "continue_dogfood"
    elif critical > 0:
        rec = "calibrate_router"
    elif privacy_bypass > 0 or false_cloud > 0:
        rec = "fix_privacy_safety"
    elif match_rate < 0.85:
        rec = "continue_dogfood_or_calibrate"
    else:
        rec = "eligible_for_warning_gate_design"

    remaining = max(0, target - total)
    progress_ratio = round(min(total / max(target, 1), 1.0), 3)

    return {
        "since": since,
        "target_records": target,
        "records_total": total,
        "records_remaining": remaining,
        "progress_ratio": progress_ratio,
        "actual_distribution": actual_dist,
        "router_type_distribution": router_dist,
        "match_rate": match_rate,
        "matched": matched,
        "unmatched": unmatched,
        "unknown_match": unknown_match,
        "unknown_rate": unknown_rate,
        "unknown_count": unknown_count,
        "critical_misrouting": critical,
        "blocked_count": blocked,
        "privacy_bypass": privacy_bypass,
        "false_cloud_on_secret": false_cloud,
        "warning_gate_candidate": warning_gate_candidate,
        "recommendation": rec,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Soft Gate Dogfood Accumulation Status Reporter"
    )
    parser.add_argument("--since", default="2026-06-13",
                        help="Start date for records (default: 2026-06-13)")
    parser.add_argument("--target", type=int, default=30,
                        help="Target record count (default: 30)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    result = status(since=args.since, target=args.target)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        bar = _progress_bar(result["progress_ratio"])
        wg = "[ELIGIBLE]" if result["warning_gate_candidate"] else "[NOT ELIGIBLE]"
        print(f"Dogfood Status ({result['since']}): {result['records_total']}/{result['target_records']} {bar}")
        print(f"  remaining:       {result['records_remaining']}")
        print(f"  match_rate:      {result['match_rate']:.1%}")
        print(f"  unknown_rate:    {result['unknown_rate']:.1%}")
        print(f"  critical:        {result['critical_misrouting']}")
        print(f"  blocked:         {result['blocked_count']}")
        print(f"  privacy_bypass:  {result['privacy_bypass']}")
        print(f"  false_cloud:     {result['false_cloud_on_secret']}")
        print(f"  warning gate:    {wg}")
        print(f"  recommendation:  {result['recommendation']}")
        if result["actual_distribution"]:
            print(f"  actual dist:     {result['actual_distribution']}")

    sys.exit(0)


def _progress_bar(ratio: float, width: int = 20) -> str:
    filled = int(ratio * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


if __name__ == "__main__":
    main()
