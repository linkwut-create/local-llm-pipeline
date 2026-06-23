"""Pipeline Pro Adjudicator — structured adjudication from artifact pack.

Pro reads a compressed evidence pack (NOT the full project) and outputs
a structured decision. Override to pro_execute_allowed requires explicit
reason and is logged.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Adjudication pack builder
# ═══════════════════════════════════════════════════════════════

def build_adjudication_pack(task_id: str) -> dict:
    """Build a compressed evidence pack for Pro adjudication.

    Reads from the task directory and artifact store to assemble a
    focused pack. Does NOT include the full project or full logs.
    """
    from pipeline_artifact_store import task_dir, artifacts_dir, list_artifacts

    td = task_dir(task_id)
    pack = {
        "task_id": task_id,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "user_task": "",
        "plan": None,
        "route": None,
        "artifacts_summary": {},
        "test_results": None,
        "cost_estimate": None,
        "committee": None,
    }

    # Session
    sf = td / "session.json"
    if sf.exists():
        try:
            s = json.loads(sf.read_text(encoding="utf-8"))
            pack["user_task"] = str(s.get("user_task", ""))[:1000]
            pack["status"] = s.get("status", "unknown")
            pack["phase"] = s.get("phase", "unknown")
        except Exception:
            pass

    # Plan
    pf = td / "plan.json"
    if pf.exists():
        try:
            pack["plan"] = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            pack["plan"] = "(unparseable)"

    # Route
    rf = td / "route.json"
    if rf.exists():
        try:
            route = json.loads(rf.read_text(encoding="utf-8"))
            pack["route"] = {
                "recommended_route": route.get("recommended_route"),
                "risk_level": route.get("risk_level"),
                "delegability": route.get("delegability"),
                "agreement": route.get("agreement"),
                "escalated": route.get("escalated"),
                "escalated_reason": route.get("escalated_reason", ""),
            }
        except Exception:
            pack["route"] = "(unparseable)"

    # Artifacts summary
    index = list_artifacts(task_id)
    by_type: dict[str, int] = {}
    patches = []
    for a in index:
        t = a.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        if t == "patch_candidate":
            patches.append(a.get("name", ""))
    pack["artifacts_summary"] = {"total": len(index), "by_type": by_type}
    pack["patch_candidates"] = patches

    # Committee decision
    cd = td / "committee" / "decision.json"
    if cd.exists():
        try:
            decision = json.loads(cd.read_text(encoding="utf-8"))
            pack["committee"] = {
                "agreement": decision.get("agreement"),
                "recommended_route": decision.get("recommended_route"),
                "qwen_route": decision.get("qwen_judgement", {}).get("recommended_route"),
                "gemma_route": decision.get("gemma_judgement", {}).get("recommended_route"),
            }
        except Exception:
            pass

    return pack


# ═══════════════════════════════════════════════════════════════
# Decision schema
# ═══════════════════════════════════════════════════════════════

DECISION_SCHEMA = {
    "type": "object",
    "required": ["decision", "reason"],
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["accept", "reject", "retry_local", "retry_flash",
                      "pro_execute_allowed", "ask_user", "cancel"],
        },
        "reason": {"type": "string"},
        "accepted_patch_id": {"type": "string"},
        "rejected_patch_ids": {"type": "array", "items": {"type": "string"}},
        "required_artifacts": {"type": "array", "items": {"type": "string"}},
        "allowed_next_tools": {"type": "array", "items": {"type": "string"}},
        "requires_more_tests": {"type": "boolean"},
        "override_reason": {"type": "string"},
    },
}


def validate_decision(decision: dict) -> list[str]:
    """Validate a Pro decision against the schema."""
    errors = []
    if not isinstance(decision, dict):
        return ["decision must be an object"]
    d = decision.get("decision")
    if not d:
        errors.append("missing required field: decision")
    elif d not in ("accept", "reject", "retry_local", "retry_flash",
                    "pro_execute_allowed", "ask_user", "cancel"):
        errors.append(f"unknown decision: {d}")
    if not decision.get("reason"):
        errors.append("missing required field: reason")
    return errors


# ═══════════════════════════════════════════════════════════════
# Adjudicate
# ═══════════════════════════════════════════════════════════════

def adjudicate(task_id: str, decision: dict) -> dict:
    """Record a Pro adjudication decision as an artifact.

    Validates the decision, saves it to the task's decisions/ directory,
    and updates artifact tracking.
    """
    errors = validate_decision(decision)
    if errors:
        return {"ok": False, "errors": errors}

    from pipeline_artifact_store import task_dir, save_artifact

    td = task_dir(task_id)
    dec_dir = td / "decisions"
    dec_dir.mkdir(parents=True, exist_ok=True)

    # Count existing decisions for sequence number
    existing = list(dec_dir.glob("pro_decision_*.json"))
    seq = len(existing) + 1

    decision["task_id"] = task_id
    decision["created_at"] = datetime.now(timezone.utc).isoformat()

    dec_file = dec_dir / f"pro_decision_{seq:03d}.json"
    dec_file.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    save_artifact(
        task_id, f"pro_decision_{seq:03d}.json",
        json.dumps(decision, ensure_ascii=False, indent=2),
        artifact_type="decision", tool_name="pipeline_adjudicator",
        creator="pro", accepted=True,
        metadata={"decision": decision.get("decision"), "seq": seq},
    )

    # If pro_execute_allowed override, record reason
    if decision.get("decision") == "pro_execute_allowed":
        save_artifact(
            task_id, f"override_reason_{seq:03d}.json",
            json.dumps({
                "reason": decision.get("override_reason", decision.get("reason", "")),
                "requested_at": decision["created_at"],
            }, ensure_ascii=False, indent=2),
            artifact_type="override", tool_name="pipeline_adjudicator",
            creator="pro",
            metadata={"decision_seq": seq},
        )

    return {"ok": True, "decision_file": str(dec_file), "seq": seq}


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Pipeline Pro Adjudicator — structured adjudication")
    sub = parser.add_subparsers(dest="cmd")

    build = sub.add_parser("build-pack", help="Build adjudication pack")
    build.add_argument("task_id")

    decide = sub.add_parser("decide", help="Record a Pro decision")
    decide.add_argument("task_id")
    decide.add_argument("--decision", required=True,
                         choices=["accept","reject","retry_local","retry_flash",
                                   "pro_execute_allowed","ask_user","cancel"])
    decide.add_argument("--reason", required=True)
    decide.add_argument("--accepted-patch", default=None)
    decide.add_argument("--override-reason", default=None)

    schema = sub.add_parser("schema", help="Show decision schema")

    args = parser.parse_args()

    try:
        if args.cmd == "build-pack":
            pack = build_adjudication_pack(args.task_id)
            print(json.dumps(pack, ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "decide":
            decision = {
                "decision": args.decision,
                "reason": args.reason,
            }
            if args.accepted_patch:
                decision["accepted_patch_id"] = args.accepted_patch
            if args.override_reason:
                decision["override_reason"] = args.override_reason
            result = adjudicate(args.task_id, decision)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        elif args.cmd == "schema":
            print(json.dumps(DECISION_SCHEMA, ensure_ascii=False, indent=2))
        else:
            parser.print_help()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
