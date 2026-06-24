"""Pipeline Mocks — simulated external components for E2E dry run.

Each mock simulates the output of a pipeline component without requiring
real model calls or network access. Used by ``pipeline_e2e_dry_run.py``
to verify the full pipeline in test mode.

Mock coverage:
  - MockPlanGenerator: simulates Pro generating plan.json
  - MockRouteCommittee: simulates Qwen + Gemma → route.json
  - MockLocalWorker: simulates local model producing artifacts
  - MockFlashWorker: simulates Flash cloud worker producing candidate artifacts
  - MockProDecision: simulates Pro reading artifact pack → structured decision
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any


# ═══════════════════════════════════════════════════════════════
# 13.1: Mock Plan Generator
# ═══════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MockPlanConfig:
    """Configurable knobs for mock plan generation."""
    risk_level: str = "medium"
    delegability: str = "medium"
    files_to_modify: list[str] | None = None
    phases: list[dict] | None = None
    requires_tests: bool = True
    cloud_ok: bool = False


def generate_mock_plan(
    task_description: str,
    task_id: str = "",
    config: MockPlanConfig | None = None,
) -> dict:
    """Generate a mock plan.json from a task description.

    Returns a plan dict matching the canonical plan.json schema.
    When ``config`` is provided, it seeds the output; otherwise sensible
    defaults are derived from keywords in the task description.
    """
    cfg = config or MockPlanConfig()

    # Heuristic: derive risk from task keywords
    risk = cfg.risk_level
    task_lower = task_description.lower()
    if any(kw in task_lower for kw in ("security", "release", "auth", "crypto", "deploy")):
        risk = "high"
    elif any(kw in task_lower for kw in ("refactor", "migrate", "schema", "api")):
        risk = "medium"
    elif any(kw in task_lower for kw in ("docs", "typo", "comment", "format")):
        risk = "low"

    files = cfg.files_to_modify or _guess_files(task_description)

    return {
        "task_id": task_id or str(uuid.uuid4()),
        "created_at": _now(),
        "generated_by": "mock_plan_generator",
        "task_description": task_description,
        "summary": f"Mock plan for: {task_description[:80]}",
        "risk_level": risk,
        "estimated_complexity": _complexity_for_risk(risk),
        "phases": cfg.phases or [
            {
                "name": "implementation",
                "description": "Implement the requested changes",
                "files_to_modify": files,
            },
        ],
        "files_to_modify": files,
        "requires_tests": cfg.requires_tests,
        "test_strategy": "unit + integration" if cfg.requires_tests else "none",
        "cloud_ok": cfg.cloud_ok,
        "estimated_tokens": {"pro": 2000, "flash": 0, "local": 0},
        "notes": "Mock plan — generated without real model call.",
    }


def _guess_files(task_description: str) -> list[str]:
    """Guess files from task description keywords (heuristic only)."""
    task_lower = task_description.lower()
    files = []
    if any(kw in task_lower for kw in ("mcp", "server", "tool")):
        files.append("tools/local_llm_mcp_server.py")
    if any(kw in task_lower for kw in ("router", "route", "routing")):
        files.append("tools/local_llm_router.py")
    if any(kw in task_lower for kw in ("worker", "model call")):
        files.append("tools/local_llm_worker.py")
    if any(kw in task_lower for kw in ("hook", "gate", "enforce")):
        files.append("tools/claude_hooks/route_enforcer.py")
    if any(kw in task_lower for kw in ("test", "pytest")):
        files.append("tests/")
    if any(kw in task_lower for kw in ("docs", "readme", "document")):
        files.append("README.md")
    return files or ["tools/local_llm_router.py"]


def _complexity_for_risk(risk: str) -> str:
    return {"low": "trivial", "medium": "small", "high": "medium", "critical": "large"}.get(
        risk, "small"
    )


# ═══════════════════════════════════════════════════════════════
# 13.2: Mock Route Committee (Qwen + Gemma)
# ═══════════════════════════════════════════════════════════════

@dataclass
class MockRouteCommitteeConfig:
    """Configurable knobs for mock route committee output."""
    qwen_route: str = "local_only"
    gemma_route: str = "local_only"
    agreement: bool = True
    risk_level: str = "medium"
    privacy_status: str = "safe"
    escalated: bool = False
    escalated_reason: str = ""


def generate_mock_qwen_judgement(
    plan: dict,
    qwen_route: str = "local_only",
    risk_level: str = "medium",
) -> dict:
    """Simulate Qwen's route judgement from plan.json."""
    return {
        "model": "qwen3.6-deep",
        "delegability": _delegability_for_route(qwen_route),
        "recommended_route": qwen_route,
        "local_preprocessing_required": qwen_route in ("local_only", "local_summary"),
        "pro_should_execute": qwen_route == "pro_execute_allowed",
        "pro_should_adjudicate": qwen_route in ("pro_decision", "pro_execute_allowed"),
        "risk_level": risk_level,
        "privacy_status": "safe",
        "reason": f"Qwen mock: task classified as {risk_level} risk, delegable to {qwen_route}.",
        "required_artifacts": _artifacts_for_route(qwen_route),
        "confidence": 0.9,
        "parse_failed": False,
    }


