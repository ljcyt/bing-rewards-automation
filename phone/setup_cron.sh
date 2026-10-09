#!/data/data/com.termux/files/usr/bin/bash
# 配置 Termux 每日定时（在手机 Termux 里执行一次：bash setup_cron.sh）
# 默认每天 09:00 跑；改时间就改下面 CRON_LINE 的 "0 9"（分 时）
set -e

export PATH=/data/data/com.termux/files/usr/bin:$PATH
export SVDIR=$PREFIX/var/service
APP="$HOME/bing-rewards"

echo "=== 1/4 安装 cronie ==="
pkg install -y cronie termux-services

echo "=== 2/4 写入 crontab ==="
mkdir -p "$APP/logs" "$PREFIX/tmp"
# 每天 09:00 执行；PATH 必须显式带上 Termux 的 bin（cron 环境很干净）
CRON_LINE="0 9 * * * PATH=/data/data/com.termux/files/usr/bin:\$PATH bash $APP/run_daily.sh >> $APP/logs/cron.log 2>&1"
TMPF="$PREFIX/tmp/mycron"
# 保留已有的非本任务行，替换/追加本任务行
( crontab -l 2>/dev/null | grep -v 'bing-rewards/run_daily.sh' ; echo "$CRON_LINE" ) > "$TMPF"
crontab "$TMPF"
echo "已写入 crontab："
crontab -l

echo "=== 3/4 启动 crond ==="
# 重要：crond 只能有一个实例。两个 crond 读同一份 crontab 会导致同一时刻触发两次任务
# （实测 10-09 双实例并发：读积分失败、quiz 三连败）。优先用 runit 服务管理；
# 若 runit 不可用才回退手动启动，且先确保没有已在运行的 crond。
rm -f "$SVDIR/crond/down"
if sv up crond 2>/dev/null && sv status crond 2>/dev/null | grep -q "^run:"; then
  echo "crond 由 runit 管理（开机自启）"
else
  echo "runit 不可用，回退手动启动"
  pkill crond 2>/dev/null || true
  sleep 1
  nohup crond > "$APP/logs/crond.log" 2>&1 &
fi
sleep 3

echo "=== 4/4 状态 ==="
running=$(pgrep -c -f 'crond' 2>/dev/null || echo 0)
echo "crond 相关进程数: $running"
pgrep -af crond 2>&1
if [ "$running" -ge 1 ]; then
  echo "crond 运行中"
else
  echo "crond 未运行；重试：nohup crond > $APP/logs/crond.log 2>&1 &"
fi

echo
echo "完成。定时：每天 09:00（日志 $APP/logs/cron.log）"
echo "手动测试一次：bash $APP/run_daily.sh"
echo "立即审核（不跑任务）：cd $APP && python3 bing_rewards.py --audit"
echo
echo "注意：Termux 进程需保活，建议在云手机设置里给 Termux 加电池白名单/后台允许，"
echo "      否则系统回收后 cron 会停；重进 Termux 后重跑本脚本即可恢复。"
