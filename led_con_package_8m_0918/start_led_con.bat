@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 goto no_python

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)

if not exist ".venv\.dependencies-ready" (
    echo Installing required Python packages...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
    type nul > ".venv\.dependencies-ready"
)

echo Starting the 8m 768-LED monitor...
".venv\Scripts\python.exe" ui\led_con_8m.py
if errorlevel 1 goto failed
exit /b 0

:no_python
echo Python was not found.
echo Install 64-bit Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
echo During installation, enable "Add Python to PATH", then run this file again.
pause
exit /b 1

:failed
echo.
echo Installation or startup failed. See the error message above.
pause
exit /b 1
