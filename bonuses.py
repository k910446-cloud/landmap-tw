#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容積獎勵目錄 —— 依基地位置自動判斷適用哪些法規與上限。

使用者的需求是「給地號，就依位置套進相對應的法條與容積獎勵，
給我最後可用的容積」。這支模組負責「相對應」那一段：

    縣市 + 都市/非都市 + 使用分區 + 基地面積 + 臨接道路寬度
        → 適用的獎勵法規、各項目的百分比、合計上限、以及法源

每一個數字都附法規名稱、條次與版本日期，是逐條連線全國法規資料庫
（law.moj.gov.tw）與各縣市法規系統查證後整理的。查不到的縣市就明說
「尚未登錄」，不套用別的縣市的數字 —— 容積移轉的道路寬度分級是各縣市
自訂的，新竹市與苗栗縣的級距就不一樣，套錯會直接影響可行性判斷。

rules.py 管的是「免計容積的法定上限」（建築技術規則），
這裡管的是「可以多拿多少容積」。兩者都會出現在評估表上。
"""

import datetime
import math

import rules


def _c(name, revision, pcode, flno, clause=""):
    return {
        "kind": "法規", "name": name, "revision": revision,
        "article": "第 %s 條%s" % (flno, clause),
        "url": "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=%s&flno=%s"
               % (pcode, flno),
    }


DANGER_LAW = ("都市危險及老舊建築物加速重建條例", "民國 112 年 12 月 06 日", "D0070249")
DANGER_RULE = ("都市危險及老舊建築物建築容積獎勵辦法", "民國 114 年 03 月 04 日", "D0070258")
RENEW_LAW = ("都市更新條例", "民國 113 年 11 月 13 日", "D0070008")
RENEW_RULE = ("都市更新建築容積獎勵辦法", "民國 114 年 01 月 13 日", "D0070027")
TDR_RULE = ("都市計畫容積移轉實施辦法", "民國 103 年 08 月 04 日", "D0070028")


def _d(flno, clause=""):
    return _c(DANGER_LAW[0], DANGER_LAW[1], DANGER_LAW[2], flno, clause)


def _dr(flno, clause=""):
    return _c(DANGER_RULE[0], DANGER_RULE[1], DANGER_RULE[2], flno, clause)


def _rl(flno, clause=""):
    return _c(RENEW_LAW[0], RENEW_LAW[1], RENEW_LAW[2], flno, clause)


def _rr(flno, clause=""):
    return _c(RENEW_RULE[0], RENEW_RULE[1], RENEW_RULE[2], flno, clause)


# ══════════════════════════════════════════════════════════════════
# 非都市土地的法定建蔽率與容積率
# ══════════════════════════════════════════════════════════════════
#
# 非都市土地使用管制規則第 9 條第 1 項。
#
# 查證後才發現：這張表只看「使用地類別」，跟使用分區無關 ——
# 鄉村區的乙建與工業區的乙建都是 60% / 240%。原本以為要用
# 「分區＋用地」兩個維度查表，那是多的。

NONURBAN_LAW = ("非都市土地使用管制規則", "民國 115 年 05 月 27 日", "D0060013")


def _nu(flno, clause=""):
    return _c(NONURBAN_LAW[0], NONURBAN_LAW[1], NONURBAN_LAW[2], flno, clause)


NONURBAN = {
    "甲種建築用地": (0.60, 2.40, "第1項第1款"),
    "乙種建築用地": (0.60, 2.40, "第1項第2款"),
    "丙種建築用地": (0.40, 1.20, "第1項第3款"),
    "丁種建築用地": (0.70, 3.00, "第1項第4款"),
    "窯業用地": (0.60, 1.20, "第1項第5款"),
    "交通用地": (0.40, 1.20, "第1項第6款"),
    "遊憩用地": (0.40, 1.20, "第1項第7款"),
    "殯葬用地": (0.40, 1.20, "第1項第8款"),
    "特定目的事業用地": (0.60, 1.80, "第1項第9款"),
}


def nonurban_intensity(designation):
    """非都市土地：由使用地類別查法定建蔽率、容積率。

    查不到就回 None —— 寧可讓使用者自己填，也不要套一個看起來合理的值。
    """
    if not designation:
        return None
    for name, (cov, far_, clause) in NONURBAN.items():
        if name in designation:
            src = _nu("9", clause)
            return {
                "designation": name,
                "coverage": {"value": cov, "source": src},
                "far": {"value": far_, "source": src},
                "note": "第9條第1項但書：直轄市或縣（市）政府得視實際需要"
                        "酌予調降並報中央主管機關備查，請向當地主管機關確認。",
            }
    return None


# ══════════════════════════════════════════════════════════════════
# 危老重建（都市危險及老舊建築物）
# ══════════════════════════════════════════════════════════════════
#
# 同一個 group 內的項目「不得重複申請」，只能擇一 —— 這是條文明訂的，
# 不是我推的（獎勵辦法第4條第2項、第5條第2項、第6條第2項、第9條第2項）。
#
# second=True 表示屬於獎勵辦法第 7～10 條，依第 12 條必須先申請第 3～6 條，
# 加總後仍未達條例上限者才可以再申請。

DANGER_ITEMS = [
    {"key": "orig", "group": "orig", "label": "原建築容積高於基準容積",
     "pct": 0.10, "source": _dr("3"),
     "note": "或逕依原建築容積建築，二擇一。"},

    {"key": "danger1", "group": "danger", "label": "經認定有危險之虞應限期拆除",
     "pct": 0.10, "source": _dr("4", "第1項第1款")},
    {"key": "danger2", "group": "danger", "label": "結構安全性能評估未達最低等級",
     "pct": 0.08, "source": _dr("4", "第1項第2款")},
    {"key": "danger3", "group": "danger", "label": "結構安全性能評估之其他情形",
     "pct": 0.06, "source": _dr("4", "第1項第3款")},

    {"key": "small", "group": "small",
     "label": "基地未達 200 ㎡ 且鄰接建物屋齡未達 30 年",
     "pct": 0.02, "source": _dr("4-1"),
     "note": "與規模獎勵條件互斥（規模獎勵要基地達 200 ㎡ 以上），"
             "不可能同時取得。"},

    {"key": "setback4", "group": "setback", "label": "退縮建築（道路退縮淨寬 ≥ 4m）",
     "pct": 0.10, "source": _dr("5", "第1項第1款"),
     "note": "須同時自計畫道路及現有巷道退縮淨寬 ≥ 4m、淨空設計、"
             "設置無遮簷人行步道，且與鄰地境界線淨寬 ≥ 2m 並淨空。"},
    {"key": "setback2", "group": "setback", "label": "退縮建築（道路退縮淨寬 ≥ 2m）",
     "pct": 0.08, "source": _dr("5", "第1項第2款")},

    {"key": "seismic_label", "group": "seismic", "label": "耐震設計標章",
     "pct": 0.10, "source": _dr("6", "第1項第1款")},
    {"key": "seismic1", "group": "seismic", "label": "耐震能力評估 第一級",
     "pct": 0.06, "source": _dr("6", "第1項第2款第1目")},
    {"key": "seismic2", "group": "seismic", "label": "耐震能力評估 第二級",
     "pct": 0.04, "source": _dr("6", "第1項第2款第2目")},
    {"key": "seismic3", "group": "seismic", "label": "耐震能力評估 第三級",
     "pct": 0.02, "source": _dr("6", "第1項第2款第3目")},

    {"key": "green_d", "group": "green", "label": "綠建築 鑽石級", "pct": 0.10,
     "source": _dr("7", "第1項第1款"), "second": True},
    {"key": "green_g", "group": "green", "label": "綠建築 黃金級", "pct": 0.08,
     "source": _dr("7", "第1項第2款"), "second": True},
    {"key": "green_s", "group": "green", "label": "綠建築 銀級", "pct": 0.06,
     "source": _dr("7", "第1項第3款"), "second": True},
    {"key": "green_b", "group": "green", "label": "綠建築 銅級", "pct": 0.04,
     "source": _dr("7", "第1項第4款"), "second": True, "maxArea": 500},
    {"key": "green_p", "group": "green", "label": "綠建築 合格級", "pct": 0.02,
     "source": _dr("7", "第1項第5款"), "second": True, "maxArea": 500},

    {"key": "smart_d", "group": "smart", "label": "智慧建築 鑽石級", "pct": 0.10,
     "source": _dr("8", "第1項第1款"), "second": True},
    {"key": "smart_g", "group": "smart", "label": "智慧建築 黃金級", "pct": 0.08,
     "source": _dr("8", "第1項第2款"), "second": True},
    {"key": "smart_s", "group": "smart", "label": "智慧建築 銀級", "pct": 0.06,
     "source": _dr("8", "第1項第3款"), "second": True},
    {"key": "smart_b", "group": "smart", "label": "智慧建築 銅級", "pct": 0.04,
     "source": _dr("8", "第1項第4款"), "second": True, "maxArea": 500},
    {"key": "smart_p", "group": "smart", "label": "智慧建築 合格級", "pct": 0.02,
     "source": _dr("8", "第1項第5款"), "second": True, "maxArea": 500},

    {"key": "acc_label", "group": "acc", "label": "無障礙住宅建築標章", "pct": 0.05,
     "source": _dr("9", "第1項第1款"), "second": True},
    {"key": "acc1", "group": "acc", "label": "無障礙環境 第一級", "pct": 0.04,
     "source": _dr("9", "第1項第2款第1目"), "second": True},
    {"key": "acc2", "group": "acc", "label": "無障礙環境 第二級", "pct": 0.03,
     "source": _dr("9", "第1項第2款第2目"), "second": True},
]

DANGER_GENERAL_CAP = 0.30    # 條例第6條第1項：獎勵後不得超過 1.3 倍基準容積
DANGER_EXTRA_CAP = 0.10      # 條例第6條第4項：時程＋規模合計上限，不受上項限制

# 時程獎勵的級距以「重建計畫申請日」判斷，每年 5 月 12 日換日。
#
# 條例 106/05/10 公布、自公布日施行，依中央法規標準法第13條起算至第三日
# 生效，所以基準日是 106/05/12（西元 2017-05-12）。
#
# 條例第6條第2項只列到施行後第 8 年（113/05/12～114/05/11，1%），
# 第 9 年起沒有級距 —— 也就是 114/05/12（2025-05-12）之後沒有時程獎勵。
# 事務所舊表上的「時程+規模 10%」在今天只能靠規模獎勵單獨達成，
# 所以這一項一定要用申請日去算，不能照抄舊案的 10%。
DANGER_TIME_TIERS = [
    ("2017-05-12", "2020-05-11", 0.10, "第2項第1款"),
    ("2020-05-12", "2021-05-11", 0.08, "第2項第2款"),
    ("2021-05-12", "2022-05-11", 0.06, "第2項第3款"),
    ("2022-05-12", "2023-05-11", 0.04, "第2項第4款"),
    ("2023-05-12", "2024-05-11", 0.02, "第2項第5款"),
    ("2024-05-12", "2025-05-11", 0.01, "第2項第6款"),
]


def danger_scale_bonus(area_m2):
    """危老基地規模獎勵 —— 這一項完全可以自動算，不必問使用者。

    條例第6條第3項：面積達 200 ㎡ 給 2%，每增加 100 ㎡ 再加 0.5%，上限 10%。
    要拿滿 10% 需要 1,800 ㎡。
    """
    if not area_m2 or area_m2 < 200:
        return {"key": "scale", "label": "基地規模獎勵", "pct": 0.0,
                "source": _d("6", "第3項"), "auto": True,
                "note": "基地面積未達 200 ㎡，無規模獎勵。"}
    pct = min(0.02 + math.floor((area_m2 - 200) / 100) * 0.005, 0.10)
    return {
        "key": "scale", "label": "基地規模獎勵", "pct": pct,
        "source": _d("6", "第3項"), "auto": True,
        "note": "基地 %s ㎡：達 200 ㎡ 給 2%%，每增 100 ㎡ 再加 0.5%%，"
                "上限 10%%（需 1,800 ㎡ 才滿額）。" % round(area_m2, 2),
    }


def danger_time_bonus(apply_date=None):
    """危老時程獎勵。apply_date 為重建計畫申請日（YYYY-MM-DD）。"""
    d = apply_date or datetime.date.today().isoformat()
    for lo, hi, pct, clause in DANGER_TIME_TIERS:
        if lo <= d <= hi:
            return {"key": "time", "label": "時程獎勵", "pct": pct,
                    "source": _d("6", clause), "auto": True,
                    "note": "依重建計畫申請日 %s 判定。" % d}
    return {"key": "time", "label": "時程獎勵", "pct": 0.0,
            "source": _d("6", "第2項"), "auto": True,
            "note": "條例第6條第2項之時程獎勵級距僅至施行後第 8 年"
                    "（114/05/11 止）；申請日 %s 已無時程獎勵。" % d}


def danger_program(area_m2, apply_date=None):
    """組出危老這一套的完整資訊：可選項目、自動項目、上限。"""
    items = []
    for it in DANGER_ITEMS:
        c = dict(it)
        if it.get("maxArea") and area_m2 and area_m2 >= it["maxArea"]:
            c["disabled"] = True
            c["disabledReason"] = ("基地面積 ≥ %d ㎡ 者不適用本級距"
                                   "（獎勵辦法第7條第2項、第8條第2項）"
                                   % it["maxArea"])
        items.append(c)
    return {
        "key": "danger",
        "title": "危老重建容積獎勵",
        "law": DANGER_LAW[0],
        "revision": DANGER_LAW[1],
        "url": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=" + DANGER_LAW[2],
        "auto": [danger_time_bonus(apply_date), danger_scale_bonus(area_m2)],
        "items": items,
        "caps": {
            "general": DANGER_GENERAL_CAP,
            "extra": DANGER_EXTRA_CAP,
            "generalNote": "獎勵後建築容積不得超過基準容積 1.3 倍"
                           "（或原建築容積 1.15 倍，二擇一取有利者）。",
            "extraNote": "時程獎勵與規模獎勵合計上限 10%，不受上開 1.3 倍限制"
                         "（條例第6條第4項）。",
            "source": _d("6"),
        },
        "order": "獎勵辦法第12條：須先申請第3～6條（原容積、危險、規模、退縮、耐震），"
                 "加總後仍未達條例上限者，始得申請第7～10條"
                 "（綠建築、智慧建築、無障礙、公設捐贈）。",
        "sunset": "條例第5條第2項：重建計畫之申請期限至 116 年 5 月 31 日止。",
        "appliesTo": "全國（中央法律，不分縣市）",
        "eligibility": "適用對象限經結構安全性能評估之合法建築物，"
                       "且不適用於實施容積管制前已興建完成之建築物以外者；"
                       "是否符合危老要件應先向當地主管建築機關確認。",
    }


# ══════════════════════════════════════════════════════════════════
# 容積移轉
# ══════════════════════════════════════════════════════════════════
#
# 中央辦法只有 30% / 40% 兩個數字，全文沒有依道路寬度分級的規定 ——
# 分級是地方依第 4 條授權自訂的「審查許可條件」。
# 所以同一塊地在新竹市與苗栗縣會得到不同上限，必須逐縣市查。
# 只放已逐條查證過的縣市，其餘退回中央 30% 並註明未登錄。

TDR_CENTRAL = {
    "default": 0.30, "max": 0.40,
    "source": _c(TDR_RULE[0], TDR_RULE[1], TDR_RULE[2], "8"),
    "note": "中央辦法為基準容積 30%「為原則」；屬整體開發地區、實施都市更新"
            "地區、面臨永久性空地或其他都市計畫指定地區者得放寬至 40%。"
            "依臨接道路寬度分級係地方依第4條授權自訂，非中央規定。",
}

TDR_LOCAL = {
    "新竹市": {
        "law": "新竹市都市計畫容積移轉審查許可規則",
        "revision": "民國 110 年 02 月修正",
        "article": "第 7 條",
        "tiers": [(15.0, None, 0.30, "第1項"), (10.0, 15.0, 0.20, "第2項"),
                  (7.2, 10.0, 0.10, "第3項")],
        "bonus": 0.10,
        "bonusNote": "屬整體開發地區、實施都市更新地區、面臨永久性空地或其他"
                     "都市計畫指定地區者，經都市設計審議委員會同意得酌予增加"
                     "基準容積 10%（第7條第4項但書）。",
        "notes": [
            "未臨接寬度達 7.2 公尺之道路者，不得為接受基地（第6條第1項第2款）。",
            "相鄰接之道路寬度得予併計，包含經市府指定之現有巷道（第7條第4項）。",
            "所有容積移轉申請案件一律提送都市設計審議委員會審議（第3條第1項）。",
            "農業區、河川區、風景區、保護區不得為接受基地（第6條第1項）。",
            "接受基地地下室開挖率以 85% 為限（第9條）。",
        ],
    },
    "苗栗縣": {
        "law": "苗栗縣都市計畫容積移轉許可審查標準",
        "revision": "民國 113 年 12 月修正",
        "article": "第 5-1 條",
        "tiers": [(15.0, None, 0.30, "第3項"), (12.0, 15.0, 0.20, "第2項"),
                  (8.0, 12.0, 0.10, "第1項")],
        "bonus": 0.20,
        "bonusCap": 0.40,
        "bonusNote": "經都市設計審議委員會同意，得增加移入容積以不超過基準容積"
                     "20% 為原則，且總移入容積不得超過基準容積 40%"
                     "（第5-1條第4項）。",
        "notes": [
            "接受基地應面臨 8 公尺以上計畫道路，面寬 ≥ 10 公尺，"
            "面積 ≥ 300 ㎡（第4條第1項）。",
            "夾雜之現有巷道寬度不得予以併計（第4條第2項，與新竹市相反）。",
            "移入容積應有 50% 以上以繳納容積代金方式辦理（第5-3條第1項）。",
            "總獎勵容積超過基準容積 50% 者，應提都市設計審議委員會審議"
            "（第8條第1項第3款）。",
            "農業區、保護區、風景區、遊樂區、行水區及山坡地範圍不得為接受基地。",
        ],
    },
}


def tdr_program(county, road_width_m=None):
    """容積移轉：依縣市與接受基地臨接道路寬度，判定移入上限。

    道路寬度不在地籍或分區圖資裡，猜不得 —— 沒給就回傳未定，
    由使用者輸入。
    """
    loc = TDR_LOCAL.get(county)
    base = {
        "key": "tdr", "title": "容積移轉",
        "law": TDR_RULE[0], "revision": TDR_RULE[1],
        "url": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=" + TDR_RULE[2],
        "formula": "移入容積 = 送出基地面積 × (送出基地公告現值 ÷ 接受基地公告現值)"
                   " × 接受基地容積率（實施辦法第9條第1項）",
        "scope": "送出基地與接受基地須位於同一主要計畫地區範圍內"
                 "（實施辦法第7條第1項）。",
        "appliesTo": ("%s（依地籍查詢確認之縣市，適用該縣市自訂之審查許可條件）"
                      % county) if county else "尚未確認縣市，僅顯示中央辦法之規定",
    }
    if not loc:
        base.update({
            "pct": TDR_CENTRAL["default"] if road_width_m else None,
            "maxPct": TDR_CENTRAL["max"],
            "source": TDR_CENTRAL["source"],
            "note": TDR_CENTRAL["note"],
            "unverified": "尚未查證 %s 的容積移轉審查許可條件，"
                          "上限暫以中央辦法 30%% 表示；實際級距請查該縣市自訂之"
                          "審查許可條件。" % (county or "此縣市"),
            "notes": [],
        })
        return base

    src = {"kind": "法規", "name": loc["law"], "revision": loc["revision"],
           "article": loc["article"]}
    base["notes"] = loc["notes"]
    base["bonusNote"] = loc.get("bonusNote")
    base["tiers"] = [
        {"min": t[0], "max": t[1], "pct": t[2], "clause": t[3]} for t in loc["tiers"]
    ]
    if not road_width_m:
        base.update({"pct": None, "source": src,
                     "note": "請輸入接受基地臨接道路寬度，才能判定移入上限級距。"})
        return base

    for lo, hi, pct, clause in loc["tiers"]:
        if road_width_m >= lo and (hi is None or road_width_m < hi):
            s = dict(src)
            s["article"] = loc["article"] + clause
            base.update({
                "pct": pct, "source": s,
                "maxPct": loc.get("bonusCap", pct + loc.get("bonus", 0)),
                "note": "臨接道路 %s 公尺 → 移入上限為基準容積 %d%%。"
                        % (road_width_m, round(pct * 100)),
            })
            return base

    lowest = min(t[0] for t in loc["tiers"])
    base.update({
        "pct": 0.0, "source": src,
        "note": "臨接道路 %s 公尺，未達 %s 之最低門檻 %s 公尺，"
                "不得為接受基地。" % (road_width_m, loc["law"], lowest),
    })
    return base


# ══════════════════════════════════════════════════════════════════
# 都市更新
# ══════════════════════════════════════════════════════════════════

RENEW_ITEMS = [
    {"key": "orig", "label": "原建築容積高於基準容積",
     "pct": 0.10, "source": _rr("5"),
     "note": "依原建築容積建築，或給予基準容積 10%。"},
    {"key": "danger", "label": "危險建築／結構評估未達最低等級",
     "pct": 0.10, "source": _rr("6"),
     "note": "限期拆除、強制拆除或有危險之虞者 10%；結構安全性能評估"
             "未達最低等級者 8%。不得累計。"},
    {"key": "welfare", "label": "協助取得或開闢公益設施", "cap": 0.30,
     "source": _rr("7"),
     "note": "獎勵容積 = 設施建築總樓地板面積 × 獎勵係數，上限基準容積 30%。"},
    {"key": "publicland", "label": "捐贈公共設施用地", "cap": 0.15,
     "source": _rr("8"),
     "note": "= 公設用地面積 ×（公設用地公告現值 ÷ 基地公告現值）× 基地容積率，"
             "上限基準容積 15%。以容積移轉方式辦理者不適用本條。"},
    {"key": "heritage", "label": "古蹟、歷史建築整體保存", "source": _rr("9"),
     "note": "古蹟、歷史建築、紀念建築、聚落建築群 × 1.5；都計指定應保存"
             "建築 × 1.0，均另不計入容積。以容積移轉辦理者不適用。"},
    {"key": "green", "label": "綠建築標章", "pct": 0.10, "source": _rr("10"),
     "note": "鑽石 10%／黃金 8%／銀 6%／銅 4%／合格 2%，不得累計。"},
    {"key": "smart", "label": "智慧建築標章", "pct": 0.10, "source": _rr("11"),
     "note": "鑽石 10%／黃金 8%／銀 6%／銅 4%／合格 2%，不得累計。"},
    {"key": "acc", "label": "無障礙環境", "pct": 0.05, "source": _rr("12"),
     "note": "無障礙住宅建築標章 5%；住宅性能評估第一級 4%、第二級 3%。"},
]

RENEW_CAPS = [
    {"key": "general", "label": "一般更新單元", "text": "≤ 基準容積 × 1.5",
     "cap": 0.50},
    {"key": "orig", "label": "原建築容積高於基準容積",
     "text": "≤ 基準容積 × 0.3 ＋ 原建築容積，或 ≤ 原建築容積 × 1.2，擇優"},
    {"key": "hazard", "label": "海砂屋等危險建築", "text": "≤ 原建築容積 × 1.3",
     "note": "選用本款者不得再申請其他容積獎勵項目（條例第65條第3項）。"},
    {"key": "strategic", "label": "策略性更新地區",
     "text": "≤ 基準容積 × 2，或 ≤ 基準容積 × 0.5 ＋ 原建築容積", "cap": 1.00},
]


def renew_program():
    return {
        "key": "renew", "title": "都市更新容積獎勵",
        "appliesTo": "全國（中央法律）；地方另訂之獎勵上限見下方",
        "law": RENEW_LAW[0], "revision": RENEW_LAW[1],
        "url": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=" + RENEW_LAW[2],
        "items": RENEW_ITEMS,
        "caps": RENEW_CAPS,
        "capSource": _rl("65"),
        "localCap": "地方自治法規另訂之獎勵上限為基準容積 20%；"
                    "依策略性更新地區辦理者為 40%（條例第65條第6項）。",
        "dedup": "另依其他法令申請容積獎勵者，獎勵重複部分應予扣除"
                 "（獎勵辦法第4條）。",
        "eligibility": "須先劃定更新單元並經核定實施都市更新事業，"
                       "適用與否應向當地都市更新主管機關確認。",
    }


# ══════════════════════════════════════════════════════════════════
# 綜合設計（開放空間）
# ══════════════════════════════════════════════════════════════════

def open_space_program(zone_name, area_m2):
    """建築技術規則第十五章。先做資格檢核，再給公式。

    門檻是條文明訂的：商業區與市場用地 ≥ 1000 ㎡，
    住宅區、文教區、風景區、機關用地 ≥ 1500 ㎡，
    且臨接 ≥ 8m 道路、連續臨接長度 ≥ 25m 或 ≥ 基地周界總長 1/6。
    """
    z = zone_name or ""
    if any(k in z for k in ("商業", "市場")):
        need, kind = 1000, "商業區、市場用地"
    elif any(k in z for k in ("住宅", "文教", "風景", "機關")):
        need, kind = 1500, "住宅區、文教區、風景區、機關用地"
    else:
        return {
            "key": "openspace", "title": "綜合設計（開放空間）獎勵",
            "eligible": False,
            "reason": "本章適用分區限住宅區、文教區、風景區、機關用地、"
                      "商業區與市場用地；本案分區為「%s」，"
                      "請確認是否屬上開分區。" % (z or "未知"),
            "source": rules.OPEN_SPACE["source"]["適用"],
        }
    ok = bool(area_m2) and area_m2 >= need
    return {
        "key": "openspace", "title": "綜合設計（開放空間）獎勵",
        "eligible": ok,
        "reason": ("基地 %s ㎡ ≥ %s（%s）門檻，面積條件符合；"
                   "尚須符合臨接 8 公尺以上道路且連續臨接長度 ≥ 25 公尺"
                   "或 ≥ 基地周界總長 1/6。"
                   % (round(area_m2 or 0, 2), need, kind)) if ok else
                  ("基地 %s ㎡ 未達 %s（%s）之最小面積門檻，不適用本章。"
                   % (round(area_m2 or 0, 2), need, kind)),
        "threshold": need,
        "formula": "△FA1 = S × I；I（鼓勵係數）= 容積率 × 2/5",
        "iCap": ("商業區、市場用地 I ≤ 2.5；住宅區、文教區、風景區、機關用地"
                 " 0.5 ≤ I ≤ 1.5（第286條第1項第1款但書）"),
        "sMin": "開放空間有效面積 S ≥ 法定空地面積 × 60%（第287條）",
        "coef": rules.OPEN_SPACE["coef"],
        "capNote": rules.OPEN_SPACE["cap_note"],
        "source": rules.OPEN_SPACE["source"]["獎勵"],
    }


# ══════════════════════════════════════════════════════════════════
# 地方獎勵（縣市自治條例與都市計畫土管要點）
# ══════════════════════════════════════════════════════════════════
#
# 這一區最容易出錯，因為每個都市計畫的土管要點都可能不一樣，而且事務所
# 的舊表常常只寫一個百分比、不寫法源。查證的結果是：那些百分比多半不是
# 法定寫法，而是套進公式後的結果。
#
# 例：竹南藝文段那份表寫「臨計畫道路3.5米(以上)退縮獎勵 16.75% = 1,350.00 ㎡」。
# 苗栗縣騎樓沿街步道空間設置自治條例第6條寫的是 △FA = S × I，商業區 I = 3。
# 1,350 ÷ 3 = 450 ㎡ 的沿街步道面積 —— 對得起來。所以正確做法是實作公式，
# 而不是把 16.75% 或 20% 抄進程式。
#
# 「上限20%」也不是憑空來的：自治條例第6條把上限準用到都市計畫法臺灣省
# 施行細則第34條之3第1項第2款「建築基地一點二倍之法定容積」，也就是
# 增額上限 20%。

PROVINCIAL_RULE = ("都市計畫法臺灣省施行細則", "民國 89 年 12 月 29 日訂定", "D0070012")

# 六都不適用臺灣省施行細則，它們有自己的自治條例
MUNICIPALITIES = ("臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市")


def _pv(flno, clause=""):
    return _c(PROVINCIAL_RULE[0], PROVINCIAL_RULE[1], PROVINCIAL_RULE[2], flno, clause)


PROVINCIAL_BONUS_CAP = {
    "key": "provincial_cap",
    "title": "獎勵容積總上限（臺灣省施行細則）",
    "appliesTo": "臺灣省各縣市之都市計畫地區（六都不適用，六都有自己的自治條例）",
    "law": PROVINCIAL_RULE[0],
    "revision": PROVINCIAL_RULE[1],
    "url": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=" + PROVINCIAL_RULE[2],
    "source": _pv("34-3", "第1項"),
    "normal": 0.20,      # 1.2 倍法定容積 → 增額 20%
    "renewal": 0.50,     # 1.5 倍法定容積 → 增額 50%
    "text": "各土地使用分區除增額容積及依本法第83條之1規定可移入容積外，"
            "於法定容積增加建築容積後，不得超過下列規定："
            "一、依都市更新法規實施都市更新事業之地區：建築基地 1.5 倍之法定容積，"
            "或各該建築基地 0.3 倍之法定容積再加其原建築容積。"
            "二、前款以外之地區：建築基地 1.2 倍之法定容積。",
    "note": "容積移轉（本法第83條之1）與增額容積不計入本項上限。",
    "caution": "危老條例與都市更新條例為法律位階，另訂有其專屬上限"
               "（危老 1.3 倍基準容積、都更 1.5 倍基準容積），"
               "與本項之競合關係應向當地主管建築機關確認。"
               "本項主要用於檢核依地方自治條例與土管要點取得之獎勵。",
}


# 苗栗縣騎樓沿街步道空間設置自治條例
# 逐條查證自 https://law.miaoli.gov.tw/glrsnewsout/LawContent.aspx?id=FL033441
MIAOLI_WALKWAY = {
    "key": "walkway_miaoli",
    "label": "沿街步道空間退縮獎勵",
    "law": "苗栗縣騎樓沿街步道空間設置自治條例",
    "revision": "民國 114 年 06 月 23 日修正（民國 88 年 12 月 28 日發布）",
    "url": "https://law.miaoli.gov.tw/glrsnewsout/LawContent.aspx?id=FL033441",
    "trigger": "都市計畫地區內，建築基地臨接 7 公尺以上計畫道路者，"
               "應退縮建築留設沿街步道空間（第2條，另有 7 款例外）。",
    "spec": "臨接道路全長應留設 3.5 公尺寬以上之空間，"
            "其中供步行之專用道淨寬不得小於 2 公尺（第3條）。",
    "formula": "△FA = S × I",
    "formulaNote": "S：沿街步道式開放空間面積；I：鼓勵係數（第6條）。",
    "coef": {"商業區": 3.0, "其他分區": 2.0},
    "setbackWidth": 3.5,
    "capRef": "第6條明定 △FA 不得超過都市計畫法臺灣省施行細則"
              "第34條之3第1項第2款之規定（法定容積 1.2 倍，即增額 20%）。",
    "source": {"kind": "法規", "name": "苗栗縣騎樓沿街步道空間設置自治條例",
               "article": "第 6 條", "revision": "民國 114 年 06 月 23 日"},
}


# 已知存在、但百分比訂在個別都市計畫的土管要點裡，本系統尚未逐案登錄。
# 寧可告訴使用者「有這一項、去哪裡查」，也不要把舊案的百分比抄進來當法規。
PLAN_SPECIFIC = {
    "苗栗縣": [
        {"label": "大街廓整體開發獎勵",
         "where": "訂於各該都市計畫之土地使用分區管制要點",
         "seenIn": "竹南科學園區暨周邊地區特定區計畫（科技商務專用區）曾採 12%",
         "lookup": "https://urbanplan.miaoli.gov.tw/BooksPictures/LandUsePartitionControlPoints"},
        {"label": "開發時程獎勵、來賓車位獎勵",
         "where": "訂於各該都市計畫之土地使用分區管制要點",
         "seenIn": "竹南科學園區暨周邊地區特定區計畫",
         "lookup": "https://urbanplan.miaoli.gov.tw/BooksPictures/LandUsePartitionControlPoints"},
    ],
}


COMMERCIAL_EXACT = ("商業區",)

# 新竹市等地把商業區簡寫成「商一」「商二」；這些是分級，仍是商業區。
COMMERCIAL_SHORT = tuple("商" + c for c in "一二三四五六七八九十")


def is_commercial_zone(zone_name):
    """判斷分區是不是自治條例第6條所稱的「商業區」。

    回傳 (是否商業區, 需要人工確認的提醒或 None)。

    一開始寫成 `"商" in zone_name`，結果「科技商務專用區」被判成商業區，
    鼓勵係數從 2 變成 3 —— 憑空多給五成獎勵，而且畫面上看起來完全正常。
    分區名稱裡有「商」字的專用區不少（科技商務、工商綜合、商業服務…），
    所以改成：叫得出「商業區」三個字、或是商一～商十這種分級寫法才算，
    其餘一律用「其他分區」的係數 2（取低），並在有「商」字時提醒人工確認。
    """
    z = (zone_name or "").strip()
    if not z:
        return False, None
    if any(k in z for k in COMMERCIAL_EXACT):
        return True, None
    if z in COMMERCIAL_SHORT:
        return True, None
    if "商" in z:
        return False, ("分區名稱「%s」含「商」字但不是「商業區」，"
                       "已取較低的鼓勵係數 I = 2。若該都市計畫將本分區"
                       "視同商業區，請查土管要點後自行改用 I = 3。" % z)
    return False, None


def walkway_program(county, zone_name, frontage_m=None, urban=True,
                    location_confirmed=True, mixed_zone=False):
    """沿街步道退縮獎勵。目前只有苗栗縣查證過自治條例。

    轄區把關（使用者要求「位置要屬實才能套入相對應的獎勵，不能跨區套用」）：

      1. 這是苗栗縣的地方自治條例，只在苗栗縣有效。別的縣市回 None，
         不是回一個「參考值」—— 給了就會有人拿去用。
      2. 自治條例第2條寫的是「都市計畫地區內」，非都市土地不適用。
      3. 地號要真的查到（location_confirmed），否則縣市只是使用者在選單
         上選的，沒有任何東西證明這塊地在苗栗縣。
      4. 基地跨分區時，鼓勵係數 I 是 3 還是 2 無法確定，只回說明不給數字。

    S 需要臨路長度才算得出來，而臨路長度不在地籍圖資裡（哪一邊臨路、
    臨幾公尺，要看建築線指示），所以由使用者輸入，不猜。
    """
    if county != "苗栗縣":
        return None
    if not location_confirmed:
        return {
            "key": "walkway", "title": "沿街步道空間退縮獎勵（地方自治條例）",
            "blocked": True,
            "blockedReason": "地號未查到，無法確認基地確實位於苗栗縣，"
                             "不套用地方自治條例之獎勵。",
        }
    if not urban:
        return {
            "key": "walkway", "title": "沿街步道空間退縮獎勵（地方自治條例）",
            "law": MIAOLI_WALKWAY["law"], "url": MIAOLI_WALKWAY["url"],
            "blocked": True,
            "blockedReason": "本自治條例第2條適用於「都市計畫地區內」，"
                             "本案為非都市土地，不適用。",
        }

    w = MIAOLI_WALKWAY
    is_comm, comm_note = is_commercial_zone(zone_name)
    coef_v = w["coef"]["商業區"] if is_comm else w["coef"]["其他分區"]
    out = {
        "key": "walkway", "title": "沿街步道空間退縮獎勵（地方自治條例）",
        "law": w["law"], "revision": w["revision"], "url": w["url"],
        "appliesTo": "苗栗縣都市計畫地區（本案：苗栗縣・都市計畫區，已由地籍與"
                     "分區圖資確認）",
        "trigger": w["trigger"], "spec": w["spec"],
        "formula": w["formula"], "formulaNote": w["formulaNote"],
        "coefUsed": coef_v,
        "coefWhy": "本案分區「%s」→ 鼓勵係數 I = %s（商業區 3、其他分區 2）"
                   % (zone_name or "未知", coef_v),
        "coefCaution": comm_note,
        "setbackWidth": w["setbackWidth"],
        "capRef": w["capRef"],
        "source": w["source"],
    }
    if mixed_zone:
        out["blocked"] = True
        out["blockedReason"] = ("基地跨越兩種以上使用分區，鼓勵係數 I "
                                "（商業區 3、其他分區 2）無法自動判定，"
                                "請分區分算後以「＋新增獎勵容積」填入。")
        return out
    if not zone_name:
        out["blocked"] = True
        out["blockedReason"] = "查不到使用分區，無法判定鼓勵係數 I，不自動套用。"
        return out
    if frontage_m:
        s_area = frontage_m * w["setbackWidth"]
        out.update({
            "frontageM": frontage_m,
            "sArea": round(s_area, 2),
            "deltaFA": round(s_area * coef_v, 2),
            "calc": "S = 臨路長 %s m × 退縮 %s m = %s ㎡；△FA = %s × %s = %s ㎡"
                    % (frontage_m, w["setbackWidth"], round(s_area, 2),
                       round(s_area, 2), coef_v, round(s_area * coef_v, 2)),
        })
    else:
        out["need"] = "請輸入臨接計畫道路長度（公尺），才能算出 S 與 △FA。"
    return out


# ══════════════════════════════════════════════════════════════════
# 總裝：依基地條件回傳所有適用的獎勵法規
# ══════════════════════════════════════════════════════════════════

def applicable(county=None, urban=True, zone_name=None, designation=None,
               area_m2=None, road_width_m=None, apply_date=None,
               frontage_m=None, location_confirmed=True, mixed_zone=False):
    """給基地條件，回傳適用的容積獎勵法規清單。

    這裡只回答「哪些法規適用、上限多少、法源是什麼」，
    不替使用者決定「這個案子拿得到幾項」—— 危老要不要件、有沒有劃更新單元、
    退縮做不做得出來，都是個案判斷，程式沒有資格代答。
    """
    out = {"county": county, "urban": bool(urban), "programs": []}

    if not urban:
        # 非都市土地不適用都市計畫法系的容積獎勵
        nu = nonurban_intensity(designation)
        out["nonurban"] = nu
        out["programs"].append({
            "key": "nonurban", "title": "非都市土地容積管制",
            "law": NONURBAN_LAW[0], "revision": NONURBAN_LAW[1],
            "url": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode="
                   + NONURBAN_LAW[2],
            "note": "非都市土地不適用都市計畫法系之容積移轉、都市更新與"
                    "危老重建容積獎勵；工業區丁種建築用地另有第9-1條之"
                    "投資額、能源管理與太陽光電容積獎勵（上限法定容積 15%，"
                    "容積率上限 400%）。",
            "intensity": nu,
        })
        return out

    out["locationConfirmed"] = bool(location_confirmed)
    out["programs"].append(danger_program(area_m2, apply_date))
    out["programs"].append(
        tdr_program(county if location_confirmed else None, road_width_m))
    out["programs"].append(renew_program())
    out["programs"].append(open_space_program(zone_name, area_m2))

    wp = walkway_program(county, zone_name, frontage_m, urban=urban,
                         location_confirmed=location_confirmed,
                         mixed_zone=mixed_zone)
    if wp:
        out["programs"].append(wp)

    # 非六都適用臺灣省施行細則的獎勵容積總上限
    if county not in MUNICIPALITIES:
        out["provincialCap"] = PROVINCIAL_BONUS_CAP
        out["programs"].append(PROVINCIAL_BONUS_CAP)

    # 已知存在但百分比訂在個別都市計畫裡的項目：告訴使用者去哪裡查，
    # 不要把舊案的百分比抄成法規值
    out["planSpecific"] = PLAN_SPECIFIC.get(county, []) if location_confirmed else []
    if not location_confirmed:
        out["scopeWarning"] = (
            "地號未查到，無法確認基地實際所在的縣市與都市計畫區，"
            "因此不套用任何地方法規（容積移轉的地方級距、地方自治條例之"
            "獎勵）。中央法規（危老、都更、建築技術規則）不受影響。")
    out["localCaution"] = (
        "各都市計畫之土地使用分區管制要點另可能訂有退縮、開發時程、"
        "大街廓整體開發等獎勵項目，百分比逐案不同，本系統只登錄已查證到"
        "條文的項目；其餘請查該案所屬都市計畫之土管要點。")
    return out
