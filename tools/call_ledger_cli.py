#!/usr/bin/env python3
"""Call Ledger CLI — query .local_llm_out/audit/calls.jsonl.

Subcommands:
    summary               aggregate totals across all records
    by-project            per-project totals
    by-task               per-task_type totals
    failures              list failing records
    recent [--limit N]    list the most recent N records (default 20)

All subcommands support `--path` to point at a different ledger file and
`--format {table,json}` to control output. Read-only — never modifies the ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from call_ledger import (
    LEDGER_FILE,
    filter_failures,
    group_by,
    read_records,
    recent,
    summarize,
)


def _resolve_path(arg: str | None) -> Path:
    return Path(arg) if arg else LEDGER_FILE


def _print_summary(summary: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    print(f"calls:               {summary['calls']}")
    print(f"  successes:         {summary['successes']}")
    print(f"  failures:          {summary['failures']}")
    print(f"input tokens:        {summary['total_input_tokens']}")
    print(f"output tokens:       {summary['total_output_tokens']}")
    print(f"total tokens:        {summary['total_tokens']}")
    print(f"total duration ms:   {summary['total_duration_ms']}")
    print(f"total cost cny:      {summary['total_cost_cny']}")
    print(f"  cost known calls:  {summary['cost_known_calls']}")
    print(f"  cost unknown:      {summary['cost_unknown_calls']}")


def _print_groups(groups: dict[str, dict], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(groups, ensure_ascii=False, indent=2))
        return
    if not groups:
        print("(no records)")
        return
    header = (
        f"{'key':<32} {'calls':>7} {'ok':>5} {'fail':>5} "
        f"{'in_tok':>10} {'out_tok':>10} {'cost_cny':>10}"
    )
    print(header)
    print("-" * len(header))
    items = sorted(groups.items(), key=lambda kv: kv[1]['calls'], reverse=True)
    for k, s in items:
        key_display = k if len(k) <= 32 else k[:29] + "..."
        print(
            f"{key_display:<32} {s['calls']:>7} {s['successes']:>5} {s['failures']:>5} "
            f"{s['total_input_tokens']:>10} {s['total_output_tokens']:>10} "
            f"{s['total_cost_cny']:>10}"
        )


def _print_records(records: list[dict], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2, default=str))
        return
    if not records:
        print("(no records)")
        return
    for r in records:
        ts = (r.get("timestamp") or "")[:19]
        ok = "OK" if r.get("success") else "FAIL"
        project = (r.get("project") or "-")[:20]
        task = (r.get("task_type") or "-")[:24]
        model = (r.get("model") or "-")[:24]
        dur = r.get("duration_ms") or 0
        cost = r.get("estimated_cost_cny")
        cost_s = f"{cost:.4f}" if isinstance(cost, (int, float)) else "?"
        reason = (r.get("failure_reason") or "")[:40]
        line = (
            f"{ts}  {ok:<4} {project:<20} {task:<24} {model:<24} "
            f"dur={dur:>6}ms cost={cost_s:>8}"
        )
        if reason:
            line += f"  reason={reason}"
        print(line)


def cmd_summary(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_summary(summarize(records), args.format)
    return 0


def cmd_by_project(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_groups(group_by(records, "project"), args.format)
    return 0


def cmd_by_task(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_groups(group_by(records, "task_type"), args.format)
    return 0


def cmd_failures(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    fails = filter_failures(records)
    if args.limit and args.limit > 0:
        fails = fails[-args.limit:]
    _print_records(fails, args.format)
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_records(recent(records, args.limit), args.format)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="call_ledger_cli",
        description="Inspect the local-llm call ledger.",
    )
    p.add_argument("--path", default=None,
                   help=f"path to ledger file (default: {LEDGER_FILE})")
    p.add_argument("--format", choices=("table", "json"), default="table",
                   help="output format (default: table)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("summary", help="show aggregate totals").set_defaults(func=cmd_summary)
    sub.add_parser("by-project", help="totals grouped by project").set_defaults(func=cmd_by_project)
    sub.add_parser("by-task", help="totals grouped by task_type").set_defaults(func=cmd_by_task)

    sp_fail = sub.add_parser("failures", help="list failing records")
    sp_fail.add_argument("--limit", type=int, default=0,
                         help="limit to last N (0 = all)")
    sp_fail.set_defaults(func=cmd_failures)

    sp_recent = sub.add_parser("recent", help="list most recent records")
    sp_recent.add_argument("--limit", type=int, default=20,
                           help="number of records to show (default 20)")
    sp_recent.set_defaults(func=cmd_recent)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
