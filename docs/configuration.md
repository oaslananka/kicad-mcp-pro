# Configuration

Configuration is resolved in this order:

1. CLI arguments
2. Environment variables
3. `.env`
4. `~/.config/kicad-mcp-pro/config.toml`
5. Built-in defaults

The active project can also be changed at runtime with `kicad_set_project()`.
