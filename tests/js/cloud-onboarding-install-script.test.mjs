import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const installer=readFileSync(new URL("../../scripts/install-cloud.ps1",import.meta.url),"utf8");

test("Windows one-command Cloud bootstrap installs or upgrades and repairs only its tool",()=>{
  assert.match(installer,/Get-Command uv -CommandType Application -ErrorAction SilentlyContinue \| Select-Object -First 1/);
  assert.match(installer,/\$uvPath = if \(\$null -ne \$uv\) \{ \$uv\.Source \}/);
  assert.match(installer,/\& \$uvPath tool install --upgrade \$package/);
  assert.match(installer,/\& \$uvPath tool install --force --reinstall \$package/g);
  assert.match(installer,/\& \$uvPath tool dir --bin/);
  assert.match(installer,/function Test-Tool\(\[string\]\$executable\)/);
  assert.match(installer,/\& \$cliPath cloud/);
  assert.match(installer,/\$existingHealthy = Test-Tool \$cliPath/);
  assert.match(installer,/\$dedicatedTools = Join-Path \$appRoot "uv-tools"/);
  assert.match(installer,/\$env:UV_TOOL_DIR = \$dedicatedTools/);
  assert.match(installer,/\$env:UV_TOOL_BIN_DIR = \$dedicatedBin/);
  assert.match(installer,/\$env:PATH = "\$dedicatedBin;\$originalPath"/);
  assert.match(installer,/\$env:PATH = \$originalPath/);
  assert.match(installer,/Get-CimInstance Win32_Process/);
  assert.match(installer,/\$running\.Count -gt 0/);
  assert.match(installer,/No update or duplicate connection was started/);
  assert.match(installer,/finally \{\s*\$env:UV_TOOL_DIR = \$originalToolDir/);
  assert.match(installer,/if \(\$existingHealthy -and \(Test-Tool \$cliPath\)\)/);
  assert.match(installer,/Update unavailable; starting the existing working version/);
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
