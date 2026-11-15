"""Advanced routing helpers, rule orchestration, and FreeRouting integration."""

from __future__ import annotations

import re
from typing import cast

from kipy.board_types import Net, Track
from mcp.server.mcpserver import MCPServer as FastMCP

from ..connection import get_board
from ..pcb.board_access import board_nets_filtered, board_tracks
from ..pcb.geometry import track_segment_length_mm
from .pcb import _current_stackup_specs, _impedance_context_for_layer
from .project import load_design_intent as _load_design_intent
from .routing_rules import _load_rules_content, _mm, _rules_file_path, _upsert_rule, _write_rule

__all__ = [
    "_load_rules_content",
    "_mm",
    "_rules_file_path",
    "_upsert_rule",
    "_write_rule",
]


def _list_board_net_names() -> set[str]:
    return {
        str(net.name)
        for net in cast(list[Net], board_nets_filtered(get_board(), netclass_filter=None))
        if getattr(net, "name", "")
    }


def _current_track_length_mm(net_name: str) -> float:
    length = 0.0
    for track in cast(list[Track], board_tracks(get_board())):
        track_net = getattr(getattr(track, "net", None), "name", "")
        if track_net == net_name:
            length += track_segment_length_mm(track)
    return length


def _current_track_length_for_pattern_mm(net_pattern: str) -> float:
    if "*" not in net_pattern:
        return _current_track_length_mm(net_pattern)
    regex = re.compile("^" + re.escape(net_pattern).replace(r"\*", ".*") + "$")
    matching_names = [name for name in _list_board_net_names() if regex.fullmatch(name) is not None]
    return sum(_current_track_length_mm(name) for name in matching_names)


def register(mcp: FastMCP) -> None:
    """Register routing tools."""

    from . import routing_manual_tracks

    routing_manual_tracks.register(mcp)

    from . import routing_coupled_pair

    routing_coupled_pair.register(mcp)

    from . import routing_one_via

    routing_one_via.register(mcp)

    from . import routing_specctra_staging

    routing_specctra_staging.register(mcp)

    from . import routing_ses_apply

    routing_ses_apply.register(mcp)

    from . import routing_autorouter

    routing_autorouter.register(mcp)

    from . import routing_net_class_rules

    routing_net_class_rules.register(
        mcp,
        routing_net_class_rules.dependencies(_write_rule),
    )

    from . import routing_differential_pair

    routing_differential_pair.register(
        mcp,
        routing_differential_pair.dependencies(
            list_board_net_names=lambda: _list_board_net_names(),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_length_tuning

    routing_length_tuning.register(
        mcp,
        routing_length_tuning.dependencies(
            list_board_net_names=lambda: _list_board_net_names(),
            current_track_length_mm=lambda net_name: _current_track_length_mm(net_name),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_tuning_profiles

    routing_tuning_profiles.register(mcp)

    from . import routing_time_domain_tuning

    routing_time_domain_tuning.register(
        mcp,
        routing_time_domain_tuning.dependencies(
            current_track_length_for_pattern_mm=lambda net_pattern: (
                _current_track_length_for_pattern_mm(net_pattern)
            ),
            stackup_context_for_layer=lambda layer: _impedance_context_for_layer(
                _current_stackup_specs(),
                layer,
            ),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_diff_pair_length

    routing_diff_pair_length.register(
        mcp,
        routing_diff_pair_length.dependencies(
            list_board_net_names=lambda: _list_board_net_names(),
            current_track_length_mm=lambda net_name: _current_track_length_mm(net_name),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )

    from . import routing_board_constraints

    routing_board_constraints.register(
        mcp,
        routing_board_constraints.dependencies(
            load_design_intent=lambda: _load_design_intent(),
            write_rule=lambda name, body: _write_rule(name, body),
        ),
    )
