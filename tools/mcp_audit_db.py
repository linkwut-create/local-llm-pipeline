#!/usr/bin/env python3
"""
MCP Audit SQLite Database — minimal viable implementation (MCP-AUDIT-2).

Stores MCP audit events in SQLite for long-term query, statistics, and
phase review. JSONL remains the source of truth; SQLite is a downstream
query layer.
"""

import json
import os
import sqlite3
from pathlib import Path

DEFAULT_AUDIT_DIR_NAME = ".mcp_audit"
DEFAULT_DB_NAME = "mcp_audit.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mcp_invocation_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    event_type TEXT,
    project_name TEXT,
    project_path TEXT,
    phase_id TEXT,
    task_id TEXT,
    tool_name TEXT,
    task_type TEXT,
    purpose TEXT,
    input_summary TEXT,
    output_summary TEXT,
    files_involved TEXT,
    tests_involved TEXT,
    command TEXT,
    result_status TEXT,
    blocking INTEGER NOT NULL DEFAULT 0,
    commit_before TEXT,
    commit_after TEXT,
    staged_diff_hash TEXT,
    reviewed_diff_hash TEXT,
    raw_log_path TEXT,
    linked_failure_id TEXT,
    linked_recommendation_id TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_invocation_project ON mcp_invocation_log(project_name, phase_id);
CREATE INDEX IF NOT EXISTS idx_invocation_tool ON mcp_invocation_log(tool_name, created_at);
CREATE INDEX IF NOT EXISTS idx_invocation_status ON mcp_invocation_log(result_status, created_at);
CREATE INDEX IF NOT EXISTS idx_invocation_event_type ON mcp_invocation_log(event_type);

CREATE TABLE IF NOT EXISTS mcp_failure_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    project_name TEXT,
    project_path TEXT,
    phase_id TEXT,
    task_id TEXT,
    failure_type TEXT,
    severity TEXT,
    tool_name TEXT,
    command TEXT,
    exit_code INTEGER,
    stderr_summary TEXT,
    traceback_summary TEXT,
    files_involved TEXT,
    tests_involved TEXT,
    mcp_diagnosis TEXT,
    possible_causes TEXT,
    recommended_fixes TEXT,
    fix_applied TEXT,
    fix_result TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    commit_before TEXT,
    commit_after TEXT,
    staged_diff_hash TEXT,
    reviewed_diff_hash TEXT,
    hook_state_summary TEXT,
    raw_log_path TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_failure_project ON mcp_failure_log(project_name, phase_id);
CREATE INDEX IF NOT EXISTS idx_failure_type ON mcp_failure_log(failure_type, created_at);
CREATE INDEX IF NOT EXISTS idx_failure_severity ON mcp_failure_log(severity, resolved);

CREATE TABLE IF NOT EXISTS mcp_recommendation_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    invocation_id TEXT,
    recommendation TEXT,
    severity TEXT,
    category TEXT,
    decision TEXT,
    decision_reason TEXT,
    applied_change TEXT,
    related_files TEXT,
    related_tests TEXT,
    applied_commit TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_rec_decision ON mcp_recommendation_log(decision, created_at);

CREATE TABLE IF NOT EXISTS mcp_phase_audit (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    project_name TEXT,
    project_path TEXT,
    phase_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    blocked_commit_count INTEGER NOT NULL DEFAULT 0,
    accepted_recommendation_count INTEGER NOT NULL DEFAULT 0,
    rejected_recommendation_count INTEGER NOT NULL DEFAULT 0,
    tests_run INTEGER NOT NULL DEFAULT 0,
    final_test_result TEXT,
    commit_before TEXT,
    commit_after TEXT,
    final_status TEXT,
    summary TEXT,
    next_recommendation TEXT
);

CREATE INDEX IF NOT EXISTS idx_phase_project ON mcp_phase_audit(project_name);
CREATE INDEX IF NOT EXISTS idx_phase_status ON mcp_phase_audit(final_status, created_at);

-- Views for common queries
CREATE VIEW IF NOT EXISTS v_tool_reliability AS
SELECT
    tool_name,
    COUNT(*) AS total_calls,
    SUM(CASE WHEN result_status = 'failed' THEN 1 ELSE 0 END) AS failure_count,
    SUM(CASE WHEN result_status = 'blocked' THEN 1 ELSE 0 END) AS blocked_count,
    SUM(CASE WHEN result_status = 'timeout' THEN 1 ELSE 0 END) AS timeout_count,
    ROUND(CAST(SUM(CASE WHEN result_status IN ('failed','timeout','blocked') THEN 1 ELSE 0 END) AS REAL) / MAX(COUNT(*), 1), 4) AS failure_rate
