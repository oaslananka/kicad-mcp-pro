"""Fail-closed generation from registered tools into reviewed Cloud pilot metadata."""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
generator = runpy.run_path(str(ROOT / "scripts" / "build_cloud_direct_tools.py"))
build = generator["build"]
render = generator["render"]
PILOT_NAMES = generator["PILOT_NAMES"]


def fixture() -> dict[str, object]:
    return {
        "tools": [
            {
                "name": name,
                "description": f"Tool {name}",
                "inputSchema": {"type": "object", "properties": {}},
                "capability": {
                    "tier": "write"
                    if name.startswith(("sch_add", "pcb_add", "pcb_save"))
                    else "read",
                    "human_gate_required": False,
                    "requires_human_confirmation": False,
                    "writes_files": name == "pcb_save",
                    "writes_kicad_gui_state": name == "pcb_save",
                },
                "remoteCallable": False,
            }
            for name in PILOT_NAMES
        ]
    }


def test_canonical_generated_pilot_is_reviewable_and_deterministic() -> None:
    source = json.loads((ROOT / "integrations/common/capability-catalog.json").read_text("utf-8"))
    tools = build(source)
    assert len(tools) == len(PILOT_NAMES)
    assert [tool["name"] for tool in tools] == sorted(PILOT_NAMES)
    assert [t["name"] for t in source["tools"] if t["remoteCallable"]] == []
    generated = (ROOT / "apps/cloud/src/cloud-direct-tool-contracts.generated.ts").read_text(
        encoding="utf-8"
    )
    assert generated == render(tools)
    assert render(tools) == render(build(source))


def test_new_unreviewed_local_tools_do_not_auto_publish() -> None:
    source = fixture()
    baseline = render(build(source))
    source["tools"].append(
        {
            "name": "manufacturing_release_gate",
            "description": "Must not appear",
            "inputSchema": {"type": "object", "properties": {}},
            "capability": {"tier": "human_only", "human_gate_required": True},
        }
    )
    assert render(build(source)) == baseline


def test_missing_or_human_gated_selected_tool_fails_closed() -> None:
    source = fixture()
    source["tools"] = source["tools"][1:]
    try:
        build(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Missing selected tool must fail")
    source = fixture()
    source["tools"][0]["capability"]["human_gate_required"] = True
    try:
        build(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Human-gated selected tool must fail")


def test_selected_name_collision_fails_closed() -> None:
    source = fixture()
    source["tools"].append(dict(source["tools"][0]))
    try:
        build(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate registry name must fail")


def test_remote_exposure_and_read_side_effects_fail_closed() -> None:
    for modification in ("remoteCallable", "writes_files"):
        source = fixture()
        item = source["tools"][0]
        if modification == "remoteCallable":
            item["remoteCallable"] = True
        else:
            item["capability"]["writes_files"] = True
        try:
            build(source)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Unreviewed exposure or read side effects: {modification}")


if __name__ == "__main__":
    for name, candidate in sorted(globals().items()):
        if name.startswith("test_") and callable(candidate):
            candidate()
    print("Cloud direct tool generator tests passed")
