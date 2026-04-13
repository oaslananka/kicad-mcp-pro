from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.utils.ngspice import NgspiceRunner, _parse_wrdata_table, prepare_spice_netlist


def test_prepare_spice_netlist_injects_directives_before_end(tmp_path: Path) -> None:
    base = tmp_path / "base.cir"
    base.write_text("* deck\nR1 in out 1k\n.end\n", encoding="utf-8")

    prepared = prepare_spice_netlist(base, tmp_path / "out", [".param gain=10"])

    text = prepared.read_text(encoding="utf-8")
    assert ".param gain=10" in text
    assert text.strip().endswith(".end")


def test_parse_wrdata_table_reads_headered_rows(tmp_path: Path) -> None:
    data = tmp_path / "ac.data"
    data.write_text(
        "frequency vm(out) vp(out)\n"
        "10 2 -90\n"
        "100 1 -135\n",
        encoding="utf-8",
    )

    header, rows = _parse_wrdata_table(data)

    assert header == ["frequency", "vm(out)", "vp(out)"]
    assert rows == [[10.0, 2.0, -90.0], [100.0, 1.0, -135.0]]


def test_ngspice_runner_prefers_inspice_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = tmp_path / "ngspice"
    cli.write_text("", encoding="utf-8")
    netlist = tmp_path / "deck.cir"
    netlist.write_text("* deck\n.end\n", encoding="utf-8")

    class FakeAnalysis:
        nodes = {"out": [1.25]}
        branches = {}

    class FakeSimulation:
        def __init__(self) -> None:
            self.received_probes: tuple[str, ...] | None = None

        def operating_point(self, **kwargs: object) -> FakeAnalysis:
            self.received_probes = tuple(kwargs.get("probes", ()))
            return FakeAnalysis()

    class FakeSimulatorInstance:
        def __init__(self) -> None:
            self.simulation_instance = FakeSimulation()

        def simulation(self, circuit: object) -> FakeSimulation:
            _ = circuit
            return self.simulation_instance

    class FakeSimulatorFactory:
        last_instance: FakeSimulatorInstance | None = None

        @classmethod
        def factory(cls, **kwargs: object) -> FakeSimulatorInstance:
            _ = kwargs
            cls.last_instance = FakeSimulatorInstance()
            return cls.last_instance

    class FakeSpiceFile:
        def __init__(self, path: Path) -> None:
            self.path = path

    class FakeBuilder:
        def translate(self, spice_file: FakeSpiceFile) -> object:
            return {"path": spice_file.path}

    monkeypatch.setattr("kicad_mcp.utils.ngspice.discover_ngspice_cli", lambda configured=None: cli)
    monkeypatch.setattr(
        "kicad_mcp.utils.ngspice._import_inspice_modules",
        lambda: {
            "SpiceFile": FakeSpiceFile,
            "Builder": FakeBuilder,
            "Simulator": FakeSimulatorFactory,
        },
    )

    result = NgspiceRunner().run_operating_point(netlist, tmp_path / "sim", ["out"])

    assert result.backend == "inspice"
    assert result.traces[0].name == "out"
    assert result.traces[0].values == [1.25]
    assert FakeSimulatorFactory.last_instance is not None
    assert FakeSimulatorFactory.last_instance.simulation_instance.received_probes == ("out",)


def test_ngspice_runner_cli_fallback_parses_transient_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = tmp_path / "ngspice"
    cli.write_text("", encoding="utf-8")
    netlist = tmp_path / "deck.cir"
    netlist.write_text("* deck\nV1 in 0 5\nR1 in out 1k\n.end\n", encoding="utf-8")
    out_dir = tmp_path / "sim"

    def fake_run(cmd: list[str], *args: object, **kwargs: object):
        _ = args, kwargs
        deck_path = Path(cmd[-1])
        data_path = deck_path.with_suffix(".data")
        log_path = deck_path.with_suffix(".log")
        raw_path = deck_path.with_suffix(".raw")
        data_path.write_text(
            "time v(out)\n"
            "0 0\n"
            "1e-3 4.5\n",
            encoding="utf-8",
        )
        log_path.write_text("ngspice ok\n", encoding="utf-8")
        raw_path.write_text("raw\n", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("kicad_mcp.utils.ngspice.discover_ngspice_cli", lambda configured=None: cli)
    monkeypatch.setattr("kicad_mcp.utils.ngspice._import_inspice_modules", lambda: None)
    monkeypatch.setattr("kicad_mcp.utils.ngspice.subprocess.run", fake_run)

    result = NgspiceRunner().run_transient_analysis(
        netlist,
        out_dir,
        ["out"],
        stop_time_s=1e-3,
        step_time_s=1e-6,
    )

    assert result.backend == "ngspice-cli"
    assert result.x_label == "time"
    assert result.x_values == [0.0, 1e-3]
    assert result.traces[0].name == "out"
    assert result.traces[0].values == [0.0, 4.5]
