from __future__ import annotations

from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from kicad_mcp.utils.ngspice import (
    NgspiceRunner,
    SimulationKind,
    _as_complex_list,
    _as_real_list,
    _parse_wrdata_table,
    _waveform_name,
    discover_ngspice_cli,
    prepare_spice_netlist,
)


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
        "frequency vm(out) vp(out)\n10 2 -90\n100 1 -135\n",
        encoding="utf-8",
    )

    header, rows = _parse_wrdata_table(data)

    assert header == ["frequency", "vm(out)", "vp(out)"]
    assert rows == [[10.0, 2.0, -90.0], [100.0, 1.0, -135.0]]


def test_ngspice_value_parsing_helpers_cover_scalar_iterable_and_names() -> None:
    assert _as_real_list(1.25) == [1.25]
    assert _as_real_list(1 + 2j) == [1.0]
    assert _as_real_list((1, 2.5)) == [1.0, 2.5]
    assert _as_complex_list(2.0) == [2 + 0j]
    assert _as_complex_list((1 + 1j, 2)) == [1 + 1j, 2 + 0j]
    assert _waveform_name("v(out)") == "out"
    assert _waveform_name("vm(out)") == "out"
    assert _waveform_name("vp(out)") == "out"
    assert _waveform_name("i(V1)") == "i(V1)"


def test_ngspice_value_helpers_without_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kicad_mcp.utils.ngspice._optional_numpy", lambda: None)

    assert _as_real_list([1, 2.5]) == [1.0, 2.5]
    assert _as_real_list(item for item in [3.0, 4.0]) == [3.0, 4.0]
    assert _as_real_list(5.0) == [5.0]
    assert _as_complex_list(1 + 2j) == [1 + 2j]
    assert _as_complex_list([1, 2 + 3j]) == [1 + 0j, 2 + 3j]
    assert _as_complex_list((4.0, 5.0)) == [4 + 0j, 5 + 0j]
    assert _as_complex_list(complex(item, 0.0) for item in [6.0, 7.0]) == [6 + 0j, 7 + 0j]


def test_discover_ngspice_cli_uses_configured_or_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "ngspice.exe"
    configured.write_text("", encoding="utf-8")
    assert discover_ngspice_cli(configured) == configured

    monkeypatch.setattr("kicad_mcp.utils.ngspice.shutil.which", lambda _name: str(configured))
    assert discover_ngspice_cli(None) == configured

    missing = tmp_path / "missing-ngspice"
    monkeypatch.setattr("kicad_mcp.utils.ngspice.shutil.which", lambda _name: None)
    assert discover_ngspice_cli(missing) is None


def test_parse_wrdata_table_numeric_rows_and_errors(tmp_path: Path) -> None:
    data = tmp_path / "dc.data"
    data.write_text("* comment\n0 1.0\n1 2.0\n", encoding="utf-8")
    header, rows = _parse_wrdata_table(data)
    assert header == ["col_0", "col_1"]
    assert rows == [[0.0, 1.0], [1.0, 2.0]]

    empty = tmp_path / "empty.data"
    empty.write_text("* only comments\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty data file"):
        _parse_wrdata_table(empty)

    non_numeric = tmp_path / "bad.data"
    non_numeric.write_text("time out\nnot numbers\n", encoding="utf-8")
    with pytest.raises(ValueError, match="numeric data rows"):
        _parse_wrdata_table(non_numeric)


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
            "time v(out)\n0 0\n1e-3 4.5\n",
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


@pytest.mark.parametrize(
    ("analysis", "kwargs"),
    [
        ("operating-point", {}),
        (
            "ac",
            {
                "points_per_decade": 10,
                "start_freq_hz": 1.0,
                "stop_freq_hz": 1_000.0,
            },
        ),
        (
            "transient",
            {
                "stop_time_s": 1e-3,
                "step_time_s": 1e-6,
            },
        ),
        (
            "dc",
            {
                "source_ref": "V1",
                "start_v": 0.0,
                "stop_v": 5.0,
                "step_v": 1.0,
            },
        ),
    ],
)
def test_ngspice_cli_deck_quotes_windows_output_paths_for_control_commands(
    tmp_path: Path,
    analysis: SimulationKind,
    kwargs: dict[str, float | int | str],
) -> None:
    runner = NgspiceRunner(ngspice_cli=tmp_path / "ngspice")
    data = PureWindowsPath(r"C:\work dir\prj1\output\simulation\result.data")
    raw = PureWindowsPath(r"C:\work dir\prj1\output\simulation\result.raw")

    deck = runner._build_cli_deck(  # noqa: SLF001
        analysis,
        "* deck\n.end\n",
        data,
        raw,
        ["out"],
        **kwargs,
    )

    assert "write 'C:/work dir/prj1/output/simulation/result.raw' all" in deck
    assert "wrdata 'C:/work dir/prj1/output/simulation/result.data'" in deck
    assert 'write "' not in deck
    assert 'wrdata "' not in deck
    assert r"C:\work dir" not in deck


