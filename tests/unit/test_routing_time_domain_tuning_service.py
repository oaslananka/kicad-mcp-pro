from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.routing.time_domain_tuning import (
    RoutingTimeDomainTuningService,
    build_time_domain_rule,
    delay_to_length_mm,
)


def _service(
    project_dir: Path | None,
    *,
    current_length: float = 12.5,
    stackup_context: tuple[str, float, float, float] | Exception = (
        "microstrip",
        0.18,
        4.2,
        1.0,
    ),
    written_path: Path | None = None,
) -> tuple[
    RoutingTimeDomainTuningService,
    list[str],
    list[tuple[str, str]],
]:
    track_calls: list[str] = []
    write_calls: list[tuple[str, str]] = []
    path = written_path or Path("demo.kicad_dru")

    def provide_stackup(layer: str) -> tuple[str, float, float, float]:
        if isinstance(stackup_context, Exception):
            raise stackup_context
        return stackup_context

    return (
        RoutingTimeDomainTuningService(
            get_project_dir=lambda: project_dir,
            current_track_length_for_pattern_mm=lambda pattern: (
                track_calls.append(pattern) or current_length
            ),
            stackup_context_for_layer=provide_stackup,
            write_rule=lambda name, body: write_calls.append((name, body)) or path,
        ),
        track_calls,
        write_calls,
    )


def test_fallback_tuning_preserves_rule_and_response(tmp_path: Path) -> None:
    service, track_calls, write_calls = _service(tmp_path, current_length=12.5)

    result = service.tune("DATA0", 250.0, 15.0)

    target_mm = delay_to_length_mm(250.0, 0.5)
    tolerance_mm = delay_to_length_mm(15.0, 0.5)
    expected_rule = build_time_domain_rule(
        "DATA0",
        250.0,
        15.0,
        target_mm,
        tolerance_mm,
    )
    assert track_calls == ["DATA0"]
    assert write_calls == [expected_rule]
    assert result == "\n".join(
        [
            "Time-domain tuning rule 'Time-domain tune DATA0' written to demo.kicad_dru.",
            "Target delay: 250.000 ps",
            "Tolerance: 15.000 ps",
            "Current measured length: 12.500 mm",
            f"Computed target length: {target_mm:.3f} mm",
            f"Required extension: {target_mm - 12.5:.3f} mm",
            f"Fallback target length: {target_mm:.3f} mm",
        ]
    )
    assert "A.NetName == 'DATA0'" in write_calls[0][1]


def test_wildcard_tuning_is_rejected_before_measurement_or_write(tmp_path: Path) -> None:
    service, track_calls, write_calls = _service(tmp_path)

    result = service.tune("DATA*", 250.0, 15.0)

    assert result == (
        "Wildcard/group time-domain tuning is not supported because KiCad length "
        "constraints apply per net. Specify a single concrete net name."
    )
    assert track_calls == []
    assert write_calls == []


def test_rule_builder_rejects_wildcard_conditions() -> None:
    for pattern in ("DATA*", "DATA?"):
        with pytest.raises(ValueError, match="constraints apply per net"):
            build_time_domain_rule(pattern, 250.0, 15.0, 37.0, 2.0)


def test_question_mark_wildcard_is_rejected_before_measurement_or_write(
    tmp_path: Path,
) -> None:
    service, track_calls, write_calls = _service(tmp_path)

    result = service.tune("DATA?", 250.0, 15.0)

    assert result == (
        "Wildcard/group time-domain tuning is not supported because KiCad length "
        "constraints apply per net. Specify a single concrete net name."
    )
    assert track_calls == []
    assert write_calls == []


def test_layer_profile_uses_stackup_and_reports_effective_er(tmp_path: Path) -> None:
    state_dir = tmp_path / ".kicad-mcp"
    state_dir.mkdir(parents=True)
    (state_dir / "tuning_profiles.json").write_text(
        json.dumps(
            {
                "profiles": {
                    "usb": {
                        "layer": "F.Cu",
                        "trace_impedance_ohm": 90.0,
                        "propagation_speed_factor": 0.6,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    service, track_calls, write_calls = _service(tmp_path)

    result = service.tune("USB_D+", 120.0, 8.0, "F.Cu")

    assert track_calls == ["USB_D+"]
    assert write_calls[0][0] == "Time-domain tune USB_D+"
    assert "A.NetName == 'USB_D+'" in write_calls[0][1]
    assert "Layer: F.Cu" in result
    assert "Effective dielectric constant:" in result
    assert "Fallback target length:" not in result


def test_stackup_value_error_preserves_profile_fallback(tmp_path: Path) -> None:
    state_dir = tmp_path / ".kicad-mcp"
    state_dir.mkdir(parents=True)
    (state_dir / "tuning_profiles.json").write_text(
        json.dumps(
            {
                "profiles": {
                    "fast": {
                        "layer": "f.cu",
                        "trace_impedance_ohm": 90.0,
                        "propagation_speed_factor": 0.6,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    service, _, _ = _service(
        tmp_path,
        stackup_context=ValueError("no stackup"),
    )

    result = service.tune("CLK", 100.0, 10.0, "F.Cu")

    target_mm = delay_to_length_mm(100.0, 0.6)
    assert f"Computed target length: {target_mm:.3f} mm" in result
    assert f"Fallback target length: {target_mm:.3f} mm" in result
    assert "Layer: F.Cu" in result


def test_writer_failure_preserves_message(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    def fail(_name: str, _body: str) -> Path:
        raise ValueError("bad rule")

    service = RoutingTimeDomainTuningService(
        get_project_dir=service.get_project_dir,
        current_track_length_for_pattern_mm=service.current_track_length_for_pattern_mm,
        stackup_context_for_layer=service.stackup_context_for_layer,
        write_rule=fail,
    )

    assert service.tune("CLK", 100.0) == "Time-domain tuning rule update failed: bad rule"


def test_missing_project_preserves_tuning_profile_state_error() -> None:
    service, _, _ = _service(None)

    with pytest.raises(
        ValueError,
        match=r"No active project directory is configured\. Call kicad_set_project\(\) first\.",
    ):
        service.tune("CLK", 100.0)
