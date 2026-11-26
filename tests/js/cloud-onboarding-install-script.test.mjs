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
  assert.match(installer,/\$existingHealthy = Test-Connector \$cliPath/);
  assert.match(installer,/\$dedicatedTools = Join-Path \$slotRoot "uv-tools"/);
  assert.match(installer,/\$env:UV_TOOL_DIR = \$dedicatedTools/);
  assert.match(installer,/\$env:UV_NO_CONFIG = "1"/);
  assert.match(installer,/\$env:UV_NO_CONFIG = \$originalNoConfig/);
  assert.match(installer,/\$env:UV_TOOL_BIN_DIR = \$dedicatedBin/);
  assert.match(installer,/\$env:PATH = "\$dedicatedBin;\$originalPath"/);
  assert.match(installer,/\$env:PATH = \$originalPath/);
  assert.match(installer,/Get-CimInstance Win32_Process/);
  assert.match(installer,/\$running\.Count -gt 0/);
  assert.match(installer,/Existing installation unchanged/);
  assert.match(installer,/finally \{\s*\$env:UV_TOOL_DIR = \$originalToolDir/);
  assert.match(installer,/elseif \(\$existingHealthy\)/);
  assert.match(installer,/Update unavailable; starting the existing working version/);
  assert.doesNotMatch(installer,/\& \$uvxPath --from/);
  assert.match(installer,/if \(\$LASTEXITCODE -ne 0\)/);
  assert.match(installer,/if \(-not \(Test-Connector \$cliPath\)\)/);
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

test("Windows installer serializes the entire bootstrap and releases its OS mutex",()=>{
  assert.match(installer,/WindowsIdentity\]::GetCurrent\(\)\.User\.Value/);
  assert.match(installer,/System\.Threading\.Mutex/);
  assert.match(installer,/WaitOne\(0\)/);
  assert.match(installer,/AbandonedMutexException/);
  assert.match(installer,/ReleaseMutex\(\)/);
  assert.match(installer,/\.Dispose\(\)/);
  assert.ok(installer.indexOf("WaitOne(0)")<installer.indexOf("Invoke-WebRequest"));
});

test("Windows publishes only a healthy inactive release and preserves the previous environment",()=>{
  assert.match(installer,/\$candidate = if \(\$active -eq "a"\) \{ "b" \} else \{ "a" \}/);
  assert.match(installer,/\$cliPath = Select-ReleaseSlot \$candidate/);
  assert.match(installer,/\$installed = \(\$LASTEXITCODE -eq 0\) -and \(Test-Connector \$cliPath\)/);
  assert.match(installer,/if \(\$installed\) \{[\s\S]*Publish-Release \$candidate/);
  assert.match(installer,/\[IO\.File\]::Replace\(\$temporary, \$pointer, \$backup\)/);
  assert.match(installer,/\$cliPath = Select-ReleaseSlot \$active/);
});

test("Live Windows update prepares before requesting drain and waits for session ownership",()=>{
  assert.match(installer,/KiCadMcpProCloudPrepareV1/);
  assert.match(installer,/Get-UpdateLease \$activeCli \$active/);
  assert.ok(installer.indexOf("tool install --upgrade") < installer.indexOf("cloud _update-control request"));
  assert.ok(installer.indexOf("cloud _update-control request") < installer.indexOf("Publish-Release $candidate"));
  assert.match(installer,/while \(-not \$ownsInstallerMutex\)/);
  assert.match(installer,/Update unavailable; existing Connector was not asked to stop/);
  assert.doesNotMatch(installer,/Stop-Process|taskkill/i);
});

test("Windows preserves the remaining healthy release and rechecks the candidate after drain",()=>{
  assert.match(installer,/\$ownsInstallerMutex -and \$active -ne "legacy" -and -not \(Test-Connector \$activeCli\)/);
  assert.match(installer,/\$previousCli = Select-ReleaseSlot \$candidate/);
  assert.match(installer,/Restored the previous working installation without upgrading it/);
  assert.match(installer,/if \(Test-Connector \$cliPath\) \{\s*Publish-Release \$candidate/);
  assert.match(installer,/elseif \(Test-Connector \$activeCli\)/);
  assert.match(installer,/Candidate failed its final startup check/);
});

test("Windows persists the prepared generation before drain and resumes without installing",()=>{
  assert.match(installer,/function Read-PendingRelease/);
  assert.match(installer,/function Save-PendingRelease/);
  assert.match(installer,/pending-release/);
  assert.match(installer,/\.Flush\(\$true\)/);
  const save=installer.indexOf("Save-PendingRelease $active $candidate $generation");
  const request=installer.indexOf("cloud _update-control request");
  assert.ok(save>=0 && save<request);
  assert.match(installer,/if \(\$null -ne \$pending\) \{[\s\S]*Resuming the prepared update without reinstalling/);
  assert.match(installer,/A different Connector session is running/);
  assert.match(installer,/Saved candidate is no longer healthy/);
});

test("Windows validates marker ownership and hardlinks on the read handle before choosing a release",()=>{
  assert.match(installer,/GetSecurityInfo/);
  assert.match(installer,/GetFileInformationByHandle/);
  assert.match(installer,/info\.Links != 1/);
  assert.match(installer,/RawSecurityDescriptor/);
  assert.match(installer,/DiscretionaryAcl == null/);
  assert.match(installer,/Read-LocalMarker \$pendingPath 37/);
  assert.match(installer,/Read-LocalMarker \$pointer 3/);
  assert.doesNotMatch(installer,/\[IO\.File\]::ReadAllText\(\$(?:pendingPath|pointer)/);
});
