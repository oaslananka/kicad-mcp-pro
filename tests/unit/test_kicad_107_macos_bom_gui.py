"""macOS GUI gate must only pass exact native AX observations and integrity."""

import json
from pathlib import Path

import pytest

from scripts import kicad_107_macos_bom_gui as gui


def test_missing_live_ax_output_is_not_qualified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui, "_osa", lambda _script, **_opts: "NO_BOM_OUTPUT_FIELD")
    with pytest.raises(RuntimeError, match="native-bom-output-field-unavailable"):
        gui._read_output()


def test_untrusted_edit_field_is_rejected_before_automation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gui, "_osa", lambda _script, **_opts: pytest.fail("must not invoke GUI for invalid input")
    )
    with pytest.raises(RuntimeError, match="native-bom-saved-value-invalid"):
        gui._edit_output("../../confidential")


def test_mac_bom_gate_fails_closed_on_unverified_native(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "7" * 40)
    (tmp_path / "summary.json").write_text(
        json.dumps({"sourceRevision": "8" * 40, "versionVerified": True, "verdict": "pass"})
    )
    output = tmp_path / "bom-gui.json"
    assert gui.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert report["status"] == "fail"
    assert report["qualified"] is False
    assert summary["verdict"] == "fail"
    assert summary["macosBomGuiQualified"] is False


def test_mac_bom_gate_only_qualifies_after_native_observations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "7" * 40)
    (tmp_path / "summary.json").write_text(
        json.dumps(
            {
                "sourceRevision": "7" * 40,
                "versionVerified": True,
                "nativeExit": 0,
                "guiExit": 0,
                "verdict": "pass",
            }
        )
    )
    monkeypatch.setattr(
        gui,
        "_run",
        lambda _executable: {
            "observedA": "BOM_SAVED_A_aaaaaaaaaaaa.csv",
            "observedB": "BOM_SAVED_B_aaaaaaaaaaaa.csv",
            "reopenedB": "BOM_SAVED_B_aaaaaaaaaaaa.csv",
            "cancelReverted": True,
            "noBomFilesCreated": True,
            "projectIntegrityVerified": True,
            "nativeGuiObserved": True,
        },
    )
    output = tmp_path / "bom-gui.json"
    assert gui.main(["--output", str(output)]) == 0
    report = json.loads(output.read_text())
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert report["qualified"] is True
    assert report["status"] == "pass"
    assert summary["macosBomGuiQualified"] is True
    assert summary["verdict"] == "pass"


def test_all_macos_ax_helpers_specify_safe_diagnostic_stage() -> None:
    import ast

    source = Path(gui.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_osa"
    ]
    assert len(calls) == 8
    assert all(any(k.arg == "stage" for k in call.keywords) for call in calls)


def test_bom_edit_is_real_keyboard_interaction_not_ax_value_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def check(script: str, *, stage: str) -> str:
        assert stage == "edit-output"
        observed.append(script)
        return gui.REPLACEMENT

    monkeypatch.setattr(gui, "_osa", check)
    assert gui._edit_output("BOM_SAVED_B_aaaaaaaaaaaa.csv") == gui.REPLACEMENT
    assert len(observed) == 1
    assert "click elementFound" in observed[0]
    assert 'keystroke "a" using {command down}' in observed[0]
    assert 'keystroke "BOM_CANCEL_NOT_PERSISTED_107.csv"' in observed[0]
    assert "set value of elementFound" not in observed[0]
    assert "set focused of elementFound to true" in observed[0]
    assert 'if (value of elementFound as text) is "BOM_CANCEL_NOT_PERSISTED_107.csv"' in observed[0]
    assert "FIELD_NOT_UPDATED|focused=" in observed[0]


def test_bom_keyboard_edit_retries_transient_modal_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []
    responses = iter(["FIELD_NOT_UPDATED|focused=false", gui.REPLACEMENT])

    def fake(script: str, *, stage: str) -> str:
        if stage == "edit-output":
            observed.append(script)
            return next(responses)
        assert stage in {"refocus-bom", "raise-bom"}
        return ""

    monkeypatch.setattr(gui, "_osa", fake)
    monkeypatch.setattr(gui.time, "sleep", lambda _seconds: None)
    assert gui._edit_output("BOM_SAVED_B_aaaaaaaaaaaa.csv") == gui.REPLACEMENT
    assert len(observed) == 2
    assert "set frontmost to true" not in observed[0]
    assert 'keystroke "BOM_CANCEL_NOT_PERSISTED_107.csv"' in observed[0]


def test_bom_keyboard_edit_fails_closed_when_focus_never_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    def no_focus(script: str, *, stage: str) -> str:
        if stage == "edit-output":
            attempts.append(script)
            return "FIELD_NOT_UPDATED|focused=false"
        assert stage in {"refocus-bom", "raise-bom"}
        return ""

    monkeypatch.setattr(gui, "_osa", no_focus)
    monkeypatch.setattr(gui.time, "sleep", lambda _seconds: None)
    assert gui._edit_output("BOM_SAVED_B_aaaaaaaaaaaa.csv") == "FIELD_NOT_UPDATED|focused=false"
    assert len(attempts) == 3


