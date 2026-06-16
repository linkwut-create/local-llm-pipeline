#!/usr/bin/env python3
"""Escalation Dispatcher — execute tasks per route.json with auto model switching.

Reads route.json (from local route committee), then dispatches each phase
to the correct model tier. Tracks results, handles fallback on failure.

Route → Action mapping:
  local_only     → local model (Ollama)
  flash_direct   → DeepSeek Flash (direct API, no subagent)
  flash_subagent → DeepSeek Flash (subagent pattern)
  pro_decision   → DeepSeek Pro (full capability)
  blocked        → abort
  ask_user       → pause, wait for human input
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


# ═══════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════

@dataclass
class PhaseResult:
    phase: str
    route: str
    model: str
    success: bool
    output: str
    elapsed_ms: int
    tokens_used: int
    cost_cny: float
    error: str


@dataclass
class DispatchResult:
    task: str
    route_file: str
    phases: list[PhaseResult] = field(default_factory=list)
    total_cost: float = 0.0
    total_elapsed_ms: int = 0
    escalated: bool = False
    escalation_reason: str = ""


# ═══════════════════════════════════════════════════════════════
# Local execution
# ═══════════════════════════════════════════════════════════════

def _run_local(task: str, profile: str = "fast_summary") -> tuple[bool, str, int]:
    """Execute a task using a local Ollama model."""
    model_map = {
        "fast_summary": "gemma4:e4b",
        "code_worker": "qwen3-coder:30b",
        "commit_reviewer": "qwen3-coder:30b",
        "diff_reviewer": "nemotron:30b",
    }
    model = model_map.get(profile, "qwen3-coder:30b")

    import urllib.request
    body = json.dumps({
        "model": model,
        "prompt": task[:2000],
        "stream": False,
        "options": {"num_predict": 512, "temperature": 0.0},
    }).encode("utf-8")
    base = os.environ.get("OLLAMA_HOST", "http://193.168.2.2:11434")
    url = base.rstrip("/") + "/api/generate"

    try:
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, data.get("response", ""), data.get("eval_count", 0)
    except Exception as e:
        return False, str(e)[:300], 0


# ═══════════════════════════════════════════════════════════════
# Cloud execution
# ═══════════════════════════════════════════════════════════════

def _run_cloud(task: str, model: str, max_tokens: int = 1024) -> tuple[bool, str, int, float]:
    """Execute a task via DeepSeek API. Returns (ok, content, tokens, cost_cny)."""
    from deepseek_client import call_deepseek

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return False, "DEEPSEEK_API_KEY not set", 0, 0.0

    result = call_deepseek(
        prompt=task[:4000],
        model=model,
        max_tokens=max_tokens,
        api_key=api_key,
        timeout=180,
    )

    ok = result.get("ok", False)
    content = result.get("content", "")
    usage = result.get("usage") or {}
    tokens = usage.get("total_tokens", 0)

    # Cost estimate
    if "pro" in model.lower():
        cost = (usage.get("prompt_tokens", 0) * 0.55 + usage.get("completion_tokens", 0) * 2.19) / 1_000_000
    else:
        cost = (usage.get("prompt_tokens", 0) * 0.14 + usage.get("completion_tokens", 0) * 0.28) / 1_000_000

    if not ok:
        return False, result.get("error", content)[:300], tokens, cost

    return True, content, tokens, cost


# ═══════════════════════════════════════════════════════════════
# Dispatcher
# ═══════════════════════════════════════════════════════════════

def dispatch(route_path: str | Path, task: str = "",
             cloud_ok: bool = False, max_budget: float = 10.0) -> DispatchResult:
    """Read route.json and execute each phase with the correct model.

    Args:
        route_path: Path to route.json
        task: Task description (override; if empty, read from route context)
        cloud_ok: Allow cloud API calls for Flash/Pro routes
        max_budget: Hard budget cap in CNY

    Returns:
        DispatchResult with per-phase results and total cost.
    """
    route_file = Path(route_path)
    if not route_file.exists():
        return DispatchResult(task=task, route_file=str(route_file))

    route = json.loads(route_file.read_text(encoding="utf-8"))
    route_type = route.get("recommended_route", "ask_user")

    result = DispatchResult(task=task or route.get("reason", ""),
                            route_file=str(route_file))

    # Short-circuit: blocked or ask_user
    if route_type == "blocked":
        result.escalated = True
        result.escalation_reason = "route is blocked"
        return result
    if route_type == "ask_user":
        result.escalated = True
        result.escalation_reason = "route requires human decision"
        return result

    # Build execution plan from route
    phases = []
    if route.get("local_preprocessing_required"):
        phases.append(("local_preprocess", "local_only", "fast_summary", task))

    phases.append(("main", route_type, route_type, task))

    for phase_name, phase_route, phase_model, phase_task in phases:
        started = time.monotonic()
        ok, output, tokens, cost = False, "", 0, 0.0

        if phase_route == "local_only":
            ok, output, tokens = _run_local(phase_task, profile=phase_model)
            cost = 0.0
        elif phase_route in ("flash_direct", "flash_subagent"):
            if not cloud_ok:
                output = "cloud_ok not set — skipping Flash call"
                ok = False
            else:
                flash_model = "deepseek-v4-flash"
                ok, output, tokens, cost = _run_cloud(phase_task, flash_model)
        elif phase_route == "pro_decision":
            if not cloud_ok:
                output = "cloud_ok not set — skipping Pro call"
                ok = False
            else:
                pro_model = "deepseek-v4-pro"
                ok, output, tokens, cost = _run_cloud(phase_task, pro_model, max_tokens=2048)

        elapsed = int((time.monotonic() - started) * 1000)
        result.total_cost += cost
        result.total_elapsed_ms += elapsed

        result.phases.append(PhaseResult(
            phase=phase_name,
            route=phase_route,
            model=phase_model,
            success=ok,
            output=output[:500],
            elapsed_ms=elapsed,
            tokens_used=tokens,
            cost_cny=cost,
            error="" if ok else output[:200],
        ))

        # Budget check
        if result.total_cost > max_budget:
            result.escalated = True
            result.escalation_reason = f"budget exceeded: {result.total_cost:.4f} CNY > {max_budget}"
            break

        # Escalate on any cloud failure (flash_direct, flash_subagent)
        if not ok and cloud_ok and phase_route.startswith("flash_"):
            result.escalated = True
            result.escalation_reason = "Flash failed — escalate to Pro"
            # Try Pro as fallback
            pro_ok, pro_out, pro_tok, pro_cost = _run_cloud(
                phase_task, "deepseek-v4-pro", max_tokens=2048)
            pro_elapsed = int((time.monotonic() - started) * 1000) - elapsed
            result.total_cost += pro_cost
            result.total_elapsed_ms += pro_elapsed
            result.phases.append(PhaseResult(
                phase="pro_fallback",
                route="pro_decision",
                model="deepseek-v4-pro",
                success=pro_ok,
                output=pro_out[:500],
                elapsed_ms=pro_elapsed,
                tokens_used=pro_tok,
                cost_cny=pro_cost,
                error="" if pro_ok else pro_out[:200],
            ))

    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Escalation Dispatcher — execute tasks per route.json")
    parser.add_argument("--route", required=True, help="Path to route.json")
    parser.add_argument("--task", default="", help="Task description override")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Allow cloud API calls")
    parser.add_argument("--max-budget", type=float, default=10.0,
                        help="Hard budget cap in CNY")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = dispatch(
        route_path=args.route,
        task=args.task,
        cloud_ok=args.cloud_ok,
        max_budget=args.max_budget,
    )

    if args.json:
        output = {
            "task": result.task,
            "route_file": result.route_file,
            "phases": [{
                "phase": p.phase,
                "route": p.route,
                "model": p.model,
                "success": p.success,
                "output": p.output[:200],
                "elapsed_ms": p.elapsed_ms,
                "tokens": p.tokens_used,
                "cost_cny": p.cost_cny,
                "error": p.error,
            } for p in result.phases],
            "total_cost": round(result.total_cost, 6),
            "total_elapsed_ms": result.total_elapsed_ms,
            "escalated": result.escalated,
            "escalation_reason": result.escalation_reason,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Task: {result.task}")
        print(f"Route: {result.route_file}")
        for p in result.phases:
            status = "✓" if p.success else "✗"
            print(f"  {status} {p.phase} ({p.route}): {p.model} "
                  f"{p.elapsed_ms}ms {p.tokens_used}t {p.cost_cny:.6f}CNY")
        print(f"Total: {result.total_cost:.6f} CNY, {result.total_elapsed_ms}ms")
        if result.escalated:
            print(f"Escalated: {result.escalation_reason}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
