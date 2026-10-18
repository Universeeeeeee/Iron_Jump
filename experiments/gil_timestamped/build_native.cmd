@echo off
call "%~1\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b %errorlevel%
cl.exe /nologo /O2 /W4 /WX /LD /MT "%~2" /link /OUT:"%~3"
exit /b %errorlevel%
