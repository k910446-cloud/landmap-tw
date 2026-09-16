#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""都市計畫區範圍 —— 取自國土管理署城鄉發展分署「全國土地使用分區資料查詢系統」。

為什麼需要這個
--------------
都市計畫「使用分區」（住宅區、商業區…）各縣市自己公開的只有八個，
而都市計畫「區範圍」（這塊地在不在都市計畫區內、屬於哪一個計畫區）
全國都查得到 —— 城鄉發展分署的查詢系統 luz.nlma.gov.tw 有完整清單與圖形。

對做土地開發的人來說，「在不在計畫區內」往往是第一個要問的問題：
框內走都市計畫法與各縣市施行細則，框外走區域計畫法與非都市土地使用管制規則，
兩套法規完全不同。之前這個 App 只有八個縣市畫得出計畫區範圍框。

哪些東西刻意不抓
----------------
同一個系統還掛了一組 ArcGIS 圖磚服務（giss.nlma.gov.tw 的 URBAN_LANDUSE_ZONE
等等），內容是全國都市計畫使用分區的著色圖。那組服務的 token 綁 referer，
只認 luz.nlma.gov.tw 送出的請求 —— 那是機關明確設下的「只許本站使用」，
要用它就得偽造 Referer。這支程式不碰那組服務。

抓的是這個系統自己的查詢 API（跟使用者在畫面上點「查詢都市計畫區」
走的是同一條路），一次一個計畫區。

對對方主機的禮貌
----------------
系統本身限制「請勿連續進行查詢動作!請5秒後再進行查詢」，所以每次查詢之間
固定等 PAUSE 秒，不並行。全國約八百個計畫區，跑完一輪要一個多小時 ——
這是一季更新一次的東西，不急。

輸出
----
    web/urban_areas/<縣市>.json

    {"county":..., "source":..., "notice":..., "plans":[
        {"code":"J0201", "name":"新豐(新庄子地區)都市計畫",
         "rings":[[[lon,lat],...]]}]}

座標轉成 WGS84 經緯度、取到小數第 5 位（約 1 公尺）—— 這是計畫區的外框，
不是地籍界線，再精細沒有意義，檔案卻會大一倍。

用法
----
    python build_urban_areas.py                 # 全部縣市
    python build_urban_areas.py --county 新竹縣  # 只跑一個
