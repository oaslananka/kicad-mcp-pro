# Docker Deployment

For install and client examples, see [Docker Install](../install/docker.md).

The published image is `ghcr.io/oaslananka/kicad-mcp-pro`. It is built from the
multi-stage `packages/mcp-server/Dockerfile`, runs as a non-root user, exposes
port `3334`, and defaults to streamable HTTP. It binds to `0.0.0.0` inside the
container so Docker port publishing can reach the server.

## Local HTTP Service

```bash
docker run --rm \
  -p 127.0.0.1:3334:3334 \
  -e KICAD_MCP_AUTH_TOKEN="replace-with-strong-32-character-token" \
  -e KICAD_MCP_HTTP_BOUNDARY="loopback-proxy" \
  -e KICAD_MCP_PUBLIC_BASE_URL="http://127.0.0.1:3334" \
  -e KICAD_MCP_PROJECT_DIR=/projects \
  -e KICAD_MCP_OUTPUT_DIR=/tmp/kicad-mcp-output \
  -v "$PWD:/projects:ro" \
  -v kicad-mcp-output:/tmp/kicad-mcp-output \
  ghcr.io/oaslananka/kicad-mcp-pro:<version>
```

Use `http://127.0.0.1:3334/mcp` as the MCP URL. Do not expose this container on
a public interface without a bearer token, strict CORS origins, and a TLS
terminating proxy or tunnel.

## Volume Mounts

- Mount KiCad projects read-only at `/projects` for analysis, DRC, ERC, and
  export workflows.
- Set `KICAD_MCP_PROJECT_DIR=/projects` so tools resolve relative project paths
  inside the container.
- Mount a writable output location such as `/tmp/kicad-mcp-output` for generated
  manufacturing files.
- If KiCad is installed outside the image, mount the directory containing
  `kicad-cli` and set `KICAD_MCP_KICAD_CLI` to its in-container path.

## Environment Variables

| Variable                | Purpose                                                                                                          |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `KICAD_MCP_TRANSPORT`   | Defaults to `streamable-http`; set `stdio` only when overriding the Docker command for stdio clients.            |
| `KICAD_MCP_HOST`        | Defaults to `0.0.0.0` inside Docker so published port `3334` reaches the server.                                 |
| `KICAD_MCP_PORT`        | Defaults to `3334`.                                                                                              |
| `KICAD_MCP_AUTH_TOKEN`  | Required when HTTP binds outside loopback. Use a 32+ character token and pass it as a bearer token from clients. |
| `KICAD_MCP_HTTP_BOUNDARY` | Set `loopback-proxy` when Docker publishes `3334` only to host loopback; use `tls-proxy` behind a trusted HTTPS tunnel/reverse proxy. |
| `KICAD_MCP_PUBLIC_BASE_URL` | Required for proxy boundary modes. Use loopback HTTP with `loopback-proxy`; use the external HTTPS origin with `tls-proxy`. |
| `KICAD_MCP_PROJECT_DIR` | In-container project mount path, typically `/projects`.                                                          |
| `KICAD_MCP_OUTPUT_DIR`  | Writable output directory for generated artifacts.                                                               |
| `KICAD_MCP_KICAD_CLI`   | Optional path to `kicad-cli` if it is mounted or bundled.                                                        |

## Docker Compose

The repository example at `examples/mcp-docker` starts the HTTP service with a
read-only project mount:

```bash
export KICAD_MCP_AUTH_TOKEN="replace-with-strong-32-character-token"
docker compose -f examples/mcp-docker/docker-compose.yml up
```

Override `KICAD_PROJECT_DIR` to point at a local KiCad project.

## ChatGPT Connector Recipe

1. Start the container or Compose service on localhost with
   `KICAD_MCP_AUTH_TOKEN` set.
2. Expose the local endpoint through an HTTPS tunnel such as Cloudflare Tunnel:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:3334
   ```

3. Restart the server/container with `KICAD_MCP_HTTP_BOUNDARY=tls-proxy` and `KICAD_MCP_PUBLIC_BASE_URL=https://<tunnel-host>` so discovery/auth metadata matches the protected HTTPS endpoint.
4. In the ChatGPT connector configuration, set the MCP URL to
   `https://<tunnel-host>/mcp`.
5. Configure authentication as a bearer token using the same
   `KICAD_MCP_AUTH_TOKEN`.
6. Keep the KiCad project mounted read-only unless the workflow intentionally
   writes generated project files.

## KiCad CLI Images

The default published image keeps KiCad external. To install the Alpine
distribution package during a local build, pass its APK package name:

```bash
docker build \
  --build-arg KICAD_CLI_APK_PACKAGE=kicad \
  -t kicad-mcp-pro:kicad-cli .
```

For CI jobs that need a self-contained KiCad 10 CLI, build with the `kicad10` variant.
Pass an official Linux x86_64 KiCad 10 AppImage URL from the
[KiCad Linux download page](https://www.kicad.org/download/linux/):

```bash
docker build \
  --build-arg KICAD_VERSION=kicad10 \
  --build-arg KICAD_APPIMAGE_URL="https://downloads.kicad.org/path/to/KiCad-10.x-x86_64.AppImage" \
  -t ghcr.io/oaslananka/kicad-mcp-pro:kicad10-ci .
```

The bundled KiCad 10 image binds its HTTP server to `127.0.0.1` by default so it
remains usable for CI smoke checks without requiring a baked-in token.

Redistributing an image with KiCad CLI included adds KiCad's upstream license
terms to the derived image. Review the official
[KiCad licenses](https://www.kicad.org/about/licenses/) before publishing such
an image.
