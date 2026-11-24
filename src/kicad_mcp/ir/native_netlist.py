"""Opt-in instance-aware semantic import of KiCad's native XML netlist.

The native export is the authority for exported component instances and nets.
This is not a geometry parser, a complete symbol-library pin census, or ERC.
A project-facing caller must bind the export to its exact source snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from .circuit_ir import (
    IRCircuit,
    IRComponent,
    IRNet,
    IRPin,
    NativeSymbolInstance,
    PinElectricalType,
)

_MAX_XML_BYTES = 32 * 1024 * 1024


class _XMLNode(Protocol):
    """Read-only view of elements returned by the hardened XML parser."""

    def findall(self, path: str) -> Sequence[_XMLNode]: ...

    def find(self, path: str) -> _XMLNode | None: ...

    def findtext(self, path: str) -> str | None: ...

    def get(self, key: str) -> str | None: ...


def _required(value: str | None, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"missing or non-normalized native {label}")
    return value


def _uuid(value: str | None) -> str:
    text = _required(value, "UUID")
    try:
        normalized = str(UUID(text))
    except ValueError as exc:
        raise ValueError("invalid native UUID") from exc
    if text != normalized:
        raise ValueError("non-canonical native UUID")
    return normalized


def _sheet_path(root_uuid: str, stamps: str | None) -> str:
    path = _required(stamps, "sheet path")
    if path == "/":
        return f"/{root_uuid}"
    if not path.startswith("/") or not path.endswith("/"):
        raise ValueError("invalid native sheet path")
    suffix = "/".join(_uuid(part) for part in path[1:-1].split("/"))
    return f"/{root_uuid}/{suffix}"


def _read_sheets(root: _XMLNode, root_uuid: str, root_name: str) -> dict[str, tuple[str, str]]:
    sheets: dict[str, tuple[str, str]] = {}
    for sheet in root.findall("design/sheet"):
        path = _sheet_path(root_uuid, sheet.get("tstamps"))
        name = _required(sheet.get("name"), "sheet name path")
        source = _required(sheet.findtext("title_block/source"), "sheet source")
        if path in sheets:
            raise ValueError("duplicate native sheet instance")
        sheets[path] = (name, source)
    root_sheet = sheets.get(f"/{root_uuid}")
    if root_sheet != ("/", PurePosixPath(root_name).name):
        raise ValueError("native export root sheet mismatch")
    for path in sheets:
        parent = path.rsplit("/", 1)[0]
        if parent and parent not in sheets:
            raise ValueError("native export has missing parent sheet")
    return sheets


def _read_components(
    root: _XMLNode, circuit: IRCircuit, sheets: dict[str, tuple[str, str]]
) -> None:
    used_instances: set[tuple[str, str]] = set()
    for comp in root.findall("components/comp"):
        ref = _required(comp.get("ref"), "component reference")
        if ref in circuit.components:
            raise ValueError("duplicate native component reference")
        libsource = comp.find("libsource")
        sheet = comp.find("sheetpath")
        if libsource is None or sheet is None:
            raise ValueError("native component lacks library or sheet identity")
        path = _sheet_path(circuit.source_uuid or "", sheet.get("tstamps"))
        name = _required(sheet.get("names"), "component sheet name")
        if path not in sheets or sheets[path][0] != name:
            raise ValueError("native component sheet identity mismatch")
        stamps = tuple(sorted(_uuid(stamp) for stamp in (comp.findtext("tstamps") or "").split()))
        keys = {(path, stamp) for stamp in stamps}
        if not stamps or len(keys) != len(stamps) or used_instances & keys:
            raise ValueError("missing or duplicate native symbol instance")
        used_instances.update(keys)
        library = _required(libsource.get("lib"), "library")
        part = _required(libsource.get("part"), "library part")
        properties = {prop.get("name") for prop in comp.findall("property")}
        circuit.native_instances[ref] = NativeSymbolInstance(path, name, stamps)
        circuit.components[ref] = IRComponent(
            ref,
            f"{library}:{part}",
            comp.findtext("value") or "",
            comp.findtext("footprint") or "",
            dnp="dnp" in properties,
            in_bom="exclude_from_bom" not in properties,
        )


def _native_pin_type(raw: str) -> PinElectricalType:
    # KiCad's XML suffix marks an explicit no-connect, not a different pin type.
    kind = raw.removesuffix("+no_connect")
    return PinElectricalType(
        {"power_in": "power_input", "power_out": "power_output", "no_connect": "not_connected"}.get(
            kind, kind
        )
    )


def _read_nets(root: _XMLNode, circuit: IRCircuit) -> None:
    pins: dict[str, dict[str, IRPin]] = {ref: {} for ref in circuit.components}
    for net in root.findall("nets/net"):
        name = _required(net.get("name"), "net name")
        if name in circuit.nets:
            raise ValueError("duplicate native net name")
        connections: set[tuple[str, str]] = set()
        for node in net.findall("node"):
            ref = _required(node.get("ref"), "pin reference")
            number = _required(node.get("pin"), "pin number")
            if ref not in pins or number in pins[ref]:
                raise ValueError("unknown or multiply-connected native pin")
            pins[ref][number] = IRPin(
                number,
                node.get("pinfunction") or number,
                _native_pin_type(node.get("pintype") or "unspecified"),
            )
            connections.add((ref, number))
        if not connections:
            raise ValueError("empty native net")
        circuit.nets[name] = IRNet(name, frozenset(connections), net_class=net.get("class"))
    for ref, component in circuit.components.items():
        circuit.components[ref] = replace(
            component, pins=tuple(pins[ref][n] for n in sorted(pins[ref]))
        )


def parse_native_netlist(
    xml: bytes,
    *,
    root_uuid: str,
    root_name: str,
    expected_sheets: Mapping[str, tuple[str, str]] | None = None,
    expected_stamps: Mapping[str, frozenset[str]] | None = None,
) -> IRCircuit:
    """Import version-E KiCad native connectivity without inventing missing facts."""
    if not xml or len(xml) > _MAX_XML_BYTES:
        raise ValueError("native XML is empty or exceeds the safety limit")
    try:
        root = SafeElementTree.fromstring(xml, forbid_dtd=True)
    except (SafeElementTree.ParseError, DefusedXmlException) as exc:
        raise ValueError("invalid native XML") from exc
    if root.tag != "export" or root.get("version") != "E":
        raise ValueError("unsupported native XML schema")
    if any(len(root.findall(section)) != 1 for section in ("design", "components", "nets")):
        raise ValueError("missing or duplicate native XML section")
    root_uuid = _uuid(root_uuid)
    sheets = _read_sheets(root, root_uuid, root_name)
    if expected_sheets is not None and sheets != expected_sheets:
        raise ValueError("native export does not cover the source sheet instances")
    circuit = IRCircuit(
        source_path=root_name,
        source_uuid=root_uuid,
        sheet_hierarchy=tuple(sorted(sheets)),
        title=root.findtext("design/sheet/title_block/title") or "",
    )
    _read_components(root, circuit, sheets)
    if expected_stamps is not None:
        for instance in circuit.native_instances.values():
            if not set(instance.symbol_uuids) <= expected_stamps.get(
                instance.sheet_path, frozenset()
            ):
                raise ValueError("native symbol UUID is not on its declared source sheet")
    _read_nets(root, circuit)
    if not circuit.components or not circuit.nets:
        raise ValueError("native XML has no component or net coverage")
    return circuit
