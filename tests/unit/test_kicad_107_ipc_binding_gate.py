"""KiCad 10.0.7 IPC additions cannot be claimed without published wrappers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.kicad_107_ipc_binding_gate as gate


class CompleteBoard:
    def get_tables(self) -> None: ...
    def get_reference_points(self) -> None: ...
    def get_embedded_files(self) -> None: ...
    def add_embedded_files(self) -> None: ...
    def set_embedded_files(self) -> None: ...


FULL_TYPES = SimpleNamespace(
    Table=type("Table", (), {}),
    TableCell=type("TableCell", (), {}),
    ReferencePoint=type("ReferencePoint", (), {}),
)


@pytest.mark.parametrize(
    "version", [None, "0.7.1", "0.8.0", "0.9.0rc1", "0.9.0.dev1", "unparsable"]
)
def test_unpublished_or_unstable_binding_versions_fail_closed(version: str | None) -> None:
    report = gate.inspect_bindings(
        binding_version=version, board_class=CompleteBoard, board_types=FULL_TYPES
    )
    assert report["stableVersionSatisfied"] is False
    assert report["bindingReadyForNativeGuiTests"] is False
    assert report["nativeGuiQualified"] is False
    assert report["status"] == "blocked"


def test_matching_version_but_missing_real_methods_is_still_blocked() -> None:
    class IncompleteBoard:
        def get_tables(self) -> None: ...

    report = gate.inspect_bindings(
        binding_version="0.9.0", board_class=IncompleteBoard, board_types=FULL_TYPES
    )
    assert "get_reference_points" in report["missingBoardMethods"]
    assert "add_embedded_files" in report["missingBoardMethods"]
    assert report["bindingReadyForNativeGuiTests"] is False


def test_matching_version_but_missing_type_wrapper_is_blocked() -> None:
    report = gate.inspect_bindings(
        binding_version="0.9.0",
        board_class=CompleteBoard,
        board_types=SimpleNamespace(Table=object),
    )
    assert report["missingBoardTypes"] == list(gate.REQUIRED_BOARD_TYPES)
    assert report["bindingReadyForNativeGuiTests"] is False


def test_stable_binding_with_all_wrappers_only_grants_eligibility_for_native_tests() -> None:
    report = gate.inspect_bindings(
        binding_version="0.9.1", board_class=CompleteBoard, board_types=FULL_TYPES
    )
    assert report["bindingReadyForNativeGuiTests"] is True
    assert report["status"] == "binding-ready-only"
    assert report["nativeGuiQualified"] is False
    assert report["missingBoardMethods"] == []
    assert report["missingBoardTypes"] == []


def test_missing_distribution_is_blocked_without_paths_or_untrusted_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_dist(_name: str) -> str:
        raise gate.metadata.PackageNotFoundError("kicad-python")

    def no_import(_name: str) -> object:
        raise ImportError("private/path/details")

    monkeypatch.setattr(gate.metadata, "version", no_dist)
    monkeypatch.setattr(gate.importlib, "import_module", no_import)
    report = gate.inspect_installed()
    assert report["installedBinding"] is None
    assert report["status"] == "blocked"
    assert "private/path" not in json.dumps(report)


def test_require_ready_is_fail_closed_but_audit_mode_reports_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        gate,
        "inspect_installed",
        lambda: gate.inspect_bindings(
            binding_version="0.7.1", board_class=CompleteBoard, board_types=FULL_TYPES
        ),
    )
    assert gate.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "blocked"
    assert report["targetKiCad"] == "10.0.7"
    assert report["nativeGuiQualified"] is False
    assert gate.main(["--require-ready"]) == 2


def test_real_installed_package_cannot_fake_native_gui_acceptance() -> None:
    report = gate.inspect_installed()
    assert report["schemaVersion"] == "kicad-107-ipc-binding-availability.v1"
    assert report["nativeGuiQualified"] is False
    assert set(report["missingBoardMethods"]).issubset(gate.REQUIRED_BOARD_METHODS)
    assert set(report["missingBoardTypes"]).issubset(gate.REQUIRED_BOARD_TYPES)
    if report["installedBinding"] == "0.7.1":
        assert report["bindingReadyForNativeGuiTests"] is False
        assert "get_tables" in report["missingBoardMethods"]
