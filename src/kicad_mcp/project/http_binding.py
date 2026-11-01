"""Single-project binding for shared HTTP MCP processes.

Dedicated local stdio clients already have independent processes. A shared
HTTP process cannot safely switch its global KiCad state between clients.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..config import KiCadMCPConfig

PROJECT_SELECTION_TOOLS = frozenset({"kicad_set_project", "kicad_create_new_project"})
PROJECT_CONFIG_FIELDS = frozenset(
    {"project_dir", "project_file", "pcb_file", "sch_file", "output_dir"}
)


class HttpProjectBinding:
    """Pin the project of a shared HTTP engine at its first tool call."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bound = False
        self._paths: tuple[Path | None, ...] = ()

    @property
    def is_bound(self) -> bool:
        with self._lock:
            return self._bound

    def check_and_pin(self, config: KiCadMCPConfig) -> bool:
        current = tuple(getattr(config, key) for key in sorted(PROJECT_CONFIG_FIELDS))
        with self._lock:
            if not self._bound:
                self._paths = current
                self._bound = True
            return self._paths == current

    @contextmanager
    def configuration_update(self) -> Iterator[bool]:
        """Serialize dashboard changes with the first HTTP project binding."""
        with self._lock:
            yield not self._bound
