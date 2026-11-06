// OS-independent build step. Windows PowerShell and cmd.exe do not provide cp.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const base = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(base, "dist");
mkdirSync(dist, { recursive: true });
for (const name of ["owner-read-enrollment-client.js", "owner-read-review-client.js"]) {
  copyFileSync(resolve(base, "src", name), resolve(dist, name));
}
