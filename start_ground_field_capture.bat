@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "GROUND_PYTHON=D:\conda\python.exe"
if not exist "%GROUND_PYTHON%" (
    echo Python was not found: %GROUND_PYTHON%
    pause
    exit /b 1
)
"%GROUND_PYTHON%" -X utf8 -m tools.ground_field_capture
exit /b %errorlevel%
