from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "integrations" / "chatgpt-app" / "apps-sdk"


def test_chatgpt_app_scopes_body_parser_security_override() -> None:
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))

    assert package["dependencies"]["express"] == "4.22.2"
    assert package["overrides"] == {
        "express@4.22.2": {"body-parser": "1.20.6"},
        "@hono/node-server": "2.0.11",
        "hono": "4.12.34",
        "fast-uri": "3.1.6",
        "qs": "6.16.0",
    }
    assert lock["packages"]["node_modules/body-parser"]["version"] == "1.20.6"
    assert (
        lock["packages"]["node_modules/@modelcontextprotocol/sdk/node_modules/body-parser"][
            "version"
        ]
        == "2.3.0"
    )
