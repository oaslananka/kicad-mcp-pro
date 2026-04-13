from __future__ import annotations

from kicad_mcp.utils.component_search import ComponentRecord, JLCSearchClient, normalize_lcsc_code


def test_normalize_lcsc_code_accepts_bare_digits() -> None:
    assert normalize_lcsc_code("25804") == "C25804"
    assert normalize_lcsc_code(25804) == "C25804"
    assert normalize_lcsc_code("C17414") == "C17414"


def test_jlcsearch_search_parses_component_records(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search._request_json",
        lambda url, params: {
            "components": [
                {
                    "lcsc": 25804,
                    "mfr": "0603WAF1002T5E",
                    "package": "0603",
                    "description": "10k resistor",
                    "stock": 37165617,
                    "price": 0.000842857,
                    "is_basic": True,
                    "is_preferred": False,
                }
            ]
        },
    )

    result = JLCSearchClient().search("10k resistor")

    assert len(result) == 1
    assert result[0].lcsc_code == "C25804"
    assert result[0].mpn == "0603WAF1002T5E"
    assert result[0].is_basic is True


def test_jlcsearch_get_part_prefers_exact_lcsc_match(monkeypatch) -> None:
    records = [
        ComponentRecord(
            source="jlcsearch",
            lcsc_code="C17414",
            mpn="0805W8F1002T5E",
            package="0805",
            description="10k resistor",
            stock=100,
            price=0.0016,
            is_basic=True,
            is_preferred=False,
        ),
        ComponentRecord(
            source="jlcsearch",
            lcsc_code="C25804",
            mpn="0603WAF1002T5E",
            package="0603",
            description="10k resistor",
            stock=100,
            price=0.0008,
            is_basic=True,
            is_preferred=False,
        ),
    ]
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search.JLCSearchClient.search",
        lambda self, keyword, **kwargs: records,
    )

    part = JLCSearchClient().get_part("25804")

    assert part is not None
    assert part.lcsc_code == "C25804"
