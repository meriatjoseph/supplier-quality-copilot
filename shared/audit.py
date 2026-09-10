"""
Append-only audit log, shared across all services via a SQLite file on a
shared Docker volume. Every dispatch, response, approval, and execution is
written here, keyed by correlation_id, so a request is traceable end-to-end.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Optional

AUDIT_DB_PATH = os.environ.get("AUDIT_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "audit.db"))

_lock = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    incident_id TEXT,
    task_id TEXT,
    sender TEXT,
    recipient TEXT,
    action TEXT,
    event_type TEXT NOT NULL,
    status TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_incident ON audit_log(incident_id);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(AUDIT_DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_audit_db() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def log_event(
    correlation_id: str,
    event_type: str,
    incident_id: Optional[str] = None,
    task_id: Optional[str] = None,
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """event_type examples: dispatch, response, health_check, approval, rejection, execution, error"""
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO audit_log
                   (timestamp, correlation_id, incident_id, task_id, sender, recipient, action, event_type, status, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts, correlation_id, incident_id, task_id, sender, recipient, action,
                    event_type, status, json.dumps(detail or {}, default=str),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_events(correlation_id: Optional[str] = None, incident_id: Optional[str] = None, limit: int = 500) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        try:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM audit_log"
            clauses = []
            params: list[Any] = []
            if correlation_id:
                clauses.append("correlation_id = ?")
                params.append(correlation_id)
            if incident_id:
                clauses.append("incident_id = ?")
                params.append(incident_id)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                out.append(d)
            return out
        finally:
            conn.close()


init_audit_db()
