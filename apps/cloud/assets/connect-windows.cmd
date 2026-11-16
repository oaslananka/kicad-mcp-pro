@echo off
setlocal EnableExtensions
title KiCad MCP Pro - Cloud device
echo.
echo  KiCad MCP Pro / Cloud device
echo  Keep this terminal open while using Cloud. Press Ctrl+C to disconnect.
echo.
rem Include normal per-user install locations without changing the permanent PATH.
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%USERPROFILE%\.local\bin;%PATH%"
where uvx >nul 2>nul
if errorlevel 1 (
  where winget >nul 2>nul
  if errorlevel 1 goto missing_winget
  echo Installing Astral uv using the official WinGet package...
  call winget install --id astral-sh.uv --exact --source winget --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto install_failed
  set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%USERPROFILE%\.local\bin;%PATH%"
)
where uvx >nul 2>nul
if errorlevel 1 goto missing_uvx
echo Starting the signed foreground Cloud Connector...
echo First connection requires owner approval in the browser.
echo.
call uvx --from kicad-mcp-pro kicad-mcp-pro cloud connect
set "exit_code=%ERRORLEVEL%"
if not "%exit_code%"=="0" echo Connector exited with an error. Check the message above.
echo Cloud session ended. Local KiCad files and saved pairing were not deleted.
pause
exit /b %exit_code%
:missing_winget
echo WinGet is unavailable. Install uv from https://docs.astral.sh/uv/getting-started/installation/
goto setup_failed
:install_failed
echo WinGet could not install Astral uv. Review the message above or install uv manually.
goto setup_failed
:missing_uvx
echo uvx was not found after setup. Open a new terminal and retry this launcher.
:setup_failed
pause
exit /b 2
