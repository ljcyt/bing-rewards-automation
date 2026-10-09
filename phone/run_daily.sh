#!/data/data/com.termux/files/usr/bin/bash
# 手机端每日执行入口：跑全部任务 → 自动审核今日积分（未满则抓取未完成任务）
# 用法：bash run_daily.sh
APP="$HOME/bing-rewards"
LOG="$APP/logs/run_$(date +%Y-%m-%d).log"
LOCK="$APP/.run_daily.lock"

cd "$APP" || exit 2
mkdir -p logs results

# 防重入：cron 与手动/多实例同时触发时只跑一个（Termux 无 flock，用 mkdir 原子性）
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(date)] 已有实例在运行（锁 $LOCK 存在），本次跳过" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

echo "[$(date)] === 每日任务开始 ===" >> "$LOG"

# 确保 adb server 活着并连上本机 adbd
adb start-server >/dev/null 2>&1 || true
adb connect 127.0.0.1:5555 >/dev/null 2>&1 || true

# 主任务（脚本内部跑完会自动审核今日积分；未满则抓取未完成任务并截图留证）
python3 bing_rewards.py >> "$LOG" 2>&1
RC=$?
echo "[$(date)] === 退出码 $RC ===" >> "$LOG"

# 只保留最近 14 天日志
find "$APP/logs" -name 'run_*.log' -mtime +14 -delete 2>/dev/null || true

exit $RC
