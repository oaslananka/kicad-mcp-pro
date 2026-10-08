"""Read-only KiCad XML netlist vs semantic IRCircuit inventory check (#944).

This is an intentionally *incomplete* authority check: a passing inventory
comparison is not proof of electrical connectivity, stable UUID identity,
Engineering Graph equivalence, or incremental update performance.

Generate native XML with KiCad CLI from a disposable *complete* hierarchy copy;
never run a modifying/exporting subprocess on a canonical project here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as SafeElementTree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

_MAX_NATIVE_XML_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class NativeInventory:
    component_refs: frozenset[str]
    net_count: int
    raw_component_count: int
    ignored_power_refs: frozenset[str]


def read_native_inventory(xml_path: Path) -> NativeInventory:
    """Extract component identities and net count from native KiCad XML.

    KiCad power symbols are excluded because the existing IRCircuit parser
    represents them as rails rather than ordinary components. Everything
    else remains in the comparison, including DNP/non-BOM components.
    """
    if xml_path.is_symlink() or not xml_path.is_file():
        raise ValueError("native XML input must be a regular, non-symlink file")
    with xml_path.open("rb") as source:
        xml_bytes = source.read(_MAX_NATIVE_XML_BYTES + 1)
    if len(xml_bytes) > _MAX_NATIVE_XML_BYTES:
        raise ValueError("native XML exceeds 32 MiB safety limit")
    upper = xml_bytes.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("native XML DTD and entity declarations are forbidden")
    try:
        root = SafeElementTree.fromstring(xml_bytes)
    except (ParseError, DefusedXmlException) as exc:
        raise ValueError("native XML is malformed") from exc
    if root.tag != "export":
        raise ValueError("native XML must have a KiCad export root")
    components = root.find("components")
    nets = root.find("nets")
    if components is None or nets is None:
        raise ValueError("native XML lacks components or nets inventory")

    active: set[str] = set()
    power: set[str] = set()
    all_refs: set[str] = set()
    count = 0
    for comp in components.findall("comp"):
        count += 1
        reference = (comp.get("ref") or "").strip()
        if not reference or reference in all_refs:
            raise ValueError("native XML has an empty or duplicate component reference")
        all_refs.add(reference)
        libsource = comp.find("libsource")
        if libsource is not None and libsource.get("lib") == "power":
            power.add(reference)
        else:
            active.add(reference)

    names: set[str] = set()
    count_nets = 0
    for net in nets.findall("net"):
        count_nets += 1
        name = net.get("name")
        if name is None or name in names:
            raise ValueError("native XML has a missing or duplicate net name")
        names.add(name)
    if count == 0 or count_nets == 0:
        raise ValueError("native XML has no components or no nets; cannot establish coverage")
    return NativeInventory(
        component_refs=frozenset(active),
        net_count=count_nets,
        raw_component_count=count,
        ignored_power_refs=frozenset(power),
    )


def compare_inventory(
    native: NativeInventory, ir_refs: set[str], ir_net_count: int
) -> dict[str, object]:
    """Report fail-closed inventory comparison, never graph equivalence."""
    missing = sorted(native.component_refs - ir_refs)
    extra = sorted(ir_refs - native.component_refs)
    # Auto-generated net names differ between KiCad and root-sheet IR, so a
    # count comparison is the only meaningful net assertion in this tranche.
    matched = not missing and not extra and native.net_count == ir_net_count
    return {
        "schema": "native-ir-inventory-v1",
        "scope": "component-reference-and-net-count-only",
        "graph_equivalent": False,  # Cannot be proven by this audit.
        "inventory_match": matched,
        "native_component_count": len(native.component_refs),
        "native_raw_component_count": native.raw_component_count,
        "native_power_symbol_count": len(native.ignored_power_refs),
        "native_net_count": native.net_count,
        "ir_component_count": len(ir_refs),
        "ir_net_count": ir_net_count,
        "missing_component_refs_count": len(missing),
        "extra_component_refs_count": len(extra),
        "missing_component_refs_preview": missing[:20],
        "extra_component_refs_preview": extra[:20],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-xml", type=Path, required=True)
    parser.add_argument("--schematic", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        native = read_native_inventory(args.native_xml)
        # Delay the project dependency until the command actually runs so the
        # pure inventory comparison can be unit-tested without KiCad packages.
        from kicad_mcp.ir.from_kicad import parse_schematic

        ir = parse_schematic(args.schematic, load_pin_metadata=False)
        result = compare_inventory(native, set(ir.components), len(ir.nets))
    except (OSError, ValueError, ImportError) as exc:
        print(f"native IR audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["inventory_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
