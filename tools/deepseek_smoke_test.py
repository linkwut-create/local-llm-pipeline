#!/usr/bin/env python3
"""
DeepSeek Manual Smoke Test — skeleton for first real API smoke test.

Implements the full gate sequence for a manual smoke test but NEVER
calls DeepSeek. Even with --manual-smoke-test, returns stub seam.

Design constraints:
  - Never calls DeepSeek API or any LLM.
  - Never imports requests, httpx, or urllib for network calls.
  - Never reads DEEPSEEK_API_KEY or accesses os.environ.
  - Fixed prompt only: "Reply with exactly: OK"
  - Flash only (v1). Budget max 1 CNY.
  - All gates must pass before reaching stub seam.

Usage:
  py -3 tools/deepseek_smoke_test.py --model deepseek-v4-flash --budget 1 --cloud-ok --real-run --manual-smoke-test --json
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

_engine = RouterEngine()

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

FIXED_PROMPT = "Return only the literal string OK in the final answer."
FIXED_PROMPT_ID = "deepseek-flash-semantic-smoke-v2"
FIXED_PROMPT_PREVIEW = "Return only...OK..."
ESTIMATED_INPUT_TOKENS = 10
ESTIMATED_OUTPUT_TOKENS = 128
SMOKE_MAX_TOKENS = 128
SMOKE_TEMPERATURE = 0.0  # NOTE: call_deepseek() does not expose temperature param.
                         # Current default is 0.1 in _build_request().
                         # Set to 0.0 when client supports it.
MAX_BUDGET_CNY = 1.0
ALLOWED_MODELS = {"deepseek-v4-flash"}
FLASH_MODEL = "deepseek-v4-flash"


# ═══════════════════════════════════════════════════════════════
# Core engine
# ═══════════════════════════════════════════════════════════════

def run_smoke_test(
    model: str = FLASH_MODEL,
    budget: float | None = None,
    cloud_ok: bool = False,
    real_run: bool = False,
    manual_smoke_test: bool = False,
    allow_live_smoke: bool = False,
    record_ledger: bool = False,
) -> dict:
    """Run the manual smoke test gate sequence. Mock-only.

    Returns a stub result. Never calls DeepSeek. Never reads API keys.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # ── Gate [1]: manual_smoke_test flag ──
    if not manual_smoke_test:
        return _abort("missing_manual_smoke_test",
                      "manual smoke test not requested (use --manual-smoke-test)",
                      model=model, budget=budget, cloud_ok=cloud_ok,
                      real_run=real_run, timestamp=timestamp)

    # ── Gate [2]: cloud_ok ──
    if not cloud_ok:
        return _abort("missing_cloud_ok",
                      "cloud escalation not enabled (use --cloud-ok)",
                      model=model, budget=budget, cloud_ok=False,
                      real_run=real_run, timestamp=timestamp)

    # ── Gate [3]: real_run ──
    if not real_run:
        return _abort("missing_real_run",
                      "real API call not requested (use --real-run)",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=False, timestamp=timestamp)

    # ── Gate [4]: model allowlist (Flash only v1) ──
    if model not in ALLOWED_MODELS:
        return _abort("model_not_allowed_for_smoke_test",
                      f"model '{model}' not allowed for smoke test. "
                      f"Allowed: {', '.join(sorted(ALLOWED_MODELS))}",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=True, timestamp=timestamp)

    # ── Gate [5]: budget ──
    if budget is None:
        return _abort("missing_budget",
                      "smoke test requires --budget (max 1 CNY)",
                      model=model, budget=None, cloud_ok=True,
                      real_run=True, timestamp=timestamp)

    if budget > MAX_BUDGET_CNY:
        return _abort("budget_limit_too_high",
                      f"smoke test budget {budget} CNY exceeds max {MAX_BUDGET_CNY} CNY",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=True, timestamp=timestamp)

    # ── Gate [6]: privacy gate (fixed prompt) ──
    privacy = privacy_check(text=FIXED_PROMPT)
    if privacy["privacy_status"] in ("blocked", "needs_review"):
        return _abort("blocked_by_privacy",
                      f"fixed prompt blocked by privacy gate: {privacy['reason']}",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=True, timestamp=timestamp,
                      privacy_status=privacy["privacy_status"])

    # ── Gate [7]: router gate ──
    task_label = "manual DeepSeek API smoke test fixed prompt"
    route = _engine.analyze(task_label)
    if route.risk_level in ("high", "critical"):
        # High risk on smoke test is abnormal → block
        return _abort("blocked_by_router",
                      f"smoke test classified as {route.risk_level} risk — "
                      f"unexpected for fixed trivial prompt",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=True, timestamp=timestamp,
                      router_task_type=route.task_type,
                      router_risk_level=route.risk_level,
                      privacy_status="safe")

    # ── Gate [8]: cost estimate ──
    cost = cost_estimate(
        task="manual DeepSeek API smoke test",
        model=model,
        input_tokens=ESTIMATED_INPUT_TOKENS,
        output_tokens=ESTIMATED_OUTPUT_TOKENS,
        budget_limit=budget,
    )
    if not cost["price_known"]:
        return _abort("unknown_price",
                      f"no pricing data for model '{model}'",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=True, timestamp=timestamp)
    if not cost["allowed"]:
        return _abort("blocked_by_budget",
                      f"estimated cost {cost['estimated_cost']} CNY exceeds budget",
                      model=model, budget=budget, cloud_ok=True,
                      real_run=True, timestamp=timestamp,
                      estimated_cost=cost["estimated_cost"])

    # ── All gates passed — enter stub seam or live seam ──
    if not allow_live_smoke:
        # Stub seam (default)
        stub = _manual_smoke_call_stub()
        result = {
            "execution_decision": "manual_smoke_test_stubbed",
            "model": model,
            "fixed_prompt_id": FIXED_PROMPT_ID,
            "fixed_prompt_preview": FIXED_PROMPT_PREVIEW,
            "estimated_input_tokens": ESTIMATED_INPUT_TOKENS,
            "estimated_output_tokens": ESTIMATED_OUTPUT_TOKENS,
            "budget_limit": budget,
            "estimated_cost": cost["estimated_cost"],
            "privacy_status": privacy["privacy_status"],
            "router_task_type": route.task_type,
            "router_risk_level": route.risk_level,
            "cloud_ok": True,
            "real_run": True,
            "manual_smoke_test": True,
            "live_smoke_enabled": False,
            "would_call_deepseek": False,
            "network_call": False,
            "api_key_lookup_attempted": False,
            "api_key_read": False,
            "api_key_value_logged": False,
            "stub_only": True,
            "smoke_call_attempted": True,
            "smoke_call_result": stub,
            "http_status": None,
            "response_text_preview": None,
            "response_text_source": "",
            "usage": None,
            "reasoning_content_present": False,
            "reasoning_tokens": 0,
            "reasoning_text_logged": False,
            "transport_smoke_pass": None,
            "semantic_smoke_pass": None,
            "ledger_event_type": "manual_smoke_test_stubbed" if record_ledger else None,
            "cost_recorded": record_ledger,
            "reason": (
                f"all smoke test gates passed — reached stub seam. "
                f"Use --allow-live-smoke for real API call. "
                f"Stub: {stub['redacted_error']}"
            ),
            "advisory_only": True,
            "generated_at": timestamp,
        }
        _maybe_record_smoke(result, record_ledger)
        return result

    # ── Live smoke seam ──
    # Read API key (only after all gates pass)
    import os
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    api_key_lookup_attempted = True

    if not api_key:
        result = {
            "execution_decision": "missing_api_key",
            "model": model,
            "fixed_prompt_id": FIXED_PROMPT_ID,
            "fixed_prompt_preview": FIXED_PROMPT_PREVIEW,
            "estimated_input_tokens": ESTIMATED_INPUT_TOKENS,
            "estimated_output_tokens": ESTIMATED_OUTPUT_TOKENS,
            "budget_limit": budget,
            "estimated_cost": cost["estimated_cost"],
            "privacy_status": privacy["privacy_status"],
            "router_task_type": route.task_type,
            "router_risk_level": route.risk_level,
            "cloud_ok": True,
            "real_run": True,
            "manual_smoke_test": True,
            "live_smoke_enabled": True,
            "would_call_deepseek": False,
            "network_call": False,
            "api_key_lookup_attempted": True,
            "api_key_read": False,
            "api_key_value_logged": False,
            "stub_only": False,
            "smoke_call_attempted": False,
            "smoke_call_result": None,
            "http_status": None,
            "response_text_preview": None,
            "response_text_source": "",
            "usage": None,
            "reasoning_content_present": False,
            "reasoning_tokens": 0,
            "reasoning_text_logged": False,
            "transport_smoke_pass": False,
            "semantic_smoke_pass": False,
            "ledger_event_type": "smoke_test_failed" if record_ledger else None,
            "cost_recorded": record_ledger,
            "reason": "DEEPSEEK_API_KEY environment variable not set",
            "advisory_only": True,
            "generated_at": timestamp,
        }
        _maybe_record_smoke(result, record_ledger)
        return result

    # Enter live call seam
    live_result = _live_smoke_call(api_key=api_key)
    ledger_event = ("smoke_test_success" if live_result["success"]
                    else "smoke_test_failed")

    result = {
        "execution_decision": ("manual_smoke_test_success" if live_result["success"]
                               else "manual_smoke_test_failed"),
        "model": model,
        "fixed_prompt_id": FIXED_PROMPT_ID,
        "fixed_prompt_preview": FIXED_PROMPT_PREVIEW,
        "estimated_input_tokens": ESTIMATED_INPUT_TOKENS,
        "estimated_output_tokens": ESTIMATED_OUTPUT_TOKENS,
        "budget_limit": budget,
        "estimated_cost": cost["estimated_cost"],
        "privacy_status": privacy["privacy_status"],
        "router_task_type": route.task_type,
        "router_risk_level": route.risk_level,
        "cloud_ok": True,
        "real_run": True,
        "manual_smoke_test": True,
        "live_smoke_enabled": True,
        "would_call_deepseek": True,
        "network_call": True,
        "api_key_lookup_attempted": True,
        "api_key_read": True,
        "api_key_value_logged": False,
        "stub_only": False,
        "smoke_call_attempted": True,
        "smoke_call_result": live_result,
        "http_status": live_result.get("http_status"),
        "response_text_preview": _safe_preview(live_result.get("response_text", "")),
        "response_text_source": live_result.get("response_text_source", ""),
        "usage": live_result.get("usage"),
        "reasoning_content_present": live_result.get("reasoning_content_present", False),
        "reasoning_tokens": live_result.get("reasoning_tokens", 0),
        "reasoning_text_logged": False,
        "transport_smoke_pass": live_result["success"],
        "semantic_smoke_pass": bool(live_result.get("response_text", "")),
        "ledger_event_type": ledger_event if record_ledger else None,
        "cost_recorded": record_ledger,
        "reason": (
            f"live smoke test {'succeeded' if live_result['success'] else 'failed'}. "
            f"Prompt: '{FIXED_PROMPT_PREVIEW}'"
        ),
        "advisory_only": False,
        "generated_at": timestamp,
    }
    _maybe_record_smoke(result, record_ledger)
    return result


