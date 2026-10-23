from kicad_mcp.tools.schematic import _pin_label_stub_direction


def test_single_column_connector_pins_stub_sideways_not_through_pin_stack() -> None:
    all_points = [(10.0, 10.0), (10.0, 12.54), (10.0, 15.08)]

    assert _pin_label_stub_direction((10.0, 10.0), (15.0, 12.54), all_points) == (-1.0, 0.0)
    assert _pin_label_stub_direction((10.0, 15.08), (15.0, 12.54), all_points) == (-1.0, 0.0)


def test_single_row_connector_pins_stub_vertically_not_through_pin_stack() -> None:
    all_points = [(10.0, 10.0), (12.54, 10.0), (15.08, 10.0)]

    assert _pin_label_stub_direction((10.0, 10.0), (12.54, 5.0), all_points) == (0.0, 1.0)
    assert _pin_label_stub_direction((15.08, 10.0), (12.54, 5.0), all_points) == (0.0, 1.0)


def test_two_terminal_part_whose_center_is_on_the_row_stubs_along_the_row() -> None:
    """SW_Push / D_Small / R / C: pins collinear WITH the body center.

    A horizontal switch, diode, resistor, or capacitor has both pins on the row
    that passes through the body center, so the pins point ALONG that row.  A
    perpendicular stub placed every terminal label at rotation 90/270, which
    kicad-cli renders as vertical text and reads badly; the stub must follow the
    row so the label stays horizontal.
    """
    all_points = [(154.94, 49.53), (165.1, 49.53)]

    assert _pin_label_stub_direction((165.1, 49.53), (160.02, 49.53), all_points) == (1.0, 0.0)
    assert _pin_label_stub_direction((154.94, 49.53), (160.02, 49.53), all_points) == (-1.0, 0.0)


def test_two_terminal_part_whose_center_is_on_the_column_stubs_along_the_column() -> None:
    """A vertically placed two-terminal part points along its column.

    The symmetric case of the row test: the pins still point away from the body
    center, so the stub follows the column instead of stepping sideways.
    """
    all_points = [(10.0, 10.0), (10.0, 15.08)]

    assert _pin_label_stub_direction((10.0, 15.08), (10.0, 12.54), all_points) == (0.0, 1.0)
    assert _pin_label_stub_direction((10.0, 10.0), (10.0, 12.54), all_points) == (0.0, -1.0)


def test_pin_label_stub_direction_keeps_origin_fallback_for_interior_points() -> None:
    # No outer pins: the historical origin-based direction resolves ties horizontally.
    assert _pin_label_stub_direction((5.0, 5.0), (0.0, 0.0), []) == (1.0, 0.0)
    assert _pin_label_stub_direction((-5.0, 2.0), (0.0, 0.0), []) == (-1.0, 0.0)
    assert _pin_label_stub_direction((1.0, -5.0), (0.0, 0.0), []) == (0.0, -1.0)
