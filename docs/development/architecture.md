# Architecture

The project is organized as a src-based Python package with:

- `config.py` for settings and path safety
- `discovery.py` for CLI and project detection
- `connection.py` for KiCad IPC lifecycle
- `tools/` for domain-specific MCP tools
- `resources/` and `prompts/` for MCP-native context surfaces
