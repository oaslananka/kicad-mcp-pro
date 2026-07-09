# Repository Topology

The only canonical source and release authority is:

https://github.com/oaslananka/kicad-mcp-pro

Release and publish automation runs from GitHub Actions in this repository. Package publishing is split by protected environment:

- `extension-marketplaces` for VS Code Marketplace and Open VSX.
- `testpypi` and `pypi` for Python package publishing through trusted publishing.
- `npm` for npm trusted publishing.
- `mcp-registry` for MCP Registry publishing through GitHub OIDC.
