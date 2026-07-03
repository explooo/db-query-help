from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from guardrails import GuardrailVerdict


def ensure_audit_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL,
            user_question TEXT NOT NULL,
            intent TEXT NOT NULL,
            generated_sql TEXT,
            guardrail_allowed INTEGER NOT NULL,
            guardrail_reason TEXT NOT NULL,
            matched_tables TEXT,
            result_preview TEXT
        )
        """
    )
    connection.commit()


def log_event(
    connection: sqlite3.Connection,
    *,
    role: str,
    user_question: str,
    intent: str,
    generated_sql: str | None,
    verdict: GuardrailVerdict,
    result_preview: list[dict[str, Any]] | None = None,
) -> None:
    ensure_audit_table(connection)
    connection.execute(
        """
        INSERT INTO audit_log (
            created_at, role, user_question, intent, generated_sql,
            guardrail_allowed, guardrail_reason, matched_tables, result_preview
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            role,
            user_question,
            intent,
            generated_sql,
            1 if verdict.allowed else 0,
            verdict.reason,
            json.dumps(verdict.matched_tables),
            json.dumps(result_preview or []),
        ),
    )
    connection.commit()


def load_recent_events(connection: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    ensure_audit_table(connection)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT audit_id, created_at, role, user_question, intent, generated_sql,
               guardrail_allowed, guardrail_reason, matched_tables, result_preview
        FROM audit_log
        ORDER BY audit_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
