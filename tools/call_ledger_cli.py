#!/usr/bin/env python3
"""Call Ledger CLI — query .local_llm_out/audit/calls.jsonl.

Subcommands:
    summary               aggregate totals across all records
    model-summary         token/call usage grouped by model
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
    breakdown_counts,
    filter_debates,
    filter_debate_skips,
    filter_escalations,
    filter_failures,
    group_by,
    group_by_extra,
    read_records,
    read_records_with_diagnostics,
    recent,
    summarize,
    summarize_debate_skips,
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


def _print_escalations(records: list[dict], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2, default=str))
        return
    if not records:
        print("(no records)")
        return
    header = (
        f"{'timestamp':<20} {'parent_req':<22} {'trigger':<18} "
        f"{'from→to':<34} {'d':>2} {'profile':<22} {'ok':>5} {'dur_ms':>8} {'cost':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in records:
        extra = r.get("extra") or {}
        ts = (r.get("timestamp") or "")[:19]
        parent = (extra.get("parent_request_id") or "-")[:21]
        trigger = (extra.get("escalation_trigger") or "-")[:17]
        from_p = (extra.get("escalation_from_profile") or "-")[:16]
        to_p = (extra.get("escalation_to_profile") or "-")[:16]
        depth = extra.get("escalation_depth", "?")
        profile = (r.get("profile") or "-")[:21]
        ok = "OK" if r.get("success") else "FAIL"
        dur = r.get("duration_ms") or 0
        cost = r.get("estimated_cost_cny")
        cost_s = f"{cost:.4f}" if isinstance(cost, (int, float)) else "?"
        print(
            f"{ts:<20} {parent:<22} {trigger:<18} "
            f"{from_p:<16}→{to_p:<16} {str(depth):>2} {profile:<22} {ok:>5} {dur:>8} {cost_s:>8}"
        )


def _print_debates(records: list[dict], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2, default=str))
        return
    if not records:
        print("(no records)")
        return
    header = (
        f"{'timestamp':<20} {'trigger':<15} {'round':>5} {'of':>3} "
        f"{'profile':<22} {'provider':<10} {'ok':>5} {'dur_ms':>8} {'cost':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in records:
        extra = r.get("extra") or {}
        ts = (r.get("timestamp") or "")[:19]
        trigger = (extra.get("debate_trigger") or "-")[:14]
        round_idx = extra.get("debate_round_index", "?")
        total = extra.get("debate_rounds", "?")
        profile = (r.get("profile") or "-")[:21]
        provider = (r.get("provider") or "-")[:9]
        ok = "OK" if r.get("success") else "FAIL"
        dur = r.get("duration_ms") or 0
        cost = r.get("estimated_cost_cny")
        cost_s = f"{cost:.4f}" if isinstance(cost, (int, float)) else "?"
        print(
            f"{ts:<20} {trigger:<15} {str(round_idx):>5} {str(total):>3} "
            f"{profile:<22} {provider:<10} {ok:>5} {dur:>8} {cost_s:>8}"
        )


def _print_diagnostics(diag: dict, fmt: str) -> None:
    """Print ledger read diagnostics (--diagnostics flag)."""
    if fmt == "json":
        out = {
            "total_lines": diag["total_lines"],
            "skipped_lines": diag["skipped_lines"],
            "empty_lines": diag["empty_lines"],
            "malformed_json_lines": diag["malformed_json_lines"],
            "non_dict_lines": diag["non_dict_lines"],
            "errors_count": len(diag["errors"]),
        }
        if diag["errors"]:
            out["error_examples"] = diag["errors"][:5]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print("--- ledger diagnostics ---")
    print(f"total lines:        {diag['total_lines']}")
    print(f"  valid records:    {len(diag['records'])}")
    print(f"  skipped:          {diag['skipped_lines']}")
    if diag["empty_lines"]:
        print(f"    empty:          {diag['empty_lines']}")
    if diag["malformed_json_lines"]:
        print(f"    malformed JSON: {diag['malformed_json_lines']}")
    if diag["non_dict_lines"]:
        print(f"    non-dict JSON:  {diag['non_dict_lines']}")
    if diag["errors"]:
        print(f"errors:             {len(diag['errors'])} (showing first 5)")
        for err in diag["errors"][:5]:
            print(f"  line {err['line_number']}: {err['error']}")
    print()


def _print_breakdown(records: list[dict], title: str, key: str,
                    default: str, fmt: str) -> None:
    """Print a compact key→count breakdown from *records*."""
    if fmt == "json":
        return  # breakdown is embedded in the JSON summary object
    counts = breakdown_counts(records, key, default=default)
    if not counts:
        return
    print(f"\n- {title}:")
    for val, n in counts.items():
        print(f"    {val:<12} {n}")


def cmd_summary(args: argparse.Namespace) -> int:
    if getattr(args, "diagnostics", False):
        diag = read_records_with_diagnostics(_resolve_path(args.path))
        summary = summarize(diag["records"])
        records = diag["records"]
        if args.format == "json":
            combined = dict(summary)
            combined["_diagnostics"] = {
                "total_lines": diag["total_lines"],
                "skipped_lines": diag["skipped_lines"],
                "empty_lines": diag["empty_lines"],
                "malformed_json_lines": diag["malformed_json_lines"],
                "non_dict_lines": diag["non_dict_lines"],
                "errors_count": len(diag["errors"]),
            }
            if diag["errors"]:
                combined["_diagnostics"]["error_examples"] = diag["errors"][:5]
            combined["_execution_location_breakdown"] = breakdown_counts(
                records, "execution_location", default="unknown")
            combined["_cost_confidence_breakdown"] = breakdown_counts(
                records, "cost_confidence", default="unknown")
            print(json.dumps(combined, ensure_ascii=False, indent=2))
        else:
            _print_summary(summary, args.format)
            _print_breakdown(records, "execution location", "execution_location",
                             "unknown", args.format)
            _print_breakdown(records, "cost confidence", "cost_confidence",
                             "unknown", args.format)
            _print_diagnostics(diag, args.format)
        return 0
    records = read_records(_resolve_path(args.path))
    summary = summarize(records)
    if args.format == "json":
        combined = dict(summary)
        combined["_execution_location_breakdown"] = breakdown_counts(
            records, "execution_location", default="unknown")
        combined["_cost_confidence_breakdown"] = breakdown_counts(
            records, "cost_confidence", default="unknown")
        print(json.dumps(combined, ensure_ascii=False, indent=2))
    else:
        _print_summary(summary, args.format)
        _print_breakdown(records, "execution location", "execution_location",
                         "unknown", args.format)
        _print_breakdown(records, "cost confidence", "cost_confidence",
                         "unknown", args.format)
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


def cmd_by_profile(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_groups(group_by(records, "profile"), args.format)
    return 0


def cmd_by_mcp_tool(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_groups(
        group_by_extra(records, "mcp_tool_name", fallback_key="tool_name"),
        args.format,
    )
    return 0


def cmd_model_summary(args: argparse.Namespace) -> int:
    """Show token/call usage grouped by model."""
    records = read_records(_resolve_path(args.path))
    _print_groups(group_by(records, "model"), args.format)
    return 0


def cmd_by_location(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    _print_groups(group_by(records, "execution_location"), args.format)
    return 0


def cmd_escalations(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    items = filter_escalations(records)
    if args.limit and args.limit > 0:
        items = items[-args.limit:]
    _print_escalations(items, args.format)
    return 0


def cmd_debates(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    items = filter_debates(records)
    if args.limit and args.limit > 0:
        items = items[-args.limit:]
    _print_debates(items, args.format)
    return 0


def _print_debate_skips(skips_summary: dict, fmt: str) -> None:
    """Print debate-skip summary in table or JSON format."""
    if fmt == "json":
        out = dict(skips_summary)
        # Don't print the full records in JSON — just counts
        records = out.pop("skipped_records", [])
        out["recent_skips"] = []
        for r in records[-5:]:
            extra = r.get("extra") or {}
            out["recent_skips"].append({
                "timestamp": (r.get("timestamp") or "")[:19],
                "profile": r.get("profile"),
                "diff_risk_level": extra.get("diff_risk_level"),
                "diff_risk_confidence": extra.get("diff_risk_confidence"),
                "debate_skip_reason": extra.get("debate_skip_reason") or "",
                "changed_files_count": extra.get("changed_files_count"),
            })
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return

    total = skips_summary["total_skipped"]
    if total == 0:
        print("debate-skips: (none — no debates have been skipped yet)")
        print("This is expected before B1-C/B1-D integration.")
        return

    print(f"debate-skips: {total} total")
    print(f"  estimated debate seconds saved: {skips_summary['estimated_debate_seconds_saved']}")
    print(f"  estimated tokens saved:         {skips_summary['estimated_tokens_saved']}")
    print()
    if skips_summary["by_risk_level"]:
        print("  by risk level:")
        for k, v in skips_summary["by_risk_level"].items():
            print(f"    {k:<12} {v}")
    if skips_summary["by_confidence"]:
        print("  by confidence:")
        for k, v in skips_summary["by_confidence"].items():
            print(f"    {k:<12} {v}")
    if skips_summary["by_preclassifier_profile"]:
        print("  by preclassifier profile:")
        for k, v in skips_summary["by_preclassifier_profile"].items():
            print(f"    {k:<24} {v}")


def cmd_debate_skips(args: argparse.Namespace) -> int:
    records = read_records(_resolve_path(args.path))
    summary = summarize_debate_skips(records)
    _print_debate_skips(summary, args.format)
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    """Archive the active calls.jsonl and start a fresh one."""
    from call_ledger import rotate_ledger
    path = _resolve_path(args.path)

    if getattr(args, "dry_run", False):
        archive_name = getattr(args, "archive_name", None)
        if archive_name is None:
            from call_ledger import _utc_now_iso
            archive_name = f"calls.{_utc_now_iso()[:10]}.jsonl"
        if args.format == "json":
            print(json.dumps(
                {"ok": True, "detail": f"[DRY RUN] would archive {path.name} → {archive_name}"},
                ensure_ascii=False))
        else:
            print(f"[DRY RUN] would archive {path.name} → {archive_name}")
        return 0

    ok, detail = rotate_ledger(
        archive_name=getattr(args, "archive_name", None),
        path=path,
    )
    if args.format == "json":
        print(json.dumps({"ok": ok, "detail": detail}, ensure_ascii=False))
    else:
        prefix = "OK" if ok else "FAIL"
        print(f"[{prefix}] {detail}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="call_ledger_cli",
        description="Inspect the local-llm call ledger.",
    )
    p.add_argument("--path", default=None,
                   help=f"path to ledger file (default: {LEDGER_FILE})")
    p.add_argument("--format", choices=("table", "json"), default="table",
                   help="output format (default: table)")
    p.add_argument("--diagnostics", action="store_true", default=False,
                   help="show ledger read diagnostics (skipped/corrupt lines)")
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

    sub.add_parser("by-profile", help="totals grouped by profile").set_defaults(func=cmd_by_profile)

    sub.add_parser("by-mcp-tool", help="totals grouped by MCP tool name").set_defaults(func=cmd_by_mcp_tool)

    sub.add_parser("model-summary", help="token/call usage grouped by model").set_defaults(func=cmd_model_summary)

    sub.add_parser("by-location", help="totals grouped by execution_location").set_defaults(func=cmd_by_location)

    sp_esc = sub.add_parser("escalations", help="list auto-escalation records")
    sp_esc.add_argument("--limit", type=int, default=0,
                        help="limit to last N (0 = all)")
    sp_esc.set_defaults(func=cmd_escalations)

    sp_deb = sub.add_parser("debates", help="list debate round records")
    sp_deb.add_argument("--limit", type=int, default=0,
                        help="limit to last N (0 = all)")
    sp_deb.set_defaults(func=cmd_debates)

    sp_ds = sub.add_parser("debate-skips", help="list debates skipped via preclassifier")
    sp_ds.set_defaults(func=cmd_debate_skips)

    sp_rot = sub.add_parser("rotate", help="archive calls.jsonl and start fresh")
    sp_rot.add_argument("--archive-name", default=None,
                        help="archive filename (default: calls.<date>.jsonl)")
    sp_rot.add_argument("--dry-run", action="store_true", default=False,
                        help="print what would happen without mutating files")
    sp_rot.set_defaults(func=cmd_rotate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