def test_ngspice_runner_cli_builds_and_parses_all_analysis_modes(tmp_path: Path) -> None:
    runner = NgspiceRunner(ngspice_cli=tmp_path / "ngspice")
    netlist = tmp_path / "deck.cir"
    netlist.write_text("* deck\n.end\n", encoding="utf-8")
    data = tmp_path / "result.data"
    raw = tmp_path / "result.raw"
    log = tmp_path / "result.log"

    op_deck = runner._build_cli_deck(  # noqa: SLF001 - coverage for CLI deck generation.
        "operating-point",
        "* deck\n.end\n",
        data,
        raw,
        ["out"],
    )
    ac_deck = runner._build_cli_deck(  # noqa: SLF001 - coverage for CLI deck generation.
        "ac",
        "* deck\n.end\n",
        data,
        raw,
        ["out"],
        points_per_decade=10,
        start_freq_hz=1.0,
        stop_freq_hz=1_000.0,
    )
    dc_deck = runner._build_cli_deck(  # noqa: SLF001 - coverage for CLI deck generation.
        "dc",
        "* deck\n.end\n",
        data,
        raw,
        [],
        source_ref="V1",
        start_v=0.0,
        stop_v=5.0,
        step_v=1.0,
    )

    assert "op" in op_deck
    assert "ac dec 10 1.0 1000.0" in ac_deck
    assert "dc V1 0.0 5.0 1.0" in dc_deck

    op = runner._result_from_wrdata(  # noqa: SLF001 - direct parser coverage.
        "operating-point",
        netlist,
        data,
        raw,
        log,
        ["v(out)", "i(V1)"],
        [[3.3, -0.01]],
    )
    ac = runner._result_from_wrdata(  # noqa: SLF001
        "ac",
        netlist,
        data,
        raw,
        log,
        ["frequency", "vm(out)", "vp(out)"],
        [[10.0, 2.0, -45.0], [100.0, 1.0, -90.0]],
    )
    dc = runner._result_from_wrdata(  # noqa: SLF001
        "dc",
        netlist,
        data,
        raw,
        log,
        ["v-sweep", "v(out)"],
        [[0.0, 0.0], [5.0, 4.9]],
    )

    assert op.traces[0].name == "out"
    assert op.traces[1].name == "i(V1)"
    assert ac.x_label == "frequency"
    assert ac.traces[0].phase_values == [-45.0, -90.0]
    assert dc.x_label == "sweep"
    assert dc.traces[0].values == [0.0, 4.9]


def test_ngspice_runner_inspice_result_parsers(tmp_path: Path) -> None:
    runner = NgspiceRunner()
    netlist = tmp_path / "deck.cir"
    netlist.write_text("* deck\n.end\n", encoding="utf-8")

    ac = runner._result_from_inspice(  # noqa: SLF001 - direct parser coverage.
        "ac",
        netlist,
        SimpleNamespace(
            frequency=[10.0, 100.0],
            nodes={"out": [1 + 1j, 0 - 1j]},
            branches={},
        ),
    )
    transient = runner._result_from_inspice(  # noqa: SLF001
        "transient",
        netlist,
        SimpleNamespace(time=[0.0, 1e-3], nodes={"out": [0.0, 1.2]}, branches={}),
    )
    dc = runner._result_from_inspice(  # noqa: SLF001
        "dc",
        netlist,
        SimpleNamespace(sweep=[0.0, 5.0], nodes={"out": [0.0, 4.9]}, branches={}),
    )

    assert ac.backend == "inspice"
    assert ac.traces[0].phase_values == [45.0, -90.0]
    assert transient.x_label == "time"
    assert transient.traces[0].values == [0.0, 1.2]
    assert dc.x_label == "sweep"
    assert dc.x_values == [0.0, 5.0]
