"""Windows 10.0.7 qualification remains manual, authentic and isolated."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kicad-10-0-7-windows-qualification.yml"


def test_windows_stable_native_qualification_is_opt_in() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(raw)
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["native-windows-cli"]
    assert job["runs-on"] == "windows-2025"
    assert job["timeout-minutes"] == 65
    steps = job["steps"]
    assert steps[0]["with"]["persist-credentials"] is False
    assert all(
        "@" not in step.get("uses", "") or len(step["uses"].split("@", 1)[1]) == 40
        for step in steps
    )
    verify = next(step for step in steps if step["name"].startswith("Download and verify"))
    install = next(step for step in steps if step["name"].startswith("Install isolated"))
    native = next(step for step in steps if step["name"].startswith("Run full native"))
    assert "mirrors.mit.edu/kicad/windows/stable/kicad-10.0.7-x86_64.exe" in verify["run"]
    assert "Get-AuthenticodeSignature" in verify["run"]
    assert "signature.Status -ne 'Valid'" in verify["run"]
    assert "SignerCertificate.Subject -notmatch" in verify["run"]
    assert "/S" in install["run"] and "/currentuser" in install["run"]
    assert "RUNNER_TEMP" in install["run"] and "cannot fall back" in install["run"]
    assert "version -ne '10.0.7'" in install["run"]
    assert "--kicad-range 10.0.x" in native["run"]
    assert "source_sha -ne $env:SOURCE_REVISION" in native["run"]
    assert "match_count -ne 5" in native["run"]
    assert "false_pass_count" in native["run"]
    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 7
    assert steps[-1]["if"] == "always()"
    assert "Remove-Item" in steps[-1]["run"]
    assert "compatibility.yaml" not in raw
