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
    # Change only the fixture DACL, without requiring SeSecurityPrivilege
    # to read or write its audit settings.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class KiCadFixtureAcl {
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true, ExactSpelling=true)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(
        string sddl, uint revision, out IntPtr descriptor, IntPtr size);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true, ExactSpelling=true)]
    private static extern bool SetFileSecurityW(string path, uint information, IntPtr descriptor);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr pointer);
    public static void SetDacl(string path, string sddl) {
        IntPtr descriptor;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, out descriptor, IntPtr.Zero))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try {
            if (!SetFileSecurityW(path, 0x80000004u, descriptor))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        } finally { LocalFree(descriptor); }
    }
}
'@
    function Set-FixturePermissions([string]$path, [string]$extra = "") {
        $userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $inheritance = if ((Get-Item -LiteralPath $path).PSIsContainer) { "OICI" } else { "" }
        $descriptor = "D:P(A;$inheritance;FA;;;$userSid)(A;$inheritance;FA;;;SY)(A;$inheritance;FA;;;BA)" + $extra
        [KiCadFixtureAcl]::SetDacl($path, $descriptor)
    }
    $env:LOCALAPPDATA = Join-Path $root "local"
    $env:UV_INSTALL_DIR = Join-Path $root "uv-bin"
    New-Item -ItemType Directory -Path $env:LOCALAPPDATA,$env:UV_INSTALL_DIR | Out-Null
    Set-FixturePermissions $env:LOCALAPPDATA
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
                if (scenario == "offline") return 1;
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
                string journal = Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA"),
                    "KiCadMCPPro", "pending-release");
                string next = args[6] == "a" ? "b" : "a";
                if (!File.Exists(journal) || File.ReadAllText(journal) != args[6] + " " + next + " " + args[4] + "\n") return 95;
                File.AppendAllText(log, "requested" + Environment.NewLine);
                File.WriteAllText(request, "drain"); return 0;
            }
            if (args.Length == 2 && args[1] == "--help") {
                if (Environment.GetEnvironmentVariable("KICAD_TEST_SCENARIO") == "late-unhealthy" &&
                    self.IndexOf("\\releases\\a\\", StringComparison.OrdinalIgnoreCase) >= 0) {
                    string check = Path.Combine(control, "late-check");
                    if (File.Exists(check)) return 1;
                    File.WriteAllText(check, "checked");
                }
                Console.WriteLine("--managed-edit"); return 0;
            }
            File.AppendAllText(Environment.GetEnvironmentVariable("KICAD_TEST_LOG"),
                "connected " + self + Environment.NewLine);
            if (Environment.GetEnvironmentVariable("KICAD_TEST_SCENARIO") == "policy-rejection") return 3;
            if (Environment.GetEnvironmentVariable("KICAD_TEST_SCENARIO") == "live" &&
                Environment.GetEnvironmentVariable("KICAD_CLOUD_UPDATE_SLOT") == "a") {
                File.WriteAllText(lease, Environment.GetEnvironmentVariable("KICAD_CLOUD_UPDATE_GENERATION") + " a");
                System.Diagnostics.Stopwatch timer = System.Diagnostics.Stopwatch.StartNew();
                while (!File.Exists(request) && timer.Elapsed.TotalSeconds < 90) System.Threading.Thread.Sleep(50);
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
    $pendingPath = Join-Path $app "pending-release"
    $count = @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count
    $env:KICAD_TEST_SCENARIO = "offline"
    [IO.File]::WriteAllText($pendingPath, ("a b " + [guid]::NewGuid().ToString("N") + [char]10), [Text.Encoding]::ASCII)
    $rejected = $false
    try { & $install } catch {
        if ($_.Exception.Message -notmatch "A different Connector session is running") { throw }
        $rejected = $true
    }
    if (-not $rejected -or (Test-Path -LiteralPath $requestPath)) { throw "Stale generation drained live A" }
    $currentGeneration = ([IO.File]::ReadAllText($leasePath)).Split(" ")[0]
    [IO.File]::WriteAllText($pendingPath, ("a b " + $currentGeneration + [char]10), [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($b, "broken saved candidate")
    $rejected = $false
    try { & $install } catch {
        if ($_.Exception.Message -notmatch "Saved candidate is no longer healthy") { throw }
        $rejected = $true
    }
    if (-not $rejected -or (Test-Path -LiteralPath $requestPath) -or
        (Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a" -or
        (Get-FileHash -LiteralPath $a).Hash -ne $hash -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Unhealthy saved candidate affected live A"
    }
    Remove-Item -LiteralPath $pendingPath
    Write-Output "PASS: Windows stale generation and unhealthy saved candidate never drain live Connector"
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
        (Test-Path -LiteralPath $pendingPath) -or
        $tail.Count -ne 3 -or $tail[0] -ne "requested" -or $tail[1] -ne "drained" -or
        $tail[2] -ne ("connected " + $b)) { throw "Unexpected handoff order" }
    Write-Output "PASS: Windows graceful live A-to-B handoff"
    # The final startup check must run before selecting the new slot.
    $hash = (Get-FileHash -LiteralPath $b).Hash
    $env:KICAD_TEST_SCENARIO = "late-unhealthy"
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        (Get-FileHash -LiteralPath $b).Hash -ne $hash -or
        (Get-Content -LiteralPath $env:KICAD_TEST_LOG | Select-Object -Last 1) -ne ("connected " + $b)) {
        throw "Late startup failure did not preserve B"
    }
    Write-Output "PASS: Windows final startup check preserves previous release"
    $env:KICAD_TEST_SCENARIO = "success"
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a") { throw "A not selected" }
    [IO.File]::WriteAllText($a, "corrupt selected fixture")
    $count = @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count
    $env:KICAD_TEST_SCENARIO = "failure"
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        (Get-FileHash -LiteralPath $b).Hash -ne $hash -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Recovery modified the last working installation"
    }
    Write-Output "PASS: Windows corrupt selected release restores backup without upgrading"
    $env:KICAD_TEST_SCENARIO = "policy-rejection"
    $denied = $false
    try { & $install } catch {
        if ($_.Exception.Message -notmatch "exit code 3") { throw }
        $denied = $true
    }
    if (-not $denied -or (Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a") {
        throw "Cloud policy rejection was treated as a package failure"
    }
    Write-Output "PASS: Windows policy failure does not downgrade"

    # A prepared, durable intent is left if the updater exits before
    # publishing its selector. Both installed executables are healthy.
    $pendingPath = Join-Path $app "pending-release"
    $generation = [guid]::NewGuid().ToString("N")
    $journal = "a b $generation" + [char]10
    $aHash = (Get-FileHash -LiteralPath $a).Hash
    $bHash = (Get-FileHash -LiteralPath $b).Hash
    $count = @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count
    [IO.File]::WriteAllText($pendingPath, $journal, [Text.Encoding]::ASCII)
    $env:KICAD_TEST_SCENARIO = "offline"
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        (Test-Path -LiteralPath $pendingPath) -or
        (Get-Content -LiteralPath $env:KICAD_TEST_LOG | Select-Object -Last 1) -ne ("connected " + $b) -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Interrupted update did not recover the prepared candidate offline"
    }
    Write-Output "PASS: Windows interrupted handoff resumes offline without reinstall"
    # Crash immediately after publishing B, before removing the journal.
    [IO.File]::WriteAllText($pendingPath, $journal, [Text.Encoding]::ASCII)
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        (Test-Path -LiteralPath $pendingPath) -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Interrupted selector publication was not idempotent"
    }
    Write-Output "PASS: Windows interrupted selector publication reconciles"
    [IO.File]::WriteAllText($pendingPath, ("b b " + $generation + [char]10), [Text.Encoding]::ASCII)
    $rejected = $false
    try { & $install } catch {
        if ($_.Exception.Message -notmatch "Invalid saved update") { throw }
        $rejected = $true
    }
    if (-not $rejected -or (Get-FileHash -LiteralPath $a).Hash -ne $aHash -or
        (Get-FileHash -LiteralPath $b).Hash -ne $bHash -or
        (Get-Content -LiteralPath $pointer -Raw).Trim() -cne "b" -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Malformed journal changed installed releases"
    }
    Remove-Item -LiteralPath $pendingPath
    Write-Output "PASS: Windows malformed update journal fails closed"
    # Prepare B from A but discover corruption before promotion.
    [IO.File]::WriteAllText($pointer, ("a" + [char]10), [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($pendingPath, $journal, [Text.Encoding]::ASCII)
    [IO.File]::WriteAllText($b, "broken candidate")
    & $install
    if ((Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a" -or
        (Test-Path -LiteralPath $pendingPath) -or
        (Get-FileHash -LiteralPath $a).Hash -ne $aHash -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Unhealthy saved candidate did not preserve A"
    }
    Write-Output "PASS: Windows unhealthy saved candidate restores previous release"

    # Rejections happen before the package fixture is invoked.
    foreach ($marker in @($pointer, $pendingPath)) {
        if ($marker -ceq $pendingPath) {
            [IO.File]::WriteAllText($pendingPath, $journal, [Text.Encoding]::ASCII)
        }
        $contents = [IO.File]::ReadAllText($marker)
        $other = Join-Path $app ("marker-link-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType HardLink -Path $other -Target $marker | Out-Null
        $rejected = $false
        try { & $install } catch {
            if ($_.Exception.Message -notmatch "Unsafe local installation entry") { throw }
            $rejected = $true
        }
        if (-not $rejected -or [IO.File]::ReadAllText($marker) -cne $contents) {
            throw "Hardlinked marker was accepted or changed"
        }
        Remove-Item -LiteralPath $other
        Set-FixturePermissions $marker "(A;;FW;;;WD)"
        $rejected = $false
        try { & $install } catch {
            if ($_.Exception.Message -notmatch "Unsafe installation ownership or permissions") { throw }
            $rejected = $true
        }
        if (-not $rejected -or [IO.File]::ReadAllText($marker) -cne $contents) {
            throw "Shared-write marker was accepted or changed"
        }
        Set-FixturePermissions $marker
        if ($marker -ceq $pendingPath) { Remove-Item -LiteralPath $marker }
    }
    Set-FixturePermissions $app "(A;;FW;;;WD)"
    $rejected = $false
    try { & $install } catch {
        if ($_.Exception.Message -notmatch "Unsafe installation ownership or permissions") { throw }
        $rejected = $true
    }
    Set-FixturePermissions $app
    if (-not $rejected -or (Get-Content -LiteralPath $pointer -Raw).Trim() -cne "a" -or
        @(Get-Content -LiteralPath $env:KICAD_TEST_LOG | Where-Object { $_ -like "install *" }).Count -ne $count) {
        throw "Unsafe marker or directory triggered installation"
    }
    Write-Output "PASS: Windows hardlinked/shared-write markers and directories fail closed"




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
