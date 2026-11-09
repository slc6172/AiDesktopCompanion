@echo off
setlocal
rem Same program as run.bat, but with a console window: you can watch what it prints and any error.
rem Closing the pet window ends the program; this window then waits for a key before it closes.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto no_venv

".venv\Scripts\python.exe" app.py
echo.
echo The program ended with exit code %errorlevel%. The log file is data\app.log
pause
exit /b 0

:no_venv
echo.
echo The Python virtual environment (.venv) was not found in this folder. See docs\install.md
echo.
pause
exit /b 1
