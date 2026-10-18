@echo off
call D:\BuildTools\VS2022\VC\Auxiliary\Build\vcvars64.bat >nul
if errorlevel 1 exit /b %errorlevel%
cl.exe /nologo /O2 /W4 /WX /LD /MT DynamicOracle.c /link /OUT:DynamicOracle.dll
if errorlevel 1 exit /b %errorlevel%
set "RUSTC=C:\Users\86150\.rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\rustc.exe"
C:\Users\86150\.rustup\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe build --release --locked --offline
exit /b %errorlevel%
