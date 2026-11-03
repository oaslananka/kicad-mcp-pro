import http from "node:http";

// Coolify requires an in-container readiness probe. Reuse Node itself rather
// than adding curl/wget to the minimal runtime image. PUBLIC_ORIGIN selects
// the expected Host; querying loopback does not traverse DNS or Cloudflare.
try {
  const expected = new URL(process.env.PUBLIC_ORIGIN ?? "");
  const port = Number(process.env.PORT || "8787");
  if (!["http:", "https:"].includes(expected.protocol) ||
      !Number.isSafeInteger(port) || port < 1 || port > 65535) {
    process.exitCode = 1;
  } else {
    const request = http.get({
      hostname: "127.0.0.1",
      port,
      path: "/health",
      headers: { Host: expected.host },
      timeout: 3_000,
    }, response => {
      response.resume();
      process.exitCode = response.statusCode === 200 ? 0 : 1;
    });
    request.on("timeout", () => request.destroy(new Error("health timeout")));
    request.on("error", () => { process.exitCode = 1; });
  }
} catch {
  process.exitCode = 1;
}
