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
        "@hono/node-server": "2.1.5",
        "hono": "4.13.13",
        "fast-uri": "3.1.9",
        "qs": "6.16.1",
        "ip-address": "10.7.4",
    }
    assert lock["packages"][""]["dependencies"]["express"] == express
    assert lock["packages"]["node_modules/express"]["version"] == express
    # Dependabot can upgrade this compatible transitive dependency independently.
    # Enforce the Express 5 declared semver floor and major version rather than
    # pinning a previous lockfile value (see dependency PR #1443).
    body_parser_range = lock["packages"]["node_modules/express"]["dependencies"]["body-parser"]
    body_parser_version = lock["packages"]["node_modules/body-parser"]["version"]
    assert body_parser_range.startswith("^2.")
    lower_bound = tuple(int(part) for part in body_parser_range[1:].split("."))
    installed = tuple(int(part) for part in body_parser_version.split("."))
    assert len(lower_bound) == len(installed) == 3
    assert installed[0] == lower_bound[0] == 2
    assert installed >= lower_bound
    assert "node_modules/@modelcontextprotocol/sdk/node_modules/body-parser" not in lock["packages"]
