"""Bounded local-folder browse frames on a signed Windows Connector session.

Positive frames answer with exactly the four result shapes Cloud accepts;
every hostile, oversized, unknown or replayed frame fails closed. Windows
filesystem fixtures run against this real operating system's temp directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from kicad_mcp.cloud_folder_browse_receiver import (
    LocalFolderBrowseService,
    default_bindings_file,
    device_folder_service,
    handle_folder_frame,
)
from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError

DEVICE_REQUEST_ID = "0f4a2c1e-7b60-4d21-9d3a-2f8f6e1c4b55"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"


def frame(operation: str, **extra: object) -> str:
    body: dict[str, object] = {
        "kind": "connector.local_browser_request",
        "version": 1,
        "requestId": DEVICE_REQUEST_ID,
        "operation": operation,
    }
    body.update(extra)
    return json.dumps(body)


class FakeService(LocalFolderBrowseService):
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def list(self, folder_id: str) -> dict[str, object]:
        self.calls.append(("list", (folder_id,)))
        if folder_id == "root":
            return {
                "folderId": "root",
                "name": "This computer",
                "parentId": None,
                "project": False,
                "more": False,
                "folders": [{"id": "child-token", "name": "KiCad Projects", "project": True}],
            }
        raise KeyError("unknown_folder")

    def bind(self, folder_id: str, project_id: str) -> bool:
        self.calls.append(("bind", (folder_id, project_id)))
        return folder_id == "child-token" and project_id == PROJECT_ID

    def choose(self) -> dict[str, object]:
        self.calls.append(("choose", ()))
        return {"status": "cancelled"}

    def project_path(self, project_id: str) -> str | None:
        self.calls.append(("path", (project_id,)))
        return "C:\\Projects\\board\\board.kicad_pro" if project_id == PROJECT_ID else None


def test_list_root_answers_one_bounded_bounded_listing() -> None:
    result = handle_folder_frame(FakeService(), frame("list", folderId="root"))
    assert result == {
        "kind": "connector.local_browser_result",
        "version": 1,
        "requestId": DEVICE_REQUEST_ID,
        "operation": "list",
        "folderId": "root",
        "name": "This computer",
        "parentId": None,
        "project": False,
        "more": False,
        "folders": [{"id": "child-token", "name": "KiCad Projects", "project": True}],
    }
    assert json.dumps(result).encode().count(b"C:\\") == 0


def test_bind_confirms_a_real_selection_and_rejects_unknown_tokens() -> None:
    service = FakeService()
    assert (
        handle_folder_frame(service, frame("bind", folderId="child-token", projectId=PROJECT_ID))[
            "ok"
        ]
        is True
    )
    assert handle_folder_frame(service, frame("bind", folderId="root", projectId=PROJECT_ID)) == {
        "kind": "connector.local_browser_result",
        "version": 1,
        "requestId": DEVICE_REQUEST_ID,
        "operation": "bind",
        "ok": False,
    }
    assert service.calls == [
        ("bind", ("child-token", PROJECT_ID)),
        ("bind", ("root", PROJECT_ID)),
    ]


def test_path_returns_the_locally_mapped_project_file_only() -> None:
    assert handle_folder_frame(FakeService(), frame("path", projectId=PROJECT_ID)) == {
        "kind": "connector.local_browser_result",
        "version": 1,
        "requestId": DEVICE_REQUEST_ID,
        "operation": "path",
        "path": "C:\\Projects\\board\\board.kicad_pro",
    }
    assert (
        handle_folder_frame(
            FakeService(), frame("path", projectId="22222222-2222-4222-8222-222222222222")
        )["path"]
        is None
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "delete",
            }
        ),
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 2,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "list",
                "folderId": "root",
            }
        ),
        json.dumps(
            {
                "kind": "connector.authorized_read",
                "version": 1,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "list",
                "folderId": "root",
            }
        ),
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": "not-a-uuid",
                "operation": "list",
                "folderId": "root",
            }
        ),
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "list",
                "folderId": "root",
                "projectId": PROJECT_ID,
            }
        ),
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "bind",
                "folderId": "root",
                "projectId": "../escape",
            }
        ),
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "path",
                "projectId": PROJECT_ID,
                "folderId": "root",
            }
        ),
        json.dumps(
            {
                "kind": "connector.local_browser_request",
                "version": 1,
                "requestId": DEVICE_REQUEST_ID,
                "operation": "list",
                "folderId": "x" * 65,
            }
        ),
    ],
)
def test_hostile_or_malformed_frames_fail_closed(raw: str) -> None:
    service = FakeService()
    with pytest.raises(CloudHandshakeDeniedError):
        handle_folder_frame(service, raw)
    assert service.calls == []


def test_oversized_frame_is_denied() -> None:
    service = FakeService()
    request_frame = frame("list", folderId="r" * 2000)
    with pytest.raises(CloudHandshakeDeniedError):
        handle_folder_frame(service, request_frame)


def test_service_level_revocation_stops_every_operation(tmp_path: Path) -> None:
    projects = tmp_path / "KiCad Projects"
    board = projects / "Board1"
    board.mkdir(parents=True)
    (board / "board.kicad_pro").write_text("{}")
    allowed = [False]
    service = device_folder_service(
        board,
        bindings_file=tmp_path / "bindings.json",
        native_picker=lambda: None,
        authorization=lambda: allowed[0],
    )
    for raw in (
        frame("list", folderId="root"),
        frame("choose"),
        frame("path", projectId=PROJECT_ID),
        frame("bind", folderId="root", projectId=PROJECT_ID),
    ):
        with pytest.raises(CloudHandshakeDeniedError):
            handle_folder_frame(service, raw)
    allowed[0] = True
    assert handle_folder_frame(service, frame("list", folderId="root"))["operation"] == "list"
    assert handle_folder_frame(service, frame("choose"))["status"] == "cancelled"


@pytest.mark.parametrize("result", ["selected", "cancelled", "denied"])
@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_posix_device_browse_uses_owner_native_picker_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, result: str, platform: str
) -> None:
    """Remote choose uses owner GUI, not the Windows picker or a leaked path."""
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver as receiver
    from kicad_mcp import cloud_user_cli

    root = tmp_path / "KiCad projects"
    root.mkdir()
    project = root / "owner chosen"
    project.mkdir()
    (project / "only.kicad_pro").write_text("{}", encoding="utf-8")
    selected = []

    def fake_owner_picker() -> Path:
        selected.append(True)
        if result == "cancelled":
            raise cloud_user_cli.typer.BadParameter(cloud_user_cli._NO_PROJECT_FOLDER_SELECTED)
        if result == "denied":
            raise cloud_user_cli.typer.BadParameter("Folder picker unavailable")
        return project

    monkeypatch.setattr(receiver, "sys", SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_browse_local_project_folder", fake_owner_picker)
    monkeypatch.setattr(
        receiver,
        "choose_project_folder",
        lambda: pytest.fail("POSIX must never launch Windows Explorer"),
    )
    service = device_folder_service(
        root, bindings_file=tmp_path / "bindings.json", authorization=lambda: True
    )
    if result == "denied":
        with pytest.raises(CloudHandshakeDeniedError):
            handle_folder_frame(service, frame("choose"))
    else:
        response = handle_folder_frame(service, frame("choose"))
        if result == "cancelled":
            assert response["status"] == "cancelled"
        else:
            assert response["status"] == "selected"
            assert response["projects"][0]["name"] == "only"
            assert str(project) not in json.dumps(response)
            assert str(root) not in json.dumps(response)
    assert len(selected) == 1
    assert not (tmp_path / "bindings.json").exists()


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_posix_device_browse_requires_owner_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    """Headless managed services cannot activate a user picker by Cloud frame."""
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver as receiver
    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(receiver, "sys", SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr(
        cloud_user_cli,
        "_browse_local_project_folder",
        lambda: pytest.fail("Headless Cloud must not open any GUI picker"),
    )
    service = device_folder_service(tmp_path.resolve(), bindings_file=tmp_path / "bindings.json")
    with pytest.raises(CloudHandshakeDeniedError):
        handle_folder_frame(service, frame("choose"))
    assert not (tmp_path / "bindings.json").exists()


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_posix_owner_selected_project_is_bound_only_after_explicit_cloud_bind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver as receiver
    from kicad_mcp import cloud_user_cli

    folder = tmp_path / "Chosen project"
    folder.mkdir()
    target = folder / "exact.kicad_pro"
    target.write_text("{}", encoding="utf-8")
    binding_file = tmp_path / "owner-binding.json"
    monkeypatch.setattr(receiver, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_browse_local_project_folder", lambda: folder)
    service = device_folder_service(folder, bindings_file=binding_file, authorization=lambda: True)
    choose = handle_folder_frame(service, frame("choose"))
    assert choose["status"] == "selected"
    assert not binding_file.exists()  # selecting cannot authorize a project
    token = choose["projects"][0]["id"]
    response = handle_folder_frame(service, frame("bind", folderId=token, projectId=PROJECT_ID))
    assert response["ok"] is True
    assert str(folder) not in json.dumps(choose)
    assert str(folder) not in json.dumps(response)
    assert json.loads(binding_file.read_text(encoding="utf-8")) == {PROJECT_ID: str(target)}


def test_windows_device_default_picker_is_not_replaced_by_posix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver as receiver

    folder = tmp_path / "Windows project"
    folder.mkdir()
    (folder / "windows.kicad_pro").write_text("{}", encoding="utf-8")
    used: list[bool] = []

    def windows_dialog() -> Path:
        used.append(True)
        return folder

    monkeypatch.setattr(receiver, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(receiver, "choose_project_folder", windows_dialog)
    service = device_folder_service(folder, bindings_file=tmp_path / "bindings.json")
    answer = handle_folder_frame(service, frame("choose"))
    assert answer["status"] == "selected"
    assert answer["projects"][0]["name"] == "windows"
    assert used == [True]
    assert str(folder) not in json.dumps(answer)
    assert not (tmp_path / "bindings.json").exists()


def _realistic_service(tmp_path: Path) -> LocalFolderBrowseService:
    projects = tmp_path / "KiCad Projects"
    board = projects / "Board1"
    board.mkdir(parents=True)
    (board / "board.kicad_pro").write_text('{"meta": {}}')
    (projects / "Empty").mkdir()
    return device_folder_service(
        board, bindings_file=tmp_path / "bindings.json", native_picker=lambda: None
    )


def test_real_windows_folder_listing_is_root_confined(tmp_path: Path) -> None:
    service = _realistic_service(tmp_path)
    root = handle_folder_frame(service, frame("list", folderId="root"))
    folders = root["folders"]
    assert isinstance(folders, list)
    # The only visible root is the KiCad projects area itself.
    assert [entry["name"] for entry in folders] == ["KiCad Projects"]  # type: ignore[index]
    area_id = folders[0]["id"]  # type: ignore[index]
    area = handle_folder_frame(service, frame("list", folderId=str(area_id)))
    area_folders = area["folders"]
    names = {entry["name"] for entry in area_folders}  # type: ignore[index]
    assert "Board1" in names
    assert "Empty" in names
    board_entry = next(entry for entry in area_folders if entry["name"] == "Board1")  # type: ignore[index]
    assert board_entry["project"] is True  # type: ignore[index]
    child_id = board_entry["id"]  # type: ignore[index]
    listing = handle_folder_frame(service, frame("list", folderId=str(child_id)))
    assert listing["project"] is True  # type: ignore[index]
    assert listing["folders"] == []  # type: ignore[index]
    # Unknown and off-root tokens never re-enter the filesystem.
    invalid_frame = frame("list", folderId="made-up-token")
    with pytest.raises(CloudHandshakeDeniedError):
        handle_folder_frame(service, invalid_frame)


def test_real_windows_binding_persists_only_a_local_project_map(tmp_path: Path) -> None:
    service = _realistic_service(tmp_path)
    root = handle_folder_frame(service, frame("list", folderId="root"))
    area_id = root["folders"][0]["id"]  # type: ignore[index]
    area = handle_folder_frame(service, frame("list", folderId=str(area_id)))
    board_entry = next(entry for entry in area["folders"] if entry["name"] == "Board1")  # type: ignore[index]
    result = handle_folder_frame(
        service, frame("bind", folderId=str(board_entry["id"]), projectId=PROJECT_ID)
    )  # type: ignore[index]
    assert result["ok"] is True  # type: ignore[index]
    stored = json.loads((tmp_path / "bindings.json").read_text(encoding="utf-8"))
    assert stored[PROJECT_ID].endswith("board.kicad_pro")
    assert Path(stored[PROJECT_ID]).is_absolute()
    # Native path handoff is intentionally Windows-only: the signed
    # receiver must deny POSIX fixture paths on Linux CI, not broaden the
    # device path contract merely to satisfy a cross-platform test.
    if os.name == "nt":
        answer = handle_folder_frame(service, frame("path", projectId=PROJECT_ID))
        assert answer["path"].endswith("board.kicad_pro")  # type: ignore[index]
    else:
        path_request = frame("path", projectId=PROJECT_ID)
        with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
            handle_folder_frame(service, path_request)
    assert UUID(PROJECT_ID)
    # A second bind with the stale token is refused (token consumed).
    assert (
        handle_folder_frame(
            service, frame("bind", folderId=str(board_entry["id"]), projectId=PROJECT_ID)
        )["ok"]
        is False
    )  # type: ignore[index]


def test_real_windows_native_cancel_never_selects(tmp_path: Path) -> None:
    service = _realistic_service(tmp_path)
    answer = handle_folder_frame(service, frame("choose"))
    assert answer == {
        "kind": "connector.local_browser_result",
        "version": 1,
        "requestId": DEVICE_REQUEST_ID,
        "operation": "choose",
        "status": "cancelled",
    }


def test_default_bindings_file_is_a_fixed_per_user_path() -> None:
    path = default_bindings_file()
    assert path.is_absolute()
    assert path.parts[-2:] == ("connector", "folder-bindings.json")
    assert ".kicad-mcp-cloud" in path.parts


def test_selected_native_folder_returns_only_tokenized_projects() -> None:
    class Selected(FakeService):
        def choose(self) -> dict[str, object]:
            return {
                "status": "selected",
                "folderId": "opaque-folder",
                "name": "KiCad Lab",
                "projects": [
                    {"id": "opaque-project-a", "name": "Motor"},
                    {"id": "opaque-project-b", "name": "Controller"},
                ],
            }

    selected = handle_folder_frame(Selected(), frame("choose"))
    assert selected == {
        "kind": "connector.local_browser_result",
        "version": 1,
        "requestId": DEVICE_REQUEST_ID,
        "operation": "choose",
        "status": "selected",
        "folderId": "opaque-folder",
        "name": "KiCad Lab",
        "projects": [
            {"id": "opaque-project-a", "name": "Motor"},
            {"id": "opaque-project-b", "name": "Controller"},
        ],
    }
    assert "C:\\" not in json.dumps(selected)


@pytest.mark.parametrize(
    "selection",
    [
        {"status": "selected", "folderId": "token", "name": "Board", "projects": []},
        {"status": "selected", "folderId": "token", "name": "Board", "projects": [None]},
        {
            "status": "selected",
            "folderId": "token",
            "name": "Board",
            "projects": [{"id": "opaque"}],
        },
        {
            "status": "selected",
            "folderId": 123,
            "name": "Board",
            "projects": [{"id": "id", "name": "Board"}],
        },
        {
            "status": "selected",
            "folderId": "token",
            "name": "",
            "projects": [{"id": "id", "name": "Board"}],
        },
        {"status": "cancelled", "folderId": "unexpected"},
        {"status": "not-valid"},
    ],
)
def test_invalid_native_folder_selection_fails_closed(selection: dict[str, object]) -> None:
    class Selected(FakeService):
        def choose(self) -> dict[str, object]:
            return selection

    service = Selected()
    choose_request = frame("choose")
    with pytest.raises(CloudHandshakeDeniedError):
        handle_folder_frame(service, choose_request)


@pytest.mark.parametrize(
    "project_path",
    [
        "",
        "relative/board.kicad_pro",
        "C:\\Projects\\board.txt",
        "C:\\Projects\\board.kicad_pro\n",
        "C:\\Projects\\board.kicad_pro" + ("x" * 2048),
    ],
)
def test_local_project_path_boundary_rejects_hostile_or_ambiguous_paths(
    project_path: str,
) -> None:
    class Malformed(FakeService):
        def project_path(self, project_id: str) -> str | None:
            assert project_id == PROJECT_ID
            return project_path

    service = Malformed()
    path_request = frame("path", projectId=PROJECT_ID)
    with pytest.raises(CloudHandshakeDeniedError):
        handle_folder_frame(service, path_request)


@pytest.mark.parametrize(
    "invalid_listing",
    [
        None,
        [],
        {"unexpected": "not part of the device folder contract"},
        {"folderId": "different"},
        {"project": "not-a-bool"},
        {"more": 1},
        {"folders": "wrong-type"},
        {"folders": [{}]},
        {"folders": [{"id": "child-token", "name": "Board", "project": "yes"}]},
        {"folders": [{"id": "child-token", "name": "Board"}]},
    ],
)
def test_device_folder_listing_rejects_inconsistent_native_response(
    invalid_listing: object,
) -> None:
    """A device's malformed listing must never appear as an owner-approved folder."""

    class BrokenList(FakeService):
        def list(self, folder_id: str) -> object:
            valid = super().list(folder_id)
            if isinstance(invalid_listing, dict):
                return {**valid, **invalid_listing}
            return invalid_listing

    service = BrokenList()
    listing_request = frame("list", folderId="root")
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        handle_folder_frame(service, listing_request)


def test_device_folder_browser_rejects_wrong_local_project_id(tmp_path: Path) -> None:
    service = _realistic_service(tmp_path)
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        service.project_path("not-an-owner-approved-uuid")


def test_folder_browser_requires_absolute_selected_device_directory() -> None:
    relative_directory = Path("relative/KiCad")
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        device_folder_service(relative_directory)
