import { build } from "esbuild";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const templatePath = resolve(root, "src/project-review.html");
const outputPath = resolve(root, "dist/project-review.html");
const marker = "/*__PROJECT_REVIEW_BUNDLE__*/";
const html = readFileSync(templatePath, "utf8");
if (html.split(marker).length !== 2) {
  throw new Error("Project review HTML requires one inline bundle marker");
}
const result = await build({
  entryPoints: [resolve(root, "src/project-review-app.ts")],
  bundle: true,
  write: false,
  format: "iife",
  platform: "browser",
  minify: true,
});
if (result.outputFiles.length !== 1) {
  throw new Error("Unexpected project review bundle count");
}
// Only trusted, built-in source goes into the fixed HTML template.
// Escape script-end tags to preserve the HTML parser boundary.
const builtScript = result.outputFiles[0].text.replace(/<\/script/gi, "<\\/script");
writeFileSync(outputPath, html.replace(marker, builtScript));
