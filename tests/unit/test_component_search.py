from __future__ import annotations

import io

import pytest

from kicad_mcp import utils
from kicad_mcp.utils.component_search import (
    DEFAULT_USER_AGENT,
    ComponentRecord,
    DigiKeyClient,
    JLCSearchClient,
    MouserClient,
    NexarClient,
    RateLimiter,
    _parse_mouser_currency,
    _parse_mouser_price,
    _parse_price_text,
    _plain_text_lines,
    _request_json,
    format_price,
    normalize_lcsc_code,
)


def test_public_utils_exports_all_live_component_clients() -> None:
    assert utils.JLCSearchClient is JLCSearchClient
    assert utils.NexarClient is NexarClient
    assert utils.DigiKeyClient is DigiKeyClient
    assert utils.MouserClient is MouserClient


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
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search.JLCSearchClient._search_jlcpcb_public",
        lambda self, keyword, *, limit: [],
    )

    part = JLCSearchClient().get_part("25804")

    assert part is not None
    assert part.lcsc_code == "C25804"


def test_request_json_rejects_non_https_urls() -> None:
    with pytest.raises(ValueError, match="Only https"):
        _request_json("http://example.com/search", {"q": "10k"})


def test_request_json_builds_expected_request(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeResponse(io.StringIO):
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            _ = (exc_type, exc, tb)

    def fake_urlopen(request, timeout: int):
        seen["url"] = request.full_url
        seen["user_agent"] = request.headers["User-agent"]
        seen["timeout"] = timeout
        return FakeResponse('{"components": []}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    payload = _request_json("https://example.com/search", {"q": "10k", "limit": 5, "empty": ""})

    assert payload == {"components": []}
    assert seen["url"] == "https://example.com/search?q=10k&limit=5"
    assert seen["user_agent"] == DEFAULT_USER_AGENT
    assert seen["timeout"] == 20


def test_jlcsearch_get_part_falls_back_to_exact_mpn_only(monkeypatch) -> None:
    records = [
        ComponentRecord(
            source="jlcsearch",
            lcsc_code="C11111",
            mpn="ABC-123",
            package="SOT-23",
            description="driver",
            stock=5,
            price=None,
            is_basic=False,
            is_preferred=False,
        ),
        ComponentRecord(
            source="jlcsearch",
            lcsc_code="C22222",
            mpn="XYZ-999",
            package="SOT-23",
            description="driver",
            stock=5,
            price=None,
            is_basic=False,
            is_preferred=False,
        ),
    ]
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search.JLCSearchClient.search",
        lambda self, keyword, **kwargs: records,
    )
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search.JLCSearchClient._search_jlcpcb_public",
        lambda self, keyword, *, limit: [],
    )

    assert JLCSearchClient().get_part("abc-123").mpn == "ABC-123"
    assert JLCSearchClient().get_part("unmatched") is None

    monkeypatch.setattr(
        "kicad_mcp.utils.component_search.JLCSearchClient.search",
        lambda self, keyword, **kwargs: [],
    )
    assert JLCSearchClient().get_part("unmatched") is None


def test_jlcsearch_public_detail_fallback_parses_extended_lcsc_code(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search._request_json",
        lambda _url, _params: {"components": []},
    )

    html = """
    <html><head><title>SSI2164 | JLCPCB Assembly | New Arrivals | JLCPCB</title></head>
    <body>
    <h1>SSI2164</h1><p>Extended</p>
    <div>MFR.Part #</div><div>SSI2164</div>
    <div>JLCPCB Part #</div><div>C9900088938</div>
    <div>Package</div><div>SOIC-16</div>
    <div>Description</div><div>SOIC-16 New Arrivals ROHS</div>
    <div>In Stock: 0</div><div>1+ $0.0365</div>
    </body></html>
    """
    monkeypatch.setattr(
        "kicad_mcp.utils.component_search.JLCSearchClient._request_text",
        lambda self, url, params=None: html,
    )

    part = JLCSearchClient().get_part("C9900088938")

    assert part is not None
    assert part.lcsc_code == "C9900088938"
    assert part.mpn == "SSI2164"
    assert part.package == "SOIC-16"
    assert part.is_basic is False


