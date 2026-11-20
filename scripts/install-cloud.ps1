# KiCad MCP Pro Cloud - one-command Windows user bootstrap.
# Entrypoint: irm https://raw.githubusercontent.com/oaslananka/kicad-mcp-pro/main/scripts/install-cloud.ps1 | iex
# The official Astral installer is used only when uvx is not already installed.
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
            Write-Host "KiCad MCP Pro: Installing uv in your user profile..."
            $officialInstaller = Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" -TimeoutSec 45
            if (-not [string]::IsNullOrWhiteSpace($officialInstaller)) {
                Invoke-Expression $officialInstaller
            } else {
                throw "The official uv installer returned no content."
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
