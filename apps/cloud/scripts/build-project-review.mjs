import { build } from "esbuild";
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const base = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const result = await build({entryPoints:[resolve(base,"src/project-review-app.ts")],bundle:true,write:false,format:"iife",platform:"browser",minify:true});
const js = result.outputFiles[0].text.replace(/<\/script/gi,"<\\/script");
writeFileSync(resolve(base,"dist/project-review.html"), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:14px system-ui,sans-serif;margin:16px;color:CanvasText;background:Canvas}main{border:1px solid GrayText;border-radius:8px;padding:16px}h1{font-size:1.1rem}button{padding:8px 12px}</style></head><body><main><h1>KiCad Project Review</h1><p id="status" role="status">Waiting for project data…</p><div id="details"></div><button id="refresh" disabled>Refresh access</button></main><script>${js}</script></body></html>`);
