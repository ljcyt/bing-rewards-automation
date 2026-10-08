@echo off
rem 从电脑推送脚本到云手机 /sdcard/br/（经 adb 隧道，仅用于部署与验收）
rem 用法：push-to-phone.bat [设备串号]
setlocal
set SERIAL=%1
if "%SERIAL%"=="" set SERIAL=127.0.0.1:55556
set SRC=%~dp0..

echo [1/3] 连接 %SERIAL% ...
adb connect %SERIAL%
adb -s %SERIAL% wait-for-device

echo [2/3] 生成手机版 config.json（device.serial=127.0.0.1:5555）...
python "%~dp0make_phone_config.py" || goto :fail

echo [3/3] 推送到 /sdcard/br/ ...
adb -s %SERIAL% shell mkdir -p /sdcard/br/
adb -s %SERIAL% push "%SRC%\bing_rewards.py" /sdcard/br/bing_rewards.py || goto :fail
adb -s %SERIAL% push "%SRC%\words.txt" /sdcard/br/words.txt || goto :fail
adb -s %SERIAL% push "%~dp0config.phone.json" /sdcard/br/config.json || goto :fail
adb -s %SERIAL% push "%~dp0setup-termux.sh" /sdcard/br/setup-termux.sh || goto :fail
adb -s %SERIAL% push "%~dp0deploy.sh" /sdcard/br/deploy.sh || goto :fail
adb -s %SERIAL% push "%~dp0run_daily.sh" /sdcard/br/run_daily.sh || goto :fail

echo.
echo 推送完成。接下来在云手机 Termux 里依次执行：
echo   bash /sdcard/br/setup-termux.sh
echo   bash /sdcard/br/deploy.sh
echo   bash /sdcard/br/run_daily.sh
exit /b 0

:fail
echo 推送失败，请检查隧道与设备连接。
exit /b 2
