#!/data/data/com.termux/files/usr/bin/bash
# 云手机端一次性环境准备（在 Termux 里执行：bash setup-termux.sh）
# 装 Python + adb 客户端，并修复 adb 的 libc++ 符号链接问题。
set -e

echo "=== 1/4 更新源并安装依赖 ==="
pkg update -y || true
pkg install -y python android-tools

echo "=== 2/4 修复 adb 链接（libc++ 需 >= 30）==="
if ! adb version >/dev/null 2>&1; then
  echo "adb 链接失败，升级 libc++ ..."
  pkg install -y libc++ || pkg upgrade -y libc++
fi
adb version | head -2

echo "=== 3/4 启动 adb server 并连接本机 adbd ==="
adb kill-server 2>/dev/null || true
adb start-server
adb connect 127.0.0.1:5555
sleep 2
adb devices

echo "=== 4/4 自检 ==="
adb -s 127.0.0.1:5555 shell echo PHONE_ADB_OK
adb -s 127.0.0.1:5555 shell "uiautomator dump /sdcard/_selftest.xml" >/dev/null && echo "uiautomator OK"
python3 --version

echo
echo "环境就绪。下一步：bash deploy.sh"
