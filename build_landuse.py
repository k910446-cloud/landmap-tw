#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從《非都市土地使用管制規則》附表一產生「這種使用地能做什麼」的對照表。

為什麼需要
----------
查到一塊非都市土地是「甲種建築用地」之後，接著要問的是「那能做什麼」。
這訂在管制規則第 6 條所指的附表一《各種使用地容許使用項目及許可使用
細目表》，法規資料庫只提供 PDF，所以用 pdftext.py 把它解出來。

表格結構（依 x 座標分欄）
------------------------
    56   使用地類別        一、甲種建築用地
    157  容許使用項目      （一）住宅
    256  免經申請許可使用細目   1. 住宅  2. 民宿
    354  需經目的事業主管機關等許可使用細目
    454  附帶條件

只輸出「容許使用項目」，不輸出細目
--------------------------------
項目名稱來自表格的項目欄，一欄一格、對位可靠。

細目（免經申請／需經許可／附帶條件）則沒有輸出。原因是那些欄位的
儲存格高度差很多、項目標籤又是垂直置中對齊，加上表格跨 73 頁，
試過依 y 範圍、依編號重設、依順序配對三種方式，都還是會在某些地方
整批錯開一格 —— 把甲種的細目掛到乙種、把畜牧設施的細目掛到鄉村教育
設施。寧可不給，也不要給錯：需要細目的人，畫面上有附表一原文 PDF 的
連結，那份才是準的。

輸出
----
    web/landuse.js

用法
----
    python build_landuse.py            # 自動下載附表一並解析
    python build_landuse.py 檔案.pdf   # 用手邊的 PDF
