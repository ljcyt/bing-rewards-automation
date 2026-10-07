#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bing Rewards 云手机每日任务自动化（纯 adb + Python，无必装第三方依赖）

用法:
    python bing_rewards.py                      # 正式跑（读 config.json）
    python bing_rewards.py --dry-run            # 连接/dump/列出任务+前置链路模拟，不执行任务动作
    python bing_rewards.py --max-searches 20    # 覆盖搜索次数上限
    python bing_rewards.py --config my.json     # 指定配置文件

退出码: 0=全部成功  1=部分任务失败  2=设备/App 层面失败
"""

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 常量（真机实测锚点）
BING_PKG = "com.microsoft.bing"
BING_MAIN_ACTIVITY = f"{BING_PKG}/com.microsoft.sapphire.app.main.SapphireMainActivity"
# 已验证 resource-id（Bing 32.6.2110003561）
ID_PROFILE_BUTTON = "sa_profile_button"
ID_REWARDS_ROOT = "sa_profile_rewards_root"
ID_TOTAL_POINTS = "sa_profile_my_rewards_points"
ID_DAILY_POINTS = "sa_profile_daily_points"
ID_STREAK = "sa_profile_daily_streak"
ID_SEARCH_BOX = "sa_search_box"
ID_HP_SEARCH_BOX = "sa_hp_header_search_box"
ID_RESULT_BAR = "iab_address_bar_text_view"
ID_BACK = "sa_template_header_action_back"

# 硬禁区：任何候选动作文本命中即一票否决（Rewards 页礼品卡兑换轮播 / 底部兑换入口）
FORBIDDEN_KEYWORDS = ["兑换", "redeem", "提现", "订单历史", "Rewards网站", "rewa rd site"]

# 弹窗扫描关键词 + 错误弹窗正则
POPUP_BUTTON_WORDS = ["同意", "接受", "允许", "知道了", "关闭", "取消", "Not now", "No thanks", "OK"]
ERROR_POPUP_RE = re.compile(r"错误.*客户支持|发生错误")

KEY_ENTER = 66
KEY_BACK = 4


# ---------------------------------------------------------------- 日志
class Logger:
    def __init__(self, log_dir, dry=False):
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, "run_%s.log" % datetime.now().strftime("%Y-%m-%d"))
        self.dry = dry

    def __call__(self, msg, stdout=True):
        line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        if stdout:
            print(line, flush=True)


# ---------------------------------------------------------------- adb 封装
class AdbError(Exception):
    pass


class Adb:
    def __init__(self, serial, adb_path, log):
        self.serial = serial
        self.adb = adb_path
        self.log = log

    def _run(self, args, timeout=20, check=True):
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += args
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise AdbError("adb 执行失败: %s (%s)" % (" ".join(cmd), e))
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        if check and p.returncode != 0:
            raise AdbError("adb 返回码 %d: %s | %s" % (p.returncode, out.strip(), err.strip()))
        return out

    def device_online(self):
        out = self._run(["devices"], check=False)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == self.serial and parts[1] == "device":
                return True
        return False

    def shell(self, cmd, timeout=25, check=True):
        # 整条命令作为单个 shell 字符串：防 MSYS/Git Bash 对 /sdcard 的路径转换
        return self._run(["shell", cmd], timeout=timeout, check=check)

    def tap(self, x, y):
        self.shell("input tap %d %d" % (int(x), int(y)))

    def swipe(self, x1, y1, x2, y2, ms=400):
        self.shell("input swipe %d %d %d %d %d" % (x1, y1, x2, y2, ms))

    def key(self, code):
        self.shell("input keyevent %d" % code)

    def start_bing(self):
        # 必须用 am start 指定 Activity；monkey 在某些前台占用时静默失败(exit 251)
        self.shell("am start -n %s" % BING_MAIN_ACTIVITY, timeout=30)

    def stop_bing(self):
        self.shell("am force-stop %s" % BING_PKG, check=False)

    def current_activity(self):
        out = self.shell("dumpsys activity activities", check=False, timeout=20)
        m = re.search(r"topResumedActivity=.*?\{[^}]*\s(\S+)\s", out) or \
            re.search(r"mResumedActivity=.*?\{[^}]*\s(\S+)\s", out) or \
            re.search(r"ResumedActivity:.*?\{[^}]*\s(\S+)\s", out)
        return m.group(1) if m else "unknown"

    def bing_version(self):
        out = self.shell("dumpsys package %s" % BING_PKG, check=False, timeout=20)
        m = re.search(r"versionName=([\w.]+)", out)
        return m.group(1) if m else "unknown"

    def screen_size(self):
        """分辨率自适应：优先 Override size（uiautomator bounds 所在坐标系），缺省按真机基线 1080x2346。"""
        if getattr(self, "_size", None):
            return self._size
        out = self.shell("wm size", check=False, timeout=15)
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or \
            re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        self._size = (int(m.group(1)), int(m.group(2))) if m else (1080, 2346)
        self.log("  [device] 屏幕坐标系: %dx%d" % self._size)
        return self._size

    def scaled_tap(self, x, y):
        """把 1080x2346 基线坐标（真机实测 HARD_FALLBACK 坐标）按实际分辨率等比换算后点击。"""
        W, H = self.screen_size()
        self.tap(x * W // 1080, y * H // 2346)

    def dump(self):
        """uiautomator dump → 返回原始 XML 字符串；失败重试 3 次。"""
        last_err = None
        for _ in range(3):
            out = self.shell("uiautomator dump /sdcard/ui.xml && cat /sdcard/ui.xml",
                             timeout=40, check=False)
            if "<hierarchy" in out:
                self.shell("rm /sdcard/ui.xml", check=False)
                return out[out.index("<hierarchy"):]
            last_err = out.strip()[:200]
            time.sleep(1.5)
        self.shell("rm /sdcard/ui.xml", check=False)
        raise AdbError("uiautomator dump 失败: %s" % last_err)


# ---------------------------------------------------------------- UI 节点解析
def parse_bounds(s):
    m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", s or "")
    if not m:
        return (0, 0, 0, 0)
    return tuple(int(v) for v in m.groups())


class Node:
    __slots__ = ("rid", "text", "desc", "bounds", "clickable", "checked", "cls", "parent")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def real(self):
        x1, y1, x2, y2 = self.bounds
        return x2 > 0 and y2 > 0

    @property
    def center(self):
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def label(self):
        return self.text or self.desc or self.rid or self.cls or ""

    def all_text(self):
        return "%s | %s | %s" % (self.text, self.desc, self.rid)


def parse_dump(xml_str):
    nodes = []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        raise AdbError("XML 解析失败: %s" % e)

    def build(el, parent):
        node = Node(
            rid=el.get("resource-id", "").split("/")[-1],
            text=el.get("text", ""),
            desc=el.get("content-desc", ""),
            bounds=parse_bounds(el.get("bounds", "")),
            clickable=el.get("clickable") == "true",
            checked=el.get("checked") == "true",
            cls=el.get("class", ""),
            parent=parent,
        )
        nodes.append(node)
        for child in el.findall("node"):
            build(child, node)

    for el in root.findall("node"):
        build(el, None)
    if not nodes:  # 非常规嵌套（hierarchy 下非直接 node）→ 退回扁平解析（无父链）
        for el in root.iter("node"):
            nodes.append(Node(
                rid=el.get("resource-id", "").split("/")[-1],
                text=el.get("text", ""),
                desc=el.get("content-desc", ""),
                bounds=parse_bounds(el.get("bounds", "")),
                clickable=el.get("clickable") == "true",
                checked=el.get("checked") == "true",
                cls=el.get("class", ""),
                parent=None,
            ))
    return nodes


class Screen:
    """一次 dump 的解析视图"""

    def __init__(self, xml_str, activity=""):
        self.xml = xml_str
        self.nodes = parse_dump(xml_str)
        self.activity = activity

    def by_id(self, rid, require_real=False):
        for n in self.nodes:
            if n.rid == rid and (n.real or not require_real):
                return n
        return None

    def by_text(self, kw, require_real=False, regex=False):
        for n in self.nodes:
            hay = n.text + " " + n.desc
            hit = re.search(kw, hay) if regex else (kw in hay)
            if hit and (n.real or not require_real):
                return n
        return None

    def all_by_text(self, kw, require_real=True, regex=False):
        res = []
        for n in self.nodes:
            hay = n.text + " " + n.desc
            hit = re.search(kw, hay) if regex else (kw in hay)
            if hit and (n.real or not require_real):
                res.append(n)
        return res

    def anchor_names(self):
        ids = set()
        for n in self.nodes:
            if n.rid:
                ids.add(n.rid)
        return sorted(ids)

    def summary(self):
        return {
            "activity": self.activity,
            "anchors_found": self.anchor_names(),
            "clickable_texts": [n.label[:40] for n in self.nodes if n.clickable and n.real][:20],
            "desc_cards": [n.desc[:60] for n in self.nodes if n.desc and n.real][:20],
        }


# ---------------------------------------------------------------- 拟人化
class Human:
    def __init__(self, cfg, log):
        d = cfg.get("delays", {})
        self.click = tuple(d.get("click", [1.5, 4.0]))
        self.page = tuple(d.get("page_load", [2.0, 6.0]))
        self.between = tuple(d.get("between_tasks", [20, 90]))
        self.dwell_search = tuple(d.get("dwell_search", [6, 14]))
        self.dwell_activity = tuple(d.get("dwell_activity", [15, 40]))
        self.dwell_read = tuple(d.get("dwell_read", [20, 50]))
        self.dwell_quiz = tuple(d.get("dwell_quiz", [30, 60]))
        h = cfg.get("human", {})
        self.zoneout_prob = h.get("zoneout_prob", 0.07)
        self.tap_jitter = h.get("tap_jitter_px", 30)
        self.log = log

    def sleep(self, lo, hi, tag=""):
        t = random.uniform(lo, hi)
        if random.random() < self.zoneout_prob:
            t += random.uniform(20, 40)  # 走神长停顿
            self.log("  [human] 走神停顿 %.1fs (%s)" % (t, tag))
        time.sleep(t)

    def tap(self, adb, node):
        x, y = node.center
        x += random.randint(-self.tap_jitter, self.tap_jitter)
        y += random.randint(-self.tap_jitter, self.tap_jitter)
        adb.tap(x, y)
        self.sleep(*self.click, tag="after_tap")

    def swipe_up(self, adb, x=None, y1=None, y2=None):
        # 分辨率自适应：默认按屏幕尺寸比例取点（基线 1080x2346 下等价于 600/1400/600）
        W, H = adb.screen_size()
        x = int(W * 0.556) if x is None else x
        y1 = int(H * 0.597) if y1 is None else y1
        y2 = int(H * 0.256) if y2 is None else y2
        # 分 2-4 段带速度抖动
        seg = random.randint(2, 4)
        cur = y1
        step = (y1 - y2) // seg
        for _ in range(seg):
            nxt = max(y2, cur - step + random.randint(-60, 60))
            adb.swipe(x + random.randint(-30, 30), cur, x, nxt, random.randint(280, 520))
            cur = nxt
            time.sleep(random.uniform(0.25, 0.6))


# ---------------------------------------------------------------- Jev 决策模块（单步判别，System 1）
# 输出原语仅三种: choice / score / noul。不做多步规划、不生成自然语言。
PAGE_TYPES = ["home", "profile", "rewards", "search_box", "search_result",
              "article", "quiz", "popup", "unknown"]

RULE_TABLE = {
    # page_type: (条件锚点, 动作)  顺序即优先级
    "popup": [("同意|接受|允许|知道了|Not now|No thanks|OK", "close_popup"),
              ("发生错误|错误.*客户支持", "close_popup")],
    "home": [(ID_SEARCH_BOX, "open_search_task"),
             (ID_PROFILE_BUTTON, "open_rewards_page")],
    "search_result": [("iab_address_bar_text_view", "wait")],
    "rewards": [("阅读以赚取", "open_read_task"),
                ("每日活动|Day\\s*\\d", "open_daily_task"),
                ("赚取.*积分", "open_quiz_card")],
    "profile": [(ID_REWARDS_ROOT, "open_rewards_page")],
    "search_box": [(None, "execute_search")],
    "article": [(None, "wait")],
    "quiz": [(None, "wait")],
    "unknown": [(None, "go_back")],
}


def classify_page(screen):
    """第一级分类：锚点特征 → 离散页面类型。"""
    if ERROR_POPUP_RE.search(screen.xml):
        return "popup"
    ids = screen.anchor_names()
    txt = screen.xml
    if ID_RESULT_BAR in ids or "BrowserActivity" in screen.activity:
        return "search_result"
    if ID_SEARCH_BOX in ids or ID_HP_SEARCH_BOX in ids:
        return "home"
    if ID_REWARDS_ROOT in ids:
        return "profile"
    if "兑换积分" in txt or "订单历史" in txt or ID_STREAK in ids:
        return "rewards"
    if "阅读以赚取" in txt:
        return "rewards"
    if re.search(r"quiz|Quiz", txt):
        return "quiz"
    return "unknown"


class TypeSafeApiBackend:
    """后端 (a): TypeSafe AI 官方 System One API（jev-latest）。
    Endpoint/请求结构经 TrueFoundry 官方文档证实（truefoundry.com/docs/ai-gateway/jev）:
      POST https://api.typesafe.ai/v1/systemone  Authorization: Bearer <key>
      body: {"model": "jev-latest", "state": ..., "questions": {name:{type,instructions,criteria}}}
      resp: {"model", "answers": {name: {choice|score|noul 结果, confidence}}, "usage"}
    支持 api_keys 主备列表：401/403/402/429 或额度类错误时按序轮换下一个 key，
    同一轮决策最多轮完全部 key；全部失效抛异常 → 本步降级下一级后端（规则引擎）并记录。
    """

    KEY_ROTATE_STATUS = {401, 402, 403, 429}
    KEY_ROTATE_WORDS = ("quota", "credit", "insufficient", "exceeded", "额度", "余额")

    def __init__(self, jev_cfg, log):
        self.endpoint = jev_cfg.get("endpoint", "https://api.typesafe.ai/v1/systemone")
        keys = list(jev_cfg.get("api_keys") or [])
        if jev_cfg.get("api_key") and jev_cfg["api_key"] not in keys:
            keys.append(jev_cfg["api_key"])
        # key 规范化：官方鉴权要求 Bearer apikey_<hex_hex> 完整格式；
        # config 里存裸 hex_hex 也可，使用前自动补 apikey_ 前缀（裸 key 直发会 401）
        self.api_keys = [("apikey_" + k if not k.startswith("apikey_") else k)
                         for k in keys if k]
        self.key_index = 0
        self.model = jev_cfg.get("model", "jev-latest")
        self.timeout = jev_cfg.get("timeout_s", 8)
        self.log = log
        self.ok = bool(self.api_keys)
        if self.ok:
            self.log("  [jev/api] endpoint=%s model=%s keys=%d(主+备)"
                     % (self.endpoint, self.model, len(self.api_keys)))

    def _is_key_fatal(self, e):
        code = getattr(e, "code", None)
        if code in self.KEY_ROTATE_STATUS:
            return True
        msg = str(e).lower()
        return any(w in msg for w in self.KEY_ROTATE_WORDS)

    def _request_once(self, body):
        key = self.api_keys[self.key_index]
        req = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer %s" % key})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        self.log("  [jev/api] key#%d %.0fms" % (self.key_index, (time.time() - t0) * 1000))
        return data

    def decide(self, state, candidates, ctx):
        questions = {"action": {
            "type": "choice",
            "instructions": "当前是 Bing Rewards 自动化脚本的单步决策，"
                            "根据屏幕状态从候选动作中选择唯一一个最合适的。",
            "criteria": {a: ACTION_DESC.get(a, a) for a in candidates},
        }}
        body = json.dumps({"state": state, "model": self.model, "questions": questions}).encode()
        data = None
        last = None
        for _ in range(len(self.api_keys)):  # 一轮决策最多轮完全部 key
            try:
                data = self._request_once(body)
                break
            except urllib.error.HTTPError as e:
                last = e
                if self._is_key_fatal(e):
                    self.log("  [jev/api] key#%d 失效(HTTP %s) → 轮换下一个 key"
                             % (self.key_index, e.code))
                    self.key_index = (self.key_index + 1) % len(self.api_keys)
                    continue
                raise  # 非 key 类错误（超时/5xx/参数）→ 直接降级下一级后端
            except Exception as e:
                last = e
                raise
        if data is None:
            raise AdbError("TypeSafe API 全部 %d 个 key 失效: %s" % (len(self.api_keys), last))
        ans = data.get("answers", {}).get("action", {})
        action, conf = ans.get("choice"), float(ans.get("confidence", 0))
        if action not in candidates:
            raise ValueError("API 返回未知动作 %r" % action)
        scores = {a: (conf if a == action else round((1 - conf) / max(1, len(candidates) - 1), 3))
                  for a in candidates}
        self.log("  [jev/api] action=%s conf=%.2f" % (action, conf))
        return {"primitive": "choice", "action": action, "confidence": conf,
                "backend": "api", "scores": scores, "noul": False}


class LocalLogitsBackend:
    """后端 (b): 本地小模型 logits 投影（Jev 复现路径）。
    transformers/torch 为可选依赖，缺失即自动禁用。"""

    def __init__(self, model_name, log):
        self.ok = False
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self.torch = torch
            self.tok = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForCausalLM.from_pretrained(model_name)
            self.temperature = 1.5  # T>1 压平过度自信的分布
            self.ok = True
            log("  [jev/local] 已加载 %s" % model_name)
        except Exception as e:
            log("  [jev/local] 禁用（%s）" % e)

    def decide(self, state, candidates, ctx):
        import math
        prompt = ("Screen: %s\nChoose one action:\n" % state[:800]) + \
                 "\n".join("- %s" % a for a in candidates) + "\nAction:"
        ids = self.tok(prompt, return_tensors="pt")
        with self.torch.no_grad():
            logits = self.model(**ids).logits[0, -1, :]
        # 各候选动作首 token 的原始 logits → 带温度的 softmax（负 logits 不会被 clamp，分布不失真）
        raw = {}
        for a in candidates:
            tok_ids = self.tok.encode(" " + a)
            if not tok_ids:
                raw[a] = float("-inf")
                continue
            raw[a] = float(logits[tok_ids[0]].item())
        T = self.temperature
        m = max(raw.values())
        if m == float("-inf"):
            probs = {a: 1.0 / len(candidates) for a in candidates}
        else:
            exps = {a: math.exp((v - m) / T) for a, v in raw.items()}
            s = sum(exps.values()) or 1e-9
            probs = {a: v / s for a, v in exps.items()}
        action = max(probs, key=probs.get)
        conf = probs[action]
        return {"primitive": "choice", "action": action, "confidence": conf,
                "backend": "local_logits", "scores": {a: round(v, 4) for a, v in probs.items()},
                "noul": False}


class RuleEngine:
    """后端 (c): 确定性规则引擎，永远可用，硬兜底。"""

    def __init__(self, log):
        self.log = log

    def decide(self, state, candidates, ctx):
        page = ctx.get("page_type", "unknown")
        anchors = ctx.get("anchors", [])
        xml = ctx.get("xml", "")
        for anchor, action in RULE_TABLE.get(page, RULE_TABLE["unknown"]):
            if anchor is None or re.search(anchor, xml) or anchor in anchors:
                if action in candidates:
                    self.log("  [jev/rule] page=%s anchor=%s -> %s" % (page, anchor, action))
                    return {"primitive": "choice", "action": action, "confidence": 0.99,
                            "backend": "rule_engine", "scores": {}, "noul": False,
                            "reason_tag": "RULE_FALLBACK"}
        self.log("  [jev/rule] page=%s 无可执行动作 -> noul" % page)
        return {"primitive": "noul", "noul": True, "confidence": 0.82,
                "backend": "rule_engine", "action": None, "scores": {},
                "reason_tag": "no_anchor_match"}


ACTION_DESC = {
    "open_search_task": "点击首页搜索框开始一次搜索",
    "open_rewards_page": "点击头像/积分卡进入 Rewards 页",
    "execute_search": "提交搜索词并回车",
    "go_back": "按返回键返回上一页",
    "wait": "原地等待页面加载/计分",
    "task_done": "当前任务已完成",
    "close_popup": "关闭当前弹窗",
    "open_daily_task": "打开每日活动卡",
    "open_read_task": "打开阅读赚分卡",
    "open_read_article": "点击新闻流文章卡进入文章页阅读",
    "open_quiz_card": "打开轮播区 Quiz/资讯活动卡",
}


class Jev:
    """置信度门控: >=0.90 自动执行; 0.60-0.90 复核锚点后保守执行; <0.60 规则硬兜底。"""

    def __init__(self, cfg, log):
        jev = cfg.get("jev", {})
        self.mode = jev.get("backend", "off")
        self.log = log
        self.api = TypeSafeApiBackend(jev, log) if self.mode == "api" else None
        self.local = None
        if self.mode == "local" and cfg.get("local_model", {}).get("enabled_auto", True):
            self.local = LocalLogitsBackend(cfg.get("local_model", {}).get("name", "Qwen/Qwen2.5-0.5B"), log)
        self.rule = RuleEngine(log)
        self.fallback_counts = {"api": 0, "local_logits": 0, "rule_engine": 0}
        self.confs = []

    def _try(self, backend, state, candidates, ctx):
        try:
            return backend.decide(state, candidates, ctx)
        except Exception as e:
            self.log("  [jev] 后端 %s 失败: %s → 降级 (DECISION_BACKEND_FALLBACK)"
                     % (type(backend).__name__, e))
            return None

    def decide(self, screen, candidates, ctx=None):
        ctx = ctx or {}
        ctx.setdefault("page_type", classify_page(screen))
        ctx.setdefault("anchors", screen.anchor_names())
        ctx.setdefault("xml", screen.xml)
        state = json.dumps({"page": ctx["page_type"], "activity": screen.activity,
                            "summary": screen.summary()}, ensure_ascii=False)
        order = []
        if self.mode == "api" and self.api and self.api.ok:
            order = [self.api, self.rule]
            if self.local and self.local.ok:
                order = [self.api, self.local, self.rule]
        elif self.mode == "local":
            order = ([self.local] if self.local and self.local.ok else []) + [self.rule]
        else:  # off
            order = [self.rule]
        decision = None
        for b in order:
            decision = self._try(b, state, candidates, ctx)
            if decision:
                self.fallback_counts[decision["backend"]] = self.fallback_counts.get(decision["backend"], 0) + 1
                break
        if not decision:  # 全部失败 → 内联最保守规则
            decision = {"primitive": "noul", "noul": True, "confidence": 0.0,
                        "backend": "none", "action": None, "scores": {}}
        self.confs.append(round(decision.get("confidence", 0), 3))
        self.log("  [jev] decision=%s" % json.dumps(decision, ensure_ascii=False))
        return decision

    def gate(self, decision, screen, required_anchors=()):
        """门控执行判定。返回 True=允许执行。"""
        if decision.get("primitive") == "noul" or not decision.get("action"):
            return False
        conf = float(decision.get("confidence", 0))
        if conf >= 0.90:
            return True
        if conf >= 0.60:
            # 保守执行：复核锚点仍在
            ok = all(screen.by_id(a, require_real=False) for a in required_anchors)
            if not ok:
                self.log("  [gate] 保守执行档锚点消失 → 按 unknown 重判")
            return ok
        self.log("  [gate] conf<0.60 → 交规则引擎硬兜底，禁止直接执行")
        return False


# ---------------------------------------------------------------- 安全线（最后防线，不信任任何决策输出）
def forbidden_hit(node):
    hay = node.all_text().lower()
    return any(k.lower() in hay for k in FORBIDDEN_KEYWORDS)


def safe_tap(human, adb, node, log):
    if node is None:
        return False
    if forbidden_hit(node):
        log("  [SAFE] REFUSED_FORBIDDEN_ZONE: %r" % node.label[:60])
        return False
    human.tap(adb, node)
    return True


# ---------------------------------------------------------------- 弹窗处置
def handle_popup(screen, human, adb, log):
    """命中弹窗按钮词或错误弹窗则处置；返回 True 表示处置过。"""
    if ERROR_POPUP_RE.search(screen.xml):
        log("  [popup] Rewards 加载错误弹窗 → BACK 重进")
        adb.key(KEY_BACK)
        human.sleep(*human.click, tag="popup_back")
        return True
    for w in POPUP_BUTTON_WORDS:
        # ASCII 词（如 OK）用词边界匹配，防误点含 OK 子串的无关可点文本；中文词保持子串匹配
        pat = r"\b%s\b" % re.escape(w) if w.isascii() else re.escape(w)
        n = screen.by_text(pat, require_real=True, regex=True)
        if n and n.clickable:
            if safe_tap(human, adb, n, log):
                log("  [popup] 关闭弹窗按钮 %r" % n.label[:40])
                return True
    return False


# ---------------------------------------------------------------- 积分读取
def parse_points(txt):
    m = re.search(r"[\d,]+", txt or "")
    return int(m.group().replace(",", "")) if m else None


def goto_profile(adb, human, log):
    """回到个人资料页（积分入口卡片所在页），返回该页 Screen 或 None。"""
    act = adb.current_activity()
    if BING_PKG not in act:
        adb.start_bing()
        human.sleep(*human.page, tag="bing_start")
    for attempt in range(3):
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        if screen.by_id(ID_REWARDS_ROOT):
            return screen
        n = screen.by_id(ID_PROFILE_BUTTON, require_real=True)
        if n:
            safe_tap(human, adb, n, log)
        else:
            log("  [nav] HARD_FALLBACK 进头像（基线坐标 102,175 按分辨率换算）")
            adb.scaled_tap(102, 175)
        human.sleep(*human.page, tag="profile")
        screen = Screen(adb.dump(), adb.current_activity())
        if screen.by_id(ID_REWARDS_ROOT):
            return screen
    log("  [nav] 未能确认个人资料页积分卡")
    return None


def read_points(adb, human, log):
    """在个人资料页读总积分/今日积分/连续天数（入口卡片锚点）。返回 dict 或 None。"""
    screen = goto_profile(adb, human, log)
    if screen is None:
        return None
    res = {}
    n = screen.by_id(ID_TOTAL_POINTS)
    if n:
        res["total"] = parse_points(n.text)
    n = screen.by_id(ID_DAILY_POINTS)
    if n:
        res["daily"] = n.text.strip()
    n = screen.by_id(ID_STREAK)
    if n:
        res["streak"] = n.text.strip()
    log("  [points] %s" % res if res else "  [points] 未读到积分锚点")
    return res or None


def goto_rewards_entry(adb, human, log):
    """从任意状态进入 Rewards 任务页。结构化定位优先，bounds 兜底标 HARD_FALLBACK。
    返回 bool：True=已确认到达（TemplateActivity 或读到积分锚点）。"""
    act = adb.current_activity()
    if BING_PKG not in act:
        log("  [nav] Bing 不在前台(%s) → 先启动" % act)
        adb.start_bing()
        human.sleep(*human.page, tag="bing_start")
    for attempt in range(3):
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        if screen.by_id(ID_REWARDS_ROOT):
            n = screen.by_id(ID_REWARDS_ROOT, require_real=True)
            if n:
                safe_tap(human, adb, n, log)
                human.sleep(*human.page, tag="rewards")
            scr2 = Screen(adb.dump(), adb.current_activity())
            if "TemplateActivity" in scr2.activity or scr2.by_id(ID_TOTAL_POINTS):
                return True
            continue
        n = screen.by_id(ID_PROFILE_BUTTON, require_real=True)
        if n:
            safe_tap(human, adb, n, log)
        else:
            log("  [nav] HARD_FALLBACK 进头像（基线坐标 102,175 按分辨率换算）")
            adb.scaled_tap(102, 175)
        human.sleep(*human.page, tag="profile")
        screen = Screen(adb.dump(), adb.current_activity())
        n = screen.by_id(ID_REWARDS_ROOT, require_real=True)
        if n:
            safe_tap(human, adb, n, log)
            human.sleep(*human.page, tag="rewards")
            scr2 = Screen(adb.dump(), adb.current_activity())
            if "TemplateActivity" in scr2.activity or scr2.by_id(ID_TOTAL_POINTS):
                return True
            continue
        log("  [nav] HARD_FALLBACK 进积分卡（基线坐标 540,649 按分辨率换算）")
        adb.scaled_tap(540, 649)
        human.sleep(*human.page, tag="rewards")
        scr2 = Screen(adb.dump(), adb.current_activity())
        if "TemplateActivity" in scr2.activity or scr2.by_id(ID_TOTAL_POINTS):
            return True
    log("  [nav] 未能确认已进入 Rewards 页")
    return False


def ensure_home(adb, human, log, max_attempts=4):
    """确保回到首页（可见 sa_search_box）。
    恢复顺序：BACK（从积分页/资料页回首页 tab）→ 冷启动（force-stop + am start，必落首页 tab）。
    返回 bool。修复：主流程 read_points / 搜索校验点把 App 留在资料页 tab 后，
    am start 对已前台实例不切 tab，原实现一次 dump 找不到搜索框即 failed（导航死锁）。"""
    for attempt in range(max_attempts):
        if BING_PKG not in adb.current_activity():
            adb.start_bing()
            human.sleep(*human.page, tag="bing_start")
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        if screen.by_id(ID_SEARCH_BOX, require_real=True) or \
                screen.by_id(ID_HP_SEARCH_BOX, require_real=True):
            return True
        on_rewards_like = (screen.by_id(ID_REWARDS_ROOT) or
                           screen.by_id(ID_TOTAL_POINTS) or
                           "TemplateActivity" in screen.activity)
        if on_rewards_like and attempt < 2:
            log("  [nav] 位于积分页/资料页 → BACK 回首页 (attempt %d)" % (attempt + 1))
            adb.key(KEY_BACK)
            human.sleep(*human.page, tag="back_home")
            continue
        log("  [nav] 首页不可见(attempt %d) → 冷启动恢复" % (attempt + 1))
        adb.stop_bing()
        time.sleep(2)
        adb.start_bing()
        human.sleep(*human.page, tag="cold_start")
    screen = Screen(adb.dump(), adb.current_activity())
    return bool(screen.by_id(ID_SEARCH_BOX, require_real=True) or
                screen.by_id(ID_HP_SEARCH_BOX, require_real=True))


# ---------------------------------------------------------------- 任务实现
def task_checkin(ctx):
    """签到：进入 Rewards 页即触发；倒计时文本表示今日已签。
    只在确认到达 Rewards 页时返回 done；导航失败返回 unknown（不报假成功）。"""
    adb, human, log, jev = ctx["adb"], ctx["human"], ctx["log"], ctx["jev"]
    adb.start_bing()
    human.sleep(*human.page, tag="bing_start")
    if not goto_rewards_entry(adb, human, log):
        log("  [checkin] 未能确认进入 Rewards 页 → unknown")
        return "unknown"
    screen = Screen(adb.dump(), adb.current_activity())
    m = re.search(r"(\d+)\s*小时\s*(\d+)\s*分", screen.xml)
    if m:
        log("  [checkin] 检测到倒计时 %s小时%s分 → 今日已签" % m.groups())
        return "done"
    # 已确认在 Rewards 页（TemplateActivity / 积分锚点）——真机实测进入页面即触发当日签到
    log("  [checkin] 已确认在 Rewards 页，未检测到倒计时 → 进入页面即已触发今日签到")
    return "done"


def load_words(path, log):
    try:
        with open(path, encoding="utf-8") as f:
            words = [w.strip() for w in f if w.strip() and w.isascii()]
    except OSError:
        words = ["weather tomorrow", "news today", "best coffee"]
        log("  [search] words.txt 缺失，使用内置 3 词")
    random.shuffle(words)
    return words


def ascii_query(word):
    # input text 不支持中文；空格转 %s；% 原样提交不影响计分（真机实测）
    return word.replace(" ", "%s")


def task_search(ctx, max_searches):
    adb, human, log, jev = ctx["adb"], ctx["human"], ctx["log"], ctx["jev"]
    # 修复导航死锁：主流程 read_points 可能把 App 留在资料页 tab，am start 不切 tab，
    # 必须先经 ensure_home 恢复（BACK/冷启动）到可见 sa_search_box 的首页
    if not ensure_home(adb, human, log):
        log("  [search] 无法回到首页（含搜索框），任务失败")
        return "failed"
    words = load_words(os.path.join(BASE_DIR, "words.txt"), log)
    if len(words) < max_searches:
        words = (words * (max_searches // max(1, len(words)) + 1))[:max_searches]
    words = words[:max_searches]

    done, stall_rounds, last_daily = 0, 0, None
    for w in words:
        if ctx["over_deadline"]():
            log("  [search] 看门狗超时，提前结束")
            break
        # 修复校验点自锁：read_points 校验后 App 停在资料页 tab，每次搜索前强制恢复首页，
        # 不再走 goto_rewards_entry（它见 ID_REWARDS_ROOT 即返回，永远回不到首页）
        if not ensure_home(adb, human, log):
            log("  [search] 无法恢复首页，终止搜索任务（已完成 %d 次）" % done)
            break
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        box = screen.by_id(ID_SEARCH_BOX, require_real=True) or \
            screen.by_id(ID_HP_SEARCH_BOX, require_real=True) or \
            screen.by_text("搜索", require_real=True)
        if not box:
            # 决策模块兜底: home 态候选
            d = jev.decide(screen, ["open_search_task", "go_back", "task_done"])
            if d.get("action") == "task_done":
                break
            continue  # 下一轮 ensure_home 再恢复
        safe_tap(human, adb, box, log)
        human.sleep(*human.click, tag="search_box")
        adb.shell('input text "%s"' % ascii_query(w), timeout=20)
        human.sleep(1.0, 3.0, tag="typing_pause")  # 输入中途停顿
        adb.key(KEY_ENTER)
        # 等 BrowserActivity 计分页
        scored = False
        for _ in range(10):
            time.sleep(1.5)
            scr2 = Screen(adb.dump(), adb.current_activity())
            if scr2.by_id(ID_RESULT_BAR):
                scored = True
                break
        if scored:
            done += 1
            log("  [search] #%d %r → 结果页已计分" % (done, w))
            human.sleep(*human.dwell_search, tag="dwell_search")
        else:
            log("  [search] %r 未见结果页（可能失败/重复）" % w)
            human.sleep(*human.click, tag="retry_gap")
        adb.key(KEY_BACK)
        human.sleep(*human.click, tag="back_to_home")
        # 每 5 次核对积分增量（下一轮循环开头 ensure_home 会从资料页恢复回首页）
        if done and done % 5 == 0:
            pts = read_points(adb, human, log)
            daily = pts.get("daily") if pts else None
            log("  [search] 校验点 daily=%s (上次=%s)" % (daily, last_daily))
            if last_daily is not None and daily is not None and daily == last_daily:
                stall_rounds += 1
                if stall_rounds >= 2:
                    log("  [search] 连续 2 轮无增量 → 停止搜索任务")
                    break
            else:
                stall_rounds = 0
            last_daily = daily
    log("  [search] 完成 %d 次搜索" % done)
    return "done" if done > 0 else "failed"


def _scroll_find(adb, human, log, pattern, max_rounds=6):
    """Rewards 页 RecyclerView 虚拟化：滚动→dump→找真实 bounds 节点。"""
    for _ in range(max_rounds):
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        for n in screen.all_by_text(pattern, require_real=True, regex=True):
            if n.real and (n.clickable or True):
                return screen, n
        human.swipe_up(adb)
        human.sleep(1.0, 2.0, tag="scroll_wait")
    return None, None


def task_daily_activities(ctx):
    adb, human, log, jev = ctx["adb"], ctx["human"], ctx["log"], ctx["jev"]
    goto_rewards_entry(adb, human, log)
    opened = 0
    for round_i in range(8):
        if ctx["over_deadline"]():
            break
        screen, card = _scroll_find(adb, human, log, r"每日活动")
        if not card:
            log("  [activity] 找不到\"每日活动\"板块")
            break
        # 板块存在但当日候选可能不可点：Day 卡缺失或行节点虚拟化 [0,0][0,0]
        # （真机实测：当日剩余活动行"拼图进度/连续/了解详细信息"均虚拟化，无法经 dump 定位点击）
        # 板块附近的未完成 Day 卡：优先 Day\s*\d 节点；排除"已赚取"（轮播区已完成卡）
        # 与禁区词；轮播"赚取 X 积分"卡仅在没有 Day 卡时作兜底（点开无害）
        screen = Screen(adb.dump(), adb.current_activity())
        hits = [n for n in screen.all_by_text(r"赚取|Day\s*\d", require_real=True, regex=True)
                if n.real and not forbidden_hit(n) and "已赚取" not in (n.desc + n.text)]
        day_cands = [n for n in hits if re.search(r"Day\s*\d", n.label)]
        other_cands = [n for n in hits if n not in day_cands]
        cands = day_cands + other_cands
        target = None
        for n in cands:
            d = jev.decide(screen, ["open_daily_task", "go_back"],
                           {"page_type": "rewards"})
            if d.get("action") == "open_daily_task" and jev.gate(d, screen):
                target = n
                break
        if not target:
            log("  [activity] 板块存在但无可见可点候选（Day 卡缺失/已赚取过滤/节点虚拟化）")
            break
        if not safe_tap(human, adb, target, log):
            break
        opened += 1
        log("  [activity] 打开活动卡 %r (%d)" % (target.label[:40], opened))
        human.sleep(*human.dwell_activity, tag="activity_dwell")
        adb.key(KEY_BACK)
        human.sleep(*human.page, tag="back_rewards")
    log("  [activity] 打开 %d 张活动卡" % opened)
    return "done" if opened > 0 else "unknown"


# ---------------------------------------------------------------- 阅读赚分（task_read）
# 阅读任务计分机制（逐篇验证）：
#   路径：头像 → 抽屉 "Microsoft Rewards" → 积分页(TemplateActivity) → 滚到"阅读以赚取"卡
#         → 点卡片可视祖先 → MainSapphireActivity 新闻流 → 逐篇点文章标题阅读 → BACK 回流
#   卡片 content-desc="阅读以赚取, , 已赚取 N 积分(需要 30 积分)" 是唯一可靠进度读取点；
#   卡片是 WebView 节点，自身 bounds=[0,0][0,0]，必须点可视祖先 View 的 bounds 中心。
#   单篇 3 积分，满 30 分 = 10 篇/日；15s 停留（含 2 次滚动）即计分，滚动非必要条件。
READ_CARD_DESC_RE = re.compile(
    r"阅读以赚取.*?已赚取\s*([\d,]+)\s*积分\s*[（(]\s*需要\s*([\d,]+)\s*积分\s*[）)]")
READ_BATCH = 3          # 每批篇数（单篇 3 分，读 3 篇回积分页核一次进度）
READ_FEED_MIN_TITLE = 12  # 新闻流文章标题 content-desc 最短长度（过滤导航/按钮类节点）
READ_AD_TEXTS = ("广告", "广告选项")
READ_PROMO_TEXTS = ("豆包", "Booking")  # 推广卡实测样本


def tapable_ancestor(node, max_up=12):
    """节点 bounds 为 [0,0][0,0]（WebView/虚拟化）时向上找首个有真实 bounds 的祖先。"""
    if node is None:
        return None
    cur, hops = node, 0
    while cur is not None and not cur.real and hops < max_up:
        cur = cur.parent
        hops += 1
    if cur is not None and cur.real:
        return cur
    return node if node.real else None


def _boxes_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _find_read_card(adb, human, log, max_rounds=8):
    """积分页滚动定位"阅读以赚取"卡。返回 (已赚, 需要, 卡节点)；找不到返回 (None, None, None)。"""
    for _ in range(max_rounds):
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        for n in screen.nodes:
            m = READ_CARD_DESC_RE.search(n.desc or "")
            if m:
                earned = int(m.group(1).replace(",", ""))
                need = int(m.group(2).replace(",", ""))
                return earned, need, n
        human.swipe_up(adb)
        human.sleep(1.0, 2.0, tag="read_scroll")
    return None, None, None


def _feed_article_candidates(screen, seen):
    """新闻流文章卡：clickable + content-desc 为标题(>12字) + 无 resource-id + bounds 真实。
    跳过广告卡（desc/文本含"广告"，或与 nativead-river-*-img 节点 bounds 重叠）、
    推广卡（豆包/Booking 等）、禁区词与已读标题。"""
    ad_boxes = [n.bounds for n in screen.nodes if "nativead" in (n.rid or "")]
    cands = []
    for n in screen.nodes:
        if not (n.clickable and n.real and n.desc and not n.rid):
            continue
        title = n.desc.strip()
        if len(title) <= READ_FEED_MIN_TITLE or title in seen:
            continue
        hay = title + " " + (n.text or "")
        if any(m in hay for m in READ_AD_TEXTS) or any(m in hay for m in READ_PROMO_TEXTS):
            continue
        if any(_boxes_overlap(n.bounds, b) for b in ad_boxes):
            continue
        if forbidden_hit(n):
            continue
        cands.append(n)
    return cands


def _read_articles_in_feed(adb, human, log, jev, ctx, seen, max_articles):
    """在新闻流逐篇阅读。返回本批已读篇数。"""
    read = 0
    idle_rounds = 0
    while read < max_articles:
        if ctx["over_deadline"]():
            break
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        cands = _feed_article_candidates(screen, seen)
        if not cands:
            human.swipe_up(adb)  # 下滚换位找新文章（已读文章留在原位不重复点）
            human.sleep(1.0, 2.0, tag="feed_scroll")
            idle_rounds += 1
            if idle_rounds >= 5:
                log("  [read] 新闻流连续 %d 轮滚动后无可读文章卡" % idle_rounds)
                break
            continue
        idle_rounds = 0
        # Jev 决策接入：是否点开文章（API 后端真判别；规则引擎对 article 页返回 wait
        # 不在候选内 → noul → 走下方确定性兜底）
        target = None
        for n in cands[:3]:
            d = jev.decide(screen, ["open_read_article", "go_back"], {"page_type": "article"})
            if d.get("action") == "open_read_article" and jev.gate(d, screen):
                target = n
                break
            if d.get("action") == "go_back" and jev.gate(d, screen):
                log("  [read] Jev 判定 go_back → 结束本批")
                return read
        if target is None:
            target = cands[0]
        title = target.desc.strip()
        seen.add(title)
        if not safe_tap(human, adb, target, log):
            continue
        read += 1
        log("  [read] 第 %d 篇 %r" % (read, title[:40]))
        human.sleep(5.0, 8.0, tag="article_load")  # 实测约 6 秒进入文章页
        # 停留阅读：下限 15s（已验证最短计分档），滚动 2-3 次（滚动非必要，稳妥起见）
        base = random.uniform(15.0, 30.0)
        swipes = random.randint(2, 3)
        seg = base / (swipes + 1)
        for _ in range(swipes):
            human.sleep(seg, seg + 2.0, tag="read_dwell")
            human.swipe_up(adb)
        human.sleep(seg, seg + 2.0, tag="read_dwell")
        adb.key(KEY_BACK)  # 回新闻流
        human.sleep(*human.page, tag="article_back")
    return read


def _back_to_points(adb, human, log, max_attempts=3):
    """新闻流 → 积分页。坑：BACK 在积分页相关界面会先弹资料抽屉，
    需点底部"主页"标签关闭；随后走 goto_rewards_entry 结构化重进。"""
    for attempt in range(max_attempts):
        adb.key(KEY_BACK)
        human.sleep(*human.page, tag="read_back")
        if "TemplateActivity" in adb.current_activity():
            return True
        screen = Screen(adb.dump(), adb.current_activity())
        if handle_popup(screen, human, adb, log):
            continue
        home_tab = screen.by_text(r"主页", require_real=True, regex=True)
        if home_tab and home_tab.real:
            adb.tap(*home_tab.center)
        else:
            adb.scaled_tap(166, 2262)  # 基线 [82,2178][250,2346] 中心，按分辨率换算
        human.sleep(*human.page, tag="close_drawer")
        if goto_rewards_entry(adb, human, log):
            return True
    log("  [read] 未能返回积分页")
    return False


def task_read(ctx):
    """阅读赚分：逐篇进新闻流文章页停留计分（单篇 3 分，满 30 分封顶）。
    进度唯一依据 = 积分页"阅读以赚取"卡 content-desc 的 X/30。"""
    adb, human, log, jev = ctx["adb"], ctx["human"], ctx["log"], ctx["jev"]
    if not goto_rewards_entry(adb, human, log):
        log("  [read] 未能进入积分页 → unknown")
        return "unknown"
    seen = set()
    total_read = 0
    for cycle in range(5):  # 上限 10 篇/30 分，5 批×3 篇足够覆盖
        if ctx["over_deadline"]():
            log("  [read] 达到任务时限 → 提前结束")
            break
        earned, need, card = _find_read_card(adb, human, log)
        if card is None:
            log("  [read] 积分页找不到\"阅读以赚取\"卡片")
            break
        log("  [read] 进度 %s/%s（第 %d 批前）" % (earned, need, cycle + 1))
        if need and earned is not None and earned >= need:
            log("  [read] 已达每日上限 %d/%d → done" % (earned, need))
            ensure_home(adb, human, log)
            return "done"
        if forbidden_hit(card):
            log("  [read] 卡片命中禁区词，跳过")
            return "skipped"
        anc = tapable_ancestor(card)  # WebView 卡片自身 [0,0][0,0] → 点可视祖先中心
        if not anc or not safe_tap(human, adb, anc, log):
            log("  [read] 卡片可视祖先不可点")
            break
        human.sleep(8.0, 12.0, tag="read_landing")  # 实测约 9 秒加载进新闻流
        scr = Screen(adb.dump(), adb.current_activity())
        if "TemplateActivity" in scr.activity:  # 仍在积分页 → 重试一次点击
            anc = tapable_ancestor(card)
            if anc and not safe_tap(human, adb, anc, log):
                break
            human.sleep(8.0, 12.0, tag="read_landing_retry")
        got = _read_articles_in_feed(adb, human, log, jev, ctx, seen, max_articles=READ_BATCH)
        total_read += got
        log("  [read] 本批 %d 篇，累计 %d 篇" % (got, total_read))
        if got == 0:
            log("  [read] 已无可读文章卡 → 结束")
            break
        if not _back_to_points(adb, human, log):
            break
    ensure_home(adb, human, log)
    log("  [read] 完成阅读流程，累计 %d 篇" % total_read)
    return "done" if total_read > 0 else "unknown"


def task_quiz(ctx):
    adb, human, log, jev = ctx["adb"], ctx["human"], ctx["log"], ctx["jev"]
    goto_rewards_entry(adb, human, log)

    def scan_cards():
        """返回 (待做卡, 已完成卡)。轮播卡: desc 含'赚取 X 积分'；'已赚取'为完成。"""
        scr = Screen(adb.dump(), adb.current_activity())
        pat = r"赚取\s*\d+\s*积分"
        pending = [n for n in scr.all_by_text(pat, require_real=True, regex=True)
                   if "已赚取" not in (n.desc + n.text)]
        finished = [n for n in scr.all_by_text(pat, require_real=True, regex=True)
                    if "已赚取" in (n.desc + n.text)]
        return scr, pending, finished

    opened = 0
    for round_i in range(5):
        if ctx["over_deadline"]():
            break
        screen, cards, finished = scan_cards()
        if not cards:
            human.swipe_up(adb)
            human.sleep(1.0, 2.0, tag="quiz_scroll")
            screen, cards, finished = scan_cards()
            if not cards:
                if finished:
                    log("  [quiz] 轮播卡均已显示'已赚取'（今日已完成）→ skipped")
                    return "skipped"
                break
        target = None
        for n in cards:
            if forbidden_hit(n):
                log("  [quiz] REFUSED_FORBIDDEN_ZONE: %r" % n.label[:50])
                continue
            d = jev.decide(screen, ["open_quiz_card", "go_back", "task_done"],
                           {"page_type": "rewards"})
            if d.get("action") == "open_quiz_card" and jev.gate(d, screen):
                target = n
                break
            if d.get("action") == "task_done":
                break
        if not target:
            break
        safe_tap(human, adb, target, log)
        opened += 1
        log("  [quiz] 打开活动卡 %r（不做自动作答，仅停留计曝光）" % target.label[:40])
        human.sleep(*human.dwell_quiz, tag="quiz_dwell")
        adb.key(KEY_BACK)
        human.sleep(*human.page, tag="quiz_back")
    log("  [quiz] 打开 %d 张轮播卡" % opened)
    return "done" if opened > 0 else "unknown"


# ---------------------------------------------------------------- 主流程
TASKS = [
    ("checkin", "签到（签入）", task_checkin),
    ("search", "搜索赚分", task_search),
    ("daily_activities", "每日活动", task_daily_activities),
    ("read", "阅读赚分", task_read),
    ("quiz", "每日 Quiz / 资讯活动卡", task_quiz),
]


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="Bing Rewards 云手机每日任务自动化")
    ap.add_argument("--config", default=os.path.join(BASE_DIR, "config.json"))
    ap.add_argument("--dry-run", action="store_true",
                    help="dump+决策+打印将执行的任务；不执行任务动作（搜索/开卡），仅允许导航类点击")
    ap.add_argument("--max-searches", type=int, default=None, help="搜索次数上限（默认读配置/30）")
    ap.add_argument("--single", choices=[t[0] for t in TASKS], help="只跑单个任务")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print("找不到配置文件 %s（可从 config.example.json 复制一份）" % args.config)
        return 2
    cfg = load_config(args.config)

    log = Logger(os.path.join(BASE_DIR, "logs"), dry=args.dry_run)
    log("=== bing_rewards 启动 mode=%s config=%s ===" % ("DRY-RUN" if args.dry_run else "RUN", args.config))

    dev = cfg.get("device", {})
    adb = Adb(dev.get("serial", "127.0.0.1:55556"), dev.get("adb_path", "adb"), log)

    # 当日已完成检测（ONLOGON 补跑幂等）
    results_dir = os.path.join(BASE_DIR, "results")
    today = datetime.now().strftime("%Y-%m-%d")
    result_path = os.path.join(results_dir, "%s.json" % today)
    if not args.dry_run and not args.single and os.path.exists(result_path):
        try:
            with open(result_path, encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("all_status") == "done":
                print("今日任务已完成（%s），直接退出" % today)
                return 0
        except (OSError, ValueError):
            pass

    if not adb.device_online():
        log("设备 %s 不在线（adb devices 无 device 状态）" % adb.serial)
        return 2
    log("设备在线: %s, Bing 版本: %s" % (adb.serial, adb.bing_version()))

    human = Human(cfg, log)
    jev = Jev(cfg, log)
    log("Jev 决策后端: %s" % (jev.mode if jev.mode != "api" else "api(%s)" % jev.api.endpoint))

    max_searches = args.max_searches or cfg.get("tasks", {}).get("max_searches", 30)

    # 每日开始时间随机偏移 ±25 分钟（正式跑且非单任务时）
    jitter = cfg.get("human", {}).get("start_jitter_minutes", 25)
    if not args.dry_run and not args.single and jitter:
        delay = random.uniform(-jitter * 60, jitter * 60)
        if delay > 0:
            log("开始随机偏移 +%.0fs" % delay)
            time.sleep(delay)

    deadline = time.time() + cfg.get("tasks", {}).get("watchdog_minutes", 45) * 60

    def over_deadline():
        return time.time() > deadline

    ctx = {"adb": adb, "human": human, "log": log, "jev": jev, "over_deadline": over_deadline}

    before = read_points(adb, human, log) if not args.dry_run else None
    log("任务前积分: %s" % before)

    if args.dry_run:
        return dry_run(ctx, max_searches)

    task_list = [t for t in TASKS if (not args.single or t[0] == args.single)]
    results = []
    for key, name, fn in TASKS:
        if key not in [t[0] for t in task_list]:
            continue
        log("--- 任务: %s ---" % name)
        status, retries = "failed", 0
        for attempt in range(3):  # 首跑 + 2 次重试
            try:
                if key == "search":
                    status = fn(ctx, max_searches)
                else:
                    status = fn(ctx)
                if status in ("done", "skipped"):
                    break
            except (AdbError, Exception) as e:
                log("  [%s] 异常: %s" % (key, e))
                status = "failed"
            retries += 1
            if retries <= 2:
                gap = random.uniform(30, 90)
                log("  [%s] 重试 %d/2，等待 %.0fs" % (key, retries, gap))
                time.sleep(gap)
        results.append({"name": key, "status": status, "retries": retries,
                        "fallback_counts": dict(jev.fallback_counts),
                        "confs": list(jev.confs[-20:])})
        if not args.single:
            human.sleep(*human.between, tag="between_tasks")

    after = read_points(adb, human, log)
    log("任务后积分: %s" % after)

    # 收尾
    adb.stop_bing()
    log("已 force-stop Bing")

    ok = sum(1 for r in results if r["status"] in ("done", "skipped"))
    all_status = "done" if ok == len(results) else ("partial" if ok else "failed")
    summary = {
        "date": today, "device": adb.serial, "dry_run": False,
        "tasks": results,
        "total_points_before": (before or {}).get("total"),
        "total_points_after": (after or {}).get("total"),
        "daily_points_before": (before or {}).get("daily"),
        "daily_points_after": (after or {}).get("daily"),
        "streak": (after or {}).get("streak"),
        "all_status": all_status,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    os.makedirs(results_dir, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    # CSV 追加: 日期,任务,结果,积分增量,置信度分布,兜底次数
    csv_path = os.path.join(results_dir, "summary.csv")
    delta = None
    if summary["total_points_before"] is not None and summary["total_points_after"] is not None:
        delta = summary["total_points_after"] - summary["total_points_before"]
    with open(csv_path, "a", encoding="utf-8") as f:
        for r in results:
            f.write("%s,%s,%s,%s,%s,%s\n" % (
                today, r["name"], r["status"],
                delta if delta is not None else "",
                "/".join(str(c) for c in r["confs"][:5]),
                sum(r["fallback_counts"].values())))

    log("=== 汇总: %s | 任务 %d/%d 成功 | 积分增量 %s ==="
        % (all_status, ok, len(results), delta))
    for r in results:
        log("  %s: %s (retries=%d)" % (r["name"], r["status"], r["retries"]))
    return 0 if all_status == "done" else (1 if ok else 2)


def dry_run(ctx, max_searches=30):
    """只 dump + 分类 + 列出将执行的任务与首个决策动作，不执行任何任务动作。
    额外模拟正式跑的关键前置链路（读积分→找搜索框）：该阶段允许导航类点击
    （进头像/积分卡，与正式跑一致），用于暴露 tab 持久化问题，但不搜索不开卡。"""
    adb, human, log, jev = ctx["adb"], ctx["human"], ctx["log"], ctx["jev"]
    adb.start_bing()
    time.sleep(4)
    screen = Screen(adb.dump(), adb.current_activity())
    page = classify_page(screen)
    log("[dry-run] 当前页面类型: %s (activity=%s)" % (page, screen.activity))
    candidates = [a for _, a in RULE_TABLE.get(page, [(None, "wait")])]
    d = jev.decide(screen, candidates)
    log("[dry-run] 首步建议动作: %s (conf=%.2f, backend=%s)"
        % (d.get("action"), d.get("confidence", 0), d.get("backend")))
    # 模拟正式跑前置链路：read_points 会把 App 留在资料页 tab（正式跑 search 任务
    # 依赖 ensure_home 从该状态恢复）。dry-run 在此复现该序列并验证恢复前提。
    log("[dry-run] 模拟正式跑前置: read_points（导航到资料页读积分）")
    pts = read_points(adb, human, log)
    log("[dry-run] 模拟读积分结果: %s" % pts)
    scr2 = Screen(adb.dump(), adb.current_activity())
    box_visible = bool(scr2.by_id(ID_SEARCH_BOX, require_real=True) or
                       scr2.by_id(ID_HP_SEARCH_BOX, require_real=True))
    log("[dry-run] 读积分后不重启直接找搜索框: 可见=%s（正式跑由 ensure_home 负责恢复）"
        % box_visible)
    print("\n[dry-run] 将执行的任务序列（不执行任务动作）:")
    for key, name, fn in TASKS:
        print("  - %-18s %s" % (key, name))
    print("[dry-run] 搜索上限: %d | 词库: words.txt | 日志: %s" % (max_searches, log.path))
    log("[dry-run] 完成，未执行任何任务动作（搜索/开卡）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
