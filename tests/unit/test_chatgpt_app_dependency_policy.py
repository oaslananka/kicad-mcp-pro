from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "integrations" / "chatgpt-app" / "apps-sdk"


def test_chatgpt_app_express5_dependency_policy() -> None:
    package = json.loads((APP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))

    # Keep Express 5 and package-lock synchronized across reviewed updates;
    # do not freeze the test to the previous dependency release.
    express = package["dependencies"]["express"]
    assert express.startswith("5.")
    assert express.count(".") == 2
    assert all(part.isdigit() for part in express.split("."))
    assert package["overrides"] == {
        "@hono/node-server": "2.0.11",
        "hono": "4.13.7",
        "fast-uri": "3.1.8",
        "qs": "6.16.0",
    }
    assert lock["packages"][""]["dependencies"]["express"] == express
    assert lock["packages"]["node_modules/express"]["version"] == express
    assert lock["packages"]["node_modules/body-parser"]["version"] == "2.3.0"
    assert "node_modules/@modelcontextprotocol/sdk/node_modules/body-parser" not in lock["packages"]
