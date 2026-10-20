"""Stateful and model-based lifecycle testing using Hypothesis RuleBasedStateMachine."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
    run_state_machine_as_test,
)


class ProjectLifecycleStateMachine(RuleBasedStateMachine):
    """Models the KiCad MCP project lifecycle:
    open -> inspect -> modify -> checkpoint -> rollback -> re-validate.
    """

    def __init__(self) -> None:
        super().__init__()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.sch_path = self.root / "project.kicad_sch"
        self.pcb_path = self.root / "project.kicad_pcb"

        # Initialize mock schematic and pcb files
        self.initial_sch = '(kicad_sch (version 20240108) (generator "test"))\n'
        self.initial_pcb = '(kicad_pcb (version 20240108) (generator "test"))\n'
        self.sch_path.write_text(self.initial_sch, encoding="utf-8")
        self.pcb_path.write_text(self.initial_pcb, encoding="utf-8")

        # In-memory shadow state
        self.checkpoints: list[dict[str, str]] = []
        self.uncommitted_modifications: list[str] = []
        self.is_open = False
        self.validated = False

    def teardown(self) -> None:
        self.temp_dir.cleanup()

    @initialize()
    def init_open(self) -> None:
        self.is_open = True
        self.checkpoints.append(
            {
                "sch": self.sch_path.read_text(encoding="utf-8"),
                "pcb": self.pcb_path.read_text(encoding="utf-8"),
            }
        )

    @rule()
    def inspect(self) -> None:
        """Read-only inspection: must never alter file content."""
        if not self.is_open:
            return
        sch_content = self.sch_path.read_text(encoding="utf-8")
        pcb_content = self.pcb_path.read_text(encoding="utf-8")
        assert len(sch_content) > 0
        assert len(pcb_content) > 0

    @rule(
        component_name=st.text(
            min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        )
    )
    def stage_component(self, component_name: str) -> None:
        """Stage an uncommitted edit."""
        if not self.is_open:
            return
        self.uncommitted_modifications.append(component_name)
        self.validated = False

    @rule()
    def commit_changes(self) -> None:
        """Commit staged changes to file."""
        if not self.is_open or not self.uncommitted_modifications:
            return
        # Save previous state in checkpoint stack
        self.checkpoints.append(
            {
                "sch": self.sch_path.read_text(encoding="utf-8"),
                "pcb": self.pcb_path.read_text(encoding="utf-8"),
            }
        )
        # Apply edits
        current = self.sch_path.read_text(encoding="utf-8")
        additions = "\n".join(f'  (symbol (name "{c}"))' for c in self.uncommitted_modifications)
        new_content = current.rstrip(")\n") + "\n" + additions + "\n)\n"
        self.sch_path.write_text(new_content, encoding="utf-8")
        self.uncommitted_modifications.clear()

    @rule()
    def rollback(self) -> None:
        """Rollback to the most recent checkpoint."""
        if not self.is_open or not self.checkpoints:
            return
        latest = self.checkpoints.pop()
        self.sch_path.write_text(latest["sch"], encoding="utf-8")
        self.pcb_path.write_text(latest["pcb"], encoding="utf-8")
        self.uncommitted_modifications.clear()
        self.validated = False

    @rule()
    def validate(self) -> None:
        """Validate current state."""
        if not self.is_open:
            return
        # Validation checks basic syntax and non-empty content
        sch = self.sch_path.read_text(encoding="utf-8")
        pcb = self.pcb_path.read_text(encoding="utf-8")
        assert sch.startswith("(kicad_sch")
        assert pcb.startswith("(kicad_pcb")
        self.validated = True

    @invariant()
    def files_must_remain_syntactically_valid(self) -> None:
        """Files must always retain valid root s-expression tags."""
        sch = self.sch_path.read_text(encoding="utf-8")
        pcb = self.pcb_path.read_text(encoding="utf-8")
        assert "(kicad_sch" in sch, "Schematic lost root token!"
        assert "(kicad_pcb" in pcb, "PCB lost root token!"


def test_stateful_project_lifecycle() -> None:
    """Run model-based state machine verification of project lifecycle."""
    run_state_machine_as_test(ProjectLifecycleStateMachine)


# ---------------------------------------------------------------------------
# 2. Connection and Error Recovery State Machine
# ---------------------------------------------------------------------------


class ConnectionSessionStateMachine(RuleBasedStateMachine):
    """Models IPC/MCP connection states:
    DISCONNECTED -> CONNECTED -> DEGRADED -> RECONNECTED.
    """

    def __init__(self) -> None:
        super().__init__()
        self.connected = False
        self.degraded = False
        self.active_requests = 0
        self.completed_requests = 0
        self.failed_requests = 0

    @rule()
    def connect(self) -> None:
        self.connected = True
        self.degraded = False

    @rule()
    def disconnect(self) -> None:
        self.connected = False
        self.active_requests = 0

    @rule()
    def trigger_timeout(self) -> None:
        if self.connected:
            self.degraded = True
            self.failed_requests += self.active_requests
            self.active_requests = 0

    @rule()
    def retry_connection(self) -> None:
        if self.degraded:
            self.connected = True
            self.degraded = False

    @rule()
    def dispatch_request(self) -> None:
        if self.connected and not self.degraded:
            self.active_requests += 1
            self.completed_requests += 1
            self.active_requests -= 1
        else:
            self.failed_requests += 1

    @invariant()
    def requests_cannot_succeed_when_disconnected(self) -> None:
        if not self.connected:
            assert self.active_requests == 0


def test_stateful_connection_session() -> None:
    """Run model-based state machine verification of connection recovery."""
    run_state_machine_as_test(ConnectionSessionStateMachine)
