"""Persisted project quality-gate history."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from ..config import get_config
from ..tools.gates import GateOutcome, GateStatus

SCHEMA_VERSION = 1


class GateHistoryRecord(TypedDict):
    timestamp: str
    gate_name: str
    status: GateStatus
    issue_count: int
    auto_fixed: int


def _status(value: object) -> GateStatus:
    rendered = str(value)
    if rendered in {"PASS", "FAIL", "BLOCKED"}:
        return cast(GateStatus, rendered)
    return "FAIL"


@dataclass
class GateHistory:
    """Project-local SQLite gate history store."""

    db_path: Path

    @classmethod
    def for_active_project(cls) -> GateHistory:
        root = get_config().project_root
        # Canonical MCP state dir is ".kicad-mcp" (hyphen) everywhere else; keep
        # gate history in the same place rather than a second ".kicad_mcp" dir.
        state_dir = root / ".kicad-mcp"
        state_dir.mkdir(parents=True, exist_ok=True)
        history = cls(state_dir / "gate_history.db")
        history._init()
        return history

    def _init(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as db:
            with db:
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Gate history schema version {version} is newer than this server supports."
                    )
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gate_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        gate_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        issue_count INTEGER NOT NULL,
                        auto_fixed INTEGER NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def record(self, outcome: GateOutcome, auto_fixed: int = 0) -> None:
        issue_count = 0 if outcome.status == "PASS" else max(1, len(outcome.details))
        with closing(sqlite3.connect(self.db_path)) as db:
            with db:
                db.execute(
                    """
                    INSERT INTO gate_history
                        (timestamp, gate_name, status, issue_count, auto_fixed, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(UTC).isoformat(),
                        outcome.name,
                        outcome.status,
                        issue_count,
                        auto_fixed,
                        json.dumps(
                            {
                                "summary": outcome.summary,
                                "details": outcome.details,
                            },
                            sort_keys=True,
                        ),
                    ),
                )

    def trend(self, gate_name: str, last_n: int = 10) -> list[GateHistoryRecord]:
        with closing(sqlite3.connect(self.db_path)) as db:
            rows = db.execute(
                """
                SELECT timestamp, gate_name, status, issue_count, auto_fixed
                FROM gate_history
                WHERE gate_name = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (gate_name, last_n),
            ).fetchall()
        return [
            {
                "timestamp": str(timestamp),
                "gate_name": str(name),
                "status": _status(status),
                "issue_count": int(issue_count),
                "auto_fixed": int(auto_fixed),
            }
            for timestamp, name, status, issue_count, auto_fixed in rows
        ]

    def latest(self, last_n: int = 10) -> list[GateHistoryRecord]:
        with closing(sqlite3.connect(self.db_path)) as db:
            rows = db.execute(
                """
                SELECT timestamp, gate_name, status, issue_count, auto_fixed
                FROM gate_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (last_n,),
            ).fetchall()
        return [
            {
                "timestamp": str(timestamp),
                "gate_name": str(name),
                "status": _status(status),
                "issue_count": int(issue_count),
                "auto_fixed": int(auto_fixed),
            }
            for timestamp, name, status, issue_count, auto_fixed in rows
        ]

    def regression_check(self) -> list[str]:
        warnings: list[str] = []
        with closing(sqlite3.connect(self.db_path)) as db:
            names = [row[0] for row in db.execute("SELECT DISTINCT gate_name FROM gate_history")]
            for name in names:
                rows = db.execute(
                    """
                    SELECT status FROM gate_history
                    WHERE gate_name = ?
                    ORDER BY id DESC
                    LIMIT 2
                    """,
                    (name,),
                ).fetchall()
                if len(rows) == 2 and rows[0][0] != "PASS" and rows[1][0] == "PASS":
                    warnings.append(f"{name} regressed from PASS to {rows[0][0]}.")
        return warnings
