#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""檢查目前收錄的資料有沒有過期。

為什麼要有
----------
這個 App 的每一份資料都是某個時間點的快照：法規會修正、實價登錄每季發佈、
政府圖資每年換版。沒有人盯著的話，它會安靜地變成一份過期資料 ——
畫面照樣好好的，數字卻是舊的。

這支程式把「目前收錄的版本」跟「上游現在的版本」比一比，
有落差就報告，並用結束碼告訴自動化流程要不要重建：

    0  都是最新的
    1  有東西該更新了
    2  檢查本身失敗（連不上之類），不代表資料過期

用法
----
    python check_updates.py            # 全部檢查
    python check_updates.py --laws     # 只檢查法規
    python check_updates.py --prices   # 只檢查實價登錄
"""

import argparse
import io
import json
import os
import re
import ssl
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_laws  # noqa: E402
import build_prices  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def load_js(path):
    """讀 web/*.js 裡的那個 JSON。"""
    full = os.path.join(BASE_DIR, path)
    if not os.path.isfile(full):
        return None
    t = io.open(full, encoding="utf-8").read()
    try:
        return json.loads(t[t.index("{"):t.rindex(";")])
    except ValueError:
        return None


def check_laws():
    """比對每部法規的修正日期。"""
    cur = load_js("web/laws.js")
    if not cur:
        return ["web/laws.js 還沒產生"], []
    stale, ok = [], []
    for name, info in (cur.get("laws") or {}).items():
        try:
            html = build_laws.fetch(build_laws.LAW_URL % info["pcode"])
        except Exception as e:
            stale.append("%s 檢查失敗：%s" % (name, str(e)[:40]))
            continue
        now = build_laws.revision_date(html)
        if now and now != info.get("revision"):
            stale.append("%s 已修正：%s → %s" % (name, info.get("revision"), now))
        else:
            ok.append("%s %s" % (name, info.get("revision")))
    return stale, ok


def check_prices():
    """看有沒有比目前收錄的更新的季別。"""
    idx_dir = os.path.join(BASE_DIR, "web", "prices")
    if not os.path.isdir(idx_dir):
        return ["web/prices/ 還沒產生"], []
    have = set()
    for f in os.listdir(idx_dir):
        if f.endswith(".idx.json"):
            d = json.load(io.open(os.path.join(idx_dir, f), encoding="utf-8"))
            have |= set(d.get("seasons") or [])
            break
    if not have:
        return ["web/prices/ 裡沒有季別資訊"], []

    newest = max(have, key=lambda s: (int(s.split("S")[0]), int(s.split("S")[1])))
    # 從「上一季」往回看兩季，找有沒有還沒收錄的
    stale, ok = [], ["目前收錄至 %s（共 %d 季）" % (newest, len(have))]
    for season in build_prices.seasons_back(2):
        if season in have:
            continue
        try:
            req = urllib.request.Request(
                build_prices.ZIP_URL % season,
                headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
            with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
                size = int(r.headers.get("Content-Length") or 0)
            if size > 100000:
                stale.append("實價登錄已發佈 %s（%.1f MB），尚未收錄"
                             % (season, size / 1e6))
        except Exception:
            # 還沒發佈的季別本來就會失敗，不算異常
            pass
    return stale, ok


def check_datasets():
    """政府圖資的版本 —— 只報告目前用的是哪一版。

    上游沒有提供可靠的「有無新版」查詢，硬猜會給出錯誤的安心感，
    所以這裡只把現況印出來，由人判斷。
    """
    import datasets as DS
    notes = []
    for key in ("nurban_zone", "nurban_desig", "urban_zone"):
        src = DS.DATASETS[key].get("source", "")
        m = re.search(r"(\d{3})\s*年", src)
        notes.append("%s：%s%s" % (key, src, "" if m else "（來源未標年份）"))
    return [], notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--laws", action="store_true")
    ap.add_argument("--prices", action="store_true")
    args = ap.parse_args()
    everything = not (args.laws or args.prices)

    stale, ok = [], []
    try:
        if args.laws or everything:
            a, b = check_laws()
            stale += a
            ok += b
        if args.prices or everything:
            a, b = check_prices()
            stale += a
            ok += b
        if everything:
            a, b = check_datasets()
            stale += a
            ok += b
    except Exception as e:
        print("檢查失敗：%r" % (e,))
        return 2

    for line in ok:
        print("  目前 %s" % line)
    if not stale:
        print("\n都是最新的。")
        return 0
    print("")
    for line in stale:
        print("  該更新 %s" % line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
