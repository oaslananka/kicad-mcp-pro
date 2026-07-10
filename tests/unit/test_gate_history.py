from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import kicad_mcp.resources.gate_history as gate_history_module
from kicad_mcp.resources.gate_history import GateHistory
from kicad_mcp.tools.validation import GateOutcome


def test_gate_history_records_trends_and_regressions(tmp_path: Path) -> None:
    history = GateHistory(tmp_path / "gate_history.db")
    history._init()

    history.record(GateOutcome("Schematic", "PASS", "ok"))
    history.record(GateOutcome("Schematic", "FAIL", "bad", ["wire missing"]))

    trend = history.trend("Schematic")

    assert trend[0]["status"] == "FAIL"
    assert trend[0]["issue_count"] == 1
    assert history.regression_check() == ["Schematic regressed from PASS to FAIL."]


def test_gate_history_schema_migration_sets_user_version(tmp_path: Path) -> None:
    db_path = tmp_path / "gate_history.db"
    with closing(sqlite3.connect(db_path)) as db:
        with db:
            db.execute(
                """
                CREATE TABLE gate_history (
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
            db.execute("PRAGMA user_version = 0")

    history = GateHistory(db_path)
    history._init()

    with closing(sqlite3.connect(db_path)) as db:
        user_version = db.execute("PRAGMA user_version").fetchone()[0]

    assert user_version == 1


def test_for_active_project_uses_canonical_state_dir(tmp_path: Path, monkeypatch) -> None:
    """Gate history must live in the canonical ".kicad-mcp" state dir (hyphen),
    not a second ".kicad_mcp" directory that diverges from the rest of the tools.
    """

    class _Cfg:
        project_root = tmp_path

    monkeypatch.setattr(gate_history_module, "get_config", lambda: _Cfg())

    history = GateHistory.for_active_project()

    assert history.db_path == tmp_path / ".kicad-mcp" / "gate_history.db"
    assert (tmp_path / ".kicad-mcp").is_dir()
    assert not (tmp_path / ".kicad_mcp").exists()
