"""Read-only binding availability gate for KiCad 10.0.7 IPC additions.

This does not connect to a GUI or qualify the behavior of IPC operations.
"""

from __future__ import annotations

import argparse
import importlib
import json
from importlib import metadata
from types import ModuleType
from typing import Any

from packaging.version import InvalidVersion, Version

TARGET_KICAD = "10.0.7"
MINIMUM_BINDING = Version("0.9.0")
REQUIRED_BOARD_METHODS = (
    "get_tables",
    "get_reference_points",
    "get_embedded_files",
    "add_embedded_files",
    "set_embedded_files",
)
REQUIRED_BOARD_TYPES = ("Table", "TableCell", "ReferencePoint")


def inspect_bindings(
    *,
    binding_version: str | None,
    board_class: type | None,
    board_types: ModuleType | object | None,
) -> dict[str, Any]:
    """Return a bounded, deterministic feature check, not a live IPC verdict."""
    version_ok = False
    if binding_version is not None:
        try:
            parsed_version = Version(binding_version)
        except InvalidVersion:
            parsed_version = None
        if parsed_version is not None:
            version_ok = (
                parsed_version >= MINIMUM_BINDING
                and not parsed_version.is_prerelease
                and not parsed_version.is_devrelease
            )

    missing_methods = [
        name
        for name in REQUIRED_BOARD_METHODS
        if board_class is None or not callable(getattr(board_class, name, None))
    ]
    missing_types = [
        name
        for name in REQUIRED_BOARD_TYPES
        if board_types is None
        or not isinstance(getattr(board_types, name, None), type)
        or getattr(board_types, name, None) is object
    ]
    ready = version_ok and not missing_methods and not missing_types
    return {
        "schemaVersion": "kicad-107-ipc-binding-availability.v1",
        "targetKiCad": TARGET_KICAD,
        "minimumPublishedBinding": str(MINIMUM_BINDING),
        "installedBinding": binding_version,
        "stableVersionSatisfied": version_ok,
        "missingBoardMethods": missing_methods,
        "missingBoardTypes": missing_types,
        "bindingReadyForNativeGuiTests": ready,
        "nativeGuiQualified": False,
        "status": "binding-ready-only" if ready else "blocked",
    }


def inspect_installed() -> dict[str, Any]:
    """Read the installed package; do not download dependencies or start KiCad."""
    try:
        binding_version = metadata.version("kicad-python")
    except metadata.PackageNotFoundError:
        binding_version = None
    try:
        board_class = importlib.import_module("kipy.board").Board
        board_types = importlib.import_module("kipy.board_types")
    except (ImportError, AttributeError):
        board_class = None
        board_types = None
    return inspect_bindings(
        binding_version=binding_version,
        board_class=board_class,
        board_types=board_types,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return a nonzero exit code unless stable binding types are available",
    )
    args = parser.parse_args(argv)
    report = inspect_installed()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if args.require_ready and not report["bindingReadyForNativeGuiTests"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
