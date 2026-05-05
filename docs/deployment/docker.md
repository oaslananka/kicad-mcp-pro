# Docker Deployment

Docker can be used to run the HTTP transport for remote access or an internal team bridge.

## Basic Flow

```bash
docker build -t kicad-mcp-pro .
docker run --rm -p 27185:27185 \
  -e KICAD_MCP_TRANSPORT=http \
  -e KICAD_MCP_PORT=27185 \
  -e KICAD_MCP_HOST=0.0.0.0 \
  kicad-mcp-pro
```

For production-style deployments, set `KICAD_MCP_AUTH_TOKEN` and keep `KICAD_MCP_CORS_ORIGINS` narrowly scoped.

## KiCad 10 CI Image

The default `Dockerfile` does not bundle KiCad. This keeps the runtime small and
lets production hosts mount their own trusted `kicad-cli`.

For CI jobs that need a self-contained KiCad 10 CLI, use `Dockerfile.kicad10`.
Pass an official Linux x86_64 KiCad 10 AppImage URL from the
[KiCad Linux download page](https://www.kicad.org/download/linux/):

```bash
docker build \
  -f Dockerfile.kicad10 \
  --build-arg KICAD_APPIMAGE_URL="https://downloads.kicad.org/path/to/KiCad-10.x-x86_64.AppImage" \
  -t ghcr.io/oaslananka/kicad-mcp-pro:kicad10-ci .
```

The `:kicad10-ci` tag is intentionally neutral. It represents the local CI image
built for runtime validation, not a published project release version.

Then run a smoke test:

```bash
docker run --rm -v "$PWD:/project" \
  ghcr.io/oaslananka/kicad-mcp-pro:kicad10-ci \
  kicad-mcp-pro --help
```

GitHub Actions jobs that build this image should provide the KiCad AppImage URL
through a repository variable or secret such as `KICAD_10_APPIMAGE_URL`.

This image is intended for CI and release validation. Do not use it as a shared
multi-tenant host unless you also configure bearer auth, strict CORS origins,
network isolation, and read/write project volume boundaries.
