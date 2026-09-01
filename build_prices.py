#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把不動產實價登錄整理成「依地號查得到成交價」的檔案。

為什麼做得到
------------
內政部的實價登錄批次資料分成兩個檔：

  <縣市碼>_lvr_land_a.csv        買賣主檔：交易年月、總價、單價、標的類型…
  <縣市碼>_lvr_land_a_land.csv   土地明細：段名 ＋ 八碼地號，用「編號」對應主檔

八碼地號（母號 4 ＋ 子號 4）跟這個 App 查地籍用的鍵完全一樣，
所以可以把成交紀錄精準掛到宗地上，不需要地址地理編碼那種會失準的做法。
實測苗栗 114S2：主檔 99.2% 對得到土地明細，地號 100% 是八碼格式。

輸出
----
    web/prices/<縣市>.json

    {
      "seasons": ["114S2", ...],
      "counts": { "土地": n, "房地": n, ... },
      "sections": {
         "中苗段": { "08800000": [ [年月, 總價萬, 單價元每坪, 面積m2, 類型], ... ] }
      }
    }

數字用陣列而不是物件，是因為同一份資料會重複幾十萬次，
欄位名稱佔的空間比數值本身還多。

用法
----
    python build_prices.py                 # 最近 8 季（兩年）
    python build_prices.py --seasons 12    # 最近 12 季
    python build_prices.py --county 苗栗縣
"""

import argparse
import csv
import io
import json
import os
import re
import ssl
import sys
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "web", "prices")
CACHE_DIR = os.path.join(BASE_DIR, "data", "lvr")

_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

ZIP_URL = ("https://plvr.land.moi.gov.tw/DownloadSeason"
           "?season=%s&type=zip&fileName=lvr_landcsv.zip")

PING = 400.0 / 121.0            # 1 坪 = 3.3057851 m²

# 實價登錄檔名用的縣市代碼
COUNTY_CODE = {
    "a": "臺北市", "b": "臺中市", "c": "基隆市", "d": "臺南市", "e": "高雄市",
    "f": "新北市", "g": "宜蘭縣", "h": "桃園市", "i": "嘉義市", "j": "新竹縣",
    "k": "苗栗縣", "m": "南投縣", "n": "彰化縣", "o": "新竹市", "p": "雲林縣",
    "q": "嘉義縣", "t": "屏東縣", "u": "花蓮縣", "v": "臺東縣", "w": "金門縣",
    "x": "澎湖縣", "z": "連江縣",
}

# 交易標的壓成一個小數字。5 是預售屋 —— 它在另一個檔案裡，
# 價格性質也跟成屋不同（賣的是還沒蓋好的房子），所以獨立一類。
KIND = {"土地": 0, "房地(土地+建物)": 1, "建物": 2, "車位": 3,
        "房地(土地+建物)+車位": 4}
PRESALE_KIND = 5


def seasons_back(n):
    """從現在往回推 n 季，回傳像 ['114S2', '114S1', ...] 的清單。

    民國年 + 季。實價登錄大約在季末後一個半月才發佈，所以從「上一季」
    開始往回抓，避免一直去要一個還不存在的檔案。
    """
    import datetime
    today = datetime.date.today()
    y = today.year - 1911
    q = (today.month - 1) // 3 + 1
    q -= 1
    if q == 0:
        q = 4
        y -= 1
    out = []
    for _ in range(n):
        out.append("%dS%d" % (y, q))
        q -= 1
        if q == 0:
            q = 4
            y -= 1
    return out


def fetch_season(season):
    """下載一季的壓縮檔，存到 data/lvr/ 以免重跑時又抓一次。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "%s.zip" % season)
    if os.path.isfile(path) and os.path.getsize(path) > 100000:
        return path
    req = urllib.request.Request(ZIP_URL % season,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180, context=_CTX) as r:
        data = r.read()
    if len(data) < 100000:
        raise ValueError("檔案太小，可能這一季還沒發佈")
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    zipfile.ZipFile(tmp).namelist()      # 壞檔就不要留下
    os.replace(tmp, path)
    return path


def read_csv(z, name):
    """讀一個 CSV。實價登錄第二行是英文欄名，不是資料，要跳掉。"""
    if name not in z.namelist():
        return []
    text = z.read(name).decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows:
        first = " ".join(str(v) for v in rows[0].values() if v)
        if "serial number" in first.lower() or "The " in first:
            rows = rows[1:]
    return rows


def to_int(t):
    try:
        return int(float(str(t).strip()))
    except (TypeError, ValueError):
        return 0


# 備註欄會註明特殊交易情形。這些成交不能當一般行情看 ——
# 親友間交易通常低於市價，含增建或裝潢則會墊高單價。
#
# 實測 115S2 四縣市 21066 筆房地交易：有標記的佔 23.7%（親友 8.0%、
# 含增建未登記 15.8%）。整段的中位數其實只差 1.6%（36.4 → 37.0 萬），
# 中位數本來就抗離群值；但單一地號往往只有兩三筆成交，那時一筆親友
# 交易就足以主導結果，所以還是要標出來、算的時候能排除。
NOTE_FLAGS = [
    (1, r"親友|特殊關係|員工|共有人"),
    (2, r"裝潢|家具|傢俱"),
    (4, r"未登記建物|增建"),
    (8, r"債務|債權|法拍|拍賣"),
]


def note_flags(text):
    v = 0
    for bit, pat in NOTE_FLAGS:
        if re.search(pat, text or ""):
            v |= bit
    return v


