# syntax=docker/dockerfile:1.7
ARG KICAD_APPIMAGE_URL
ARG UV_VERSION=0.11.31

FROM ghcr.io/astral-sh/uv:${UV_VERSION}@sha256:ecd4de2f060c64bea0ff8ecb182ddf46ba3fcccdc8a60cfdbaf20d1a047d7437 AS uv-bin

FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS kicad-extract
ARG KICAD_APPIMAGE_URL
ARG DEBIAN_FRONTEND=noninteractive
RUN if [ -n "${KICAD_APPIMAGE_URL}" ]; then \
      apt-get update && apt-get install -y --no-install-recommends ca-certificates curl fuse libfuse2 file \
      && rm -rf /var/lib/apt/lists/* \
      && curl -fL "${KICAD_APPIMAGE_URL}" -o /tmp/kicad.AppImage \
      && chmod +x /tmp/kicad.AppImage \
      && /tmp/kicad.AppImage --appimage-extract \
      && mkdir -p /opt/kicad-appimage \
      && cp -a squashfs-root/. /opt/kicad-appimage/; \
    fi; \
    mkdir -p /opt/kicad-appimage

FROM python:3.14.5-alpine3.22@sha256:6b91e66ab2a880ce9ca5a1b91c70f45963ff71ff68268df056336e1a657d5efd AS builder
ENV UV_NO_CACHE=1
COPY --from=uv-bin /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
RUN uv build --wheel --out-dir /dist \
  && uv export --frozen --no-dev --no-emit-project \
    --format requirements.txt \
    --output-file /dist/requirements.txt

FROM python:3.14.7-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS builder-kicad10
ENV UV_NO_CACHE=1
COPY --from=uv-bin /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
RUN uv sync --frozen --extra http --extra simulation --extra freerouting

FROM python:3.14.5-alpine3.22@sha256:6b91e66ab2a880ce9ca5a1b91c70f45963ff71ff68268df056336e1a657d5efd AS runtime
ARG KICAD_MCP_VERSION=0.0.0
ARG VCS_REF=unknown
ARG KICAD_CLI_APK_PACKAGE=
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  KICAD_MCP_TRANSPORT=streamable-http \
  KICAD_MCP_HOST=0.0.0.0
WORKDIR /app
COPY --from=uv-bin /uv /usr/local/bin/uv
LABEL io.modelcontextprotocol.server.name="io.github.oaslananka/kicad-mcp-pro" \
  org.opencontainers.image.title="kicad-mcp-pro" \
  org.opencontainers.image.description="Professional MCP server for KiCad automation" \
  org.opencontainers.image.source="https://github.com/oaslananka/kicad-mcp-pro" \
  org.opencontainers.image.version="${KICAD_MCP_VERSION}" \
  org.opencontainers.image.revision="${VCS_REF}" \
  org.opencontainers.image.licenses="MIT"
RUN apk upgrade --no-cache \
  && if [ -n "${KICAD_CLI_APK_PACKAGE}" ]; then apk add --no-cache "${KICAD_CLI_APK_PACKAGE}"; fi \
  && addgroup -S kicadmcp \
  && adduser -S -G kicadmcp -h /app -s /sbin/nologin kicadmcp
COPY --from=builder /dist/ /tmp/dist/
COPY docker-entrypoint.sh /usr/local/bin/kicad-mcp-pro-entrypoint
# Install hash-pinned dependencies first (uv export emits hashes, so pip runs in
# --require-hashes mode), then the first-party wheel separately with --no-deps. A local
# wheel has no hash, so installing it on the same command line as the hashed requirements
# fails hash-mode validation; splitting the steps keeps the supply-chain pinning intact.
RUN uv pip install --system --no-cache --require-hashes --requirement /tmp/dist/requirements.txt \
  && uv pip install --system --no-cache --no-deps /tmp/dist/*.whl \
  && rm -rf /tmp/dist \
  && rm -f /usr/local/bin/uv \
  && chmod 0755 /usr/local/bin/kicad-mcp-pro-entrypoint
USER kicadmcp
EXPOSE 3334
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; exit(0 if urllib.request.urlopen('http://127.0.0.1:3334/api/health').status == 200 else 1)" 2>/dev/null || exit 1
ENTRYPOINT ["kicad-mcp-pro-entrypoint"]
CMD ["--transport", "streamable-http"]

FROM python:3.14.7-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS runtime-kicad10
ARG KICAD_MCP_VERSION=0.0.0
ARG VCS_REF=unknown
ENV DEBIAN_FRONTEND=noninteractive \
  PATH="/app/.venv/bin:/opt/kicad-appimage/usr/bin:$PATH" \
  KICAD_MCP_TRANSPORT=streamable-http \
  KICAD_MCP_HOST=127.0.0.1 \
  KICAD_MCP_KICAD_CLI=/opt/kicad-appimage/usr/bin/kicad-cli
WORKDIR /app
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
  && apt-get install -y --no-install-recommends ca-certificates libgl1 libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --system kicadmcp \
  && useradd --system --gid kicadmcp --home-dir /app --shell /usr/sbin/nologin kicadmcp
COPY --from=builder-kicad10 --chown=kicadmcp:kicadmcp /app/.venv .venv
COPY --from=kicad-extract /opt/kicad-appimage /opt/kicad-appimage
COPY --chown=kicadmcp:kicadmcp src/ src/
COPY --chown=kicadmcp:kicadmcp README.md LICENSE ./
COPY docker-entrypoint.sh /usr/local/bin/kicad-mcp-pro-entrypoint
RUN chmod 0755 /usr/local/bin/kicad-mcp-pro-entrypoint
LABEL io.modelcontextprotocol.server.name="io.github.oaslananka/kicad-mcp-pro" \
  org.opencontainers.image.title="kicad-mcp-pro-kicad10" \
  org.opencontainers.image.description="KiCad MCP Pro with KiCad 10 kicad-cli from AppImage. Not for shared hosting." \
  org.opencontainers.image.source="https://github.com/oaslananka/kicad-mcp-pro" \
  org.opencontainers.image.version="${KICAD_MCP_VERSION}" \
  org.opencontainers.image.revision="${VCS_REF}" \
  org.opencontainers.image.licenses="MIT"
USER kicadmcp
EXPOSE 3334
ENTRYPOINT ["kicad-mcp-pro-entrypoint"]
CMD ["--transport", "streamable-http"]

FROM runtime
