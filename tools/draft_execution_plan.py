#!/usr/bin/env python3
"""Draft Execution Plan — decompose a task into phases with per-phase model routing.

Design contract:
  - Default: heuristic planner (mock-only, no API calls, no cost)
  - --real-run --cloud-ok: DeepSeek Pro API (gated behind privacy/budget/dry-run)
  - Output: structured JSON execution plan with <phase, model, route, cost>
  - Advisory-only: controller makes final decisions, /model switching is manual

Phase D (v0.13.0 Full Escalation) integrates this with the auto-escalation skill
(.claude/skills/auto-escalate.md) for automatic /model switching.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Ensure tools/ is importable
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_explain import RouterEngine, TieringPolicy

# Resolve actual cloud model names once (from profiles, not hardcoded)
_FLASH_MODEL, _PRO_MODEL = TieringPolicy._get_cloud_models()


# ═══════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════

@dataclass
class Phase:
    """A single execution phase with model routing."""
    index: int
    name: str                          # human-readable phase name
    description: str                   # what to do in this phase
    task_type: str                     # router task type
    recommended_model: str             # which model to use
    execution_route: str               # local_only | flash_direct | flash_subagent | claude_code_pro
    cost_tier: str                     # free | cheap | moderate | expensive
    estimated_tokens: int = 0          # estimated input tokens
    local_profile: Optional[str] = None  # which local profile if local_only


@dataclass
class ExecutionPlan:
    """Complete execution plan for a task."""
    task: str
    phases: list[Phase] = field(default_factory=list)
    total_estimated_cost_cny: float = 0.0
    recommended_starting_model: str = "deepseek-v4-pro"
    planner_model: str = "heuristic"   # heuristic | deepseek-v4-pro
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "phases": [{
                "index": p.index,
                "name": p.name,
                "description": p.description,
                "task_type": p.task_type,
                "recommended_model": p.recommended_model,
                "execution_route": p.execution_route,
                "cost_tier": p.cost_tier,
                "estimated_tokens": p.estimated_tokens,
                "local_profile": p.local_profile,
            } for p in self.phases],
            "total_estimated_cost_cny": self.total_estimated_cost_cny,
            "recommended_starting_model": self.recommended_starting_model,
            "planner_model": self.planner_model,
            "advisory_only": self.advisory_only,
        }


# ═══════════════════════════════════════════════════════════════
# Phase templates — heuristic task decomposition patterns
# ═══════════════════════════════════════════════════════════════

# Each template: (task_type_pattern, [(phase_name, description_template, task_type_for_phase)])
# The task_type_for_phase is fed to RouterEngine to determine model/routing.
PHASE_TEMPLATES = {
    "default": [
        ("understand",  "Read and understand the relevant code, files, and context"),
        ("implement",   "Write the implementation or make the required changes"),
        ("test",        "Write or update tests for the changes"),
        ("review",      "Review the diff for bugs, test gaps, and compatibility issues"),
    ],
    "feature": [
        ("understand",  "Analyze existing code, interfaces, and design constraints"),
        ("plan",        "Design the implementation approach and identify affected files"),
        ("implement",   "Write the implementation code"),
        ("test",        "Write tests covering new functionality and edge cases"),
        ("review",      "Cross-review the complete diff for correctness and completeness"),
    ],
    "bug-fix": [
        ("understand",  "Reproduce and understand the bug, identify root cause"),
        ("implement",   "Write the minimal fix"),
        ("test",        "Add regression tests to prevent recurrence"),
        ("review",      "Verify the fix is correct, minimal, and well-tested"),
    ],
    "refactor": [
        ("understand",  "Understand the current code structure and coupling points"),
        ("implement",   "Perform the refactoring incrementally"),
        ("test",        "Run existing tests, add missing coverage"),
        ("review",      "Verify no behavioral changes, interfaces intact"),
    ],
    "docs": [
        ("understand",  "Review current documentation state"),
        ("implement",   "Write or update documentation"),
        ("review",      "Proofread and verify accuracy"),
    ],
    "release": [
        ("understand",  "Audit changes since last release, review changelog"),
        ("review",      "Security and interface review of all changes"),
        ("test",        "Full test suite run and flaky test analysis"),
        ("release",     "Version bump, tag, changelog finalization"),
    ],
}

# Mapping from task description keywords to template name
TEMPLATE_KEYWORDS = {
    "feature": ["feature", "implement", "add new", "build", "create"],
    "bug-fix": ["fix", "bug", "patch", "hotfix", "crash", "error", "exception"],
    "refactor": ["refactor", "restructure", "clean up", "simplify", "redesign"],
    "docs": ["documentation", "docs", "readme", "changelog", "comment"],
    "release": ["release", "deploy", "publish", "tag", "version bump"],
}


# ═══════════════════════════════════════════════════════════════
# Phase-to-task-type mapping (for RouterEngine consumption)
# ═══════════════════════════════════════════════════════════════

PHASE_TASK_TYPE = {
    "understand":  "summarize-file",      # cheap: local or Flash direct
    "plan":        "architecture-review", # high-stakes: Pro
    "implement":   "draft-feature",       # code mod: Pro
    "test":        "generate-test-plan",  # moderate: Flash subagent
    "review":      "review-diff",         # moderate: Flash subagent
    "release":     "release-risk-review", # high-stakes: Pro
}


# ═══════════════════════════════════════════════════════════════
# Cost estimation (static pricing, advisory-only)
# ═══════════════════════════════════════════════════════════════

def _estimate_phase_cost(route: str, tokens: int) -> float:
    """Estimate CNY cost for a phase based on route and token count."""
    rates = {
        "local_only":       0.0,        # free
        "blocked":          0.0,        # free (no call)
        "manual_confirm":   0.0,        # free (human decides)
        "flash_direct":     0.0004,     # ~0.0004 CNY per 1K tokens
        "flash_subagent":   0.0010,     # ~0.0010 CNY per 1K (includes overhead)
        "claude_code_pro":  0.0050,     # ~0.0050 CNY per 1K tokens
    }
    rate = rates.get(route, 0.001)
    return round(rate * (tokens / 1000), 6)


# ═══════════════════════════════════════════════════════════════
# Core planner
# ═══════════════════════════════════════════════════════════════

def _select_template(task: str) -> str:
    """Select a phase template based on task description keywords."""
    task_lower = task.lower()
    for template_name, keywords in TEMPLATE_KEYWORDS.items():
        if any(kw in task_lower for kw in keywords):
            return template_name
    return "default"


def _estimate_tokens(description: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(500, len(description) // 3)


def draft_execution_plan(task: str, cloud_ok: bool = False,
                         real_run: bool = False) -> ExecutionPlan:
    """Draft an execution plan for the given task.

    In mock mode (default), uses heuristic templates and the RouterEngine
    to assign models per phase. No cloud API calls, no cost.

    In real-run mode (--real-run --cloud-ok), would call DeepSeek Pro API.
    Currently returns real_run_not_implemented marker.
    """
    if real_run and cloud_ok:
        return _draft_real(task)

    # --- Heuristic mode ---
    template_name = _select_template(task)
    phases_spec = PHASE_TEMPLATES.get(template_name, PHASE_TEMPLATES["default"])
    engine = RouterEngine()

    plan = ExecutionPlan(task=task)

    for i, (phase_name, description) in enumerate(phases_spec, 1):
        task_type = PHASE_TASK_TYPE.get(phase_name, "summarize-file")

        # Get tiering for this phase's actual task_type, not the description.
        # The parent task's risk context is inherited only for the "implement"
        # and "review" phases; other phases use standalone routing.
        tier = TieringPolicy.resolve(task_type, "medium", "safe")
        route = tier["recommended_execution_route"]
        model = tier["recommended_model"]

        # For local_only routes, use the recommended local profile from the
        # RouterEngine (which knows about available local models)
        local_profile = None
        if route == "local_only":
            decision = engine.analyze(description)
            local_profile = decision.recommended_local_profile

        tokens = _estimate_tokens(description)

        # Resolve actual model name (never hardcoded)
        resolved_model = model or local_profile or "local"
        if resolved_model == "deepseek-v4-flash":
            resolved_model = _FLASH_MODEL
        elif resolved_model == "deepseek-v4-pro":
            resolved_model = _PRO_MODEL

        phase = Phase(
            index=i,
            name=phase_name,
            description=description,
            task_type=task_type,
            recommended_model=resolved_model,
            execution_route=route,
            cost_tier=tier["cost_tier"],
            estimated_tokens=tokens,
            local_profile=local_profile,
        )
        plan.phases.append(phase)
        plan.total_estimated_cost_cny += _estimate_phase_cost(route, tokens)

    plan.total_estimated_cost_cny = round(plan.total_estimated_cost_cny, 6)
    return plan


def _draft_real(task: str) -> ExecutionPlan:
    """Real DeepSeek Pro planning call — not yet implemented."""
    plan = ExecutionPlan(
        task=task,
        planner_model="deepseek-v4-pro",
    )
    plan.phases.append(Phase(
        index=0,
        name="real_planning_not_implemented",
        description=(
            "Real DeepSeek Pro planning is not yet implemented. "
            "Use --mock (default) for heuristic planning, or wait for "
            "Phase C (Flash real-run pilot) to unblock real API integration."
        ),
        task_type="api-execution-boundary",
        recommended_model="deepseek-v4-pro",
        execution_route="claude_code_pro",
        cost_tier="expensive",
    ))
    plan.total_estimated_cost_cny = 0.0
    return plan


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Draft execution plan with per-phase model routing")
    parser.add_argument("task", nargs="+", help="Task description")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Allow cloud API calls (for real-run)")
    parser.add_argument("--real-run", action="store_true",
                        help="Use real DeepSeek Pro API (requires --cloud-ok)")
    args = parser.parse_args()

    task = " ".join(args.task)
    plan = draft_execution_plan(
        task, cloud_ok=args.cloud_ok, real_run=args.real_run)

    if args.json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    else:
        # Human-readable output
        print(f"Task: {plan.task}")
        print(f"Planner: {plan.planner_model}")
        print(f"Template: {_select_template(task)}")
        print(f"Phases: {len(plan.phases)}")
        print(f"Estimated cost: {plan.total_estimated_cost_cny} CNY")
        print()
        for p in plan.phases:
            model_str = p.recommended_model or "local"
            route_symbol = {
                "local_only": "🏠", "flash_direct": "⚡", "flash_subagent": "🔀",
                "claude_code_pro": "🔴", "manual_confirm": "❓", "blocked": "🚫",
            }.get(p.execution_route, "❓")
            print(f"  {route_symbol} Phase {p.index}: {p.name}")
            print(f"     Task: {p.task_type}")
            print(f"     Model: /model {model_str}")
            print(f"     Route: {p.execution_route} ({p.cost_tier})")
            print(f"     {p.description}")
            if p.local_profile:
                print(f"     Local profile: {p.local_profile}")
            print()

        if plan.advisory_only:
            print("⚠ Advisory only — controller makes final model decisions.")
            print("  Use /model <name> to switch before each phase.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
