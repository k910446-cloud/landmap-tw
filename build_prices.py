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
    web/prices/<縣市>.idx.json   幾十 KB：每個「段」在 .bin 裡的位移
    web/prices/<縣市>.bin        該縣市全部成交，依段排好、varint 編碼

為什麼不是一個大 JSON：收錄十年份之後，新北市的 JSON 會超過 30 MB，
手機根本載不動。改成二進位加索引，瀏覽器用 HTTP Range 只抓需要的那一段
（通常幾十 KB），跟非都市圖層是同一套做法。

.bin 裡每一段的內容：
    段內地號數
    每筆地號：八碼地號、成交筆數、每筆成交的欄位（差分後 varint）

租賃資料（c 檔）沒有收：實測 115S2 七個縣市 39063 筆租賃，只有 2.5%
對得到地號 —— 租賃申報多半只有門牌沒有地號。收進來會得到一份不具
代表性的樣本，比沒有更糟。

用法
----
    python build_prices.py                 # data/lvr/ 裡所有已下載的季別
    python build_prices.py --seasons 8     # 只用最近 8 季
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


# 早期季別有極長的備註欄，會撞到 csv 模組的預設上限
csv.field_size_limit(10 * 1024 * 1024)


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
SHARE_FLAG = 16      # 持分移轉，不是整筆 —— 單價基準跟整筆不同


def note_flags(text):
    v = 0
    for bit, pat in NOTE_FLAGS:
        if re.search(pat, text or ""):
            v |= bit
    return v


def deal_record(m, presale=False, age=None, project=None,
                btype=-1, use=-1, share=False):
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
    flags = note_flags(m.get("備註"))
    if share:
        flags |= SHARE_FLAG
    return [ym, round(total / 10000.0, 1), int(round(unit_m2 * PING)),
            round(area, 1), kind, flags,
            age if age is not None else -1,
            project if project is not None else -1,
            btype, use]


def dict_id(store, county, kind, name):
    """把重複出現的字串（建物型態、主要用途、建案名稱）收進字典存編號。"""
    if not name:
        return -1
    key = county + "#" + kind
    lst = store.setdefault(key, [])
    idx = store.setdefault(key + "#idx", {})
    if name not in idx:
        idx[name] = len(lst)
        lst.append(name)
    return idx[name]


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

    def attach(m, parts, presale, age, project, btype=-1, use=-1, share=False):
        nonlocal added
        rec = deal_record(m, presale=presale, age=age, project=project,
                          btype=btype, use=use, share=share)
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
        use = -1
        b = (by_build.get(sid) or [None])[0]
        if b:
            a = to_int(b.get("屋齡"))
            if a > 0:
                age = a
            use = dict_id(projects, county, "use", (b.get("主要用途") or "").strip())
        if use < 0:
            use = dict_id(projects, county, "use", (m.get("主要用途") or "").strip())
        btype = dict_id(projects, county, "btype", (m.get("建物型態") or "").strip())
        share = any("持分" in (p.get("移轉情形") or "") for p in parts)
        attach(m, parts, False, age, None, btype, use, share)

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
        btype = dict_id(projects, county, "btype", (m.get("建物型態") or "").strip())
        use = dict_id(projects, county, "use", (m.get("主要用途") or "").strip())
        share = any("持分" in (p.get("移轉情形") or "") for p in parts)
        attach(m, parts, True, 0, pid, btype, use, share)

    return added



# ── 二進位輸出 ───────────────────────────────────────────────
#
# 一筆成交十個欄位，用 JSON 存每個數字都要六七個位元組的文字；
# 換成 varint 之後多半只要一兩個。收錄十年份時差距是 30 MB 對 5 MB。

def put_uvarint(buf, v):
    v = int(v)
    if v < 0:
        v = 0
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            break


def put_svarint(buf, v):
    v = int(v)
    put_uvarint(buf, (v << 1) if v >= 0 else ((-v << 1) - 1))


