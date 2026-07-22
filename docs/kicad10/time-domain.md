# KiCad 10 Time-Domain Tuning

The following helpers were added for KiCad 10 style time-domain routing workflows:

- `route_create_tuning_profile(...)`
- `route_list_tuning_profiles()`
- `route_apply_tuning_profile(net_pattern, profile_name)`
- `route_tune_time_domain(net_or_group, target_delay_ps, tolerance_ps=10)`

## How It Works

Profile definitions are stored in `.kicad-mcp/tuning_profiles.json`. When a stackup is available, `route_tune_time_domain(...)` derives an effective dielectric constant from the selected layer context and converts delay targets into a computed length target. The resulting delay and length constraints are then written into `.kicad_dru`.

If no usable stackup context exists, the helper falls back to the legacy propagation-speed-factor path. This fallback preserves file-level behavior but does not imply support for dropped KiCad lines.
