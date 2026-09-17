#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容積檢討用的法規上限值。

每一筆都附「法規名稱＋條次＋版本日期＋網址」，是實際連線到全國法規資料庫
抓下條文後整理的，不是憑印象寫的。查證方式與逐條複驗紀錄見 build_laws.py。

這個檔的用途只有一個：讓 far.py 算完之後，能拿設計值去對法定上限，
超過就在表上標出來。它不決定「應該填多少」——那是設計者的判斷；
它只回答「填這個數字有沒有超過法規允許」。

要更新時：重跑 build_laws.py 核對條文，或到下面每筆的 url 逐條複查。
"""

LAW_BASE = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=%s&flno=%s"

# 建築技術規則建築設計施工編。已連線驗證：pcode 為 D0070115
# （D0070116 是建築構造編、D0070117 是建築設備編，一開始很容易填錯）。
TECH = {
    "pcode": "D0070115",
    "name": "建築技術規則建築設計施工編",
    "revision": "民國 115 年 02 月 23 日",
}


def cite(flno, clause=""):
    return {
        "kind": "法規",
        "name": TECH["name"],
        "article": "第 %s 條%s" % (flno, clause),
        "revision": TECH["revision"],
        "url": LAW_BASE % (TECH["pcode"], flno),
    }


# ── 免計容積的法定上限 ──────────────────────────────────────────────
#
# 這一組是整份評估表最容易踩到的地雷。事務所的表沿用「機電 15%、梯廳 5%
# 或 7.5%、陽台 7.5% 或 10%」，但現行條文長得不一樣：
#
#   * 15% 的分母是「該基地容積」（基地面積 × 法定容積率），不是樓地板面積；
#     而且那 15% 是機電設備空間、安全梯梯間、緊急昇降機機道、特別安全梯與
#     緊急昇降機排煙室、管委會空間「五項合計」的上限，不是機房單獨的額度。
#   * 陽臺與梯廳現行各為該層樓地板面積 10%，兩者合計上限 15%。
#     5%／7.5% 是民國 92 年以前的舊數值。
#
# 所以這裡放的是「法定上限」，不是「建議值」。設計值仍由使用者填，
# 我們只負責在超過時說出來。

CAPS = {
    "mep": {
        "label": "機電設備等五項免計容積",
        "value": 0.15,
        "base": "基準容積",
        "note": ("上限為該基地容積之 15%，且是「機電設備空間＋安全梯之梯間＋"
                 "緊急昇降機之機道＋特別安全梯與緊急昇降機之排煙室＋公寓大廈"
                 "管理委員會使用空間」五項面積之和；依規定僅須設置一座直通"
                 "樓梯之建築物降為 10%。"),
        "source": cite("162", "第1項第2款但書"),
    },
    "mep_single_stair": {
        "label": "機電設備等五項免計容積（僅需一座直通樓梯）",
        "value": 0.10,
        "base": "基準容積",
        "source": cite("162", "第1項第2款但書"),
    },
    "balcony": {
        "label": "陽臺免計容積",
        "value": 0.10,
        "base": "該層樓地板面積",
        "note": "無共同使用梯廳之住宅用途為 12.5% 或 8 ㎡。",
        "source": cite("162", "第1項第1款"),
    },
    "lobby": {
        "label": "梯廳免計容積",
        "value": 0.10,
        "base": "該層樓地板面積",
        "note": "梯廳淨深度不得小於 2 公尺。",
        "source": cite("162", "第1項第1款"),
    },
    "balcony_lobby": {
        "label": "陽臺＋梯廳合計免計容積",
        "value": 0.15,
        "base": "該層樓地板面積",
        "note": "超過部分應計入該層樓地板面積。",
        "source": cite("162", "第1項第1款"),
    },
    "penthouse": {
        "label": "屋頂突出物水平投影面積",
        "value": 0.125,
        "base": "建築面積",
        "note": "高層建築物為 15%；未達 25 ㎡ 者得建 25 ㎡。",
        "source": cite("1", "第9款第1目"),
    },
    "penthouse_high": {
        "label": "屋頂突出物水平投影面積（高層建築物）",
        "value": 0.15,
        "base": "建築面積",
        "source": cite("1", "第9款第1目"),
    },
    "parking_area": {
        "label": "每輛停車空間換算容積之樓地板面積",
        "value": 40.0,
        "base": "㎡／輛",
        "note": "不含機械式停車空間，限實施容積管制地區。",
        "source": cite("60", "第1項第7款"),
    },
}


# ── 停車空間設置標準（第 59 條附表）────────────────────────────────
#
# 條文明訂「依都市計畫法令或都市計畫書之規定；其未規定者，依下表規定」——
# 所以這張表是備位規定，個案要先看土管有沒有另訂。
#
# 另一件事：事務所的表寫 (檢討面積 − 300) ÷ 150 + 1，那個 +1 在條文裡
# 找不到。條文說明（六）寫的是「未達整數時其零數應設置一輛」，也就是
# 無條件進位 ceil((FA − 免設額度) ÷ 級距)。除得盡的時候 +1 會多算一輛。
# 我們照條文算，並在表上把事務所慣用的算法一起列出來對照。

PARKING = {
    "1-in": {"label": "第一類・都市計畫內", "exempt": 300, "step": 150,
             "uses": "戲院、辦公室、金融業、市場、商場、餐飲、店鋪等"},
    "1-out": {"label": "第一類・都市計畫外", "exempt": 300, "step": 250,
              "uses": "同上"},
    "2-in": {"label": "第二類・都市計畫內", "exempt": 500, "step": 150,
             "uses": "住宅、集合住宅等居住用途"},
    "2-out": {"label": "第二類・都市計畫外", "exempt": 500, "step": 300,
              "uses": "同上"},
    "3-in": {"label": "第三類・都市計畫內", "exempt": 500, "step": 200,
             "uses": "旅館、醫院、體育設施、宗教設施、福利設施等"},
    "3-out": {"label": "第三類・都市計畫外", "exempt": 500, "step": 350,
              "uses": "同上"},
    "4-in": {"label": "第四類・都市計畫內", "exempt": 500, "step": 250,
             "uses": "倉庫、學校、補習班、工廠等"},
    "4-out": {"label": "第四類・都市計畫外", "exempt": 500, "step": 350,
              "uses": "同上"},
}
PARKING_SOURCE = cite("59")
PARKING_NOTE = ("檢討面積不含室內停車空間、法定防空避難設備、騎樓門廊外廊等"
                "無牆壁面積，以及機械房、變電室、蓄水池、屋頂突出物等；"
                "計算結果未達整數時，其零數應設置一輛。")


# ── 綜合設計（開放空間）獎勵 ────────────────────────────────────────
#
# 事務所的表寫「△FA=有效面積×2×0.4」。現行條文是 △FA1 = S × I，
# 其中 I（鼓勵係數）＝ 容積率 × 2/5，商業區與市場用地 I ≤ 2.5、
# 住宅區文教區風景區機關用地 0.5 ≤ I ≤ 1.5。
# 容積率 200% 時 I = 0.8，跟「×2×0.4」剛好同值 —— 難怪會被寫成那樣，
# 但容積率不是 200% 的時候就會差。這裡照條文放。

OPEN_SPACE = {
    "formula": "△FA1 = S × I",
    "I": "容積率 × 2/5",
    "I_commercial_max": 2.5,
    "I_residential_min": 0.5,
    "I_residential_max": 1.5,
    "S_min_ratio": 0.60,          # 開放空間有效面積 ≥ 法定空地面積 60%
    "coef": {"沿街步道式": 1.5, "廣場式（臨接大於八分之一）": 1.0,
             "廣場式（臨接小於八分之一）": 0.6},
    "cover_factor": 0.8,          # 有頂蓋者 ×0.8；地面層為住宅、集合住宅者歸零
    "threshold": {
        "商業區、市場用地": 1000,
        "住宅區、文教區、風景區、機關用地": 1500,
    },
    "road": "臨接寬度 ≥ 8 公尺之道路，連續臨接長度 ≥ 25 公尺或 ≥ 基地周界總長 1/6",
    "source": {
        "適用": cite("282"),
        "有效面積": cite("284"),
        "下限": cite("287"),
        "獎勵": cite("286", "第1項第1款"),
        "上限": cite("285"),
    },
    "cap_note": ("建築技術規則本身未訂獎勵百分比上限 —— 第285條規定應符合都市計畫"
                 "法規或都市計畫書圖，未規定者須送當地都市計畫委員會審議通過。"
                 "坊間常見的「上限20%」「上限30%」是地方土管的規定，不是中央法規，"
                 "請查該案所在都市計畫的土地使用分區管制要點。"),
}


def check_caps(design, base_fa, build_area, floor_area, single_stair=False,
               high_rise=False):
    """拿設計值去對法定上限，回傳檢核結果清單。

    只回報，不修改任何數字。每一筆都帶法源，讓使用者自己判斷是要改設計、
    還是這個案子有土管的特別規定可以援引。
    """
    out = []

    def add(key, label, used, limit, base_label, source, note=None):
        if used is None or limit is None:
            return
        ok = used <= limit + 1e-9
        out.append({
            "key": key, "label": label,
            "used": used, "limit": limit, "baseLabel": base_label,
            "ok": ok, "source": source, "note": note,
            "over": None if ok else used - limit,
        })

    cap = CAPS["mep_single_stair"] if single_stair else CAPS["mep"]
    if base_fa:
        add("mep", cap["label"], design.get("mep"), base_fa * cap["value"],
            "基準容積 × %s%%" % (cap["value"] * 100), cap["source"], cap.get("note"))

    # 陽臺、梯廳的分母是「該層樓地板面積」。評估表階段還沒有分層設計，
    # 只能用地上層總樓地板面積近似 —— 這一點必須講明白，不能讓人以為
    # 這是逐層檢討過的結果。
    if floor_area:
        for k in ("balcony", "lobby"):
            c = CAPS[k]
            add(k, c["label"], design.get(k), floor_area * c["value"],
                "地上層樓地板 × %s%%" % (c["value"] * 100), c["source"],
                (c.get("note") or "") + "（評估階段以地上層樓地板面積近似該層樓地板面積）")
        c = CAPS["balcony_lobby"]
        both = (design.get("balcony") or 0) + (design.get("lobby") or 0)
        add("balcony_lobby", c["label"], both, floor_area * c["value"],
            "地上層樓地板 × %s%%" % (c["value"] * 100), c["source"], c.get("note"))

    if build_area:
        c = CAPS["penthouse_high"] if high_rise else CAPS["penthouse"]
        # 屋突是「每一層」的水平投影面積受限，不是各層加總
        per = design.get("penthousePerFloor")
        add("penthouse", c["label"], per, max(build_area * c["value"], 25.0),
            "建築面積 × %s%%（未達 25 ㎡ 者得建 25 ㎡）" % (c["value"] * 100),
            c["source"], c.get("note"))

    return out
