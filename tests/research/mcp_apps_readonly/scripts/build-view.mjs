import { build } from "esbuild";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const out = path.join(root, "dist");
await mkdir(out, { recursive: true });
const result = await build({
  entryPoints: [path.join(root, "src", "mcp-app.ts")],
  bundle: true,
  platform: "browser",
  format: "iife",
  write: false,
  minify: true,
  target: "es2022",
  logLevel: "silent",
});
const javascript = result.outputFiles?.[0]?.text;
if (!javascript) throw new Error("Missing bundled view JavaScript");
if (javascript.includes("</script")) throw new Error("Unsafe inline script terminator");
const document = await readFile(path.join(root, "src", "view.html"), "utf8");
if (!document.includes("<!-- APP_SCRIPT -->")) throw new Error("Missing view marker");
await writeFile(path.join(out, "view.html"), document.replace("<!-- APP_SCRIPT -->", () => "<script>" + javascript + "</script>"));
