# -*- coding: utf-8 -*-
"""诊断：进新闻流后 dump，统计 _feed_article_candidates 命中数并打印卡片段落。"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    if card is None:
        print("FAIL: 未找到阅读卡")
        return 2
    anc = br.tapable_ancestor(card)
    if anc is None:
        print("FAIL: 卡片不可点")
        return 2
    log("  [diag] 点阅读卡进新闻流")
    br.safe_tap(human, adb, anc, log)
    human.sleep(9.0, 12.0, tag="read_landing")

    for round_i in range(4):
        xml = adb.dump()
        screen = br.Screen(xml, adb.current_activity())
        log("  [diag] 轮 %d activity=%s 节点数=%d" % (round_i, screen.activity, len(screen.nodes)))
        cands = br._feed_article_candidates(screen, set())
        log("  [diag] 候选文章卡=%d" % len(cands))
        for n in screen.nodes:
            d = (n.desc or "").strip()
            t = (n.text or "").strip()
            if d and (n.clickable or len(d) > 12):
                log("    node clickable=%s real=%s rid=%r desc=%r text=%r" % (
                    n.clickable, n.real, n.rid, d[:50], t[:50]))
            elif t and len(t) > 12 and not n.rid:
                log("    text-only clickable=%s real=%s rid=%r text=%r" % (
                    n.clickable, n.real, n.rid, t[:50]))
        human.swipe_up(adb)
        human.sleep(1.0, 2.0, tag="diag_scroll")
    # 退回积分页再回首页，保持现场可控
    br._back_to_points(adb, human, log)
    br.ensure_home(adb, human, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
