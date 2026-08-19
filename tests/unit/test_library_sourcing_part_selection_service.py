from __future__ import annotations

from collections.abc import Callable

import pytest

from kicad_mcp.library.sourcing import LibrarySourcingService
from kicad_mcp.utils.component_search import ComponentRecord


def _record(
    *,
    code: str = "C123",
    stock: int = 100,
    package: str = "SOT-23",
    description: str = "5V 1A regulator",
) -> ComponentRecord:
    return ComponentRecord(
        source="jlcsearch",
        lcsc_code=code,
        mpn=f"MPN-{code}",
        package=package,
        description=description,
        stock=stock,
        price=0.01,
        is_basic=True,
        is_preferred=False,
    )


class FakeClient:
    def __init__(self, records: list[ComponentRecord], part: ComponentRecord | None = None) -> None:
        self.records = records
        self.part = part
        self.search_calls: list[tuple[object, ...]] = []
        self.get_calls: list[str] = []

    def search(self, query: str, **kwargs: object) -> list[ComponentRecord]:
        self.search_calls.append((query, kwargs))
        return self.records

    def get_part(self, identifier: str) -> ComponentRecord | None:
        self.get_calls.append(identifier)
        return self.part


def _service(
    client: FakeClient,
    updates: list[tuple[str, str, str]],
    *,
    update_symbol_property: Callable[[str, str, str], object] | None = None,
) -> LibrarySourcingService:
    updater = update_symbol_property or (
        lambda ref, field, value: updates.append((ref, field, value))
    )
    return LibrarySourcingService(
        component_search_client=lambda _source: client,
        parse_passive_parametric_query=lambda *_args, **_kwargs: None,
        rank_passive_parametric_results=lambda results, _query: (results, {}),
        format_passive_parametric_lines=lambda heading, _results, _evidence, **_kwargs: heading,
        sort_component_results=lambda results, **_kwargs: list(results),
        format_component_lines=lambda heading, results, **_kwargs: (
            heading + "\n" + "\n".join(item.lcsc_code for item in results)
        ),
        max_items_per_response=lambda: 20,
        schematic_component_rows=lambda: [],
        group_bom_rows=lambda rows: rows,
        lookup_component=lambda *_args, **_kwargs: None,
        update_symbol_property=updater,
    )


def test_recommend_part_filters_unstocked_results_and_preserves_search_contract() -> None:
    client = FakeClient([_record(code="C0", stock=0), _record(code="C1", stock=25)])
    service = _service(client, [])

    result = service.recommend_part("LDO regulator", {}, package="SOT-23", max_results=3)

    assert client.search_calls == [
        ("LDO regulator", {"package": "SOT-23", "only_basic": True, "limit": 50})
    ]
    assert "C1" in result
    assert "C0" not in result
    assert "Use lib_bind_part_to_symbol()" in result


def test_bind_part_to_symbol_assigns_identity_and_footprint_hint() -> None:
    part = _record(code="C777", package="SOT-23")
    client = FakeClient([], part=part)
    updates: list[tuple[str, str, str]] = []
    service = _service(client, updates)

    result = service.bind_part_to_symbol("U1", "C777")

    assert client.get_calls == ["C777"]
    assert updates == [
        ("U1", "LCSC", "C777"),
        ("U1", "MPN", "MPN-C777"),
        ("U1", "Footprint", "SOT-23"),
    ]
    assert "Bound 'C777' to U1" in result
    assert "assigned to symbol" in result


class RaisingClient(FakeClient):
    def get_part(self, identifier: str) -> ComponentRecord | None:
        raise RuntimeError(f"lookup failed for {identifier}")


def test_bind_part_to_symbol_reports_lookup_failure() -> None:
    service = _service(RaisingClient([]), [])
    assert service.bind_part_to_symbol("U1", "C404") == "Part lookup failed: lookup failed for C404"


def test_bind_part_to_symbol_reports_missing_part() -> None:
    service = _service(FakeClient([], part=None), [])
    assert service.bind_part_to_symbol("U1", "C404") == "No part found for 'C404' on jlcsearch."


def test_bind_part_to_symbol_reports_identity_update_failure() -> None:
    part = _record(code="C500")

    def fail_update(_ref: str, _field: str, _value: str) -> None:
        raise RuntimeError("write blocked")

    service = _service(FakeClient([], part=part), [], update_symbol_property=fail_update)
    assert service.bind_part_to_symbol("U1", "C500") == (
        "Could not update schematic properties for 'U1': write blocked"
    )


