import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const installer=readFileSync(new URL("../../scripts/install-cloud.ps1",import.meta.url),"utf8");

test("PowerShell onboarding runs one foreground Cloud entrypoint and never re-pairs unconditionally",()=>{
  assert.match(installer,/\& \$uvxPath --from "kicad-mcp-pro" "kicad-mcp-pro" "cloud"/);
  assert.match(installer,/Get-Command uvx/);
  assert.match(installer,/https:\/\/astral\.sh\/uv\/install\.ps1/);
  assert.match(installer,/Test-Path -LiteralPath \$candidate/);
  assert.doesNotMatch(installer,/cloud (?:setup|remote|connect|reconnect|repair)|new-device|enable-native-write/);
});
