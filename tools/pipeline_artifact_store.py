"""Pipeline Artifact Store — formalized artifact lifecycle.

Directory layout::

    .local_llm_out/tasks/<task_id>/
      user_task.md
      session.json
      plan.json
      route.json
      committee/
        evidence_pack.json
        qwen_initial.json
        gemma_initial.json
        qwen_cross_review.json
        gemma_cross_review.json
        decision.json
        metrics.json
      artifacts/
        artifact_index.json
        tool_call_000001.json
        bash_output_000001.log
        edit_record_000001.json
        ...
      decisions/
        pro_decision_001.json
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════
# Directory layout
# ═══════════════════════════════════════════════════════════════

def tasks_dir() -> Path:
    override = os.environ.get("LOCAL_LLM_TASKS_DIR")
    if override:
        return Path(override)
    return Path(".local_llm_out/tasks")


def task_dir(task_id: str) -> Path:
    return tasks_dir() / task_id


def artifacts_dir(task_id: str) -> Path:
    return task_dir(task_id) / "artifacts"


def committee_dir(task_id: str) -> Path:
    return task_dir(task_id) / "committee"


def decisions_dir(task_id: str) -> Path:
    return task_dir(task_id) / "decisions"


# ═══════════════════════════════════════════════════════════════
# Artifact metadata schema
# ═══════════════════════════════════════════════════════════════

# Fields tracked per artifact in artifact_index.json
ARTIFACT_METADATA_SCHEMA: dict[str, str] = {
    "name": "string — filename within artifacts/",
    "type": "string — tool_call | test_run | git_diff | git_log | git_status | "
             "package_install | script_run | bash_output | file_edit | "
             "local_summary | flash_review | patch_candidate | risk_note | decision",
    "tool": "string — Claude Code tool that produced it",
    "size_bytes": "int — UTF-8 byte count",
    "sha256": "string — hex digest of content",
    "created_at": "ISO 8601 timestamp",
    "creator": "string — model name or 'controller'",
    "accepted": "bool | null — controller accepted/rejected (null = pending)",
    "verified": "bool | null — test-passing verified (null = pending)",
    "dependencies": "list[str] — names of artifacts this one depends on",
    "meta": "dict | null — arbitrary extra metadata",
}


# ═══════════════════════════════════════════════════════════════
# Artifact index operations
# ═══════════════════════════════════════════════════════════════

def _index_path(task_id: str) -> Path:
    return artifacts_dir(task_id) / "artifact_index.json"


def _read_index(task_id: str) -> list[dict]:
    path = _index_path(task_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def _write_index(task_id: str, index: list[dict]) -> None:
    path = _index_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# Save artifact
# ═══════════════════════════════════════════════════════════════

def save_artifact(
    task_id: str,
    name: str,
    content: str,
    *,
    artifact_type: str = "generic",
    tool_name: str = "",
    creator: str = "controller",
    dependencies: list[str] | None = None,
    metadata: dict | None = None,
    accepted: bool | None = None,
    verified: bool | None = None,
) -> Path:
    """Save an artifact file and update the artifact index.

    Prevents name collisions by appending a sequence number when a file
    with the same name already exists.
    """
    art_dir = artifacts_dir(task_id)
    art_dir.mkdir(parents=True, exist_ok=True)

    # Collision prevention: append sequence number
    target = art_dir / name
    if target.exists():
        stem, ext = os.path.splitext(name)
        seq = 1
        while True:
            new_name = f"{stem}_{seq:03d}{ext}"
            target = art_dir / new_name
            if not target.exists():
                name = new_name
                break
            seq += 1
            if seq > 999:
                # Fallback: use timestamp
                ts = datetime.now(timezone.utc).strftime("%H%M%S%f")
                name = f"{stem}_{ts}{ext}"
                target = art_dir / name
                break

    content_bytes = content.encode("utf-8")
    target.write_text(content, encoding="utf-8")

    # Build index entry
    entry: dict[str, Any] = {
        "name": name,
        "type": artifact_type,
        "tool": tool_name,
        "size_bytes": len(content_bytes),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "creator": creator,
        "accepted": accepted,
        "verified": verified,
        "dependencies": dependencies or [],
    }
    if metadata:
        entry["meta"] = metadata

    index = _read_index(task_id)
    index.append(entry)
    _write_index(task_id, index)

    return target


# ═══════════════════════════════════════════════════════════════
# Read artifacts
# ═══════════════════════════════════════════════════════════════

def list_artifacts(task_id: str) -> list[dict]:
    """Return the artifact index for a task."""
    return _read_index(task_id)


def read_artifact(task_id: str, name: str) -> str | None:
    """Read the content of a named artifact. Returns None if not found."""
    target = artifacts_dir(task_id) / name
    if target.exists():
        return target.read_text(encoding="utf-8")
    return None


def find_artifacts_by_type(task_id: str, artifact_type: str) -> list[dict]:
    """Return all artifacts of a given type."""
    return [a for a in _read_index(task_id) if a.get("type") == artifact_type]


# ═══════════════════════════════════════════════════════════════
# Status updates
# ═══════════════════════════════════════════════════════════════

def mark_accepted(task_id: str, name: str, accepted: bool = True) -> bool:
    """Mark an artifact as accepted or rejected."""
    index = _read_index(task_id)
    for entry in index:
        if entry.get("name") == name:
            entry["accepted"] = accepted
            _write_index(task_id, index)
            return True
    return False


def mark_verified(task_id: str, name: str, verified: bool = True) -> bool:
    """Mark an artifact as verified (e.g., tests passing after applying a patch)."""
    index = _read_index(task_id)
    for entry in index:
        if entry.get("name") == name:
            entry["verified"] = verified
            _write_index(task_id, index)
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# Task report
# ═══════════════════════════════════════════════════════════════

def generate_task_report(task_id: str) -> str:
    """Generate a human-readable report from a task directory alone.

    No chat history required — everything comes from artifacts on disk.
    """
    td = task_dir(task_id)
    if not td.exists():
        return f"Task directory not found: {td}"

    session_file = td / "session.json"
    session = {}
    if session_file.exists():
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    lines = [
        f"# Task Report: {task_id}",
        "",
        f"Status: {session.get('status', 'unknown')}",
        f"Phase: {session.get('phase', 'unknown')}",
        f"Created: {session.get('created_at', 'unknown')}",
        f"Updated: {session.get('updated_at', 'unknown')}",
    ]

    user_task = session.get("user_task", "")[:200]
    if user_task:
        lines.append(f"\nTask: {user_task}")

    # Plan
    plan_file = td / "plan.json"
    lines.append(f"\nPlan: {'exists' if plan_file.exists() else 'missing'}")

    # Route
    route_file = td / "route.json"
    if route_file.exists():
        try:
            route = json.loads(route_file.read_text(encoding="utf-8"))
            lines.append(f"Route: {route.get('recommended_route', 'unknown')}")
            lines.append(f"Risk: {route.get('risk_level', 'unknown')}")
        except Exception:
            lines.append("Route: (unparseable)")

    # Committee
    cd = committee_dir(task_id)
    if cd.exists():
        decision_file = cd / "decision.json"
        if decision_file.exists():
            lines.append(f"\nCommittee: decision saved")
        metrics_file = cd / "metrics.json"
        if metrics_file.exists():
            try:
                metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
                lines.append(f"Committee metrics: {len(metrics)} entries")
            except Exception:
                pass

    # Artifacts
    index = _read_index(task_id)
    lines.append(f"\nArtifacts: {len(index)} total")
    by_type: dict[str, int] = {}
    for a in index:
        t = a.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    for t, count in sorted(by_type.items()):
        lines.append(f"  {t}: {count}")

    accepted_count = sum(1 for a in index if a.get("accepted") is True)
    rejected_count = sum(1 for a in index if a.get("accepted") is False)
    verified_count = sum(1 for a in index if a.get("verified") is True)
    if accepted_count or rejected_count:
        lines.append(f"\nAccepted: {accepted_count}, Rejected: {rejected_count}")
    if verified_count:
        lines.append(f"Verified: {verified_count}")

    # Model state
    ms = session.get("model_state", {})
    if ms:
        lines.append(f"\nModel: {ms.get('initial_model', '?')}")
        switches = ms.get("model_switches", [])
        if switches:
            lines.append(f"Model switches: {len(switches)}")

    return "\n".join(lines)
