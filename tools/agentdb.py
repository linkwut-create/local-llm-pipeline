"""AgentDB — minimal SQLite database for structured pipeline facts.

Usage::

    py -3 tools/agentdb.py init
    py -3 tools/agentdb.py import-task <task_id>
    py -3 tools/agentdb.py task <task_id>
    py -3 tools/agentdb.py recent
    py -3 tools/agentdb.py report <task_id>
    py -3 tools/agentdb.py costs

The database lives at ``.local_llm_out/agentdb.sqlite``. All writes are
advisory — a DB write failure MUST NOT break task execution.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════
# Database path
# ═══════════════════════════════════════════════════════════════

def db_path() -> Path:
    override = os.environ.get("LOCAL_LLM_AGENTDB_PATH")
    if override:
        return Path(override)
    return Path(".local_llm_out/agentdb.sqlite")


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ═══════════════════════════════════════════════════════════════
# Schema
# ═══════════════════════════════════════════════════════════════

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'active',
    phase           TEXT NOT NULL DEFAULT 'planning',
    user_task       TEXT,
    project_root    TEXT,
    claude_session  TEXT,
    parent_task_id  TEXT,
    is_test_task    INTEGER NOT NULL DEFAULT 0,
    route_type      TEXT,
    risk_level      TEXT,
    privacy_status  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    completed_at    TEXT,
    FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS task_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS routes (
    task_id         TEXT PRIMARY KEY,
    route_type      TEXT NOT NULL,
    risk_level      TEXT,
    privacy_status  TEXT,
    delegability    TEXT,
    agreement       INTEGER,
    escalated       INTEGER,
    escalated_reason TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    tool            TEXT,
    size_bytes      INTEGER,
    sha256          TEXT,
    creator         TEXT,
    accepted        INTEGER,
    verified        INTEGER,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS model_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    model           TEXT NOT NULL,
    role            TEXT,
    round           TEXT,
    latency_sec     REAL,
    input_chars     INTEGER,
    output_chars    INTEGER,
    ok              INTEGER,
    error           TEXT,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS test_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    command         TEXT,
    passed          INTEGER,
    failed          INTEGER,
    skipped         INTEGER,
    duration_sec    REAL,
    log_artifact    TEXT,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    decision        TEXT NOT NULL,
    reason          TEXT,
    accepted_patch  TEXT,
    requires_tests  INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS costs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT,
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    estimated_cost  REAL NOT NULL DEFAULT 0.0,
    provider        TEXT,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT,
    tool_name       TEXT NOT NULL,
    input_summary   TEXT,
    output_size     INTEGER,
    ok              INTEGER,
    timestamp       TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_model_calls_task ON model_calls(task_id);
CREATE INDEX IF NOT EXISTS idx_decisions_task ON decisions(task_id);
CREATE INDEX IF NOT EXISTS idx_costs_task ON costs(task_id);
"""


# ═══════════════════════════════════════════════════════════════
# Init
# ═══════════════════════════════════════════════════════════════

def init_db() -> str:
    """Create or migrate the database schema. Idempotent."""
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        return f"AgentDB initialized at {db_path()}"
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# Upsert helpers (safe — never raise on DB error)
# ═══════════════════════════════════════════════════════════════

