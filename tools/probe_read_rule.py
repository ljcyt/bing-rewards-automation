# -*- coding: utf-8 -*-
"""实验：逐篇阅读并逐篇核对积分页进度，确定"阅读以赚取"的计分规则。
用法：python3 probe_read_rule.py
输出 /sdcard/probe_read_rule.txt
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bing_rewards as br

OUT = "/sdcard/probe_read_rule.txt"
lines = []


def w(s):
    lines.append(s)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def read_card(adb, human, log):
    """进积分页读进度，再回首页。"""
    if not br.goto_rewards_entry(adb, human, log):
        return None
    earned, need, card = br._find_read_card(adb, human, log)
    br.ensure_home(adb, human, log)
    return (earned, need)


def main():
    cfg = br.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    log = br.Logger(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
    dev = cfg.get("device", {})
    adb = br.Adb(dev.get("serial"), dev.get("adb_path", "adb"), log)
    human = br.Human(cfg, log)

    w("=== 阅读计分规则探测 %s ===" % time.strftime("%H:%M:%S"))

    r = read_card(adb, human, log)
    w("起始进度: %s" % (r,))

    for i in range(1, 4):
        w("--- 第 %d 篇 ---" % i)
        # 进积分页，滚到阅读卡可见，点进新闻流
        if not br.goto_rewards_entry(adb, human, log):
            w("  未能进积分页"); break
        earned, need, card = br._find_read_card(adb, human, log, need_visible=True)
        if card is None:
            w("  未找到可见阅读卡"); break
        w("  点前卡片进度 %s/%s real=%s bounds=%s" % (earned, need, card.real, card.bounds))
        target = card if card.real else br.tapable_ancestor(card)
        if not target or not br.safe_tap(human, adb, target, log):
            w("  卡片不可点"); break
        human.sleep(8.0, 11.0, tag="landing")
        act = adb.current_activity()
        w("  点击后 activity=%s" % act)
        scr = br.Screen(adb.dump(), act)
        if "TemplateActivity" in act or scr.by_id("com.microsoft.bing:id/dailyActivities"):
            w("  仍在积分页 → 放弃本实验"); break
        # 选一篇文章
        cands = br._feed_article_candidates(scr, set())
        w("  候选文章 %d 篇" % len(cands))
        if not cands:
            w("  无候选文章"); break
        t = cands[0]
        w("  点文章 %r bounds=%s" % (t.desc[:40], t.bounds))
        if not br.safe_tap(human, adb, t, log):
            w("  文章不可点"); break
        human.sleep(6.0, 8.0, tag="article_load")
        act2 = adb.current_activity()
        w("  文章页 activity=%s" % act2)
        # 长停留 35 秒 + 滚动
        for k in range(3):
            human.sleep(10.0, 12.0, tag="dwell")
            human.swipe_up(adb)
        adb.key(br.KEY_BACK)
        human.sleep(*human.page, tag="back")
        # 核对进度
        r2 = read_card(adb, human, log)
        w("  读后进度: %s（前值 %s）" % (r2, r))
        if r2 and r and r2[0] is not None and r[0] is not None:
            w("  本篇增量: %s" % (r2[0] - r[0]))
        r = r2

    w("=== 结束 %s ===" % time.strftime("%H:%M:%S"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
