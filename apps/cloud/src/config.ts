export interface Config {
  host: string;
  port: number;
  publicOrigin: string;
  issuer: string;
  jwksUrl: string;
  audience: string;
  databaseUrl: string;
  allowedOrigins: string[];
  managementClientId: string;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const publicOrigin = env.PUBLIC_ORIGIN ?? "";
  const issuer = env.OAUTH_ISSUER ?? "";
  const jwksUrl = env.OAUTH_JWKS_URL ?? "";
  const audience = env.OAUTH_AUDIENCE ?? "";
  const databaseUrl = env.DATABASE_URL ?? "";
  if (!publicOrigin || !issuer || !jwksUrl || !audience || !databaseUrl) {
    throw new Error("Missing PUBLIC_ORIGIN, OAUTH_ISSUER, OAUTH_JWKS_URL, OAUTH_AUDIENCE or DATABASE_URL");
  }
  const origin = new URL(publicOrigin);
  const issuerUrl = new URL(issuer);
  const jwks = new URL(jwksUrl);
  const isLocal = origin.hostname === "127.0.0.1" || origin.hostname === "localhost";
  if (origin.pathname !== "/" || origin.search || origin.hash || origin.username || origin.password) {
    throw new Error("PUBLIC_ORIGIN must be an origin, not a path or credential-bearing URL");
  }
  if (origin.protocol !== "https:" && !(isLocal && origin.protocol === "http:")) {
    throw new Error("Public MCP origin must use HTTPS");
  }
  if (issuerUrl.protocol !== "https:" || jwks.protocol !== "https:") {
    throw new Error("OAuth issuer and JWKS URL must use HTTPS");
  }
  if (audience !== origin.origin + "/mcp") {
    throw new Error("OAUTH_AUDIENCE must identify this MCP resource");
  }
  const port = Number(env.PORT ?? "8787");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid port");
  const host = env.HOST ?? "127.0.0.1";
  if (host !== "127.0.0.1" && !isLocal && origin.protocol !== "https:") {
    throw new Error("Non-loopback binding requires HTTPS public origin");
  }
  const allowedOrigins = (env.ALLOWED_ORIGINS ?? "").split(",").map(s => s.trim()).filter(Boolean);
  for (const value of allowedOrigins) {
    if (new URL(value).origin !== value || !value.startsWith("https://")) {
      throw new Error("ALLOWED_ORIGINS entries must be exact HTTPS origins");
    }
  }
  return { host, port, publicOrigin: origin.origin, issuer, jwksUrl, audience, databaseUrl, allowedOrigins, managementClientId: env.MANAGEMENT_CLIENT_ID ?? "" };
}
