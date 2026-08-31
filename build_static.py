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


def cors_only(mapping):
    return {c: pick(v) for c, v in mapping.items()
            if isinstance(v, dict) and v.get("cors")}


def main():
    cadastre = cors_only(DS.CADASTRE_COUNTIES)

    urban = cors_only(DS.DATASETS["urban_zone"]["counties"])
    # 臺北的伺服器模式走下載的 SHP，靜態版改用它的即時服務
    for cty, cfg in DS.URBAN_LIVE_FOR_STATIC.items():
        if cfg.get("cors"):
            urban[cty] = pick(cfg)

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
    print("  地籍查詢   %d 縣市：%s" % (len(cadastre), "、".join(sorted(cadastre))))
    print("  都市計畫   %d 縣市：%s" % (len(urban), "、".join(sorted(urban))))
    print("  非都市分區 靜態版不支援（需要後端解析 shapefile）")


if __name__ == "__main__":
    main()
