@echo off
call D:\BuildTools\VS2022\VC\Auxiliary\Build\vcvars64.bat >nul
if errorlevel 1 exit /b %errorlevel%
cl.exe /nologo /O2 /W4 /WX /LD /MT CpuProbe.c /link /OUT:CpuProbe.dll
exit /b %errorlevel%
