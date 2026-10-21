"""Library pin electrical type no_connect must not be a dangling pin error."""

from kicad_mcp.tools.validation import _check_connectivity_group_smells


def _group(pin_type: str) -> dict[str, object]:
    return {
        "pins": [{"reference": "J2", "pin": "7", "etype": pin_type}],
        "names": [],
        "points": [(241.3, 96.52)],
        "no_connect": False,
    }


def test_library_no_connect_pin_is_intentional() -> None:
    failures: list[str] = []
    assert _check_connectivity_group_smells("Top level", [_group("no_connect")], failures) == (0, 0)
    assert failures == []


def test_normal_unlabeled_single_pin_remains_a_failure() -> None:
    failures: list[str] = []
    assert _check_connectivity_group_smells("Top level", [_group("input")], failures) == (0, 1)
    assert "J2:7" in failures[0]


def test_explicit_no_connect_marker_still_works_for_normal_pin() -> None:
    group = _group("input")
    group["no_connect"] = True
    failures: list[str] = []
    assert _check_connectivity_group_smells("Top level", [group], failures) == (0, 0)
    assert failures == []