def generate_mock_gemma_judgement(
    plan: dict,
    gemma_route: str = "local_only",
    risk_level: str = "medium",
    privacy_status: str = "safe",
) -> dict:
    """Simulate Gemma's route judgement from plan.json."""
    return {
        "model": "gemma4-31b",
        "delegability": _delegability_for_route(gemma_route),
        "recommended_route": gemma_route,
        "local_preprocessing_required": gemma_route in ("local_only", "local_summary", "ask_user"),
        "pro_should_execute": gemma_route == "pro_execute_allowed",
        "pro_should_adjudicate": gemma_route in ("pro_decision", "pro_execute_allowed", "ask_user"),
        "risk_level": risk_level,
        "privacy_status": privacy_status,
        "reason": f"Gemma mock: {privacy_status} privacy, {risk_level} risk → {gemma_route}.",
        "required_artifacts": _artifacts_for_route(gemma_route),
        "confidence": 0.85,
        "parse_failed": False,
    }


def generate_mock_route_decision(
    plan: dict,
    config: MockRouteCommitteeConfig | None = None,
) -> dict:
    """Simulate the full route committee: Qwen + Gemma → merged decision.

    Returns a dict matching the RouteDecision schema from local_route_committee.py.
    """
    cfg = config or MockRouteCommitteeConfig()

    qwen = generate_mock_qwen_judgement(
        plan, qwen_route=cfg.qwen_route, risk_level=cfg.risk_level,
    )
    gemma = generate_mock_gemma_judgement(
        plan, gemma_route=cfg.gemma_route, risk_level=cfg.risk_level,
        privacy_status=cfg.privacy_status,
    )

    # Deterministic merge: if both agree on pro_decision or higher, use that;
    # if either says blocked, use blocked; if either says ask_user, use ask_user;
    # otherwise use the more conservative route.
    merged_route = _merge_routes(cfg.qwen_route, cfg.gemma_route)
    merged_artifacts = list(dict.fromkeys(
        qwen["required_artifacts"] + gemma["required_artifacts"]
    ))

    return {
        "delegability": _delegability_for_route(merged_route),
        "recommended_route": merged_route,
        "local_preprocessing_required": (
            qwen["local_preprocessing_required"] or gemma["local_preprocessing_required"]
        ),
        "pro_should_execute": (
            qwen["pro_should_execute"] or gemma["pro_should_execute"]
        ),
        "pro_should_adjudicate": (
            qwen["pro_should_adjudicate"] or gemma["pro_should_adjudicate"]
        ),
        "risk_level": cfg.risk_level,
        "privacy_status": cfg.privacy_status,
        "reason": f"Committee merged: Qwen={cfg.qwen_route}, Gemma={cfg.gemma_route} → {merged_route}",
        "required_artifacts": merged_artifacts,
        "qwen_judgement": qwen,
        "gemma_judgement": gemma,
        "agreement": cfg.agreement,
        "escalated": cfg.escalated,
        "escalated_reason": cfg.escalated_reason,
        "pro_audit_requested": not cfg.agreement,
    }


