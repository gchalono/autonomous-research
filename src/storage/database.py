"""SQLite persistence for projects, events, agent outputs and tool calls.

Design notes:
- One row per project; every state change is an appended event row, so the
  full transition history is reconstructable.
- Agent outputs are stored keyed by (project, step_key). The orchestrator
  reuses a stored output on resume instead of re-invoking the agent, which
  is what makes resume idempotent and prevents duplicate LLM spend.
- All writes that must move together use a single transaction.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            objective TEXT NOT NULL,
            state TEXT NOT NULL,
            budget_usd REAL NOT NULL,
            spent_usd REAL NOT NULL DEFAULT 0,
            prompt_revisions INTEGER NOT NULL DEFAULT 0,
            corrections INTEGER NOT NULL DEFAULT 0,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT NOT NULL,
            event TEXT NOT NULL,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_outputs (
            project_id TEXT NOT NULL,
            step_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, step_key)
        );
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            tool TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            ok INTEGER NOT NULL,
            output_preview TEXT,
            cost_usd REAL NOT NULL DEFAULT 0,
            ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS issues (
            project_id TEXT NOT NULL,
            issue_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (project_id, issue_id)
        );
        """)
        self.conn.commit()

    # ------------------------------------------------------------ projects
    def create_project(self, project_id: str, objective: str, budget_usd: float) -> None:
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO projects (id, objective, state, budget_usd, created_at, updated_at)"
            " VALUES (?, ?, 'CREATED', ?, ?, ?)",
            (project_id, objective, budget_usd, now, now))
        self.conn.execute(
            "INSERT INTO events (project_id, ts, from_state, to_state, event, detail)"
            " VALUES (?, ?, NULL, 'CREATED', 'create', ?)",
            (project_id, now, objective))
        self.conn.commit()

    def get_project(self, project_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_project_spend(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT id, spent_usd FROM projects")]

    def transition(self, project_id: str, from_state: str, to_state: str,
                   event: str, detail: str = "", counters: dict | None = None) -> None:
        now = _now_iso()
        counters = counters or {}
        if set(counters) - {"prompt_revisions", "corrections"}:
            raise ValueError("unsupported transition counters")
        assignments = "".join(f", {k} = ?" for k in counters)
        with self.conn:
            cur = self.conn.execute(
                "UPDATE projects SET state = ?, updated_at = ?" + assignments
                + " WHERE id = ? AND state = ?",
                (to_state, now, *counters.values(), project_id, from_state))
            if cur.rowcount != 1:
                raise RuntimeError("project state changed before transition")
            self.conn.execute(
                "INSERT INTO events (project_id, ts, from_state, to_state, event, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, now, from_state, to_state, event, detail))

    def update_counters(self, project_id: str, **fields: Any) -> None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE projects SET {assignments}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now_iso(), project_id))
        self.conn.commit()

    def add_spend(self, project_id: str, amount_usd: float) -> float:
        """Atomically add spend; returns the new total."""
        cur = self.conn.execute(
            "UPDATE projects SET spent_usd = spent_usd + ?, updated_at = ?"
            " WHERE id = ? RETURNING spent_usd",
            (amount_usd, _now_iso(), project_id))
        row = cur.fetchone()
        self.conn.commit()
        return float(row[0]) if row else 0.0

    def request_cancel(self, project_id: str) -> None:
        self.conn.execute(
            "UPDATE projects SET cancel_requested = 1, updated_at = ? WHERE id = ?",
            (_now_iso(), project_id))
        self.conn.commit()

    # ------------------------------------------------------- agent outputs
    def save_output(self, project_id: str, step_key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO agent_outputs (project_id, step_key, payload_json, created_at)"
            " VALUES (?, ?, ?, ?)",
            (project_id, step_key, json.dumps(payload), _now_iso()))
        self.conn.commit()

    def load_output(self, project_id: str, step_key: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT payload_json FROM agent_outputs WHERE project_id = ? AND step_key = ?",
            (project_id, step_key)).fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------ tooling
    def record_tool_call(self, project_id: str, tool: str, arguments: dict,
                         ok: bool, output_preview: str, cost_usd: float = 0.0,
                         *, result_key: str | None = None,
                         result_payload: dict | None = None) -> None:
        # A completed native tool, its replayable result and project charge
        # must survive together, even if the transcript checkpoint never lands.
        with self.conn:
            self.conn.execute(
                "INSERT INTO tool_calls (project_id, tool, arguments_json, ok, output_preview, cost_usd, ts)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, tool, json.dumps(arguments), 1 if ok else 0,
                 output_preview[:2000], cost_usd, _now_iso()))
            self.conn.execute(
                "UPDATE projects SET spent_usd = spent_usd + ?, updated_at = ? WHERE id = ?",
                (cost_usd, _now_iso(), project_id))
            if result_key is not None:
                self.conn.execute(
                    "INSERT INTO agent_outputs (project_id, step_key, payload_json, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (project_id, result_key, json.dumps(result_payload), _now_iso()))

    def list_tool_calls(self, project_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tool_calls WHERE project_id = ? ORDER BY id",
            (project_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_events(self, project_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE project_id = ? ORDER BY id",
            (project_id,)).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------- issues
    def upsert_issue(self, project_id: str, issue: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO issues (project_id, issue_id, severity, status, payload_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (project_id, issue["id"], issue["severity"], issue["status"],
             json.dumps(issue)))
        self.conn.commit()

    def list_issues(self, project_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload_json FROM issues WHERE project_id = ? ORDER BY issue_id",
            (project_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        self.conn.close()
