#!/usr/bin/env python3
"""Local Workflow Planner — heuristic workflow recommendation for local dev tasks.

Read-only.  Advisory-only.  No LLM calls.  No file modification.
Classifies a change by task description + file listing into one of four
workflow types and outputs a recommended sequence of existing tool calls.

Usage:
    git ls-files | py -3 tools/local_workflow_plan.py --stdin
    git diff --name-only | py -3 tools/local_workflow_plan.py --stdin \\
        --task "Fix router eligibility bug"
    py -3 tools/local_workflow_plan.py --task "Release v0.13.0 checkpoint" \\
        --stdin < file_list.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VERSION = "0.1.0"

HIGH_RISK_PATH_PATTERNS = (
    "hooks",
    "gate",
    "router",
    "local_llm_mcp_server",
    "local_llm_debate",
    "local_llm_worker",
    "local_llm_profiles",
    "local_llm_tasks",
    "call_ledger",
    "mcp_auto_worker",
    "preclassifier",
    "classify_failure",
)

HIGH_RISK_CONTENT_KEYWORDS = (
    r"\beval\b", r"\bexec\b", r"\bsubprocess\b",
    r"\bauth\b", r"\btoken\b", r"\bsecret\b", r"\bcrypto\b",
    r"\.env", r"credentials", r"api_key",
)

DOCS_PATH_PATTERNS = (
    "docs/", "README", "CHANGELOG", "RELEASE_NOTES",
    "PROJECT_STATUS", "CLAUDE.md", "AGENTS.md", "*.md",
)

RELEASE_TASK_KEYWORDS = (
    "release", "checkpoint", "version", "changelog",
    "tag", "baseline", "v0.", "bump version",
)


def _find_router() -> str:
    return "py -3 tools/local_llm_router.py"


def _find_debate() -> str:
    return "py -3 tools/local_llm_debate.py"


def _find_ledger_cli() -> str:
    return "py -3 tools/call_ledger_cli.py"


def _format_command(tool: str, args: str, stdin: str | None = None) -> str:
    parts = [tool]
    if args:
        parts.append(args)
    if stdin:
        return f"{stdin} | {' '.join(parts)}"
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Heuristic classifiers
# ---------------------------------------------------------------------------

def _is_high_risk_path(path: str) -> bool:
    p = path.lower()
    for pattern in HIGH_RISK_PATH_PATTERNS:
        if pattern in p:
            return True
    return False


def _is_docs_path(path: str) -> bool:
    p = path.lower()
    if p.startswith("docs/"):
        return True
    basename = Path(p).name.lower()
    return any(
        basename == d.lower()
        for d in ("readme.md", "readme.txt", "readme.rst", "readme",
                   "changelog.md", "release_notes.md", "project_status.md",
                   "claude.md", "agents.md", "license", "license.md",
                   "codex.md")
    ) or p.lower() in ("readme.md", "changelog.md", "release_notes.md",
                       "project_status.md", "claude.md", "agents.md")


def classify_workflow_type(
    files: list[str],
    task_desc: str = "",
    diff_text: str = "",
) -> str:
    """Return one of: small-code-change, docs-only-change,
    high-risk-runtime-change, release-local-checkpoint, unknown."""
    task_lower = task_desc.lower()
    has_release_kw = any(kw in task_lower for kw in RELEASE_TASK_KEYWORDS)

    if not files and not task_desc:
        return "unknown"

    if files:
        all_docs = all(_is_docs_path(f) for f in files)
    else:
        all_docs = False

    if files:
        any_high_risk = any(_is_high_risk_path(f) for f in files)
    else:
        any_high_risk = False

    # Task-level release indication overrides file classification
    if has_release_kw and not any_high_risk:
        return "release-local-checkpoint"

    if any_high_risk:
        return "high-risk-runtime-change"

    if all_docs and files:
        return "docs-only-change"

    if files and not all_docs:
        return "small-code-change"

    return "unknown"


def classify_risk_level(workflow_type: str) -> str:
    mapping = {
        "docs-only-change": "low",
        "small-code-change": "medium",
        "high-risk-runtime-change": "high",
        "release-local-checkpoint": "medium",
        "unknown": "medium",
    }
    return mapping.get(workflow_type, "medium")


def classify_debate_required(workflow_type: str, files: list[str]) -> tuple[bool, str]:
    if workflow_type == "docs-only-change":
        return False, "docs-only changes do not require debate"
    if workflow_type == "high-risk-runtime-change":
        high_risk = [f for f in files if _is_high_risk_path(f)]
        return True, f"high-risk paths detected: {', '.join(high_risk[:3])}"
    if workflow_type in ("small-code-change", "release-local-checkpoint"):
        # Check if any file still triggers debate policy
        if files:
            any_hr = any(_is_high_risk_path(f) for f in files)
            if any_hr:
                high_risk = [f for f in files if _is_high_risk_path(f)]
                return True, f"policy-triggering paths: {', '.join(high_risk[:3])}"
        return False, "no debate policy trigger detected"
    return False, "unable to determine"


# ---------------------------------------------------------------------------
# Work order template generator
# ---------------------------------------------------------------------------

def _build_work_order_template(
    workflow_type: str,
    risk_level: str,
    debate_required: bool,
    debate_reason: str,
    files: list[str],
    task_desc: str,
) -> dict:
    """Build a U-1 Controller Delegation Contract-aligned work order template.

    Pure heuristic — no LLM calls.  Advisory-only.
    The controller (big model) uses this template to delegate read-only heavy
    work to local models before editing.
    """
    allowed_tools: list[str] = ["local_workflow_plan"]
    stop_conditions = ["ok=false", "timeout", "high_uncertainty", "safety_boundary"]
    local_steps: list[dict] = [
        {
            "step_id": "orient",
            "tool": "local_workflow_plan",
            "reason": "classify workflow type and risk level",
        },
    ]

    # --- Determine review level and debate policy ---
    if workflow_type == "docs-only-change":
        review_level = "commit_gate"
        debate_policy = "skip"
        allowed_tools.extend([
            "draft-commit-message",
        ])
        local_steps.append({
            "step_id": "review",
            "tool": "local_review_diff",
            "reason": "pre-commit gate review",
        })
    elif workflow_type == "small-code-change":
        review_level = "commit_gate"
        debate_policy = "optional"
        allowed_tools.extend([
            "find-related-files",
            "local_repo_map",
            "local_summarize_file",
            "local_generate_test_plan",
            "local_review_diff",
            "draft-commit-message",
        ])
        local_steps.extend([
            {
                "step_id": "discover",
                "tool": "find-related-files",
                "reason": "identify related source/test/config files",
            },
            {
                "step_id": "understand",
                "tool": "local_summarize_file",
                "reason": "summarize key files > 200 lines before editing",
            },
            {
                "step_id": "review",
                "tool": "local_review_diff",
                "reason": "commit gate review after edits",
            },
        ])
    elif workflow_type == "high-risk-runtime-change":
        review_level = "debate_fast" if debate_required else "commit_gate"
        debate_policy = "required" if debate_required else "optional"
        allowed_tools.extend([
            "find-related-files",
            "local_repo_map",
            "local_summarize_file",
            "local_generate_test_plan",
            "local_review_diff",
            "draft-commit-message",
        ])
        if debate_required:
            allowed_tools.append("local_debate_review_diff")
        local_steps.extend([
            {
                "step_id": "discover",
                "tool": "find-related-files",
                "reason": "identify all affected files and subsystems",
            },
            {
                "step_id": "understand",
                "tool": "local_summarize_file",
                "reason": "summarize key files > 200 lines before editing",
            },
            {
                "step_id": "test_plan",
                "tool": "local_generate_test_plan",
                "reason": "generate test plan for high-risk change",
            },
            {
                "step_id": "review",
                "tool": "local_review_diff",
                "reason": "commit gate review after edits",
            },
        ])
        if debate_required:
            local_steps.append({
                "step_id": "debate",
                "tool": "local_debate_review_diff",
                "reason": f"multi-model debate review — {debate_reason}",
            })
    elif workflow_type == "release-local-checkpoint":
        review_level = "debate_fast"
        debate_policy = "optional"
        allowed_tools.extend([
            "find-related-files",
            "local_repo_map",
            "local_review_diff",
            "draft-commit-message",
            "draft-pr-summary",
            "draft-changelog-entry",
        ])
        local_steps.extend([
            {
                "step_id": "discover",
                "tool": "find-related-files",
                "reason": "identify all changes since baseline",
            },
            {
                "step_id": "review",
                "tool": "local_review_diff",
                "reason": "commit gate review after edits",
            },
            {
                "step_id": "batch",
                "tool": "draft-changelog-entry",
                "reason": "generate changelog entry from diff range",
            },
        ])
        if any(_is_high_risk_path(f) for f in files):
            allowed_tools.append("local_debate_review_diff")
            debate_policy = "required"
            local_steps.append({
                "step_id": "debate",
                "tool": "local_debate_review_diff",
                "reason": "high-risk paths detected in release — debate required",
            })
    else:  # unknown
        review_level = "commit_gate"
        debate_policy = "optional"
        allowed_tools.extend([
            "find-related-files",
            "local_repo_map",
            "local_summarize_file",
            "local_review_diff",
            "draft-commit-message",
        ])
        local_steps.extend([
            {
                "step_id": "discover",
                "tool": "find-related-files",
                "reason": "identify affected files — workflow type unknown",
            },
            {
                "step_id": "review",
                "tool": "local_review_diff",
                "reason": "commit gate review after edits",
            },
        ])

    return {
        "schema_version": 1,
        "task_description": task_desc,
        "controller_objective": (
            "Big model plans and delegates read-only heavy work to local models. "
            "Local models execute bounded read-only tasks. "
            "Big model audits, integrates, edits, and finalizes."
        ),
        "risk_level": risk_level,
        "workflow_type": workflow_type,
        "local_steps_requested": local_steps,
        "target_files": list(files),
        "search_scope": ".",
        "allowed_tools": allowed_tools,
        "forbidden_actions": ["edit", "stage", "commit", "push", "tag", "release"],
        "budget_limits": {
            "max_files_to_summarize": 5,
            "max_runtime_seconds": 300,
            "max_model_calls": 10,
        },
        "expected_outputs": [
            "related_files",
            "summaries",
            "test_recommendations",
            "risk_notes",
            "suggested_next_calls",
        ],
        "review_level": review_level,
        "debate_policy": debate_policy,
        "debate_reason": debate_reason,
        "stop_conditions": stop_conditions,
        "controller_notes": (
            "Big model remains controller — local model output is advisory only. "
            "Controller must verify, decide which files to edit, apply edits, "
            "run tests, inspect git diff, and finalize the commit message. "
            "Local models never edit, stage, commit, or push."
        ),
        "advisory_only": True,
    }


# ---------------------------------------------------------------------------
# Workflow planner
# ---------------------------------------------------------------------------

def build_plan(
    files: list[str],
    task_desc: str = "",
    diff_text: str = "",
) -> dict:
    workflow_type = classify_workflow_type(files, task_desc, diff_text)
    risk = classify_risk_level(workflow_type)
    debate_required, debate_reason = classify_debate_required(workflow_type, files)

    router = _find_router()
    debate_bin = _find_debate()
    ledger_cli = _find_ledger_cli()

    plan: dict = {
        "workflow_type": workflow_type,
        "risk_level": risk,
        "debate_required": debate_required,
        "debate_reason": debate_reason,
        "phases": {},
        "work_order_template": _build_work_order_template(
            workflow_type, risk, debate_required, debate_reason,
            files, task_desc,
        ),
        "estimated_cost_seconds": 0,
        "advisory_only": True,
        "controller_must_decide": [
            "which files to edit",
            "whether to accept or reject advisory output",
            "final commit message text",
            "final PR summary / changelog text",
            "whether to run debate even when recommended NO",
        ],
    }

    # --- Phase: Orient ---
    orient: dict = {"description": "", "commands": []}

    if workflow_type in ("small-code-change", "high-risk-runtime-change",
                         "release-local-checkpoint"):
        orient["description"] = "Identify related files, tests, subsystems, and inspection order"
        orient["commands"].append(
            _format_command(router, "find-related-files --stdin",
                            "git ls-files")
        )
    elif workflow_type == "docs-only-change":
        orient["description"] = "Confirm scope is docs-only"
        orient["commands"].append(
            _format_command(router, "find-related-files --stdin",
                            "git ls-files")
        )

    plan["phases"]["orient"] = orient

    # --- Phase: Understand ---
    understand: dict = {"description": "", "commands": []}
    if workflow_type in ("high-risk-runtime-change", "small-code-change"):
        understand["description"] = (
            "Summarize key files > 200 lines before editing"
        )
        understand["commands"].append(
            "# For each file > 200 lines that you plan to edit:"
        )
        understand["commands"].append(
            _format_command(router, "summarize-file <path/to/file>", None)
        )
        understand["commands"].append(
            "# Or use the MCP tool: /local-summarize-file <path>"
        )
    plan["phases"]["understand"] = understand

    # --- Phase: Plan ---
    planner: dict = {"description": "", "commands": []}
    if workflow_type == "high-risk-runtime-change":
        planner["description"] = (
            "Generate test plan before implementing new API/schema/parser/UI"
        )
        planner["commands"].append(
            _format_command(router, "generate-test-plan <source_file>", None)
        )
        planner["commands"].append(
            "# Or MCP: local_generate_test_plan with use_repo_map=true for context"
        )
    elif workflow_type == "small-code-change":
        planner["description"] = "Optional test planning"
        planner["commands"].append(
            "# If adding new API/schema/parser/UI, run:"
        )
        planner["commands"].append(
            _format_command(router, "generate-test-plan <source_file>", None)
        )
    plan["phases"]["plan"] = planner

    # --- Phase: Implement ---
    implement: dict = {"description": "", "commands": []}
    implement["description"] = "Controller writes code and tests"
    implement["commands"].append("# Controller implements changes manually")
    implement["commands"].append("# Controller runs tests: py -3 -m pytest tests/ -q")
    plan["phases"]["implement"] = implement

    # --- Phase: Review ---
    review: dict = {"description": "", "commands": []}
    review["description"] = "Pre-commit diff review"
    if workflow_type == "docs-only-change":
        review["commands"].append(
            _format_command(router, "review-diff --stdin",
                            "git diff --cached")
        )
        review["commands"].append(
            "# Or MCP: local_review_diff with commit_gate=true"
        )
    elif workflow_type in ("small-code-change", "release-local-checkpoint"):
        review["commands"].append(
            _format_command(router, "review-diff --stdin",
                            "git diff --cached")
        )
        review["commands"].append(
            "# Or MCP: local_review_diff with commit_gate=true"
        )
    elif workflow_type == "high-risk-runtime-change":
        review["commands"].append("## Step 1: Single-model review")
        review["commands"].append(
            _format_command(router, "review-diff --stdin",
                            "git diff --cached")
        )
        if debate_required:
            review["commands"].append("")
            review["commands"].append("## Step 2: Multi-model debate review")
            review["commands"].append(
                _format_command(debate_bin, "review-diff --stdin",
                                "git diff --cached")
            )
            review["commands"].append(
                "# Or MCP: local_debate_review_diff (fast mode minimum,"
            )
            review["commands"].append(
                "#   full 3-round for architecture/DB/schema/release)"
            )
    plan["phases"]["review"] = review

    # --- Phase: Commit ---
    commit: dict = {"description": "", "commands": []}
    commit["description"] = "Draft commit message and finalize"
    commit["commands"].append(
        _format_command(router, "draft-commit-message --stdin",
                        "git diff --cached")
    )
    commit["commands"].append("# Controller reviews draft → edits → commits")
    plan["phases"]["commit"] = commit

    # --- Phase: Batch / Release ---
    batch: dict = {"description": "", "commands": []}
    if workflow_type in ("release-local-checkpoint", "high-risk-runtime-change"):
        batch["description"] = "Batch summary and changelog"
        batch["commands"].append(
            _format_command(router, "draft-pr-summary --stdin",
                            "git diff main..HEAD")
        )
        batch["commands"].append(
            _format_command(router, "draft-changelog-entry --stdin",
                            "git diff main..HEAD")
        )
        batch["commands"].append("")
        batch["commands"].append("## Efficiency check")
        batch["commands"].append(f"{ledger_cli} by-task")
    elif workflow_type == "small-code-change":
        batch["description"] = "Optional: batch summary for multi-commit work"
        batch["commands"].append("# If this is part of a multi-commit batch:")
        batch["commands"].append(
            _format_command(router, "draft-pr-summary --stdin",
                            "git diff main..HEAD")
        )
    plan["phases"]["batch_release"] = batch

    # Cost estimate
    cost = 0
    if workflow_type == "docs-only-change":
        cost = 30  # review ~10s + advisor ~20s
    elif workflow_type == "small-code-change":
        cost = 60  # orient ~15s + review ~30s + advisor ~15s
    elif workflow_type == "high-risk-runtime-change":
        cost = 240  # orient ~15s + understand ~30s + review ~30s + debate ~150s + advisors ~15s
    elif workflow_type == "release-local-checkpoint":
        cost = 120  # orient ~15s + review ~30s + advisors ~60s + ledger ~15s
    plan["estimated_cost_seconds"] = cost

    return plan


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

_WORKFLOW_LABELS = {
    "small-code-change": "Small Code Change (Scenario A)",
    "docs-only-change": "Docs-Only Change (Scenario B)",
    "high-risk-runtime-change": "High-Risk Runtime Change (Scenario C)",
    "release-local-checkpoint": "Release / Local Checkpoint (Scenario D)",
    "unknown": "Unknown — insufficient input",
}

_RISK_LABELS = {
    "low": "LOW — docs only, no runtime impact",
    "medium": "MEDIUM — code logic changed, review required",
    "high": "HIGH — hooks/gate/router/schema/security touched, debate required",
}


def _print_plan_text(plan: dict, files: list[str], task_desc: str) -> None:
    wf = plan["workflow_type"]
    print("=" * 64)
    print("  LOCAL WORKFLOW PLAN")
    print("=" * 64)
    print()
    print(f"  Workflow:    {_WORKFLOW_LABELS.get(wf, wf)}")
    print(f"  Risk:        {_RISK_LABELS.get(plan['risk_level'], plan['risk_level'])}")
    print(f"  Debate:      {'YES — ' + plan['debate_reason'] if plan['debate_required'] else 'NO — ' + plan['debate_reason']}")
    if task_desc:
        print(f"  Task:        {task_desc[:80]}")
    if files:
        preview = ", ".join(files[:5])
        if len(files) > 5:
            preview += f" (+{len(files) - 5} more)"
        print(f"  Files:       {preview}")
    print(f"  Est. cost:   ~{plan['estimated_cost_seconds']}s")
    print()

    for phase_key in ("orient", "understand", "plan", "implement",
                      "review", "commit", "batch_release"):
        phase = plan["phases"].get(phase_key) or {}
        desc = phase.get("description", "")
        cmds = phase.get("commands", [])
        if not desc and not cmds:
            continue
        labels = {
            "orient": "PHASE 1: Orient",
            "understand": "PHASE 2: Understand",
            "plan": "PHASE 3: Plan",
            "implement": "PHASE 4: Implement",
            "review": "PHASE 5: Review",
            "commit": "PHASE 6: Commit",
            "batch_release": "PHASE 7: Batch / Release",
        }
        label = labels.get(phase_key, phase_key.upper())
        print(f"  {label}")
        print(f"  {'-' * 58}")
        if desc:
            print(f"  {desc}")
        if cmds:
            print()
            for cmd in cmds:
                if cmd.startswith("#"):
                    print(f"  {cmd}")
                else:
                    print(f"    {cmd}")
        print()

    print("-" * 64)
    print("  Controller must decide:")
    for item in plan["controller_must_decide"]:
        print(f"    - {item}")
    print()
    print("  Advisory only — this plan does not run any commands.")
    print("  All tool output goes to .local_llm_out/.")
    print("  Controller reviews, edits, and decides.")
    print("=" * 64)


def _print_plan_json(plan: dict, files: list[str], task_desc: str) -> None:
    out = dict(plan)
    out["input_files_count"] = len(files)
    out["input_task_description"] = task_desc
    out["input_files_preview"] = files[:10]
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Input gathering
# ---------------------------------------------------------------------------

def gather_input(args: argparse.Namespace) -> tuple[str, list[str]]:
    task_desc = args.task or ""
    files: list[str] = []

    if args.stdin:
        raw = sys.stdin.buffer.read()
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                files.append(stripped)
    elif args.files:
        for f in args.files:
            p = Path(f)
            if p.exists():
                if p.is_file():
                    files.append(str(p))
            else:
                files.append(str(p))

    return task_desc, files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local_workflow_plan",
        description="Heuristic workflow planner for local dev tasks. "
                    "Advisory-only — no LLM calls, no file modification.",
    )
    p.add_argument("--task", default=None,
                   help="task description for context-aware classification")
    p.add_argument("--stdin", action="store_true", default=False,
                   help="read file listing from stdin (one path per line)")
    p.add_argument("--files", nargs="*", default=None,
                   help="specific files to evaluate (alternative to --stdin)")
    p.add_argument("--format", choices=("text", "json"), default="text",
                   help="output format (default: text)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.stdin and not args.files and not args.task:
        parser.print_help()
        print("\nProvide at least --task, --stdin, or --files.")
        return 2

    task_desc, files = gather_input(args)
    plan = build_plan(files, task_desc)

    if args.format == "json":
        _print_plan_json(plan, files, task_desc)
    else:
        _print_plan_text(plan, files, task_desc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
