# -*- coding: utf-8 -*-
"""读取'阅读以赚取'卡片进度 X/30：启动 Bing → 进积分页 → 滚动定位卡片。
用法：python read_progress.py
输出：READ_PROGRESS=X/Y 或 FAIL 原因。退出码 0 成功，2 失败。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import bing_rewards as br  # noqa: E402


def main():
    cfg = br.load_config(os.path.join(BASE_DIR, "config.json"))
    log = br.Logger(os.path.join(BASE_DIR, "logs"))
    dev = cfg.get("device", {})
    adb = br.Adb(dev.get("serial", "127.0.0.1:55556"), dev.get("adb_path", "adb"), log)
    human = br.Human(cfg, log)
    if not adb.device_online():
        print("FAIL: 设备不在线")
        return 2
    if "com.microsoft.bing" not in adb.current_activity():
        adb.start_bing()
        human.sleep(*human.page, tag="bing_start")
    if not br.goto_rewards_entry(adb, human, log):
        print("FAIL: 未能进入积分页")
        return 2
    earned, need, card = br._find_read_card(adb, human, log)
    if earned is None:
        print("FAIL: 积分页未找到'阅读以赚取'卡")
        return 2
    print("READ_PROGRESS=%s/%s" % (earned, need))
    return 0


if __name__ == "__main__":
    sys.exit(main())