def deal_record(m, presale=False, age=None, project=None):
    """一筆交易壓成小陣列。

    [年月, 總價萬, 單價元每坪, 面積m2, 類型, 備註旗標, 屋齡, 建案編號]

    屋齡與建案名稱不是每筆都有：屋齡來自成屋的建物明細檔，
    建案名稱只有預售屋檔才有 —— 成屋的開放資料沒有這個欄位，
    這是資料本身的限制，不是漏抓。
    """
    ym = to_int(m.get("交易年月日"))
    ym = ym // 100 if ym > 100000 else ym          # 1141102 → 11411
    total = to_int(m.get("總價元"))
    unit_m2 = to_int(m.get("單價元平方公尺"))
    area = 0.0
    try:
        area = float(m.get("建物移轉總面積平方公尺") or 0) \
            or float(m.get("土地移轉總面積平方公尺") or 0)
    except (TypeError, ValueError):
        area = 0.0
    kind = PRESALE_KIND if presale else KIND.get((m.get("交易標的") or "").strip(), 9)
    return [ym, round(total / 10000.0, 1), int(round(unit_m2 * PING)),
            round(area, 1), kind, note_flags(m.get("備註")),
            age if age is not None else -1,
            project if project is not None else -1]


def build_county(z, code, county, store, projects):
    """成屋（a）與預售屋（b）都收，兩者都能靠土地明細對到地號。"""
    added = 0

    def link(rows):
        by = {}
        for row in rows:
            sid = (row.get("編號") or "").strip()
            if sid:
                by.setdefault(sid, []).append(row)
        return by

    def attach(m, parts, presale, age, project):
        nonlocal added
        rec = deal_record(m, presale=presale, age=age, project=project)
        if rec[1] <= 0:
            return
        for p in parts:
            sect = (p.get("土地位置") or "").strip()
            no8 = (p.get("地號") or "").strip()
            if not sect or not re.match(r"^\d{8}$", no8):
                continue
            store.setdefault(county, {}).setdefault(sect, {})                  .setdefault(no8, []).append(rec)
            added += 1

    # ── 成屋 ──
    main = read_csv(z, "%s_lvr_land_a.csv" % code)
    by_land = link(read_csv(z, "%s_lvr_land_a_land.csv" % code))
    by_build = link(read_csv(z, "%s_lvr_land_a_build.csv" % code))
    for m in main:
        sid = (m.get("編號") or "").strip()
        parts = by_land.get(sid)
        if not parts:
            continue
        # 屋齡在建物明細檔。一筆交易可能含好幾棟，取第一棟就好 ——
        # 同一次交易的建物通常是同一批完工的
        age = None
        b = (by_build.get(sid) or [None])[0]
        if b:
            a = to_int(b.get("屋齡"))
            if a > 0:
                age = a
        attach(m, parts, False, age, None)

    # ── 預售屋：只有這個檔有建案名稱 ──
    pre = read_csv(z, "%s_lvr_land_b.csv" % code)
    pre_land = link(read_csv(z, "%s_lvr_land_b_land.csv" % code))
    for m in pre:
        sid = (m.get("編號") or "").strip()
        parts = pre_land.get(sid)
        if not parts:
            continue
        name = (m.get("建案名稱") or "").strip()
        pid = None
        if name:
            lst = projects.setdefault(county, [])
            idx = projects.setdefault(county + "#idx", {})
            if name not in idx:
                idx[name] = len(lst)
                lst.append(name)
            pid = idx[name]
        attach(m, parts, True, 0, pid)

    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=8, help="往回抓幾季（預設 8＝兩年）")
    ap.add_argument("--county", action="append", help="只輸出指定縣市")
    args = ap.parse_args()

    want = seasons_back(args.seasons)
    store = {}
    projects = {}
    used = []

    for season in want:
        try:
            path = fetch_season(season)
        except Exception as e:
            print("  %s 取得失敗（%s），跳過" % (season, str(e)[:50]))
            continue
        with zipfile.ZipFile(path) as z:
            n = 0
            for code, county in COUNTY_CODE.items():
                if args.county and county not in args.county:
                    continue
                n += build_county(z, code, county, store, projects)
        used.append(season)
        print("  %s 完成，累計掛到宗地的紀錄 %d 筆" % (season, n))

    if not store:
        print("沒有取得任何資料。")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    total_files = total_bytes = 0
    for county, sections in sorted(store.items()):
        deals = sum(len(v) for sec in sections.values() for v in sec.values())
        # 每一筆地號的紀錄依年月新到舊排好，前端就不必再排
        for sec in sections.values():
            for k in sec:
                sec[k].sort(key=lambda r: -r[0])
        payload = {
            "county": county,
            "seasons": used,
            "source": "內政部不動產成交案件實際資訊資料供應系統（實價登錄）",
            "licence": "政府資料開放授權條款－第 1 版",
            "fields": ["交易年月", "總價萬元", "單價元每坪", "面積平方公尺",
                       "類型", "備註旗標", "屋齡", "建案編號"],
            "projects": projects.get(county, []),
            "flags": {"1": "親友或特殊關係間交易", "2": "含裝潢或家具",
                      "4": "含增建或未登記建物", "8": "債權債務或法拍"},
            "kinds": dict({str(v): k for k, v in KIND.items()},
                          **{str(PRESALE_KIND): "預售屋"}),
            "sections": sections,
        }
        p = os.path.join(OUT_DIR, "%s.json" % county)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        size = os.path.getsize(p)
        total_files += 1
        total_bytes += size
        print("%-6s %6d 段  %8d 筆紀錄  %6.2f MB"
              % (county, len(sections), deals, size / 1e6))

    print("\n共 %d 個縣市、%.1f MB，季別：%s"
          % (total_files, total_bytes / 1e6, "、".join(used)))


if __name__ == "__main__":
    main()
