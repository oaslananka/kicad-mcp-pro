from __future__ import annotations

from kicad_mcp.library.sourcing import LibrarySourcingService
from kicad_mcp.utils.component_search import ComponentRecord


def _record(*, code: str = "C123", stock: int = 100, package: str = "SOT-23") -> ComponentRecord:
    return ComponentRecord(
        source="jlcsearch",
        lcsc_code=code,
        mpn=f"MPN-{code}",
        package=package,
        description="5V 1A regulator",
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


def _service(client: FakeClient, updates: list[tuple[str, str, str]]) -> LibrarySourcingService:
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
        update_symbol_property=lambda ref, field, value: updates.append((ref, field, value)),
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
