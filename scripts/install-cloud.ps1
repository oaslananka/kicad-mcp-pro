# KiCad MCP Pro Cloud - repeatable Windows install/update/repair/start.
# Entrypoint: irm https://raw.githubusercontent.com/oaslananka/kicad-mcp-pro/main/scripts/install-cloud.ps1 | iex
# Never changes user KiCad projects, Cloud authorization, or MCP client settings.
& {
    $ErrorActionPreference = "Stop"
    $package = "kicad-mcp-pro"

    function Test-Tool([string]$executable) {
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            return $false
        }
        try {
            & $executable --version *> $null
            return ($LASTEXITCODE -eq 0)
        } catch {
            return $false
        }
    }

    # Serialize all installer work for this Windows user, including bootstrap.
    # Windows releases the mutex even after a crash; never trust a PID file.
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $prepareMutex = [System.Threading.Mutex]::new($false, "Global\KiCadMcpProCloudPrepareV1-$sid")
    $installerMutex = [System.Threading.Mutex]::new($false, "Global\KiCadMcpProCloudInstallerV2-$sid")
    $ownsPrepare = $false
    $ownsInstallerMutex = $false
    function Enter-InstallerMutex([System.Threading.Mutex]$mutex) {
        try { return $mutex.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { return $true }
    }
    try {
        $ownsPrepare = Enter-InstallerMutex $prepareMutex
        if (-not $ownsPrepare) {
            throw "Another setup is preparing an update. Existing installation unchanged."
        }
        $ownsInstallerMutex = Enter-InstallerMutex $installerMutex
    $installDir = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else {
        Join-Path $HOME ".local\bin"
    }
    $fallbackUv = Join-Path $installDir "uv.exe"
    $uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $uvPath = if ($null -ne $uv) { $uv.Source } else { $fallbackUv }

    if (-not (Test-Tool $uvPath)) {
        # Download exact official Astral release bytes, never execute downloaded scripts.
        $release = "0.13.9"
        $artifacts = @{
            X64 = @("uv-x86_64-pc-windows-msvc.zip", "edd61f7f5728a56cc62455386661860bdfc7bab65872f39b0c25bdcc1d8e1beb")
            Arm64 = @("uv-aarch64-pc-windows-msvc.zip", "72eed595983a4d7d22d79f21065b0f4479cc7e5c7a89104bb410c8f47559a878")
            X86 = @("uv-i686-pc-windows-msvc.zip", "eb4bd7285a512ebc4122f65a21b72e3f7072610d62164f43ca6aca280c39f6fd")
        }
        $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
        if (-not $artifacts.ContainsKey($architecture)) {
            throw "This Windows processor is not supported: $architecture."
        }
        $artifact = $artifacts[$architecture]
        $url = "https://github.com/astral-sh/uv/releases/download/$release/$($artifact[0])"
        $temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("kicad-cloud-uv-" + [guid]::NewGuid().ToString("N"))
        try {
            New-Item -ItemType Directory -Path $temporary -Force | Out-Null
            $archive = Join-Path $temporary "uv.zip"
            $unpacked = Join-Path $temporary "unpacked"
            Write-Host "KiCad MCP Pro: Preparing the installer..."
            Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -TimeoutSec 90
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $artifact[1]) {
                throw "The installer download failed integrity verification. Nothing was installed."
            }
            Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
            $uvBinary = Join-Path $unpacked "uv.exe"
            $uvxBinary = Join-Path $unpacked "uvx.exe"
            if (-not (Test-Path -LiteralPath $uvBinary -PathType Leaf) -or
                -not (Test-Path -LiteralPath $uvxBinary -PathType Leaf)) {
                throw "The verified installer archive is incomplete."
            }
            New-Item -ItemType Directory -Path $installDir -Force | Out-Null
            Copy-Item -LiteralPath $uvBinary -Destination $fallbackUv -Force
            Copy-Item -LiteralPath $uvxBinary -Destination (Join-Path $installDir "uvx.exe") -Force
        } finally {
            if (Test-Path -LiteralPath $temporary) {
                Remove-Item -LiteralPath $temporary -Recurse -Force
            }
        }
        $uvPath = $fallbackUv
        if (-not (Test-Tool $uvPath)) {
            throw "The installer could not start. Check Windows security controls and retry."
        }
    }

    # Keep this Cloud launcher separate from the user's pip, pipx and uv tools.
    # Windows cannot safely replace an environment while its Python is running.
    $appRoot = Join-Path $env:LOCALAPPDATA "KiCadMCPPro"
    $originalNoConfig = $env:UV_NO_CONFIG
    $originalToolDir = $env:UV_TOOL_DIR
    $originalBinDir = $env:UV_TOOL_BIN_DIR
    $originalPath = $env:PATH
    $originalGeneration = $env:KICAD_CLOUD_UPDATE_GENERATION
    $originalSlot = $env:KICAD_CLOUD_UPDATE_SLOT
    $releases = Join-Path $appRoot "releases"
    $pointer = Join-Path $appRoot "active-release"
    $pendingPath = Join-Path $appRoot "pending-release"

    # Standalone installer: no installed Python is required for these checks.
    if (-not ("KiCadCloudInstallerMarkerV1" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

public static class KiCadCloudInstallerMarkerV1 {
    [StructLayout(LayoutKind.Sequential)]
    private struct Info {
        public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh,
            WriteLow, WriteHigh, Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true, ExactSpelling=true)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint share,
        IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out Info info);
    [DllImport("advapi32.dll")]
    private static extern uint GetSecurityInfo(SafeFileHandle file, int type, uint flags,
        out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")]
    private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr pointer);

    private static bool Trusted(SecurityIdentifier identity, string sid) {
        if (identity == null) return false;
        string value = identity.Value;
        return value == sid || value == "S-1-5-18" || value == "S-1-5-32-544";
    }

    private static void CheckAcl(SafeFileHandle file, string sid) {
        IntPtr owner, group, dacl, sacl, descriptor;
        uint result = GetSecurityInfo(file, 1, 5, out owner, out group, out dacl,
            out sacl, out descriptor);
        try {
            if (result != 0 || descriptor == IntPtr.Zero)
                throw new IOException("Cannot verify installation security.");
            uint length = GetSecurityDescriptorLength(descriptor);
            if (length < 20 || length > 131072)
                throw new IOException("Invalid installation security descriptor.");
            byte[] bytes = new byte[(int)length];
            Marshal.Copy(descriptor, bytes, 0, bytes.Length);
            RawSecurityDescriptor sd = new RawSecurityDescriptor(bytes, 0);
            if (!Trusted(sd.Owner, sid) || sd.DiscretionaryAcl == null)
                throw new IOException("Unsafe installation ownership or permissions.");
            foreach (GenericAce entry in sd.DiscretionaryAcl) {
                if ((entry.AceFlags & AceFlags.InheritOnly) != 0) continue;
                CommonAce ace = entry as CommonAce;
                if (ace == null || ace.IsCallback)
                    throw new IOException("Unsupported installation access rule.");
                if (ace.AceQualifier == AceQualifier.AccessDenied) continue;
                if (ace.AceQualifier != AceQualifier.AccessAllowed ||
                    (!Trusted(ace.SecurityIdentifier, sid) &&
                    (unchecked((uint)ace.AccessMask) & ~0xA01200A9u) != 0))
                    throw new IOException("Unsafe installation ownership or permissions.");
            }
        } finally {
            if (descriptor != IntPtr.Zero) LocalFree(descriptor);
        }
    }

    private static SafeFileHandle OpenChecked(string path, string sid, bool directory,
        bool missingOk, out Info info) {
        info = new Info();
        // READ_CONTROL and attributes; marker reads also deny write/delete sharing.
        SafeFileHandle file = CreateFileW(path, directory ? 0x00020080u : 0x80020080u,
            directory ? 3u : 1u, IntPtr.Zero, 3, 0x02200000u, IntPtr.Zero);
        if (file.IsInvalid) {
            int error = Marshal.GetLastWin32Error();
            file.Dispose();
            if (missingOk && (error == 2 || error == 3)) return null;
            throw new IOException("Cannot safely open local installation entry (" + error + ").");
        }
        try {
            if (!GetFileInformationByHandle(file, out info) ||
                (info.Attributes & 0x1400u) != 0 ||
                ((info.Attributes & 0x10u) != 0) != directory ||
                (!directory && info.Links != 1))
                throw new IOException("Unsafe local installation entry.");
            CheckAcl(file, sid);
            return file;
        } catch {
            file.Dispose();
            throw;
        }
    }

    public static void CheckDirectory(string path, string sid, bool missingOk) {
        Info info;
        using (SafeFileHandle file = OpenChecked(path, sid, true, missingOk, out info)) {}
    }

    public static string ReadMarker(string path, string sid, int limit) {
        Info info;
        using (SafeFileHandle file = OpenChecked(path, sid, false, true, out info)) {
            if (file == null) return null;
            if (info.SizeHigh != 0 || info.SizeLow == 0 || info.SizeLow > (uint)limit)
                throw new IOException("Invalid local release marker size.");
            using (FileStream stream = new FileStream(file, FileAccess.Read)) {
                byte[] bytes = new byte[(int)info.SizeLow];
                int offset = 0;
                while (offset < bytes.Length) {
                    int count = stream.Read(bytes, offset, bytes.Length - offset);
                    if (count == 0) throw new IOException("Local release marker changed.");
                    offset += count;
                }
                if (stream.ReadByte() != -1) throw new IOException("Local release marker changed.");
                return Encoding.ASCII.GetString(bytes);
            }
        }
    }
}
'@
    }

    function Assert-LocalDirectory([string]$path) {
        [KiCadCloudInstallerMarkerV1]::CheckDirectory($path, $sid, $true)
    }

    function Read-LocalMarker([string]$path, [int]$limit) {
        return [KiCadCloudInstallerMarkerV1]::ReadMarker($path, $sid, $limit)
    }

    function Test-Connector([string]$executable) {
        $bin = Split-Path -Parent $executable
        Assert-LocalDirectory (Split-Path -Parent $bin)
        Assert-LocalDirectory $bin
        if (-not (Test-Tool $executable)) { return $false }
        try {
            & $executable cloud --help *> $null
            return ($LASTEXITCODE -eq 0)
        } catch {
            return $false
        }
    }

    function Select-ReleaseSlot([string]$slot) {
        $slotRoot = if ($slot -eq "legacy") { $appRoot } else { Join-Path $releases $slot }
        Assert-LocalDirectory $slotRoot
        $dedicatedTools = Join-Path $slotRoot "uv-tools"
        $dedicatedBin = Join-Path $slotRoot "bin"
        Assert-LocalDirectory $dedicatedTools
        Assert-LocalDirectory $dedicatedBin
        $env:UV_TOOL_DIR = $dedicatedTools
        $env:UV_TOOL_BIN_DIR = $dedicatedBin
        $env:PATH = "$dedicatedBin;$originalPath"
        $toolBin = & $uvPath tool dir --bin
        if ($LASTEXITCODE -ne 0 -or -not $toolBin -or
            -not ([string]($toolBin | Select-Object -Last 1)).Equals($dedicatedBin, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Could not verify the KiCad MCP Pro installation directory."
        }
        return (Join-Path $dedicatedBin "$package.exe")
    }

    function Write-DurableMarker([string]$path, [string]$value) {
        $bytes = [Text.Encoding]::ASCII.GetBytes($value + "`n")
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        } finally { $stream.Dispose() }
    }

    function Read-PendingRelease {
        $value = Read-LocalMarker $pendingPath 37
        if ($null -eq $value) { return $null }
        if ($value -cmatch '\A([ab]) ([ab]) ([0-9a-f]{32})\n\z') {
            if ($Matches[1] -cne $Matches[2]) {
                return @{ Old = $Matches[1]; Candidate = $Matches[2]; Generation = $Matches[3]; Raw = $value }
            }
        }
        throw "Invalid saved update. Existing releases unchanged."
    }

    function Save-PendingRelease([string]$old, [string]$next, [string]$generation) {
        if ($null -ne (Read-PendingRelease)) { throw "A saved update already exists." }
        $temporary = Join-Path $appRoot (".pending-release-" + [guid]::NewGuid().ToString("N"))
        try {
            Assert-LocalDirectory $appRoot
            Write-DurableMarker $temporary "$old $next $generation"
            [IO.File]::Move($temporary, $pendingPath)
        } finally {
            if (Test-Path -LiteralPath $temporary -PathType Leaf) {
                Remove-Item -LiteralPath $temporary -Force
            }
        }
    }

    function Publish-Release([string]$slot) {
        # uv environments are not relocatable. Publish only a small selector,
        # leaving the old environment and the prepared candidate in place.
        $temporary = Join-Path $appRoot (".active-release-" + [guid]::NewGuid().ToString("N"))
        $backup = $temporary + ".previous"
        try {
            Assert-LocalDirectory $appRoot
            Write-DurableMarker $temporary $slot
            if ((Read-ActiveRelease) -cne "legacy") {
                [IO.File]::Replace($temporary, $pointer, $backup)
            } else {
                [IO.File]::Move($temporary, $pointer)
            }
        } finally {
            foreach ($file in @($temporary, $backup)) {
                if (Test-Path -LiteralPath $file -PathType Leaf) {
                    Remove-Item -LiteralPath $file -Force
                }
            }
        }
    }

    function Read-ActiveRelease {
        $value = Read-LocalMarker $pointer 3
        if ($null -eq $value) { return "legacy" }
        if ($value -cmatch '\A([ab])(?:\r?\n)?\z') { return $Matches[1] }
        throw "Invalid release selection."
    }

    function Get-InstallProcesses {
        if (-not (Test-Path -LiteralPath $appRoot)) { return }
        try {
            Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'kicad-mcp-pro.exe'" -ErrorAction Stop |
                Where-Object {
                    ([string]$_.ExecutablePath).StartsWith($appRoot + [IO.Path]::DirectorySeparatorChar,
                        [StringComparison]::OrdinalIgnoreCase)
                }
        } catch {
            throw "Could not verify running Connector processes. Existing installation unchanged."
        }
    }

    function Get-UpdateLease([string]$executable, [string]$slot) {
        if ($slot -cnotin @("a", "b")) { return $null }
        try {
            $result = (& $executable cloud _update-control probe 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $result -cmatch ('^[0-9a-f]{32} ' + $slot + '$')) {
                return $result
            }
        } catch {
            # An unverifiable lease is not permission to replace a live installation.
            return $null
        }
        return $null
    }

    try {
        $env:UV_NO_CONFIG = "1"
        [KiCadCloudInstallerMarkerV1]::CheckDirectory($env:LOCALAPPDATA, $sid, $false)
        Assert-LocalDirectory $appRoot
        Assert-LocalDirectory $releases
        Assert-LocalDirectory (Join-Path $releases "a")
        Assert-LocalDirectory (Join-Path $releases "b")
        $active = Read-ActiveRelease
        $pending = Read-PendingRelease
        if ($null -ne $pending) {
            if ($active -cnotin @($pending.Old, $pending.Candidate) -or
                ($active -ceq $pending.Candidate -and -not $ownsInstallerMutex)) {
                throw "Saved update conflicts with the active session. Existing releases unchanged."
            }
            $active = $pending.Old
        }
        $candidate = if ($active -eq "a") { "b" } else { "a" }
        $cliPath = Select-ReleaseSlot $active

        $activeCli = $cliPath
        $running = @(Get-InstallProcesses)
        $lease = $null
        if (-not $ownsInstallerMutex) {
            $lease = Get-UpdateLease $activeCli $active
            if (-not $lease -and $null -eq $pending) {
                throw "Another setup or Connector is running. Existing installation unchanged."
            }
            if ($null -ne $pending -and $lease -and $lease -cne ($pending.Generation + " " + $active)) {
                throw "A different Connector session is running. Saved update preserved."
            }
            $activeRoot = (Join-Path $releases $active) + [IO.Path]::DirectorySeparatorChar
            if (@($running | Where-Object {
                -not ([string]$_.ExecutablePath).StartsWith($activeRoot, [StringComparison]::OrdinalIgnoreCase)
            }).Count -gt 0) {
                throw "Another installation is running. Existing installation unchanged."
            }
        } elseif ($running.Count -gt 0) {
            throw "A manually started or older Connector is running. Existing installation unchanged."
        }

        $recovery = $null
        if ($null -eq $pending -and $ownsInstallerMutex -and $active -ne "legacy" -and -not (Test-Connector $activeCli)) {
            $previousCli = Select-ReleaseSlot $candidate
            if (Test-Connector $previousCli) {
                $recovery = $candidate
            } else {
                $legacyCli = Select-ReleaseSlot "legacy"
                if (Test-Connector $legacyCli) { $recovery = "legacy" }
            }
        }
        if ($null -ne $pending) {
            Write-Host "KiCad MCP Pro: Resuming the prepared update without reinstalling..."
            $candidate = $pending.Candidate
            $cliPath = Select-ReleaseSlot $candidate
            if (-not $ownsInstallerMutex -and -not (Test-Connector $cliPath)) {
                throw "Saved candidate is no longer healthy. No new stop request was sent."
            }
            # The final health check under session ownership decides whether
            # to promote the candidate or restore the previous release.
            $installed = $true
        } elseif ($null -ne $recovery) {
            # Never overwrite the remaining working environment while
            # attempting to repair a broken selected release.
            $cliPath = Select-ReleaseSlot $recovery
            if (-not (Test-Connector $cliPath)) { throw "Previous installation is no longer healthy." }
            if ($recovery -eq "legacy") {
                Remove-Item -LiteralPath $pointer -Force
            } else {
                Publish-Release $recovery
            }
            $selected = $recovery
            Write-Warning "Restored the previous working installation without upgrading it."
        } else {
            $cliPath = Select-ReleaseSlot $active
            $existingHealthy = Test-Connector $cliPath
            $cliPath = Select-ReleaseSlot $candidate
            Write-Host "KiCad MCP Pro: Preparing a separate update..."
            & $uvPath tool install --upgrade $package
            $installed = ($LASTEXITCODE -eq 0) -and (Test-Connector $cliPath)
            if (-not $installed -and -not $existingHealthy -and $ownsInstallerMutex) {
                Write-Host "KiCad MCP Pro: Installation needs repair. Retrying once..."
                & $uvPath tool install --force --reinstall $package
                $installed = ($LASTEXITCODE -eq 0) -and (Test-Connector $cliPath)
            }
        }
        if ($null -eq $recovery) {
            if ($installed) {
                if (-not $ownsInstallerMutex) {
                    $ownsInstallerMutex = Enter-InstallerMutex $installerMutex
                    if ($null -eq $pending) {
                        if ((Read-ActiveRelease) -cne $active) {
                            throw "The active release changed. Retry the same setup."
                        }
                        if (-not $ownsInstallerMutex -and (Get-UpdateLease $activeCli $active) -cne $lease) {
                            throw "The running session changed. Retry the same setup."
                        }
                        $generation = $lease.Split(" ")[0]
                        Save-PendingRelease $active $candidate $generation
                        $pending = Read-PendingRelease
                        if ($null -eq $pending) { throw "Saved update could not be verified." }
                    }
                    if (-not $ownsInstallerMutex) {
                        $generation = $pending.Generation
                        $expected = $generation + " " + $active
                        $current = Get-UpdateLease $activeCli $active
                        if ($current -and $current -cne $expected) {
                            throw "A different Connector session is running. Saved update preserved."
                        }
                        if ($current -ceq $expected) {
                            & $activeCli cloud _update-control request --generation $generation --slot $active *> $null
                            if ($LASTEXITCODE -ne 0) {
                                $ownsInstallerMutex = Enter-InstallerMutex $installerMutex
                                if (-not $ownsInstallerMutex -and (Get-UpdateLease $activeCli $active)) {
                                    throw "Connector did not accept the saved update request."
                                }
                            }
                        }
                        Write-Host "KiCad MCP Pro: Finishing the current Cloud operation before updating..."
                        $deadline = [Diagnostics.Stopwatch]::StartNew()
                        while (-not $ownsInstallerMutex) {
                            if ($deadline.Elapsed.TotalSeconds -ge 300) {
                                throw "Previous Connector is still finishing. Retry setup; no process was killed."
                            }
                            Start-Sleep -Milliseconds 200
                            $ownsInstallerMutex = Enter-InstallerMutex $installerMutex
                        }
                    }
                }
                $currentSelection = Read-ActiveRelease
                if ($currentSelection -cne $active -and
                    ($null -eq $pending -or $currentSelection -cne $candidate)) {
                    throw "The active release changed. Existing releases unchanged."
                }
                if (@(Get-InstallProcesses).Count -gt 0) {
                    throw "A Connector process is still running. Existing release unchanged."
                }
                if ($null -ne $pending) {
                    $verifiedPending = Read-PendingRelease
                    if ($null -eq $verifiedPending -or $verifiedPending.Raw -cne $pending.Raw) {
                        throw "Saved update changed. Existing releases preserved."
                    }
                }
                # Recheck the prepared environment once the old launcher has
                # stopped, before making it the active installation.
                if (Test-Connector $cliPath) {
                    Publish-Release $candidate
                    $selected = $candidate
                } elseif (Test-Connector $activeCli) {
                    Write-Warning "Candidate failed its final startup check; using the previous version."
                    $selected = $active
                    $cliPath = Select-ReleaseSlot $active
                    if ($null -ne $pending) { Publish-Release $active }
                } else {
                    throw "Neither installation passed the final startup check. Existing files were preserved."
                }
                if ($null -ne $pending) {
                    $verifiedPending = Read-PendingRelease
                    if ($null -eq $verifiedPending -or $verifiedPending.Raw -cne $pending.Raw) {
                        throw "Saved update changed. Existing releases preserved."
                    }
                    Remove-Item -LiteralPath $pendingPath
                }
            } elseif (-not $ownsInstallerMutex) {
                throw "Update unavailable; existing Connector was not asked to stop."
            } elseif ($existingHealthy) {
                Write-Warning "Update unavailable; starting the existing working version."
                $selected = $active
                $cliPath = Select-ReleaseSlot $active
                if (-not (Test-Connector $cliPath)) {
                    throw "Existing installation is no longer healthy."
                }
            } else {
                throw "Could not install or repair KiCad MCP Pro. Existing files and Cloud permissions were preserved."
            }
        }

        $env:KICAD_CLOUD_UPDATE_GENERATION = [guid]::NewGuid().ToString("N")
        $env:KICAD_CLOUD_UPDATE_SLOT = $selected
        $prepareMutex.ReleaseMutex()
        $ownsPrepare = $false
        Write-Host "KiCad MCP Pro: Ready. Opening Cloud Connector..."
        # Main may be ahead of the published wheel. Do not pass an unsupported option.
        $cloudHelp = (& $cliPath cloud --help 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) {
            throw "Selected Connector failed its launch check. Retry the same setup; no Cloud session was started."
        }
        if ($cloudHelp -match '(?<![\w-])--managed-edit(?![\w-])') {
            Write-Host "Cloud Edit grants control editing in this owner-started session."
            & $cliPath cloud --managed-edit
        } else {
            Write-Warning "The installed Connector does not yet support managed editing. Starting its existing connection mode."
            & $cliPath cloud
        }
        if ($LASTEXITCODE -ne 0) {
            throw "The Cloud Connector could not start (exit code $LASTEXITCODE). Review the on-screen connection guidance."
        }
    } finally {
        $env:UV_TOOL_DIR = $originalToolDir
        $env:UV_TOOL_BIN_DIR = $originalBinDir
        $env:PATH = $originalPath
        $env:UV_NO_CONFIG = $originalNoConfig
        $env:KICAD_CLOUD_UPDATE_GENERATION = $originalGeneration
        $env:KICAD_CLOUD_UPDATE_SLOT = $originalSlot
    }
    } finally {
        try {
            if ($ownsInstallerMutex) { $installerMutex.ReleaseMutex() }
        } finally {
            $installerMutex.Dispose()
            try {
                if ($ownsPrepare) { $prepareMutex.ReleaseMutex() }
            } finally {
                $prepareMutex.Dispose()
            }
        }
    }
}
