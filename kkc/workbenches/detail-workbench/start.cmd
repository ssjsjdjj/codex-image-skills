@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "WORKBENCH_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%WORKBENCH_PYTHON%" (
    set "WORKBENCH_PYTHON="
    for /f "delims=" %%I in ('where.exe python.exe 2^>nul') do if not defined WORKBENCH_PYTHON set "WORKBENCH_PYTHON=%%I"
)
if not defined WORKBENCH_PYTHON goto setup_required
"%WORKBENCH_PYTHON%" -c "import sys; assert sys.version_info >= (3, 10); import tkinter; from PIL import Image, ImageTk" >nul 2>&1
if errorlevel 1 goto setup_required
for %%I in ("%WORKBENCH_PYTHON%") do set "WORKBENCH_PYTHONW=%%~dpIpythonw.exe"
if exist "%WORKBENCH_PYTHONW%" (
    start "" "%WORKBENCH_PYTHONW%" "%~dp0app.py" %*
) else (
    "%WORKBENCH_PYTHON%" "%~dp0app.py" %*
)
exit /b %ERRORLEVEL%

:setup_required
echo Workbench dependencies are missing. Run install.cmd first.
pause
exit /b 1
