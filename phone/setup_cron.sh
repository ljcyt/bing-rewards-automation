#!/data/data/com.termux/files/usr/bin/bash
# 配置 Termux 每日定时（在手机 Termux 里执行一次：bash setup_cron.sh）
# 默认每天 09:00 跑；改时间就改下面 CRON_LINE 的 "0 9"（分 时）
set -e

APP="$HOME/bing-rewards"

echo "=== 1/4 安装 cronie（Termux 的 cron 实现）==="
pkg install -y cronie termux-services

echo "=== 2/4 写入 crontab ==="
# 每天 09:00 执行；PATH 必须显式带上 Termux 的 bin
CRON_LINE="0 9 * * * PATH=/data/data/com.termux/files/usr/bin:\$PATH bash $APP/run_daily.sh >> $APP/logs/cron.log 2>&1"
mkdir -p "$APP/logs"
# 保留已有的非本任务行，替换/追加本任务行
( crontab -l 2>/dev/null | grep -v 'bing-rewards/run_daily.sh' ; echo "$CRON_LINE" ) | crontab -
echo "已写入："
crontab -l

echo "=== 3/4 启动 crond（termux-services 管理，开机自启）==="
mkdir -p "$PREFIX/var/service/crond"
ln -sf "$PREFIX/share/termux-services/svlogger" "$PREFIX/var/service/crond/log/run" 2>/dev/null || true
sv-enable crond 2>/dev/null || true
sv up crond 2>/dev/null || true
sleep 2

echo "=== 4/4 状态 ==="
sv status crond 2>/dev/null || echo "（sv 不可用，可手动启动：crond）"
pgrep -f crond >/dev/null && echo "crond 运行中" || echo "crond 未运行"

echo
echo "完成。定时：每天 09:00（日志 $APP/logs/cron.log）"
echo "手动测试一次：bash $APP/run_daily.sh"
echo "立即审核（不跑任务）：cd $APP && python3 bing_rewards.py --audit"
