from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from kicad_mcp.library.sourcing import LibrarySourcingService
from kicad_mcp.utils.component_search import ComponentRecord, ComponentSearchClient


def _record(
    *,
    code: str = "C123",
    mpn: str | None = None,
    stock: int = 100,
    price: float | None = 0.05,
    package: str = "SOT-23",
    description: str = "5V regulator",
    lifecycle: str = "Active",
    rohs: str = "Yes",
) -> ComponentRecord:
    return ComponentRecord(
        source="jlcsearch",
        lcsc_code=code,
        mpn=mpn or f"MPN-{code}",
        package=package,
        description=description,
        stock=stock,
        price=price,
        is_basic=True,
        is_preferred=False,
        lifecycle=lifecycle,
        rohs=rohs,
    )


class FakeClient:
    def __init__(
        self,
        records: list[ComponentRecord] | None = None,
        parts: dict[str, ComponentRecord | None] | None = None,
    ) -> None:
        self.records = records or []
        self.parts = parts or {}
        self.search_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls: list[str] = []

    def search(
        self,
        query: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        self.search_calls.append(
            (query, {"package": package, "only_basic": only_basic, "limit": limit})
        )
        return list(self.records)

    def get_part(self, identifier: str) -> ComponentRecord | None:
        self.get_calls.append(identifier)
        return self.parts.get(identifier)


def _service(
    client: FakeClient,
    *,
    rows: list[dict[str, str]] | None = None,
    grouped_rows: list[dict[str, Any]] | None = None,
    lookup_component: Callable[..., ComponentRecord | None] | None = None,
    schematic_component_rows: Callable[[], list[dict[str, str]]] | None = None,
    component_search_client: Callable[[str], ComponentSearchClient] | None = None,
) -> LibrarySourcingService:
    source_rows = rows or []
    grouped = grouped_rows if grouped_rows is not None else []
    client_factory: Callable[[str], ComponentSearchClient] = component_search_client or (
        lambda _source: client
    )
    return LibrarySourcingService(
        component_search_client=client_factory,
        parse_passive_parametric_query=lambda *_args, **_kwargs: None,
        rank_passive_parametric_results=lambda results, _query: (list(results), {}),
        format_passive_parametric_lines=lambda heading, results, _evidence, **_kwargs: (
            heading + "\n" + ",".join(item.lcsc_code for item in results)
        ),
        sort_component_results=lambda results, **_kwargs: list(results),
        format_component_lines=lambda heading, results, **_kwargs: (
            heading + "\n" + ",".join(item.lcsc_code for item in results)
        ),
        max_items_per_response=lambda: 20,
        schematic_component_rows=schematic_component_rows or (lambda: list(source_rows)),
        group_bom_rows=lambda _rows: list(grouped),
        lookup_component=lookup_component or (lambda *_args, **_kwargs: None),
        update_symbol_property=lambda *_args: None,
    )


def test_search_components_preserves_filters_heading_and_stock_contract() -> None:
    compliant = _record(code="C1", stock=50, lifecycle="Active", rohs="RoHS compliant")
    eol = _record(code="C2", stock=100, lifecycle="EOL", rohs="No")
    client = FakeClient([compliant, eol])
    service = _service(client)

    result = service.search_components(
        keyword="LDO",
        rohs_compliant=True,
        lifecycle="active",
        min_stock=10,
    )

    assert client.search_calls == [("LDO", {"package": None, "only_basic": True, "limit": 20})]
    assert result == (
        "Live component matches for 'LDO' from jlcsearch "
        "[RoHS compliant only, lifecycle=active] (1 total):\nC1"
    )


def test_search_components_preserves_below_stock_explanation() -> None:
    client = FakeClient([_record(code="C1", stock=4)])
    service = _service(client)

    result = service.search_components(query="resistor", min_stock=10)

    assert result == (
        "Live component matches for 'resistor' from jlcsearch "
        "(1 total below min_stock=10):\n"
        "Matches exist, but all are below the requested stock threshold.\nC1"
    )


@pytest.mark.parametrize(
    ("lifecycle", "rohs", "expected", "finding_locations"),
    [
        ("Active", "Yes", "PASS", set()),
        ("", "", "WARN", {"lifecycle", "rohs"}),
        ("EOL", "No", "FAIL", {"lifecycle", "rohs"}),
    ],
)
def test_sourcing_policy_preserves_optional_metadata_verdicts(
    lifecycle: str,
    rohs: str,
    expected: str,
    finding_locations: set[str],
) -> None:
    part = _record(code="C10", lifecycle=lifecycle, rohs=rohs)
    service = _service(FakeClient(parts={"C10": part}))

    report = service.check_sourcing_policy(
        "C10",
        min_stock=10,
        max_unit_price=0.10,
        allowed_lifecycle=["Active"],
        require_rohs=True,
    )

    assert report.verdict == expected
    assert {finding.location for finding in report.findings} == finding_locations
    assert report.metadata["checks"] == ["stock", "price", "lifecycle", "rohs"]
    assert report.text.startswith(f"Sourcing policy verdict: {expected}\n- Part: C10 | MPN-C10")


def test_sourcing_policy_preserves_avl_warning_and_failure_precedence() -> None:
    part = _record(code="C11", stock=2, price=0.50)
    service = _service(FakeClient(parts={"C11": part}))

    report = service.check_sourcing_policy(
        "C11",
        min_stock=10,
        max_unit_price=0.10,
        approved_manufacturers=["ACME"],
    )

    assert report.verdict == "FAIL"
    assert {finding.location for finding in report.findings} == {"stock", "price", "avl"}
    assert "- avl [WARN]: approved_manufacturers configured" in report.text
    assert report.failure_mode == "design"


def test_bom_pricing_preserves_resolved_unresolved_rows_and_total() -> None:
    part = _record(code="C20", stock=1000, price=0.05)
    grouped_rows: list[dict[str, Any]] = [
        {"references": ["R1", "R2"], "lcsc": "C20", "value": "10k"},
        {"references": ["D1"], "lcsc": "", "value": "LED"},
    ]

    def lookup(_client: FakeClient, *, lcsc_code: str, value: str) -> ComponentRecord | None:
        assert value in {"10k", "LED"}
        return part if lcsc_code == "C20" else None

    service = _service(FakeClient(), grouped_rows=grouped_rows, lookup_component=lookup)

    result = service.get_bom_with_pricing(quantity=3)

    assert result == (
        "Live BOM with pricing from jlcsearch:\n"
        "- R1, R2 | C20 | MPN-C20 | qty 6 | stock 1,000 | unit $0.050000 | ext $0.300000\n"
        "- D1 | (unresolved) | LED (add LCSC field; value-only matching disabled) | "
        "qty 3 | stock n/a | unit (n/a) | ext (n/a)\n"
        "Estimated total: $0.300000"
    )


def test_bom_and_stock_keep_filenotfounderror_as_environment_failure() -> None:
    def missing_rows() -> list[dict[str, str]]:
        raise FileNotFoundError("schematic vanished")

    service = _service(FakeClient(), schematic_component_rows=missing_rows)

    assert service.get_bom_with_pricing() == "Live BOM generation failed: schematic vanished"
    assert (
        service.check_stock_availability(refs=["R1"])
        == "Stock availability check failed: schematic vanished"
    )


def test_stock_availability_preserves_client_filenotfounderror_as_environment_failure() -> None:
    def missing_client(_source: str) -> ComponentSearchClient:
        raise FileNotFoundError("provider executable vanished")

    service = _service(FakeClient(), component_search_client=missing_client)

    assert (
        service.check_stock_availability(refs=["R1"])
        == "Stock availability check failed: provider executable vanished"
    )


def test_stock_availability_preserves_direct_mpn_rendering() -> None:
    part = _record(code="C30", mpn="LM1117-3.3", stock=5000, price=0.0123)
    client = FakeClient(parts={"LM1117-3.3": part, "MISSING": None})
    service = _service(client)

    result = service.check_stock_availability(mpns=[" LM1117-3.3 ", "MISSING"])

    assert client.get_calls == ["LM1117-3.3", "MISSING"]
    assert result == (
        "Stock availability from jlcsearch:\n"
        "- LM1117-3.3: C30 | LM1117-3.3 | stock 5,000 | $0.012300\n"
        "- MISSING: unresolved (no matching part found)"
    )


def test_stock_availability_preserves_reference_lookup_rendering() -> None:
    part = _record(code="C40", stock=42, price=None)
    rows = [
        {"reference": "R1", "lcsc": "C40", "value": "10k"},
        {"reference": "D1", "lcsc": "", "value": "LED"},
    ]

    def lookup(_client: FakeClient, *, lcsc_code: str, value: str) -> ComponentRecord | None:
        assert value in {"10k", "LED"}
        return part if lcsc_code == "C40" else None

    service = _service(FakeClient(), rows=rows, lookup_component=lookup)

    result = service.check_stock_availability(refs=["r1", "D1"])

    assert result == (
        "Stock availability from jlcsearch:\n"
        "- R1: C40 | MPN-C40 | stock 42 | (n/a)\n"
        "- D1: unresolved (LED; add an LCSC field)"
    )
