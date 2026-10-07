# -*- coding: utf-8 -*-
"""修复项自查单测（不依赖真机/torch）：python tools/test_fixes.py"""
import math
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import bing_rewards as br  # noqa: E402

log = br.Logger(os.path.join(BASE_DIR, "logs"), dry=True)
passed = []

# ---------- 1) 规则引擎 rewards 页对三类任务候选都能给动作（修 daily_activities 死锁） ----------
rule = br.RuleEngine(log)
ctx_rw = {"page_type": "rewards", "anchors": [],
          "xml": "<hierarchy>每日活动 阅读以赚取 赚取 10 积分</hierarchy>"}
d1 = rule.decide('s', ["open_daily_task", "go_back"], dict(ctx_rw))
assert d1["action"] == "open_daily_task" and d1["backend"] == "rule_engine", d1
d2 = rule.decide('s', ["open_quiz_card", "go_back", "task_done"], dict(ctx_rw))
assert d2["action"] == "open_quiz_card", d2
d3 = rule.decide('s', ["open_read_task", "go_back"], dict(ctx_rw))
assert d3["action"] == "open_read_task", d3
passed.append("1 规则引擎 rewards 三类候选覆盖(open_daily_task/quiz/read)")

# ---------- 2) OK 词边界：'YESOK' 不误点，独立 'OK' 命中 ----------
s1 = br.Screen('<hierarchy><node text="YESOK" clickable="true" bounds="[0,0][100,100]"/></hierarchy>')
s2 = br.Screen('<hierarchy><node text="OK" clickable="true" bounds="[0,0][100,100]"/></hierarchy>')


class TappingHuman:
    def __init__(self):
        self.taps = []

    def tap(self, adb, node):  # 与 Human.tap(adb, node) 同签名
        self.taps.append(node.label)

    def sleep(self, *a, **k):
        pass


h = TappingHuman()
assert br.handle_popup(s1, h, None, log) is False, "OK 子串误命中"
assert h.taps == [], "YESOK 被点击"
assert br.handle_popup(s2, h, None, log) is True, "独立 OK 未命中"
assert len(h.taps) == 1
passed.append("2 OK 词边界匹配(YESOK 不误点, OK 命中)")

# ---------- 3) LocalLogits softmax：负 logits 不被 clamp，概率归一 ----------
class Scal:
    def __init__(self, v):
        self.v = v

    def item(self):
        return self.v


class Vec:
    def __init__(self, d):
        self.d = d

    def __getitem__(self, i):
        return Scal(self.d[i])


class Mat:
    def __init__(self, d):
        self.d = d

    def __getitem__(self, idx):  # [0, -1, :] 元组索引 → 返回向量
        return Vec(self.d)


class FakeTok:
    ids = {" go_back": [0], " wait": [1], " task_done": [2]}

    def encode(self, s):
        return self.ids[s]

    def __call__(self, p, return_tensors=None):
        return {}


class FakeModel:
    def __init__(self, d):
        self.d = d

    def __call__(self, **kw):
        out = type('O', (), {})()
        out.logits = Mat(self.d)  # 模拟 tensor: logits[0, -1, :] → Vec
        return out


lb = object.__new__(br.LocalLogitsBackend)
lb.ok = True
lb.tok = FakeTok()
lb.temperature = 1.0
lb.torch = type('T', (), {'no_grad': staticmethod(lambda: _NoGrad())})()


class _NoGrad:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


lb.model = FakeModel([2.0, -1.0, 0.0])  # go_back=2.0, wait=-1.0, task_done=0.0
d = lb.decide("state", ["go_back", "wait", "task_done"], {})
# softmax([2,-1,0], T=1): e^2/e^2=1? m=2 → exps: 1, e^-3, e^-2 → sum≈1.1353 → conf(go_back)≈0.881
assert abs(d["scores"]["go_back"] - (1 / (1 + math.exp(-3) + math.exp(-2)))) < 1e-4, d  # scores 保留 4 位
assert abs(sum(d["scores"].values()) - 1.0) < 1e-6
assert d["scores"]["wait"] > 1e-9, "负 logits 被 clamp 失真"
passed.append("3 LocalLogits softmax 归一且负值不 clamp")