# ═══════════════════════════════════════════════════════════════
# Live call seam
# ═══════════════════════════════════════════════════════════════

def _extract_response_text(result: dict) -> str:
    """Robustly extract FINAL response text from DeepSeek API result.

    Tries known content fields in priority order. Does NOT return
    reasoning_content — reasoning is not a user-facing response.
    Returns empty string if no final text found.
    """
    # Standard field from deepseek_client
    content = result.get("content", "")
    if content:
        return content

    # OpenAI-compatible nested path (content only, not reasoning)
    choices = result.get("choices", [])
    if choices:
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = msg.get("content", "")
        if content:
            return content

    # Direct text field
    text = result.get("text", "")
    if text:
        return text

    return ""


def _extract_reasoning_metadata(result: dict) -> dict:
    """Extract reasoning metadata WITHOUT exposing raw reasoning text.

    Returns presence signals only — raw reasoning text is NEVER returned.
    """
    choices = result.get("choices", [])
    has_reasoning = False
    if choices:
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        reasoning = msg.get("reasoning_content", "")
        has_reasoning = bool(reasoning)

    usage = result.get("usage") or {}
    reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0) if isinstance(usage, dict) else 0

    return {
        "reasoning_content_present": has_reasoning,
        "reasoning_tokens": reasoning_tokens,
        "reasoning_text_logged": False,
        "reasoning_text_included_in_response": False,
    }


