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
$oldControl = $env:KICAD_TEST_CONTROL
$job = $null
try {
    $env:LOCALAPPDATA = Join-Path $root "local"
    $env:UV_INSTALL_DIR = Join-Path $root "uv-bin"
    New-Item -ItemType Directory -Path $env:LOCALAPPDATA,$env:UV_INSTALL_DIR | Out-Null
    $env:PATH = $env:UV_INSTALL_DIR + ";" + $oldPath
    $env:KICAD_TEST_LOG = Join-Path $root "events"
    $env:KICAD_TEST_CONTROL = Join-Path $root "control"
    New-Item -ItemType Directory -Path $env:KICAD_TEST_CONTROL | Out-Null
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
            string control = Environment.GetEnvironmentVariable("KICAD_TEST_CONTROL");
            string lease = Path.Combine(control, "lease");
            string request = Path.Combine(control, "request");
            string log = Environment.GetEnvironmentVariable("KICAD_TEST_LOG");
            if (args.Length == 3 && args[1] == "_update-control" && args[2] == "probe") {
                if (!File.Exists(lease)) return 1;
                Console.WriteLine(File.ReadAllText(lease)); return 0;
            }
            if (args.Length == 7 && args[1] == "_update-control" && args[2] == "request") {
                if (!File.Exists(lease) || File.ReadAllText(lease) != args[4] + " " + args[6]) return 1;
                File.AppendAllText(log, "requested" + Environment.NewLine);
                File.WriteAllText(request, "drain"); return 0;
            }
            if (args.Length == 2 && args[1] == "--help") {
                Console.WriteLine("--managed-edit"); return 0;
            }
            File.AppendAllText(Environment.GetEnvironmentVariable("KICAD_TEST_LOG"),
                "connected " + self + Environment.NewLine);
            if (Environment.GetEnvironmentVariable("KICAD_TEST_SCENARIO") == "live" &&
                Environment.GetEnvironmentVariable("KICAD_CLOUD_UPDATE_SLOT") == "a") {
                File.WriteAllText(lease, Environment.GetEnvironmentVariable("KICAD_CLOUD_UPDATE_GENERATION") + " a");
                System.Diagnostics.Stopwatch timer = System.Diagnostics.Stopwatch.StartNew();
                while (!File.Exists(request) && timer.Elapsed.TotalSeconds < 35) System.Threading.Thread.Sleep(50);
                bool requested = File.Exists(request);
                File.Delete(lease);
                if (!requested) return 99;
                File.AppendAllText(log, "drained" + Environment.NewLine);
            }
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
    $InstallerSource = $InstallerSource.Replace('Global\KiCadMcpProCloudPrepareV1-$sid', ($fixtureName + "-prepare"))
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
    # B is current; start an update-aware A fixture in an independent
    # PowerShell process holding the real test installer-session mutex.
    $env:KICAD_TEST_SCENARIO = "live"
    $job = Start-Job -ArgumentList $InstallerSource -ScriptBlock {
        param($source)
        & ([scriptblock]::Create($source))
    }
    $leasePath = Join-Path $env:KICAD_TEST_CONTROL "lease"
    $requestPath = Join-Path $env:KICAD_TEST_CONTROL "request"
    $wait = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $leasePath)) {
        if ($wait.Elapsed.TotalSeconds -ge 12 -or $job.State -in @("Failed", "Completed", "Stopped")) {
            Receive-Job $job
            throw "Live fixture did not publish a lease."
        }
        Start-Sleep -Milliseconds 100
    }
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a") { throw "A not selected" }
    $hash = (Get-FileHash -LiteralPath $a).Hash
    $env:KICAD_TEST_SCENARIO = "failure"
    $rejected = $false
    try { & $install } catch {
        if ($_.Exception.Message -notmatch "existing Connector was not asked to stop") { throw }
        $rejected = $true
    }
    if (-not $rejected -or (Test-Path -LiteralPath $requestPath) -or
        (Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a" -or
        (Get-FileHash -LiteralPath $a).Hash -ne $hash) { throw "Live failure affected A" }
    Write-Output "PASS: Windows failed live candidate keeps A"
    $env:KICAD_TEST_SCENARIO = "live"
    & $install
    if (-not (Wait-Job $job -Timeout 12)) { throw "Old launcher did not finish" }
    Receive-Job $job -ErrorAction Stop
    if ($job.State -ne "Completed") { throw "Old launcher failed" }
    Remove-Job $job
    $job = $null
    $tail = @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Select-Object -Last 3)
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        $tail.Count -ne 3 -or $tail[0] -ne "requested" -or $tail[1] -ne "drained" -or
        $tail[2] -ne ("connected " + $b)) { throw "Unexpected handoff order" }
    Write-Output "PASS: Windows graceful live A-to-B handoff"

} finally {
    $env:PATH = $oldPath
    $env:LOCALAPPDATA = $oldLocal
    $env:UV_INSTALL_DIR = $oldUv
    $env:KICAD_TEST_LOG = $oldLog
    if ($job) {
        # Unblock only the disposable fixture, then release its background job.
        $requestPath = Join-Path $env:KICAD_TEST_CONTROL "request"
        [IO.File]::WriteAllText($requestPath, "fixture cleanup")
        Wait-Job $job -Timeout 8 | Out-Null
        Remove-Job $job -Force
    }
    $env:KICAD_TEST_SCENARIO = $oldScenario
    $env:KICAD_TEST_CONTROL = $oldControl
    Remove-Item -LiteralPath $root -Recurse -Force
}
