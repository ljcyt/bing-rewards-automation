#!/data/data/com.termux/files/usr/bin/bash
# 把脚本部署进 Termux 家目录（在 Termux 里执行：bash deploy.sh）
# 前置：setup-termux.sh 已跑过；bing_rewards.py / config.json / words.txt 已放在 /sdcard/br/
set -e

APP="$HOME/bing-rewards"
SRC="/sdcard/br"

echo "=== 部署到 $APP ==="
mkdir -p "$APP/logs" "$APP/results"
cp "$SRC/bing_rewards.py" "$SRC/config.json" "$SRC/words.txt" "$APP/"

cd "$APP"
python3 -m py_compile bing_rewards.py && echo "语法检查通过"

echo "=== dry-run 自检 ==="
timeout 180 python3 bing_rewards.py --dry-run 2>&1 | tail -20

echo
echo "部署完成。正式运行：bash run_daily.sh"
