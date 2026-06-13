#!/usr/bin/env python3
"""
Claude Code Soft Gate — advisory governance check before key actions.

Composes router_explain + privacy_gate (+ cost_ledger for pre-cloud)
into a unified soft gate output. ALWAYS advisory-only. NEVER blocks.

Design constraints:
  - would_block is ALWAYS false (soft gate).
  - advisory_only is ALWAYS true.
  - Never calls DeepSeek API or any LLM.
  - Never reads API keys or secrets.
  - Never reads file contents.
  - Never modifies profiles, hooks, or MCP server.

Usage:
  py -3 tools/claude_soft_gate.py --stage pre-task --task "summarize README" --json
  py -3 tools/claude_soft_gate.py --stage pre-cloud --task "review diff" --cloud-ok --budget 0.5 --json
  py -3 tools/claude_soft_gate.py --stage pre-commit --task "update docs" --json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from router_explain import RouterEngine
from privacy_gate import check as privacy_check

_engine = RouterEngine()

VALID_STAGES = {"pre-task", "pre-commit", "pre-cloud"}

# ═══════════════════════════════════════════════════════════════
# Severity & decision mapping
# ═══════════════════════════════════════════════════════════════

def _severity_from_privacy(privacy_status: str) -> str:
    if privacy_status == "blocked":
        return "red"
    if privacy_status == "needs_review":
        return "orange"
    return "green"  # safe → determined by risk later


def _severity_from_risk(risk: str, task_type: str) -> str:
    if risk in ("high", "critical"):
        return "orange"
    if risk == "medium":
        return "yellow"
    return "green"


def _decision_from_severity(severity: str, privacy_status: str) -> str:
    if privacy_status == "blocked":
        return "cloud_blocked"
    if severity == "orange":
        return "manual_confirm_recommended"
    if severity == "yellow":
        return "warn"
    return "allow"


def _recommended_route(privacy_status: str, risk: str) -> str:
    if privacy_status == "blocked":
        return "cloud-blocked"
    if risk in ("high", "critical"):
        return "pro-review"
    if risk == "medium":
        return "flash-limited"
    return "local"


def _check_file_paths(files: list[str]) -> dict:
    """Check file paths via privacy_gate without reading file contents."""
    if not files:
        return {"privacy_status": "safe", "matched_found": 0}
    matched = 0
    worst_status = "safe"
    for f in files:
        result = privacy_check(path=f.strip())
        if result["privacy_status"] == "blocked":
            worst_status = "blocked"
            matched += 1
        elif result["privacy_status"] == "needs_review" and worst_status != "blocked":
            worst_status = "needs_review"
            matched += 1
    return {"privacy_status": worst_status, "matched_found": matched}


# ═══════════════════════════════════════════════════════════════
# Core engine
# ═══════════════════════════════════════════════════════════════

def evaluate(
    task: str,
    stage: str = "pre-task",
    cloud_ok: bool = False,
    budget: float | None = None,
    model: str = "",
    files: str = "",
    input_summary: str = "",
) -> dict:
    """Evaluate task through soft gate and return advisory result.

    Composes router_explain → privacy_gate → (cost context if pre-cloud).
    Always advisory-only. Never blocks.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    if stage not in VALID_STAGES:
        stage = "pre-task"

    # ── Router ──
    route = _engine.analyze(task)
    task_type = route.task_type
    risk = route.risk_level

    # ── Privacy on task text ──
    task_privacy = privacy_check(text=task)
    task_privacy_status = task_privacy["privacy_status"]

    # ── Privacy on file paths ──
    file_list = [f.strip() for f in files.split(",") if f.strip()] if files else []
    file_privacy = _check_file_paths(file_list)
    file_privacy_status = file_privacy["privacy_status"]
    files_matched = file_privacy["matched_found"]

    # ── Privacy on input summary ──
    input_privacy_status = "safe"
    if input_summary:
        ip = privacy_check(text=input_summary)
        input_privacy_status = ip["privacy_status"]

    # ── Combined privacy (worst of all) ──
    privacy_severity_order = {"safe": 0, "needs_review": 1, "blocked": 2}
    combined_privacy = "safe"
    for s in [task_privacy_status, file_privacy_status, input_privacy_status]:
        if privacy_severity_order.get(s, 0) > privacy_severity_order.get(combined_privacy, 0):
            combined_privacy = s

    # ── Severity & decision ──
    base_severity = _severity_from_risk(risk, task_type)
    privacy_sev = _severity_from_privacy(combined_privacy)
    sev_order = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
    severity = privacy_sev if sev_order.get(privacy_sev, 0) > sev_order.get(base_severity, 0) else base_severity
    decision = _decision_from_severity(severity, combined_privacy)

    # ── Unknown task → defer (unless privacy blocked) ──
    if task_type == "unknown" and combined_privacy != "blocked":
        decision = "defer"
        severity = "yellow" if combined_privacy == "safe" else "orange"

    # ── Route ──
    recommended_route = _recommended_route(combined_privacy, risk)

    # ── Budget context (lightweight) ──
    budget_status = "not_applicable"
    if stage == "pre-cloud":
        if budget is None:
            budget_status = "missing_budget"
        else:
            budget_status = "within_budget"  # full check left to dry_run

    # ── Cloud allowed ──
    cloud_allowed = combined_privacy != "blocked" and cloud_ok

    # ── Reason ──
    reasons = []
    if combined_privacy == "blocked":
        reasons.append(f"privacy: blocked ({task_privacy_status}/{file_privacy_status}/{input_privacy_status})")
    elif combined_privacy == "needs_review":
        reasons.append(f"privacy: needs_review")
    if risk in ("high", "critical"):
        reasons.append(f"risk: {risk}")
    if task_type == "unknown":
        reasons.append("task: unclassified")
    if not reasons:
        reasons.append(f"risk={risk}, privacy={combined_privacy}")

    return {
        "decision": decision,
        "severity": severity,
        "stage": stage,
        "task": task[:120],
        "task_type": task_type,
        "risk_level": risk,
        "privacy_status": combined_privacy,
        "privacy_detail": {
            "task_text": task_privacy_status,
            "file_paths": file_privacy_status,
            "input_summary": input_privacy_status,
        },
        "budget_status": budget_status,
        "recommended_route": recommended_route,
        "cloud_allowed": cloud_allowed,
        "files_checked": len(file_list),
        "files_matched": files_matched,
        "manual_confirm_recommended": decision == "manual_confirm_recommended",
        "hard_block_recommended": False,
        "advisory_only": True,
        "would_block": False,
        "reason": "; ".join(reasons),
        "next_required_action": _next_action(decision, stage),
        "generated_at": timestamp,
    }


