@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "WORKBENCH_INSTALL_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %WORKBENCH_INSTALL_EXIT%
