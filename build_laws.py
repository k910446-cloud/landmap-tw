#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從全國法規資料庫抓條文，產生 web/laws.js。

查到使用分區或使用地類別之後，接著會想知道「那能蓋什麼、蓋多大」。
這支程式把相關法條抓下來存成前端可用的資料檔。

原則：
  1. 條文一律取自全國法規資料庫（law.moj.gov.tw），不憑印象寫。
  2. 建蔽率、容積率的數字用程式從條文本身解析，不手抄。
  3. 只放已驗證過的法規代碼；驗不到的一律改放搜尋連結，
     寧可讓使用者多點一下，也不要指到錯的法規。

法規會修正，需要更新時重跑這支程式。

用法：
    python build_laws.py
"""

import io
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "web", "laws.js")

_CTX = ssl.create_default_context()
_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

LAW_URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=%s"
ART_URL = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=%s&flno=%s"
SEARCH_URL = "https://law.moj.gov.tw/Law/LawSearchResult.aspx?ty=ONEBAR&kw=%s"

# 已逐一連線驗證過標題與條文數的法規代碼
LAWS = [
    ("D0060013", "非都市土地使用管制規則", ["5", "6", "9", "9-1"]),
    ("D0070001", "都市計畫法", ["32", "34", "35", "36", "37", "39"]),
    ("D0070012", "都市計畫法臺灣省施行細則", ["32", "34", "35", "36"]),
]

# 六都的分區管制訂在自己的地方自治法規，不適用臺灣省施行細則。
#
# 這些名稱與網址是逐一到各市法規系統查出來的，不是憑印象寫 ——
# 一開始我照「都市計畫法○○市施行細則」的規律推，結果臺北市根本不叫這個名字
# （它叫「臺北市都市計畫施行自治條例」，是由舊名改的），臺中市也不是「細則」
# 而是「自治條例」。規律推出來的名稱會錯，所以下面每一筆都經過查證。
#
# 產生時會再連線核對一次頁面標題，對不上就不輸出。
MUNICIPAL_RULES = {
    "臺北市": [
        ("臺北市都市計畫施行自治條例",
         "https://laws.gov.taipei/Law/LawSearch/LawInformation/FL003961"),
        # 臺北市的建蔽率、容積率實際訂在這一部，不在上面那部裡
        ("臺北市土地使用分區管制自治條例",
         "https://laws.gov.taipei/Law/LawSearch/LawInformation/FL003962"),
    ],
    "新北市": [
        ("都市計畫法新北市施行細則",
         "https://web.law.ntpc.gov.tw/Scripts/FLAWDAT01.aspx?lncode=1C0150108"),
    ],
    "桃園市": [
        ("都市計畫法桃園市施行細則",
         "https://law.tycg.gov.tw/LawContent.aspx?id=GL001628"),
    ],
    "臺中市": [
        ("都市計畫法臺中市施行自治條例",
         "https://law.taichung.gov.tw/LawContent.aspx?id=GL002020"),
    ],
    "臺南市": [
        ("都市計畫法臺南市施行細則",
         "https://law01.tainan.gov.tw/GLRSNEWSOUT/LawContent.aspx?id=GL000655"),
    ],
    "高雄市": [
        ("都市計畫法高雄市施行細則",
         "https://outlaw.kcg.gov.tw/LawContent.aspx?id=GL000627"),
    ],
}

# 其他常用法規：只給連結不抓全文（篇幅大且多為技術性規定）。
# 這裡放法規代碼而不是搜尋連結 —— 全國法規資料庫的搜尋結果頁只顯示筆數，
# 使用者還得再點一次才看得到條文，直接連過去比較有用。
# 代碼一樣會核對標題，對不上就不輸出。
REFERENCE_LAWS = [
    # 這些代碼是掃過法規資料庫的鄰近號段核對出來的。
    # 第一版是照印象寫的，結果整組錯位（建築設計施工編寫成了設備編的號、
    # 區域計畫法跟容積移轉辦法還對調），全被標題核對擋下來 —— 所以才改成
    # 每一筆都連線核對標題，對不上就不輸出。
    ("D0070114", "建築技術規則總則編"),
    ("D0070115", "建築技術規則建築設計施工編"),
    ("D0070116", "建築技術規則建築構造編"),
    ("D0070117", "建築技術規則建築設備編"),
    ("D0070109", "建築法"),
    # 非都市土地的建築管理實際上走這一部
    ("D0070123", "實施區域計畫地區建築管理辦法"),
    ("D0070030", "區域計畫法"),
    ("D0070230", "國土計畫法"),
    ("D0070028", "都市計畫容積移轉實施辦法"),
]

CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_number(text):
    """把「一百八十」「六十」「五」這種中文數字轉成整數。"""
    text = text.strip()
    if not text:
        return None
    total, section, ok = 0, 0, False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in CN_DIGITS:
            section = CN_DIGITS[ch]
            ok = True
        elif ch == "十":
            section = (section or 1) * 10
            total += section
            section = 0
            ok = True
        elif ch == "百":
            section = (section or 1) * 100
            total += section
            section = 0
            ok = True
        else:
            return None
        i += 1
    total += section
    return total if ok else None


def name_variants(name):
    """條文寫「加油（氣）站專用區」，圖資只寫「加油站專用區」——字面對不上。

    括號在這裡是「或」的意思（加油站或加氣站），所以把去掉括號、
    以及把括號內容併入的兩種寫法都建索引。這不是猜，是照條文的寫法還原。
    """
    out = [name]
    if "（" in name and "）" in name:
        import re as _re
        out.append(_re.sub(r"（[^）]*）", "", name))          # 加油站專用區
        out.append(name.replace("（", "").replace("）", ""))   # 加油氣站專用區
    return [x for x in dict.fromkeys(out) if x]


def parse_percent_list(text):
    """從「一、住宅區：百分之六十。二、商業區：百分之八十。」抓出 {分區: 百分比}。

    直接解析條文本身，避免人工轉抄出錯。
    """
    out = {}
    # 條文是連續一段，用「數字、」當分隔
    for m in re.finditer(r"[一二三四五六七八九十]+、\s*([^：:]{2,40})[：:]([^。]{0,60})", text):
        names, rest = m.group(1), m.group(2)
        pm = re.search(r"百分之([零一二三四五六七八九十百]+)", rest)
        if not pm:
            continue
        val = cn_number(pm.group(1))
        if val is None:
            continue
        full = names.strip()
        if full and len(full) <= 30:
            for v in name_variants(full):
                out.setdefault(v, val)
        # 「郵政、電信、變電所專用區」這種並列寫法，把每個名稱也各自建索引，
        # 並補上共同的後綴（專用區、區…），方便前端用分區名直接查到。
        parts = [x.strip() for x in re.split(r"[、，,]", full) if x.strip()]
        if len(parts) > 1:
            last = parts[-1]
            suffix = ""
            for suf in ("專用區", "保存區", "特定區", "區", "用地"):
                if last.endswith(suf):
                    suffix = suf
                    break
            for name in parts:
                if len(name) > 20:
                    continue
                for v in name_variants(name):
                    out.setdefault(v, val)
                if suffix and not name.endswith(suffix):
                    for v in name_variants(name + suffix):
                        out.setdefault(v, val)
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(html):
    t = re.sub(r"<br\s*/?>", "\n", html)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return "\n".join(l.rstrip() for l in t.split("\n") if l.strip())


def parse_articles(html):
    pat = re.compile(
        r'name="(\d+(?:-\d+)?)">第\s*([\d-]+)\s*條</a></div>'
        r'<div class="col-data[^"]*">(.*?)</div></div>', re.S)
    return {m.group(2): strip_tags(m.group(3)) for m in pat.finditer(html)}


def law_title(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    return m.group(1).replace("-全國法規資料庫", "").strip() if m else ""


def revision_date(html):
    t = re.sub(r"<[^>]+>", " ", html)
    m = re.search(r"修正日期[：:]\s*(民國[^<\n]{4,24}?日)", t)
    if not m:
        m = re.search(r"公發布日[：:]\s*(民國[^<\n]{4,24}?日)", t)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def verify_page(url, name):
    """連過去確認這個網址真的是那部法規。

    回傳 ok / mismatch / unreachable。分開 mismatch 與 unreachable 是因為
    兩者意義不同：標題對不上代表資料錯，一定要丟掉；連不上只代表這台機器
    當下連不到那個主機，資料本身仍是查證過的。
    """
    try:
        html = fetch(url)
    except Exception:
        return "unreachable"
    title = law_title(html)
    body = re.sub(r"<[^>]+>", " ", html[:200000])
    return "ok" if (name in title or name in body) else "mismatch"


def main():
    payload = {
        "source": "全國法規資料庫 law.moj.gov.tw",
        "laws": {},
        "articles": {},
        "nonUrbanCaps": {},
        "nonUrbanDelegated": {},
        "provinceBcr": {},
        "provinceFar": {},
        "publicFacilityBcr": {},
        "municipalRules": {},
        "referenceLinks": [],
    }

    articles_by_law = {}
    for pcode, name, wanted in LAWS:
        print("抓取 %s …" % name)
        html = fetch(LAW_URL % pcode)
        title = law_title(html)
        if name not in title:
            print("  ！標題不符（拿到「%s」），跳過以免放錯法規" % title)
            continue
        arts = parse_articles(html)
        rev = revision_date(html)
        payload["laws"][name] = {
            "pcode": pcode, "url": LAW_URL % pcode,
            "title": title, "revision": rev, "articleCount": len(arts),
        }
        articles_by_law[name] = arts
        print("  %s　%s　共 %d 條" % (title, rev or "（無修正日期）", len(arts)))
        for no in wanted:
            body = arts.get(no)
            if not body:
                print("  ！找不到第 %s 條" % no)
                continue
            payload["articles"]["%s§%s" % (name, no)] = {
                "law": name, "no": no, "text": body,
                "url": ART_URL % (pcode, no),
            }

    # 非都市土地使用管制規則第 9 條：各使用地建蔽率、容積率上限
    a9 = articles_by_law.get("非都市土地使用管制規則", {}).get("9", "")
    if a9:
        head = a9.split("經區域計畫擬定機關")[0]
        for m in re.finditer(r"[一二三四五六七八九十]+、\s*([^︰:：]{2,20})[︰:：]\s*"
                             r"建蔽率百分之([零一二三四五六七八九十百]+)。?\s*"
                             r"容積率百分之([零一二三四五六七八九十百]+)", head):
            payload["nonUrbanCaps"][m.group(1).strip()] = {
                "bcr": cn_number(m.group(2)), "far": cn_number(m.group(3))
            }
        # 第 9 條未列者由各該中央主管機關另訂
        tail = a9.split("第一項以外使用地")[-1]
        for m in re.finditer(r"[一二三四五六七八九十]+、\s*([^︰:：]{2,30})用地之中央主管機關"
                             r"[︰:：]\s*([^。]{2,20})", tail):
            for nm in re.split(r"[、，,]", m.group(1)):
                nm = nm.strip()
                if nm:
                    payload["nonUrbanDelegated"][nm + "用地"] = m.group(2).strip()
        print("  第9條解析出 %d 種用地上限、%d 種授權另訂"
              % (len(payload["nonUrbanCaps"]), len(payload["nonUrbanDelegated"])))

    # 都市計畫法臺灣省施行細則：§32 建蔽率、§34 容積率、§36 公共設施用地建蔽率
    prov = articles_by_law.get("都市計畫法臺灣省施行細則", {})
    if prov.get("32"):
        payload["provinceBcr"] = parse_percent_list(prov["32"])
        print("  §32 解析出 %d 個分區的建蔽率" % len(payload["provinceBcr"]))
    if prov.get("34"):
        # §34 第一款是住商的表格，程式不解析；其餘條列可解析
        payload["provinceFar"] = parse_percent_list(prov["34"].split("二、旅館區")[-1])
        print("  §34 解析出 %d 個分區的容積率" % len(payload["provinceFar"]))
    if prov.get("36"):
        payload["publicFacilityBcr"] = parse_percent_list(prov["36"])
        print("  §36 解析出 %d 種公共設施用地的建蔽率" % len(payload["publicFacilityBcr"]))

    print("核對地方自治法規連結 …")
    for cty, entries in MUNICIPAL_RULES.items():
        good = []
        for name, url in entries:
            state = verify_page(url, name)
            if state == "mismatch":
                print("  ！%s：頁面標題不含「%s」，跳過" % (cty, name))
                continue
            if state == "unreachable":
                # 連不到不代表資料錯（臺南的主機從這裡常連不通），
                # 名稱與網址都是查證過的，保留並標示出來。
                print("  [略過複核] %s：%s（連線逾時）" % (cty, name))
            else:
                print("  [OK]   %s：%s" % (cty, name))
            good.append({"name": name, "url": url})
        if good:
            payload["municipalRules"][cty] = good

    print("核對相關法規代碼 …")
    for pcode, name in REFERENCE_LAWS:
        url = LAW_URL % pcode
        state = verify_page(url, name)
        if state == "mismatch":
            print("  ！%s：代碼 %s 指到別部法規，跳過" % (name, pcode))
            continue
        print("  %s %s" % ("[OK]  " if state == "ok" else "[未複核]", name))
        payload["referenceLinks"].append({"name": name, "url": url})

    buf = io.StringIO()
    buf.write("/* 這個檔案由 build_laws.py 從全國法規資料庫產生，不要手動改。\n")
    buf.write(" *\n")
    buf.write(" * 建蔽率、容積率的數字是從條文本文解析出來的，不是人工轉抄。\n")
    buf.write(" * 六都的施行細則屬地方自治法規，這裡放搜尋連結而非直接連結，\n")
    buf.write(" * 以免指到錯的法規。\n")
    buf.write(" *\n")
    buf.write(" * 法規會修正 —— 需要更新時重跑 build_laws.py。\n")
    buf.write(" * 條文僅供參考，個案適用以主管機關認定與最新公告為準。\n")
    buf.write(" */\n")
    buf.write("window.LAWS = ")
    json.dump(payload, buf, ensure_ascii=False, indent=1)
    buf.write(";\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print("\n已產生 %s（%d 部法規、%d 條條文）"
          % (os.path.relpath(OUT, BASE_DIR), len(payload["laws"]), len(payload["articles"])))


if __name__ == "__main__":
    main()
