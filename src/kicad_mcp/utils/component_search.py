"""Live component search helpers."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, Protocol, cast

# Transport seam: (url, body, headers) -> decoded JSON. Injectable so the live
# distributor clients can be unit-tested without touching the network.
HttpPostJson = Callable[[str, bytes, dict[str, str]], dict[str, Any]]

DEFAULT_USER_AGENT = "kicad-mcp-pro/1.0 (+https://github.com/oaslananka/kicad-mcp-pro)"


@dataclass(frozen=True)
class ComponentRecord:
    """Normalized part record returned by live search providers."""

    source: str
    lcsc_code: str
    mpn: str
    package: str
    description: str
    stock: int
    price: float | None
    is_basic: bool
    is_preferred: bool
    # Sourcing/compliance metadata (populated when the provider reports it).
    lifecycle: str = ""
    rohs: str = ""
    # Direct datasheet URL (populated when the provider reports it).
    datasheet_url: str = ""


class ComponentSearchClient(Protocol):
    """Protocol shared by live part search providers."""

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        raise NotImplementedError

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        raise NotImplementedError


class RateLimiter:
    """Simple synchronous sliding-window limiter for external component APIs."""

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.calls: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self.calls and now - self.calls[0] > self.period_seconds:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            wait_seconds = self.period_seconds - (now - self.calls[0])
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            now = time.monotonic()
            while self.calls and now - self.calls[0] > self.period_seconds:
                self.calls.popleft()
        self.calls.append(time.monotonic())


_jlcsearch_limiter = RateLimiter(max_calls=5, period_seconds=1.0)


def normalize_lcsc_code(value: str | int) -> str:
    """Normalize a user-supplied LCSC identifier."""
    raw = str(value).strip().upper()
    if raw.startswith("C"):
        suffix = raw[1:]
    else:
        suffix = raw
    return f"C{suffix}" if suffix.isdigit() else raw


def _request_json(url: str, params: dict[str, object]) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {key: value for key, value in params.items() if value not in (None, "")}
    )
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only https component-search endpoints are permitted.")
    request = urllib.request.Request(  # noqa: S310 - scheme is validated above
        f"{url}?{query}",
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310  # nosec B310
        return cast(dict[str, Any], json.load(response))


def _record_from_jlcsearch(item: dict[str, Any]) -> ComponentRecord:
    raw_lcsc = item.get("lcsc", "")
    return ComponentRecord(
        source="jlcsearch",
        lcsc_code=normalize_lcsc_code(raw_lcsc),
        mpn=str(item.get("mfr", "")),
        package=str(item.get("package", "")),
        description=str(item.get("description", "")),
        stock=int(item.get("stock", 0) or 0),
        price=float(item["price"]) if item.get("price") is not None else None,
        is_basic=bool(item.get("is_basic", False)),
        is_preferred=bool(item.get("is_preferred", False)),
    )


class JLCSearchClient:
    """Zero-auth live search against jlcsearch.tscircuit.com."""

    BASE = "https://jlcsearch.tscircuit.com"
    JLCPCB_BASE = "https://jlcpcb.com"

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        _jlcsearch_limiter.acquire()
        payload = _request_json(
            f"{self.BASE}/api/search",
            {
                "q": keyword,
                "package": package,
                "limit": str(limit),
                "is_basic": "true" if only_basic else None,
            },
        )
        records = [_record_from_jlcsearch(item) for item in payload.get("components", [])]
        if records:
            return records
        fallback = self._search_jlcpcb_public(keyword, limit=limit)
        if only_basic:
            fallback = [item for item in fallback if item.is_basic]
        if package:
            package_folded = package.casefold()
            fallback = [
                item
                for item in fallback
                if package_folded in item.package.casefold()
                or package_folded in item.description.casefold()
            ]
        return fallback[:limit]

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        query = normalize_lcsc_code(lcsc_code_or_mpn)
        results = self.search(query, only_basic=False, limit=10)
        lcsc_matches = [item for item in results if item.lcsc_code == query]
        if lcsc_matches:
            return lcsc_matches[0]

        raw_query = lcsc_code_or_mpn.strip()
        for item in results:
            if item.mpn.casefold() == raw_query.casefold():
                return item
        if query.startswith("C") and query[1:].isdigit():
            return self._get_jlcpcb_public_part(query)
        public_matches = self._search_jlcpcb_public(raw_query, limit=10)
        for item in public_matches:
            if item.mpn.casefold() == raw_query.casefold():
                return item
        return None

    def _request_text(self, url: str, params: dict[str, object] | None = None) -> str:
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value not in (None, "")}
        )
        target = f"{url}?{query}" if query else url
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme != "https" or parsed.netloc not in {"jlcpcb.com", "www.jlcpcb.com"}:
            raise ValueError("Only https JLCPCB public endpoints are permitted.")
        request = urllib.request.Request(  # noqa: S310 - endpoint allow-list is enforced above
            target,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310  # nosec B310
            return cast(bytes, response.read()).decode("utf-8", errors="replace")

    def _search_jlcpcb_public(self, keyword: str, *, limit: int) -> list[ComponentRecord]:
        if not keyword.strip():
            return []
        try:
            html = self._request_text(
                f"{self.JLCPCB_BASE}/parts/componentSearch",
                {"isSearch": "true", "searchTxt": keyword.strip()},
            )
        except (OSError, ValueError):
            return []
        codes = []
        for match in re.finditer(r'componentCode:"(C\d+)"', html):
            code = match.group(1)
            if code not in codes:
                codes.append(code)
            if len(codes) >= limit:
                break
        return [
            record for code in codes if (record := self._get_jlcpcb_public_part(code)) is not None
        ][:limit]

    def _get_jlcpcb_public_part(self, lcsc_code: str) -> ComponentRecord | None:
        try:
            html = self._request_text(f"{self.JLCPCB_BASE}/partdetail/-/{lcsc_code}")
        except (OSError, ValueError):
            return None
        return _record_from_jlcpcb_detail_page(html, lcsc_code)


def _plain_text_lines(html: str) -> list[str]:
    parser = _VisibleTextParser()
    parser.feed(html)
    parser.close()
    return parser.lines


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._chunks: list[str] = []

    @property
    def lines(self) -> list[str]:
        return [line.strip() for line in "\n".join(self._chunks).splitlines() if line.strip()]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._chunks.append(data)


def _line_after_label(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        if line == label and index + 1 < len(lines):
            return lines[index + 1]
    return ""


def _record_from_jlcpcb_detail_page(html: str, lcsc_code: str) -> ComponentRecord | None:
    if lcsc_code not in html:
        return None
    lines = _plain_text_lines(html)
    full_text = "\n".join(lines)
    title_match = re.search(r"<title>([^|<]+)", html, re.IGNORECASE)
    mpn = _line_after_label(lines, "MFR.Part #") or (
        unescape(title_match.group(1)).strip() if title_match else ""
    )
    package = _line_after_label(lines, "Package")
    description = _line_after_label(lines, "Description")
    library_type = " ".join(lines[:80]).casefold()
    stock_match = re.search(r"In Stock:\s*([\d,]+)", full_text, re.IGNORECASE)
    price_match = re.search(r"1\+\s*\$([0-9.]+)", full_text)
    lifecycle = ""
    rohs = ""
    datasheet_url = ""
    for line in lines:
        lower = line.strip().casefold()
        if not lifecycle and lower.startswith("lifecycle"):
            lifecycle = line.split(":", 1)[-1].strip()
        if not rohs and lower.startswith("rohs"):
            rohs = line.split(":", 1)[-1].strip()
        if not datasheet_url and lower.startswith("datasheet"):
            parts = line.split(":", 1)
            if len(parts) > 1 and parts[1].strip():
                datasheet_url = parts[1].strip()
    # Also try to find datasheet URL in HTML href attributes
    if not datasheet_url:
        ds_match = re.search(r'href="(https?://[^"]*datasheet[^"]*)"', html, re.IGNORECASE)
        if ds_match:
            datasheet_url = ds_match.group(1)
    return ComponentRecord(
        source="jlcpcb-public",
        lcsc_code=normalize_lcsc_code(lcsc_code),
        mpn=mpn,
        package=package,
        description=description,
        stock=int(stock_match.group(1).replace(",", "")) if stock_match else 0,
        price=float(price_match.group(1)) if price_match else None,
        is_basic="basic" in library_type and "extended" not in library_type,
        is_preferred=False,
        lifecycle=lifecycle,
        rohs=rohs,
        datasheet_url=datasheet_url,
    )


def _https_post_json(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """POST ``body`` to an https URL and decode the JSON response."""
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("Only https distributor endpoints are permitted.")
    merged = {"User-Agent": DEFAULT_USER_AGENT, **headers}
    request = urllib.request.Request(url, data=body, headers=merged, method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310  # nosec B310
        return cast(dict[str, Any], json.load(response))


_NEXAR_SEARCH_QUERY = (
    "query KicadMcpSearch($q: String!, $limit: Int!) {"
    "  supSearchMpn(q: $q, limit: $limit) {"
    "    results {"
    "      part {"
    "        mpn"
    "        manufacturer { name }"
    "        shortDescription"
    "        totalAvail"
    "        medianPrice1000 { price }"
    "        specs { attribute { name } displayValue }"
    "      }"
    "    }"
    "  }"
    "}"
)

_nexar_limiter = RateLimiter(max_calls=5, period_seconds=1.0)


def _record_from_nexar(part: dict[str, Any]) -> ComponentRecord:
    manufacturer = str((part.get("manufacturer") or {}).get("name", ""))
    price: float | None = None
    median = part.get("medianPrice1000")
    if isinstance(median, dict) and median.get("price") is not None:
        price = float(median["price"])
    package = ""
    lifecycle = ""
    rohs = ""
    datasheet_url = ""
    for spec in part.get("specs") or []:
        attribute = str((spec.get("attribute") or {}).get("name", "")).casefold()
        value = str(spec.get("displayValue", ""))
        if not package and attribute in ("case/package", "package", "case / package"):
            package = value
        elif not lifecycle and "lifecycle" in attribute:
            lifecycle = value
        elif not rohs and ("rohs" in attribute or "reach" in attribute):
            rohs = value
        elif not datasheet_url and "datasheet" in attribute and value.startswith("http"):
            datasheet_url = value
    # Nexar supply API may also provide a bestDatasheet URL at the part level.
    if not datasheet_url:
        datasheet_url = str(part.get("bestDatasheet", part.get("datasheet", "")))
    description = str(part.get("shortDescription") or "").strip() or manufacturer
    return ComponentRecord(
        source="nexar",
        lcsc_code="",
        mpn=str(part.get("mpn", "")),
        package=package,
        description=description,
        stock=int(part.get("totalAvail", 0) or 0),
        price=price,
        is_basic=False,
        is_preferred=False,
        lifecycle=lifecycle,
        rohs=rohs,
        datasheet_url=datasheet_url,
    )


class NexarClient:
    """Live Nexar Supply (Octopart) GraphQL client.

    Authenticates with the OAuth2 ``client_credentials`` grant against
    ``identity.nexar.com`` and queries ``supSearchMpn`` on the Supply API. Requires
    ``NEXAR_CLIENT_ID`` / ``NEXAR_CLIENT_SECRET`` (loaded from ``.env`` at server
    startup) and an app subscribed to the Supply API. ``transport`` is injectable
    so the OAuth + GraphQL flow is unit-testable without the network.
    """

    ENDPOINT = "https://api.nexar.com/graphql"
    TOKEN_URL = "https://identity.nexar.com/connect/token"  # noqa: S105

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        transport: HttpPostJson | None = None,
    ) -> None:
        self._client_id = client_id if client_id is not None else os.getenv("NEXAR_CLIENT_ID")
        self._client_secret = (
            client_secret if client_secret is not None else os.getenv("NEXAR_CLIENT_SECRET")
        )
        self._transport = transport or _https_post_json
        self._token: str | None = None
        self._token_expiry = 0.0

    def _require_credentials(self) -> tuple[str, str]:
        if not self._client_id or not self._client_secret:
            raise RuntimeError("Nexar search requires NEXAR_CLIENT_ID and NEXAR_CLIENT_SECRET.")
        return self._client_id, self._client_secret

    def _access_token(self) -> str:
        now = time.monotonic()
        if self._token is not None and now < self._token_expiry:
            return self._token
        client_id, client_secret = self._require_credentials()
        _nexar_limiter.acquire()
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode("utf-8")
        response = self._transport(
            self.TOKEN_URL,
            body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = response.get("access_token")
        if not token:
            raise RuntimeError("Nexar token endpoint did not return an access_token.")
        self._token = str(token)
        # Refresh a minute early to avoid using a token that expires mid-request.
        self._token_expiry = now + float(response.get("expires_in", 3600)) - 60.0
        return self._token

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        _ = only_basic
        self._require_credentials()
        token = self._access_token()
        _nexar_limiter.acquire()
        capped = max(1, min(limit, 20))
        body = json.dumps(
            {"query": _NEXAR_SEARCH_QUERY, "variables": {"q": keyword, "limit": capped}}
        ).encode("utf-8")
        response = self._transport(
            self.ENDPOINT,
            body,
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        errors = response.get("errors")
        if errors:
            if isinstance(errors, list) and errors:
                message = errors[0].get("message", "unknown error")
            else:
                message = str(errors)
            lowered = message.casefold()
            if "part limit" in lowered or "upgrade your plan" in lowered:
                raise RuntimeError(
                    f"Nexar part-lookup quota reached: {message} Use source='jlcsearch' "
                    "(zero-auth) for local work, or upgrade/await reset of the Nexar plan."
                )
            raise RuntimeError(f"Nexar GraphQL error: {message}")
        results = ((response.get("data") or {}).get("supSearchMpn") or {}).get("results") or []
        records = [_record_from_nexar(entry.get("part") or {}) for entry in results]
        if package:
            needle = package.casefold()
            records = [record for record in records if needle in record.package.casefold()]
        return records[:limit]

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        self._require_credentials()
        results = self.search(lcsc_code_or_mpn, limit=5)
        needle = lcsc_code_or_mpn.strip().casefold()
        for record in results:
            if record.mpn.casefold() == needle:
                return record
        return results[0] if results else None


_digikey_limiter = RateLimiter(max_calls=5, period_seconds=1.0)


def _record_from_digikey(product: dict[str, Any]) -> ComponentRecord:
    mpn = str(product.get("ManufacturerProductNumber", ""))
    manufacturer = str((product.get("Manufacturer") or {}).get("Name", ""))
    description = (
        str((product.get("Description") or {}).get("ProductDescription", "")).strip()
        or manufacturer
    )
    price_raw = product.get("UnitPrice")
    price = float(price_raw) if isinstance(price_raw, (int, float)) else None
    package = ""
    for param in product.get("Parameters") or []:
        text = str(param.get("ParameterText", "")).casefold()
        if text in ("package / case", "supplier device package", "package"):
            package = str(param.get("ValueText", ""))
            break
    # DigiKey may report datasheet URL; try a few common field names.
    datasheet_url = str(product.get("DatasheetUrl", product.get("PrimaryDatasheetUrl", "")))
    return ComponentRecord(
        source="digikey",
        lcsc_code="",
        mpn=mpn,
        package=package,
        description=description,
        stock=int(product.get("QuantityAvailable", 0) or 0),
        price=price,
        is_basic=False,
        is_preferred=False,
        datasheet_url=datasheet_url,
    )


class DigiKeyClient:
    """Live DigiKey Product Information (v4) client.

    Authenticates with the OAuth2 ``client_credentials`` grant and queries the v4
    keyword-search endpoint. Requires ``DIGIKEY_CLIENT_ID`` / ``DIGIKEY_CLIENT_SECRET``
    (loaded from ``.env`` at server startup) for an app subscribed to the Product
    Information API. ``transport`` is injectable so the OAuth + search flow is
    unit-tested without the network. The response schema follows DigiKey API v4; run
    a live smoke test to confirm field mapping against the production response.
    """

    TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"  # noqa: S105
    SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        transport: HttpPostJson | None = None,
    ) -> None:
        self._client_id = client_id if client_id is not None else os.getenv("DIGIKEY_CLIENT_ID")
        self._client_secret = (
            client_secret if client_secret is not None else os.getenv("DIGIKEY_CLIENT_SECRET")
        )
        self._transport = transport or _https_post_json
        self._token: str | None = None
        self._token_expiry = 0.0

    def _require_credentials(self) -> tuple[str, str]:
        if not self._client_id or not self._client_secret:
            raise RuntimeError(
                "DigiKey search requires DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET."
            )
        return self._client_id, self._client_secret

    def _access_token(self) -> str:
        now = time.monotonic()
        if self._token is not None and now < self._token_expiry:
            return self._token
        client_id, client_secret = self._require_credentials()
        _digikey_limiter.acquire()
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode("utf-8")
        response = self._transport(
            self.TOKEN_URL,
            body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        token = response.get("access_token")
        if not token:
            raise RuntimeError("DigiKey token endpoint did not return an access_token.")
        self._token = str(token)
        self._token_expiry = now + float(response.get("expires_in", 600)) - 60.0
        return self._token

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        _ = only_basic
        client_id, _secret = self._require_credentials()
        token = self._access_token()
        _digikey_limiter.acquire()
        capped = max(1, min(limit, 50))
        body = json.dumps({"Keywords": keyword, "Limit": capped, "Offset": 0}).encode("utf-8")
        response = self._transport(
            self.SEARCH_URL,
            body,
            {
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": client_id,
                "Content-Type": "application/json",
            },
        )
        products = response.get("Products") or []
        records = [_record_from_digikey(product) for product in products]
        if package:
            needle = package.casefold()
            records = [record for record in records if needle in record.package.casefold()]
        return records[:limit]

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        self._require_credentials()
        results = self.search(lcsc_code_or_mpn, limit=5)
        needle = lcsc_code_or_mpn.strip().casefold()
        for record in results:
            if record.mpn.casefold() == needle:
                return record
        return results[0] if results else None


_mouser_limiter = RateLimiter(max_calls=5, period_seconds=1.0)


def _parse_mouser_price(price_breaks: list[dict[str, Any]]) -> float | None:
    if not price_breaks:
        return None
    raw = str(price_breaks[0].get("Price", "")).replace("$", "").replace(",", "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _record_from_mouser(part: dict[str, Any]) -> ComponentRecord:
    manufacturer = str(part.get("Manufacturer", ""))
    stock_digits = "".join(ch for ch in str(part.get("AvailabilityInStock", "")) if ch.isdigit())
    return ComponentRecord(
        source="mouser",
        lcsc_code="",
        mpn=str(part.get("ManufacturerPartNumber", "")),
        package="",
        description=str(part.get("Description", "")).strip() or manufacturer,
        stock=int(stock_digits or 0),
        price=_parse_mouser_price(part.get("PriceBreaks") or []),
        is_basic=False,
        is_preferred=False,
        lifecycle=str(part.get("LifecycleStatus", "")),
        rohs=str(part.get("ROHSStatus", "")),
        datasheet_url=str(part.get("DataSheetUrl", "")),
    )


class MouserClient:
    """Live Mouser keyword-search client.

    Mouser authenticates with an API key (``MOUSER_API_KEY``, loaded from ``.env``
    at server startup) passed as a query parameter, not OAuth. ``transport`` is
    injectable so the search flow is unit-tested without the network.
    """

    SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"

    def __init__(
        self, api_key: str | None = None, *, transport: HttpPostJson | None = None
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("MOUSER_API_KEY")
        self._transport = transport or _https_post_json

    def _require_key(self) -> str:
        if not self._api_key:
            raise RuntimeError("Mouser search requires MOUSER_API_KEY.")
        return self._api_key

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        _ = only_basic
        api_key = self._require_key()
        _mouser_limiter.acquire()
        url = f"{self.SEARCH_URL}?apiKey={urllib.parse.quote(api_key)}"
        body = json.dumps(
            {"SearchByKeywordRequest": {"keyword": keyword, "records": max(1, min(limit, 50))}}
        ).encode("utf-8")
        response = self._transport(url, body, {"Content-Type": "application/json"})
        errors = response.get("Errors")
        if errors:
            if isinstance(errors, list) and errors:
                message = errors[0].get("Message", "unknown error")
            else:
                message = str(errors)
            raise RuntimeError(f"Mouser API error: {message}")
        parts = ((response.get("SearchResults") or {}).get("Parts")) or []
        records = [_record_from_mouser(part) for part in parts]
        if package:
            needle = package.casefold()
            records = [record for record in records if needle in record.description.casefold()]
        return records[:limit]

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        self._require_key()
        results = self.search(lcsc_code_or_mpn, limit=5)
        needle = lcsc_code_or_mpn.strip().casefold()
        for record in results:
            if record.mpn.casefold() == needle:
                return record
        return results[0] if results else None
