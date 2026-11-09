@echo off
setlocal
rem Starts the desktop pet with NO console window: only the pet window appears.
rem Use run-debug.bat instead to see what the program prints. Setup steps: docs\install.md
cd /d "%~dp0"

rem ---- check the installation first; a hidden program cannot show its own start-up errors ----
if not exist ".venv\Scripts\pythonw.exe" goto no_venv
".venv\Scripts\python.exe" -c "import uvicorn" >nul 2>&1
if errorlevel 1 goto no_packages
if not exist "electron\node_modules\electron\path.txt" goto no_electron
set ELECTRON_EXE=
set /p ELECTRON_EXE=<"electron\node_modules\electron\path.txt"
if not defined ELECTRON_EXE goto no_electron
if not exist "electron\node_modules\electron\dist\%ELECTRON_EXE%" goto no_electron

start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0

:no_venv
echo.
echo The Python virtual environment (.venv) was not found in this folder.
echo Create it, then install the packages:
echo     python -m venv .venv
echo     .venv\Scripts\pip install -r requirements.txt
echo Full steps: docs\install.md
echo.
pause
exit /b 1

:no_packages
echo.
echo The Python packages are not installed in .venv. Run:
echo     .venv\Scripts\pip install -r requirements.txt
echo Full steps: docs\install.md
echo.
pause
exit /b 1

:no_electron
echo.
echo Electron (the pet window) is not installed, or its program file is missing.
echo Install it once:
echo     cd electron
echo     npm install
echo If the download is slow or fails, see docs\install.md for the mirror and manual-download options.
echo.
pause
exit /b 1
