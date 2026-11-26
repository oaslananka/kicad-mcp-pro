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
    $installerMutex = [System.Threading.Mutex]::new($false, "Global\KiCadMcpProCloudInstallerV2-$sid")
    $ownsInstallerMutex = $false
    try {
        try {
            $ownsInstallerMutex = $installerMutex.WaitOne(0)
        } catch [System.Threading.AbandonedMutexException] {
            $ownsInstallerMutex = $true
        }
        if (-not $ownsInstallerMutex) {
            Write-Host "KiCad MCP Pro: Another setup or Connector is running. No installation files were changed."
            return
        }
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
    $releases = Join-Path $appRoot "releases"
    $pointer = Join-Path $appRoot "active-release"

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

    function Publish-Release([string]$slot) {
        # uv environments are not relocatable. Publish only a small selector,
        # leaving the old environment and the prepared candidate in place.
        $temporary = Join-Path $appRoot (".active-release-" + [guid]::NewGuid().ToString("N"))
        $backup = $temporary + ".previous"
        try {
            [IO.File]::WriteAllText($temporary, $slot + "`n", [Text.Encoding]::ASCII)
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

    try {
        $env:UV_NO_CONFIG = "1"
        Assert-LocalDirectory $appRoot
        Assert-LocalDirectory $releases
        Assert-LocalDirectory (Join-Path $releases "a")
        Assert-LocalDirectory (Join-Path $releases "b")
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
        $candidate = if ($active -eq "a") { "b" } else { "a" }
        $cliPath = Select-ReleaseSlot $active

        # Detect older/manual processes in any dedicated installation slot.
        # Never modify a potentially running slot, including the inactive one.
        if (Test-Path -LiteralPath $appRoot) {
            try {
                $running = @(
                    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe' OR Name = 'kicad-mcp-pro.exe'" -ErrorAction Stop |
                        Where-Object {
                            $path = [string]$_.ExecutablePath
                            $path.StartsWith($appRoot + [IO.Path]::DirectorySeparatorChar,
                                [StringComparison]::OrdinalIgnoreCase)
                        }
                )
            } catch {
                throw "Could not check whether the Connector is already running. No installation files were changed."
            }
            if ($running.Count -gt 0) {
                Write-Host "KiCad MCP Pro: This Connector is already running. No update or duplicate connection was started."
                return
            }
        }

        $existingHealthy = Test-Connector $cliPath
        $cliPath = Select-ReleaseSlot $candidate
        Write-Host "KiCad MCP Pro: Preparing a separate update..."
        & $uvPath tool install --upgrade $package
        $installed = ($LASTEXITCODE -eq 0) -and (Test-Connector $cliPath)
        if (-not $installed -and -not $existingHealthy) {
            Write-Host "KiCad MCP Pro: Installation needs repair. Retrying once..."
            & $uvPath tool install --force --reinstall $package
            $installed = ($LASTEXITCODE -eq 0) -and (Test-Connector $cliPath)
        }
        if ($installed) {
            Publish-Release $candidate
        } elseif ($existingHealthy) {
            Write-Warning "Update unavailable; starting the existing working version."
            $cliPath = Select-ReleaseSlot $active
            if (-not (Test-Connector $cliPath)) {
                throw "Existing installation is no longer healthy."
            }
        } else {
            throw "Could not install or repair KiCad MCP Pro. Existing files and Cloud permissions were preserved."
        }

        Write-Host "KiCad MCP Pro: Ready. Opening Cloud Connector..."
        # Main may be ahead of the published wheel. Do not pass an unsupported option.
        $cloudHelp = (& $cliPath cloud --help 2>&1 | Out-String)
        if ($LASTEXITCODE -eq 0 -and $cloudHelp -match '(?<![\w-])--managed-edit(?![\w-])') {
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
    }
    } finally {
        try {
            if ($ownsInstallerMutex) { $installerMutex.ReleaseMutex() }
        } finally {
            $installerMutex.Dispose()
        }
    }
}
