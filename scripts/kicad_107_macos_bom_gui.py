"""Exact-KiCad macOS BOM GUI/Cancel acceptance in a disposable A/B project session.

The AX reads and writes below target ONLY fixtures created by kicad_107_bom_portable.
This is a native GUI test, not a CLI BOM export or an operator attestation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - fixed osascript and verified signed KiCad only
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from scripts import kicad_107_bom_portable as fixture

TARGET = "10.0.7"
REPLACEMENT = fixture.CANCELLED_NAME


def _osa(script: str, *, stage: str) -> str:
    # Commands use a fixed Apple-provided binary and fixture-scoped AX scripts.
    result = subprocess.run(  # nosec B603
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"macos-ax-{stage}-failed")
    return result.stdout.strip()


def _editor_windows() -> str:
    return _osa(
        'tell application "System Events" to tell process "eeschema" to get name of every window',
        stage="windows",
    )


def _validated_editor_binary(executable: Path, project: Path) -> Path:
    # The workflow verifies the official DMG's hash and code signature before
    # publishing KICAD_MAC_MOUNT and the selected eeschema path.
    mount_env = os.environ.get("KICAD_MAC_MOUNT")
    if not mount_env:
        raise RuntimeError("signed-kicad-mount-not-provided")
    mount = Path(mount_env).resolve(strict=True)
    binary = executable.resolve(strict=True)
    if (
        binary.name != "eeschema"
        or not binary.is_relative_to(mount)
        or not binary.is_file()
        or not os.access(binary, os.X_OK)
    ):
        raise RuntimeError("native-editor-outside-signed-mount")
    # Only fixture-owned, randomized temp projects can be launched.
    session_root = project.parent.parent
    session = session_root.name.removeprefix("kicad-107-bom-operator-")
    try:
        expected_root = fixture._session_workspace(session)
    except fixture.FixtureError as exc:
        raise RuntimeError("native-editor-untrusted-project") from exc
    if (
        session_root.is_symlink()
        or session_root.resolve(strict=True) != expected_root.resolve(strict=True)
        or project.parent.name not in fixture.PROJECTS
        or project.name != f"{project.parent.name}.kicad_sch"
        or not project.is_file()
        or project.is_symlink()
    ):
        raise RuntimeError("native-editor-untrusted-project")
    return binary


@contextmanager
def _editor(executable: Path, project: Path) -> Iterator[None]:
    binary = _validated_editor_binary(executable, project)
    # No shell, no external user path, and a verified executable in the signed DMG.
    # Codacy/Opengrep false positive: the executable and A/B fixture path are
    # confined by _validated_editor_binary; no shell or untrusted command is run.
    process = subprocess.Popen(  # nosemgrep  # nosec B603
        [str(binary), str(project)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        for _ in range(25):
            if process.poll() is not None:
                raise RuntimeError("native-editor-exited-early")
            time.sleep(1)
            try:
                windows = _editor_windows()
            except (RuntimeError, subprocess.TimeoutExpired):
                continue
            if "Schematic Editor" in windows:
                break
        else:
            raise RuntimeError("native-editor-window-unavailable")
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        time.sleep(1)


def _open_bom() -> None:
    _osa(
        'tell application "System Events" to tell process "eeschema" to set frontmost to true',
        stage="focus",
    )
    _osa(
        'tell application "System Events" to tell process "eeschema" '
        'to click (first menu item of menu 1 of menu bar item "Tools" '
        'of menu bar 1 whose name contains "Generate Bill of Materials")',
        stage="open-bom",
    )
    for _ in range(15):
        time.sleep(1)
        try:
            windows = _editor_windows()
        except (RuntimeError, subprocess.TimeoutExpired):
            continue
        if "Symbol Fields Table" in windows:
            return
    raise RuntimeError("native-bom-modal-unavailable")


def _read_output() -> str:
    script = """
    tell application "System Events"
      tell process "eeschema"
        set elementsFound to entire contents of window "Symbol Fields Table"
        repeat with elementFound in elementsFound
          try
            if role of elementFound is "AXTextField" then
              set fieldValue to value of elementFound as text
              if fieldValue starts with "BOM_SAVED_" or fieldValue starts with "BOM_CANCEL_" then
                return fieldValue
              end if
            end if
          end try
        end repeat
      end tell
    end tell
    return "NO_BOM_OUTPUT_FIELD"
    """
    output = _osa(script, stage="read-output")
    if not (output.startswith("BOM_SAVED_") or output == REPLACEMENT):
        raise RuntimeError("native-bom-output-field-unavailable")
    return output


def _refocus_bom_modal() -> None:
    # Only after a failed keyboard edit: raise the exact native BOM modal
    # before retrying its fixture-scoped field, never setting AXValue.
    _osa(
        'tell application "System Events" to tell process "eeschema" to set frontmost to true',
        stage="refocus-bom",
    )
    _osa(
        """
        tell application "System Events"
          tell process "eeschema"
            try
              perform action "AXRaise" of window "Symbol Fields Table"
            end try
          end tell
        end tell
        """,
        stage="raise-bom",
    )


def _edit_output(old_value: str) -> str:
    # The fixture-generated strings match a restrictive regex; no user input is interpolated.
    if not fixture.SAVED_NAME.fullmatch(old_value):
        raise RuntimeError("native-bom-saved-value-invalid")
    script = f"""
    tell application "System Events"
      tell process "eeschema"
        set fieldCount to 0
        set prefixCount to 0
        set elementsFound to entire contents of window "Symbol Fields Table"
        repeat with elementFound in elementsFound
          try
            if role of elementFound is "AXTextField" then
              set fieldCount to fieldCount + 1
              set theValue to value of elementFound as text
              if theValue starts with "BOM_SAVED_B_" then
                set prefixCount to prefixCount + 1
                set wasFocused to false
                try
                  set focused of elementFound to true
                  set wasFocused to focused of elementFound
                end try
                try
                  click elementFound
                  delay 0.2
                  set focused of elementFound to true
                  set wasFocused to focused of elementFound
                  keystroke "a" using {{command down}}
                  keystroke "{REPLACEMENT}"
                  key code 48
                  delay 0.4
                  if (value of elementFound as text) is "{REPLACEMENT}" then
                    return "{REPLACEMENT}"
                  end if
                end try
                return "FIELD_NOT_UPDATED|focused=" & (wasFocused as text)
              end if
            end if
          end try
        end repeat
      end tell
    end tell
    set resultText to "FIELD_NOT_FOUND|textFields=" & (fieldCount as text)
    return resultText & "|matchingPrefix=" & (prefixCount as text)
    """
    # Native focus can lag behind the BOM modal. Retry keyboard interaction
    # briefly, but never qualify the gate without exact readback of the edit.
    outcome = "FIELD_NOT_UPDATED|focused=false"
    for attempt in range(3):
        try:
            outcome = _osa(script, stage="edit-output")
        except (RuntimeError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
        else:
            if outcome == REPLACEMENT or not outcome.startswith("FIELD_NOT_UPDATED|"):
                return outcome
        if attempt != 2:
            # Recover the modal's foreground state rather than blindly
            # sending further keystrokes to a possibly unfocused field.
            _refocus_bom_modal()
            time.sleep(0.5)
    return outcome


def _cancel() -> None:
    cancel_script = """
    tell application "System Events"
      tell process "eeschema"
        try
          click button "Cancel" of window "Symbol Fields Table"
          return "CANCEL_CLICKED"
        end try
        set buttonsFound to 0
        set hasClose to false
        set hasOK to false
        repeat with elementFound in (entire contents of window "Symbol Fields Table")
          try
            if role of elementFound is "AXButton" then
              set buttonsFound to buttonsFound + 1
              set theName to ""
              set theDescription to ""
              set theTitle to ""
              try
                set theName to name of elementFound as text
              end try
              try
                set theDescription to description of elementFound as text
              end try
              try
                set theTitle to value of attribute "AXTitle" of elementFound as text
              end try
              if theName is "Close" or theDescription is "Close" then set hasClose to true
              if theName is "OK" or theDescription is "OK" then set hasOK to true
              if theName is "Cancel" or theDescription is "Cancel" or theTitle is "Cancel" then
                try
                  click elementFound
                  return "CANCEL_CLICKED"
                on error
                  return "CANCEL_CLICK_FAILED"
                end try
              end if
            end if
          end try
        end repeat
        set summaryResult to "CANCEL_CONTROL_NOT_FOUND|buttons=" & (buttonsFound as text)
        set summaryResult to summaryResult & "|close=" & (hasClose as text)
        return summaryResult & "|ok=" & (hasOK as text)
      end tell
    end tell
    """
    outcome = _osa(cancel_script, stage="cancel")
    if outcome != "CANCEL_CLICKED":
        # Only bounded button counts and whitelisted labels; never raw UI text.
        print("macOS BOM Cancel accessibility:", outcome[:110], flush=True)
        if outcome == "CANCEL_CLICK_FAILED":
            raise RuntimeError("native-bom-cancel-click-failed")
        raise RuntimeError("native-bom-cancel-control-unavailable")
    for _ in range(10):
        time.sleep(1)
        try:
            windows = _editor_windows()
        except (RuntimeError, subprocess.TimeoutExpired):
            continue
        if "Symbol Fields Table" not in windows:
            return
    raise RuntimeError("native-bom-cancel-did-not-close")


def _run(executable: Path) -> dict[str, object]:
    print("macOS BOM stage: prepare", flush=True)
    prepared = fixture.prepare()
    session = prepared["sessionId"]
    workspace = fixture._session_workspace(session)
    a_saved, b_saved = prepared["savedNames"]

    # Establish a baseline BEFORE touching BOM. KiCad may normalize project
    # settings on first GUI launch. Never re-arm after the actual UI test.
    for name in fixture.PROJECTS:
        print(f"macOS BOM stage: initialize-{name}", flush=True)
        project = workspace / name / f"{name}.kicad_sch"
        with _editor(executable, project):
            if "Schematic Editor" not in _editor_windows():
                raise RuntimeError("native-initialization-window-lost")
    print("macOS BOM stage: seal-baseline", flush=True)
    try:
        verified = fixture.verify(workspace)
    except fixture.FixtureError as exc:
        if str(exc) != "fixture-project-file-changed":
            raise
        fixture.arm_baseline(workspace)
        verified = fixture.verify(workspace)
    if not verified["integrityVerified"]:
        raise RuntimeError("pre-gui-baseline-unverified")

    print("macOS BOM stage: A-gui", flush=True)
    with _editor(executable, workspace / "PortableBom107A/PortableBom107A.kicad_sch"):
        _open_bom()
        observed_a = _read_output()
        if observed_a != a_saved:
            raise RuntimeError("cross-project-a-saved-filename-mismatch")
        _cancel()
    print("macOS BOM stage: B-gui", flush=True)
    with _editor(executable, workspace / "PortableBom107B/PortableBom107B.kicad_sch"):
        _open_bom()
        observed_b = _read_output()
        if observed_b != b_saved or observed_b == observed_a:
            raise RuntimeError("cross-project-b-saved-filename-mismatch")
        edited = _edit_output(observed_b)
        if edited != REPLACEMENT:
            print("macOS BOM edit accessibility:", edited[:100], flush=True)
            raise RuntimeError("native-bom-edit-control-not-updated")
        if _read_output() != REPLACEMENT:
            raise RuntimeError("native-bom-edit-value-not-retained")
        _cancel()
        _open_bom()
        reopened_b = _read_output()
        if reopened_b != b_saved:
            raise RuntimeError("native-bom-cancel-persisted-unexpectedly")
        _cancel()
    print("macOS BOM stage: verify-post-cancel", flush=True)
    integrity = fixture.verify(
        workspace,
        observed_a=observed_a,
        observed_b=observed_b,
        reopened_b=reopened_b,
        cancelled_b=True,
    )
    if (
        integrity["status"] != "operator-attested"
        or integrity.get("projectSha256UnchangedSinceBaseline") is False
        or not integrity["integrityVerified"]
        or not integrity["noBomFilesCreated"]
    ):
        raise RuntimeError("post-gui-integrity-rejected")

    return {
        "observedA": observed_a,
        "observedB": observed_b,
        "reopenedB": reopened_b,
        "cancelReverted": reopened_b == observed_b,
        "noBomFilesCreated": True,
        "projectIntegrityVerified": True,
        "nativeGuiObserved": True,
        "sessionInitialized": verified["integrityVerified"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source = os.environ.get("GITHUB_SHA", "")
    executable = Path(os.environ.get("KICAD_MAC_EESCHEMA", "/missing"))
    report: dict[str, object] = {
        "schemaVersion": "macos-kicad-107-bom-gui.v1",
        "sourceRevision": source,
        "version": TARGET,
        "status": "incomplete",
        "qualified": False,
    }
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    summary_path = output.parent / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["macosBomGuiQualified"] = False
    summary["verdict"] = "infrastructure-invalid"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    try:
        if source != summary["sourceRevision"] or summary.get("versionVerified") is not True:
            raise RuntimeError("source-or-signed-kicad-unverified")
        if summary.get("nativeExit") != 0 or summary.get("guiExit") != 0:
            raise RuntimeError("preceding-native-canary-incomplete")
        observations = _run(executable)
        report.update(observations, status="pass", qualified=True)
        summary["macosBomGuiQualified"] = True
        summary["verdict"] = "pass"
    except Exception as exc:
        report["status"] = "fail"
        reason = str(exc)
        report["reason"] = (
            reason if re.fullmatch(r"[a-z0-9][a-z0-9-]{2,100}", reason) else type(exc).__name__
        )
        summary["verdict"] = "fail"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("macOS BOM GUI qualification:", report["status"])
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
