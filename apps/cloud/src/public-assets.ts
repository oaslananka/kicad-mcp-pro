import {readFileSync} from "node:fs";

/**
 * A fixed allowlist of public, build-time assets. Never use URL paths to
 * construct filesystem paths or publish project/owner files.
 */
const types:Readonly<Record<string,{file:string;contentType:string}>>={
  "/favicon.ico":{file:"favicon.ico",contentType:"image/x-icon"},
  "/favicon.svg":{file:"favicon.svg",contentType:"image/svg+xml"},
  "/assets/icon.svg":{file:"favicon.svg",contentType:"image/svg+xml"},
  "/assets/favicon-16.png":{file:"favicon-16.png",contentType:"image/png"},
  "/assets/favicon-32.png":{file:"favicon-32.png",contentType:"image/png"},
  "/apple-touch-icon.png":{file:"apple-touch-icon.png",contentType:"image/png"},
  "/assets/icon-192.png":{file:"icon-192.png",contentType:"image/png"},
  "/assets/icon-512.png":{file:"icon-512.png",contentType:"image/png"},
  "/site.webmanifest":{file:"site.webmanifest",contentType:"application/manifest+json"},
  "/llms.txt":{file:"llms.txt",contentType:"text/plain; charset=utf-8"},
  "/llms-full.txt":{file:"llms-full.txt",contentType:"text/plain; charset=utf-8"},
  "/robots.txt":{file:"robots.txt",contentType:"text/plain; charset=utf-8"},
  "/sitemap.xml":{file:"sitemap.xml",contentType:"application/xml; charset=utf-8"},
  "/sitemap.md":{file:"sitemap.md",contentType:"text/markdown; charset=utf-8"},
  "/AGENTS.md":{file:"AGENTS.md",contentType:"text/markdown; charset=utf-8"},
  "/index.md":{file:"index.md",contentType:"text/markdown; charset=utf-8"},
};
const publicBodies=new Map(
  Object.entries(types).map(([url,entry])=>[
    url,{
      body:readFileSync(new URL("../assets/"+entry.file,import.meta.url)),
      contentType:entry.contentType,
    }
  ])
);
export function publicAsset(path:string){
  return publicBodies.get(path);
}
