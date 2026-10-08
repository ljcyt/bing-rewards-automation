#!/bin/bash
# 等隧道恢复后自动跑一次每日任务（最多等 60 分钟）
cd "C:/Users/WSFG/.zcode/workspace/default/bing-rewards-automation" || exit 2
for i in $(seq 1 120); do
  adb disconnect 127.0.0.1:55556 >/dev/null 2>&1
  adb connect 127.0.0.1:55556 >/dev/null 2>&1
  sleep 2
  dev=$(adb devices | grep "127.0.0.1:55556" | awk '{print $2}')
  if [ "$dev" = "device" ]; then
    echo "[$(date +%H:%M:%S)] 设备已恢复，开始跑"
    if timeout 30 adb -s 127.0.0.1:55556 shell echo OK 2>&1 | grep -q OK; then
      python bing_rewards.py 2>&1 | tail -40
      echo "[$(date +%H:%M:%S)] 脚本退出码 ${PIPESTATUS[0]}"
      exit 0
    fi
  fi
  echo "[$(date +%H:%M:%S)] 等待中 ($i/120) dev=$dev"
  sleep 30
done
echo "[$(date +%H:%M:%S)] 60 分钟内隧道未恢复，放弃"
exit 2
