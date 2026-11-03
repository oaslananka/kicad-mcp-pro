import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

// This package is now in the main repository. The root GitHub Actions policy
// checks workflows separately; do not preserve duplicate nested workflows.
test("Cloud container and runtime never bake authentication secrets", async () => {
  const dockerfile = await readFile(new URL("../Dockerfile", import.meta.url), "utf8");
  const runtime = await readFile(
    new URL("../scripts/doppler-runtime.sh", import.meta.url),
    "utf8",
  );
  const compose = await readFile(
    new URL("../infra/compose.production.yml", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(dockerfile, /\b(?:COPY|ADD)\b[^\n]*\.(?:env|pem|key)\b/i);
  assert.doesNotMatch(dockerfile, /\b(?:DOPPLER_TOKEN|GOOGLE_CLIENT_SECRET|GITHUB_CLIENT_SECRET)\b/);
  assert.doesNotMatch(runtime, /doppler\s+secrets\s+download/);
  assert.match(runtime, /exec doppler run/);
  assert.match(compose, /GOOGLE_CLIENT_SECRET:\s*\$\{GOOGLE_CLIENT_SECRET:-\}/);
  assert.match(compose, /GITHUB_CLIENT_SECRET:\s*\$\{GITHUB_CLIENT_SECRET:-\}/);
  assert.doesNotMatch(compose, /\b(?:GOOGLE_CLIENT_SECRET|GITHUB_CLIENT_SECRET):\s*["'][^$]/);
});
