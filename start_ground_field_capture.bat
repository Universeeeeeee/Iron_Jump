@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "GROUND_PYTHON=D:\conda\python.exe"
if not exist "%GROUND_PYTHON%" (
    echo 未找到Python：%GROUND_PYTHON%
    pause
    exit /b 1
)
echo 请依次完成1、2、3、4、5，每次只打开一个采集程序。
echo 1. A1固定物：纯命令行，自动采集60秒，无图形界面
echo 2. B固定物：打开主程序界面，需要手动结束
echo 3. A2固定物：纯命令行，自动采集60秒，无图形界面
echo 4. 正常走路：打开主程序界面，同时录制原始USB数据
echo 5. 正常跑步：打开主程序界面，同时录制原始USB数据
choice /c 12345 /n /m "请选择采集项目 [1-5]："
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
echo.
if "%GROUND_CONDITION%"=="minimal" (
    echo 当前是固定物最小采集，不会打开图形界面。
    echo 开始前：在第3段中部放好不透明固定物，连续遮挡约20厘米，避开接缝。
    echo 人站在跑道外。采集期间物体保持不动，不拔插设备或更换USB接口。
    echo 按键后自动采集60秒，请等待完成提示。
)
if "%GROUND_CHOICE%"=="2" (
    echo 开始前：先移走固定物，让跑道保持空场。
    echo 按键后打开主程序，选择8米地面走路，结束条件选软件手动结束。
    echo 完成空场预检并点击开始后，把固定物放回第3段的同一标记位置。
    echo 稳定保持60秒，再手动结束。录屏须包含相机预览和报告概览。
    echo 保存报告后关闭整个主程序，返回此窗口等待日志写完。
)
if "%GROUND_CHOICE%"=="4" echo 按键后打开主程序，请选择8米地面走路。
if "%GROUND_CHOICE%"=="5" echo 按键后打开主程序，请选择8米地面跑步。
if "%GROUND_CHOICE%"=="4" call :movement_instructions
if "%GROUND_CHOICE%"=="5" call :movement_instructions
echo.
echo 准备好后按任意键开始；尚未准备好可按Ctrl+C取消。
pause >nul
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss_fff"') do set "GROUND_STAMP=%%T"
set "GROUND_OUTPUT=exports\ground_field_20261010\%GROUND_LABEL%_%GROUND_STAMP%"
echo 本轮保存目录：%CD%\%GROUND_OUTPUT%
if "%GROUND_CONDITION%"=="minimal" echo 采集已开始，请保持固定物不动，等待约60秒。
"%GROUND_PYTHON%" -m tools.ground_capture_condition --condition "%GROUND_CONDITION%" --label "%GROUND_LABEL%" --output-dir "%GROUND_OUTPUT%"
set "GROUND_RESULT=%errorlevel%"
if "%GROUND_RESULT%"=="0" (
    echo 本轮采集完成，程序已正常退出。
) else (
    echo 本轮采集异常退出，错误码：%GROUND_RESULT%。请保留目录并反馈窗口中的报错。
)
echo 数据保存目录：%CD%\%GROUND_OUTPUT%
if "%GROUND_CHOICE%"=="1" echo 下一步选2：先移走固定物，再打开主程序完成空场预检。
if "%GROUND_CHOICE%"=="2" echo 下一步选3：固定物留在同一标记位置，再进行60秒最小采集。
if "%GROUND_CHOICE%"=="3" echo 下一步选4：移走固定物，准备正常走路测试。
if "%GROUND_CHOICE%"=="4" echo 下一步选5：准备正常跑步测试。
echo 按任意键关闭此窗口。
pause
exit /b %GROUND_RESULT%

:movement_instructions
echo 结束条件选软件手动结束；展开滤波参数，将最小接触时间设为60毫秒。
echo 完成空场预检，点击开始后先留约3秒空场，再正常走或跑过整个设备末端。
echo 从跑道外返回，离场后留约3秒空场，再手动结束；独立记实际落脚次数。
echo 录屏须包含相机预览和报告概览，另保存明细TXT并导出Excel。
echo 保存后关闭整个主程序，返回此窗口等待日志写完。
exit /b 0
