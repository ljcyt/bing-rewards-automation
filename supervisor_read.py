# -*- coding: utf-8 -*-
"""read 任务监督循环：跑 --single read → 测进度 → 30/30 或连续 2 轮不涨即停。
隧道抖动导致的崩溃轮不计入不涨轮次，但消耗轮次预算（最多 12 轮）。"""
import os
import re
import subprocess
import sys
import time

BASE = r"C:\Users\WSFG\.zcode\workspace\default\bing-rewards-automation"
SERIAL = "127.0.0.1:55556"


def adb_ok():
    try:
        r = subprocess.run(["adb", "-s", SERIAL, "shell", "echo", "ok"],
                           capture_output=True, text=True, timeout=25)
        return "ok" in r.stdout
    except Exception:
        return False


def ensure_connected(max_wait=240):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        subprocess.run(["adb", "connect", SERIAL], capture_output=True, timeout=20)
        if adb_ok():
            return True
        time.sleep(10)
    return False


def measure():
    """跑 read_progress.py 读 X/30；失败重试 3 次。返回 (x, y) 或 None。"""
    for _ in range(3):
        if not ensure_connected():
            continue
        try:
            r = subprocess.run([sys.executable, "read_progress.py"], cwd=BASE,
                               capture_output=True, text=True, timeout=420)
            m = re.search(r"READ_PROGRESS=(\d+)/(\d+)", r.stdout)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        time.sleep(15)
    return None


def main():
    prev = None
    no_progress = 0
    for rnd in range(3, 13):  # 轮 3..12
        if not ensure_connected():
            print("SUP: 设备不可达，中止", flush=True)
            break
        print("SUP: === 第 %d 轮开始 ===" % rnd, flush=True)
        try:
            p = subprocess.run([sys.executable, "bing_rewards.py", "--single", "read"],
                               cwd=BASE, capture_output=True, text=True, timeout=5400)
            print("SUP: 第 %d 轮脚本退出码 %d" % (rnd, p.returncode), flush=True)
            ran_ok = (p.returncode == 0)
        except Exception as e:
            print("SUP: 第 %d 轮异常 %r" % (rnd, e), flush=True)
            ran_ok = False
        m = measure()
        if m is None:
            print("SUP: 第 %d 轮测量失败（不计不涨）" % rnd, flush=True)
            prev = None
            continue
        x, y = m
        print("SUP: 第 %d 轮进度 %d/%d（前值 %s）" % (rnd, x, y, prev), flush=True)
        if x >= y:
            print("SUP: 已满 %d/%d → 结束" % (x, y), flush=True)
            prev = x
            break
        if prev is not None and x <= prev and ran_ok:
            no_progress += 1
            print("SUP: 不涨（连续 %d 次）" % no_progress, flush=True)
        else:
            no_progress = 0
        prev = x
        if no_progress >= 2:
            print("SUP: 连续 2 轮不涨 → 停止", flush=True)
            break
    print("SUP: 最终进度 %s" % (prev,), flush=True)


if __name__ == "__main__":
    main()