# ---------- 4) 分辨率自适应 scaled_tap / swipe_up ----------
class FakeAdb(br.Adb):
    """继承真 Adb 以获得 scaled_tap/screen_size，仅重写 IO 层。"""
    def __init__(self, wm_out):
        super().__init__("fake", "adb", log)
        self.wm_out = wm_out
        self.taps = []
        self.swipes = []

    def shell(self, cmd, **kw):
        return self.wm_out

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, x1, y1, x2, y2, ms):
        self.swipes.append((x1, y1, x2, y2, ms))


a2346 = FakeAdb("Physical size: 1080x1920\nOverride size: 1080x2346")
a2346.scaled_tap(102, 175)
a2346.scaled_tap(540, 649)
assert a2346.taps == [(102, 175), (540, 649)], a2346.taps

a720 = FakeAdb("Physical size: 720x1280\nOverride size: 720x1600")
a720.scaled_tap(102, 175)
a720.scaled_tap(540, 649)
assert a720.taps == [(102 * 720 // 1080, 175 * 1600 // 2346),
                     (540 * 720 // 1080, 649 * 1600 // 2346)], a720.taps

human = br.Human({"delays": {"click": [0, 0], "page_load": [0, 0]}, "human": {"zoneout_prob": 0}}, log)
human.swipe_up(a720)
# 起点=自适应默认(400,955)±抖动；y 单调递减（多段滑动，末段落点带 ±180 抖动）
x0, y1v, x2v, y2v, _ = a720.swipes[0]
assert abs(x0 - int(720 * 0.556)) <= 30 and abs(y1v - int(1600 * 0.597)) <= 60, a720.swipes
ys = [s[3] for s in a720.swipes]
assert all(ys[i] > ys[i + 1] for i in range(len(ys) - 1)), a720.swipes
passed.append("4 scaled_tap/swipe_up 按 wm size 等比换算")

# ---------- 5) ensure_home：资料页 BACK 恢复 / 未知态冷启动 ----------
class NavFakeAdb(FakeAdb):
    """dump 返回预设 xml 序列；记录 key/stop/start 调用。"""
    def __init__(self, screens, acts=None):
        super().__init__("Override size: 1080x2346")
        self.screens = list(screens)
        self.last = ""
        self.acts = list(acts or [])
        self.keys = []
        self.stopped = 0
        self.started = 0

    def dump(self):
        if self.screens:
            self.last = self.screens.pop(0)
        return self.last

    def current_activity(self):
        return self.acts.pop(0) if self.acts else "com.microsoft.bing/.MainSapphireActivity"

    def key(self, code):
        self.keys.append(code)

    def stop_bing(self):
        self.stopped += 1

    def start_bing(self):
        self.started += 1

    def device_online(self):
        return True


XML_HOME = ('<hierarchy><node resource-id="com.microsoft.bing:id/sa_search_box" '
            'text="" bounds="[48,636][1032,828]" clickable="true"/></hierarchy>')
XML_PROFILE = ('<hierarchy><node resource-id="com.microsoft.bing:id/sa_profile_rewards_root" '
               'text="" bounds="[48,504][1032,794]" clickable="true"/></hierarchy>')

# 场景A: 停在资料页 → BACK 一次 → 首页
fa = NavFakeAdb([XML_PROFILE, XML_HOME])
assert br.ensure_home(fa, human, log) is True
assert fa.keys == [br.KEY_BACK] and fa.stopped == 0, (fa.keys, fa.stopped)
passed.append("5a ensure_home 资料页 BACK 恢复")

# 场景B: 一直未知态 → 冷启动后到首页
XML_UNKNOWN = '<hierarchy><node text="hello" bounds="[0,0][100,100]"/></hierarchy>'
XML_RESULT = ('<hierarchy><node resource-id="com.microsoft.bing:id/iab_address_bar_text_view" '
              'text="alpha" bounds="[0,100][1080,200]"/></hierarchy>')
fa2 = NavFakeAdb([XML_UNKNOWN, XML_UNKNOWN, XML_HOME])
assert br.ensure_home(fa2, human, log) is True
assert fa2.stopped == 2 and fa2.started == 2, (fa2.stopped, fa2.started)
passed.append("5b ensure_home 未知态冷启动恢复")

# 场景C: 永远无搜索框 → False（不再死锁成异常）
fa3 = NavFakeAdb([XML_UNKNOWN] * 10)
assert br.ensure_home(fa3, human, log) is False
passed.append("5c ensure_home 恢复失败返回 False")

# ---------- 6) task_search：校验点后从资料页恢复继续搜索（自锁修复） ----------
calls = {"n": 0}
words5 = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]


class SearchFakeAdb(NavFakeAdb):
    """模拟完整搜索轮回：首页→(输词回车)→结果页×10→BACK→首页；校验点时是资料页。"""
    def __init__(self):
        super().__init__([])
        self.inputs = []
        self.pending_profile = False
        self.result_dumps = 0  # >0 时后续 dump 返回结果页

    def dump(self):
        if self.result_dumps > 0:
            self.result_dumps -= 1
            return XML_RESULT
        if self.pending_profile:  # 校验点 read_points 走到的资料页
            self.pending_profile = False
            return XML_PROFILE
        return XML_HOME

    def shell(self, cmd, **kw):
        if cmd.startswith("input text"):
            self.inputs.append(cmd)
        return ""

    def key(self, code):
        self.keys.append(code)
        if code == br.KEY_ENTER:
            self.result_dumps = 10  # 回车后进入结果页
        if code == br.KEY_BACK:
            self.result_dumps = 0  # 返回键 → 回首页

    def current_activity(self):
        return "com.microsoft.bing/.MainSapphireActivity"


fa4 = SearchFakeAdb()
fa4.pending_profile = True  # 复现致命bug1: 主流程 read_points 后 App 停在资料页 tab
ctx4 = {"adb": fa4, "human": human, "log": log, "jev": br.Jev({"jev": {"backend": "off"}}, log),
        "over_deadline": lambda: False}
# read_points 校验点会把 pending_profile 置位：手动在 done%5==0 时触发
orig_read_points = br.read_points


def fake_read_points(adb, human_, log_):
    adb.pending_profile = True
    return {"daily": "13/120", "total": 10169, "streak": "95 天"}


br.read_points = fake_read_points
status = br.task_search(ctx4, 6)  # 6 个词 → 触发一次 done%5==0 校验点
br.read_points = orig_read_points
assert status == "done" and len(fa4.inputs) == 6, (status, fa4.inputs)
assert fa4.pending_profile is False, "校验点后未回到首页继续（自锁仍在）"
passed.append("6 task_search 校验点后恢复首页并完成全部 6 次搜索(自锁修复)")

# ---------- 7) task_quiz 待做卡路径（回归: 修复 tried 未初始化 NameError） ----------
XML_CARD_PENDING = ('<hierarchy>'
                    '<node resource-id="com.microsoft.bing:id/sa_profile_rewards_root" text="" '
                    'bounds="[48,504][1032,794]" clickable="true"/>'
                    '<node content-desc="Vengeance Unleashed, 赚取 10 积分" '
                    'bounds="[48,1200][1032,1400]" clickable="true"/></hierarchy>')
XML_CARD_DONE = ('<hierarchy>'
                 '<node resource-id="com.microsoft.bing:id/sa_profile_rewards_root" text="" '
                 'bounds="[48,504][1032,794]" clickable="true"/>'
                 '<node content-desc="Melbourne Buzz, 已赚取的 10 积分" '
                 'bounds="[48,1200][1032,1400]" clickable="true"/></hierarchy>')

human0 = br.Human({"delays": {"click": [0, 0], "page_load": [0, 0], "dwell_quiz": [0, 0],
                              "dwell_activity": [0, 0]},
                   "human": {"zoneout_prob": 0}}, log)


class RewardsFakeAdb(br.Adb):
    """dump 按序列返回（末尾重复最后一帧）；记录 tap 的节点 label。"""
    def __init__(self, frames):
        super().__init__("fake", "adb", log)
        self.frames = list(frames)
        self.tapped = []

    def shell(self, cmd, **kw):
        return "Override size: 1080x2346"

    def dump(self):
        if self.frames:
            self.last = self.frames.pop(0)
        return self.last

    def current_activity(self):
        return "com.microsoft.sapphire.runtime.templates.TemplateActivity"

    def tap(self, x, y):
        self.tapped.append((x, y))


class RecordingHuman(br.Human):
    def __init__(self, adb_ref):
        super().__init__({"delays": {"click": [0, 0], "page_load": [0, 0],
                                     "dwell_quiz": [0, 0], "dwell_activity": [0, 0]},
                          "human": {"zoneout_prob": 0}}, log)
        self.adb_ref = adb_ref

    def tap(self, adb, node):
        self.adb_ref.tapped.append(node.label)


fa5 = RewardsFakeAdb([XML_CARD_PENDING, XML_CARD_PENDING,  # goto_rewards_entry 两次
                      XML_CARD_PENDING,                    # round1 scan
                      XML_CARD_DONE])                      # round2 scan(已赚取→skipped)
rh = RecordingHuman(fa5)
ctx5 = {"adb": fa5, "human": rh, "log": log,
        "jev": br.Jev({"jev": {"backend": "off"}}, log),
        "over_deadline": lambda: False}
status = br.task_quiz(ctx5)  # 修复前此处抛 NameError: tried
assert status in ("done", "skipped"), status
assert any("赚取 10 积分" in t for t in fa5.tapped), fa5.tapped
passed.append("7 task_quiz 待做卡路径无 NameError(修复 tried)")

# ---------- 8) task_daily_activities 候选优先 Day 卡、排除"已赚取" ----------
RW_ROOT = ('<node resource-id="com.microsoft.bing:id/sa_profile_rewards_root" text="" '
           'bounds="[48,504][1032,794]" clickable="true"/>')
XML_ACT1 = ('<hierarchy>' + RW_ROOT +
            '<node text="每日活动" bounds="[48,300][1032,420]" clickable="true"/>'
            '<node content-desc="News card 赚取 10 积分" bounds="[48,500][1032,700]" clickable="true"/>'
            '<node content-desc="Day 2 赚取 30 积分" bounds="[48,800][1032,1000]" clickable="true"/></hierarchy>')
XML_ACT2 = ('<hierarchy>' + RW_ROOT +
            '<node text="每日活动" bounds="[48,300][1032,420]" clickable="true"/>'
            '<node content-desc="Melbourne, 已赚取的 10 积分" bounds="[48,500][1032,700]" clickable="true"/></hierarchy>')

# goto 消耗 2 帧(进 rewards 页确认)；round1: scroll_find+候选 dump 各 1 帧 → 开 Day2 卡；
# round2: scroll_find+候选 dump 各 1 帧 → 仅剩"已赚取" → break
fa6 = RewardsFakeAdb([XML_ACT1, XML_ACT1,
                      XML_ACT1, XML_ACT1,
                      XML_ACT2, XML_ACT2])
rh6 = RecordingHuman(fa6)
ctx6 = {"adb": fa6, "human": rh6, "log": log,
        "jev": br.Jev({"jev": {"backend": "off"}}, log),
        "over_deadline": lambda: False}
status6 = br.task_daily_activities(ctx6)
assert status6 == "done", status6
day_taps = [t for t in fa6.tapped if "Day" in t]
assert day_taps and "Day 2" in day_taps[0], "未优先点 Day 卡: %r" % fa6.tapped
assert not any("已赚取" in t for t in fa6.tapped), "点开了已完成卡: %r" % fa6.tapped
passed.append("8 daily_activities 优先 Day 卡且排除已赚取")

print("\n".join("PASS " + p for p in passed))
print("ALL_UNIT_TESTS_OK")