def test_plain_text_lines_ignores_script_tags_with_spaced_end_tags() -> None:
    lines = _plain_text_lines(
        """
        <html>
          <script>dangerousText()</script >
          <style>.hidden { color: red; }</style >
          <body><h1>SSI2164</h1><p>C9900088938</p></body>
        </html>
        """
    )

    assert "SSI2164" in lines
    assert "C9900088938" in lines
    assert all("dangerousText" not in line for line in lines)
    assert all("hidden" not in line for line in lines)


def test_optional_search_clients_raise_clear_messages(monkeypatch) -> None:
    monkeypatch.delenv("NEXAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("NEXAR_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="NEXAR_CLIENT_ID"):
        NexarClient().search("accelerometer")
    with pytest.raises(RuntimeError, match="NEXAR_CLIENT_ID"):
        NexarClient().get_part("C12345")

    monkeypatch.delenv("DIGIKEY_CLIENT_ID", raising=False)
    monkeypatch.delenv("DIGIKEY_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="DIGIKEY_CLIENT_ID"):
        DigiKeyClient().search("buzzer")
    with pytest.raises(RuntimeError, match="DIGIKEY_CLIENT_ID"):
        DigiKeyClient().get_part("C12345")


def test_digikey_search_parses_records_with_injected_transport() -> None:
    calls: list[str] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        calls.append(url)
        if url.endswith("/oauth2/token"):
            assert b"client_credentials" in body
            return {"access_token": "dk-tok", "expires_in": 600}
        assert headers.get("X-DIGIKEY-Client-Id") == "id"
        assert headers.get("Authorization") == "Bearer dk-tok"
        return {
            "Products": [
                {
                    "ManufacturerProductNumber": "LM358DR",
                    "Manufacturer": {"Name": "Texas Instruments"},
                    "Description": {"ProductDescription": "Op-amp dual"},
                    "QuantityAvailable": 125000,
                    "UnitPrice": 0.123,
                    "Parameters": [
                        {"ParameterText": "Package / Case", "ValueText": "8-SOIC"},
                    ],
                }
            ]
        }

    client = DigiKeyClient(client_id="id", client_secret="secret", transport=transport)  # noqa: S106
    records = client.search("LM358", limit=5)

    assert len(records) == 1
    record = records[0]
    assert record.source == "digikey"
    assert record.mpn == "LM358DR"
    assert record.package == "8-SOIC"
    assert record.stock == 125000
    assert record.price == 0.123
    assert calls[0].endswith("/oauth2/token")
    assert calls[1].endswith("/search/keyword")


def test_mouser_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MOUSER_API_KEY"):
        MouserClient().search("resistor")


def test_mouser_search_parses_records_with_injected_transport() -> None:
    seen_urls: list[str] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        seen_urls.append(url)
        return {
            "SearchResults": {
                "Parts": [
                    {
                        "ManufacturerPartNumber": "GRM188R71H104KA93D",
                        "Manufacturer": "Murata",
                        "Description": "CAP CER 0.1UF 50V X7R 0603",
                        "AvailabilityInStock": "125,000",
                        "PriceBreaks": [{"Price": "$0.018"}],
                        "LifecycleStatus": "Active",
                        "ROHSStatus": "RoHS Compliant",
                    }
                ]
            }
        }

    client = MouserClient(api_key="mk-123", transport=transport)
    records = client.search("0.1uF 0603", limit=5)

    assert len(records) == 1
    record = records[0]
    assert record.source == "mouser"
    assert record.mpn == "GRM188R71H104KA93D"
    assert record.stock == 125000  # comma-separated availability parsed
    assert record.price == 0.018
    assert record.lifecycle == "Active"
    # The API key is sent as a query parameter, not a header.
    assert "apiKey=mk-123" in seen_urls[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # US formatting (Mouser accounts registered in the US).
        ("$0.018", 0.018),
        ("$6.85", 6.85),
        ("$1,234.56", 1234.56),
        ("$1,234", 1234.0),
        ("$1,234,567.89", 1234567.89),
        # EU formatting (e.g. Mouser accounts registered in Germany).
        ("6,85 €", 6.85),
        ("0,018 €", 0.018),
        ("1.234,56 €", 1234.56),
        ("1.234 €", 1234.0),
        ("1 234,56 €", 1234.56),
        ("1\u00a0234,56\u00a0€", 1234.56),
        ("€6,85", 6.85),
        # Other currencies and plain numbers.
        ("£0.52", 0.52),
        ("CHF 1'234.50", 1234.5),
        ("0.5", 0.5),
        ("0,5", 0.5),
        ("12", 12.0),
    ],
)
def test_parse_price_text_handles_us_and_eu_formats(text: str, expected: float) -> None:
    assert _parse_price_text(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "n/a", "Quote", "€"])