def _safe_execute(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    try:
        conn.execute(sql, params)
    except Exception:
        pass  # advisory only


def upsert_task(task_id: str, **fields) -> None:
    """Insert or update a task record from a session dict."""
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT task_id FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE tasks SET {sets} WHERE task_id=?",
                (*fields.values(), task_id),
            )
        else:
            keys = ["task_id"] + list(fields)
            placeholders = "?, " + ", ".join("?" for _ in fields)
            conn.execute(
                f"INSERT INTO tasks ({', '.join(keys)}) VALUES ({placeholders})",
                (task_id, *fields.values()),
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def insert_artifact(task_id: str, entry: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO artifacts
               (task_id, name, type, tool, size_bytes, sha256, creator,
                accepted, verified, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id, entry.get("name", ""), entry.get("type", "generic"),
                entry.get("tool", ""), entry.get("size_bytes", 0),
                entry.get("sha256", ""), entry.get("creator", ""),
                1 if entry.get("accepted") else (0 if entry.get("accepted") is False else None),
                1 if entry.get("verified") else (0 if entry.get("verified") is False else None),
                entry.get("created_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def insert_model_call(task_id: str, metrics: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO model_calls
               (task_id, model, role, round, latency_sec, input_chars,
                output_chars, ok, error, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id, metrics.get("model", "unknown"),
                metrics.get("role", ""), metrics.get("round", ""),
                metrics.get("latency_sec", 0), metrics.get("input_chars", 0),
                metrics.get("output_chars", 0), 1 if metrics.get("ok") else 0,
                metrics.get("error", ""),
                metrics.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def insert_test_run(task_id: str, test_data: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO test_runs
               (task_id, command, passed, failed, skipped, duration_sec,
                log_artifact, timestamp)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                task_id, test_data.get("command", ""),
                test_data.get("passed", 0), test_data.get("failed", 0),
                test_data.get("skipped", 0), test_data.get("duration_sec", 0.0),
                test_data.get("log_artifact", ""),
                test_data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def insert_decision(task_id: str, decision_data: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO decisions
               (task_id, decision, reason, accepted_patch, requires_tests, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                task_id, decision_data.get("decision", "unknown"),
                decision_data.get("reason", ""),
                decision_data.get("accepted_patch_id", ""),
                1 if decision_data.get("requires_more_tests") else 0,
                decision_data.get("created_at", datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def insert_cost(task_id: str | None, model: str, input_tokens: int,
                output_tokens: int, estimated_cost: float, provider: str = "") -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO costs
               (task_id, model, input_tokens, output_tokens, estimated_cost,
                provider, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (
                task_id, model, input_tokens, output_tokens, estimated_cost,
                provider, datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# Import from file-system tasks
# ═══════════════════════════════════════════════════════════════

def _tasks_base() -> Path:
    override = os.environ.get("LOCAL_LLM_TASKS_DIR")
    if override:
        return Path(override)
    return Path(".local_llm_out/tasks")


def import_task(task_id: str) -> str:
    """Import a task from file-system directories into the database."""
    task_dir = _tasks_base() / task_id
    if not task_dir.exists():
        return f"Task directory not found: {task_dir}"

    lines = []

    # Session
    session_file = task_dir / "session.json"
    if session_file.exists():
        try:
            s = json.loads(session_file.read_text(encoding="utf-8"))
            upsert_task(
                task_id,
                status=s.get("status", "active"),
                phase=s.get("phase", "planning"),
                user_task=(s.get("user_task", "") or "")[:500],
                project_root=s.get("project_root", ""),
                claude_session=s.get("claude_session_id", ""),
                parent_task_id=s.get("parent_task_id"),
                is_test_task=1 if s.get("is_test_task") else 0,
                created_at=s.get("created_at", ""),
                updated_at=s.get("updated_at", ""),
            )

            # Messages
            for msg in s.get("messages", []):
                conn = _connect()
                try:
                    conn.execute(
                        "INSERT INTO task_messages (task_id, role, content, timestamp) VALUES (?,?,?,?)",
                        (task_id, msg.get("role", "user"), (msg.get("content", "") or "")[:2000],
                         msg.get("timestamp", "")),
                    )
                    conn.commit()
                except Exception:
                    pass
                finally:
                    conn.close()
            lines.append(f"  session: {len(s.get('messages', []))} messages")
        except Exception as e:
            lines.append(f"  session: ERROR ({e})")

    # Route
    route_file = task_dir / "route.json"
    if route_file.exists():
        try:
            r = json.loads(route_file.read_text(encoding="utf-8"))
            conn = _connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO routes
                       (task_id, route_type, risk_level, privacy_status, delegability,
                        agreement, escalated, escalated_reason, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        task_id, r.get("recommended_route", "ask_user"),
                        r.get("risk_level", ""), r.get("privacy_status", ""),
                        r.get("delegability", ""),
                        1 if r.get("agreement") else 0,
                        1 if r.get("escalated") else 0,
                        r.get("escalated_reason", ""),
                        r.get("created_at", ""),
                    ),
                )
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()
            lines.append(f"  route: {r.get('recommended_route', '?')}")
        except Exception as e:
            lines.append(f"  route: ERROR ({e})")

    # Artifacts
    index_file = task_dir / "artifacts" / "artifact_index.json"
    if index_file.exists():
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
            for entry in index:
                insert_artifact(task_id, entry)
            lines.append(f"  artifacts: {len(index)} entries")
        except Exception as e:
            lines.append(f"  artifacts: ERROR ({e})")

    # Committee metrics
    metrics_file = task_dir / "committee" / "metrics.json"
    if metrics_file.exists():
        try:
            metrics_list = json.loads(metrics_file.read_text(encoding="utf-8"))
            for m in metrics_list:
                if isinstance(m, dict) and m.get("model"):
                    insert_model_call(task_id, m)
            lines.append(f"  model calls: {len(metrics_list)} entries")
        except Exception as e:
            lines.append(f"  model calls: ERROR ({e})")

    return f"Imported {task_id}:\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Queries
# ═══════════════════════════════════════════════════════════════

def query_task(task_id: str) -> dict | None:
    """Return structured task data from the database."""
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not task:
            return None
        result = dict(task)
        result["messages"] = [
            dict(m) for m in conn.execute(
                "SELECT * FROM task_messages WHERE task_id=? ORDER BY timestamp", (task_id,)
            ).fetchall()
        ]
        result["artifacts"] = [
            dict(a) for a in conn.execute(
                "SELECT * FROM artifacts WHERE task_id=? ORDER BY created_at", (task_id,)
            ).fetchall()
        ]
        result["model_calls"] = [
            dict(m) for m in conn.execute(
                "SELECT * FROM model_calls WHERE task_id=? ORDER BY timestamp", (task_id,)
            ).fetchall()
        ]
        result["test_runs"] = [
            dict(t) for t in conn.execute(
                "SELECT * FROM test_runs WHERE task_id=? ORDER BY timestamp", (task_id,)
            ).fetchall()
        ]
        result["decisions"] = [
            dict(d) for d in conn.execute(
                "SELECT * FROM decisions WHERE task_id=? ORDER BY created_at", (task_id,)
            ).fetchall()
        ]
        route = conn.execute("SELECT * FROM routes WHERE task_id=?", (task_id,)).fetchone()
        result["route"] = dict(route) if route else None
        return result
    except Exception:
        return None
    finally:
        conn.close()


def query_recent(limit: int = 10) -> list[dict]:
    """Return the most recent tasks."""
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT task_id, status, phase, route_type, risk_level, created_at "
            "FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def query_costs() -> dict:
    """Return cost summary."""
    conn = _connect()
    try:
        total_cost = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost), 0) FROM costs"
        ).fetchone()[0]
        by_model = conn.execute(
            "SELECT model, COUNT(*) as calls, SUM(input_tokens) as inp, "
            "SUM(output_tokens) as out, SUM(estimated_cost) as cost "
            "FROM costs GROUP BY model ORDER BY cost DESC"
        ).fetchall()
        by_task = conn.execute(
            "SELECT task_id, SUM(estimated_cost) as cost FROM costs "
            "WHERE task_id IS NOT NULL GROUP BY task_id ORDER BY cost DESC LIMIT 20"
        ).fetchall()
        return {
            "total_cost": round(total_cost, 6),
            "by_model": [
                {"model": m[0], "calls": m[1], "input_tokens": m[2],
                 "output_tokens": m[3], "cost": round(m[4], 6)}
                for m in by_model
            ],
            "by_task": [
                {"task_id": t[0], "cost": round(t[1], 6)} for t in by_task
            ],
        }
    except Exception:
        return {"total_cost": 0, "by_model": [], "by_task": []}
    finally:
        conn.close()


def query_report(task_id: str) -> str:
    """Generate a human-readable report from the database."""
    data = query_task(task_id)
    if data is None:
        return f"Task not found in database: {task_id}"

    lines = [
        f"# AgentDB Report: {task_id}",
        f"Status: {data.get('status', '?')}  |  Phase: {data.get('phase', '?')}",
        f"Route: {data.get('route_type', '?')}  |  Risk: {data.get('risk_level', '?')}",
        f"Created: {data.get('created_at', '?')}",
        "",
    ]

    route = data.get("route")
    if route:
        lines.append(f"Route decision: {route.get('route_type', '?')} "
                      f"(agreement={route.get('agreement')}, escalated={route.get('escalated')})")

    lines.append(f"\nMessages: {len(data.get('messages', []))}")
    lines.append(f"Artifacts: {len(data.get('artifacts', []))}")
    lines.append(f"Model calls: {len(data.get('model_calls', []))}")
    lines.append(f"Test runs: {len(data.get('test_runs', []))}")
    lines.append(f"Decisions: {len(data.get('decisions', []))}")

    decisions = data.get("decisions", [])
    if decisions:
        lines.append("\nDecisions:")
        for d in decisions:
            lines.append(f"  - {d.get('decision')}: {d.get('reason', '')[:100]}")

    # Cost
    conn = _connect()
    try:
        task_cost = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost), 0) FROM costs WHERE task_id=?",
            (task_id,)
        ).fetchone()[0]
        lines.append(f"\nTotal cost: ${round(task_cost, 6)}")
    except Exception:
        pass
    finally:
        conn.close()

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="AgentDB — minimal SQLite database for pipeline facts")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Create/migrate the database schema")

    imp = sub.add_parser("import-task", help="Import a task from file-system")
    imp.add_argument("task_id", help="Task ID to import")

    task = sub.add_parser("task", help="Show structured task data")
    task.add_argument("task_id", help="Task ID")
    task.add_argument("--json", action="store_true", help="Output as JSON")

    recent = sub.add_parser("recent", help="Show recent tasks")
    recent.add_argument("-n", "--limit", type=int, default=10)

    report = sub.add_parser("report", help="Generate task report")
    report.add_argument("task_id", help="Task ID")

    costs = sub.add_parser("costs", help="Show cost summary")
    costs.add_argument("--json", action="store_true")

    args = parser.parse_args()

    init_db()  # ensure schema exists

    try:
        if args.cmd == "init":
            print(init_db())
        elif args.cmd == "import-task":
            print(import_task(args.task_id))
        elif args.cmd == "task":
            data = query_task(args.task_id)
            if data is None:
                print(f"Task not found: {args.task_id}")
                return 1
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"Task: {data['task_id']}")
                print(f"Status: {data.get('status')} | Phase: {data.get('phase')}")
                print(f"Route: {data.get('route_type')} | Risk: {data.get('risk_level')}")
                print(f"Messages: {len(data.get('messages', []))}")
                print(f"Artifacts: {len(data.get('artifacts', []))}")
                print(f"Model calls: {len(data.get('model_calls', []))}")
                print(f"Test runs: {len(data.get('test_runs', []))}")
                print(f"Decisions: {len(data.get('decisions', []))}")
        elif args.cmd == "recent":
            tasks = query_recent(args.limit)
            if not tasks:
                print("No tasks in database.")
                return 0
            for t in tasks:
                status = (t.get('status') or '?')[:10]
                route = (t.get('route_type') or '?')[:20]
                created = (t.get('created_at') or '')[:19]
                print(f"  {t['task_id']}  {status:10s}  {route:20s}  {created}")
        elif args.cmd == "report":
            print(query_report(args.task_id))
        elif args.cmd == "costs":
            data = query_costs()
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(f"Total cost: ${data['total_cost']}")
                if data["by_model"]:
                    print("\nBy model:")
                    for m in data["by_model"]:
                        print(f"  {m['model']}: {m['calls']} calls, "
                              f"{m['input_tokens']}/{m['output_tokens']} tokens, "
                              f"${m['cost']}")
        else:
            parser.print_help()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
