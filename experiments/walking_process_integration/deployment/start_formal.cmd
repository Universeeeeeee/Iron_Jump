@echo off
setlocal
set PYTHONUTF8=1
set QT_API=pyside6
cd /d "E:\OptoJump\Iron_Jump"
"D:\conda\python.exe" -m ui.main_window
if errorlevel 1 (
  echo IronJump exited with an error. Keep this window for diagnosis.
  pause
)
endlocal
