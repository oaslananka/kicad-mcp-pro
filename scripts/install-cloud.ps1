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

    function Assert-LocalDirectory([string]$path) {
        $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if ($null -ne $item -and
            (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint))) {
            throw "Invalid local installation directory."
        }
    }

    function Test-Connector([string]$executable) {
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
        try {
            $item = Get-Item -LiteralPath $pendingPath -Force -ErrorAction Stop
        } catch [System.Management.Automation.ItemNotFoundException] {
            return $null
        }
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            $item.Length -ne 37) { throw "Invalid saved update. Existing releases unchanged." }
        $value = [IO.File]::ReadAllText($pendingPath, [Text.Encoding]::ASCII)
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
            Write-DurableMarker $temporary $slot
            if (Test-Path -LiteralPath $pointer -PathType Leaf) {
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
        $active = "legacy"
        $selection = Get-Item -LiteralPath $pointer -Force -ErrorAction SilentlyContinue
        if ($null -ne $selection) {
            if ($selection.PSIsContainer -or ($selection.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                $selection.Length -gt 3) {
                throw "Invalid release selection."
            }
            $active = [IO.File]::ReadAllText($pointer).TrimEnd([char]10, [char]13)
            if ($active -cnotin @("a", "b")) { throw "Invalid release selection." }
        }
        return $active
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
        } catch {}
        return $null
    }

    try {
        $env:UV_NO_CONFIG = "1"
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
