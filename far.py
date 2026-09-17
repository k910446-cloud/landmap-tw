#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容積分析 —— 開發面積預估表的計算引擎。

這支模組只做算術，不做查詢、不連網、不內建任何法規數字。

為什麼要這樣切
--------------
使用者的要求是「所有來源都要有依據，不能瞎猜」。如果把建蔽率、容積率、
獎勵上限、停車級距直接寫死在計算式裡，日後法規一修，程式就會安靜地
算錯 —— 而且沒有人看得出來是哪個數字過期了。

所以：
  * 每一個係數都由呼叫端傳進來，並且要附上 `source`（法源）。
  * 沒有法源的係數一律標記 assumed=True，畫面上會示警。
  * 這裡只保證「給定係數，算式正確」，係數對不對是 rules.py / build_laws.py 的責任。

算式怎麼來的
------------
不是憑印象寫的，是從使用者提供的 13 份建築師事務所實際製表反推、
再逐案回帶驗算到小數點後兩位（見 tests/test_far.py）。來源：

  上立建設／豪廷建築師事務所 開發面積預估表、土地開發坪效分析表
  （新竹市舊社段、中寮段、西門段、竹北家興段、苗栗竹南大同段、藝文段、
    頭份信義段、德義段、尖山段、雄基福林段）

