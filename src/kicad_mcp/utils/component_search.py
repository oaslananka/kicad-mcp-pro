"""Live component search helpers."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, cast

DEFAULT_USER_AGENT = "kicad-mcp-pro/2.0 (+https://github.com/oaslananka/kicad-mcp-pro)"


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


class ComponentSearchClient(Protocol):
    """Protocol shared by live part search providers."""

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]: ...

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None: ...


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

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        payload = _request_json(
            f"{self.BASE}/api/search",
            {
                "q": keyword,
                "package": package,
                "limit": str(limit),
                "is_basic": "true" if only_basic else None,
            },
        )
        return [_record_from_jlcsearch(item) for item in payload.get("components", [])]

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
        return results[0] if results else None


class NexarClient:
    """Optional Nexar GraphQL client."""

    ENDPOINT = "https://api.nexar.com/graphql"
    TOKEN_URL = "https://identity.nexar.com/connect/token"  # noqa: S105

    def __init__(self) -> None:
        self._client_id = os.getenv("NEXAR_CLIENT_ID")
        self._client_secret = os.getenv("NEXAR_CLIENT_SECRET")

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        _ = (package, only_basic, limit)
        if not self._client_id or not self._client_secret:
            raise RuntimeError(
                "Nexar search requires NEXAR_CLIENT_ID and NEXAR_CLIENT_SECRET."
            )
        raise RuntimeError(
            "Nexar live search is reserved for authenticated deployments. "
            f"Use the zero-auth 'jlcsearch' source for local usage. Query was: {keyword}"
        )

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        _ = lcsc_code_or_mpn
        raise RuntimeError("Nexar component detail lookups require authenticated deployment.")


class DigiKeyClient:
    """Optional DigiKey client placeholder."""

    def __init__(self) -> None:
        self._client_id = os.getenv("DIGIKEY_CLIENT_ID")
        self._client_secret = os.getenv("DIGIKEY_CLIENT_SECRET")

    def search(
        self,
        keyword: str,
        *,
        package: str | None = None,
        only_basic: bool = True,
        limit: int = 20,
    ) -> list[ComponentRecord]:
        _ = (package, only_basic, limit)
        if not self._client_id or not self._client_secret:
            raise RuntimeError(
                "DigiKey search requires DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET."
            )
        raise RuntimeError(
            "DigiKey live search wiring is not enabled in the default zero-auth profile. "
            f"Query was: {keyword}"
        )

    def get_part(self, lcsc_code_or_mpn: str) -> ComponentRecord | None:
        _ = lcsc_code_or_mpn
        raise RuntimeError("DigiKey component detail lookups require authenticated deployment.")