"""

import io
import json
import os
import re
import ssl
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdftext  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "web", "landuse.js")
PDF = os.path.join(BASE_DIR, "data", "附表一.pdf")

# 法規資料庫上《非都市土地使用管制規則》的附表一
PDF_URL = "https://law.moj.gov.tw/LawClass/LawGetFile.ashx?FileId=0000418664&lan=C"
LAW_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0060013"

_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

# 欄位的 x 範圍（依實際 PDF 量出來的）
COL_CATEGORY = (0, 150)
COL_ITEM = (150, 250)
COL_FREE = (250, 350)
COL_PERMIT = (350, 450)
COL_COND = (450, 999)

CN = "一二三四五六七八九十"


def fetch_pdf():
    if os.path.isfile(PDF) and os.path.getsize(PDF) > 100000:
        return PDF
    os.makedirs(os.path.dirname(PDF), exist_ok=True)
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120, context=_CTX) as r:
        data = r.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("下載到的不是 PDF")
    with open(PDF, "wb") as f:
        f.write(data)
    return PDF


def in_col(x, col):
    return col[0] <= x < col[1]


def clean(t):
    """只去空白。條文原文照留，不做任何字元置換。"""
    return re.sub(r"\s+", "", t)


def norm(t):
    """比對編號用：把半形括號當成全形。

    附表的編號大多寫「（一）」，但有幾處是半形「(十五)」。
    這個轉換只用在「這是不是一個新編號」的判斷上，
    存進輸出的仍是原文 —— 不去動法規的字。
    """
    return t.replace("(", "（").replace(")", "）")


# 表頭文字會跟第一列資料混在一起，先擋掉
HEADER_WORDS = ("使用地類別", "容許使用項目", "許可使用細目", "免經申請",
                "需經目的事業", "附帶條件", "各種使用地容許使用", "附表一")


def is_header(t):
    return any(w in t for w in HEADER_WORDS)


def parse(pages):
    """回傳 [{category, items:[{item, free:[], permit:[], cond}]}]。

    三件事沒有想像中直觀：

    一、類別名稱會跨行：「十四、古蹟保存用」在上一列、「地」在下一列，
        要一直接下去，直到名稱以「用地」結尾。

    二、有的類別沒有「（一）」編號，項目名稱直接寫在欄位裡
        （古蹟保存用地、特定目的事業用地就是這樣）。

    三、最麻煩的：容許使用項目的標籤是「垂直置中」對齊它那一格的細目。
        照順序邊讀邊配會整批錯開；改用 y 最接近也不夠，因為每一格的高度
        差很多。真正可靠的訊號是細目的編號 —— 每一格都從「1.」重新編號，
        所以看到 1. 就是新的一格。先照這個切出「格」，再用「標籤的 y 落在
        哪一格的範圍內」把格配給項目，兩個訊號互相驗證。
    """
    cats = []
    cur_cat = None
    last_item = None

    def new_cat(name):
        nonlocal cur_cat, last_item
        cur_cat = {"category": name, "items": []}
        cats.append(cur_cat)
        last_item = None

    def add_item(name, y):
        nonlocal last_item
        if cur_cat is None:
            return None
        last_item = {"item": name, "free": [], "permit": [], "cond": ""}
        cur_cat["items"].append(last_item)
        return (y, last_item)

    for page in pages:
        rows = pdftext.rows_of(page)

        # 表頭（使用地類別／容許使用項目／許可使用細目／附帶條件）跟第一列
        # 資料靠得很近，片段又會跨行拆開，逐片比對擋不乾淨。
        # 改成整列判斷：表頭那幾列以上的東西一律不要。
        head_end = None
        for i, (y, cells) in enumerate(rows):
            line = clean("".join(t for _x, t in cells))
            if is_header(line):
                head_end = i
        if head_end is not None:
            rows = rows[head_end + 1:]

        labels = []

        # ── 類別欄與項目標籤 ──
        for y, cells in rows:
            cat_txt = clean("".join(t for x, t in cells if in_col(x, COL_CATEGORY)))
            if cat_txt and not is_header(cat_txt):
                m = re.match(r"^([%s]+)、(.*)$" % CN, cat_txt)
                if m:
                    new_cat(m.group(2))
                elif (cur_cat is not None
                      and not cur_cat["category"].endswith("用地")
                      and len(cur_cat["category"]) < 14):
                    cur_cat["category"] += cat_txt

            item_txt = clean("".join(t for x, t in cells if in_col(x, COL_ITEM)))
            if not item_txt or is_header(item_txt):
                continue
            m2 = re.match(r"^（([%s]+)）(.*)$" % CN, norm(item_txt))
            if m2:
                lb = add_item(m2.group(2), y)
                if lb:
                    labels.append(lb)
            elif cur_cat is not None and not cur_cat["items"]:
                # 古蹟保存用地、特定目的事業用地沒有「（一）」編號，
                # 項目名稱直接寫在欄位裡。這個判斷要放在續接前面 ——
                # 否則名稱會被接到上一個類別的最後一項去。
                lb = add_item(item_txt, y)
                if lb:
                    labels.append(lb)
            elif labels:
                # 同一列可能把「兒童課後照顧服務中心（十五）動物保護相關設施」
                # 黏在一起，遇到編號就切成新的一項
                parts = re.split(r"（([%s]+)）" % CN, norm(item_txt))
                labels[-1][1]["item"] += parts[0]
                for k in range(1, len(parts) - 1, 2):
                    lb = add_item(parts[k + 1], y)
                    if lb:
                        labels.append(lb)

        # ── 細目切格：看到「1.」就是新的一格 ──
        for col, key in ((COL_FREE, "free"), (COL_PERMIT, "permit")):
            blocks = []          # [{y0, y1, texts:[...]}]
            for y, cells in rows:
                for x, raw in sorted(cells):
                    t = clean(raw)
                    if not t or not in_col(x, col) or is_header(t):
                        continue
                    num = re.match(r"^(\d+)\.$", t)
                    if num:
                        if num.group(1) == "1" or not blocks:
                            blocks.append({"y0": y, "y1": y, "texts": [""],
                                           "numbered": True, "row": y})
                        else:
                            blocks[-1]["texts"].append("")
                            blocks[-1]["y1"] = y
                            blocks[-1]["row"] = y
                    elif blocks and (blocks[-1]["numbered"]
                                     or blocks[-1]["row"] == y):
                        # 有編號的格：後續文字是同一項的內容；
                        # 沒編號的格：只有同一列才算同一格
                        blocks[-1]["texts"][-1] += t
                        blocks[-1]["y1"] = y
                        blocks[-1]["row"] = y
                    else:
                        # 沒有編號、自成一格的寫法，例如「同甲種建築用地」。
                        # 這種一列就是一格，連著好幾列是好幾個不同的項目，
                        # 不能併在一起。
                        blocks.append({"y0": y, "y1": y, "texts": [t],
                                       "numbered": False, "row": y})

            # 格與項目都是由上而下的，照順序配對最穩。
            # 先用「標籤的 y 落在這一格的範圍內」認領（項目標籤垂直置中，
            # 所以會落在自己那一格裡）；沒認到的再往下取還沒配過的標籤。
            ptr = 0
            for blk in blocks:
                target = None
                for i in range(ptr, len(labels)):
                    ly = labels[i][0]
                    if blk["y1"] - 4 <= ly <= blk["y0"] + 4:
                        target = labels[i][1]
                        ptr = i + 1
                        break
                    if ly < blk["y1"] - 4:
                        break
                if target is None:
                    for i in range(ptr, len(labels)):
                        if not labels[i][1][key]:
                            target = labels[i][1]
                            ptr = i + 1
                            break
                if target is None:
                    target = last_item
                if target is None:
                    continue
                target[key] += [s2 for s2 in blk["texts"] if s2]

        # ── 附帶條件：整欄併給 y 最接近的項目 ──
        for y, cells in rows:
            for x, raw in cells:
                t = clean(raw)
                if not t or not in_col(x, COL_COND) or is_header(t):
                    continue
                if labels:
                    min(labels, key=lambda kv: abs(kv[0] - y))[1]["cond"] += t
                elif last_item is not None:
                    last_item["cond"] += t

    return cats


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else fetch_pdf()
    print("解析 %s …" % os.path.basename(path))
    pages = pdftext.page_texts(path)
    if not any(pages):
        print("這個 PDF 取不到文字（可能是掃描檔）。沒有內容就不輸出，"
              "以免產生一份空的對照表。")
        return
    cats = parse(pages)

    # 只留看起來像使用地類別的（結尾是「用地」）
    cats = [c for c in cats if c["category"].endswith("用地") and c["items"]]
    if not cats:
        print("解析不出使用地類別，不輸出。")
        return

    # 只留項目名稱。細目對位不可靠，寧可不給也不要給錯（見檔頭說明）。
    slim = [{"category": c["category"],
             "items": [it["item"] for it in c["items"]]} for c in cats]

    payload = {
        "source": "非都市土地使用管制規則 附表一：各種使用地容許使用項目及許可使用細目表",
        "lawUrl": LAW_URL,
        "pdfUrl": PDF_URL,
        "note": "只收錄容許使用項目；各項的細目與附帶條件請看附表一原文。",
        "categories": slim,
    }

    buf = io.StringIO()
    buf.write("/* 這個檔案由 build_landuse.py 從《非都市土地使用管制規則》附表一產生。\n")
    buf.write(" *\n")
    buf.write(" * 附表一在法規資料庫上只有 PDF，所以是用 pdftext.py 解出來的，\n")
    buf.write(" * 不是人工轉抄。附表修正時重跑 build_landuse.py 即可。\n")
    buf.write(" *\n")
    buf.write(" * 「同甲種建築用地」這種寫法照條文原文保留，沒有自行展開 ——\n")
    buf.write(" * 展開等於代替主管機關解釋。\n")
    buf.write(" */\n")
    buf.write("window.LANDUSE = ")
    json.dump(payload, buf, ensure_ascii=False, indent=1)
    buf.write(";\n")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())

    print("\n已產生 %s" % os.path.relpath(OUT, BASE_DIR))
    for c in cats:
        print("  %-14s %2d 項容許使用" % (c["category"], len(c["items"])))


if __name__ == "__main__":
    main()