def test_parse_price_text_returns_none_for_non_prices(text: str) -> None:
    assert _parse_price_text(text) is None


def test_parse_mouser_price_and_currency_from_price_breaks() -> None:
    eu = [
        {"Quantity": 1, "Price": "6,85 €", "Currency": "EUR"},
        {"Quantity": 10, "Price": "4,79 €"},
    ]
    assert _parse_mouser_price(eu) == pytest.approx(6.85)
    assert _parse_mouser_currency(eu) == "EUR"
    # Legacy payloads without a Currency field fall back to the symbol.
    assert _parse_mouser_currency([{"Price": "$0.018"}]) == "USD"
    assert _parse_mouser_currency([{"Price": "0,50 €"}]) == "EUR"
    assert _parse_mouser_price([]) is None
    assert _parse_mouser_currency([]) == ""


def test_mouser_search_parses_eu_localized_price() -> None:
    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        return {
            "SearchResults": {
                "Parts": [
                    {
                        "ManufacturerPartNumber": "STM32F103C8T6",
                        "Manufacturer": "STMicroelectronics",
                        "AvailabilityInStock": "4886",
                        "PriceBreaks": [
                            {"Quantity": 1, "Price": "6,85 €", "Currency": "EUR"},
                            {"Quantity": 10, "Price": "4,79 €", "Currency": "EUR"},
                        ],
                    }
                ]
            }
        }

    record = MouserClient(api_key="mk-123", transport=transport).search("STM32F103C8T6")[0]

    assert record.price == pytest.approx(6.85)
    assert record.currency == "EUR"


def test_format_price_keeps_dollar_prefix_for_usd_and_suffixes_other_currencies() -> None:
    assert format_price(0.05) == "$0.050000"
    assert format_price(0.05, "USD") == "$0.050000"
    assert format_price(6.85, "EUR") == "6.850000 EUR"
    assert format_price(None) == "(n/a)"
    assert format_price(None, "EUR", missing="n/a") == "n/a"


def test_mouser_api_error_surfaces() -> None:
    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        return {"Errors": [{"Message": "Invalid API key"}]}

    with pytest.raises(RuntimeError, match="Mouser API error: Invalid API key"):
        MouserClient(api_key="bad", transport=transport).search("x")


def test_digikey_token_is_cached_across_searches() -> None:
    calls: list[str] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        calls.append(url)
        if url.endswith("/oauth2/token"):
            return {"access_token": "dk", "expires_in": 600}
        return {"Products": []}

    client = DigiKeyClient(client_id="id", client_secret="secret", transport=transport)  # noqa: S106
    client.search("a")
    client.search("b")
    assert calls.count("https://api.digikey.com/v1/oauth2/token") == 1
    assert calls.count("https://api.digikey.com/products/v4/search/keyword") == 2


