@echo off
call D:\BuildTools\VS2022\VC\Auxiliary\Build\vcvars64.bat >nul
if errorlevel 1 exit /b %errorlevel%
cl.exe /nologo /O2 /W4 /WX /LD /MT /ID:\conda\include NativeOwner.c D:\conda\libs\python311.lib /link /OUT:NativeOwner.dll
exit /b %errorlevel%
