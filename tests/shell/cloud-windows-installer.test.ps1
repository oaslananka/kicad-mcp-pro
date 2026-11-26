# Execute the actual bootstrap with a disposable native package fixture.
# No network, installed Connector, credentials, or user projects are touched.
param([string]$InstallerSource)
$ErrorActionPreference = "Stop"
if (-not $InstallerSource) {
    $InstallerSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot "../../scripts/install-cloud.ps1") -Raw
}
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput($InstallerSource, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$root = Join-Path ([IO.Path]::GetTempPath()) ("kicad-installer-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $root | Out-Null
$oldPath = $env:PATH
$oldLocal = $env:LOCALAPPDATA
$oldUv = $env:UV_INSTALL_DIR
$oldLog = $env:KICAD_TEST_LOG
$oldScenario = $env:KICAD_TEST_SCENARIO
try {
    $env:LOCALAPPDATA = Join-Path $root "local"
    $env:UV_INSTALL_DIR = Join-Path $root "uv-bin"
    New-Item -ItemType Directory -Path $env:LOCALAPPDATA,$env:UV_INSTALL_DIR | Out-Null
    $env:PATH = $env:UV_INSTALL_DIR + ";" + $oldPath
    $env:KICAD_TEST_LOG = Join-Path $root "events"
    $mock = Join-Path $env:UV_INSTALL_DIR "uv.exe"
    $code = @'
using System;
using System.IO;
using System.Reflection;
public class Fixture {
    public static int Main(string[] args) {
        string self = Assembly.GetExecutingAssembly().Location;
        if (args.Length > 0 && args[0] == "--version") {
            Console.WriteLine("fixture 1"); return 0;
        }
        if (Path.GetFileName(self).Equals("uv.exe", StringComparison.OrdinalIgnoreCase)) {
            string bin = Environment.GetEnvironmentVariable("UV_TOOL_BIN_DIR");
            if (args.Length >= 3 && args[0] == "tool" && args[1] == "dir") {
                Console.WriteLine(bin); return 0;
            }
            if (args.Length >= 3 && args[0] == "tool" && args[1] == "install") {
                if (Environment.GetEnvironmentVariable("UV_NO_CONFIG") != "1") return 96;
                Directory.CreateDirectory(bin);
                string target = Path.Combine(bin, "kicad-mcp-pro.exe");
                File.AppendAllText(Environment.GetEnvironmentVariable("KICAD_TEST_LOG"),
                    "install " + target + Environment.NewLine);
                string scenario = Environment.GetEnvironmentVariable("KICAD_TEST_SCENARIO");
                if (scenario == "failure" || scenario == "unhealthy") {
                    File.WriteAllText(target, "broken fixture");
                    return scenario == "failure" ? 1 : 0;
                }
                File.Copy(self, target, true); return 0;
            }
            return 97;
        }
        if (args.Length >= 1 && args[0] == "cloud") {
            if (args.Length == 2 && args[1] == "--help") {
                Console.WriteLine("--managed-edit"); return 0;
            }
            File.AppendAllText(Environment.GetEnvironmentVariable("KICAD_TEST_LOG"),
                "connected " + self + Environment.NewLine);
            return 0;
        }
        return 98;
    }
}
'@
    Add-Type -TypeDefinition $code -OutputAssembly $mock -OutputType ConsoleApplication
    # Never acquire the real user's installer mutex during fixture execution.
    $fixtureName = "Global\KiCadMcpProInstallerFixture-" + [guid]::NewGuid().ToString("N")
    $InstallerSource = $InstallerSource.Replace('Global\KiCadMcpProCloudInstallerV2-$sid', $fixtureName)
    $install = [scriptblock]::Create($InstallerSource)
    $app = Join-Path $env:LOCALAPPDATA "KiCadMCPPro"
    $pointer = Join-Path $app "active-release"
    $a = Join-Path $app "releases\a\bin\kicad-mcp-pro.exe"
    $b = Join-Path $app "releases\b\bin\kicad-mcp-pro.exe"
    $env:KICAD_TEST_SCENARIO = "success"
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a") { throw "First publish failed" }
    $hash = (Get-FileHash -LiteralPath $a).Hash
    foreach ($scenario in @("failure", "unhealthy")) {
        $env:KICAD_TEST_SCENARIO = $scenario
        & $install
        if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a" -or
            (Get-FileHash -LiteralPath $a).Hash -ne $hash) { throw "Active release changed on failure" }
        if ((Get-Content -LiteralPath $env:KICAD_TEST_LOG | Select-Object -Last 1) -ne ("connected " + $a)) {
            throw "Fallback did not launch A"
        }
        Write-Output "PASS: Windows $scenario preserves active A"
    }
    $env:KICAD_TEST_SCENARIO = "success"
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        (Get-FileHash -LiteralPath $a).Hash -ne $hash) { throw "Second publish failed" }
    if ((Get-Content -LiteralPath $env:KICAD_TEST_LOG | Select-Object -Last 1) -ne ("connected " + $b)) {
        throw "B did not launch"
    }
    Write-Output "PASS: Windows healthy candidate atomic B promotion"
} finally {
    $env:PATH = $oldPath
    $env:LOCALAPPDATA = $oldLocal
    $env:UV_INSTALL_DIR = $oldUv
    $env:KICAD_TEST_LOG = $oldLog
    $env:KICAD_TEST_SCENARIO = $oldScenario
    Remove-Item -LiteralPath $root -Recurse -Force
}
