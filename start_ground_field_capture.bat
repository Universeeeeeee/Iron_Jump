@echo off
setlocal
cd /d "%~dp0"
set "GROUND_PYTHON=D:\conda\python.exe"
if not exist "%GROUND_PYTHON%" (
    echo Python was not found: %GROUND_PYTHON%
    pause
    exit /b 1
)
echo 1. A1 - fixed object, minimal capture, 60 seconds
echo 2. B  - fixed object, main program, manual stop
echo 3. A2 - fixed object, minimal capture, 60 seconds
echo 4. Walking - main program with raw capture
echo 5. Running - main program with raw capture
choice /c 12345 /n /m "Choose a capture [1-5]: "
set "GROUND_CHOICE=%errorlevel%"
set "GROUND_CONDITION=main"
if "%GROUND_CHOICE%"=="1" set "GROUND_LABEL=A1-fixed"
if "%GROUND_CHOICE%"=="1" set "GROUND_CONDITION=minimal"
if "%GROUND_CHOICE%"=="2" set "GROUND_LABEL=B-fixed"
if "%GROUND_CHOICE%"=="3" set "GROUND_LABEL=A2-fixed"
if "%GROUND_CHOICE%"=="3" set "GROUND_CONDITION=minimal"
if "%GROUND_CHOICE%"=="4" set "GROUND_LABEL=ground-walk"
if "%GROUND_CHOICE%"=="5" set "GROUND_LABEL=ground-run"
if not defined GROUND_LABEL exit /b 1
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss_fff"') do set "GROUND_STAMP=%%T"
set "GROUND_OUTPUT=exports\ground_field_20261010\%GROUND_LABEL%_%GROUND_STAMP%"
echo Capture directory: %CD%\%GROUND_OUTPUT%
echo Main-program captures: select the test mode in the UI.
echo Close the program after saving the report so the raw logs can finish.
"%GROUND_PYTHON%" -m tools.ground_capture_condition --condition "%GROUND_CONDITION%" --label "%GROUND_LABEL%" --output-dir "%GROUND_OUTPUT%"
set "GROUND_RESULT=%errorlevel%"
echo Capture process exited with code %GROUND_RESULT%.
echo Output directory: %CD%\%GROUND_OUTPUT%
pause
exit /b %GROUND_RESULT%
