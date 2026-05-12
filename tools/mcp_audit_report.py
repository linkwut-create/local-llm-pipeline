#!/usr/bin/env python3
"""
MCP Audit Phase Report Generator — MCP-AUDIT-3.

Generates markdown phase audit reports from SQLite audit DB.
Outputs to docs/mcp-audit/{project}/{phase}.md.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REPORT_DIR_NAME = "docs/mcp-audit"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _md_escape(value) -> str:
    """Escape pipe and other special chars for markdown table cells."""
    if value is None:
        return ""
    s = str(value)
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", "")


def _format_table(rows: list[dict], columns: list[str]) -> str:
    """Format a list of dicts as a markdown table."""
    if not rows:
        return "*(no data)*\n"
    header = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    lines = [header, sep]
    for row in rows:
        cells = [_md_escape(row.get(c, "")) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_report_dir(base_dir: str | Path | None = None) -> Path:
    report_base = os.environ.get("MCP_AUDIT_REPORT_DIR")
    if report_base:
        return Path(report_base)
    if base_dir:
        return Path(base_dir) / DEFAULT_REPORT_DIR_NAME
    return Path.cwd() / DEFAULT_REPORT_DIR_NAME


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_phase_report_data(conn: sqlite3.Connection, phase_id: str,
                              project_name: str | None = None) -> dict:
    """Collect all data needed for a phase report. Returns a dict."""
    data = {
        "phase_id": phase_id,
        "project_name": project_name or "unknown",
        "generated_at": _utc_now(),
        "commit_before": None,
        "commit_after": None,
        "final_status": "unknown",
    }

    # --- Invocation stats ---
    sql = "SELECT COUNT(*) FROM mcp_invocation_log WHERE phase_id = ?"
    params = [phase_id]
    if project_name:
        sql += " AND project_name = ?"
        params.append(project_name)
    data["invocation_count"] = conn.execute(sql, params).fetchone()[0]

    # --- Failure stats ---
    sql = "SELECT COUNT(*) FROM mcp_failure_log WHERE phase_id = ?"
    params = [phase_id]
    if project_name:
        sql += " AND project_name = ?"
        params.append(project_name)
    data["failure_count"] = conn.execute(sql, params).fetchone()[0]

    # --- Blocked commits ---
    sql = (
        "SELECT COUNT(*) FROM mcp_invocation_log "
        "WHERE phase_id = ? AND event_type = 'commit_gate_blocked'"
    )
    data["blocked_commit_count"] = conn.execute(sql, [phase_id]).fetchone()[0]

    # --- Commit gate bypass ---
    sql = (
        "SELECT COUNT(*) FROM mcp_invocation_log "
        "WHERE phase_id = ? AND event_type IN ('gate_subprocess_bypass', 'commit_gate_bypassed')"
    )
    data["bypass_count"] = conn.execute(sql, [phase_id]).fetchone()[0]

    # --- Recommendations ---
    sql = (
        "SELECT decision, COUNT(*) as cnt FROM mcp_recommendation_log "
        "WHERE id IN (SELECT linked_recommendation_id FROM mcp_invocation_log WHERE phase_id = ?) "
        "GROUP BY decision"
    )
    rec_counts = {r["decision"]: r["cnt"] for r in conn.execute(sql, [phase_id]).fetchall()}
    data["accepted_recommendation_count"] = rec_counts.get("accepted", 0)
    data["rejected_recommendation_count"] = rec_counts.get("rejected", 0)
    data["ignored_recommendation_count"] = rec_counts.get("ignored", 0)
    data["overridden_count"] = rec_counts.get("overridden_by_user", 0)

    # --- Test results ---
    sql = (
        "SELECT tests_run, final_test_result, commit_before, commit_after, final_status "
        "FROM mcp_phase_audit "
        "WHERE phase_id = ? ORDER BY created_at DESC LIMIT 1"
    )
    pa = conn.execute(sql, [phase_id]).fetchone()
    if pa:
        data["tests_run"] = pa["tests_run"] or 0
        data["final_test_result"] = pa["final_test_result"] or "not_run"
        data["commit_before"] = pa["commit_before"]
        data["commit_after"] = pa["commit_after"]
        data["final_status"] = pa["final_status"] or "unknown"

    # --- Commit range from events ---
    if not data["commit_before"]:
        row = conn.execute(
            "SELECT commit_before, commit_after FROM mcp_invocation_log "
            "WHERE phase_id = ? AND commit_before IS NOT NULL "
            "ORDER BY created_at LIMIT 1",
            [phase_id]
        ).fetchone()
        if row:
            data["commit_before"] = row["commit_before"]
    if not data["commit_after"]:
        row = conn.execute(
            "SELECT commit_after FROM mcp_invocation_log "
            "WHERE phase_id = ? AND commit_after IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            [phase_id]
        ).fetchone()
        if row:
            data["commit_after"] = row["commit_after"]

    # --- Tool usage ---
    sql = (
        "SELECT tool_name, COUNT(*) as total, "
        "SUM(CASE WHEN result_status = 'failed' THEN 1 ELSE 0 END) as failed, "
        "SUM(CASE WHEN result_status = 'blocked' THEN 1 ELSE 0 END) as blocked, "
        "SUM(CASE WHEN result_status = 'timeout' THEN 1 ELSE 0 END) as timeout "
        "FROM mcp_invocation_log "
        "WHERE phase_id = ? AND tool_name IS NOT NULL "
        "GROUP BY tool_name ORDER BY total DESC"
    )
    data["tool_usage"] = [dict(r) for r in conn.execute(sql, [phase_id]).fetchall()]

    # --- Failures detail ---
    sql = (
        "SELECT * FROM mcp_failure_log WHERE phase_id = ? ORDER BY created_at DESC"
    )
    data["failures"] = [dict(r) for r in conn.execute(sql, [phase_id]).fetchall()]

    # --- Commit gate events ---
    sql = (
        "SELECT * FROM mcp_invocation_log "
        "WHERE phase_id = ? AND event_type IN "
        "('commit_gate_blocked', 'hook_state_mismatch', 'staged_diff_hash_mismatch', "
        "'gate_subprocess_bypass', 'commit_gate_bypassed', 'gate_boundary_audit') "
        "ORDER BY created_at DESC"
    )
    data["gate_events"] = [dict(r) for r in conn.execute(sql, [phase_id]).fetchall()]

    # --- Recommendations ---
    sql = (
        "SELECT * FROM mcp_recommendation_log WHERE id IN "
        "(SELECT linked_recommendation_id FROM mcp_invocation_log WHERE phase_id = ?) "
        "ORDER BY created_at DESC"
    )
    data["recommendations"] = [dict(r) for r in conn.execute(sql, [phase_id]).fetchall()]

    return data


# ---------------------------------------------------------------------------
# Risk judgment
# ---------------------------------------------------------------------------

def _status_from_counts(data: dict) -> str:
    """Determine risk level from phase data.

    Returns one of: blocked, high, medium, low
    """
    failures = data.get("failures", [])

    # Unresolved critical/blocking → blocked
    for f in failures:
        if f.get("severity") in ("critical", "blocking") and not f.get("resolved"):
            return "blocked"

    # Unresolved high failure → high
    for f in failures:
        if f.get("severity") == "high" and not f.get("resolved"):
            return "high"

    # Commit gate bypass event → high
    if data.get("bypass_count", 0) > 0:
        return "high"

    # Rejected blocking recommendation → high
    for r in data.get("recommendations", []):
        if r.get("severity") == "blocking" and r.get("decision") == "rejected":
            return "high"

    # Failures exist but all resolved → medium
    if data.get("failure_count", 0) > 0:
        return "medium"

    # All clean → low
    return "low"


def _next_recommendation(data: dict, risk: str) -> str:
    """Generate a next-step recommendation based on risk and data."""
    if risk == "blocked":
        return "Fix unresolved critical/blocking failures before proceeding."
    if risk == "high":
        if data.get("bypass_count", 0) > 0:
            return "Investigate gate bypass events before proceeding. Run debate review."
        return "Resolve high-severity failures before proceeding. Consider debate review."
    if risk == "medium":
        return "All failures resolved. Verify fixes and re-run tests before proceeding."
    return "Proceed to next phase."


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def format_phase_report_markdown(data: dict) -> str:
    """Generate a complete markdown phase audit report."""
    risk = _status_from_counts(data)
    next_rec = _next_recommendation(data, risk)

    lines = []
    lines.append(f"# MCP Audit Report — {_md_escape(data['phase_id'])}")
    lines.append("")

    # 1. Metadata
    lines.append("## 1. Metadata")
    lines.append("")
    lines.append(f"- **Project**: {_md_escape(data.get('project_name', 'unknown'))}")
    lines.append(f"- **Phase**: {_md_escape(data['phase_id'])}")
    lines.append(f"- **Generated**: {_md_escape(data.get('generated_at', ''))}")
    lines.append(f"- **Commit before**: `{_md_escape(data.get('commit_before', 'unknown'))}`")
    lines.append(f"- **Commit after**: `{_md_escape(data.get('commit_after', 'unknown'))}`")
    lines.append(f"- **Final status**: {_md_escape(data.get('final_status', 'unknown'))}")
    lines.append("")

    # 2. Summary
    lines.append("## 2. Summary")
    lines.append("")
    lines.append(f"- **MCP calls**: {data.get('invocation_count', 0)}")
    lines.append(f"- **Failures**: {data.get('failure_count', 0)}")
    lines.append(f"- **Blocked commits**: {data.get('blocked_commit_count', 0)}")
    lines.append(f"- **Gate bypass events**: {data.get('bypass_count', 0)}")
    lines.append(f"- **Accepted recommendations**: {data.get('accepted_recommendation_count', 0)}")
    lines.append(f"- **Rejected recommendations**: {data.get('rejected_recommendation_count', 0)}")
    lines.append(f"- **Tests run**: {data.get('tests_run', 0)}")
    lines.append(f"- **Final test result**: {_md_escape(data.get('final_test_result', 'not_run'))}")
    lines.append("")

    # 3. Tool usage
    lines.append("## 3. Tool usage")
    lines.append("")
    tools = data.get("tool_usage", [])
    if tools:
        for t in tools:
            total = t.get("total", 0)
            failed = t.get("failed", 0)
            rate = f"{(failed / total * 100):.0f}%" if total > 0 else "0%"
            t["failure_rate"] = rate
        lines.append(_format_table(tools, ["tool_name", "total", "failed", "blocked", "timeout", "failure_rate"]))
    else:
        lines.append("*(no tool usage data)*")
        lines.append("")

    # 4. Failures
    lines.append("## 4. Failures")
    lines.append("")
    failures = data.get("failures", [])
    if failures:
        lines.append(_format_table(failures, [
            "failure_type", "severity", "tool_name", "command",
            "resolved", "notes",
        ]))
    else:
        lines.append("No failures recorded.")
        lines.append("")

    # 5. Commit gate events
    lines.append("## 5. Commit gate events")
    lines.append("")
    gate_events = data.get("gate_events", [])
    if gate_events:
        lines.append(_format_table(gate_events, [
            "event_type", "result_status", "created_at", "notes",
        ]))
    else:
        lines.append("No commit gate events recorded.")
        lines.append("")

    # 6. Recommendations
    lines.append("## 6. Recommendations")
    lines.append("")
    recs = data.get("recommendations", [])
    accepted = [r for r in recs if r.get("decision") == "accepted"]
    rejected = [r for r in recs if r.get("decision") in ("rejected", "ignored", "overridden_by_user")]

    lines.append("### Accepted")
    lines.append("")
    if accepted:
        lines.append(_format_table(accepted, [
            "recommendation", "severity", "applied_commit",
        ]))
    else:
        lines.append("*(none)*")
        lines.append("")

    lines.append("### Rejected / Ignored / Overridden")
    lines.append("")
    if rejected:
        lines.append(_format_table(rejected, [
            "recommendation", "severity", "decision", "decision_reason",
        ]))
    else:
        lines.append("*(none)*")
        lines.append("")

    # 7. Tests
    lines.append("## 7. Tests")
    lines.append("")
    lines.append(f"- **Tests run**: {data.get('tests_run', 0)}")
    lines.append(f"- **Final test result**: {_md_escape(data.get('final_test_result', 'not_run'))}")
    lines.append("")

    # 8. Risk judgment
    lines.append("## 8. Risk judgment")
    lines.append("")
    lines.append(f"**Risk level: {risk.upper()}**")
    lines.append("")

    # Explain why
    if risk == "blocked":
        lines.append("Unresolved critical or blocking failures exist.")
    elif risk == "high":
        if data.get("bypass_count", 0) > 0:
            lines.append(f"Gate bypass events detected ({data['bypass_count']}).")
        else:
            lines.append("Unresolved high-severity failures exist.")
    elif risk == "medium":
        lines.append("Failures exist but all are resolved or low severity.")
    else:
        lines.append("No failures. Tests pass.")
    lines.append("")

    # 9. Next recommendation
    lines.append("## 9. Next recommendation")
    lines.append("")
    lines.append(next_rec)
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_phase_report(conn: sqlite3.Connection, phase_id: str,
                          project_name: str | None = None) -> str:
    """Generate a markdown phase report from SQLite data."""
    data = collect_phase_report_data(conn, phase_id, project_name)
    return format_phase_report_markdown(data)


def write_phase_report(base_dir: str | Path | None = None,
                       phase_id: str | None = None,
                       project_name: str | None = None,
                       output_dir: str | Path | None = None) -> str | None:
    """Generate and write a phase report to disk.

    Uses SQLite DB at base_dir (or .mcp_audit/).
    Writes to output_dir if given, otherwise docs/mcp-audit/{project}/{phase}.md.

    Returns the output path on success, None on failure.
    """
    # Import here to avoid circular dependency at module level
    import mcp_audit_db

    if not phase_id:
        return None

    try:
        conn = mcp_audit_db.connect_audit_db(base_dir)
        report = generate_phase_report(conn, phase_id, project_name)
        conn.close()

        proj = project_name or "unknown"
        out = Path(output_dir) if output_dir else _get_report_dir(base_dir)
        out_dir = out / proj
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{phase_id}.md"
        out_file.write_text(report, encoding="utf-8")
        return str(out_file)
    except Exception:
        return None
