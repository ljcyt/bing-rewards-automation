#!/data/data/com.termux/files/usr/bin/bash
# Termux 保活配置（在手机 Termux 里执行一次：bash setup_keepalive.sh）
#
# 解决三个导致任务中断的问题：
#   1) 系统回收 Termux 进程        → 电池白名单 + appops 后台/前台权限 + 关闭幽灵进程限制
#   2) 设备休眠导致任务挂起         → termux-wake-lock 持锁
#   3) watcher/crond 被杀后不再恢复 → 交给 termux-services (runit) 托管，崩溃自动重启
#
# 电脑侧需先执行（无需 root，adb 直接设置）：
#   adb -s <serial> shell "dumpsys deviceidle whitelist +com.termux"
#   adb -s <serial> shell "cmd appops set com.termux RUN_IN_BACKGROUND allow"
#   adb -s <serial> shell "cmd appops set com.termux START_FOREGROUND allow"
#   adb -s <serial> shell "device_config put activity_manager max_phantom_processes 2147483647"
# 本脚本负责手机侧部分（wake-lock + 服务托管）。
set -e

export PATH=/data/data/com.termux/files/usr/bin:$PATH
export SVDIR=$PREFIX/var/service

echo "=== 1/4 安装 termux-services（runit 主管）==="
pkg install -y termux-services

echo "=== 2/4 wake-lock 持锁（防休眠）==="
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock && echo "wake-lock 已获取"
else
  echo "termux-wake-lock 不存在（Termux 0.118+ 已内置，若缺失请 pkg install termux-api）"
fi

echo "=== 3/4 托管 watcher 服务（崩溃自动重启）==="
SV="$SVDIR/watcher"
mkdir -p "$SV/log" "$PREFIX/var/log/sv/watcher"
printf '#!/data/data/com.termux/files/usr/bin/sh\nexec 2>&1\nexec bash /sdcard/br/watcher.sh\n' > "$SV/run"
chmod +x "$SV/run"
printf '#!/data/data/com.termux/files/usr/bin/sh\nexec svlogd -tt /data/data/com.termux/files/usr/var/log/sv/watcher\n' > "$SV/log/run"
chmod +x "$SV/log/run"
rm -f "$SV/down"   # down 文件 = 服务停用标记

echo "=== 4/4 托管 crond 服务 ==="
CSV="$SVDIR/crond"
mkdir -p "$CSV/log" "$PREFIX/var/log/sv/crond"
[ -f "$CSV/log/run" ] || printf '#!/data/data/com.termux/files/usr/bin/sh\nexec svlogd -tt /data/data/com.termux/files/usr/var/log/sv/crond\n' > "$CSV/log/run"
chmod +x "$CSV/log/run"
rm -f "$CSV/down"

# 停掉可能残留的手动实例（避免重复）
pkill -f '^bash /sdcard/br/watcher.sh$' 2>/dev/null || true

sv up watcher 2>&1
sv up crond 2>&1
sleep 3

echo
echo "=== 状态 ==="
sv status watcher 2>&1
sv status crond 2>&1
echo
ps -ef 2>/dev/null | grep -E 'watcher|crond' | grep -v grep
echo
echo "完成。两个服务由 runit 托管：被杀死后约 5 秒自动重启，Termux 重开后自动拉起。"
echo "手动检查：sv status watcher / sv status crond"
echo "重启服务：sv restart watcher"
