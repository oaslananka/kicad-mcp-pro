import { bench, describe } from "vitest";
import { loadConfig } from "../src/config.js";

const env = {
  PUBLIC_ORIGIN: "https://cloud.example",
  OAUTH_ISSUER: "https://auth.example",
  OAUTH_JWKS_URL: "https://auth.example/jwks",
  OAUTH_AUDIENCE: "https://cloud.example/mcp",
  DATABASE_URL: "postgres://example",
  ALLOWED_ORIGINS: "https://chatgpt.com,https://claude.ai,https://cloud.example"
};

describe("config", () => {
  bench("loadConfig", () => {
    loadConfig(env);
  });
});
