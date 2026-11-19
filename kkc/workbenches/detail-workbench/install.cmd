@echo off
setlocal
if not exist "%~dp0install.ps1" (
  echo Setup files are incomplete. Right-click the ZIP and choose Extract All first.
  if "%~1"=="" pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "WORKBENCH_INSTALL_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %WORKBENCH_INSTALL_EXIT%