幾個一開始想當然耳、實際回帶才發現不對的地方，都寫在對應函式的註解裡。
"""

import decimal
import math
import re

import rules

PING = 400 / 121.0          # 1 坪 = 3.3057851239669… m²，與 start.py 同一個定義


def to_ping(m2):
    return m2 / PING


def _r(v, n=2):
    """四捨五入到小數點後 n 位。事務所的表都取兩位，回帶驗算才對得起來。

    刻意不用內建的 round()。Python 的 round() 是「銀行家捨入」，遇到正好
    .5 會捨向偶數：屋突 725 × 60% ÷ 8 × 3 = 163.125，round() 給 163.12，
    而事務所的表寫 163.13。工程與財務報表用的是四捨五入，差一分錢看起來
    像我們算錯，所以這裡明確指定 ROUND_HALF_UP。
    """
    if v is None:
        return None
    try:
        q = decimal.Decimal(str(float(v))).quantize(
            decimal.Decimal(1).scaleb(-n), rounding=decimal.ROUND_HALF_UP)
    except (decimal.InvalidOperation, ValueError, OverflowError):
        return round(v + 0.0, n)
    return float(q)


class Coef:
    """一個係數 —— 值 + 它的依據。

    `source` 為 None 代表這個數字沒有法源支撐（使用者自訂、或業界慣例），
    會被標記成 assumed，前端顯示成橘色。這是刻意的：寧可畫面上難看，
    也不要讓人以為每個數字都有法規背書。
    """

    __slots__ = ("value", "source", "note")

    def __init__(self, value, source=None, note=None):
        self.value = value
        self.source = source
        self.note = note

    @property
    def assumed(self):
        return not self.source

    def as_dict(self):
        return {"value": self.value, "source": self.source,
                "note": self.note, "assumed": self.assumed}


def coef(spec, default=None, source=None, note=None):
    """把前端傳來的 JSON 轉成 Coef。

    接受三種寫法：
        0.15                                  純數字，無法源 → assumed
        {"value": 0.15, "source": {...}}       有法源
        None                                   用 default
    """
    if spec is None:
        return Coef(default, source, note)
    if isinstance(spec, dict):
        return Coef(spec.get("value", default),
                    spec.get("source", source),
                    spec.get("note", note))
    return Coef(spec, source, note)


def row(key, label, formula, m2, *, pct=None, source=None, note=None,
        assumed=False, ping=None):
    """表格的一列。

    formula 是要顯示給人看的算式字串 —— 事務所的表每一列都寫算式，
    使用者要能一眼核對我們有沒有算錯，這比只給答案重要。
    """
    return {
        "key": key,
        "label": label,
        "formula": formula,
        "m2": _r(m2),
        "ping": _r(ping if ping is not None else (to_ping(m2) if m2 is not None else None)),
        "pct": _r(pct * 100, 2) if pct is not None else None,
        "source": source,
        "note": note,
        "assumed": bool(assumed),
    }


def fmt(v, n=2):
    """千分位，給算式字串用。"""
    if v is None:
        return "—"
    return ("{:,.%df}" % n).format(v)


# ── 壹、貳　基地面積 ────────────────────────────────────────────────

AREA_FROM = {
    "registered": "登記面積",
    "service": "服務提供之面積",
    "geometry": "由圖形計算",
}


def parcel_area(p):
    """單筆地號採用的面積。

    areaOverride 優先於查到的登記面積 —— 「218部分」這種只納入一部分的
    情形（德義段那份表就有），或謄本與圖資對不起來時，都要能人工指定。
    """
    ov = p.get("areaOverride")
    if ov not in (None, ""):
        try:
            return float(ov)
        except (TypeError, ValueError):
            pass
    return float(p.get("areaM2") or 0)


def site_area(site):
    """基地面積 = 各筆地號面積合計 − 騎樓地 − 道路占用地 − 保留地。

    事務所的表把「基地面積」跟「基地使用面積」分開寫，因為容積是用
    「可使用面積」去乘的 —— 騎樓地與既成道路不能計入。苗栗大同段那份
    還另外列了「保留地面積」。三個扣除項都留著，沒填就是 0。
    """
    parcels = site.get("parcels") or []

    # 逐筆納入或排除。實務上很常見：
    #   頭份信義段那份「包括國有地662-1、662-2，不包括頭份市有地660-1」
    #   尖山段那份「不含河川區29地號面積、含國有地70地號面積」
    # 排除的地號仍然要印在表上並註明理由，不能只是消失 ——
    # 看表的人要能核對「這筆為什麼沒算進去」。
    used = [p for p in parcels if p.get("include", True)]
    dropped = [p for p in parcels if not p.get("include", True)]

    listed = sum(parcel_area(p) for p in used)
    # 允許使用者直接給總面積（業主提供、或地籍服務查不到時手動輸入）
    gross = site.get("areaM2")
    gross = float(gross) if gross not in (None, "") else listed
    if parcels:
        # 有逐筆資料時以逐筆合計為準 —— 否則勾掉一筆卻沒反映在總數上，
        # 是最難發現的錯
        gross = listed

    arcade = float(site.get("deductArcadeM2") or 0)
    road = float(site.get("deductRoadM2") or 0)
    reserve = float(site.get("deductReserveM2") or 0)
    net = gross - arcade - road - reserve

    rows = []
    for p in used:
        a = parcel_area(p)
        note = AREA_FROM.get(p.get("areaFrom"))
        if p.get("areaOverride") not in (None, ""):
            note = "人工填入" + ("（%s）" % p["note"] if p.get("note") else "")
        elif p.get("note"):
            note = (note + "・" if note else "") + p["note"]
        rows.append(row("parcel", "%s %s地號" % (p.get("sect") or "", p.get("no") or ""),
                        p.get("zoneName") or "", a,
                        source=None if p.get("areaOverride") not in (None, "")
                        else p.get("source"),
                        assumed=(p.get("areaOverride") not in (None, ""))
                        or not p.get("source"),
                        note=note))
    for p in dropped:
        r = row("parcelOut", "%s %s地號" % (p.get("sect") or "", p.get("no") or ""),
                "不納入", None, assumed=True,
                note=p.get("note") or "使用者排除")
        r["excluded"] = True
        rows.append(r)
    rows.append(row("gross", "土地面積合計",
                    "%d 筆納入%s" % (len(used),
                                     "、%d 筆排除" % len(dropped) if dropped else "")
                    if parcels else "手動輸入", gross,
                    assumed=not parcels))
    if arcade:
        rows.append(row("arcade", "騎樓地", "扣除", -arcade, assumed=True))
    if road:
        rows.append(row("road", "道路占用地", "扣除", -road, assumed=True))
    if reserve:
        rows.append(row("reserve", "保留地", "扣除", -reserve, assumed=True))
    rows.append(row("net", "基地使用面積",
                    "%s − 扣除" % fmt(gross) if (arcade or road or reserve) else "",
                    net))
    return net, rows


# ── 伍　允設容積 ────────────────────────────────────────────────────

def capacity(net_m2, zone, bonuses, transfer):
    """允設容積 = 法定基準容積 + Σ獎勵容積 + 容積移轉。

    bonuses 每一筆長這樣：
        {"key":..., "label":..., "pct":0.20, "base":"base"|"allowed"|"absolute",
         "m2": 123.4,            # base=="absolute" 時直接給面積
         "countsToMep": True,     # 是否計入機電設備的計算基數（見 mep()）
         "source": {...}}

    `base` 預設 "base"（乘基準容積）。事務所的表絕大多數獎勵都是乘基準容積，
    但綜合設計的 △FA 是用開放空間有效面積算出來的絕對值，所以要留 absolute。
    """
    far = coef(zone.get("far"))
    cov = coef(zone.get("coverage"))

    # 跨分區時要分區分算：基準容積 = Σ(各分區面積 × 該分區容積率)。
    # 拿第一筆的分區去套整塊地，在商業區帶住宅區的臨街基地會差很多，
    # 而且畫面上看起來完全正常。
    groups = zone.get("groups") or []
    if len(groups) > 1:
        detail, base = [], 0.0
        for g in groups:
            ga = float(g.get("areaM2") or 0)
            gf = coef(g.get("far"))
            amt = ga * (gf.value or 0)
            base += amt
            detail.append(row("zoneBase", "　%s" % (g.get("name") or "未知分區"),
                              "%s ㎡ × %s%%" % (fmt(ga), fmt((gf.value or 0) * 100)),
                              amt, pct=gf.value, source=gf.source,
                              assumed=gf.assumed))
        # 先給總數再列組成 —— 看表的人要的是「基準容積多少」，
        # 分區明細是拿來核對的
        rows = [row("base", "法定基準容積 FA（%d 個分區分算）" % len(groups),
                    "各分區面積 × 各該容積率之和", base,
                    pct=(base / net_m2) if net_m2 else None)] + detail
    else:
        base = net_m2 * (far.value or 0)
        rows = [row("base", "法定基準容積 FA",
                    "%s × %s%%" % (fmt(net_m2), fmt((far.value or 0) * 100)),
                    base, pct=far.value, source=far.source, assumed=far.assumed)]

    total_bonus = 0.0
    detail = []
    for b in (bonuses or []):
        mode = b.get("base") or "base"
        if mode == "absolute":
            amt = float(b.get("m2") or 0)
            # 有些獎勵不是「基準容積乘幾 %」，而是自己的公式算出來的面積
            # （例如沿街步道退縮的 △FA = S × I）。那就把算式原樣印出來，
            # 只顯示「直接給定」等於把依據藏起來。
            f = b.get("formula") or "直接給定"
            pct = (amt / base) if base else None
        else:
            pct = float(b.get("pct") or 0)
            ref = base if mode == "base" else None
            amt = (ref or 0) * pct
            f = "基準容積 × %s%%" % fmt(pct * 100)
        total_bonus += amt
        item = row(b.get("key") or "bonus", b.get("label") or "獎勵容積", f, amt,
                   pct=pct, source=b.get("source"), assumed=not b.get("source"),
                   note=b.get("note"))
        item["countsToMep"] = bool(b.get("countsToMep", True))
        detail.append(item)
        rows.append(item)

    tr_pct = float((transfer or {}).get("pct") or 0)
    tr_amt = base * tr_pct
    tr_row = row("transfer", "容積移轉",
                 "基準容積 × %s%%" % fmt(tr_pct * 100), tr_amt, pct=tr_pct,
                 source=(transfer or {}).get("source"),
                 assumed=not (transfer or {}).get("source"),
                 note=(transfer or {}).get("note"))
    # 容積移轉一律計入機電基數 —— 苗栗大同段那份表寫得最清楚：
    # 「地面層以上設備(15%) (基準容積+容移獎勵+土管內獎勵)*0.15」
    tr_row["countsToMep"] = bool((transfer or {}).get("countsToMep", True))
    if tr_pct:
        rows.append(tr_row)

    allowed = base + total_bonus + tr_amt
    rows.append(row("allowed", "合計允設容積", "基準 + 獎勵 + 容移", allowed,
                    pct=(allowed / net_m2 if net_m2 else None)))

    return {
        "base": base,
        "bonusTotal": total_bonus,
        "transfer": tr_amt,
        "allowed": allowed,
        "farAllowed": (allowed / net_m2) if net_m2 else None,
        "coverage": cov,
        "rows": rows,
        "bonusDetail": detail,
        "transferRow": tr_row if tr_pct else None,
    }


# ── 陸　設計樓地板面積 ──────────────────────────────────────────────

def mep_base(cap):
    """機電設備空間的計算基數。

    這是整份表最容易算錯的一格。原本以為就是乘「允設容積」，回帶
    竹南藝文段那份才發現不對：

        f. 機房面積=15%*(a)(退縮獎勵非都計法系、不含)  15% * 10,479.07

    a（基準容積）是 8,060.83，合計 d 是 11,829.07，而 10,479.07 =
    8,060.83 + 2,418.25（容移）—— 也就是把「非都市計畫法系」的退縮獎勵
    排除在外。苗栗大同段那份直接把規則寫在欄位名上：

        地面層以上設備(15%) (基準容積+容移獎勵+土管內獎勵)*0.15

    頭份信義段則把建築技術規則的綜合設計獎勵排除（7,091.60+1,418.32）。
    所以基數不是固定的，取決於每一項獎勵是不是「都計法系」——
    交給每筆 bonus 自己帶 countsToMep 旗標決定。
    """
    total = cap["base"]
    for b in cap["bonusDetail"]:
        if b.get("countsToMep"):
            total += b["m2"]
    tr = cap.get("transferRow")
    if tr and tr.get("countsToMep"):
        total += tr["m2"]
    return total


def floors(net_m2, cap, fl):
    """e ~ m 的樓地板面積推算。"""
    e = cap["allowed"]

    mep = coef(fl.get("mepPct"), 0.15)
    lobby = coef(fl.get("lobbyPct"), 0.075)
    balcony = coef(fl.get("balconyPct"), 0.075)
    awning = coef(fl.get("awningPct"), 0.0)

    rows = [row("e", "允設容積樓地板面積", "＝伍、合計", e)]

    # f 機電設備空間
    mb = mep_base(cap)
    f = mb * (mep.value or 0)
    rows.append(row("f", "機電設備空間",
                    "%s × %s%%" % (fmt(mb), fmt((mep.value or 0) * 100)),
                    f, source=mep.source, assumed=mep.assumed,
                    note="基數＝基準容積＋計入之獎勵與容移" if abs(mb - e) > 0.01 else None))

    # g 梯廳 —— 兩種寫法都在使用者提供的表裡出現過，差很多：
    #
    #   "self"（預設）自我參照：g = r × (e+f+g)，解出 g = (e+f) × r/(1−r)
    #          上立事務所的表用這個。舊社段方案二：
    #          0.0811 × 1,500.75 = 121.68，而 1,500.75 = e+f。
    #          法規上免計上限是對「該層樓地板面積」的比例，g 本身也在那
    #          層樓地板裡，所以分母含 g 才是條文的讀法。
    #
    #   "simple" 直接乘：g = r × (e+f)
    #          新竹中寮段那份用這個：7,928.32 × 5.00% = 396.42，
    #          而 7,928.32 = 允設容積 6,894.19 + 機電 1,034.13。
    #
    # 兩者在 7.5% 時差約 8%，會一路影響陽台、地上層面積與銷售面積，
    # 所以不能挑一種寫死。
    lr = lobby.value or 0
    mode = fl.get("lobbyMode") or "self"
    if mode == "simple":
        g = (e + f) * lr
        g_formula = "(%s) × %s%%" % (fmt(e + f), fmt(lr * 100))
    else:
        g = (e + f) * (lr / (1 - lr)) if lr < 1 else 0.0
        g_formula = "(%s) × %s%% ÷ (1−%s%%)" % (fmt(e + f), fmt(lr * 100),
                                                fmt(lr * 100))
    rows.append(row("g", "梯廳", g_formula, g,
                    source=lobby.source, assumed=lobby.assumed,
                    note=None if mode == "self" else "直接乘（不含梯廳自身）"))

    # h 陽台 —— 基數含 f，不含 h 自己（回帶舊社段：7.5% × (e+f+g)）
    br = balcony.value or 0
    h = (e + f + g) * br
    rows.append(row("h", "陽台",
                    "(%s) × %s%%" % (fmt(e + f + g), fmt(br * 100)),
                    h, source=balcony.source, assumed=balcony.assumed))

    aw = awning.value or 0
    awning_m2 = (e + f + g) * aw
    if aw:
        rows.append(row("h2", "雨遮", "(%s) × %s%%" % (fmt(e + f + g), fmt(aw * 100)),
                        awning_m2, source=awning.source, assumed=awning.assumed))

    # i 屋突 = 建築面積 ÷ 8 × 層數
    #
    # 表上寫「屋突＝預估建蔽率60%/8*3」，回帶 725 × 0.6 ÷ 8 × 3 = 163.13 ✓。
    # 分母 8 是建築技術規則對屋頂突出物水平投影面積的限制，但各案採用的
    # 建蔽率不一定等於法定建蔽率（西門段法定 80%、表上用 70%），所以
    # 讓使用者自己填，預設帶法定建蔽率。
    ph = fl.get("penthouse") or {}
    ph_cov = coef(ph.get("coveragePct"), (cap["coverage"].value or 0))
    ph_fl = float(ph.get("floors") or 0)
    ph_div = float(ph.get("divisor") or 8)
    i = net_m2 * (ph_cov.value or 0) / ph_div * ph_fl if ph_div else 0.0
    rows.append(row("i", "屋頂突出物",
                    "%s × %s%% ÷ %s × %s層" % (fmt(net_m2), fmt((ph_cov.value or 0) * 100),
                                               fmt(ph_div, 0), fmt(ph_fl, 0)),
                    i, source=ph_cov.source, assumed=ph_cov.assumed))

    # 地面一層免計容積（室內停車空間、公共服務空間）
    gp = coef((fl.get("groundPark") or {}).get("pct"), 0.0)
    gp_m2 = net_m2 * (cap["coverage"].value or 0) * (gp.value or 0)
    if gp.value:
        rows.append(row("i2", "地面一層免計容積停車空間",
                        "建築面積 × %s%%" % fmt((gp.value or 0) * 100), gp_m2,
                        source=gp.source, assumed=gp.assumed))

    ps = coef((fl.get("publicService") or {}).get("pct"), 0.0)
    ps_m2 = e * (ps.value or 0)
    if ps.value:
        rows.append(row("i3", "公共服務空間",
                        "允設容積 × %s%%" % fmt((ps.value or 0) * 100), ps_m2,
                        source=ps.source, assumed=ps.assumed))

    j = e + f + g + h + awning_m2 + gp_m2 + ps_m2
    rows.append(row("j", "地上層面積（不含屋突）", "e＋f＋g＋h", j))
    k = j + i
    rows.append(row("k", "地上層面積（含屋突）", "j＋i", k))

    # l 地下層面積
    #
    # 三種給法，因為地下室不一定是全開挖，各層也不一定一樣大：
    #
    #   "rate"（預設）基地面積 × 開挖率 × 層數
    #   "area"        直接給單層面積 × 層數 —— 設計者已經知道實際輪廓時用
    #   "areas"       逐層面積相加 —— B1 因車道、退縮而比 B2 小是常態
    #
    # 開挖率本身也是設計條件，不是法規值（少數縣市的土管有訂上限，
    # 例如新竹市容移審查許可規則第9條的 85%），所以一律標成假設值。
    bs = fl.get("basement") or {}
    dig = coef(bs.get("digRate"), 0.0)
    bmode = bs.get("mode") or "rate"
    bfl = float(bs.get("floors") or 0)

    if bmode == "areas":
        areas = [float(a or 0) for a in (bs.get("floorAreas") or [])]
        l = sum(areas)
        one = (l / len(areas)) if areas else 0.0
        b_formula = " ＋ ".join("B%d %s" % (i + 1, fmt(a))
                                for i, a in enumerate(areas)) or "未填各層面積"
        b_note = "共 %d 層，平均單層 %s ㎡" % (len(areas), fmt(one)) if areas else None
        bfl = float(len(areas))
    elif bmode == "area":
        one = float(bs.get("areaPerFloor") or 0)
        l = one * bfl
        b_formula = "單層 %s ㎡ × %s層" % (fmt(one), fmt(bfl, 0))
        b_note = "單層面積由設計者直接給定"
    else:
        one = net_m2 * (dig.value or 0)
        l = one * bfl
        b_formula = "%s × %s%% × %s層" % (fmt(net_m2), fmt((dig.value or 0) * 100),
                                          fmt(bfl, 0))
        b_note = "單層 %s ㎡" % fmt(one)

    rows.append(row("l", "地下層面積", b_formula, l,
                    source=dig.source if bmode == "rate" else None,
                    assumed=(dig.assumed if bmode == "rate" else True),
                    note=b_note))

    m = k + l
    rows.append(row("m", "總樓地板面積", "k＋l", m))

    return {
        "e": e, "f": f, "g": g, "h": h, "awning": awning_m2,
        "i": i, "groundPark": gp_m2, "publicService": ps_m2,
        "j": j, "k": k, "l": l, "basementOne": one, "basementFloors": bfl,
        "basementMode": bmode, "m": m,
        "mepBase": mb, "rows": rows,
    }


# ── 柒　停車 ────────────────────────────────────────────────────────

CODE59 = {
    "kind": "法規", "name": "建築技術規則建築設計施工編",
    "article": "第 59 條第1項", "revision": "民國 115 年 02 月 23 日",
    "url": "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=D0070115&flno=59",
    "note": "依都市計畫法令或都市計畫書之規定；其未規定者才依附表",
}


def parking_per_unit(pk, units):
    """依土管「住宅一戶一車位」計算法定停車，另加來賓車位與機車位。

    土管是逐個都市計畫訂的，條次各案不同，所以條號由使用者填
    （lawNote，例如「○○細部計畫土地使用分區管制要點第26條第1款」）。
    沒填就標成無法源 —— 這一格不能替使用者掛一個看起來像法條的東西。
    """
    rows = []
    if not units:
        rows.append(row("legalCar", "法定汽車停車位",
                        "依土管一戶一車位計算，需先有戶數；"
                        "請在「捌」設定地上層數與每層戶數",
                        None, assumed=True))
        return {"rows": rows, "legalCars": None, "totalCars": None}

    ratio = float(pk.get("carsPerUnit") or 1)
    legal = math.ceil(units * ratio - 1e-9)
    src = ({"kind": "法規", "name": pk.get("lawNote")} if pk.get("lawNote")
           else None)
    rows.append(row("legalCar", "法定汽車停車位",
                    "%s 戶 × %s 車位/戶" % (fmt(units, 1), fmt(ratio, 2)),
                    None, source=src, assumed=not src,
                    note=None if src else "請填土管條次（如：土管第26條第1款）"))
    rows[-1]["cars"] = legal
    rows.append(row("legalBasis", "　（法源順位）",
                    "土管有訂停車標準者從土管，未訂者依建築技術規則第59條附表",
                    None, source=CODE59))

    guest = 0
    gp = float(pk.get("guestPct") or 0)
    if gp:
        guest = math.ceil(legal * gp - 1e-9)
        rows.append(row("guestCar", "來賓停車位",
                        "法定 %d 輛 × %s%%" % (legal, fmt(gp * 100)),
                        None, source=src, assumed=not src,
                        note="依土管加設，不得出售"))
        rows[-1]["cars"] = guest

    extra = int(pk.get("extraCars") or 0)
    if extra:
        rows.append(row("extraCar", "自設汽車停車位", "設計者自訂", None))
        rows[-1]["cars"] = extra

    total = legal + guest + extra
    rows.append(row("totalCar", "汽車停車位合計",
                    "法定 %d ＋ 來賓 %d ＋ 自設 %d" % (legal, guest, extra),
                    None))
    rows[-1]["cars"] = total

    mr = pk.get("motoPerUnit")
    moto = None
    if mr not in (None, ""):
        moto = math.ceil(units * float(mr) - 1e-9)
        rows.append(row("moto", "機車停車位",
                        "%s 戶 × %s 車位/戶" % (fmt(units, 1), fmt(float(mr), 2)),
                        None, source=src, assumed=not src))
        rows[-1]["cars"] = moto

    return {"rows": rows, "legalCars": legal, "guestCars": guest,
            "totalCars": total, "motoCars": moto, "units": units}


def parking(fldata, pk, units=None):
    """法定停車位。

    建築技術規則第 59 條是一張分類分級的表（依建築物用途、都市計畫區內外，
    各有「免設額度」與「每 N ㎡ 一輛」）。那張表的實際數字必須由
    build_laws.py 從全國法規資料庫抓回來，這裡不寫死 —— 只實作算式形狀：

        車位數 = (檢討面積 − 免設額度) ÷ 級距 + 起算輛數

    這個形狀是從使用者提供的表反推的（新竹中寮段：
    (8,324.74 − 300) ÷ 150 + 1 = 54.50 → 55 輛）。

    另外有些土管會加成（西門段：商業區須為建技則規定的 1.2 倍），
    用 multiplier 表示。
    """
    if not pk:
        return {"rows": [], "legalCars": None, "totalCars": None}

    # 依土管「一戶一車位」計算 —— 建築技術規則第59條第1項明定
    # 「依都市計畫法令或都市計畫書之規定，其未規定者，依下表規定」，
    # 土管有訂就以土管為準，附表是備位規定。
    #
    # 竹北家興段那份表寫的就是這種：
    #   n. 預估法定汽車停車：土管二十六條(一)住宅一戶一車位 = 22 輛
    #   　 預估法定來賓汽車停車：土管二十六條(三)應加設5%來賓停車空間
    #   　 且不得出售 5% = 2 輛
    if (pk.get("mode") or "code") == "perUnit":
        return parking_per_unit(pk, units)

    basis_key = pk.get("basis") or "e"
    basis = {
        "e": fldata["e"],
        "e+f": fldata["e"] + fldata["f"],
        "e+f+g": fldata["e"] + fldata["f"] + fldata["g"],
        "j": fldata["j"],
    }.get(basis_key, fldata["e"])

    rows = []
    exempt = coef(pk.get("exemptM2"), None)
    step = coef(pk.get("stepM2"), None)
    startn = float(pk.get("startCars") or 0)
    mult = coef(pk.get("multiplier"), 1.0)

    legal = None
    if step.value:
        raw = max(0.0, basis - (exempt.value or 0)) / step.value + startn
        raw *= (mult.value or 1)
        legal = math.ceil(raw - 1e-9)
        rows.append(row("legalCar", "法定汽車停車位",
                        "(%s − %s) ÷ %s%s%s = %s 輛，零數進位"
                        % (fmt(basis), fmt(exempt.value or 0), fmt(step.value),
                           (" + %s" % fmt(startn, 0)) if startn else "",
                           (" ×%s" % fmt(mult.value, 2)) if (mult.value or 1) != 1 else "",
                           fmt(raw, 2)),
                        None, source=step.source, assumed=step.assumed))
        rows[-1]["cars"] = legal
    else:
        rows.append(row("legalCar", "法定汽車停車位",
                        "尚未載入建築技術規則第59條之級距，請於「法規」頁更新或手動填入",
                        None, assumed=True))

    extra = int(pk.get("extraCars") or 0)
    if extra:
        rows.append(row("extraCar", "自設汽車停車位", "設計者自訂", None))
        rows[-1]["cars"] = extra

    total = (legal or 0) + extra
    rows.append(row("totalCar", "汽車停車位合計", "法定＋自設", None))
    rows[-1]["cars"] = total

    # 機車：土管常見「一戶一機車位」，戶數要等銷售段算完才知道，
    # 所以這裡只接受直接給定的數字或每戶比例，實際值在 analyze() 收尾時補。
    moto = pk.get("motorcycles")
    if moto not in (None, ""):
        rows.append(row("moto", "機車停車位", pk.get("motoNote") or "設計者自訂", None))
        rows[-1]["cars"] = int(moto)

    return {"rows": rows, "legalCars": legal, "totalCars": total, "basis": basis}


# ── 戶數 ────────────────────────────────────────────────────────────

def unit_count(sl, sale_total_m2=None):
    """預估戶數。回傳 (戶數, 要印的列)。

    原本只有「銷售坪 ÷ 每戶坪數」一種，那是倒推 —— 每戶坪數本身就是猜的，
    猜錯（例如填成 9 坪）會得到 91 戶這種明顯不合理的數字，卻沒有任何
    東西擋下來。設計上真正決定戶數的是樓層與每層幾戶，所以預設改成那個。

    苗栗大同段那份表寫的就是這種：「1幢2棟地下4層地上15層，
    一樓3戶，2~15樓每層12戶(6拼+6拼)」。

    這個函式被抽出來，是因為法定停車若依土管「一戶一車位」計算，
    就必須先知道戶數 —— 停車要排在銷售面積之後、戶數之前。
    """
    if not sl:
        return None, []
    mode = sl.get("unitsMode") or "floors"

    if mode == "direct":
        u = sl.get("units")
        if u in (None, ""):
            return None, []
        units = float(u)
        r = row("units", "預估戶數", "設計者直接指定", None, assumed=True)

    elif mode == "ping":
        per = sl.get("pingPerUnit")
        if not per or not sale_total_m2:
            return None, []
        per = float(per)
        units = to_ping(sale_total_m2) / per
        r = row("units", "預估戶數",
                "銷售 %s 坪 ÷ %s 坪/戶" % (fmt(to_ping(sale_total_m2)), fmt(per)),
                None, assumed=True)

    else:
        up, fls = sl.get("unitsPerFloor"), sl.get("aboveFloors")
        if not up or not fls:
            return None, []
        up, fls = float(up), float(fls)
        g = float(sl.get("groundUnits") or 0)
        units = up * (fls - (1 if g else 0)) + g
        r = row("units", "預估戶數",
                ("一樓 %s 戶 ＋ 2～%s 樓每層 %s 戶"
                 % (fmt(g, 0), fmt(fls, 0), fmt(up, 0))) if g else
                ("地上 %s 層 × 每層 %s 戶" % (fmt(fls, 0), fmt(up, 0))),
                None, assumed=True)

    r["units"] = _r(units, 1)
    return units, [r]


# ── 捌～拾　銷售與坪效 ──────────────────────────────────────────────

def sales(net_m2, cap, fldata, sl, park, units=None):
    """銷售面積、戶數、車位持分、開發係數。

    使用者提供的 13 份表裡就有三種算法，數字差很多，所以模型與分子
    都做成可選，並且一律把算式印在表上。

      "ratio"  總銷售面積 = 基數 ÷ (1 − 公設比)
               基數 base 有三種寫法，實測對應到不同的事務所表：

                 "allowed"       允設容積樓地板面積
                                 舊社段三份表都是這個：1,305.00 × 1.5
                                 ＝ 1,957.50（公設比 1/3）。

                 "allowed+bal"   允設容積 + 陽台
                                 新竹中寮段那份：
                                 (6,894.19 + 832.47) ÷ (1 − 29.5%)
                                 ＝ 10,959.8，與表上相符。

                 "allowed+mep+bal"  允設容積 + 機電 + 陽台

      "sum"    總銷售面積 = 全部樓地板面積（含免計容積與地下室）
               豪廷事務所的坪效表用這個（總售坪 Q = E + L + O）。

    預設用 "allowed"。公設比的定義是「公共設施佔總銷售面積的比例」，
    分子再把機電、梯廳、陽台加進去，等於把免計容積算了兩次 ——
    一開始就是這樣寫的，跟舊社段那份表差了 428 ㎡ 才發現。
    """
    if not sl:
        return {"rows": []}

    model = sl.get("model") or "ratio"
    rows = []
    common = coef(sl.get("commonRatio"), 0.32)

    if model == "sum":
        total = fldata["m"] + fldata["h"] + fldata["awning"]
        rows.append(row("sale", "總銷售面積（含車位）", "總樓地板 ＋ 陽台雨遮", total))
        above = total - fldata["l"]
        rows.append(row("saleAbove", "地面層以上銷售面積", "總銷售 − 地下層", above))
    else:
        basis = sl.get("base") or "allowed"
        inner, basis_label = {
            "allowed": (cap["allowed"], "允設容積"),
            "allowed+bal": (cap["allowed"] + fldata["h"] + fldata["awning"],
                            "允設容積＋陽台"),
            "allowed+mep+bal": (cap["allowed"] + fldata["f"] + fldata["h"]
                                + fldata["awning"], "允設容積＋機電＋陽台"),
        }.get(basis, (cap["allowed"], "允設容積"))
        cr = common.value or 0
        total = inner / (1 - cr) if cr < 1 else inner
        rows.append(row("sale", "預估總銷售面積",
                        "%s %s ÷ (1 − %s%%)"
                        % (basis_label, fmt(inner), fmt(cr * 100)),
                        total, source=common.source, assumed=common.assumed,
                        note="公設比 %s%%" % fmt(cr * 100)))
        above = total

    if units is None:
        units, urows = unit_count(sl, total)
    else:
        _u, urows = unit_count(sl, total)
    rows.extend(urows)

    if units:
        # 反推每戶平均銷售坪，用來檢查戶數合不合理
        avg = to_ping(total) / units
        rows.append(row("unitAvg", "每戶平均銷售坪",
                        "%s 坪 ÷ %s 戶" % (fmt(to_ping(total)), fmt(units, 1)),
                        None, assumed=True))
        rows[-1]["ping"] = _r(avg)
        if avg < 12 or avg > 120:
            rows[-1]["note"] = "每戶 %s 坪，超出常見範圍，請確認戶數" % fmt(avg)
            rows[-1]["outlier"] = True

    cars = (park or {}).get("totalCars")
    if cars:
        pub = fldata["l"] / cars if cars else None
        rows.append(row("carShare", "預估車位持分（車公）",
                        "地下層 %s ÷ %s 輛" % (fmt(fldata["l"]), cars), pub,
                        assumed=True))

    site_ping = to_ping(net_m2) if net_m2 else None
    ratio = (to_ping(total) / site_ping) if site_ping else None
    rows.append(row("efficiency", "開發係數（坪效）",
                    "%s 坪 ÷ %s 坪" % (fmt(to_ping(total)), fmt(site_ping)),
                    None))
    rows[-1]["ratio"] = _r(ratio)

    return {"rows": rows, "total": total, "above": above,
            "units": units, "ratio": ratio, "model": model,
            "base": sl.get("base") or "allowed"}


def zone_groups(site, zone):
    """把納入的地號依使用分區分組，回傳 [{name, areaM2, far, coverage}]。

    每筆地號的分區是查詢時各自查出來的（見 start.site_lookup），
    所以基地跨分區時這裡就會分出兩組以上。分不出來（地號沒帶分區資訊）
    就回單一組，行為跟以前一樣。
    """
    parcels = [p for p in (site.get("parcels") or []) if p.get("include", True)]
    if not parcels or not any(p.get("zoneName") for p in parcels):
        return []

    order, acc = [], {}
    for p in parcels:
        name = p.get("zoneName") or "未知分區"
        if name not in acc:
            order.append(name)
            acc[name] = {
                "name": name,
                "areaM2": 0.0,
                "far": p.get("zoneFar") if p.get("zoneFar") is not None
                else zone.get("far"),
                "coverage": p.get("zoneCoverage")
                if p.get("zoneCoverage") is not None else zone.get("coverage"),
            }
        acc[name]["areaM2"] += parcel_area(p)
    return [acc[n] for n in order]


# ── 主函式 ──────────────────────────────────────────────────────────

def analyze(params):
    """跑一次完整的開發面積預估。

    回傳的結構刻意跟事務所的表一致（壹～拾），前端直接照著印。
    """
    site = params.get("site") or {}
    zone = params.get("zone") or {}

    net, site_rows = site_area(site)

    # 依使用分區把納入的地號分組。只有一組時等同於原本的單一分區算法。
    groups = zone_groups(site, zone)
    zone = dict(zone, groups=groups)

    cap = capacity(net, zone, params.get("bonuses"), params.get("transfer"))
    far_c = coef(zone.get("far"))
    cov_c = coef(zone.get("coverage"))
    if len(groups) > 1:
        build_area = sum(float(g.get("areaM2") or 0)
                         * (coef(g.get("coverage")).value or 0) for g in groups)
    else:
        build_area = net * (cov_c.value or 0)
    fl = floors(net, cap, params.get("floors") or {})
    # 順序有意義：法定停車若依土管「一戶一車位」計算，就得先知道戶數；
    # 而戶數在「銷售坪 ÷ 每戶坪數」模式下又要先有銷售面積。
    # 所以先預跑一次銷售拿到面積與戶數，再算停車，最後才組出正式的銷售段
    # （車位持分需要車位數）。
    pre = sales(net, cap, fl, params.get("sales"), None)
    units, _ = unit_count(params.get("sales") or {}, pre.get("total"))
    pk = parking(fl, params.get("parking"), units=units)
    sl = sales(net, cap, fl, params.get("sales"), pk, units=units)

    zone_rows = [
        row("zone", "使用分區", zone.get("plan") or "", None,
            note=zone.get("name"), source=zone.get("source"),
            assumed=not zone.get("source")),
        row("far", "法定容積率", "", None, pct=far_c.value,
            source=far_c.source, assumed=far_c.assumed),
        row("coverage", "法定建蔽率", "", None, pct=cov_c.value,
            source=cov_c.source, assumed=cov_c.assumed),
        row("buildArea", "最大建築面積",
            "%s × %s%%" % (fmt(net), fmt((cov_c.value or 0) * 100)), build_area),
        row("openArea", "法定空地面積",
            "%s − %s" % (fmt(net), fmt(build_area)), net - build_area),
    ]

    sections = [
        {"key": "site", "title": "壹、貳　基地面積", "rows": site_rows},
        {"key": "zone", "title": "叁　使用分區與法定強度", "rows": zone_rows},
        {"key": "capacity", "title": "伍　允設容積檢討", "rows": cap["rows"]},
        {"key": "floors", "title": "陸　設計樓地板面積", "rows": fl["rows"]},
        {"key": "parking", "title": "柒　停車檢討", "rows": pk["rows"]},
        {"key": "sales", "title": "捌～拾　銷售與坪效", "rows": sl["rows"]},
    ]

    # 拿設計值去對建築技術規則的法定上限。只回報、不改數字 ——
    # 超過的時候使用者要自己決定是改設計，還是這個案子有土管特別規定。
    ph = (params.get("floors") or {}).get("penthouse") or {}
    ph_floors = float(ph.get("floors") or 0)
    checks = rules.check_caps(
        {"mep": fl["f"], "balcony": fl["h"], "lobby": fl["g"],
         "penthousePerFloor": (fl["i"] / ph_floors) if ph_floors else None},
        base_fa=cap["base"],
        build_area=build_area,
        floor_area=fl["j"],
        single_stair=bool((params.get("floors") or {}).get("singleStair")),
        high_rise=bool((params.get("floors") or {}).get("highRise")),
    )

    # 把所有「沒有法源」的欄位挑出來，前端在表頭列一張清單。
    # 使用者要求所有來源都要有依據 —— 做不到的地方就要講清楚是哪幾格。
    assumed = []
    for s in sections:
        for r in s["rows"]:
            if r.get("assumed") and r.get("label"):
                assumed.append({"section": s["title"], "label": r["label"],
                                "note": r.get("note")})

    return {
        "netAreaM2": _r(net),
        "netAreaPing": _r(to_ping(net)),
        "sections": sections,
        "totals": {
            "baseFA": _r(cap["base"]),
            "allowedFA": _r(cap["allowed"]),
            "farAllowed": _r((cap["farAllowed"] or 0) * 100),
            "aboveGround": _r(fl["k"]),
            "grossFloor": _r(fl["m"]),
            "saleArea": _r(sl.get("total")),
            "efficiency": _r(sl.get("ratio")),
        },
        "assumed": assumed,
        "checks": checks,
        "zoneGroups": groups,
        "mixedZone": len(groups) > 1,
        "ping": PING,
    }


# ── 把圖資服務給的字串變成可算的數字 ──────────────────────────────

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def _cn_int(text):
    """中文數字轉阿拉伯數字：「二百四十」→ 240、「六十」→ 60。

    只處理容積率條文用得到的範圍（0～9999）。
    一開始寫成「遇到單位就把目前的數乘上去」，「六十」對，「二百四十」
    卻算成 2004 —— 位數要各自結算再累加才行。
    """
    total, num, ok = 0, 0, False
    for ch in text:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
            ok = True
        elif ch in _CN_UNIT:
            total += (num or 1) * _CN_UNIT[ch]
            num = 0
            ok = True
        else:
            return None
    return (total + num) if ok else None


def parse_ratio(text):
    """把建蔽率／容積率的原始值轉成小數（60% → 0.60，容積率 240% → 2.40）。

    各縣市 ArcGIS 圖層回來的格式差很多，實際看過的有：
        60、"60"、"60%"、"60 %"、"百分之六十"、"建蔽率60%"、"200/60"
    法規條文裡則多半寫「百分之二百四十」。

    一律當成百分比除以 100，不做任何「這個數字看起來像小數」的猜測。

    曾經寫過「大於 1.5 才除以 100」的門檻，想同時吃下 0.6 與 60 兩種寫法，
    結果 2.4 被當成 240% 除成 0.024。台灣的建蔽率、容積率在圖資與條文裡
    一律是百分比整數（60、200、240），沒有用小數表示的慣例；與其用門檻
    猜，不如規則單純、算錯時看得出來。

    回傳 None 代表看不懂，呼叫端要把這格留白並標示成需人工確認，
    不可以自己猜一個數字填進去。
    """
    if text is None:
        return None
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        v = float(text)
        return v / 100.0 if v > 0 else None
    s = str(text).strip()
    if not s:
        return None

    m = re.search(r"百分之([零一二三四五六七八九十百千]+)", s)
    if m:
        n = _cn_int(m.group(1))
        return n / 100.0 if n else None

    m = re.search(r"(\d+(?:\.\d+)?)", s.replace(",", ""))
    if not m:
        return None
    v = float(m.group(1))
    return v / 100.0 if v > 0 else None


def ratio_is_sane(value, kind):
    """粗略檢查解析出來的比例合不合理，不合理就讓呼叫端標示人工確認。

    建蔽率不可能超過 100%，容積率低於 30% 或高於 2000% 在台灣也極罕見。
    這個函式不修正數值，只回報「可不可疑」—— 修正等於猜，猜就違背了
    「所有來源都要有依據」。
    """
    if value is None:
        return False
    if kind == "coverage":
        return 0.05 <= value <= 1.0
    return 0.3 <= value <= 20.0
