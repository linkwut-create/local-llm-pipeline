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
  - would_call_deepseek is ALWAYS false.
  - api_key_read is ALWAYS false.
  - network_call is ALWAYS false.
  - --real-run with all gates passed → reaches guarded API call stub seam
    (real_run_stubbed), but the stub never makes network calls.

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

# Flash limited real-run constraints
FLASH_LIMITED_MAX_BUDGET = 0.5   # CNY per call
FLASH_LIMITED_MAX_INPUT = 4000   # tokens
FLASH_LIMITED_MAX_OUTPUT = 1024  # tokens
FLASH_LIMITED_ALLOWED_TASKS = {
    "review-diff", "summarize-file", "suggest-improvements",
    "draft-fix", "generate-test-plan", "translate-text",
    "rewrite-text", "deep-code-review",
}
FLASH_LIMITED_BLOCKED_TASKS = {
    "release-risk-review", "security-review", "interface-review",
    "api-execution-boundary", "architecture-review",
}


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
    flash_limited: bool = False,
    manual_confirm: bool = False,
    input_text: str = "",
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

    # ═══════════════════════════════════════════════════════════════
    # Flash limited real-run path
    # ═══════════════════════════════════════════════════════════════
    if flash_limited:
        return _execute_flash_limited(
            task=task, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            budget=budget, cloud_ok=cloud_ok, real_run=real_run,
            manual_confirm=manual_confirm, input_text=input_text,
            record_ledger=record_ledger, timestamp=timestamp,
        )

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
        # Privacy needs_review → hard block for real-run (v1)
        if privacy_needs_review:
            result = _abort(
                task=task, model=model,
                execution_decision="blocked_by_privacy",
                reason=(
                    f"real_run blocked: privacy status is needs_review — "
                    f"human review required before real API call. "
                    f"Privacy: {privacy['reason']}"
                ),
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
            _maybe_record(result, record_ledger)
            return result

        # All gates passed — enter guarded API call stub seam
        stub = _guarded_api_call_stub(
            task=task, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        result = _result_base(
            task=task, model=model,
            execution_decision="real_run_stubbed",
            dry_run_decision=dry["decision"],
            reason=(
                f"all governance gates passed — reached guarded API call seam. "
                f"Stub response: {stub['redacted_error']}. "
                f"Dry-run: {dry['reason']}"
            ),
            router_task_type=route.task_type,
            router_risk_level=route.risk_level,
            privacy_status=privacy["privacy_status"],
            privacy_needs_review=False,
            estimated_cost=cost["estimated_cost"],
            budget_limit=budget,
            budget_remaining=cost.get("budget_remaining"),
            cloud_ok=True, real_run=True,
            input_tokens=input_tokens, output_tokens=output_tokens,
            timestamp=timestamp,
            recommended_model=dry.get("recommended_model", model),
            ledger_event_type="real_run_stubbed",
            stub_only=True,
            network_call=False,
            api_call_attempted=True,
            api_call_result=stub,
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
# Guarded API call stub seam
# ═══════════════════════════════════════════════════════════════

def _guarded_api_call_stub(
    task: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict:
    """Stub that represents the API call seam without making real calls.

    NEVER imports requests/httpx. NEVER reads DEEPSEEK_API_KEY.
    NEVER accesses os.environ. NEVER makes network calls.

    Returns a stub result dict that the real-run path can embed.
    """
    # Deliberately NOT importing: requests, httpx, urllib, os.environ
    return {
        "success": False,
        "stub_only": True,
        "response_text": None,
        "usage": None,
        "elapsed_ms": 0,
        "network_call": False,
        "api_key_read": False,
        "http_status": None,
        "error_type": "stubbed_real_run",
        "redacted_error": (
            "real API call seam reached but external call is disabled "
            "in this skeleton. No network request was made."
        ),
    }


# ═══════════════════════════════════════════════════════════════
# Flash limited real-run
# ═══════════════════════════════════════════════════════════════

def _fl_abort(decision: str, reason: str, **kw) -> dict:
    """Shortcut for flash-limited abort with mode preset."""
    return _abort(
        task=kw.pop("task", ""), model=kw.pop("model", FLASH_MODEL),
        execution_decision=decision, reason=reason, **kw,
    )


def _execute_flash_limited(
    task: str, model: str,
    input_tokens: int, output_tokens: int,
    budget: float | None, cloud_ok: bool, real_run: bool,
    manual_confirm: bool, input_text: str,
    record_ledger: bool, timestamp: str,
) -> dict:
    """Execute the flash-limited gate sequence. Stub only."""
    fl = {"task": task, "model": model, "mode": "flash_limited",
          "real_run": real_run, "timestamp": timestamp}
    co = {**fl, "cloud_ok": cloud_ok, "budget": budget}

    if not manual_confirm:
        return _fl_abort("missing_manual_confirm",
                         "manual confirmation required", **co)
    if not cloud_ok:
        return _fl_abort("cloud_ok_required",
                         "cloud escalation not enabled (use --cloud-ok)",
                         **{**co, "cloud_ok": False})
    if not real_run:
        return _fl_abort("mock_plan_ready",
                         "real_run not requested", **co)
    if model != FLASH_MODEL:
        return _fl_abort("model_not_allowed_for_flash_limited",
                         f"model '{model}' not allowed", **co)

    privacy = privacy_check(text=task)
    if privacy["privacy_status"] in ("blocked", "needs_review"):
        return _fl_abort("blocked_by_privacy",
                         f"task: {privacy['reason']}",
                         privacy_status=privacy["privacy_status"], **co)

    input_privacy_status = "safe"
    if input_text:
        ip = privacy_check(text=input_text)
        input_privacy_status = ip["privacy_status"]
        if input_privacy_status in ("blocked", "needs_review"):
            return _fl_abort("blocked_by_privacy",
                             f"input: {ip['reason']}",
                             privacy_status=privacy["privacy_status"],
                             input_privacy_status=input_privacy_status, **co)

    route = _engine.analyze(task)
    if route.risk_level in ("high", "critical"):
        return _fl_abort("needs_pro_review",
                         f"risk={route.risk_level}",
                         router_task_type=route.task_type,
                         router_risk_level=route.risk_level,
                         privacy_status=privacy["privacy_status"], **co)
    if route.task_type == "unknown":
        return _fl_abort("blocked_by_router",
                         "router cannot classify task",
                         router_task_type=route.task_type,
                         router_risk_level=route.risk_level,
                         privacy_status=privacy["privacy_status"], **co)
    if route.task_type in FLASH_LIMITED_BLOCKED_TASKS:
        return _fl_abort("blocked_by_router",
                         f"task type '{route.task_type}' blocked",
                         router_task_type=route.task_type,
                         router_risk_level=route.risk_level,
                         privacy_status=privacy["privacy_status"], **co)

    context_ok = (input_tokens <= FLASH_LIMITED_MAX_INPUT and
                  output_tokens <= FLASH_LIMITED_MAX_OUTPUT)
    if not context_ok:
        return _fl_abort("context_limit_exceeded",
                         f"in:{input_tokens}/{FLASH_LIMITED_MAX_INPUT} "
                         f"out:{output_tokens}/{FLASH_LIMITED_MAX_OUTPUT}",
                         router_task_type=route.task_type,
                         router_risk_level=route.risk_level,
                         privacy_status=privacy["privacy_status"], **co)

    if budget is None:
        return _fl_abort("missing_budget",
                         "flash-limited requires --budget", **co)
    if budget > FLASH_LIMITED_MAX_BUDGET:
        return _fl_abort("budget_limit_too_high_for_flash_limited",
                         f"{budget} > {FLASH_LIMITED_MAX_BUDGET}", **co)

    cost = cost_estimate(task=task, model=model,
                         input_tokens=input_tokens, output_tokens=output_tokens,
                         budget_limit=budget)
    if not cost["price_known"]:
        return _fl_abort("unknown_price", f"no pricing for '{model}'", **co)
    if not cost["allowed"]:
        return _fl_abort("blocked_by_budget",
                         f"est {cost['estimated_cost']} CNY",
                         estimated_cost=cost["estimated_cost"], **co)

    # ── All gates passed — stub seam ──
    result = {
        "execution_decision": "flash_limited_stubbed",
        "mode": "flash_limited",
        "model": model,
        "task": task,
        "router_task_type": route.task_type,
        "router_risk_level": route.risk_level,
        "privacy_status": privacy["privacy_status"],
        "input_privacy_status": input_privacy_status,
        "budget_limit": budget,
        "estimated_cost": cost["estimated_cost"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "max_input_tokens": FLASH_LIMITED_MAX_INPUT,
        "max_output_tokens": FLASH_LIMITED_MAX_OUTPUT,
        "context_limit_pass": True,
        "cloud_ok": True,
        "real_run": True,
        "flash_limited": True,
        "manual_confirm": True,
        "would_call_deepseek": False,
        "network_call": False,
        "api_key_lookup_attempted": False,
        "api_key_read": False,
        "stub_only": True,
        "api_call_attempted": False,
        "api_call_result": None,
        "error_type": None,
        "redacted_error": None,
        "ledger_event_type": "flash_limited_stubbed" if record_ledger else None,
        "cost_recorded": record_ledger,
        "reason": (
            f"all flash-limited gates passed — reached stub seam. "
            f"Privacy: task={privacy['privacy_status']}, input={input_privacy_status}. "
            f"Router: {route.task_type}/{route.risk_level}. "
            f"Cost: {cost['estimated_cost']} CNY. "
            f"Context: {input_tokens}/{FLASH_LIMITED_MAX_INPUT} in, "
            f"{output_tokens}/{FLASH_LIMITED_MAX_OUTPUT} out."
        ),
        "advisory_only": True,
        "generated_at": timestamp,
    }
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
    stub_only: bool = False,
    network_call: bool = False,
    api_call_attempted: bool = False,
    api_call_result: dict | None = None,
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
        "stub_only": stub_only,
        "network_call": network_call,
        "would_call_deepseek": False,
        "api_key_read": False,
        "api_call_attempted": api_call_attempted,
        "api_call_result": api_call_result,
        "error_type": api_call_result.get("error_type") if api_call_result else None,
        "redacted_error": api_call_result.get("redacted_error") if api_call_result else None,
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
        "stub_only": False,
        "network_call": False,
        "would_call_deepseek": False,
        "api_key_read": False,
        "api_call_attempted": False,
        "api_call_result": None,
        "error_type": None,
        "redacted_error": None,
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
    parser.add_argument("--flash-limited", action="store_true",
                        help="Enable Flash limited real-run mode")
    parser.add_argument("--manual-confirm", action="store_true",
                        help="Manual confirmation for real-run (required)")
    parser.add_argument("--input-text", default="",
                        help="Input text for flash-limited tasks")
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
        flash_limited=args.flash_limited,
        manual_confirm=args.manual_confirm,
        input_text=args.input_text,
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
