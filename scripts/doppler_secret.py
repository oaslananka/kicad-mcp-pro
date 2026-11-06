"""Read one requested secret from the protected Doppler main config.

This module does not export credentials to PR jobs or GitHub's runner
environment. A service token for main grants access to *all* main secrets:
use it only in a protected production workflow, never in pull requests.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

API = "https://api.doppler.com/v3/configs/config/secret"
PROJECT = "kicad-mcp-pro"
CONFIG = "main"
NAME = re.compile(r"[A-Z][A-Z0-9_]{1,95}\Z", re.ASCII)
MAX_RESPONSE = 65536


class SecretError(ValueError):
    """Deliberately redacted response; never echo a credential or server body."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: object,
        file: object,
        code: int,
        message: str,
        headers: dict[str, str],
        newurl: str,
    ) -> None:
        return None


def get_secret(
    name: str,
    *,
    token: str,
    project: str = PROJECT,
    config: str = CONFIG,
    opener: Callable[..., Any] | None = None,
) -> str:
    if not NAME.fullmatch(name) or project != PROJECT or config != CONFIG:
        raise SecretError("UNEXPECTED_DOPPLER_SECRET_SCOPE")
    if not token or "\n" in token or "\r" in token:
        raise SecretError("DOPPLER_TOKEN_REQUIRED")
    query = urllib.parse.urlencode({"project": PROJECT, "config": CONFIG, "name": name})
    request = urllib.request.Request(  # noqa: S310 -- fixed Doppler HTTPS-only endpoint
        API + "?" + query,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        client = opener if opener is not None else urllib.request.build_opener(NoRedirect).open
        with client(request, timeout=12) as response:  # noqa: S310 -- HTTPS only; no redirects
            raw = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        raise SecretError(f"DOPPLER_HTTP_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise SecretError("DOPPLER_UNAVAILABLE") from None
    if len(raw) > MAX_RESPONSE:
        raise SecretError("DOPPLER_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(raw)
        value = result["value"]["computed"]
    except (TypeError, KeyError, ValueError):
        raise SecretError("DOPPLER_RESPONSE_INVALID") from None
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise SecretError("SECRET_MISSING_OR_INVALID")
    if any(c in value for c in "\r\n\x00") or "$" + "{" in value:
        raise SecretError("SECRET_UNSAFE_OR_UNRESOLVED")
    return value
