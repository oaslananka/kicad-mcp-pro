# Security

For HTTP deployments, the following checks are recommended:

- Enable bearer-token protection with `KICAD_MCP_AUTH_TOKEN`.
- Keep HTTP on loopback, or explicitly select a protected boundary with `KICAD_MCP_HTTP_BOUNDARY`: direct TLS (`KICAD_MCP_TLS_CERT_FILE` + `KICAD_MCP_TLS_KEY_FILE`), `loopback-proxy` for a bind-all container published only to host loopback, or `tls-proxy` with an HTTPS `KICAD_MCP_PUBLIC_BASE_URL`. A bearer token does not provide transport confidentiality.
- Limit `KICAD_MCP_CORS_ORIGINS` to only the origins you actually need.
- Use the `resolve_within_project()` flow for path parameters so requests cannot escape the active project root.
- Run manufacturing/export tools only after the relevant quality gate passes.
