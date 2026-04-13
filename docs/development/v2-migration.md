# v2 Migration Notes

## Component Search Surface

The v2 library surface removes the legacy browser-URL helpers:

- `lib_get_lcsc_search_url`
- `lib_search_lcsc`

Use the live component tools instead:

- `lib_search_components`
- `lib_get_component_details`
- `lib_assign_lcsc_to_symbol`
- `lib_get_bom_with_pricing`
- `lib_check_stock_availability`
- `lib_find_alternative_parts`

### Default Source

`jlcsearch` is the default live source because it is zero-auth and works in the
standard local profile.

### Optional Sources

`nexar` and `digikey` require external credentials and are intended for
authenticated deployments.
