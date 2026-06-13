#!/usr/bin/env python3
"""
DeepSeek Dry-Run Execution Contract — composable cloud call plan generator.

Composes router_explain + privacy_gate + cost_ledger into a unified dry-run
execution plan. Answers: "If we were to call DeepSeek, would governance allow it?"

Design constraints:
  - Never calls DeepSeek API or any LLM.
  - Never reads API keys or secrets.
  - Never modifies profiles, hooks, MCP server, or deepseek_client.
  - Advisory-only: would_call_deepseek is ALWAYS false.
  - All output is a plan, not an execution.

Usage:
  py -3 tools/deepseek_dry_run.py --task "review diff before commit" --model deepseek-v4-flash --input-tokens 10000 --output-tokens 2000 --budget 200
  py -3 tools/deepseek_dry_run.py --task "prepare release gate v0.13.0" --model deepseek-v4-pro --input-tokens 20000 --output-tokens 4000 --budget 200
  py -3 tools/deepseek_dry_run.py --task "check .env.production for credentials" --model deepseek-v4-flash --input-tokens 10000 --output-tokens 2000 --budget 200
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from router_explain import RouterEngine
from privacy_gate import check as privacy_check
from cost_ledger import estimate as cost_estimate, _estimate_cost, _get_pricing


_engine = RouterEngine()

# Pro model identifier — determines whether escalation to Pro is needed
PRO_MODEL = "deepseek-v4-pro"
FLASH_MODEL = "deepseek-v4-flash"


# ═══════════════════════════════════════════════════════════════
# Core engine
# ═══════════════════════════════════════════════════════════════

def plan(task: str, model: str, input_tokens: int,
         output_tokens: int, budget: float | None = None,
         cloud_ok: bool = True) -> dict:
    """Generate a dry-run DeepSeek execution plan.

    Composes router_explain, privacy_gate, and cost_ledger into a single
    governance decision. Never calls DeepSeek. Never reads API keys.

    Args:
        task: Task description to analyze.
        model: Requested DeepSeek model (e.g. deepseek-v4-flash).
        input_tokens: Estimated input token count.
        output_tokens: Estimated output token count.
        budget: Monthly budget limit in CNY (None = no limit).
        cloud_ok: Whether cloud escalation is permitted by the user.

    Returns:
        Dict with full governance plan, decision, and reason.
    """
    # ── Step 1: Router analysis ──
    route = _engine.analyze(task)

    # ── Step 2: Privacy check ──
    privacy = privacy_check(text=task)

    # ── Step 3: Cost estimate ──
    cost = cost_estimate(
        task=task,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        budget_limit=budget,
    )

    # ── Step 4: Compose decision ──
    decision, reason = _compose_decision(
        route_decision=route,
        privacy_result=privacy,
        cost_result=cost,
        model=model,
        cloud_ok=cloud_ok,
        task=task,
    )

    # ── Step 5: Recommend model ──
    recommended_model = _recommend_model(
        route_decision=route,
        requested_model=model,
        privacy_ok=privacy["privacy_status"] != "blocked",
    )

    return {
        # Task identity
        "task": task,
        "requested_model": model,
        "recommended_model": recommended_model,
        # Router analysis
        "router_task_type": route.task_type,
        "router_risk_level": route.risk_level,
        # Privacy
        "privacy_status": privacy["privacy_status"],
        "privacy_allowed": privacy["allowed_for_cloud"],
        "privacy_reason": privacy["reason"],
        # Budget
        "budget_allowed": cost["allowed"],
        "estimated_cost": cost["estimated_cost"],
        "budget_limit": budget,
        "budget_remaining": cost.get("budget_remaining"),
        "price_known": cost["price_known"],
        # Cloud
        "cloud_ok": cloud_ok,
        "cloud_allowed": decision == "allow_dry_run",
        # Decision
        "decision": decision,
        "reason": reason,
        # Meta
        "dry_run_only": True,
        "would_call_deepseek": False,
        "advisory_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _compose_decision(
    route_decision,
    privacy_result: dict,
    cost_result: dict,
    model: str,
    cloud_ok: bool,
    task: str = "",
) -> tuple[str, str]:
    """Compose governance components into a single decision.

    Returns (decision, reason).
    """
    # ── Privacy gate ──
    if privacy_result["privacy_status"] == "blocked":
        return (
            "blocked_by_privacy",
            f"privacy gate blocked: {privacy_result['reason']}",
        )

    # ── Unknown model price ──
    if not cost_result["price_known"]:
        return (
            "unknown_price",
            f"no pricing data for model '{model}' — cannot estimate cost",
        )

    # ── Budget guard ──
    if not cost_result["allowed"]:
        return (
            "blocked_by_budget",
            (
                f"budget exceeded: estimated {cost_result['estimated_cost']} CNY "
                f"would exceed {cost_result.get('budget_limit', '?')} CNY limit"
            ),
        )

    # ── Cloud escalation not enabled ──
    if not cloud_ok:
        return (
            "defer",
            "cloud escalation not enabled (use --cloud-ok to allow)",
        )

    # ── Privacy needs_review → still allow but with note ──
    #    Check BEFORE unknown task — privacy concerns override task classification
    if privacy_result["privacy_status"] == "needs_review":
        return (
            "allow_dry_run",
            f"privacy gate: needs_review — {privacy_result['reason']}. "
            f"Dry-run plan passes, but human review recommended before real call.",
        )

    # ── Unknown task ──
    if route_decision.task_type == "unknown":
        return (
            "defer",
            f"unknown task type — insufficient information to route: "
            f"'{task[:80]}'",
        )

    # ── High/critical risk needs Pro ──
    is_pro_model = "pro" in model.lower()
    if route_decision.risk_level in ("high", "critical") and not is_pro_model:
        return (
            "needs_pro_review",
            (
                f"task risk is {route_decision.risk_level} but model is "
                f"'{model}' (not Pro) — escalate to {PRO_MODEL} for review"
            ),
        )

    # ── All clear ──
    return (
        "allow_dry_run",
        (
            f"all governance gates passed: privacy={privacy_result['privacy_status']}, "
            f"budget={cost_result['estimated_cost']} CNY, "
            f"risk={route_decision.risk_level}"
        ),
    )


def _recommend_model(route_decision, requested_model: str,
                     privacy_ok: bool) -> str:
    """Recommend the appropriate model based on risk and privacy."""
    if not privacy_ok:
        return "(blocked — do not call any model)"
    risk = route_decision.risk_level
    if risk in ("high", "critical"):
        if "pro" not in requested_model.lower():
            return PRO_MODEL
    return requested_model


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="DeepSeek Dry-Run — composable cloud call governance plan"
    )
    parser.add_argument("--task", required=True,
                        help="Task description")
    parser.add_argument("--model", default=FLASH_MODEL,
                        help=f"Requested model (default: {FLASH_MODEL})")
    parser.add_argument("--input-tokens", type=int, required=True,
                        help="Estimated input tokens")
    parser.add_argument("--output-tokens", type=int, required=True,
                        help="Estimated output tokens")
    parser.add_argument("--budget", type=float, default=None,
                        help="Monthly budget limit in CNY")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Cloud escalation permitted (default: False)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--cost-only", action="store_true",
                        help="Output cost estimate only (quick check)")
    args = parser.parse_args()

    if args.input_tokens < 0 or args.output_tokens < 0:
        print("error: token counts must be >= 0", file=sys.stderr)
        sys.exit(2)

    if args.cost_only:
        cost = cost_estimate(
            task=args.task,
            model=args.model,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            budget_limit=args.budget,
        )
        if args.json:
            print(json.dumps(cost, ensure_ascii=False, indent=2))
        else:
            _print_cost_only(cost, args.model)
        sys.exit(0)

    result = plan(
        task=args.task,
        model=args.model,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        budget=args.budget,
        cloud_ok=args.cloud_ok,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    sys.exit(0)


def _print_human(result: dict) -> None:
    """Human-readable output (ASCII-safe for Windows GBK)."""
    decision = result["decision"]
    allowed = "[OK]" if result["cloud_allowed"] else "[BLOCKED]"

    print(f"DeepSeek Dry-Run Plan: {decision} {allowed}")
    print(f"  task:            {result['task'][:70]}")
    print(f"  model:           {result['requested_model']}")
    print(f"  recommended:     {result['recommended_model']}")
    print(f"  router:          {result['router_task_type']} / {result['router_risk_level']}")
    print(f"  privacy:         {result['privacy_status']}")
    print(f"  cost:            {result['estimated_cost']} CNY"
          if result['estimated_cost'] is not None else
          f"  cost:            unknown")
    if result.get("budget_limit") is not None:
        print(f"  budget:          {result['budget_remaining']} CNY remaining"
              f" (limit: {result['budget_limit']})")
    print(f"  would-call:      {result['would_call_deepseek']}")
    print(f"  reason:          {result['reason']}")


def _print_cost_only(cost: dict, model: str) -> None:
    """Quick cost check output."""
    cost_str = f"{cost['estimated_cost']:.6f}" if cost['estimated_cost'] is not None else "unknown"
    allowed = "[OK]" if cost["allowed"] else "[BLOCKED]"
    print(f"Cost check: {model} -> {cost_str} CNY {allowed}")


if __name__ == "__main__":
    main()