def _next_action(decision: str, stage: str) -> str:
    if decision == "cloud_blocked":
        return "Use local models only. Do not send task or files to any cloud API."
    if decision == "manual_confirm_recommended":
        return "Human review recommended before proceeding. Consider local-first approach."
    if decision == "defer":
        return "Provide more specific task description before proceeding."
    if decision == "warn":
        return "Proceed with awareness. Cloud escalation may need review."
    return "Proceed."


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Claude Code Soft Gate — advisory governance check"
    )
    parser.add_argument("--stage", default="pre-task",
                        choices=["pre-task", "pre-commit", "pre-cloud"],
                        help="Gate stage (default: pre-task)")
    parser.add_argument("--task", required=True,
                        help="Task description")
    parser.add_argument("--cloud-ok", action="store_true",
                        help="Cloud escalation permitted")
    parser.add_argument("--budget", type=float, default=None,
                        help="Budget limit in CNY (for pre-cloud)")
    parser.add_argument("--model", default="",
                        help="Cloud model (for pre-cloud)")
    parser.add_argument("--files", default="",
                        help="Comma-separated file paths (no content read)")
    parser.add_argument("--input-summary", default="",
                        help="Brief summary of input content")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    result = evaluate(
        task=args.task,
        stage=args.stage,
        cloud_ok=args.cloud_ok,
        budget=args.budget,
        model=args.model,
        files=args.files,
        input_summary=args.input_summary,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Soft Gate [{result['stage']}]: {result['decision']} ({result['severity']})")
        print(f"  task:     {result['task']}")
        print(f"  type:     {result['task_type']} / {result['risk_level']}")
        print(f"  privacy:  {result['privacy_status']}")
        print(f"  route:    {result['recommended_route']}")
        print(f"  cloud:    {result['cloud_allowed']}")
        print(f"  would-block: {result['would_block']}")
        print(f"  reason:   {result['reason']}")
        print(f"  next:     {result['next_required_action']}")

    sys.exit(0)


if __name__ == "__main__":
    main()
