"""Regression: ``exclude_nets`` must keep Freerouting from routing those nets.

The runner merged ``exclude_nets`` into the ``-inc`` argument, which Freerouting
reads as net *class* names. A net name there matches nothing, so the excluded
nets were routed anyway. Removing them from the DSN network (the net list and
each class's member list) is what actually stops Freerouting: their pads stay on
the board as obstacles with no net to route.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kicad_mcp.utils.freerouting import FreeRoutingRunner

DSN = """(pcb demo.dsn
  (parser
    (string_quote ")
    (space_in_quoted_tokens on)
  )
  (network
    (net A
      (pins R1-1 R2-1)
    )
    (net "Net-(D1-A)"
      (pins D1-1 R1-2)
    )
    (net SHIELD
      (pins J1-5 J1-6)
    )
    (net B
      (pins R2-2 D1-2)
    )
    (class kicad_default "" A "Net-(D1-A)" SHIELD
      (circuit
        (use_via "Via[0-1]_600:300_um")
      )
      (rule
        (width 250)
        (clearance 200)
      )
    )
    (class Power B
      (circuit
        (use_via "Via[0-1]_800:400_um")
      )
      (rule
        (width 500)
      )
    )
  )
  (wiring
  )
)
"""


def _routed_input(command: list[str], use_docker: bool) -> Path:
    dsn_arg = command[command.index("-de") + 1]
    if not use_docker:
        return Path(dsn_arg)
    mount = command[command.index("-v") + 1]
    host_root = mount.rsplit(":/work", 1)[0]
    return Path(host_root) / dsn_arg


@pytest.mark.parametrize("use_docker", [True, False], ids=["docker", "jar"])
def test_excluded_nets_are_removed_from_the_routed_dsn_not_passed_as_classes(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_docker: bool,
) -> None:
    dsn_path = sample_project / "board.dsn"
    ses_path = sample_project / "board.ses"
    jar_path = sample_project / "freerouting.jar"
    dsn_path.write_text(DSN, encoding="utf-8")
    jar_path.write_text("jar", encoding="utf-8")
    observed: list[list[str]] = []
    routed_text: list[str] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(cmd)
        routed_text.append(_routed_input(cmd, use_docker).read_text(encoding="utf-8"))
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="100% routed", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_run)
    monkeypatch.setattr("kicad_mcp.utils.freerouting._docker_available", lambda _: use_docker)

    result = FreeRoutingRunner().run_freerouting(
        dsn_path,
        ses_path,
        use_docker=use_docker,
        freerouting_jar_path=None if use_docker else jar_path,
        net_classes_to_ignore=["Power"],
        exclude_nets=["SHIELD", "Net-(D1-A)", "NOT_ON_BOARD"],
    )

    command = observed[0]
    routed = routed_text[0]
    # The excluded nets are gone from the net list and from their class.
    assert "(net SHIELD" not in routed
    assert '(net "Net-(D1-A)"' not in routed
    assert '(class kicad_default "" A\n' in routed
    assert "(net A\n" in routed
    assert "(net B\n" in routed
    assert "(class Power B\n" in routed
    # Only real net classes go to -inc.
    assert command[command.index("-inc") + 1] == "Power"
    # The exported DSN itself is left as it was.
    assert dsn_path.read_text(encoding="utf-8") == DSN
    assert result.excluded_nets == ("SHIELD", "Net-(D1-A)")
    assert result.total_nets == 2


def test_without_excluded_nets_the_exported_dsn_is_routed_directly(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn_path = sample_project / "board.dsn"
    ses_path = sample_project / "board.ses"
    jar_path = sample_project / "freerouting.jar"
    dsn_path.write_text(DSN, encoding="utf-8")
    jar_path.write_text("jar", encoding="utf-8")
    observed: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(cmd)
        ses_path.write_text("ses", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="100% routed", stderr="")

    monkeypatch.setattr("kicad_mcp.utils.freerouting.subprocess.run", fake_run)

    result = FreeRoutingRunner().run_freerouting(
        dsn_path, ses_path, use_docker=False, freerouting_jar_path=jar_path
    )

    assert Path(observed[0][observed[0].index("-de") + 1]) == dsn_path.resolve()
    assert "-inc" not in observed[0]
    assert result.excluded_nets == ()
    assert result.total_nets == 4
