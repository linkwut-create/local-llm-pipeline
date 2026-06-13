#!/usr/bin/env python3
"""
DeepSeek Execution Adapter — mock skeleton for future real API calls.

Implements the full gate sequence from the design contract
(docs/deepseek_api_execution_adapter_design.md) but NEVER calls DeepSeek.
Even with --real-run, the adapter returns real_run_not_implemented.

Gate sequence:
  [1] cloud_ok check
  [2] router_explain (task_type, risk_level)
  [3] privacy_gate (safe | needs_review | blocked)
  [4] cost_ledger estimate (budget check)
  [5] deepseek_dry_run plan (governance decision)
  [6] real_run check → always real_run_not_implemented (mock)

Design constraints:
  - Never calls DeepSeek API or any LLM.
  - Never reads API keys or secrets.
  - Never modifies profiles, hooks, MCP server, or deepseek_client.
  - would_call_deepseek is ALWAYS false (mock skeleton).
  - api_key_read is ALWAYS false (mock skeleton).
  - mock_only is ALWAYS true.

Usage:
  py -3 tools/deepseek_execution_adapter.py --task "review diff" --model deepseek-v4-flash --input-tokens 10000 --output-tokens 2000 --budget 200 --cloud-ok
  py -3 tools/deepseek_execution_adapter.py --task "review diff" --model deepseek-v4-flash --input-tokens 10000 --output-tokens 2000 --budget 200 --cloud-ok --real-run
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from router_explain import RouterEngine
from privacy_gate import check as privacy_check
from cost_ledger import estimate as cost_estimate
from deepseek_dry_run import plan as dry_run_plan

_engine = RouterEngine()

PRO_MODEL = "deepseek-v4-pro"
FLASH_MODEL = "deepseek-v4-flash"
ALLOWED_MODELS = {FLASH_MODEL, PRO_MODEL}


# ═══════════════════════════════════════════════════════════════
# Core engine
# ═══════════════════════════════════════════════════════════════

def execute(
    task: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    budget: float | None = None,
    cloud_ok: bool = False,
    real_run: bool = False,
    record_ledger: bool = False,
) -> dict:
    """Run the full execution adapter gate sequence. Mock-only.

    Runs gates [1]-[6]. Never calls DeepSeek. Never reads API keys.
    With --real-run, gate [6] returns real_run_not_implemented.

    Args:
        task: Task description.
        model: Requested model (must be in allowlist).
        input_tokens: Estimated input tokens.
        output_tokens: Estimated output tokens.
        budget: Monthly budget limit in CNY.
        cloud_ok: User permits cloud escalation.
        real_run: User requests real API call (always blocked in mock).
        record_ledger: Whether to write a cost ledger record.

    Returns:
        Full execution plan dict.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # ── Gate [1]: cloud_ok ──
    if not cloud_ok:
        return _abort(
            task=task, model=model,
            execution_decision="cloud_ok_required",
            reason="cloud escalation not enabled (use --cloud-ok)",
            input_tokens=input_tokens, output_tokens=output_tokens,
            budget=budget, timestamp=timestamp,
        )

    # ── Model allowlist check ──
    if model not in ALLOWED_MODELS:
        return _abort(
            task=task, model=model,
            execution_decision="blocked_by_router",
            reason=f"model '{model}' not in real-run allowlist ({', '.join(sorted(ALLOWED_MODELS))})",
            input_tokens=input_tokens, output_tokens=output_tokens,
            budget=budget, timestamp=timestamp,
        )

    # ── Gate [2]: router_explain ──
    route = _engine.analyze(task)

    # ── Gate [3]: privacy_gate ──
    privacy = privacy_check(text=task)

    if privacy["privacy_status"] == "blocked":
        return _abort(
            task=task, model=model,
            execution_decision="blocked_by_privacy",
            reason=f"privacy gate blocked: {privacy['reason']}",
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            privacy_reason=privacy["reason"],
            input_tokens=input_tokens, output_tokens=output_tokens,
            budget=budget, timestamp=timestamp,
        )

    # ── Gate [4]: cost_ledger estimate ──
    cost = cost_estimate(
        task=task, model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        budget_limit=budget,
    )

    if not cost["price_known"]:
        return _abort(
            task=task, model=model,
            execution_decision="unknown_price",
            reason=f"no pricing data for model '{model}' — cannot estimate cost",
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            estimated_cost=None,
            budget_limit=budget,
            input_tokens=input_tokens, output_tokens=output_tokens,
            timestamp=timestamp,
        )

    if not cost["allowed"]:
        return _abort(
            task=task, model=model,
            execution_decision="blocked_by_budget",
            reason=(
                f"budget exceeded: estimated {cost['estimated_cost']} CNY "
                f"would exceed {budget} CNY limit"
            ),
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            estimated_cost=cost["estimated_cost"],
            budget_limit=budget,
            budget_remaining=cost.get("budget_remaining"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            timestamp=timestamp,
        )

    # ── Gate [5]: deepseek_dry_run plan ──
    dry = dry_run_plan(
        task=task, model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        budget=budget,
        cloud_ok=cloud_ok,
    )

    if dry["decision"] == "defer":
        return _abort(
            task=task, model=model,
            execution_decision="blocked_by_router",
            reason=f"router cannot classify task: {dry['reason']}",
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            estimated_cost=cost["estimated_cost"],
            budget_limit=budget,
            budget_remaining=cost.get("budget_remaining"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            timestamp=timestamp,
        )

    if dry["decision"] == "needs_pro_review":
        return _abort(
            task=task, model=model,
            execution_decision="needs_pro_review",
            reason=dry["reason"],
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            estimated_cost=cost["estimated_cost"],
            budget_limit=budget,
            budget_remaining=cost.get("budget_remaining"),
            input_tokens=input_tokens, output_tokens=output_tokens,
            timestamp=timestamp,
            recommended_model=dry.get("recommended_model", model),
        )

    # ── Privacy needs_review: real-run blocks, mock allows with note ──
    privacy_needs_review = privacy["privacy_status"] == "needs_review"

    # ── Gate [6]: real_run check ──
    if real_run:
        # Mock skeleton: ALWAYS block real-run
        result = _result_base(
            task=task, model=model,
            execution_decision="real_run_not_implemented",
            dry_run_decision=dry["decision"],
            reason=(
                "real_run requested but this is a mock skeleton — "
                "real DeepSeek API calls are not yet implemented. "
                "Dry-run plan: " + dry["reason"]
            ),
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            privacy_needs_review=privacy_needs_review,
            estimated_cost=cost["estimated_cost"],
            budget_limit=budget,
            budget_remaining=cost.get("budget_remaining"),
            cloud_ok=True, real_run=True,
            input_tokens=input_tokens, output_tokens=output_tokens,
            timestamp=timestamp,
            recommended_model=dry.get("recommended_model", model),
            ledger_event_type="real_run_not_implemented",
        )
        _maybe_record(result, record_ledger)
        return result

    # ── Mock plan ready (dry-run path) ──
    privacy_note = ""
    if privacy_needs_review:
        privacy_note = (
            f" Privacy needs_review — human review required before real call."
        )

    result = _result_base(
        task=task, model=model,
        execution_decision="mock_plan_ready",
        dry_run_decision=dry["decision"],
        reason=(
            f"all governance gates passed (mock skeleton).{privacy_note} "
            f"Dry-run: {dry['reason']}"
        ),
        router_task_type=route.task_type,
        router_risk_level=route.risk_level,
        privacy_status=privacy["privacy_status"],
        privacy_needs_review=privacy_needs_review,
        estimated_cost=cost["estimated_cost"],
        budget_limit=budget,
        budget_remaining=cost.get("budget_remaining"),
        cloud_ok=True, real_run=False,
        input_tokens=input_tokens, output_tokens=output_tokens,
        timestamp=timestamp,
        recommended_model=dry.get("recommended_model", model),
        ledger_event_type="mock_plan" if record_ledger else None,
    )
    _maybe_record(result, record_ledger)
    return result


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _result_base(
    task: str, model: str,
    execution_decision: str,
    reason: str,
    dry_run_decision: str = "",
    router_task_type: str = "",
    router_risk_level: str = "",
    privacy_status: str = "safe",
    privacy_needs_review: bool = False,
    estimated_cost: float | None = None,
    budget_limit: float | None = None,
    budget_remaining: float | None = None,
    cloud_ok: bool = False,
    real_run: bool = False,
    recommended_model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    timestamp: str = "",
    ledger_event_type: str | None = None,
) -> dict:
    """Build the standard output dict."""
    return {
        "task": task,
        "requested_model": model,
        "recommended_model": recommended_model or model,
        "dry_run_decision": dry_run_decision,
        "execution_decision": execution_decision,
        "router_task_type": router_task_type,
        "router_risk_level": router_risk_level,
        "privacy_status": privacy_status,
        "privacy_needs_review": privacy_needs_review,
        "budget_allowed": execution_decision not in (
            "blocked_by_budget", "unknown_price"
        ),
        "estimated_cost": estimated_cost,
        "budget_limit": budget_limit,
        "budget_remaining": budget_remaining,
        "cloud_ok": cloud_ok,
        "real_run": real_run,
        "dry_run_only": not real_run,
        "mock_only": True,
        "would_call_deepseek": False,
        "api_key_read": False,
        "cost_recorded": ledger_event_type is not None,
        "ledger_event_type": ledger_event_type,
        "reason": reason,
        "advisory_only": True,
        "generated_at": timestamp or datetime.now(timezone.utc).isoformat(),
    }


def _abort(
    task: str, model: str,
    execution_decision: str,
    reason: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    budget: float | None = None,
    timestamp: str = "",
    **extra,
) -> dict:
    """Build an abort result (gate blocked)."""
    result = {
        "task": task,
        "requested_model": model,
        "recommended_model": extra.get("recommended_model", model),
        "dry_run_decision": "",
        "execution_decision": execution_decision,
        "router_task_type": extra.get("router_task_type", ""),
        "router_risk_level": extra.get("router_risk_level", ""),
        "privacy_status": extra.get("privacy_status", "safe"),
        "privacy_needs_review": False,
        "budget_allowed": False,
        "estimated_cost": extra.get("estimated_cost"),
        "budget_limit": budget,
        "budget_remaining": extra.get("budget_remaining"),
        "cloud_ok": execution_decision != "cloud_ok_required",
        "real_run": False,
        "dry_run_only": True,
        "mock_only": True,
        "would_call_deepseek": False,
        "api_key_read": False,
        "cost_recorded": False,
        "ledger_event_type": None,
        "reason": reason,
        "advisory_only": True,
        "generated_at": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    return result


def _maybe_record(result: dict, record_ledger: bool) -> None:
    """Optionally write a record to cost ledger. Mock-only events."""
    if not record_ledger:
        return
    if not result.get("ledger_event_type"):
        return
    # Only record mock_plan and real_run_not_implemented events
    try:
        from cost_ledger import record as ledger_record
        ledger_record(
            task=result["task"],
            model=result["requested_model"],
            input_tokens=0,   # mock — no actual tokens
            output_tokens=0,  # mock — no actual tokens
            budget_limit=result.get("budget_limit"),
            notes=f"mock: {result['ledger_event_type']} — {result['execution_decision']}",
        )
    except Exception:
        pass  # ledger write failure is non-blocking


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="DeepSeek Execution Adapter — mock skeleton (no real API calls)"
    )
    parser.add_argument("--task", required=True,
                        help="Task description")
    parser.add_argument("--model", default=FLASH_MODEL,
                        help=f"Model (default: {FLASH_MODEL})")
    parser.add_argument("--input-tokens", type=int, required=True,
                        help="Estimated input tokens")
    parser.add_argument("--output-tokens", type=int, required=True,
                        help="Estimated output tokens")
    parser.add_argument("--budget", type=float, default=None,
                        help="Monthly budget limit in CNY")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Allow cloud escalation (required)")
    parser.add_argument("--real-run", action="store_true",
                        help="Request real API call (ALWAYS blocked in mock)")
    parser.add_argument("--record-ledger", action="store_true",
                        help="Write mock event to cost ledger (default: off)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    if args.input_tokens < 0 or args.output_tokens < 0:
        print("error: token counts must be >= 0", file=sys.stderr)
        sys.exit(2)

    result = execute(
        task=args.task,
        model=args.model,
        input_tokens=args.input_tokens,
        output_tokens=args.output_tokens,
        budget=args.budget,
        cloud_ok=args.cloud_ok,
        real_run=args.real_run,
        record_ledger=args.record_ledger,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    sys.exit(0)


def _print_human(result: dict) -> None:
    """Human-readable output (ASCII-safe for Windows GBK)."""
    decision = result["execution_decision"]
    would = "[MOCK ONLY]" if result["mock_only"] else ""
    api = "API key: not read" if not result["api_key_read"] else "API key: READ"

    print(f"Execution Adapter: {decision} {would}")
    print(f"  task:            {result['task'][:70]}")
    print(f"  model:           {result['requested_model']}")
    if result.get("recommended_model") and \
       result["recommended_model"] != result["requested_model"]:
        print(f"  recommended:     {result['recommended_model']}")
    print(f"  router:          {result['router_task_type']} / {result['router_risk_level']}")
    print(f"  privacy:         {result['privacy_status']}")
    if result.get("estimated_cost") is not None:
        print(f"  cost:            {result['estimated_cost']} CNY")
    if result.get("budget_limit") is not None:
        print(f"  budget:          {result.get('budget_remaining', '?')} CNY remaining")
    print(f"  cloud-ok:        {result['cloud_ok']}")
    print(f"  real-run:        {result['real_run']}")
    print(f"  would-call:      {result['would_call_deepseek']}")
    print(f"  {api}")
    print(f"  cost-recorded:   {result['cost_recorded']}")
    print(f"  reason:          {result['reason']}")


if __name__ == "__main__":
    main()