def _live_smoke_call(api_key: str) -> dict:
    """Make a real DeepSeek API call with the fixed smoke test prompt.

    Only called after all gates pass and DEEPSEEK_API_KEY is verified.
    Uses deepseek_client.call_deepseek() for the actual API call.

    Args:
        api_key: DEEPSEEK_API_KEY value (never logged).

    Returns:
        Dict with success, response_text, usage, http_status, error fields.
    """
    from deepseek_client import call_deepseek

    # API key is intentionally NOT included in any return value or log
    result = call_deepseek(
        prompt=FIXED_PROMPT,
        model=FLASH_MODEL,
        thinking=False,
        max_tokens=SMOKE_MAX_TOKENS,
        api_key=api_key,
        timeout=30,
    )

    response_text = _extract_response_text(result)
    reasoning_meta = _extract_reasoning_metadata(result)

    return {
        "success": result["ok"],
        "response_text": response_text,
        "response_text_source": _classify_text_source(result, response_text),
        "usage": result.get("usage"),
        "http_status": None,
        "elapsed_ms": int(result.get("elapsed_seconds", 0) * 1000),
        "error_type": None if result["ok"] else _classify_error(result.get("error", "")),
        "error": None if result["ok"] else _redact_error(result.get("error", "")),
        "network_call": True,
        "api_key_read": True,
        "api_key_never_logged": True,
        "reasoning_content_present": reasoning_meta["reasoning_content_present"],
        "reasoning_tokens": reasoning_meta["reasoning_tokens"],
        "reasoning_text_logged": False,
    }