FROM mcp_invocation_log
WHERE tool_name IS NOT NULL
GROUP BY tool_name;

CREATE VIEW IF NOT EXISTS v_phase_summary AS
SELECT
    project_name,
    phase_id,
    COUNT(*) AS invocation_count,
    SUM(CASE WHEN result_status IN ('failed','blocked','timeout') THEN 1 ELSE 0 END) AS failure_count,
    SUM(CASE WHEN event_type = 'commit_gate_blocked' THEN 1 ELSE 0 END) AS blocked_commit_count,
    MIN(created_at) AS started_at,
    MAX(created_at) AS finished_at
FROM mcp_invocation_log
WHERE phase_id IS NOT NULL
GROUP BY project_name, phase_id;
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_audit_base_dir(base_dir: str | Path | None = None) -> Path:
    env_dir = os.environ.get("MCP_AUDIT_DIR")
    if env_dir:
        return Path(env_dir)
    if base_dir:
        return Path(base_dir) / DEFAULT_AUDIT_DIR_NAME
    return Path.cwd() / DEFAULT_AUDIT_DIR_NAME


def _serialize_field(value, default=None) -> str | None:
    """Serialize list/dict fields to JSON string for SQLite storage."""
    v = value if value is not None else default
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _ensure_db_dir(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_audit_db_path(base_dir: str | Path | None = None) -> Path:
    return _get_audit_base_dir(base_dir) / DEFAULT_DB_NAME


def connect_audit_db(base_dir: str | Path | None = None) -> sqlite3.Connection:
    db_path = get_audit_db_path(base_dir)
    _ensure_db_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return conn


def init_audit_db(base_dir: str | Path | None = None):
    """Create/recreate all tables and indexes. Idempotent (IF NOT EXISTS)."""
    conn = connect_audit_db(base_dir)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def migrate_audit_db(conn: sqlite3.Connection):
    """Run schema migrations. Currently a no-op (v1 schema)."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Insert functions (idempotent — INSERT OR IGNORE)
# ---------------------------------------------------------------------------

def insert_invocation(conn: sqlite3.Connection, record: dict):
    fields = [
        "id", "created_at", "event_type", "project_name", "project_path",
        "phase_id", "task_id", "tool_name", "task_type", "purpose",
        "input_summary", "output_summary", "files_involved", "tests_involved",
        "command", "result_status", "blocking", "commit_before", "commit_after",
        "staged_diff_hash", "reviewed_diff_hash", "raw_log_path",
        "linked_failure_id", "linked_recommendation_id", "notes",
    ]
    defaults = {"blocking": 0}
    values = {f: _serialize_field(record.get(f), defaults.get(f)) for f in fields}
    placeholders = ", ".join(f":{f}" for f in fields)
    columns = ", ".join(fields)
    sql = f"INSERT OR IGNORE INTO mcp_invocation_log ({columns}) VALUES ({placeholders})"
    conn.execute(sql, values)


def insert_failure(conn: sqlite3.Connection, record: dict):
    fields = [
        "id", "created_at", "project_name", "project_path", "phase_id",
        "task_id", "failure_type", "severity", "tool_name", "command",
        "exit_code", "stderr_summary", "traceback_summary", "files_involved",
        "tests_involved", "mcp_diagnosis", "possible_causes", "recommended_fixes",
        "fix_applied", "fix_result", "resolved", "commit_before", "commit_after",
        "staged_diff_hash", "reviewed_diff_hash", "hook_state_summary",
        "raw_log_path", "notes",
    ]
    defaults = {"resolved": 0}
    values = {f: _serialize_field(record.get(f), defaults.get(f)) for f in fields}
    placeholders = ", ".join(f":{f}" for f in fields)
    columns = ", ".join(fields)
    sql = f"INSERT OR IGNORE INTO mcp_failure_log ({columns}) VALUES ({placeholders})"
    conn.execute(sql, values)


def insert_recommendation(conn: sqlite3.Connection, record: dict):
    fields = [
        "id", "created_at", "invocation_id", "recommendation", "severity",
        "category", "decision", "decision_reason", "applied_change",
        "related_files", "related_tests", "applied_commit", "notes",
    ]
    defaults = {}
    values = {f: _serialize_field(record.get(f), defaults.get(f)) for f in fields}
    placeholders = ", ".join(f":{f}" for f in fields)
    columns = ", ".join(fields)
    sql = f"INSERT OR IGNORE INTO mcp_recommendation_log ({columns}) VALUES ({placeholders})"
    conn.execute(sql, values)


def insert_phase_audit(conn: sqlite3.Connection, record: dict):
    fields = [
        "id", "created_at", "project_name", "project_path", "phase_id",
        "started_at", "finished_at", "invocation_count", "failure_count",
        "blocked_commit_count", "accepted_recommendation_count",
        "rejected_recommendation_count", "tests_run", "final_test_result",
        "commit_before", "commit_after", "final_status", "summary",
        "next_recommendation",
    ]
    defaults = {
        "invocation_count": 0, "failure_count": 0, "blocked_commit_count": 0,
        "accepted_recommendation_count": 0, "rejected_recommendation_count": 0,
        "tests_run": 0,
    }
    values = {f: _serialize_field(record.get(f), defaults.get(f)) for f in fields}
    placeholders = ", ".join(f":{f}" for f in fields)
    columns = ", ".join(fields)
    sql = f"INSERT OR IGNORE INTO mcp_phase_audit ({columns}) VALUES ({placeholders})"
    conn.execute(sql, values)


# ---------------------------------------------------------------------------
# JSONL import
# ---------------------------------------------------------------------------

def import_jsonl_file(conn: sqlite3.Connection, path: Path, record_type: str) -> dict:
    """Import one JSONL file into the corresponding SQLite table.

    record_type: 'event', 'failure', 'recommendation', 'phase_audit'

    Returns {"imported": N, "skipped": N, "errors": N}.
    """
    insert_fn = {
        "event": insert_invocation,
        "failure": insert_failure,
        "recommendation": insert_recommendation,
        "phase_audit": insert_phase_audit,
    }.get(record_type)

    if not insert_fn:
        return {"imported": 0, "skipped": 0, "errors": 1}

    result = {"imported": 0, "skipped": 0, "errors": 0}
    if not path.exists():
        return result

    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            result["errors"] += 1
            continue
        try:
            insert_fn(conn, record)
            result["imported"] += 1
        except Exception:
            result["errors"] += 1
    conn.commit()
    return result


def import_audit_jsonl(base_dir: str | Path | None = None) -> dict:
    """Import all JSONL files into SQLite. Returns summary dict."""
    audit_dir = _get_audit_base_dir(base_dir)
    conn = connect_audit_db(base_dir)
    migrate_audit_db(conn)  # ensure schema exists on this connection

    file_map = {
        "event": audit_dir / "events.jsonl",
        "failure": audit_dir / "failures.jsonl",
        "recommendation": audit_dir / "recommendations.jsonl",
        "phase_audit": audit_dir / "phase_audits.jsonl",
    }

    summary = {}
    total = {"imported": 0, "skipped": 0, "errors": 0}
    try:
        for record_type, path in file_map.items():
            r = import_jsonl_file(conn, path, record_type)
            summary[f"{record_type}s_imported"] = r["imported"]
            total["imported"] += r["imported"]
            total["skipped"] += r["skipped"]
            total["errors"] += r["errors"]
        summary.update(total)
    finally:
        conn.close()
    return summary


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def summarize_phase(conn: sqlite3.Connection, phase_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM v_phase_summary WHERE phase_id = ?", (phase_id,)
    ).fetchone()
    if not row:
        return None
    return dict(row)


def list_failures(conn: sqlite3.Connection, project_name: str | None = None,
                  phase_id: str | None = None) -> list[dict]:
    sql = "SELECT * FROM mcp_failure_log WHERE 1=1"
    params = []
    if project_name:
        sql += " AND project_name = ?"
        params.append(project_name)
    if phase_id:
        sql += " AND phase_id = ?"
        params.append(phase_id)
    sql += " ORDER BY created_at DESC"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def list_blocked_commits(conn: sqlite3.Connection,
                         project_name: str | None = None) -> list[dict]:
    sql = (
        "SELECT * FROM mcp_invocation_log "
        "WHERE event_type = 'commit_gate_blocked' AND result_status = 'blocked'"
    )
    params = []
    if project_name:
        sql += " AND project_name = ?"
        params.append(project_name)
    sql += " ORDER BY created_at DESC"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def list_rejected_recommendations(conn: sqlite3.Connection,
                                  project_name: str | None = None) -> list[dict]:
    sql = "SELECT * FROM mcp_recommendation_log WHERE decision = 'rejected'"
    params = []
    if project_name:
        sql += " AND project_name = ?"  # note: rec table doesn't have project_name in v1
    sql += " ORDER BY created_at DESC"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def tool_reliability_summary(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM v_tool_reliability ORDER BY failure_rate DESC"
    ).fetchall()]
