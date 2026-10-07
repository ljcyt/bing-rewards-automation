#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jev 官方端点连通性自检。

读取 config.json 的 jev 段，按序用 api_keys 数组中每个 key 各向官方端点
（jev.endpoint，应为 https://api.typesafe.ai/v1/systemone）发一次最小请求。
打印每个 key 的 HTTP 状态与响应摘要（模型名 / urgency）。
门禁通过标准：至少一个 key 返回 HTTP 200 且响应为合法 JSON → 退出码 0；
全部失败 → 退出码非 0。

判定参考（2026-10-07 实测）：
  401 authentication_error = key 问题（缺 apikey_ 前缀的裸 hex_hex 或 key 无效）；
  400 api_usage_error      = 鉴权已通过、请求体校验未过；
  200                      = 全链路连通。

注意：TypeSafe 官方域名只有 api.typesafe.ai 与 console.typesafe.ai，
其余任何域名（如 jevmodel.org）均为第三方。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
OFFICIAL_HOST = "api.typesafe.ai"
KEY_PREFIX = "apikey_"


def load_jev_cfg():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    jev = cfg.get("jev") or {}
    endpoint = jev.get("endpoint") or "https://api.typesafe.ai/v1/systemone"
    keys = [k for k in (jev.get("api_keys") or []) if k]
    model = jev.get("model", "jev-latest")
    timeout = jev.get("timeout_s", 8)
    return endpoint, keys, model, timeout


def normalize_key(key):
    """官方鉴权要求 Bearer apikey_<hex_hex> 完整格式；裸 key 自动补前缀。"""
    return key if key.startswith(KEY_PREFIX) else KEY_PREFIX + key


def mask_key(key):
    return (key[:10] + "..." + key[-6:]) if len(key) > 20 else key


def try_key(endpoint, key, model, timeout):
    """对单个 key 发一次最小请求。返回 (http_status, ok, summary)。

    最小请求体结构与 bing_rewards.py TypeSafeApiBackend.decide() 一致：
    {"model", "state"(JSON 字符串), "questions": {name:{type,instructions,criteria}}}，
    仅把 state 的 summary 缩成单屏样例。
    """
    state = json.dumps({
        "page": "home",
        "activity": "org.chromium.chrome.BrowserActivity",
        "summary": {
            "activity": "org.chromium.chrome.BrowserActivity",
            "anchors_found": ["iab_address_bar_text_view"],
            "clickable_texts": ["Search or type URL"],
            "desc_cards": [],
        },
    }, ensure_ascii=False)
    body = json.dumps({
        "model": model,
        "state": state,
        "questions": {
            "action": {
                "type": "choice",
                "instructions": "连通性自检，从候选动作中选一个。",
                "criteria": {"wait": "do nothing", "go_back": "go back"},
            }
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % key})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        hint = ""
        if e.code == 401:
            hint = "（鉴权失败：key 缺 %s 前缀或无效）" % KEY_PREFIX
        elif e.code == 400:
            hint = "（鉴权已通过，请求体校验未过）"
        return e.code, False, "HTTP %s %s%s" % (e.code, raw or e.reason, hint)
    except Exception as e:
        return None, False, "请求异常: %s" % e

    try:
        data = json.loads(raw)
    except ValueError:
        return status, False, "HTTP %s 但响应不是合法 JSON: %r" % (status, raw[:120])

    model_name = data.get("model") or (data.get("answers") or {}).get("model")
    urgency = data.get("urgency")
    if urgency is None:
        urgency = (data.get("answers") or {}).get("urgency")
    summary = "HTTP %s 合法JSON model=%s urgency=%s" % (status, model_name, urgency)
    return status, True, summary


def main():
    endpoint, keys, model, timeout = load_jev_cfg()
    host = urllib.parse.urlsplit(endpoint).hostname or ""
    print("endpoint = %s (host=%s)" % (endpoint, host))
    if host != OFFICIAL_HOST:
        print("警告: endpoint 域名 %s 不是官方域名 %s（其余均为第三方）" % (host, OFFICIAL_HOST))
    if not keys:
        print("config.json 的 jev.api_keys 为空，无法测试")
        return 2

    any_ok = False
    for i, raw_key in enumerate(keys):
        key = normalize_key(raw_key)
        tag = "key#%d(%s)" % (i, mask_key(key))
        status, ok, summary = try_key(endpoint, key, model, timeout)
        print("%-30s -> %s" % (tag, summary))
        if ok:
            any_ok = True

    if any_ok:
        print("结果：至少一个 key 在官方端点返回 200 且响应为合法 JSON")
        return 0
    print("结果：全部 %d 个 key 均失败" % len(keys))
    return 1


if __name__ == "__main__":
    sys.exit(main())
