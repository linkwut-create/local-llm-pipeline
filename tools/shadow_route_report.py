#!/usr/bin/env python3
"""
Shadow Route Report Exporter — dogfood metrics from shadow routing JSONL logs.

Reads `.local_llm_out/shadow_routes/*.jsonl` and produces a structured quality
report to help decide whether the router is ready for Stop hook reminder,
budget guard integration, or needs further calibration.

Usage:
  py -3 tools/shadow_route_report.py
  py -3 tools/shadow_route_report.py --since 2026-06-13
  py -3 tools/shadow_route_report.py --json
  py -3 tools/shadow_route_report.py --output .local_llm_out/shadow_route_report.md

Design:
  - Advisory-only: never calls DeepSeek API, never calls any LLM.
  - Read-only: reads shadow route logs, writes report only.
  - No profile changes, no source mutation.
  - Output constrained to .local_llm_out/ or user-specified safe path.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
SHADOW_DIR = PROJECT_ROOT / ".local_llm_out" / "shadow_routes"
OUTPUT_DIR = PROJECT_ROOT / ".local_llm_out"

# ── Task types that require Pro review ──
PRO_REQUIRED_TYPES = {"release-risk-review", "security-review", "interface-review", "architecture-review"}

# ── Risk levels considered "high risk" ──
HIGH_RISK_LEVELS = {"high", "critical"}


def _load_records(since: Optional[str] = None) -> list[dict]:
    """Load all shadow route records, optionally filtered by date."""
    records = []
    if not SHADOW_DIR.exists():
        return records

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            # Try date-only format
            try:
                since_dt = datetime.strptime(since, "%Y-%m-%d")
            except ValueError:
                pass

    for f in sorted(SHADOW_DIR.glob("*.jsonl")):
        # Filter by filename date if --since provided
        if since_dt:
            try:
                file_date = datetime.strptime(f.stem, "%Y%m%d")
                if file_date < since_dt.replace(hour=0, minute=0, second=0, microsecond=0):
                    continue
            except ValueError:
                pass

        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        # Also filter by timestamp if --since provided
                        if since_dt and rec.get("timestamp"):
                            try:
                                rec_dt = datetime.fromisoformat(rec["timestamp"])
                                if rec_dt < since_dt:
                                    continue
                            except (ValueError, TypeError):
                                pass
                        records.append(rec)
                    except json.JSONDecodeError:
                        continue

    return records


def compute_report(since: Optional[str] = None) -> dict:
    """Compute aggregate metrics from shadow route records."""
    records = _load_records(since)

    if not records:
        return {
            "total_records": 0,
            "match_rate": None,
            "unknown_rate": None,
            "blocked_count": 0,
            "high_risk_count": 0,
            "privacy_bypass_count": 0,
            "false_cloud_on_secret_count": 0,
            "critical_misrouting_count": 0,
            "release_security_interface_pro_rate": None,
            "mismatch_examples": [],
            "recommendation": "no data — start dogfood logging",
            "_meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "since": since,
                "source_dir": str(SHADOW_DIR),
            },
        }

    total = len(records)

    # Match / unknown breakdown
    matched = [r for r in records if r.get("match") is True]
    unmatched = [r for r in records if r.get("match") is False]
    unknown = [r for r in records if r.get("match") is None]

    match_rate = round(len(matched) / max(len(matched) + len(unmatched), 1), 3)
    unknown_rate = round(len(unknown) / max(total, 1), 3)

    # Privacy blocked
    blocked = [r for r in records if r.get("router_privacy_status") == "blocked"]
    blocked_count = len(blocked)

    # High risk
    high_risk = [r for r in records if r.get("router_risk_level") in HIGH_RISK_LEVELS]
    high_risk_count = len(high_risk)

    # Privacy bypass: router says blocked but cloud_allowed is True (data integrity)
    privacy_bypass_count = sum(
        1 for r in blocked if r.get("router_cloud_allowed") is True
    )

    # False cloud on secret: router says blocked but human used cloud
    CLOUD_DECISIONS = {"pro-review", "flash-fallback", "cloud"}
    false_cloud_on_secret_count = 0
    for r in blocked:
        actual = r.get("actual_decision", "").lower().strip()
        if actual in CLOUD_DECISIONS:
            false_cloud_on_secret_count += 1

    # Critical misrouting: high/critical risk but human disagreed (match=false)
    critical_misrouting_count = sum(
        1 for r in high_risk if r.get("match") is False
    )

    # Release/security/interface Pro accuracy
    pro_tasks = [r for r in records if r.get("router_task_type") in PRO_REQUIRED_TYPES]
    if pro_tasks:
        pro_correct = sum(
            1 for r in pro_tasks
            if r.get("match") is True
            and "pro" in r.get("actual_decision", "").lower()
        )
        release_security_interface_pro_rate = round(pro_correct / len(pro_tasks), 3)
    else:
        release_security_interface_pro_rate = None

    # Mismatch examples (up to 5)
    mismatch_examples = []
    for r in unmatched[:5]:
        mismatch_examples.append({
            "task": r.get("task", ""),
            "router_type": r.get("router_task_type", "?"),
            "router_risk": r.get("router_risk_level", "?"),
            "actual": r.get("actual_decision", ""),
            "notes": r.get("notes", ""),
        })

    # Recommendation
    recommendation = _make_recommendation(
        total, match_rate, critical_misrouting_count, unknown_rate
    )

    return {
        "total_records": total,
        "match_rate": match_rate,
        "unknown_rate": unknown_rate,
        "blocked_count": blocked_count,
        "high_risk_count": high_risk_count,
        "privacy_bypass_count": privacy_bypass_count,
        "false_cloud_on_secret_count": false_cloud_on_secret_count,
        "critical_misrouting_count": critical_misrouting_count,
        "release_security_interface_pro_rate": release_security_interface_pro_rate,
        "mismatch_examples": mismatch_examples,
        "recommendation": recommendation,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "since": since,
            "source_dir": str(SHADOW_DIR),
        },
    }


def _make_recommendation(
    total: int,
    match_rate: Optional[float],
    critical_misrouting: int,
    unknown_rate: Optional[float],
) -> str:
    """Produce a human-readable recommendation based on metrics."""
    if total == 0:
        return "no data — start dogfood logging"

    if total < 30:
        return (
            f"continue dogfood — only {total} records (need ≥30 for stable metrics). "
            "Keep logging shadow routes through precommit_advisory and advisory_workflow."
        )

    if critical_misrouting > 0:
        return (
            f"needs router calibration — {critical_misrouting} critical misrouting(s) "
            "detected (high-risk task where human overrode router). Review mismatch "
            "examples and adjust router rules before advancing to Stop hook."
        )

    if match_rate is not None and match_rate < 0.70:
        return (
            f"needs router calibration — match rate {match_rate:.0%} below 70% threshold. "
            "Router advice frequently disagrees with human decisions."
        )

    if (
        match_rate is not None
        and match_rate >= 0.85
        and critical_misrouting == 0
        and (unknown_rate is None or unknown_rate < 0.30)
    ):
        return (
            f"ready for Stop hook reminder — match rate {match_rate:.0%}, "
            "zero critical misrouting, unknown rate acceptable. "
            "Consider enabling post-advisory integration (Stop hook, budget guard)."
        )

    rate_str = f"{match_rate:.0%}" if match_rate is not None else "N/A"
    return (
        f"continue dogfood — match rate {rate_str}, "
        f"{'some concerns remain' if critical_misrouting > 0 else 'metrics trending positive'}. "
        "Continue collecting data before Stop hook integration."
    )


def format_report(report: dict, fmt: str = "markdown") -> str:
    """Format the report as Markdown or JSON."""
    if fmt == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    lines = []
    lines.append("# Shadow Route Report")
    lines.append("")
    lines.append(f"Generated: {report['_meta']['generated_at']}")
    if report["_meta"]["since"]:
        lines.append(f"Since: {report['_meta']['since']}")
    lines.append(f"Source: {report['_meta']['source_dir']}")
    lines.append("")

    total = report["total_records"]
    if total == 0:
        lines.append("## Result")
        lines.append("")
        lines.append("**No shadow route records found.**")
        lines.append("")
        lines.append("Start dogfood logging by running:")
        lines.append("```bash")
        lines.append("py -3 tools/precommit_advisory.py --cloud-ok")
        lines.append("py -3 tools/advisory_workflow.py \"<task>\" --cloud-ok")
        lines.append("```")
        lines.append("")
        lines.append("Recommendation: **start dogfood logging**")
        return "\n".join(lines)

    # ── Summary ──
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total records | {total} |")

    mr = report["match_rate"]
    if mr is not None:
        matched = int(round(mr * total))
        lines.append(f"| Match rate | {mr:.1%} ({matched}/{total}) |")
    else:
        lines.append(f"| Match rate | N/A (no decisions with actual) |")

    ur = report["unknown_rate"]
    if ur is not None:
        unknown_n = int(round(ur * total))
        lines.append(f"| Unknown rate | {ur:.1%} ({unknown_n}/{total}) |")
    else:
        lines.append(f"| Unknown rate | N/A |")

    lines.append(f"| Privacy blocked | {report['blocked_count']} |")
    lines.append(f"| High risk | {report['high_risk_count']} |")

    rsi = report["release_security_interface_pro_rate"]
    if rsi is not None:
        lines.append(f"| Release/Security/Interface Pro accuracy | {rsi:.1%} |")
    else:
        lines.append(f"| Release/Security/Interface Pro accuracy | N/A (no records) |")

    lines.append("")

    # ── Integrity Checks ──
    lines.append("## Integrity Checks")
    lines.append("")
    lines.append(f"| Check | Count | Status |")
    lines.append(f"|-------|-------|--------|")

    pbc = report["privacy_bypass_count"]
    lines.append(
        f"| Privacy bypass (blocked but cloud_allowed=true) | {pbc} | "
        f"{'✅ OK' if pbc == 0 else '⚠️ DATA ISSUE'} |"
    )

    fcc = report["false_cloud_on_secret_count"]
    lines.append(
        f"| False cloud on secret (blocked but used cloud) | {fcc} | "
        f"{'✅ OK' if fcc == 0 else '⚠️ POLICY VIOLATION'} |"
    )

    cmc = report["critical_misrouting_count"]
    lines.append(
        f"| Critical misrouting (high risk, human override) | {cmc} | "
        f"{'✅ OK' if cmc == 0 else '⚠️ NEEDS REVIEW'} |"
    )

    lines.append("")

    # ── Mismatch Examples ──
    mismatches = report.get("mismatch_examples", [])
    if mismatches:
        lines.append("## Mismatch Examples")
        lines.append("")
        lines.append("Top cases where router advice and human decision diverged:")
        lines.append("")
        for i, m in enumerate(mismatches, 1):
            lines.append(f"### {i}. {m['router_type']} / {m['router_risk']}")
            lines.append(f"- **Task**: {m['task']}")
            lines.append(f"- **Router said**: {m['router_type']} ({m['router_risk']})")
            lines.append(f"- **Human chose**: {m['actual']}")
            if m["notes"]:
                lines.append(f"- **Notes**: {m['notes']}")
            lines.append("")
    else:
        lines.append("## Mismatch Examples")
        lines.append("")
        lines.append("*No mismatches found — all human decisions aligned with router advice.*")
        lines.append("")

    # ── Recommendation ──
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"**{report['recommendation']}**")
    lines.append("")

    # ── Next Steps ──
    lines.append("## Next Steps")
    lines.append("")
    if "ready for Stop hook" in report["recommendation"]:
        lines.append("1. Enable post-advisory Stop hook in `.claude/settings.json`.")
        lines.append("2. Add budget guard integration.")
        lines.append("3. Begin DeepSeek Flash real-call testing (low-risk tasks only).")
    elif "needs router calibration" in report["recommendation"]:
        lines.append("1. Review mismatch examples above.")
        lines.append("2. Adjust router rules in `tools/router_explain.py`.")
        lines.append("3. Re-run report after 10+ new records.")
    else:
        lines.append("1. Continue running `precommit_advisory.py` before each commit.")
        lines.append("2. Continue running `advisory_workflow.py` for non-trivial tasks.")
        lines.append("3. Re-run this report when total records ≥ 30.")
    lines.append("")

    return "\n".join(lines)


def _validate_output_path(path_str: str) -> Path:
    """Ensure output path is within .local_llm_out/ or explicitly safe."""
    out = Path(path_str).resolve()

    # Allow .local_llm_out/ subtree
    local_out = OUTPUT_DIR.resolve()
    try:
        out.relative_to(local_out)
        return out
    except ValueError:
        pass

    # Check if inside project root
    project_root = PROJECT_ROOT.resolve()
    try:
        out.relative_to(project_root)
        # It's inside the project but not under .local_llm_out/ — reject
        raise ValueError(
            f"Output path '{path_str}' is inside project but not under .local_llm_out/.\n"
            f"Use a path under .local_llm_out/ or an external directory."
        )
    except ValueError as e:
        # Check if this is our raised error or from relative_to
        if "not under .local_llm_out" in str(e):
            raise
        # Not inside project — allowed (user's explicit choice)
        return out


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Shadow Route Report Exporter — dogfood metrics from shadow routing logs"
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only include records from this date (YYYY-MM-DD or ISO format)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON instead of Markdown",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write report to file (default: stdout). Must be under .local_llm_out/ or external.",
    )
    args = parser.parse_args()

    report = compute_report(since=args.since)
    fmt = "json" if args.json else "markdown"
    output = format_report(report, fmt=fmt)

    if args.output:
        out_path = _validate_output_path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report written to {out_path}")
    else:
        # On Windows GBK terminals, safely encode for stdout
        try:
            print(output)
        except UnicodeEncodeError:
            print(output.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            ))


if __name__ == "__main__":
    main()
