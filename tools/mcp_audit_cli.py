#!/usr/bin/env python3
"""
MCP Audit CLI — minimal query tool (MCP-AUDIT-4).

Usage:
    python tools/mcp_audit_cli.py summary --phase MCP-AUDIT-3
    python tools/mcp_audit_cli.py failures --project local-llm-pipeline
    python tools/mcp_audit_cli.py blocked-commits
    python tools/mcp_audit_cli.py rejected-recommendations
    python tools/mcp_audit_cli.py tool-reliability
    python tools/mcp_audit_cli.py import-jsonl
    python tools/mcp_audit_cli.py generate-report --phase MCP-AUDIT-3
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure tools/ is on path for local imports
sys.path.insert(0, str(Path(__file__).parent))


def _error(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def _print_text_table(rows: list[dict], columns: list[str] | None = None):
    """Print a list of dicts as an aligned text table."""
    if not rows:
        print("No records found.")
        return
    cols = columns or list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for row in rows:
        for c in cols:
            v = str(row.get(c, ""))
            widths[c] = max(widths[c], len(v))
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols))


def _get_conn(base_dir: str | None = None):
    """Get a DB connection or print error and exit."""
    import mcp_audit_db as db
    try:
        conn = db.connect_audit_db(base_dir)
        return conn
    except Exception:
        print(
            "Audit DB not found. Run: python tools/mcp_audit_cli.py import-jsonl",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_summary(args) -> int:
    import mcp_audit_db as db
    conn = _get_conn(args.base_dir)
    try:
        result = db.summarize_phase(conn, args.phase)
        if not result:
            print("No records found.")
            return 0
        if args.format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            for k, v in result.items():
                print(f"{k}: {v}")
        return 0
    except Exception:
        print("No records found.")
        return 0
    finally:
        conn.close()


def cmd_failures(args) -> int:
    import mcp_audit_db as db
    conn = _get_conn(args.base_dir)
    rows = db.list_failures(conn, args.project, args.phase)
    conn.close()
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        _print_text_table(
            [dict(r) for r in rows],
            ["failure_type", "severity", "tool_name", "resolved", "created_at"],
        )
    return 0


def cmd_blocked_commits(args) -> int:
    import mcp_audit_db as db
    conn = _get_conn(args.base_dir)
    rows = db.list_blocked_commits(conn, args.project)
    conn.close()
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        _print_text_table(
            [dict(r) for r in rows],
            ["id", "project_name", "phase_id", "created_at", "notes"],
        )
    return 0


def cmd_rejected_recommendations(args) -> int:
    import mcp_audit_db as db
    conn = _get_conn(args.base_dir)
    rows = db.list_rejected_recommendations(conn, args.project)
    conn.close()
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        _print_text_table(
            [dict(r) for r in rows],
            ["id", "recommendation", "severity", "decision_reason", "created_at"],
        )
    return 0


def cmd_tool_reliability(args) -> int:
    import mcp_audit_db as db
    conn = _get_conn(args.base_dir)
    rows = db.tool_reliability_summary(conn)
    conn.close()
    if args.format == "json":
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        _print_text_table([dict(r) for r in rows],
                          ["tool_name", "total_calls", "failure_count",
                           "blocked_count", "timeout_count", "failure_rate"])
    return 0


def cmd_import_jsonl(args) -> int:
    import mcp_audit_db as db
    result = db.import_audit_jsonl(args.base_dir)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        for k, v in result.items():
            print(f"{k}: {v}")
    return 0


def cmd_generate_report(args) -> int:
    import mcp_audit_report as report_mod
    path = report_mod.write_phase_report(
        args.base_dir, args.phase, args.project, args.output_dir
    )
    if path:
        print(f"Report written: {path}")
    else:
        print("ERROR: Failed to generate report.", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcp_audit_cli",
        description="MCP Audit CLI — query and manage audit records",
    )
    parser.add_argument("--base-dir", default=None,
                        help="Project root (audit DB at .mcp_audit/mcp_audit.db)")

    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["text", "json", "markdown"],
                        default="text")

    phase_filter = argparse.ArgumentParser(add_help=False)
    phase_filter.add_argument("--phase", default=None, help="Filter by phase ID")
    phase_filter.add_argument("--project", default=None, help="Filter by project name")

    # summary
    p = sub.add_parser("summary", parents=[common, phase_filter],
                       help="Summarize phase")
    p.set_defaults(func=cmd_summary)

    # failures
    p = sub.add_parser("failures", parents=[common, phase_filter],
                       help="List failures")
    p.set_defaults(func=cmd_failures)

    # blocked-commits
    p = sub.add_parser("blocked-commits", parents=[common, phase_filter],
                       help="List blocked commits")
    p.set_defaults(func=cmd_blocked_commits)

    # rejected-recommendations
    p = sub.add_parser("rejected-recommendations", parents=[common, phase_filter],
                       help="List rejected recommendations")
    p.set_defaults(func=cmd_rejected_recommendations)

    # tool-reliability
    p = sub.add_parser("tool-reliability", parents=[common],
                       help="Show tool reliability summary")
    p.set_defaults(func=cmd_tool_reliability)

    # import-jsonl
    p = sub.add_parser("import-jsonl", parents=[common],
                       help="Import JSONL files into SQLite")
    p.set_defaults(func=cmd_import_jsonl)

    # generate-report
    p = sub.add_parser("generate-report", parents=[phase_filter],
                       help="Generate phase audit report")
    p.add_argument("--output-dir", default=None,
                   help="Output directory for report")
    p.set_defaults(func=cmd_generate_report)

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        raise
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
