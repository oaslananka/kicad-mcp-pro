import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const installer=readFileSync(new URL("../../scripts/install-cloud.ps1",import.meta.url),"utf8");

test("Windows one-command Cloud bootstrap installs or upgrades and repairs only its tool",()=>{
  assert.match(installer,/Get-Command uv -CommandType Application/);
  assert.match(installer,/\& \$uvPath tool install --upgrade \$package/);
  assert.match(installer,/\& \$uvPath tool install --force --reinstall \$package/g);
  assert.match(installer,/\& \$uvPath tool dir --bin/);
  assert.match(installer,/function Test-Tool\(\[string\]\$executable\)/);
  assert.match(installer,/\& \$cliPath cloud/);
  assert.match(installer,/\$existingHealthy = Test-Tool \$cliPath/);
  assert.match(installer,/if \(\$existingHealthy\)/);
  assert.match(installer,/Update check failed\. Starting the existing working version/);
  assert.doesNotMatch(installer,/\& \$uvxPath --from/);
  assert.match(installer,/if \(\$LASTEXITCODE -ne 0\)/);
  assert.match(installer,/if \(-not \(Test-Tool \$cliPath\)\)/);
});

test("Installer preserves user data and uses verified Astral release bytes",()=>{
  assert.match(installer,/https:\/\/github\.com\/astral-sh\/uv\/releases\/download\//);
  assert.match(installer,/Get-FileHash -LiteralPath \$archive -Algorithm SHA256/);
  assert.match(installer,/Expand-Archive -LiteralPath \$archive/);
  assert.match(installer,/uv-x86_64-pc-windows-msvc\.zip/);
  assert.match(installer,/uv-aarch64-pc-windows-msvc\.zip/);
  assert.match(installer,/uv-i686-pc-windows-msvc\.zip/);
  assert.doesNotMatch(installer,/Invoke-Expression|https:\/\/astral\.sh\/uv\/install\.ps1/i);
  assert.doesNotMatch(installer,/cloud (?:setup|remote|connect|reconnect|repair)|new-device|enable-native-write/);
  assert.doesNotMatch(installer,/uv tool uninstall|pip uninstall|pipx uninstall|Remove-Item.*kicad-mcp-pro/i);
  assert.match(installer,/Remove-Item -LiteralPath \$temporary -Recurse -Force/);
});