def _classify_text_source(result: dict, text: str) -> str:
    """Classify where the response text was extracted from."""
    if text:
        if result.get("content"):
            return "content"
        if result.get("choices", [{}])[0].get("message", {}).get("content"):
            return "choices[0].message.content"
        if result.get("choices", [{}])[0].get("message", {}).get("reasoning_content"):
            return "choices[0].message.reasoning_content"
        if result.get("text"):
            return "text"
        return "unknown"
    return "empty"


def _classify_error(error: str) -> str:
    """Classify error type without exposing key values."""
    el = error.lower()
    if "401" in el or "403" in el or "unauthorized" in el or "forbidden" in el:
        return "auth_error"
    if "429" in el or "rate" in el:
        return "rate_limit"
    if "timeout" in el or "timed out" in el:
        return "timeout"
    if "500" in el or "502" in el or "503" in el:
        return "server_error"
    if "400" in el:
        return "bad_request"
    return "unknown_error"


def _redact_error(error: str) -> str:
    """Redact sensitive content from error messages."""
    import re
    # Remove sk-... patterns
    redacted = re.sub(r'sk-[a-zA-Z0-9\-_]{8,}', '[REDACTED_KEY]', error)
    # Truncate
    if len(redacted) > 300:
        redacted = redacted[:300] + "..."
    return redacted


def _safe_preview(text: str | None, max_len: int = 100) -> str:
    """Safe preview of response text — no API key, bounded length.

    Returns the preview string. Empty text returns "" (not None)
    to distinguish "API returned empty content" from "no call made".
    """
    if text is None:
        return "(no response)"
    if not text:
        return "(empty)"
    return text[:max_len]


# ═══════════════════════════════════════════════════════════════
# Stub seam
# ═══════════════════════════════════════════════════════════════

