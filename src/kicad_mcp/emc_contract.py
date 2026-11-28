"""Explicit access contract for source-reviewed EMC board readers."""

# Explicitly reviewed EMC board readers; future EMC tools are not implicitly safe.
EMC_READ_TOOLS = frozenset(
    {
        "emc_check_ground_plane_voids",
        "emc_check_return_path_continuity",
        "emc_check_split_plane_crossing",
        "emc_check_decoupling_placement",
        "emc_check_via_stitching",
        "emc_check_differential_pair_symmetry",
        "emc_check_high_speed_routing_rules",
        "emc_run_full_compliance",
    }
)
