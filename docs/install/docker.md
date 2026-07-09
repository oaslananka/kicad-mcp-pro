# Docker Install

The runtime image is published to GitHub Container Registry:

```text
ghcr.io/oaslananka/kicad-mcp-pro
```

The image runs as the non-root `kicadmcp` user, exposes port `3334`, and starts
`kicad-mcp-pro --transport streamable-http` by default. It binds to `0.0.0.0`
inside the container so Docker port publishing reaches the server; keep the
published host port on loopback unless a trusted proxy or tunnel handles
access. It does not contain secrets.

## Help Smoke Test

```bash
docker run --rm ghcr.io/oaslananka/kicad-mcp-pro:latest --help
```

For reproducible deployments, pin the image by a version tag or immutable GHCR
digest:

```bash
docker run --rm ghcr.io/oaslananka/kicad-mcp-pro:<version> --help
docker run --rm ghcr.io/oaslananka/kicad-mcp-pro@sha256:<digest> --help
```

## Streamable HTTP

Run the default streamable HTTP server for local connector testing:

```bash
docker run --rm \
  -p 127.0.0.1:3334:3334 \
  -e KICAD_MCP_AUTH_TOKEN="replace-with-strong-32-character-token" \
  -e KICAD_MCP_PROJECT_DIR=/projects \
  -v "$PWD:/projects:ro" \
  ghcr.io/oaslananka/kicad-mcp-pro:<version>
```

The MCP endpoint is `http://127.0.0.1:3334/mcp`. Binding HTTP to
`0.0.0.0` requires `KICAD_MCP_AUTH_TOKEN`; keep the published Docker port bound
to loopback unless a reverse proxy or tunnel terminates authentication.

## stdio Override

Use this form for MCP clients that communicate over standard input and output:

```bash
docker run --rm -i \
  -e KICAD_MCP_PROJECT_DIR=/projects \
  -v "$PWD:/projects:ro" \
  ghcr.io/oaslananka/kicad-mcp-pro:<version> \
  --transport stdio
```

Claude Desktop stdio example:

```json
{
  "mcpServers": {
    "kicad-mcp-pro": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v",
        "/absolute/path/to/project:/projects:ro",
        "-e",
        "KICAD_MCP_PROJECT_DIR=/projects",
        "ghcr.io/oaslananka/kicad-mcp-pro:<version>",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

## KiCad CLI

The published runtime image keeps KiCad external so operators can choose the
KiCad version that matches their projects. File-backed DRC, ERC, export, and
quality-gate tools need `kicad-cli` available inside the container through one
of these paths:

- mount a host-managed KiCad install and set `KICAD_MCP_KICAD_CLI`;
- build locally with `--build-arg KICAD_CLI_APK_PACKAGE=kicad` when the Alpine
  distribution package is acceptable for the target platform;
- build with `--build-arg KICAD_VERSION=kicad10` for CI images that extract an official KiCad 10
  AppImage at build time (see [`Dockerfile multi-stage`](https://github.com/oaslananka/kicad-mcp-pro/blob/main/Dockerfile)).

Redistributing images that bundle KiCad CLI brings KiCad's upstream license
terms into the image supply chain. Review the official
[KiCad licenses](https://www.kicad.org/about/licenses/) before publishing a
derived image with KiCad included.

## Compose

A Docker Compose example lives in the repository at `examples/mcp-docker`. It
mounts a KiCad project read-only, exposes the HTTP endpoint on localhost, and
keeps output files in a named volume.
