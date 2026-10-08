#!/data/data/com.termux/files/usr/bin/bash
# 常驻命令轮询器（在 Termux 里执行一次：bash /sdcard/br/watcher.sh）
#
# 为什么需要它：通过 adb 往 Termux 终端 `input text` 敲命令极不稳定（隧道抖动时丢失）。
# 这个轮询器启动后，只需把 .sh 文件 push 到 /sdcard/br/cmd/，就会被自动执行，
# 输出写到 /sdcard/br/out/<名字>.txt，无需再碰终端输入。
#
# 用法：
#   adb push 你的脚本.sh /sdcard/br/cmd/task.sh
#   adb shell cat /sdcard/br/out/task.txt
CMD=/sdcard/br/cmd
OUT=/sdcard/br/out
mkdir -p "$CMD" "$OUT"
echo "watcher started $(date)" > /sdcard/br/watcher.log
while true; do
  for f in "$CMD"/*.sh; do
    [ -e "$f" ] || continue
    name=$(basename "$f" .sh)
    echo "[$(date +%H:%M:%S)] run $name" >> /sdcard/br/watcher.log
    mv "$f" "$CMD/.running_$name.sh"
    bash "$CMD/.running_$name.sh" > "$OUT/$name.txt" 2>&1
    echo "[$(date +%H:%M:%S)] done $name rc=$?" >> /sdcard/br/watcher.log
    rm -f "$CMD/.running_$name.sh"
  done
  sleep 5
done