def encode_section(parcels):
    """一個段：地號數 →（八碼地號、成交數、各筆成交欄位）。

    同一筆地號的成交依年月排序後做差分，年月與單價都會變成小數字。
    """
    buf = bytearray()
    put_uvarint(buf, len(parcels))
    for no8 in sorted(parcels):
        put_uvarint(buf, int(no8))
        rows = sorted(parcels[no8], key=lambda r: r[0])
        put_uvarint(buf, len(rows))
        prev_ym = prev_unit = 0
        for r in rows:
            put_svarint(buf, r[0] - prev_ym)          # 年月（差分）
            prev_ym = r[0]
            put_uvarint(buf, round(r[1] * 10))        # 總價萬元 ×10
            put_svarint(buf, r[2] - prev_unit)        # 單價元每坪（差分）
            prev_unit = r[2]
            put_uvarint(buf, round(r[3] * 10))        # 面積 m² ×10
            put_uvarint(buf, r[4])                    # 類型
            put_uvarint(buf, r[5])                    # 備註旗標
            put_uvarint(buf, r[6] + 1)                # 屋齡（-1 → 0）
            put_uvarint(buf, r[7] + 1)                # 建案編號
            put_uvarint(buf, r[8] + 1)                # 建物型態
            put_uvarint(buf, r[9] + 1)                # 主要用途
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=0,
                    help="往回取幾季（0＝用 data/lvr/ 裡已下載的全部）")
    ap.add_argument("--county", action="append", help="只輸出指定縣市")
    args = ap.parse_args()

    if args.seasons:
        want = seasons_back(args.seasons)
    else:
        # 已經下載好的全部，新到舊
        want = sorted(
            (f[:-4] for f in os.listdir(CACHE_DIR)
             if f.endswith(".zip") and os.path.getsize(
                 os.path.join(CACHE_DIR, f)) > 100000),
            key=lambda t: (int(t.split("S")[0]), int(t.split("S")[1])),
            reverse=True) if os.path.isdir(CACHE_DIR) else []
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
    total_bin = total_idx = total_deals = 0
    for county, sections in sorted(store.items()):
        blob = bytearray()
        index = {}
        deals = 0
        for sect in sorted(sections):
            off = len(blob)
            chunk = encode_section(sections[sect])
            blob += chunk
            index[sect] = [off, len(chunk)]
            deals += sum(len(v) for v in sections[sect].values())

        meta = {
            "county": county,
            "seasons": used,
            "source": "內政部不動產成交案件實際資訊資料供應系統（實價登錄）",
            "licence": "政府資料開放授權條款－第 1 版",
            "fields": ["交易年月", "總價萬元", "單價元每坪", "面積平方公尺",
                       "類型", "備註旗標", "屋齡", "建案", "建物型態", "主要用途"],
            "flags": {"1": "親友或特殊關係間交易", "2": "含裝潢或家具",
                      "4": "含增建或未登記建物", "8": "債權債務或法拍",
                      "16": "持分移轉"},
            "kinds": dict({str(v): k for k, v in KIND.items()},
                          **{str(PRESALE_KIND): "預售屋"}),
            "projects": projects.get(county, []),
            "btypes": projects.get(county + "#btype", []),
            "uses": projects.get(county + "#use", []),
            "dealCount": deals,
            "sections": index,
        }
        stem = os.path.join(OUT_DIR, county)
        with open(stem + ".bin", "wb") as f:
            f.write(bytes(blob))
        with open(stem + ".idx.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
        ib = os.path.getsize(stem + ".idx.json")
        total_bin += len(blob)
        total_idx += ib
        total_deals += deals
        print("%-6s %5d 段  %8d 筆  bin %6.2f MB  idx %5.2f MB"
              % (county, len(index), deals, len(blob) / 1e6, ib / 1e6))

    print("")
    print("共 %d 個縣市、%d 筆成交，bin %.1f MB ＋ idx %.1f MB"
          % (len(store), total_deals, total_bin / 1e6, total_idx / 1e6))
    print("季別 %d 季：%s ～ %s" % (len(used), used[-1], used[0]))


if __name__ == "__main__":
    main()
