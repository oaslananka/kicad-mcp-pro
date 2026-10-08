"""Contract tests for read-only #944 KiCad-native inventory guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parents[2] / "scripts" / "compare_native_netlist_ir.py"
_SPEC = importlib.util.spec_from_file_location("compare_native_netlist_ir", AUDIT)
assert _SPEC is not None and _SPEC.loader is not None

module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = module
_SPEC.loader.exec_module(module)


def _xml(*, refs: tuple[str, ...] = ("U1", "R1"), names: tuple[str, ...] = ("VCC", "GND")) -> bytes:
    return (
        "<?xml version='1.0'?>\n<export><components>"
        + "".join(f"<comp ref='{ref}'><libsource lib='Device'/></comp>" for ref in refs)
        + "<comp ref='#PWR01'><libsource lib='power'/></comp>"
        + "</components><nets>"
        + "".join(f"<net code='{i + 1}' name='{name}'/>" for i, name in enumerate(names))
        + "</nets></export>"
    ).encode("utf-8")


def test_matching_inventory_never_claims_graph_equivalence(tmp_path: Path) -> None:
    source = tmp_path / "native.xml"
    source.write_bytes(_xml())
    native = module.read_native_inventory(source)
    result = module.compare_inventory(native, {"U1", "R1"}, 2)
    assert result["inventory_match"] is True
    assert result["graph_equivalent"] is False
    assert result["native_raw_component_count"] == 3
    assert result["native_power_symbol_count"] == 1


def test_native_hierarchy_undercount_is_a_hard_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "native.xml"
    source.write_bytes(_xml(refs=("U1", "R1", "C1")))
    native = module.read_native_inventory(source)
    result = module.compare_inventory(native, {"U1"}, 1)
    assert result["inventory_match"] is False
    assert result["missing_component_refs_count"] == 2
    assert result["missing_component_refs_preview"] == ["C1", "R1"]


def test_matching_counts_with_different_refs_still_fail(tmp_path: Path) -> None:
    source = tmp_path / "native.xml"
    source.write_bytes(_xml())
    result = module.compare_inventory(module.read_native_inventory(source), {"U1", "Q9"}, 2)
    assert result["inventory_match"] is False
    assert result["missing_component_refs_preview"] == ["R1"]
    assert result["extra_component_refs_preview"] == ["Q9"]


def test_net_count_mismatch_blocks_inventory_match(tmp_path: Path) -> None:
    source = tmp_path / "native.xml"
    source.write_bytes(_xml())
    result = module.compare_inventory(module.read_native_inventory(source), {"U1", "R1"}, 1)
    assert result["inventory_match"] is False


@pytest.mark.parametrize(
    "payload",
    [
        b"<export/>",
        b"<export><components/><nets/></export>",
        b"<!DOCTYPE x [<!ENTITY x SYSTEM 'file:///tmp/x'>]><export/>",
        (
            b"<export><components><comp ref='U1'/><comp ref='U1'/>"
            b"</components><nets><net name='A'/></nets></export>"
        ),
        (
            b"<export><components><comp ref='R1'/></components><nets>"
            b"<net name='A'/><net name='A'/></nets></export>"
        ),
        b"<export><components><comp ref='R1'/></components><nets><net code='1'/></nets></export>",
        b"not-xml",
    ],
)
def test_invalid_native_authority_fails_closed(tmp_path: Path, payload: bytes) -> None:
    source = tmp_path / "native.xml"
    source.write_bytes(payload)
    with pytest.raises(ValueError):
        module.read_native_inventory(source)


def test_symlink_is_not_followed(tmp_path: Path) -> None:
    real = tmp_path / "real.xml"
    real.write_bytes(_xml())
    symlink = tmp_path / "link.xml"
    try:
        symlink.symlink_to(real)
    except OSError:
        pytest.skip("symlink creation unavailable on this runner")
    with pytest.raises(ValueError, match="symlink"):
        module.read_native_inventory(symlink)


def test_oversize_payload_rejected(tmp_path: Path) -> None:
    source = tmp_path / "native.xml"
    source.write_bytes(b"x" * (32 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="32 MiB"):
        module.read_native_inventory(source)


def test_cli_output_remains_json_if_legacy_parser_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json
    from types import ModuleType, SimpleNamespace

    native_xml = tmp_path / "native.xml"
    native_xml.write_bytes(_xml())
    legacy = ModuleType("kicad_mcp.ir.from_kicad")

    def fake_parse(_source: Path, *, load_pin_metadata: bool) -> object:
        assert not load_pin_metadata
        print("diagnostic from legacy parser")
        return SimpleNamespace(
            components={"U1": object(), "R1": object()},
            nets={"VCC": object(), "GND": object()},
        )

    legacy.parse_schematic = fake_parse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kicad_mcp.ir.from_kicad", legacy)
    assert (
        module.main(
            ["--native-xml", str(native_xml), "--schematic", str(tmp_path / "demo.kicad_sch")]
        )
        == 0
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["inventory_match"] is True
    assert "diagnostic from legacy parser" in output.err
    assert "diagnostic from legacy parser" not in output.out
