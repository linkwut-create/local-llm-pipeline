#!/usr/bin/env python3
"""
MCP Audit JSONL Event Logger — minimal viable implementation (MCP-AUDIT-1).

Writes structured JSONL records to .mcp_audit/{events,failures,recommendations,phase_audits}.jsonl.
No SQLite, no query CLI, no hook integration.
Follows the design in docs/mcp-audit-design.md.

Privacy: never writes full prompt body, full diff, full code, or secrets to JSONL.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants — default audit directory (relative to project root)
# ---------------------------------------------------------------------------
DEFAULT_AUDIT_DIR_NAME = ".mcp_audit"
DEFAULT_EVENTS_FILE = "events.jsonl"
DEFAULT_FAILURES_FILE = "failures.jsonl"
DEFAULT_RECOMMENDATIONS_FILE = "recommendations.jsonl"
DEFAULT_PHASE_AUDITS_FILE = "phase_audits.jsonl"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

EVENT_TYPES = frozenset({
    "mcp_invocation_started",
    "mcp_invocation_finished",
    "mcp_invocation_failed",
    "recommendation_created",
    "recommendation_accepted",
    "recommendation_rejected",
    "test_failed",
    "test_passed",
    "commit_gate_blocked",
    "staged_review_passed",
    "debate_review_warning",
    "error_recovery_triggered",
    "fix_applied",
    "phase_audit_completed",
    "hook_state_mismatch",
    "cli_review_not_recognized",
    "staged_diff_hash_mismatch",
    "manual_hook_state_alignment",
})

TASK_TYPES = frozenset({
    "environment_check",
    "file_summary",
    "test_plan",
    "diff_review",
    "debate_review",
    "commit_gate",
    "error_diagnosis",
    "phase_freeze_review",
    "release_review",
    "documentation_review",
    "hook_state_check",
    "audit_logging",
})

FAILURE_TYPES = frozenset({
    "tool_failed",
    "model_timeout",
    "model_bad_output",
    "model_unavailable",
    "commit_gate_blocked",
    "test_failed",
    "diff_review_blocked",
    "debate_review_warning",
    "repeated_error_triggered",
    "environment_error",
    "dependency_error",
    "path_error",
    "permission_error",
    "git_state_error",
    "dirty_worktree_error",
    "hook_state_mismatch",
    "cli_review_not_recognized",
    "staged_diff_hash_mismatch",
    "manual_state_alignment_required",
    "user_override",
    "recommendation_rejected",
    "fixed_after_mcp",
    "unresolved_failure",
})

RECOMMENDATION_DECISIONS = frozenset({
    "accepted",
    "rejected",
    "partially_accepted",
    "ignored",
    "overridden_by_user",
    "obsolete_after_fix",
})

SEVERITY_VALUES = frozenset({
    "info",
    "low",
    "medium",
    "high",
    "critical",
    "blocking",
})

RESULT_STATUS_VALUES = frozenset({
    "started",
    "passed",
    "failed",
    "blocked",
    "warning",
    "skipped",
    "timeout",
    "resolved",
    "unresolved",
})

# ---------------------------------------------------------------------------
# Privacy: fields that must NOT appear in JSONL records
# ---------------------------------------------------------------------------
_FORBIDDEN_FIELDS = frozenset({
    "prompt_body",
    "full_diff",
    "full_code",
    "file_content",
    "api_key",
    "token",
    "password",
    "secret",
})

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_audit_base_dir(base_dir: str | Path | None = None) -> Path:
    """Resolve the audit base directory.

    Priority:
    1. MCP_AUDIT_DIR environment variable (used as-is)
    2. base_dir argument (treated as project root, .mcp_audit appended)
    3. CWD / .mcp_audit
    """
    env_dir = os.environ.get("MCP_AUDIT_DIR")
    if env_dir:
        return Path(env_dir)
    if base_dir:
        return Path(base_dir) / DEFAULT_AUDIT_DIR_NAME
    return Path.cwd() / DEFAULT_AUDIT_DIR_NAME


def _sanitize_record(record: dict) -> dict:
    """Remove forbidden fields and redact obvious secret patterns."""
    clean = {}
    for k, v in record.items():
        if k in _FORBIDDEN_FIELDS:
            continue
        if isinstance(v, str) and _looks_like_secret(v):
            clean[k] = "[REDACTED]"
        else:
            clean[k] = v
    return clean


def _looks_like_secret(value: str) -> bool:
    """Quick heuristic: does this string look like a secret/token/key?"""
    if len(value) < 8:
        return False
    import re
    patterns = [
        r'sk-[a-zA-Z0-9_-]{20,}',
        r'Bearer\s+[a-zA-Z0-9_\-\.]{20,}',
        r'api_key[=:]\s*["\']?[a-zA-Z0-9_\-]{10,}',
        r'"token"\s*:\s*"[a-zA-Z0-9_\-]{10,}"',
        r'"secret"\s*:\s*"[^"]{8,}"',
        r'"password"\s*:\s*"[^"]{8,}"',
    ]
    for pat in patterns:
        if re.search(pat, value):
            return True
    return False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_event_id() -> str:
    return str(uuid.uuid4())


def ensure_audit_dirs(base_dir: str | Path | None = None) -> Path:
    """Create .mcp_audit directory if it doesn't exist. Returns the base path."""
    audit_dir = _get_audit_base_dir(base_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir


def append_jsonl(path: Path, record: dict) -> bool:
    """Append a single JSON object as one line to a JSONL file.

    Returns True on success, False on failure (never raises).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        # Atomic-ish: write to temp, then replace (best-effort on Windows)
        tmp_path = path.parent / f".{path.name}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(line + "\n")
        # Append — for JSONL we append, not replace
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        tmp_path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_event(record: dict) -> list[str]:
    """Validate an audit event record. Returns list of error messages (empty = valid)."""
    errors = []
    if "event_type" not in record:
        errors.append("missing field: event_type")
    elif record["event_type"] not in EVENT_TYPES:
        errors.append(f"invalid event_type: {record['event_type']}")
    if record.get("task_type") and record["task_type"] not in TASK_TYPES:
        errors.append(f"invalid task_type: {record['task_type']}")
    if record.get("result_status") and record["result_status"] not in RESULT_STATUS_VALUES:
        errors.append(f"invalid result_status: {record['result_status']}")
    if not record.get("id"):
        errors.append("missing field: id")
    return errors


def validate_failure(record: dict) -> list[str]:
    """Validate a failure record."""
    errors = []
    if "failure_type" not in record:
        errors.append("missing field: failure_type")
    elif record["failure_type"] not in FAILURE_TYPES:
        errors.append(f"invalid failure_type: {record['failure_type']}")
    if record.get("severity") and record["severity"] not in SEVERITY_VALUES:
        errors.append(f"invalid severity: {record['severity']}")
    if not record.get("id"):
        errors.append("missing field: id")
    return errors


def validate_recommendation(record: dict) -> list[str]:
    """Validate a recommendation record."""
    errors = []
    if "decision" not in record:
        errors.append("missing field: decision")
    elif record["decision"] not in RECOMMENDATION_DECISIONS:
        errors.append(f"invalid decision: {record['decision']}")
    if record.get("severity") and record["severity"] not in SEVERITY_VALUES:
        errors.append(f"invalid severity: {record['severity']}")
    if not record.get("id"):
        errors.append("missing field: id")
    return errors


def validate_phase_audit(record: dict) -> list[str]:
    """Validate a phase audit record."""
    errors = []
    if "phase_id" not in record:
        errors.append("missing field: phase_id")
    if record.get("final_status") and record["final_status"] not in {"completed", "blocked", "failed", "abandoned"}:
        errors.append(f"invalid final_status: {record['final_status']}")
    if not record.get("id"):
        errors.append("missing field: id")
    return errors


# ---------------------------------------------------------------------------
# Core write functions
# ---------------------------------------------------------------------------

def write_audit_event(base_dir: str | Path, event: dict) -> str | None:
    """Write an audit event to events.jsonl.

    Automatically fills id and created_at if missing.
    Returns the event id on success, None on failure.
    """
    record = dict(event)
    record.setdefault("id", generate_event_id())
    record.setdefault("created_at", utc_now_iso())

    errors = validate_event(record)
    if errors:
        return None

    record = _sanitize_record(record)
    audit_dir = ensure_audit_dirs(base_dir)
    path = audit_dir / DEFAULT_EVENTS_FILE
    if append_jsonl(path, record):
        return record["id"]
    return None


def write_failure_event(base_dir: str | Path, failure: dict) -> str | None:
    """Write a failure event to failures.jsonl (and also to events.jsonl).

    Returns the event id on success, None on failure.
    """
    record = dict(failure)
    record.setdefault("id", generate_event_id())
    record.setdefault("created_at", utc_now_iso())

    errors = validate_failure(record)
    if errors:
        return None

    record = _sanitize_record(record)
    audit_dir = ensure_audit_dirs(base_dir)

    # Write to failures.jsonl
    fail_path = audit_dir / DEFAULT_FAILURES_FILE
    if not append_jsonl(fail_path, record):
        return None

    # Also record as a general event
    event_record = {
        "id": generate_event_id(),
        "created_at": record["created_at"],
        "event_type": "mcp_invocation_failed",
        "project_name": record.get("project_name"),
        "project_path": record.get("project_path"),
        "phase_id": record.get("phase_id"),
        "task_id": record.get("task_id"),
        "tool_name": record.get("tool_name"),
        "result_status": "failed",
        "linked_failure_id": record["id"],
        "failure_type": record.get("failure_type"),
    }
    evt_path = audit_dir / DEFAULT_EVENTS_FILE
    append_jsonl(evt_path, _sanitize_record(event_record))

    return record["id"]


def write_recommendation_event(base_dir: str | Path, recommendation: dict) -> str | None:
    """Write a recommendation to recommendations.jsonl.

    Returns the event id on success, None on failure.
    """
    record = dict(recommendation)
    record.setdefault("id", generate_event_id())
    record.setdefault("created_at", utc_now_iso())

    errors = validate_recommendation(record)
    if errors:
        return None

    record = _sanitize_record(record)
    audit_dir = ensure_audit_dirs(base_dir)
    path = audit_dir / DEFAULT_RECOMMENDATIONS_FILE
    if append_jsonl(path, record):
        # Also write as event
        evt = {
            "id": generate_event_id(),
            "created_at": record["created_at"],
            "event_type": "recommendation_created",
            "project_name": record.get("project_name"),
            "phase_id": record.get("phase_id"),
            "tool_name": record.get("tool_name"),
            "result_status": record.get("decision", "pending"),
            "linked_recommendation_id": record["id"],
        }
        evt_path = audit_dir / DEFAULT_EVENTS_FILE
        append_jsonl(evt_path, _sanitize_record(evt))
        return record["id"]
    return None


def write_phase_audit_event(base_dir: str | Path, phase_audit: dict) -> str | None:
    """Write a phase audit summary to phase_audits.jsonl.

    Returns the event id on success, None on failure.
    """
    record = dict(phase_audit)
    record.setdefault("id", generate_event_id())
    record.setdefault("created_at", utc_now_iso())

    errors = validate_phase_audit(record)
    if errors:
        return None

    record = _sanitize_record(record)
    audit_dir = ensure_audit_dirs(base_dir)
    path = audit_dir / DEFAULT_PHASE_AUDITS_FILE
    if append_jsonl(path, record):
        # Also write as event
        evt = {
            "id": generate_event_id(),
            "created_at": record["created_at"],
            "event_type": "phase_audit_completed",
            "project_name": record.get("project_name"),
            "phase_id": record.get("phase_id"),
            "final_status": record.get("final_status"),
            "commit_before": record.get("commit_before"),
            "commit_after": record.get("commit_after"),
        }
        evt_path = audit_dir / DEFAULT_EVENTS_FILE
        append_jsonl(evt_path, _sanitize_record(evt))
        return record["id"]
    return None
