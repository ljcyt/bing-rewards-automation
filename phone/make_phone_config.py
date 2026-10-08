# -*- coding: utf-8 -*-
"""生成手机版 config.json：把 device.serial 改为本机 adbd（127.0.0.1:5555）。

手机内执行时，脚本用 Termux 的 adb 连本机 adbd，不经过任何隧道。
用法：python make_phone_config.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "config.json")
DST = os.path.join(HERE, "config.phone.json")

if not os.path.exists(SRC):
    raise SystemExit("找不到 %s，请先准备 config.json（可从 config.example.json 复制）" % SRC)

with open(SRC, "r", encoding="utf-8") as f:
    cfg = json.load(f)

cfg.setdefault("device", {})
cfg["device"]["serial"] = "127.0.0.1:5555"
cfg["device"]["adb_path"] = "adb"

with open(DST, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("已生成 %s（serial=%s，keys=%d）" % (
    DST, cfg["device"]["serial"], len((cfg.get("jev") or {}).get("api_keys") or [])))
