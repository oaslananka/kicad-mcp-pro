from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "integrations" / "chatgpt-app" / "apps-sdk"


def test_chatgpt_app_express5_dependency_policy() -> None:
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))

    assert package["dependencies"]["express"] == "5.2.1"
    assert package["overrides"] == {
        "@hono/node-server": "2.0.11",
        "hono": "4.13.7",
        "fast-uri": "3.1.8",
        "qs": "6.16.0",
    }
    assert lock["packages"][""]["dependencies"]["express"] == "5.2.1"
    assert lock["packages"]["node_modules/express"]["version"] == "5.2.1"
    assert lock["packages"]["node_modules/body-parser"]["version"] == "2.3.0"
    assert "node_modules/@modelcontextprotocol/sdk/node_modules/body-parser" not in lock["packages"]