def test_bind_part_to_symbol_reports_missing_package_for_auto_assignment() -> None:
    part = _record(code="C600", package="")
    service = _service(FakeClient([], part=part), [])

    result = service.bind_part_to_symbol("U1", "C600")

    assert "Footprint: package info unavailable" in result


def test_bind_part_to_symbol_preserves_identity_when_footprint_assignment_fails() -> None:
    part = _record(code="C700", package="QFN-16")
    updates: list[tuple[str, str, str]] = []

    def update(ref: str, field: str, value: str) -> None:
        if field == "Footprint":
            raise RuntimeError("footprint write blocked")
        updates.append((ref, field, value))

    service = _service(FakeClient([], part=part), updates, update_symbol_property=update)
    result = service.bind_part_to_symbol("U1", "C700")

    assert updates == [("U1", "LCSC", "C700"), ("U1", "MPN", "MPN-C700")]
    assert "automatic assignment failed: footprint write blocked" in result


def test_bind_part_to_symbol_skips_footprint_when_disabled() -> None:
    part = _record(code="C800", package="SOT-23")
    updates: list[tuple[str, str, str]] = []
    service = _service(FakeClient([], part=part), updates)

    result = service.bind_part_to_symbol("U1", "C800", auto_assign_footprint=False)

    assert updates == [("U1", "LCSC", "C800"), ("U1", "MPN", "MPN-C800")]
    assert "Footprint hint" not in result


def test_recommend_part_reports_search_failure() -> None:
    class SearchFailureClient(FakeClient):
        def search(self, query: str, **kwargs: object) -> list[ComponentRecord]:
            raise OSError(f"search failed for {query}")

    service = _service(SearchFailureClient([]), [])
    assert (
        service.recommend_part("LDO", {})
        == "Part recommendation search failed: search failed for LDO"
    )


@pytest.mark.parametrize(
    ("key", "value", "description"),
    [
        ("rds_on_mohm", 1000, "1 ohm MOSFET"),
        ("capacitance_uf", 10, "10 uF capacitor"),
        ("capacitance_nf", 1000, "1 uF capacitor"),
        ("capacitance_pf", 1_000_000, "1 uF capacitor"),
        ("frequency_mhz", 10, "10 MHz oscillator"),
        ("frequency_khz", 10_000, "10 MHz oscillator"),
        ("voltage_v", 5, "5 V regulator"),
    ],
)
def test_recommend_part_applies_scaled_numeric_requirements(
    key: str, value: float, description: str
) -> None:
    part = _record(code="C900", description=description)
    service = _service(FakeClient([part]), [])

    result = service.recommend_part("candidate", {key: value})

    assert "C900" in result
    assert f"{key}={value}" in result


def test_recommend_part_applies_range_requirements_and_reports_no_match() -> None:
    part = _record(code="C901", description="12 V regulator")
    service = _service(FakeClient([part]), [])

    result = service.recommend_part("regulator", {"voltage_v": {"min": 4, "max": 6}})

    assert "C901" not in result
    assert "No matching parts found" in result


def test_recommend_part_rejects_numeric_requirement_below_threshold() -> None:
    part = _record(code="C902", description="1 V regulator")
    service = _service(FakeClient([part]), [])

    result = service.recommend_part("regulator", {"voltage_v": 10})

    assert "C902" not in result
    assert "No matching parts found" in result


def test_check_derating_compliance_preserves_pass_and_avl_output() -> None:
    service = _service(FakeClient([]), [])

    result = service.check_derating_compliance(
        "capacitor", "voltage", 25.0, 12.0, "Murata", ["Murata", "TDK"]
    )

    assert result == (
        "Part sourcing compliance: PASS\n"
        "- Derating [PASS]: capacitor voltage: utilization 48% is within the 80% "
        "derating limit.\n"
        "- AVL [PASS]: Murata is on the approved-vendor list."
    )


def test_check_derating_compliance_preserves_warning_and_error_behavior() -> None:
    service = _service(FakeClient([]), [])

    warning = service.check_derating_compliance("resistor", "power", 1.0, 0.58)
    assert warning.startswith("Part sourcing compliance: WARN\n- Derating [WARN]:")
    assert "- AVL [WARN]: No approved-vendor list configured — AVL not enforced." in warning

    failure = service.check_derating_compliance("unobtanium", "flux", 1.0, 0.1)
    assert failure.startswith("Derating check failed: No derating policy for 'unobtanium'/'flux'.")
