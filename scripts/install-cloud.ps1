# KiCad MCP Pro Cloud - one-command Windows user bootstrap.
# Entrypoint: irm https://raw.githubusercontent.com/oaslananka/kicad-mcp-pro/main/scripts/install-cloud.ps1 | iex
# When uvx is absent, install a checksum-pinned official Astral release archive.
& {
    $ErrorActionPreference = "Stop"
    $uvx = Get-Command uvx -ErrorAction SilentlyContinue
    if ($null -eq $uvx) {
        $installDir = if ($env:UV_INSTALL_DIR) { $env:UV_INSTALL_DIR } else {
            Join-Path $HOME ".local\bin"
        }
        $candidate = Join-Path $installDir "uvx.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $uvxPath = $candidate
        } else {
            # The archive and hashes are published by Astral in its 0.13.9 release.
            # Pin the exact bytes instead of executing downloaded PowerShell code.
            $release = "0.13.9"
            $artifacts = @{
                X64 = @("uv-x86_64-pc-windows-msvc.zip", "edd61f7f5728a56cc62455386661860bdfc7bab65872f39b0c25bdcc1d8e1beb")
                Arm64 = @("uv-aarch64-pc-windows-msvc.zip", "72eed595983a4d7d22d79f21065b0f4479cc7e5c7a89104bb410c8f47559a878")
                X86 = @("uv-i686-pc-windows-msvc.zip", "eb4bd7285a512ebc4122f65a21b72e3f7072610d62164f43ca6aca280c39f6fd")
            }
            $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
            if (-not $artifacts.ContainsKey($architecture)) {
                throw "Unsupported Windows architecture: $architecture"
            }
            $artifact = $artifacts[$architecture]
            $url = "https://github.com/astral-sh/uv/releases/download/$release/$($artifact[0])"
            $temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("kicad-cloud-uv-" + [guid]::NewGuid().ToString("N"))
            try {
                New-Item -ItemType Directory -Path $temporary -Force | Out-Null
                $archive = Join-Path $temporary "uv.zip"
                $unpacked = Join-Path $temporary "unpacked"
                Write-Host "KiCad MCP Pro: Downloading a verified Astral uv release..."
                Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -TimeoutSec 90
                $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
                if ($actualHash -ne $artifact[1]) {
                    throw "Astral uv archive checksum mismatch. Installation aborted."
                }
                Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
                $uvBinary = Join-Path $unpacked "uv.exe"
                $uvxBinary = Join-Path $unpacked "uvx.exe"
                if (-not (Test-Path -LiteralPath $uvBinary -PathType Leaf) -or
                    -not (Test-Path -LiteralPath $uvxBinary -PathType Leaf)) {
                    throw "Official uv archive is missing expected Windows binaries."
                }
                New-Item -ItemType Directory -Path $installDir -Force | Out-Null
                Copy-Item -LiteralPath $uvBinary -Destination (Join-Path $installDir "uv.exe") -Force
                Copy-Item -LiteralPath $uvxBinary -Destination $candidate -Force
            } finally {
                if (Test-Path -LiteralPath $temporary) {
                    Remove-Item -LiteralPath $temporary -Recurse -Force
                }
            }
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
                throw "uvx was not found after installation. Your Cloud registration was not modified."
            }
            $uvxPath = $candidate
        }
    } else {
        $uvxPath = $uvx.Source
    }

    Write-Host "KiCad MCP Pro: Opening Cloud Connector..."
    & $uvxPath --from "kicad-mcp-pro" "kicad-mcp-pro" "cloud"
    if ($LASTEXITCODE -ne 0) {
        throw "Cloud Connector exited with code $LASTEXITCODE."
    }
}
