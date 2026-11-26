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
    $dedicatedTools = Join-Path $appRoot "uv-tools"
    $dedicatedBin = Join-Path $appRoot "bin"
    $originalNoConfig = $env:UV_NO_CONFIG
    $originalToolDir = $env:UV_TOOL_DIR
    $originalBinDir = $env:UV_TOOL_BIN_DIR
    $originalPath = $env:PATH

    try {
        $env:UV_NO_CONFIG = "1"
        $env:UV_TOOL_DIR = $dedicatedTools
        $env:UV_TOOL_BIN_DIR = $dedicatedBin
        # Keep uv's installer from asking the user to modify PATH manually.
        $env:PATH = "$dedicatedBin;$originalPath"

        $toolBin = & $uvPath tool dir --bin
        if ($LASTEXITCODE -ne 0 -or -not $toolBin) {
            throw "Could not locate the KiCad MCP Pro installation directory."
        }
        $cliPath = Join-Path ($toolBin | Select-Object -Last 1) "$package.exe"

        # Avoid uv's known Windows in-use upgrade failure, which can leave
        # site-packages deleted while the executable remains file-locked.
        if (Test-Path -LiteralPath $dedicatedTools) {
            try {
                $running = @(
                    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'kicad-mcp-pro.exe'" -ErrorAction Stop |
                        Where-Object {
                            $path = [string]$_.ExecutablePath
                            $path.StartsWith($dedicatedTools + [IO.Path]::DirectorySeparatorChar,
                                [StringComparison]::OrdinalIgnoreCase) -or
                            $path.Equals($cliPath, [StringComparison]::OrdinalIgnoreCase)
                        }
                )
            } catch {
                throw "Could not check whether the Connector is already running. No installation files were changed."
            }
            if ($running.Count -gt 0) {
                if (Test-Tool $cliPath) {
                    Write-Host "KiCad MCP Pro: This Connector is already running. No update or duplicate connection was started."
                    return
                }
                throw "KiCad MCP Pro is still running, and Windows has locked its files. Close the older Connector terminal, then run this same command again."
            }
        }

        $existingHealthy = Test-Tool $cliPath
        Write-Host "KiCad MCP Pro: Checking the installed version..."
        & $uvPath tool install --upgrade $package
        if ($LASTEXITCODE -ne 0) {
            if ($existingHealthy -and (Test-Tool $cliPath)) {
                Write-Warning "Update unavailable; starting the existing working version."
            } else {
                Write-Host "KiCad MCP Pro: Installation needs repair. Retrying once..."
                & $uvPath tool install --force --reinstall $package
                if ($LASTEXITCODE -ne 0) {
                    throw "Could not install or repair KiCad MCP Pro. Your projects and Cloud permissions were not modified."
                }
            }
        }

        if (-not (Test-Tool $cliPath)) {
            Write-Host "KiCad MCP Pro: Verifying the installation failed. Repairing once..."
            & $uvPath tool install --force --reinstall $package
            if ($LASTEXITCODE -ne 0 -or -not (Test-Tool $cliPath)) {
                throw "The application is still not healthy. Your KiCad projects and Cloud permissions were left unchanged."
            }
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