def test_cancel_uses_explicit_native_cancel_button_not_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def command(script: str, *, stage: str) -> str:
        seen.append(script)
        if stage == "cancel":
            return "CANCEL_CLICKED"
        if stage == "windows":
            return "PortableBom107B - Schematic Editor"
        pytest.fail("unexpected AX stage")

    monkeypatch.setattr(gui, "_osa", command)
    monkeypatch.setattr(gui.time, "sleep", lambda _seconds: None)
    gui._cancel()
    assert len(seen) == 2
    assert 'role of elementFound is "AXButton"' in seen[0]
    assert 'theName is "Cancel"' in seen[0]
    assert 'theDescription is "Cancel"' in seen[0]
    assert 'button "Cancel" of window "Symbol Fields Table"' in seen[0]
    assert "key code 53" not in seen[0]


def test_cancel_fails_closed_when_named_button_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gui, "_osa", lambda _script, *, stage: "CANCEL_CONTROL_NOT_FOUND")
    with pytest.raises(RuntimeError, match="native-bom-cancel-control-unavailable"):
        gui._cancel()


def test_bom_edit_targets_unique_project_b_sentinel_not_variable_ax_equality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts: list[str] = []

    def fake(script: str, *, stage: str) -> str:
        scripts.append(script)
        return gui.REPLACEMENT

    monkeypatch.setattr(gui, "_osa", fake)
    assert gui._edit_output("BOM_SAVED_B_aaaaaaaaaaaa.csv") == gui.REPLACEMENT
    assert len(scripts) == 1
    assert 'theValue starts with "BOM_SAVED_B_"' in scripts[0]
    assert "set frontmost to true" not in scripts[0]
    assert "FIELD_NOT_FOUND|textFields=" in scripts[0]


def test_macos_editor_refuses_binary_outside_signed_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "signed-mount"
    root.mkdir()
    outside = tmp_path / "eeschema"
    outside.write_text("not a KiCad binary")
    outside.chmod(0o755)
    monkeypatch.setenv("KICAD_MAC_MOUNT", str(root))
    with pytest.raises(RuntimeError, match="native-editor-outside-signed-mount"):
        with gui._editor(outside, tmp_path / "fixture.kicad_sch"):
            pass


def test_macos_editor_refuses_arbitrary_project_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "signed-mount"
    root.mkdir()
    binary = root / "eeschema"
    binary.write_text("mock trusted executable")
    binary.chmod(0o755)
    project = tmp_path / "PortableBom107A" / "PortableBom107A.kicad_sch"
    project.parent.mkdir()
    project.write_text("dummy fixture")
    monkeypatch.setenv("KICAD_MAC_MOUNT", str(root))
    with pytest.raises(RuntimeError, match="native-editor-untrusted-project"):
        with gui._editor(binary, project):
            pass


def test_bom_edit_uses_same_materialized_ax_collection_as_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts: list[str] = []

    def fake(script: str, *, stage: str) -> str:
        assert stage == "edit-output"
        scripts.append(script)
        return gui.REPLACEMENT

    monkeypatch.setattr(gui, "_osa", fake)
    gui._edit_output("BOM_SAVED_B_aaaaaaaaaaaa.csv")
    assert len(scripts) == 1
    assert 'set elementsFound to entire contents of window "Symbol Fields Table"' in scripts[0]
    assert "repeat with elementFound in elementsFound" in scripts[0]


def test_bom_modal_retries_transient_ax_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = iter(
        [
            RuntimeError("transient"),
            "No modal yet",
            "Symbol Fields Table",
        ]
    )
    seen: list[str] = []

    def fake(_script: str, *, stage: str) -> str:
        seen.append(stage)
        if stage == "windows":
            nxt = next(queries)
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt
        return ""

    monkeypatch.setattr(gui, "_osa", fake)
    monkeypatch.setattr(gui.time, "sleep", lambda _seconds: None)
    gui._open_bom()
    assert seen.count("windows") == 3


def test_bom_cancel_retries_transient_ax_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = iter(
        [gui.subprocess.TimeoutExpired("osascript", 1), "Symbol Fields Table", "Schematic Editor"]
    )
    seen: list[str] = []

    def fake(_script: str, *, stage: str) -> str:
        seen.append(stage)
        if stage == "cancel":
            return "CANCEL_CLICKED"
        nxt = next(queries)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    monkeypatch.setattr(gui, "_osa", fake)
    monkeypatch.setattr(gui.time, "sleep", lambda _seconds: None)
    gui._cancel()
    assert seen.count("windows") == 3
