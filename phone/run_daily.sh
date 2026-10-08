#!/data/data/com.termux/files/usr/bin/bash
# 手机端每日执行入口（在 Termux 里执行：bash run_daily.sh）
# 全部操作走本机 adb（127.0.0.1:5555），不依赖任何隧道。
APP="$HOME/bing-rewards"
LOG="$APP/logs/run_$(date +%Y-%m-%d).log"

cd "$APP" || exit 2
mkdir -p logs results

echo "[$(date)] === 每日任务开始 ===" >> "$LOG"

# 确保 adb server 活着并连上本机 adbd
adb start-server >/dev/null 2>&1 || true
adb connect 127.0.0.1:5555 >/dev/null 2>&1 || true

python3 bing_rewards.py >> "$LOG" 2>&1
RC=$?
echo "[$(date)] === 退出码 $RC ===" >> "$LOG"

# 只保留最近 14 天日志
find "$APP/logs" -name 'run_*.log' -mtime +14 -delete 2>/dev/null || true

exit $RC
