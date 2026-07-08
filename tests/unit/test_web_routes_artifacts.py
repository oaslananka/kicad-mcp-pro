"""Tests for the dashboard schematic-artifact routes (/api/artifacts/*)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _clean_globals(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the workspace at a scratch dir and reset config between tests."""
    from kicad_mcp.config import reset_config

    monkeypatch.setenv("KICAD_MCP_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(tmp_path))
    reset_config()


def _write_manifest(render_dir: Path, *, session_id: str, svg_name: str) -> Path:
    svg_path = render_dir / svg_name
    svg_path.write_text("<svg></svg>")
    manifest = {
        "schema_version": "live-preview.manifest.v1",
        "session_id": session_id,
        "target_path": str(render_dir / "test.kicad_sch"),
        "watch": {"root_sheet": str(render_dir / "test.kicad_sch"), "child_sheets": []},
        "render": {
            "status": "ok",
            "sheet_path": str(render_dir / "test.kicad_sch"),
            "svg_path": str(svg_path),
        },
        "artifacts": [],
    }
    manifest_path = render_dir / f"{Path(svg_name).stem}.manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return svg_path


class TestArtifactsSchematicList:
    def test_lists_manifest_entries(self, tmp_path: Path) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.config import get_config
        from kicad_mcp.web.routes import web_routes

        render_dir = get_config().ensure_output_dir("schematic-renders")
        _write_manifest(render_dir, session_id="sess-1", svg_name="live-preview-a.svg")

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/schematic")
        assert response.status_code == 200
        artifacts = response.json()["artifacts"]
        assert len(artifacts) == 1
        assert artifacts[0]["session_id"] == "sess-1"
        assert artifacts[0]["svg_path"].endswith("live-preview-a.svg")

    def test_empty_when_no_manifests(self) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/schematic")
        assert response.status_code == 200
        assert response.json()["artifacts"] == []

    def test_ignores_malformed_manifest(self, tmp_path: Path) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.config import get_config
        from kicad_mcp.web.routes import web_routes

        render_dir = get_config().ensure_output_dir("schematic-renders")
        (render_dir / "broken.manifest.json").write_text("not json")

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/schematic")
        assert response.status_code == 200
        assert response.json()["artifacts"] == []


class TestArtifactsFile:
    def test_serves_svg_within_sandbox(self, tmp_path: Path) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.config import get_config
        from kicad_mcp.web.routes import web_routes

        render_dir = get_config().ensure_output_dir("schematic-renders")
        svg_path = _write_manifest(render_dir, session_id="sess-1", svg_name="live-preview-b.svg")

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/file", params={"path": str(svg_path)})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")

    def test_rejects_missing_path(self) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/file")
        assert response.status_code == 400

    def test_rejects_disallowed_extension(self, tmp_path: Path) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/file", params={"path": "/etc/passwd"})
        assert response.status_code == 400

    def test_rejects_path_traversal_outside_sandbox(self, tmp_path: Path) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        outside = tmp_path / "secret.svg"
        outside.write_text("<svg>secret</svg>")

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/file", params={"path": str(outside)})
        assert response.status_code == 403

    def test_returns_404_for_missing_file_in_sandbox(self, tmp_path: Path) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.config import get_config
        from kicad_mcp.web.routes import web_routes

        render_dir = get_config().ensure_output_dir("schematic-renders")

        app = Starlette(routes=web_routes)
        client = TestClient(app)
        response = client.get("/api/artifacts/file", params={"path": str(render_dir / "ghost.svg")})
        assert response.status_code == 404


class TestArtifactsRouteRegistration:
    def test_routes_in_web_routes(self) -> None:
        from kicad_mcp.web.routes import web_routes

        paths = {r.path for r in web_routes}
        assert "/api/artifacts/schematic" in paths
        assert "/api/artifacts/file" in paths
