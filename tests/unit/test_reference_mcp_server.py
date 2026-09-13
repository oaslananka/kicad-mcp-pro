from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _reset_reference_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from kicad_mcp.config import reset_config

    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "manufacturing")
    monkeypatch.setenv("KICAD_MCP_FILTER_RUNTIME_TOOLS", "false")
    reset_config()


def test_reference_manufacturing_server_has_exact_non_release_surface(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.evals.reference_mcp_server import (
        REFERENCE_MANUFACTURING_TOOL_NAMES,
        build_reference_manufacturing_server,
    )

    _reset_reference_env(monkeypatch, tmp_path)
    server = build_reference_manufacturing_server(defer_registration=False)
    names = {tool.name for tool in server.list_tools_sync()}

    assert names == set(REFERENCE_MANUFACTURING_TOOL_NAMES)
    assert "reference_generate_manufacturing_snapshot" in names
    assert "reference_compare_manufacturing_snapshots" in names
    assert "export_manufacturing_package" not in names
    assert "export_gerber" not in names
    assert "export_drill" not in names
    assert "export_bom" not in names


@pytest.mark.anyio
async def test_execution_allowlist_rejects_hidden_direct_tool_call() -> None:
    from kicad_mcp.operating_modes import OperatingMode
    from kicad_mcp.server import KiCadFastMCP

    server = KiCadFastMCP(name="reference-execution-boundary")
    server.operating_mode = OperatingMode.MANUFACTURING
    server.execution_tool_names = {"allowed_tool"}
    hidden_called = False

    @server.tool(name="allowed_tool")
    def allowed_tool() -> str:
        return "allowed"

    @server.tool(name="hidden_tool")
    def hidden_tool() -> str:
        nonlocal hidden_called
        hidden_called = True
        return "hidden"

    result = await server.call_tool("hidden_tool", {})

    assert hidden_called is False
    assert result.isError is True
    assert "execution surface" in result.content[0].text


def test_reference_snapshot_generation_is_fresh_and_manifested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    calls: list[tuple[str, str]] = []

    class Gerber:
        def export(self, output_subdir: str = "Gerbers") -> str:
            calls.append(("gerber", output_subdir))
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            root.mkdir(parents=True, exist_ok=True)
            (root / "board-F_Cu.gbr").write_bytes(b"gerber\n")
            return "ok"

    class Drill:
        def export(self, output_subdir: str = "Gerbers") -> str:
            calls.append(("drill", output_subdir))
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            root.mkdir(parents=True, exist_ok=True)
            (root / "board.drl").write_bytes(b"drill\n")
            return "ok"

    class Bom:
        def export(self, format: str = "csv") -> str:
            calls.append(("bom", format))
            root = reference_server._reference_snapshot_root("generation-1")
            (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
            return "ok"

    monkeypatch.setattr(
        reference_server,
        "_snapshot_export_services",
        lambda _root: SimpleNamespace(gerber=Gerber(), drill=Drill(), bom=Bom()),
    )

    result = reference_server.generate_reference_manufacturing_snapshot("generation-1")
    payload = json.loads(result)

    assert calls == [("gerber", "Gerbers"), ("drill", "Gerbers"), ("bom", "csv")]
    assert payload["generation"] == "generation-1"
    assert payload["artifact_manifest_digest"].startswith("sha256:")
    assert {item["path"] for item in payload["files"]} == {
        "BOM.csv",
        "Gerbers/board-F_Cu.gbr",
        "Gerbers/board.drl",
    }
    manifest = reference_server._reference_snapshot_root("generation-1") / "artifact-manifest.json"
    assert manifest.is_file()

    with pytest.raises(ValueError, match="already contains artifacts"):
        reference_server.generate_reference_manufacturing_snapshot("generation-1")


def test_reference_snapshot_comparison_revalidates_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    for generation in ("generation-1", "generation-2"):
        root = reference_server._reference_snapshot_root(generation)
        (root / "Gerbers").mkdir(parents=True)
        (root / "BOM.csv").write_bytes(b"same bom\n")
        (root / "Gerbers/board-F_Cu.gbr").write_bytes(b"same gerber\n")
        reference_server._write_snapshot_manifest(root, generation)

    identical = json.loads(reference_server.compare_reference_manufacturing_snapshots())
    assert identical["comparison"] == "byte_identical"
    assert len(identical["artifact_manifest_digests"]) == 2

    second = reference_server._reference_snapshot_root("generation-2") / "Gerbers/board-F_Cu.gbr"
    second.write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="manifest no longer matches snapshot bytes"):
        reference_server.compare_reference_manufacturing_snapshots()


def test_reference_snapshot_comparison_normalizes_only_kicad_generation_timestamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    timestamped = {
        "Gerbers/board-F_Cu.gtl": (
            "%TF.GenerationSoftware,KiCad,Pcbnew,10.0.6*%\n"
            "%TF.CreationDate,{iso}*%\n"
            "G04 Created by KiCad (PCBNEW 10.0.6) date {plain}*\n"
            "X100Y200D02*\n"
        ),
        "Gerbers/board.drl": (
            "M48\n; DRILL file KiCad 10.0.6 date {drill}\n; #@! TF.CreationDate,{iso}\nT1C0.300\n"
        ),
        "Gerbers/board-job.gbrjob": (
            '{{\n  "Header": {{\n    "CreationDate": "{iso}",\n'
            '    "GenerationSoftware": {{"Vendor": "KiCad"}}\n  }},\n'
            '  "GeneralSpecs": {{"ProjectId": "board"}}\n}}\n'
        ),
    }
    values = (
        ("generation-1", "2026-09-10T23:30:36+03:00", "2026-09-10 23:30:36", "2026-09-10T23:30:36"),
        ("generation-2", "2026-09-10T23:30:37+03:00", "2026-09-10 23:30:37", "2026-09-10T23:30:37"),
    )
    for generation, iso, plain, drill in values:
        root = reference_server._reference_snapshot_root(generation)
        (root / "Gerbers").mkdir(parents=True)
        (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
        for relative, template in timestamped.items():
            path = root / relative
            path.write_text(template.format(iso=iso, plain=plain, drill=drill), encoding="utf-8")
        reference_server._write_snapshot_manifest(root, generation)

    result = json.loads(reference_server.compare_reference_manufacturing_snapshots())

    assert result["comparison"] == "normalized_equivalent"
    assert result["normalization_rules_version"] == (
        reference_server.REFERENCE_MANUFACTURING_NORMALIZATION_RULES_VERSION
    )
    assert result["artifact_manifest_digests"][0] != result["artifact_manifest_digests"][1]
    assert (
        result["normalized_artifact_manifest_digests"][0]
        == (result["normalized_artifact_manifest_digests"][1])
    )


def test_reference_snapshot_comparison_does_not_normalize_manufacturing_content_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    for generation, coordinate in (
        ("generation-1", "X100Y200D02*"),
        ("generation-2", "X101Y200D02*"),
    ):
        root = reference_server._reference_snapshot_root(generation)
        (root / "Gerbers").mkdir(parents=True)
        (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
        (root / "Gerbers/board-F_Cu.gtl").write_text(
            f"%TF.CreationDate,2026-09-10T23:30:36+03:00*%\n{coordinate}\n",
            encoding="utf-8",
        )
        (root / "Gerbers/board.drl").write_text("M48\nT1C0.300\n", encoding="utf-8")
        reference_server._write_snapshot_manifest(root, generation)

    result = json.loads(reference_server.compare_reference_manufacturing_snapshots())

    assert result["comparison"] == "divergent"
    assert "normalization_rules_version" not in result


def test_reference_timestamp_normalization_requires_kicad_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    for generation, stamp in (
        ("generation-1", "2026-09-10T23:30:36+03:00"),
        ("generation-2", "2026-09-10T23:30:37+03:00"),
    ):
        root = reference_server._reference_snapshot_root(generation)
        (root / "Gerbers").mkdir(parents=True)
        (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
        (root / "Gerbers/board-F_Cu.gtl").write_text(
            f"%TF.CreationDate,{stamp}*%\nX100Y200D02*\n",
            encoding="utf-8",
        )
        (root / "Gerbers/board-job.gbrjob").write_text(
            json.dumps(
                {
                    "Header": {
                        "CreationDate": stamp,
                        "GenerationSoftware": {"Vendor": "OtherEDA"},
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
        reference_server._write_snapshot_manifest(root, generation)

    result = json.loads(reference_server.compare_reference_manufacturing_snapshots())

    assert result["comparison"] == "divergent"
    assert "normalization_rules_version" not in result


def test_reference_snapshot_rejects_export_failure_even_with_partial_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)

    class Gerber:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            root.mkdir(parents=True, exist_ok=True)
            (root / "board-F_Cu.gtl").write_text("partial\n", encoding="utf-8")
            return "Gerber export failed: synthetic failure"

    class Drill:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            (root / "board.drl").write_text("drill\n", encoding="utf-8")
            return "ok"

    class Bom:
        def export(self, format: str = "csv") -> str:
            root = reference_server._reference_snapshot_root("generation-1")
            (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
            return "ok"

    monkeypatch.setattr(
        reference_server,
        "_snapshot_export_services",
        lambda _root: SimpleNamespace(gerber=Gerber(), drill=Drill(), bom=Bom()),
    )

    with pytest.raises(ValueError, match="Gerber export failed"):
        reference_server.generate_reference_manufacturing_snapshot("generation-1")


def test_reference_snapshot_rejects_empty_required_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)

    class Gerber:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            root.mkdir(parents=True, exist_ok=True)
            (root / "board-F_Cu.gtl").write_bytes(b"")
            return "ok"

    class Drill:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            (root / "board.drl").write_text("drill\n", encoding="utf-8")
            return "ok"

    class Bom:
        def export(self, format: str = "csv") -> str:
            root = reference_server._reference_snapshot_root("generation-1")
            (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
            return "ok"

    monkeypatch.setattr(
        reference_server,
        "_snapshot_export_services",
        lambda _root: SimpleNamespace(gerber=Gerber(), drill=Drill(), bom=Bom()),
    )

    with pytest.raises(ValueError, match="missing BOM, Gerber, or drill output"):
        reference_server.generate_reference_manufacturing_snapshot("generation-1")


def test_reference_snapshot_rejects_symlinked_generation_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    outside = tmp_path / "outside-generation"
    outside.mkdir()
    root = reference_server._reference_snapshot_root("generation-1")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.symlink_to(outside, target_is_directory=True)

    def fail_services(_root: Path) -> SimpleNamespace:
        raise AssertionError("export services must not start for a symlinked generation root")

    monkeypatch.setattr(reference_server, "_snapshot_export_services", fail_services)

    with pytest.raises(ValueError, match="snapshot root must not be a symlink"):
        reference_server.generate_reference_manufacturing_snapshot("generation-1")
    assert list(outside.iterdir()) == []


def test_reference_gbrjob_normalization_preserves_non_timestamp_raw_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    first = b"""{
  "Header": {
    "GenerationSoftware": {"Vendor": "KiCad", "Application": "Pcbnew"},
    "CreationDate": "2026-09-10T23:30:36+03:00"
  },
  "GeneralSpecs": {"ProjectId": "board"}
}
"""
    second = (
        b'{"GeneralSpecs":{"ProjectId":"board"},'
        b'"Header":{"CreationDate":"2026-09-10T23:30:37+03:00",'
        b'"GenerationSoftware":{"Application":"Pcbnew","Vendor":"KiCad"}}}\n'
    )
    for generation, payload in (("generation-1", first), ("generation-2", second)):
        root = reference_server._reference_snapshot_root(generation)
        (root / "Gerbers").mkdir(parents=True)
        (root / "BOM.csv").write_bytes(b"reference,value\nU1,MCU\n")
        (root / "Gerbers/board-job.gbrjob").write_bytes(payload)
        reference_server._write_snapshot_manifest(root, generation)

    result = json.loads(reference_server.compare_reference_manufacturing_snapshots())

    assert result["comparison"] == "divergent"
    assert "normalization_rules_version" not in result


def test_reference_snapshot_rejects_invalid_generation_and_subdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="generation is invalid"):
        reference_server._reference_snapshot_root("generation-3")  # type: ignore[arg-type]

    root = tmp_path / "snapshot"
    assert reference_server._snapshot_subdir(root, None) == root
    assert reference_server._snapshot_subdir(root, "Gerbers") == root / "Gerbers"
    with pytest.raises(ValueError, match="output subdirectory is invalid"):
        reference_server._snapshot_subdir(root, "Elsewhere")


def test_reference_snapshot_manifest_rejects_unsafe_and_stale_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = reference_server._reference_snapshot_root("generation-1")
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="manifest is missing"):
        reference_server._validated_snapshot_manifest("generation-1")

    manifest = root / "artifact-manifest.json"
    manifest.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest is invalid"):
        reference_server._validated_snapshot_manifest("generation-1")

    manifest.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest is invalid"):
        reference_server._validated_snapshot_manifest("generation-1")

    (root / "BOM.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "pcb-reference-manufacturing-snapshot.v1",
                "generation": "generation-1",
                "artifact_manifest_digest": "sha256:" + "0" * 64,
                "files": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no longer matches snapshot bytes"):
        reference_server._validated_snapshot_manifest("generation-1")


def test_reference_snapshot_entries_reject_symlinked_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = tmp_path / "snapshot"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (root / "linked.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        reference_server._snapshot_file_entries(root)
    with pytest.raises(ValueError, match="must not contain symlinks"):
        reference_server._normalized_snapshot_entries(root)


def test_reference_gbrjob_normalization_is_fail_closed_for_malformed_metadata() -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    malformed = b'{"Header":'
    assert reference_server._normalize_kicad_timestamp_bytes("board.gbrjob", malformed) == malformed

    wrong_shape = b"[]\n"
    assert (
        reference_server._normalize_kicad_timestamp_bytes("board.gbrjob", wrong_shape)
        == wrong_shape
    )

    no_header = b'{"Other": {"CreationDate": "2026-09-11T00:00:00Z"}}\n'
    assert reference_server._normalize_kicad_timestamp_bytes("board.gbrjob", no_header) == no_header

    other_vendor = (
        b'{"Header":{"CreationDate":"2026-09-11T00:00:00Z",'
        b'"GenerationSoftware":{"Vendor":"OtherEDA"}}}\n'
    )
    assert (
        reference_server._normalize_kicad_timestamp_bytes("board.gbrjob", other_vendor)
        == other_vendor
    )

    duplicate = (
        b'{"Header":{"CreationDate":"2026-09-11T00:00:00Z",'
        b'"GenerationSoftware":{"Vendor":"KiCad"}},'
        b'"Other":{"CreationDate":"2026-09-11T00:00:01Z"}}\n'
    )
    assert reference_server._normalize_kicad_timestamp_bytes("board.gbrjob", duplicate) == duplicate


def test_reference_snapshot_accepts_lowercase_generated_bom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)

    class Gerber:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            root.mkdir(parents=True, exist_ok=True)
            (root / "board-F_Cu.gbr").write_text("gerber\n", encoding="utf-8")
            return "ok"

    class Drill:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            (root / "board.drl").write_text("drill\n", encoding="utf-8")
            return "ok"

    class Bom:
        def export(self, format: str = "csv") -> str:
            root = reference_server._reference_snapshot_root("generation-1")
            (root / "bom.csv").write_text("reference,value\nU1,MCU\n", encoding="utf-8")
            return "ok"

    monkeypatch.setattr(
        reference_server,
        "_snapshot_export_services",
        lambda _root: SimpleNamespace(gerber=Gerber(), drill=Drill(), bom=Bom()),
    )

    payload = json.loads(reference_server.generate_reference_manufacturing_snapshot("generation-1"))

    root = reference_server._reference_snapshot_root("generation-1")
    assert (root / "BOM.csv").is_file()
    names = {path.name for path in root.iterdir()}
    assert "BOM.csv" in names
    assert "bom.csv" not in names
    assert any(item["path"] == "BOM.csv" for item in payload["files"])


def test_reference_snapshot_normalizes_same_file_bom_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import os

    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)

    class Gerber:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            root.mkdir(parents=True, exist_ok=True)
            (root / "board-F_Cu.gbr").write_text("gerber\n", encoding="utf-8")
            return "ok"

    class Drill:
        def export(self, output_subdir: str = "Gerbers") -> str:
            root = reference_server._reference_snapshot_root("generation-1") / output_subdir
            (root / "board.drl").write_text("drill\n", encoding="utf-8")
            return "ok"

    class Bom:
        def export(self, format: str = "csv") -> str:
            root = reference_server._reference_snapshot_root("generation-1")
            lowercase = root / "bom.csv"
            lowercase.write_text("reference,value\nU1,MCU\n", encoding="utf-8")
            try:
                os.link(lowercase, root / "BOM.csv")
            except FileExistsError:
                pytest.skip("case-insensitive filesystem cannot create a second BOM alias")
            return "ok"

    monkeypatch.setattr(
        reference_server,
        "_snapshot_export_services",
        lambda _root: SimpleNamespace(gerber=Gerber(), drill=Drill(), bom=Bom()),
    )

    reference_server.generate_reference_manufacturing_snapshot("generation-1")

    root = reference_server._reference_snapshot_root("generation-1")
    assert (root / "BOM.csv").is_file()
    names = {path.name for path in root.iterdir()}
    assert "BOM.csv" in names
    assert "bom.csv" not in names
    assert ".reference-bom-case-normalize.tmp" not in names


def test_reference_snapshot_rejects_distinct_bom_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = reference_server._reference_snapshot_root("generation-1")
    root.mkdir(parents=True, exist_ok=True)
    (root / "BOM.csv").write_text("canonical\n", encoding="utf-8")
    (root / "bom.csv").write_text("different\n", encoding="utf-8")
    aliases = [path for path in root.iterdir() if path.name.casefold() == "bom.csv"]
    if len(aliases) < 2:
        pytest.skip("case-insensitive filesystem cannot represent distinct BOM aliases")

    with pytest.raises(ValueError, match="ambiguous BOM artifacts"):
        reference_server._canonicalize_snapshot_bom(root)


def test_reference_snapshot_rejects_reserved_bom_temp_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = reference_server._reference_snapshot_root("generation-1")
    root.mkdir(parents=True, exist_ok=True)
    (root / "bom.csv").write_text("bom\n", encoding="utf-8")
    (root / ".reference-bom-case-normalize.tmp").write_text("reserved\n", encoding="utf-8")

    with pytest.raises(ValueError, match="reserved temporary BOM artifact"):
        reference_server._canonicalize_snapshot_bom(root)


def test_reference_snapshot_bom_canonicalizer_returns_missing_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = reference_server._reference_snapshot_root("generation-1")
    root.mkdir(parents=True, exist_ok=True)

    canonical = reference_server._canonicalize_snapshot_bom(root)

    assert canonical == root / "BOM.csv"
    assert not canonical.exists()


def test_reference_snapshot_rejects_multiple_noncanonical_bom_spellings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = reference_server._reference_snapshot_root("generation-1")
    root.mkdir(parents=True, exist_ok=True)
    (root / "bom.csv").write_text("one\n", encoding="utf-8")
    (root / "BoM.csv").write_text("two\n", encoding="utf-8")
    aliases = [path for path in root.iterdir() if path.name.casefold() == "bom.csv"]
    if len(aliases) < 2:
        pytest.skip("case-insensitive filesystem cannot represent multiple BOM spellings")

    with pytest.raises(ValueError, match="ambiguous BOM artifacts"):
        reference_server._canonicalize_snapshot_bom(root)


def test_reference_snapshot_bom_case_rename_rolls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    _reset_reference_env(monkeypatch, tmp_path)
    root = reference_server._reference_snapshot_root("generation-1")
    root.mkdir(parents=True, exist_ok=True)
    source = root / "bom.csv"
    source.write_text("bom\n", encoding="utf-8")
    original_replace = Path.replace

    def fail_canonical_replace(path: Path, target: Path) -> Path:
        if path.name == ".reference-bom-case-normalize.tmp" and target.name == "BOM.csv":
            raise OSError("simulated case-only rename failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_canonical_replace)

    with pytest.raises(OSError, match="simulated case-only rename failure"):
        reference_server._canonicalize_snapshot_bom(root)

    assert source.read_text(encoding="utf-8") == "bom\n"
    assert not (root / ".reference-bom-case-normalize.tmp").exists()


def test_reference_gerber_timestamp_line_matching_preserves_exact_semantics() -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    normalize = reference_server._normalize_kicad_generated_line
    kwargs = {"is_kicad_gerber": True, "is_kicad_drill": False}

    assert normalize(b"%TF.CreationDate,2026-09-13T19:00:00Z*%", **kwargs) == (
        b"%TF.CreationDate,<normalized>*%"
    )
    assert (
        normalize(b"G04 Created by KiCad (PCBNEW 10.0.6) date 2026-09-13 19:00:00*", **kwargs)
        == b"G04 Created by KiCad (PCBNEW 10.0.6) date <normalized>*"
    )
    assert (
        normalize(b"G04 Created by KiCad (PCBNEW 10.0.6) date alpha date beta*", **kwargs)
        == b"G04 Created by KiCad (PCBNEW 10.0.6) date alpha date <normalized>*"
    )


def test_reference_gerber_timestamp_line_matching_rejects_near_misses() -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    normalize = reference_server._normalize_kicad_generated_line
    kwargs = {"is_kicad_gerber": True, "is_kicad_drill": False}
    near_misses = (
        b"%TF.CreationDate,2026-09-13T19:00:00Z*X",
        b"%TF.CreationDate,2026-09-13\nT19:00:00Z*%",
        b"G04 Created by KiCad (PCBNEW 10.0.6) 2026-09-13 19:00:00*",
        b"G04 Created by KiCad (PCBNEW 10.0.6) date 2026-09-13\r19:00:00*",
        b"G04 Created by KiCad PCBNEW 10.0.6) date 2026-09-13 19:00:00*",
        b"G04 Created by KiCad (PCBNEW 10.0.6) date 2026-09-13 19:00:00",
    )

    for body in near_misses:
        assert normalize(body, **kwargs) == body


def test_reference_drill_created_by_line_matching_preserves_exact_semantics() -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    normalize = reference_server._normalize_kicad_generated_line
    kwargs = {"is_kicad_gerber": False, "is_kicad_drill": True}

    assert normalize(b"; DRILL file KiCad 10.0.6 date 2026-09-13T19:00:00", **kwargs) == (
        b"; DRILL file KiCad 10.0.6 date <normalized>"
    )
    assert normalize(b"; DRILL file KiCad 10.0.6 date alpha date beta", **kwargs) == (
        b"; DRILL file KiCad 10.0.6 date alpha date <normalized>"
    )


def test_reference_drill_created_by_line_matching_rejects_near_misses() -> None:
    import kicad_mcp.evals.reference_mcp_server as reference_server

    normalize = reference_server._normalize_kicad_generated_line
    kwargs = {"is_kicad_gerber": False, "is_kicad_drill": True}
    near_misses = (
        b"; DRILL file KiCad 10.0.6 2026-09-13T19:00:00",
        b"; DRILL file KiCad 10.0.6 date 2026-09-13\nT19:00:00",
        b"DRILL file KiCad 10.0.6 date 2026-09-13T19:00:00",
    )

    for body in near_misses:
        assert normalize(body, **kwargs) == body