class _FakeNexarTransport:
    """Scripted OAuth + GraphQL transport for hermetic NexarClient tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        self.calls.append(url)
        if url.endswith("/connect/token"):
            assert b"client_credentials" in body
            return {"access_token": "tok-123", "expires_in": 3600}
        assert headers.get("Authorization") == "Bearer tok-123"
        return {
            "data": {
                "supSearchMpn": {
                    "results": [
                        {
                            "part": {
                                "mpn": "STM32F103C8T6",
                                "manufacturer": {"name": "STMicroelectronics"},
                                "shortDescription": "ARM Cortex-M3 MCU",
                                "totalAvail": 4200,
                                "medianPrice1000": {"price": 1.83},
                                "specs": [
                                    {
                                        "attribute": {"name": "Case/Package"},
                                        "displayValue": "LQFP-48",
                                    },
                                    {
                                        "attribute": {"name": "Lifecycle Status"},
                                        "displayValue": "Active",
                                    },
                                    {
                                        "attribute": {"name": "RoHS Status"},
                                        "displayValue": "Compliant",
                                    },
                                ],
                            }
                        }
                    ]
                }
            }
        }


def test_nexar_search_parses_records_with_injected_transport() -> None:
    transport = _FakeNexarTransport()
    client = NexarClient(client_id="id", client_secret="secret", transport=transport)  # noqa: S106
    records = client.search("STM32F103", limit=5)

    assert len(records) == 1
    record = records[0]
    assert record.source == "nexar"
    assert record.mpn == "STM32F103C8T6"
    assert record.package == "LQFP-48"
    assert record.stock == 4200
    assert record.price == 1.83
    # Sourcing/compliance metadata is parsed from the part specs.
    assert record.lifecycle == "Active"
    assert record.rohs == "Compliant"
    # OAuth token fetched, then the GraphQL query issued.
    assert transport.calls[0].endswith("/connect/token")
    assert transport.calls[1].endswith("/graphql")


def test_nexar_token_is_cached_across_searches() -> None:
    transport = _FakeNexarTransport()
    client = NexarClient(client_id="id", client_secret="secret", transport=transport)  # noqa: S106
    client.search("a")
    client.search("b")
    # One token call, two graphql calls — the token is reused, not re-fetched.
    assert transport.calls.count("https://identity.nexar.com/connect/token") == 1
    assert transport.calls.count("https://api.nexar.com/graphql") == 2


def test_nexar_graphql_errors_surface_as_runtime_error() -> None:
    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        if url.endswith("/connect/token"):
            return {"access_token": "t", "expires_in": 3600}
        return {"errors": [{"message": "rate limit exceeded"}]}

    client = NexarClient(client_id="id", client_secret="secret", transport=transport)  # noqa: S106
    with pytest.raises(RuntimeError, match="Nexar GraphQL error: rate limit exceeded"):
        client.search("anything")


def test_nexar_quota_limit_gives_actionable_error() -> None:
    def transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, object]:
        if url.endswith("/connect/token"):
            return {"access_token": "t", "expires_in": 3600}
        return {"errors": [{"message": "You have exceeded your part limit of 10."}]}

    client = NexarClient(client_id="id", client_secret="secret", transport=transport)  # noqa: S106
    with pytest.raises(RuntimeError, match="quota reached") as exc_info:
        client.search("anything")
    # Steers the caller to the zero-auth fallback rather than a bare GraphQL error.
    assert "jlcsearch" in str(exc_info.value)


def test_rate_limiter_waits_when_window_is_full(monkeypatch) -> None:
    timeline = iter([0.0, 0.0, 0.1, 0.1, 0.2, 1.3, 1.3])
    slept: list[float] = []

    monkeypatch.setattr("kicad_mcp.utils.component_search.time.monotonic", lambda: next(timeline))
    monkeypatch.setattr("kicad_mcp.utils.component_search.time.sleep", slept.append)

    limiter = RateLimiter(max_calls=2, period_seconds=1.0)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert slept and slept[0] > 0.0
