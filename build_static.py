#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 datasets.py 產生前端用的服務設定 web/services.js。

靜態版（GitHub Pages）沒有 Python 後端，地籍與都市計畫查詢得由瀏覽器
直接打各縣市的 ArcGIS。但不是每個縣市的服務都送 CORS 標頭，
所以這裡只輸出 datasets.py 裡標了 cors=True 的那些。

這麼做是為了維持單一來源：縣市服務只在 datasets.py 登錄一次，
前端設定用這支程式產生，不會兩邊各寫一份而走鐘。

用法：
    python build_static.py
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datasets as DS  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "web", "services.js")

# 只有這些鍵前端用得到，其餘（下載網址、檔案大小）靜態版沒有意義
FIELD_KEYS = ("url", "wkid", "sect", "sectcode", "landno", "landno8",
              "mother", "child", "area", "town", "office", "source")


def pick(cfg):
    return {k: cfg[k] for k in FIELD_KEYS if k in cfg}


def collect(mapping):
    """全部縣市都輸出；沒有 CORS 標頭的標記 needsProxy。

    先前只輸出有 CORS 的，等於在產生階段就把苗栗這種縣市剔除掉。
    但那些服務其實是好的，只差瀏覽器不准直連 —— 只要設定了自己的代理
    就能用，所以改成一律輸出，由前端依 needsProxy 決定怎麼連。
    """
    out = {}
    for c, v in mapping.items():
        if not isinstance(v, dict) or not v.get("url"):
            continue
        cfg = pick(v)
        if not v.get("cors"):
            cfg["needsProxy"] = True
        out[c] = cfg
    return out


def main():
    cadastre = collect(DS.CADASTRE_COUNTIES)

    urban = collect(DS.DATASETS["urban_zone"]["counties"])
    # 臺北的伺服器模式走下載的 SHP，靜態版改用它的即時服務
    for cty, cfg in DS.URBAN_LIVE_FOR_STATIC.items():
        urban[cty] = pick(cfg)
        if not cfg.get("cors"):
            urban[cty]["needsProxy"] = True

    ds = DS.DATASETS["urban_zone"]
    payload = {
        "cadastre": cadastre,
        "urban": urban,
        "urbanFields": {
            "value": ds["value_fields"],
            "code": ds["code_fields"],
            "extra": ds["extra_fields"],
        },
        # 非都市分區／編定需要在伺服器端解析 shapefile，靜態版做不到
        "nonUrbanCounties": sorted(DS.DATASETS["nurban_zone"]["counties"]),
    }

    buf = io.StringIO()
    buf.write("/* 這個檔案由 build_static.py 從 datasets.py 產生，不要手動改。\n")
    buf.write(" *\n")
    buf.write(" * 靜態版（GitHub Pages）沒有後端，地籍與都市計畫查詢由瀏覽器直接\n")
    buf.write(" * 打各縣市的 ArcGIS 服務。只有會送 CORS 標頭的服務能這樣用，\n")
    buf.write(" * 所以這裡的縣市會比本機完整版少。\n")
    buf.write(" */\n")
    buf.write("window.SERVICES = ")
    json.dump(payload, buf, ensure_ascii=False, indent=2)
    buf.write(";\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())

    print("已產生 %s" % os.path.relpath(OUT, BASE_DIR))
    def split(m):
        direct = sorted(c for c, v in m.items() if not v.get("needsProxy"))
        viap = sorted(c for c, v in m.items() if v.get("needsProxy"))
        return direct, viap

    for label, m in (("地籍查詢", cadastre), ("都市計畫", urban)):
        direct, viap = split(m)
        print("  %s   直連 %d 縣市：%s" % (label, len(direct), "、".join(direct)))
        if viap:
            print("  %s   需代理 %d 縣市：%s" % ("　" * len(label), len(viap), "、".join(viap)))
    print("  非都市分區 靜態版不支援（需要後端解析 shapefile）")


if __name__ == "__main__":
    main()