"""

import argparse
import http.cookiejar
import io
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "web", "urban_areas")

SITE = "https://luz.nlma.gov.tw/WEB/"
WS_DATA = SITE + "ws_data.ashx"
WS_FORM = SITE + "ws_form.ashx"

SOURCE = "內政部國土管理署城鄉發展分署 全國土地使用分區資料查詢系統"
NOTICE = ("本圖資僅供參考，不得作為任何形式證明或主張；"
          "實際範圍以各該都市計畫公告發布實施之書圖為準。")

# 系統自己的限制：請勿連續查詢，請 5 秒後再查。留一點餘裕。
PAUSE = 5.5

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"

_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=_CTX))
    op.addheaders = [("User-Agent", UA), ("Referer", SITE)]
    return op


def get_token(op):
    """首頁的 M_CONFIG 裡就帶著這次連線要用的 token。"""
    html = op.open(SITE, timeout=60).read().decode("utf-8", "replace")
    m = re.search(r'"Token"\s*:\s*"([^"]+)"', html)
    if not m:
        raise RuntimeError("首頁裡找不到 token，系統可能改版了")
    return m.group(1)


def counties(op):
    """縣市代碼對照，從查詢表單的下拉選單解出來。"""
    url = WS_FORM + "?" + urllib.parse.urlencode({"CMD": "GETFORM", "FUNC": "#0101"})
    html = op.open(url, timeout=60).read().decode("utf-8", "replace")
    block = re.search(r'id="COUNTY_0101".*?</select>', html, re.S)
    if not block:
        raise RuntimeError("解不出縣市清單，系統可能改版了")
    out = []
    for code, name in re.findall(r'<option value="(\d+)"[^>]*>([^<]+)</option>',
                                 block.group(0)):
        out.append((code, name.strip()))
    return out


def plans(op, token, county_code):
    url = WS_DATA + "?" + urllib.parse.urlencode(
        {"CMD": "GETDATA", "OBJ": "URBANPLAN", "COUNTY": county_code, "TOKEN": token})
    data = op.open(url, timeout=60).read().decode("utf-8", "replace")
    return [(p["計畫區代碼"], p["計畫區名稱"]) for p in json.loads(data)]


def rings_of(op, token, plan_code):
    """一個計畫區的外框。回傳 Web Mercator 的 rings。"""
    url = WS_DATA + "?" + urllib.parse.urlencode(
        {"CMD": "SEARCHURBANRANGE", "TOKEN": token})
    body = urllib.parse.urlencode({"VAL1": plan_code}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    raw = op.open(req, timeout=90).read().decode("utf-8", "replace")
    d = json.loads(raw)
    if isinstance(d, dict) and d.get("success") == "false":
        raise RuntimeError(d.get("status", "查詢被拒"))
    out = []
    for f in (d.get("features") or []):
        out += ((f.get("geometry") or {}).get("rings") or [])
    return out


def to_lonlat(x, y):
    """Web Mercator → WGS84 經緯度，取到小數第 5 位（約 1 公尺）。"""
    lon = x / 20037508.34 * 180.0
    lat = y / 20037508.34 * 180.0
    lat = 180.0 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2)
    return [round(lon, 5), round(lat, 5)]


def drop_repeats(ring):
    """相鄰重複點去掉 —— 取到公尺之後會多出一些。"""
    out = []
    for p in ring:
        if not out or out[-1] != p:
            out.append(p)
    return out


def build(op, token, code, name, only=None):
    got, failed = [], []
    for plan_code, plan_name in plans(op, token, code):
        try:
            rings = rings_of(op, token, plan_code)
        except Exception as e:
            failed.append("%s %s（%s）" % (plan_code, plan_name, str(e)[:40]))
            time.sleep(PAUSE)
            continue
        ll = [drop_repeats([to_lonlat(p[0], p[1]) for p in r]) for r in rings]
        ll = [r for r in ll if len(r) >= 4]
        if ll:
            got.append({"code": plan_code, "name": plan_name, "rings": ll})
        else:
            failed.append("%s %s（沒有圖形）" % (plan_code, plan_name))
        time.sleep(PAUSE)

    if not got:
        return None, failed
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name + ".json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump({"county": name, "source": SOURCE, "notice": NOTICE,
                   "plans": got}, f, ensure_ascii=False, separators=(",", ":"))
    return path, failed


def write_index():
    """把各縣市檔案的外框寫成索引，前端才知道要不要載那一份。

    沒有索引的話，前端只能一次把全部縣市都載下來 —— 全國八百多個
    計畫區會是好幾 MB，而使用者多半只看得到其中一個縣市。
    """
    if not os.path.isdir(OUT_DIR):
        return
    out = []
    for f in sorted(os.listdir(OUT_DIR)):
        if not f.endswith(".json") or f == "index.json":
            continue
        d = json.load(io.open(os.path.join(OUT_DIR, f), encoding="utf-8"))
        pts = [p for pl in d["plans"] for r in pl["rings"] for p in r]
        if not pts:
            continue
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        out.append({"county": d["county"], "plans": len(d["plans"]),
                    "bbox": [round(min(lons), 4), round(min(lats), 4),
                             round(max(lons), 4), round(max(lats), 4)]})
    with io.open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"source": SOURCE, "notice": NOTICE, "counties": out},
                  f, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", action="append", help="只跑指定縣市（可重複）")
    args = ap.parse_args()

    op = opener()
    token = get_token(op)
    cty = counties(op)
    if args.county:
        want = set(args.county)
        cty = [c for c in cty if c[1] in want]
        missing = want - {c[1] for c in cty}
        if missing:
            print("沒有這些縣市：%s" % "、".join(sorted(missing)))
            return 2
    if not cty:
        print("沒有要處理的縣市")
        return 2

    total_plans = 0
    for code, name in cty:
        path, failed = build(op, token, code, name)
        if path is None:
            print("%-5s 一個計畫區都沒取到" % name)
        else:
            d = json.load(io.open(path, encoding="utf-8"))
            total_plans += len(d["plans"])
            print("%-5s %3d 個計畫區  %6.1f KB" % (
                name, len(d["plans"]), os.path.getsize(path) / 1024.0))
        for line in failed:
            print("       略過 %s" % line)

    write_index()
    print("\n共 %d 個計畫區，輸出到 %s" % (total_plans, OUT_DIR))
    print("資料來源：%s" % SOURCE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
