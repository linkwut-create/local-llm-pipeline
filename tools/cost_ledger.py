#!/usr/bin/env python3
"""
Local Cost Ledger — budget guard skeleton for future DeepSeek Flash/Pro calls.

Records estimated cloud API cost entries to .local_llm_out/cost_ledger/YYYYMM.jsonl
so that budget tracking, call decisions, and cost governance are available BEFORE
real API calls begin.

Design constraints:
  - Never calls DeepSeek API or any LLM.
  - Never reads API keys or secrets.
  - Never modifies profiles, hooks, MCP server, or deepseek_client.
  - All output confined to .local_llm_out/cost_ledger/.
  - Exit code 0 unless CLI arguments are invalid.
  - Pricing is configurable — defaults are mock/approximate, not final.

Usage:
  py -3 tools/cost_ledger.py --estimate --model deepseek-v4-flash --input-tokens 10000 --output-tokens 2000
  py -3 tools/cost_ledger.py --record --model deepseek-v4-flash --input-tokens 10000 --output-tokens 2000 --task "review diff"
  py -3 tools/cost_ledger.py --summary
  py -3 tools/cost_ledger.py --budget 200 --summary
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_DIR = PROJECT_ROOT / ".local_llm_out"
LEDGER_DIR = OUTPUT_DIR / "cost_ledger"


# ═══════════════════════════════════════════════════════════════
# Configurable pricing (mock defaults — not final DeepSeek prices)
# ═══════════════════════════════════════════════════════════════

# Prices in CNY per 1M tokens. These are approximate and configurable.
# To override, set COST_LEDGER_PRICING_JSON env var to a JSON string
# with the same structure.
_DEFAULT_PRICING: dict = {
    "deepseek-v4-flash": {
        "provider": "deepseek",
        "input_cny_per_1m": 1.0,       # ~$0.14
        "output_cny_per_1m": 2.0,      # ~$0.28
        "currency": "CNY",
    },
    "deepseek-v4-pro": {
        "provider": "deepseek",
        "input_cny_per_1m": 4.0,       # ~$0.55
        "output_cny_per_1m": 8.0,      # ~$1.10
        "currency": "CNY",
    },
    # Catch-all for unknown models — cost is unknown but ledger won't crash
    "_unknown": {
        "provider": "unknown",
        "input_cny_per_1m": None,
        "output_cny_per_1m": None,
        "currency": "CNY",
    },
}


def _load_pricing() -> dict:
    """Load pricing from env override or default."""
    override = os.environ.get("COST_LEDGER_PRICING_JSON", "")
    if override:
        try:
            custom = json.loads(override)
            merged = {**_DEFAULT_PRICING, **custom}
            return merged
        except json.JSONDecodeError:
            pass
    return dict(_DEFAULT_PRICING)


PRICING = _load_pricing()


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _ensure_dir() -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)


def _month_file(timestamp: Optional[datetime] = None) -> Path:
    """Return the JSONL file path for the current month."""
    ts = timestamp or datetime.now(timezone.utc)
    return LEDGER_DIR / f"{ts.strftime('%Y%m')}.jsonl"


def _get_pricing(model: str) -> dict:
    """Get pricing info for a model. Returns _unknown entry if model unknown."""
    return PRICING.get(model, PRICING["_unknown"])


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    """Compute estimated cost for a model call. Never calls any API."""
    pricing = _get_pricing(model)

    input_rate = pricing.get("input_cny_per_1m")
    output_rate = pricing.get("output_cny_per_1m")

    if input_rate is None or output_rate is None:
        return {
            "estimated_cost": None,
            "currency": pricing.get("currency", "CNY"),
            "price_known": False,
            "reason": "unknown_price",
        }

    input_cost = (input_tokens / 1_000_000) * input_rate
    output_cost = (output_tokens / 1_000_000) * output_rate
    total = round(input_cost + output_cost, 6)

    return {
        "estimated_cost": total,
        "currency": pricing.get("currency", "CNY"),
        "price_known": True,
        "input_rate_cny_per_1m": input_rate,
        "output_rate_cny_per_1m": output_rate,
        "reason": "ok",
    }


def _load_month_records(month_str: Optional[str] = None) -> list[dict]:
    """Load all records for a given month (YYYYMM). Default: current month."""
    if month_str is None:
        month_str = datetime.now(timezone.utc).strftime("%Y%m")

    file_path = LEDGER_DIR / f"{month_str}.jsonl"
    if not file_path.exists():
        return []

    records = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def _load_all_records() -> list[dict]:
    """Load all records from all months."""
    if not LEDGER_DIR.exists():
        return []
    records = []
    for f in sorted(LEDGER_DIR.glob("*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return records


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def estimate(task: str, model: str, input_tokens: int,
             output_tokens: int, budget_limit: Optional[float] = None) -> dict:
    """Dry-run estimate — does NOT write to ledger. Never calls any API."""
    cost_info = _estimate_cost(model, input_tokens, output_tokens)
    pricing = _get_pricing(model)

    # Budget check against current month usage
    budget_used = 0.0
    budget_remaining = None
    allowed = True
    budget_reason = "ok"

    if budget_limit is not None:
        records = _load_month_records()
        budget_used = round(sum(
            r.get("estimated_cost", 0) or 0 for r in records
        ), 6)
        budget_remaining = round(budget_limit - budget_used, 6)

        if cost_info["estimated_cost"] is not None:
            if budget_used + cost_info["estimated_cost"] > budget_limit:
                allowed = False
                budget_reason = "budget_exceeded"
            budget_remaining = round(budget_limit - budget_used - cost_info["estimated_cost"], 6)
        else:
            budget_remaining = round(budget_limit - budget_used, 6)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "model": model,
        "provider": pricing.get("provider", "unknown"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost": cost_info["estimated_cost"],
        "currency": cost_info["currency"],
        "price_known": cost_info["price_known"],
        "budget_limit": budget_limit,
        "budget_used": budget_used,
        "budget_remaining": budget_remaining,
        "allowed": allowed,
        "reason": budget_reason if budget_limit is not None else cost_info["reason"],
        "dry_run": True,
    }


def record(task: str, model: str, input_tokens: int,
           output_tokens: int, budget_limit: Optional[float] = None,
           notes: str = "") -> dict:
    """Record an estimated call to the cost ledger. Never calls any API."""
    _ensure_dir()

    cost_info = _estimate_cost(model, input_tokens, output_tokens)
    pricing = _get_pricing(model)

    # Budget check
    records = _load_month_records()
    budget_used_before = round(sum(
        r.get("estimated_cost", 0) or 0 for r in records
    ), 6)

    allowed = True
    reason = cost_info["reason"]

    if budget_limit is not None:
        if cost_info["estimated_cost"] is not None:
            projected = budget_used_before + cost_info["estimated_cost"]
            if projected > budget_limit:
                allowed = False
                reason = "budget_exceeded"
            budget_remaining = round(budget_limit - projected, 6)
        else:
            budget_remaining = round(budget_limit - budget_used_before, 6)
    else:
        budget_remaining = None

    record_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "model": model,
        "provider": pricing.get("provider", "unknown"),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost": cost_info["estimated_cost"],
        "currency": cost_info["currency"],
        "price_known": cost_info["price_known"],
        "budget_limit": budget_limit,
        "budget_used_before": budget_used_before,
        "budget_remaining": budget_remaining,
        "allowed": allowed,
        "reason": reason,
        "notes": notes.strip(),
    }

    file_path = _month_file()
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record_data, ensure_ascii=False) + "\n")

    return record_data


def summary(budget_limit: Optional[float] = None,
            month_str: Optional[str] = None) -> dict:
    """Summarize cost ledger records. Never calls any API."""
    if month_str:
        records = _load_month_records(month_str)
    else:
        records = _load_month_records()  # current month only

    all_records = _load_all_records()

    total_calls = len(records)
    total_cost = round(sum(
        r.get("estimated_cost", 0) or 0 for r in records
    ), 6)

    all_time_calls = len(all_records)
    all_time_cost = round(sum(
        r.get("estimated_cost", 0) or 0 for r in all_records
    ), 6)

    allowed_count = sum(1 for r in records if r.get("allowed", True))
    blocked_count = sum(1 for r in records if not r.get("allowed", True))
    unknown_price_count = sum(1 for r in records if not r.get("price_known", True))

    by_model = {}
    for r in records:
        m = r.get("model", "unknown")
        if m not in by_model:
            by_model[m] = {"calls": 0, "total_cost": 0.0, "total_input": 0, "total_output": 0}
        by_model[m]["calls"] += 1
        by_model[m]["total_cost"] += r.get("estimated_cost", 0) or 0
        by_model[m]["total_input"] += r.get("input_tokens", 0)
        by_model[m]["total_output"] += r.get("output_tokens", 0)

    # Round model costs
    for m in by_model:
        by_model[m]["total_cost"] = round(by_model[m]["total_cost"], 6)

    result = {
        "month": month_str or datetime.now(timezone.utc).strftime("%Y%m"),
        "total_calls": total_calls,
        "total_estimated_cost": total_cost,
        "all_time_calls": all_time_calls,
        "all_time_estimated_cost": all_time_cost,
        "allowed": allowed_count,
        "blocked": blocked_count,
        "unknown_price": unknown_price_count,
        "by_model": by_model,
        "currency": "CNY",
    }

    if budget_limit is not None:
        result["budget_limit"] = budget_limit
        result["budget_remaining"] = round(budget_limit - total_cost, 6)
        result["budget_exceeded"] = total_cost > budget_limit

    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Local Cost Ledger — budget guard skeleton for future DeepSeek calls"
    )
    parser.add_argument("--estimate", action="store_true",
                        help="Dry-run estimate (no ledger write)")
    parser.add_argument("--record", action="store_true",
                        help="Record an estimated call to the ledger")
    parser.add_argument("--summary", action="store_true",
                        help="Show cost summary for current month")
    parser.add_argument("--model", default="",
                        help="Model name (e.g. deepseek-v4-flash)")
    parser.add_argument("--input-tokens", type=int, default=0,
                        help="Estimated input tokens")
    parser.add_argument("--output-tokens", type=int, default=0,
                        help="Estimated output tokens")
    parser.add_argument("--task", default="",
                        help="Task description")
    parser.add_argument("--budget", type=float, default=None,
                        help="Monthly budget limit in CNY (default: no limit)")
    parser.add_argument("--month", default=None,
                        help="Month for summary (YYYYMM, default: current)")
    parser.add_argument("--notes", default="",
                        help="Free-form notes (--record only)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    # ── Validation ──
    if not args.estimate and not args.record and not args.summary:
        parser.print_help()
        sys.exit(1)

    if (args.estimate or args.record):
        if not args.model:
            print("error: --model is required for --estimate/--record", file=sys.stderr)
            sys.exit(2)
        if args.input_tokens < 0 or args.output_tokens < 0:
            print("error: token counts must be >= 0", file=sys.stderr)
            sys.exit(2)

    if args.estimate and args.record:
        print("error: use --estimate or --record, not both", file=sys.stderr)
        sys.exit(2)

    # ── Execute ──
    if args.estimate:
        result = estimate(
            task=args.task or "(estimate only)",
            model=args.model,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            budget_limit=args.budget,
        )
    elif args.record:
        result = record(
            task=args.task or "(no task)",
            model=args.model,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            budget_limit=args.budget,
            notes=args.notes,
        )
    else:  # summary
        result = summary(
            budget_limit=args.budget,
            month_str=args.month,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result, mode="estimate" if args.estimate else
                      ("record" if args.record else "summary"))

    sys.exit(0)


def _print_human(result: dict, mode: str) -> None:
    """Human-readable output."""
    if mode == "estimate":
        cost_str = f"{result['estimated_cost']:.6f}" if result["estimated_cost"] is not None else "unknown"
        allowed = "[OK]" if result["allowed"] else "[BLOCKED]"
        print(f"Estimate: {result['model']} ({result['provider']})")
        print(f"  tokens:   {result['input_tokens']:,} in + {result['output_tokens']:,} out")
        print(f"  cost:     {cost_str} {result['currency']}")
        if result.get("budget_limit") is not None:
            print(f"  budget:   {result['budget_used']:.4f} used + this -> "
                  f"{result['budget_remaining']:.4f} remaining "
                  f"(limit: {result['budget_limit']})")
        print(f"  allowed:  {allowed}")
        if result.get("reason") and result["reason"] != "ok":
            print(f"  reason:   {result['reason']}")

    elif mode == "record":
        cost_str = f"{result['estimated_cost']:.6f}" if result["estimated_cost"] is not None else "unknown"
        allowed = "[OK]" if result["allowed"] else "[BLOCKED]"
        print(f"Recorded: {result['model']}")
        print(f"  task:     {result['task']}")
        print(f"  tokens:   {result['input_tokens']:,} in + {result['output_tokens']:,} out")
        print(f"  cost:     {cost_str} {result['currency']}")
        print(f"  allowed:  {allowed}")
        if result.get("reason") and result["reason"] != "ok":
            print(f"  reason:   {result['reason']}")
        print(f"  ledger:   {_month_file()}")

    else:  # summary
        print(f"Cost Ledger -- {result['month']}")
        print(f"  calls:           {result['total_calls']}")
        print(f"  cost (month):    {result['total_estimated_cost']:.6f} {result['currency']}")
        print(f"  cost (all-time): {result['all_time_estimated_cost']:.6f} {result['currency']}")
        print(f"  allowed:         {result['allowed']}")
        print(f"  blocked:         {result['blocked']}")
        if result.get("unknown_price", 0) > 0:
            print(f"  unknown price:   {result['unknown_price']}")
        if result.get("budget_limit") is not None:
            remaining = result.get("budget_remaining", 0)
            exceeded = "EXCEEDED" if result.get("budget_exceeded") else "ok"
            print(f"  budget:          {result['budget_limit']} {result['currency']} "
                  f"(remaining: {remaining:.4f}, {exceeded})")
        if result["by_model"]:
            print(f"  by model:")
            for m, s in sorted(result["by_model"].items()):
                cost_s = f"{s['total_cost']:.6f}" if s['total_cost'] else "unknown"
                print(f"    {m}: {s['calls']} calls, {cost_s} {result['currency']}, "
                      f"{s['total_input']:,} in / {s['total_output']:,} out")


if __name__ == "__main__":
    main()