ROUTE_PRIORITY = {
    "blocked": 0, "ask_user": 1, "pro_decision": 2,
    "pro_execute_allowed": 3, "local_only": 4, "local_summary": 5,
    "flash_direct": 6, "flash_subagent": 7, "direct": 8,
}


def _merge_routes(a: str, b: str) -> str:
    """Deterministic merge: pick the more conservative (lower priority) route."""
    pa = ROUTE_PRIORITY.get(a, 4)
    pb = ROUTE_PRIORITY.get(b, 4)
    return a if pa <= pb else b


def _delegability_for_route(route: str) -> str:
    return {
        "blocked": "blocked", "ask_user": "low",
        "pro_decision": "low", "pro_execute_allowed": "medium",
        "local_only": "high", "local_summary": "high",
        "flash_direct": "medium", "flash_subagent": "medium",
        "direct": "high",
    }.get(route, "medium")


def _artifacts_for_route(route: str) -> list[str]:
    base = ["plan.json", "route.json"]
    if route in ("local_only", "local_summary"):
        return base + ["file_summary.md", "diff_review.json"]
    if route in ("flash_direct", "flash_subagent"):
        return base + ["patch_candidate.diff", "test_results.json"]
    if route in ("pro_decision", "pro_execute_allowed"):
        return base + ["evidence_pack.json", "artifact_index.json"]
    if route == "ask_user":
        return base + ["clarification_needed.md"]
    return base


# ═══════════════════════════════════════════════════════════════
# 13.3: Mock Local Worker & Flash Worker
# ═══════════════════════════════════════════════════════════════

MOCK_LOCAL_ARTIFACTS: dict[str, dict] = {
    "file_summary": {
        "artifact_type": "local_summary",
        "filename": "file_summary.md",
        "content_template": "# File Summary (Mock)\n\nMock summary for {path}.\n\n"
                          "## Purpose\nMock purpose description.\n\n"
                          "## Key Functions\n- mock_func_1\n- mock_func_2\n\n"
                          "## Dependencies\n- mock_dep\n",
    },
    "diff_review": {
        "artifact_type": "local_review",
        "filename": "diff_review.json",
        "content_template": json.dumps({
            "findings": [
                {"severity": "info", "category": "style",
                 "message": "Mock: code looks fine.", "line": 1},
            ],
            "risk_notes": ["Mock risk note — no real issues found."],
            "uncertainty": "low",
            "confidence": "high",
        }, indent=2),
    },
    "repo_map": {
        "artifact_type": "local_repo_map",
        "filename": "repo_map.json",
        "content_template": json.dumps({
            "entrypoints": ["tools/local_llm_router.py"],
            "subsystems": {"routing": ["router.py"], "execution": ["worker.py"]},
            "risk_tags": [],
        }, indent=2),
    },
    "test_plan": {
        "artifact_type": "local_test_plan",
        "filename": "test_plan.md",
        "content_template": "# Test Plan (Mock)\n\n## Unit Tests\n- mock test 1\n- mock test 2\n\n"
                          "## Edge Cases\n- empty input\n- large input\n",
    },
}


def generate_mock_local_artifact(
    task_id: str,
    artifact_name: str,
    path: str = "unknown",
) -> tuple[str, str, str]:
    """Return (filename, content, artifact_type) for a mock local worker artifact.

    Raises ValueError for unknown artifact names.
    """
    spec = MOCK_LOCAL_ARTIFACTS.get(artifact_name)
    if not spec:
        raise ValueError(
            f"Unknown mock artifact: {artifact_name}. "
            f"Known: {list(MOCK_LOCAL_ARTIFACTS)}"
        )
    content = spec["content_template"]
    if "{path}" in content:
        content = content.replace("{path}", path)
    return spec["filename"], content, spec["artifact_type"]


