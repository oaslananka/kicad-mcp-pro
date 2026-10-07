from __future__ import annotations

import pytest

from kicad_mcp.evals.connectivity_differential import (
    build_connectivity_differential_result,
    connectivity_signature_hash,
    normalize_custom_connectivity_groups,
    normalize_native_net_map,
)

SOURCE_SHA = "a" * 40
FIXTURE_HASH = "sha256:" + "b" * 64


def test_native_and_custom_normalization_compare_pin_membership_not_net_names() -> None:
    native = normalize_native_net_map(
        {
            ("U1", "1"): "/generated/native/name-1",
            ("R1", "2"): "/generated/native/name-1",
            ("U1", "2"): "+3V3",
            ("C1", "1"): "+3V3",
        }
    )
    custom = normalize_custom_connectivity_groups(
        [
            {
                "names": ["CUSTOM_ALIAS"],
                "pins": [
                    {"reference": "R1", "pin": "2"},
                    {"reference": "U1", "pin": "1"},
                ],
            },
            {
                "names": ["+3V3"],
                "pins": [
                    {"reference": "C1", "pin": "1"},
                    {"reference": "U1", "pin": "2"},
                ],
            },
        ]
    )

    assert native == custom
    assert native == (
        (("C1", "1"), ("U1", "2")),
        (("R1", "2"), ("U1", "1")),
    )
    assert connectivity_signature_hash(native) == connectivity_signature_hash(custom)


def test_connectivity_result_matches_equal_normalized_semantics() -> None:
    native_map = {("U1", "1"): "N1", ("R1", "2"): "N1"}
    custom_groups = [
        {
            "names": ["N1"],
            "pins": [
                {"reference": "R1", "pin": "2"},
                {"reference": "U1", "pin": "1"},
            ],
        }
    ]

    result = build_connectivity_differential_result(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="gallery-esp32-c3-wroom-02-breakout",
        fixture_hash=FIXTURE_HASH,
        native_net_map=native_map,
        custom_groups=custom_groups,
    )

    assert result.status == "match"
    assert result.operation == "connectivity.net-compilation"
    assert result.authority == "kicad-cli:sch-export-netlist-kicadsexpr"
    assert result.comparison_method == "pin-membership-sha256.v1"
    assert result.native_result_hash == result.custom_result_hash


def test_seeded_connectivity_divergence_is_detected() -> None:
    native_map = {("U1", "1"): "N1", ("R1", "2"): "N1"}
    custom_groups = [
        {
            "names": ["N1"],
            "pins": [{"reference": "U1", "pin": "1"}],
        },
        {
            "names": [],
            "pins": [{"reference": "R1", "pin": "2"}],
        },
    ]

    result = build_connectivity_differential_result(
        source_sha=SOURCE_SHA,
        lane="stable",
        kicad_version="10.0.6",
        fixture_id="gallery-esp32-c3-wroom-02-breakout",
        fixture_hash=FIXTURE_HASH,
        native_net_map=native_map,
        custom_groups=custom_groups,
    )

    assert result.status == "divergence"
    assert result.native_result_hash != result.custom_result_hash
    assert result.false_pass is False
    assert result.false_fail is False


def test_connectivity_result_rejects_vacuous_equivalence() -> None:
    common = {
        "source_sha": SOURCE_SHA,
        "lane": "stable",
        "kicad_version": "10.0.6",
        "fixture_id": "gallery-esp32-c3-wroom-02-breakout",
        "fixture_hash": FIXTURE_HASH,
    }
    with pytest.raises(ValueError, match="Native connectivity authority produced an empty"):
        build_connectivity_differential_result(
            **common,
            native_net_map={},
            custom_groups=[{"pins": [{"reference": "U1", "pin": "1"}]}],
        )

    empty_custom = build_connectivity_differential_result(
        **common,
        native_net_map={("U1", "1"): "N1"},
        custom_groups=[],
    )
    assert empty_custom.status == "divergence"
    assert empty_custom.native_result_hash != empty_custom.custom_result_hash


def test_custom_connectivity_rejects_duplicate_pin_membership() -> None:
    groups = [
        {
            "pins": [
                {"reference": "U1", "pin": "1"},
                {"reference": "R1", "pin": "2"},
            ]
        },
        {
            "pins": [
                {"reference": "U1", "pin": "1"},
                {"reference": "C1", "pin": "1"},
            ]
        },
    ]

    with pytest.raises(ValueError, match="U1:1 appears in multiple connectivity groups"):
        normalize_custom_connectivity_groups(groups)


def test_custom_connectivity_rejects_repeated_equivalent_group() -> None:
    group = {
        "pins": [
            {"reference": "U1", "pin": "1"},
            {"reference": "R1", "pin": "2"},
        ]
    }

    with pytest.raises(ValueError, match="appears in multiple connectivity groups"):
        normalize_custom_connectivity_groups([group, group])


def test_connectivity_normalization_rejects_malformed_identities() -> None:
    with pytest.raises(ValueError, match="non-empty net identity"):
        normalize_native_net_map({("U1", "1"): ""})

    for malformed_pin in (
        {"reference": "", "pin": "1"},
        {"reference": "U1", "pin": ""},
    ):
        with pytest.raises(ValueError, match="non-empty reference and pin"):
            normalize_custom_connectivity_groups([{"pins": [malformed_pin]}])

    with pytest.raises(ValueError, match="non-empty reference and pin"):
        normalize_native_net_map({("", "1"): "N1"})