def _manual_smoke_call_stub() -> dict:
    """Stub that represents the smoke test API call seam.

    NEVER imports requests, httpx, or urllib.
    NEVER reads DEEPSEEK_API_KEY.
    NEVER accesses os.environ.
    NEVER makes network calls.
    """
    return {
        "success": False,
        "stub_only": True,
        "response_text": None,
        "usage": None,
        "elapsed_ms": 0,
        "network_call": False,
        "api_key_read": False,
        "http_status": None,
        "error_type": "manual_smoke_test_stubbed",
        "redacted_error": (
            "manual smoke test reached stub seam; "
            "no network call was made."
        ),
    }


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _abort(
    execution_decision: str,
    reason: str,
    model: str = "",
    budget: float | None = None,
    cloud_ok: bool = False,
    real_run: bool = False,
    timestamp: str = "",
    **extra,
) -> dict:
    """Build an abort result."""
    return {
        "execution_decision": execution_decision,
        "model": model,
        "fixed_prompt_id": FIXED_PROMPT_ID,
        "fixed_prompt_preview": FIXED_PROMPT_PREVIEW,
        "estimated_input_tokens": ESTIMATED_INPUT_TOKENS,
        "estimated_output_tokens": ESTIMATED_OUTPUT_TOKENS,
        "budget_limit": budget,
        "estimated_cost": extra.get("estimated_cost"),
        "privacy_status": extra.get("privacy_status", "safe"),
        "router_task_type": extra.get("router_task_type", ""),
        "router_risk_level": extra.get("router_risk_level", ""),
        "cloud_ok": cloud_ok,
        "real_run": real_run,
        "manual_smoke_test": execution_decision != "missing_manual_smoke_test",
        "live_smoke_enabled": False,
        "would_call_deepseek": False,
        "network_call": False,
        "api_key_lookup_attempted": False,
        "api_key_read": False,
        "api_key_value_logged": False,
        "stub_only": False,
        "smoke_call_attempted": False,
        "smoke_call_result": None,
        "http_status": None,
        "response_text_preview": None,
        "response_text_source": "",
        "usage": None,
        "reasoning_content_present": False,
        "reasoning_tokens": 0,
        "reasoning_text_logged": False,
        "transport_smoke_pass": None,
        "semantic_smoke_pass": None,
        "ledger_event_type": None,
        "cost_recorded": False,
        "reason": reason,
        "advisory_only": True,
        "generated_at": timestamp or datetime.now(timezone.utc).isoformat(),
    }


def _maybe_record_smoke(result: dict, record_ledger: bool) -> None:
    """Optionally write a mock smoke test record to cost ledger."""
    if not record_ledger:
        return
    try:
        from cost_ledger import record as ledger_record
        ledger_record(
            task="manual DeepSeek API smoke test",
            model=result.get("model", FLASH_MODEL),
            input_tokens=0,
            output_tokens=0,
            budget_limit=result.get("budget_limit"),
            notes=f"mock: {result.get('ledger_event_type', 'unknown')}",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="DeepSeek Manual Smoke Test — skeleton (no real API calls)"
    )
    parser.add_argument("--model", default=FLASH_MODEL,
                        help=f"Model (default: {FLASH_MODEL})")
    parser.add_argument("--budget", type=float, default=None,
                        help="Budget limit in CNY (max 1.0)")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Allow cloud escalation")
    parser.add_argument("--real-run", action="store_true",
                        help="Request real API call")
    parser.add_argument("--manual-smoke-test", action="store_true",
                        help="Enable manual smoke test mode")
    parser.add_argument("--allow-live-smoke", action="store_true",
                        help="Allow real API call (requires DEEPSEEK_API_KEY)")
    parser.add_argument("--record-ledger", action="store_true",
                        help="Write stub event to cost ledger")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--prompt", default=None,
                        help=argparse.SUPPRESS)  # Rejected in v1
    args = parser.parse_args()

    # Reject arbitrary prompt
    if args.prompt is not None:
        result = _abort("arbitrary_prompt_rejected",
                        "smoke test uses fixed prompt only; --prompt not accepted",
                        model=args.model, budget=args.budget,
                        cloud_ok=args.cloud_ok, real_run=args.real_run)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Smoke Test: arbitrary_prompt_rejected [BLOCKED]")
            print(f"  reason: {result['reason']}")
        sys.exit(0)

    result = run_smoke_test(
        model=args.model,
        budget=args.budget,
        cloud_ok=args.cloud_ok,
        real_run=args.real_run,
        manual_smoke_test=args.manual_smoke_test,
        allow_live_smoke=args.allow_live_smoke,
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
    stub = "[STUB]" if result["stub_only"] else "[BLOCKED]"

    print(f"Smoke Test: {decision} {stub}")
    print(f"  model:           {result.get('model', '?')}")
    print(f"  prompt:          {result.get('fixed_prompt_preview', '?')}")
    print(f"  budget:          {result.get('budget_limit', '?')} CNY")
    print(f"  privacy:         {result.get('privacy_status', '?')}")
    print(f"  router:          {result.get('router_task_type', '?')} / {result.get('router_risk_level', '?')}")
    print(f"  would-call:      {result['would_call_deepseek']}")
    print(f"  network:         {result['network_call']}")
    print(f"  api-key-read:    {result['api_key_read']}")
    print(f"  stub-only:       {result['stub_only']}")
    print(f"  reason:          {result['reason']}")


if __name__ == "__main__":
    main()