MOCK_FLASH_ARTIFACTS: dict[str, dict] = {
    "patch_candidate": {
        "artifact_type": "patch_candidate",
        "filename": "patch_candidate.diff",
        "content_template": (
            "--- a/tools/local_llm_router.py\n"
            "+++ b/tools/local_llm_router.py\n"
            "@@ -100,6 +100,7 @@\n"
            " # Mock patch — do not apply.\n"
            "+# MOCK CHANGE: added a comment\n"
        ),
    },
    "test_results": {
        "artifact_type": "test_run",
        "filename": "test_results.json",
        "content_template": json.dumps({
            "total": 5, "passed": 5, "failed": 0, "errors": 0,
            "duration": 2.5, "mock": True,
        }, indent=2),
    },
    "flash_review": {
        "artifact_type": "flash_review",
        "filename": "flash_review.json",
        "content_template": json.dumps({
            "verdict": "pass",
            "issues": [],
            "suggestions": ["Mock: consider adding docstring."],
        }, indent=2),
    },
    "failure_analysis": {
        "artifact_type": "flash_failure_analysis",
        "filename": "failure_analysis.json",
        "content_template": json.dumps({
            "failure_hypotheses": [
                {"hypothesis": "Mock: assertion mismatch", "confidence": "medium",
                 "evidence": "Mock evidence"},
            ],
            "repair_strategy": {
                "approach": "Fix assertion",
                "files_to_modify": ["tools/local_llm_router.py"],
                "estimated_complexity": "small",
                "risks": ["Mock risk"],
            },
            "requires_pro_escalation": False,
        }, indent=2),
    },
}


def generate_mock_flash_artifact(
    task_id: str,
    artifact_name: str,
) -> tuple[str, str, str]:
    """Return (filename, content, artifact_type) for a mock Flash worker artifact.

    Raises ValueError for unknown artifact names.
    """
    spec = MOCK_FLASH_ARTIFACTS.get(artifact_name)
    if not spec:
        raise ValueError(
            f"Unknown mock flash artifact: {artifact_name}. "
            f"Known: {list(MOCK_FLASH_ARTIFACTS)}"
        )
    return spec["filename"], spec["content_template"], spec["artifact_type"]


# ═══════════════════════════════════════════════════════════════
# 13.4: Mock Pro Decision
# ═══════════════════════════════════════════════════════════════

@dataclass
class MockProDecisionConfig:
    """Configurable knobs for mock Pro adjudication output."""
    decision: str = "accept"           # accept | reject | retry_local | retry_flash |
                                       # pro_execute_allowed | ask_user | cancel
    reason: str = "Mock: all artifacts look good."
    accepted_patch_id: str | None = None
    rejected_patch_ids: list[str] | None = None
    requires_more_tests: bool = False
    override_reason: str = ""


def generate_mock_pro_decision(
    adjudication_pack: dict,
    config: MockProDecisionConfig | None = None,
) -> dict:
    """Simulate Pro reading the adjudication pack → structured decision.

    Returns a dict matching the DECISION_SCHEMA from pipeline_adjudicator.py.
    """
    cfg = config or MockProDecisionConfig()

    decision = {
        "decision": cfg.decision,
        "reason": cfg.reason,
        "created_at": _now(),
        "adjudication_pack_summary": {
            "task_id": adjudication_pack.get("task_id", ""),
            "artifacts_total": adjudication_pack.get("artifacts_summary", {}).get("total", 0),
            "route": adjudication_pack.get("route", {}).get("recommended_route", "unknown"),
        },
    }

    if cfg.accepted_patch_id:
        decision["accepted_patch_id"] = cfg.accepted_patch_id
    if cfg.rejected_patch_ids:
        decision["rejected_patch_ids"] = cfg.rejected_patch_ids
    if cfg.requires_more_tests:
        decision["requires_more_tests"] = True
    if cfg.decision == "pro_execute_allowed" and cfg.override_reason:
        decision["override_reason"] = cfg.override_reason

    return decision


# ═══════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════

def run_mock_tests(task_id: str) -> dict:
    """Simulate a test run and return structured results."""
    return {
        "task_id": task_id,
        "total": 10,
        "passed": 10,
        "failed": 0,
        "errors": 0,
        "duration_sec": 1.5,
        "mock": True,
        "run_at": _now(),
    }
