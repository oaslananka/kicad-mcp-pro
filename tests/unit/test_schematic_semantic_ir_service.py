from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from kicad_mcp.schematic.semantic_ir import SchematicSemanticIRService


@dataclass
class FakeCircuit:
    source_path: str | None = None
    source_uuid: str | None = None
    title: str = ""
    components: dict[str, object] = field(default_factory=dict)
    nets: dict[str, object] = field(default_factory=dict)
    power_rails: dict[str, object] = field(default_factory=dict)
    interfaces: dict[str, object] = field(default_factory=dict)

    def component_count(self) -> int:
        return len(self.components)

    def pin_count(self) -> int:
        return sum(len(component.pins) for component in self.components.values())  # type: ignore[attr-defined]

    def net_count(self) -> int:
        return len(self.nets)

    def interface_count(self) -> int:
        return len(self.interfaces)


def test_get_summary_logs_and_wraps_parse_failures(tmp_path: Path) -> None:
    schematic = tmp_path / "demo.kicad_sch"
    warnings: list[str] = []
    diagnostics: list[tuple[str, Path]] = []

    def parse(_path: Path) -> FakeCircuit:
        raise ValueError("broken IR")

    def with_diagnostics(message: str, path: Path) -> str:
        diagnostics.append((message, path))
        return f"diagnostic: {message}"

    service = SchematicSemanticIRService(
        active_schematic_file=lambda: schematic,
        parse_circuit=parse,
        lint_circuit=lambda _circuit: [],
        with_diagnostics=with_diagnostics,
        warn_parse_failure=lambda exc: warnings.append(str(exc)),
    )

    assert service.get_summary() == "diagnostic: Could not parse IR: broken IR"
    assert warnings == ["broken IR"]
    assert diagnostics == [("Could not parse IR: broken IR", schematic)]


def test_get_summary_renders_empty_circuit_without_optional_sections(tmp_path: Path) -> None:
    schematic = tmp_path / "empty.kicad_sch"
    circuit = FakeCircuit()
    service = SchematicSemanticIRService(
        active_schematic_file=lambda: schematic,
        parse_circuit=lambda _path: circuit,
        lint_circuit=lambda _circuit: [],
        with_diagnostics=lambda message, _path: message,
        warn_parse_failure=lambda _exc: None,
    )

    assert service.get_summary() == "\n".join(
        [
            "# Semantic Circuit IR — ",
            "Source: None",
            "UUID: N/A",
            "",
            "**Summary:** 0 components, 0 pins, 0 nets, 0 rails, 0 interfaces",
        ]
    )


def test_get_summary_preserves_complete_rendering_and_sorting(tmp_path: Path) -> None:
    schematic = tmp_path / "demo.kicad_sch"
    circuit = FakeCircuit(
        source_path="/project/demo.kicad_sch",
        source_uuid="abc-123",
        title="Demo Board",
        components={
            "U1": SimpleNamespace(
                lib_id="MCU:STM32",
                value="STM32F0",
                footprint="Package_QFP:LQFP-48",
                pins=(1,),
                dnp=False,
                in_bom=True,
            ),
            "R2": SimpleNamespace(
                lib_id="Device:R",
                value="10k",
                footprint="Resistor_SMD:R_0603",
                pins=(1, 2),
                dnp=True,
                in_bom=False,
            ),
        },
        nets={
            "VCC": SimpleNamespace(
                connections=frozenset({("U1", "1")}),
                is_power=True,
                voltage=3.3,
            ),
            "SIGNAL": SimpleNamespace(
                connections=frozenset({("U1", "2"), ("R2", "1")}),
                is_power=False,
                voltage=None,
            ),
        },
        power_rails={
            "VCC": SimpleNamespace(
                voltage=3.3,
                net_names=frozenset({"VCC", "VCC_A", "VCC_B", "VCC_C", "VCC_D", "VCC_E", "VCC_F"}),
                source_ref="U1",
                source_pin="1",
            )
        },
        interfaces={
            "SPI1": SimpleNamespace(
                kind="spi",
                net_roles={"mosi": "SPI1_MOSI", "miso": "SPI1_MISO"},
                refs=("U3", "U1", "U4", "U2"),
            )
        },
    )
    findings = [
        SimpleNamespace(
            severity=SimpleNamespace(value="warning"),
            rule_id="ir-005",
            subject="SIGNAL",
            message="Dangling net",
            detail="one endpoint",
        ),
        SimpleNamespace(
            severity=SimpleNamespace(value="info"),
            rule_id="ir-006",
            subject="",
            message="No pin metadata",
            detail="",
        ),
    ]
    service = SchematicSemanticIRService(
        active_schematic_file=lambda: schematic,
        parse_circuit=lambda _path: circuit,
        lint_circuit=lambda _circuit: findings,
        with_diagnostics=lambda message, _path: message,
        warn_parse_failure=lambda _exc: None,
    )

    assert service.get_summary() == "\n".join(
        [
            "# Semantic Circuit IR — Demo Board",
            "Source: /project/demo.kicad_sch",
            "UUID: abc-123",
            "",
            "**Summary:** 2 components, 3 pins, 2 nets, 1 rails, 1 interfaces",
            "",
            "## Components (2)",
            "- R2: Device:R = 10k (Resistor_SMD:R_0603) [DNP] [NoBOM]  (2 pins)",
            "- U1: MCU:STM32 = STM32F0 (Package_QFP:LQFP-48)  (1 pins)",
            "",
            "## Nets (2 total: 1 signal, 1 power)",
            "- `SIGNAL` (2 connections)",
            "- `VCC` [POWER] 3.3V (1 connections)",
            "",
            "## Power Rails (1)",
            "- VCC: 3.3V from U1.1  nets=[VCC, VCC_A, VCC_B, VCC_C, VCC_D … (+2 more)]",
            "",
            "## Interfaces (1)",
            "- SPI1 (spi): [mosi=SPI1_MOSI, miso=SPI1_MISO]  refs=[U1, U2, U3]",
            "",
            "## IR Lint Findings (2)",
            "- [WARNING] ir-005 (SIGNAL): Dangling net — one endpoint",
            "- [INFO] ir-006: No pin metadata",
        ]
    )
