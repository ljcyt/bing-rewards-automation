@echo off
rem Bing Rewards 每日定时任务入口（由 schtasks 调用）
cd /d %~dp0

rem adb 不在 PATH 时取消下一行注释并改为实际路径
rem set PATH=%PATH%;D:\platform-tools

rem 云手机串号（与 config.json 的 device.serial 保持一致，改串号时两处同步改）
set SERIAL=127.0.0.1:55556

if not exist logs mkdir logs

rem 日期戳用 python 生成，避免 %date% 依赖中文区域日期格式
set today=
for /f %%i in ('python -c "import datetime;print(datetime.date.today().strftime('%%Y%%m%%d'))"') do set today=%%i
if "%today%"=="" set today=run
set LOG=logs\sched_%today%.log

echo [%date% %time%] scheduled run start >> %LOG%

rem 等待云手机上线：最多 30 次 x 10 秒（约 5 分钟），防止设备未启动时永久挂起
set /a tries=0
:waitloop
adb -s %SERIAL% get-state 2>nul | findstr /C:"device" >nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% GEQ 30 (
    echo [%date% %time%] DEVICE_OFFLINE: %SERIAL% 5 分钟内未上线 >> logs\alerts.log
    echo [%date% %time%] device offline, give up >> %LOG%
    exit /b 2
)
ping -n 11 127.0.0.1 >nul
goto waitloop

:ready
echo [%date% %time%] device %SERIAL% online >> %LOG%

python bing_rewards.py --config config.json >> %LOG% 2>&1
set RC=%ERRORLEVEL%
echo [%date% %time%] exit code %RC% >> %LOG%

if %RC% GEQ 2 echo %date% %time% LEVEL2_FAIL >> logs\alerts.log
if %RC% EQU 1 echo %date% %time% PARTIAL_FAIL >> logs\alerts.log
if %RC% EQU 0 echo %date% %time% ALL_DONE >> logs\alerts.log

exit /b %RC%
