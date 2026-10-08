# -*- coding: utf-8 -*-
"""诊断：阅读任务为何不计分。
逐步复现 task_read 的导航与收割逻辑，输出每步的 activity 与候选文章卡。
用法：python tools/diag_read.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import bing_rewards as br  # noqa: E402

out = []


def w(s):
    out.append(s)
    print(s)


def main():
    cfg = br.load_config(os.path.join(BASE_DIR, "config.json"))
    log = br.Logger(os.path.join(BASE_DIR, "logs"))
    dev = cfg.get("device", {})
    adb = br.Adb(dev.get("serial", "127.0.0.1:55556"), dev.get("adb_path", "adb"), log)
    human = br.Human(cfg, log)

    if not adb.device_online():
        w("FAIL 设备不在线")
        return 2
    if "com.microsoft.bing" not in adb.current_activity():
        adb.start_bing()
        human.sleep(*human.page, tag="bing_start")

    w("=== 步骤1：进积分页 ===")
    if not br.goto_rewards_entry(adb, human, log):
        w("FAIL 未进积分页")
        return 2
    w("activity=%s" % adb.current_activity())

    w("=== 步骤2：定位阅读卡 ===")
    earned, need, card = br._find_read_card(adb, human, log)
    w("阅读卡: earned=%s need=%s" % (earned, need))
    if card is None:
        w("FAIL 未找到阅读卡")
        return 2
    w("卡片 desc=%r bounds=%s real=%s" % (card.desc[:60], card.bounds, card.real))

    anc = br.tapable_ancestor(card)
    w("可视祖先: %s" % (repr(anc.bounds) if anc else None))
    if anc is None:
        w("FAIL 无可点祖先")
        return 2

    w("=== 步骤3：点击阅读卡 ===")
    br.safe_tap(human, adb, anc, log)
    human.sleep(9.0, 11.0, tag="read_landing")
    act = adb.current_activity()
    w("点击后 activity=%s" % act)

    w("=== 步骤4：dump 并列出候选 ===")
    screen = br.Screen(adb.dump(), act)
    w("节点数=%d  零bounds节点=%d" % (len(screen.nodes), sum(1 for n in screen.nodes if not n.real)))
    cands = br._feed_article_candidates(screen, set())
    w("候选文章卡=%d" % len(cands))
    for n in cands[:8]:
        w("  cand desc=%r bounds=%s" % (n.desc[:55], n.bounds))

    w("=== 步骤5：看页面里所有 clickable+desc 节点（判断是否还在积分页）===")
    cnt = 0
    for n in screen.nodes:
        if n.clickable and n.desc and n.desc.strip():
            cnt += 1
            if cnt <= 12:
                w("  click desc=%r rid=%r real=%s" % (n.desc[:50], n.rid, n.real))
    w("clickable+desc 总数=%d" % cnt)

    w("=== 步骤6：是否含积分页特征节点 ===")
    w("含'阅读以赚取'卡=%s" % any("阅读以赚取" in (n.desc or "") for n in screen.nodes))
    w("含'每日活动'文本=%s" % any("每日活动" in (n.text or "") for n in screen.nodes))
    w("含 sa_search_box=%s" % bool(screen.by_id("com.microsoft.bing:id/sa_search_box")))

    with open(os.path.join(BASE_DIR, "_dev", "diag_read_out.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
