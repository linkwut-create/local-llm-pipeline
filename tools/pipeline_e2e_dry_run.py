#!/usr/bin/env python3
"""Pipeline End-to-End Dry Run — full pipeline in one command with mocks.

Usage::

    py -3 tools/pipeline_e2e_dry_run.py <task_description>
    py -3 tools/pipeline_e2e_dry_run.py "fix failing tests" --route local_only
    py -3 tools/pipeline_e2e_dry_run.py "add new MCP tool" --route flash_subagent --risk high
    py -3 tools/pipeline_e2e_dry_run.py "security audit" --route pro_decision
    py -3 tools/pipeline_e2e_dry_run.py --route blocked "delete everything"
    py -3 tools/pipeline_e2e_dry_run.py --all-routes  # run one of each

Phases executed (mock components marked with *):
  1. Create task session (real: artifact_store + agentdb)
  2. *Mock Plan Generator → plan.json
  3. Build evidence pack (real: local_route_committee)
  4. *Mock Qwen + Gemma → route.json (deterministic merge)
  5. *Execute per route: local/Flash/Pro worker → artifacts/
  6. *Mock test run → test_results.json
  7. Build adjudication pack (real: pipeline_adjudicator)
  8. *Mock Pro decision → decisions/pro_decision_001.json
  9. Record to AgentDB (real: agentdb.py)
  10. Finalize task session
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure tools/ is on sys.path
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

ALL_ROUTES = [
    "local_only", "flash_direct", "flash_subagent",
    "pro_decision", "pro_execute_allowed", "blocked", "ask_user", "direct",
]


def parse_args():
    p = argparse.ArgumentParser(
        description="Pipeline E2E Dry Run — full pipeline with mocks",
    )
    p.add_argument("task", nargs="?", default="dry-run test task",
                   help="Task description (default: generic test task)")
    p.add_argument("--route", choices=ALL_ROUTES, default="local_only",
                   help="Route for this dry run (default: local_only)")
    p.add_argument("--risk", choices=["low", "medium", "high", "critical"],
                   default="medium", help="Risk level (default: medium)")
    p.add_argument("--privacy", choices=["safe", "needs_review", "blocked"],
                   default="safe", help="Privacy status (default: safe)")
    p.add_argument("--all-routes", action="store_true",
                   help="Run one dry run for every route type")
    p.add_argument("--task-id", default="",
                   help="Task ID (auto-generated if omitted)")
    p.add_argument("--output-dir", default=".local_llm_out",
                   help="Output directory (default: .local_llm_out)")
    p.add_argument("--json", action="store_true",
                   help="Output machine-readable JSON")
    return p.parse_args()


# ═══════════════════════════════════════════════════════════════
# Step 1: Create task session
# ═══════════════════════════════════════════════════════════════

def step_create_task(task_description: str, task_id: str,
                     output_dir: str) -> dict:
    """Create task session directory and initial session.json."""
    from pipeline_artifact_store import task_dir, save_artifact

    tid = task_id or str(uuid.uuid4())
    td = task_dir(tid)

    # Create directory structure
    for sub in ("committee", "artifacts", "decisions"):
        (td / sub).mkdir(parents=True, exist_ok=True)

    session = {
        "task_id": tid,
        "status": "active",
        "phase": "planning",
        "user_task": task_description,
        "created_at": _now(),
        "updated_at": _now(),
        "project_root": str(Path.cwd()),
    }
    (td / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write user_task.md
    (td / "user_task.md").write_text(
        f"# Task\n\n{task_description}\n", encoding="utf-8")

    return {"ok": True, "task_id": tid, "task_dir": str(td)}


# ═══════════════════════════════════════════════════════════════
# Step 2: Mock plan
# ═══════════════════════════════════════════════════════════════

def step_mock_plan(task_description: str, task_id: str,
                   risk_level: str) -> dict:
    """Generate mock plan.json."""
    from pipeline_mocks import generate_mock_plan, MockPlanConfig
    from pipeline_artifact_store import task_dir, save_artifact

    cfg = MockPlanConfig(risk_level=risk_level)
    plan = generate_mock_plan(task_description, task_id=task_id, config=cfg)

    td = task_dir(task_id)
    (td / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    save_artifact(task_id, "plan.json",
                  json.dumps(plan, ensure_ascii=False, indent=2),
                  artifact_type="plan", tool_name="mock_plan_generator",
                  creator="mock_pro")

    return {"ok": True, "plan": plan}


# ═══════════════════════════════════════════════════════════════
# Step 3: Evidence pack (real)
# ═══════════════════════════════════════════════════════════════

def step_evidence_pack(task_id: str) -> dict:
    """Build real evidence pack using local_route_committee."""
    from local_route_committee import build_evidence_pack, format_evidence_pack
    from pipeline_artifact_store import task_dir, save_artifact

    pack = build_evidence_pack()
    formatted = format_evidence_pack(pack)

    td = task_dir(task_id)
    comm_dir = td / "committee"
    (comm_dir / "evidence_pack.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    save_artifact(task_id, "evidence_pack.json",
                  json.dumps(pack, ensure_ascii=False, indent=2),
                  artifact_type="evidence_pack",
                  tool_name="local_route_committee", creator="controller")

    return {"ok": True, "pack": pack, "formatted": formatted}


# ═══════════════════════════════════════════════════════════════
# Step 4: Mock route committee
# ═══════════════════════════════════════════════════════════════

def step_mock_route(task_id: str, plan: dict, route: str,
                    risk_level: str, privacy_status: str) -> dict:
    """Generate mock route.json via Qwen + Gemma → merge."""
    from pipeline_mocks import (
        MockRouteCommitteeConfig, generate_mock_route_decision,
        generate_mock_qwen_judgement, generate_mock_gemma_judgement,
    )
    from pipeline_artifact_store import task_dir, save_artifact

    cfg = MockRouteCommitteeConfig(
        qwen_route=route, gemma_route=route,
        agreement=True, risk_level=risk_level,
        privacy_status=privacy_status,
    )
    decision = generate_mock_route_decision(plan, config=cfg)

    td = task_dir(task_id)
    comm_dir = td / "committee"

    # Save individual judgements
    (comm_dir / "qwen_initial.json").write_text(
        json.dumps(decision["qwen_judgement"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    (comm_dir / "gemma_initial.json").write_text(
        json.dumps(decision["gemma_judgement"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    (comm_dir / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save route.json at task root
    (td / "route.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    save_artifact(task_id, "route.json",
                  json.dumps(decision, ensure_ascii=False, indent=2),
                  artifact_type="route", tool_name="mock_route_committee",
                  creator="mock_committee")

    return {"ok": True, "route": decision}


# ═══════════════════════════════════════════════════════════════
# Step 5: Execute per route
# ═══════════════════════════════════════════════════════════════

def step_execute(task_id: str, route: dict) -> dict:
    """Execute mock workers based on the recommended route."""
    from pipeline_mocks import (
        generate_mock_local_artifact, generate_mock_flash_artifact,
    )
    from pipeline_artifact_store import save_artifact

    route_type = route.get("recommended_route", "blocked")
    required = route.get("required_artifacts", [])
    results = []

    # Map route to execution strategy
    if route_type == "blocked":
        results.append({"step": "execute", "status": "blocked",
                        "reason": "Route is blocked — no execution allowed."})
        return {"ok": True, "route_type": route_type, "results": results}

    if route_type == "ask_user":
        results.append({"step": "execute", "status": "paused",
                        "reason": "Route is ask_user — waiting for user input."})
        return {"ok": True, "route_type": route_type, "results": results}

    # Local execution: generate summary + review + repo_map if requested
    if route_type in ("local_only", "local_summary"):
        for artifact_name in ("file_summary", "diff_review"):
            try:
                fname, content, atype = generate_mock_local_artifact(
                    task_id, artifact_name)
                save_artifact(task_id, fname, content, artifact_type=atype,
                              tool_name="mock_local_worker", creator="mock_qwen")
                results.append({"artifact": artifact_name, "filename": fname,
                                "type": atype, "status": "saved"})
            except ValueError as e:
                results.append({"artifact": artifact_name, "error": str(e)})

    # Flash execution: generate patch candidate + test results
    if route_type in ("flash_direct", "flash_subagent"):
        for artifact_name in ("patch_candidate", "test_results", "flash_review"):
            try:
                fname, content, atype = generate_mock_flash_artifact(
                    task_id, artifact_name)
                save_artifact(task_id, fname, content, artifact_type=atype,
                              tool_name="mock_flash_worker", creator="mock_flash")
                results.append({"artifact": artifact_name, "filename": fname,
                                "type": atype, "status": "saved"})
            except ValueError as e:
                results.append({"artifact": artifact_name, "error": str(e)})

    # Pro execution: only adjudication — no direct file modification
    if route_type in ("pro_decision", "pro_execute_allowed"):
        results.append({"step": "execute", "status": "delegated_to_pro",
                        "reason": "Pro reads evidence and adjudicates in step 7."})

    # Direct: allow full execution (mock)
    if route_type == "direct":
        for artifact_name in ("file_summary", "diff_review", "test_plan"):
            try:
                fname, content, atype = generate_mock_local_artifact(
                    task_id, artifact_name)
                save_artifact(task_id, fname, content, artifact_type=atype,
                              tool_name="mock_local_worker", creator="mock_qwen")
                results.append({"artifact": artifact_name, "filename": fname,
                                "type": atype, "status": "saved"})
            except ValueError as e:
                results.append({"artifact": artifact_name, "error": str(e)})

    return {"ok": True, "route_type": route_type, "results": results}


# ═══════════════════════════════════════════════════════════════
# Step 6: Mock test run
# ═══════════════════════════════════════════════════════════════

def step_mock_tests(task_id: str) -> dict:
    """Simulate a test run and save results as artifact."""
    from pipeline_mocks import run_mock_tests
    from pipeline_artifact_store import save_artifact

    test_result = run_mock_tests(task_id)
    save_artifact(task_id, "test_results.json",
                  json.dumps(test_result, ensure_ascii=False, indent=2),
                  artifact_type="test_run", tool_name="mock_test_runner",
                  creator="controller")
    return {"ok": True, "test_result": test_result}


# ═══════════════════════════════════════════════════════════════
# Step 7: Pro adjudication
# ═══════════════════════════════════════════════════════════════

def step_pro_adjudication(task_id: str, route: dict) -> dict:
    """Build adjudication pack (real) + mock Pro decision."""
    from pipeline_adjudicator import build_adjudication_pack, adjudicate
    from pipeline_mocks import generate_mock_pro_decision, MockProDecisionConfig

    route_type = route.get("recommended_route", "unknown")

    # Build real adjudication pack
    pack = build_adjudication_pack(task_id)

    # Map outcome to route type
    if route_type == "blocked":
        decision_outcome = "cancel"
        reason = "Route is blocked. Cannot proceed."
    elif route_type == "ask_user":
        decision_outcome = "ask_user"
        reason = "Route requires user confirmation."
    else:
        decision_outcome = "accept"
        reason = "Mock: all artifacts present and valid."

    cfg = MockProDecisionConfig(decision=decision_outcome, reason=reason)
    mock_decision = generate_mock_pro_decision(pack, config=cfg)

    # Record via real adjudicator
    result = adjudicate(task_id, mock_decision)

    return {"ok": result.get("ok", False), "pack": pack,
            "decision": mock_decision, "adjudicate_result": result}


# ═══════════════════════════════════════════════════════════════
# Step 8: AgentDB record
# ═══════════════════════════════════════════════════════════════

def step_agentdb_record(task_id: str, task_description: str,
                        route: dict, decision: dict) -> dict:
    """Record the task in AgentDB."""
    try:
        import agentdb as adb  # type: ignore
    except ImportError:
        return {"ok": False, "error": "agentdb module not importable"}

    route_type = route.get("recommended_route", "unknown")
    risk_level = route.get("risk_level", "medium")
    privacy = route.get("privacy_status", "safe")
    decision_type = decision.get("decision", "unknown")

    try:
        # Ensure database is initialized
        adb.init_db()

        # Insert task record
        conn = adb._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id, status, phase, user_task, route_type, risk_level,
                    privacy_status, created_at, updated_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, "completed", "adjudicated", task_description[:500],
                 route_type, risk_level, privacy,
                 _now(), _now(), _now()),
            )

            # Insert route record
            conn.execute(
                """INSERT OR REPLACE INTO routes
                   (task_id, route_type, risk_level, privacy_status, delegability,
                    agreement, escalated, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, route_type, risk_level, privacy,
                 route.get("delegability", "medium"),
                 int(route.get("agreement", True)),
                 int(route.get("escalated", False)),
                 _now()),
            )

            # Insert decision record
            conn.execute(
                """INSERT OR REPLACE INTO decisions
                   (task_id, decision, reason, created_at)
                   VALUES (?, ?, ?, ?)""",
                (task_id, decision_type,
                 decision.get("reason", "")[:500], _now()),
            )

            conn.commit()
        finally:
            conn.close()

        return {"ok": True, "task_id": task_id,
                "recorded": ["task", "route", "decision"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Step 9: Finalize task
# ═══════════════════════════════════════════════════════════════

def step_finalize(task_id: str) -> dict:
    """Update session.json to completed status."""
    from pipeline_artifact_store import task_dir

    td = task_dir(task_id)
    sf = td / "session.json"

    if sf.exists():
        session = json.loads(sf.read_text(encoding="utf-8"))
        session["status"] = "completed"
        session["phase"] = "adjudicated"
        session["updated_at"] = _now()
        session["completed_at"] = _now()
        sf.write_text(json.dumps(session, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    return {"ok": True, "task_id": task_id, "status": "completed"}


# ═══════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════

def run_dry_run(task_description: str, *, route: str = "local_only",
                risk_level: str = "medium", privacy_status: str = "safe",
                task_id: str = "", output_dir: str = ".local_llm_out",
                ) -> list[dict]:
    """Execute the full pipeline dry run and return step-by-step results.

    Returns a list of step result dicts, each with ``step``, ``ok``, and
    step-specific keys.  The caller can format the output for human or
    machine consumption.
    """
    steps: list[dict] = []

    # --- Step 1: Create task session ---
    s1 = step_create_task(task_description, task_id, output_dir)
    tid = s1["task_id"]
    steps.append({"step": 1, "name": "create_task", **s1})
    if not s1["ok"]:
        return steps

    # --- Step 2: Mock plan ---
    s2 = step_mock_plan(task_description, tid, risk_level)
    steps.append({"step": 2, "name": "mock_plan", **s2})

    # --- Step 3: Evidence pack (real) ---
    s3 = step_evidence_pack(tid)
    steps.append({"step": 3, "name": "evidence_pack", **s3})

    # --- Step 4: Mock route committee ---
    s4 = step_mock_route(tid, s2.get("plan", {}), route, risk_level, privacy_status)
    route_decision = s4.get("route", {})
    steps.append({"step": 4, "name": "mock_route", **s4})

    # --- Step 5: Execute per route ---
    s5 = step_execute(tid, route_decision)
    steps.append({"step": 5, "name": "execute", **s5})

    # --- Step 6: Mock test run ---
    s6 = step_mock_tests(tid)
    steps.append({"step": 6, "name": "mock_tests", **s6})

    # --- Step 7: Pro adjudication ---
    s7 = step_pro_adjudication(tid, route_decision)
    steps.append({"step": 7, "name": "pro_adjudication", **s7})

    # --- Step 8: AgentDB record ---
    s8 = step_agentdb_record(tid, task_description, route_decision,
                              s7.get("decision", {}))
    steps.append({"step": 8, "name": "agentdb_record", **s8})

    # --- Step 9: Finalize ---
    s9 = step_finalize(tid)
    steps.append({"step": 9, "name": "finalize", **s9})

    return steps


# ═══════════════════════════════════════════════════════════════
# Output formatting
# ═══════════════════════════════════════════════════════════════

def format_output(steps: list[dict], json_output: bool = False) -> str:
    """Format dry run results as human-readable text or JSON."""
    if json_output:
        return json.dumps(steps, ensure_ascii=False, indent=2, default=str)

    lines: list[str] = []
    task_id = ""
    for s in steps:
        if s.get("task_id"):
            task_id = s["task_id"]

    lines.append("=" * 60)
    lines.append(f"Pipeline E2E Dry Run — {task_id}")
    lines.append("=" * 60)

    status_icons = {True: "[OK]", False: "[FAIL]", None: "[--]"}
    for s in steps:
        icon = status_icons.get(s.get("ok"), "[--]")
        name = s.get("name", f"step_{s.get('step', '?')}")
        lines.append(f"\n{icon} Step {s['step']}: {name}")
        if not s.get("ok"):
            lines.append(f"   ERROR: {s.get('error', 'unknown error')}")
        elif name == "create_task":
            lines.append(f"   Task ID: {s.get('task_id', '?')}")
        elif name == "mock_plan":
            p = s.get("plan", {})
            lines.append(f"   Risk: {p.get('risk_level', '?')}")
            lines.append(f"   Files: {p.get('files_to_modify', [])}")
        elif name == "mock_route":
            r = s.get("route", {})
            lines.append(f"   Route: {r.get('recommended_route', '?')}")
            lines.append(f"   Agreement: {r.get('agreement', '?')}")
            lines.append(f"   Risk: {r.get('risk_level', '?')}")
        elif name == "execute":
            lines.append(f"   Route: {s.get('route_type', '?')}")
            for r in s.get("results", []):
                status = r.get("status", r.get("error", "?"))
                art = r.get("artifact", r.get("step", "?"))
                lines.append(f"     - {art}: {status}")
        elif name == "mock_tests":
            tr = s.get("test_result", {})
            lines.append(f"   Passed: {tr.get('passed', '?')}/{tr.get('total', '?')}")
        elif name == "pro_adjudication":
            d = s.get("decision", {})
            lines.append(f"   Decision: {d.get('decision', '?')}")
            lines.append(f"   Reason: {d.get('reason', '?')}")
        elif name == "agentdb_record":
            lines.append(f"   Recorded: {s.get('recorded', 'none')}")
        elif name == "finalize":
            lines.append(f"   Status: {s.get('status', '?')}")

    lines.append("\n" + "=" * 60)
    all_ok = all(s.get("ok", True) for s in steps)
    lines.append(f"Overall: {'PASS' if all_ok else 'FAIL'}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

def main():
    args = parse_args()

    if args.all_routes:
        results = {}
        for route in ALL_ROUTES:
            steps = run_dry_run(
                f"dry-run task: {route}",
                route=route,
                risk_level=args.risk,
                privacy_status=args.privacy,
            )
            results[route] = {
                "task_id": steps[0].get("task_id", ""),
                "ok": all(s.get("ok", True) for s in steps),
                "steps": len(steps),
            }
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'Route':<25} {'Task ID':<38} {'OK':<6} {'Steps'}")
            print("-" * 78)
            for route, r in results.items():
                print(f"{route:<25} {r['task_id']:<38} {r['ok']!s:<6} {r['steps']}")
            all_ok = all(r["ok"] for r in results.values())
            print(f"\nAll routes passed: {all_ok}")
        return 0 if all(r["ok"] for r in results.values()) else 1

    # Single dry run
    steps = run_dry_run(
        args.task,
        route=args.route,
        risk_level=args.risk,
        privacy_status=args.privacy,
        task_id=args.task_id,
        output_dir=args.output_dir,
    )

    print(format_output(steps, json_output=args.json))
    return 0 if all(s.get("ok", True) for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
