#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容積分析引擎的回帶驗算。

這裡的期望值不是我算出來的，是建築師事務所實際製表的數字 ——
使用者提供的 13 份「開發面積預估表 / 土地開發坪效分析表」。
把基地面積、容積率、獎勵條件餵進 far.analyze()，跑出來的每一格
都要跟事務所的表對得起來，差距容許 0.02 ㎡（他們的表本身就是
逐格四捨五入到小數點後兩位，會累積誤差）。

為什麼要這樣測
--------------
容積試算最危險的不是當掉，是「看起來很合理但少算一項」。
機電設備的計算基數就是活生生的例子：一開始想當然耳寫成
「乘允設容積」，回帶竹南藝文段才發現退縮獎勵要排除在基數外
（見 far.mep_base 的註解）。沒有這些真實案例，那個錯會一路帶到
使用者的評估報告裡。

執行
----
    python -m unittest tests.test_far -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import far  # noqa: E402


TOL = 0.02


def cell(result, section_key, row_key):
    """從結果裡撈某一格的 m²。"""
    for s in result["sections"]:
        if s["key"] != section_key:
            continue
        for r in s["rows"]:
            if r["key"] == row_key:
                return r["m2"]
    raise KeyError("%s/%s 不在結果裡" % (section_key, row_key))


class Case(unittest.TestCase):
    def near(self, got, want, what):
        self.assertIsNotNone(got, "%s 沒有值" % what)
        self.assertAlmostEqual(
            got, want, delta=TOL,
            msg="%s：算出 %s，事務所的表是 %s" % (what, got, want))


class TestJiuSheBase(Case):
    """新竹市舊社段10地號案 方案二（基準容積）—— 112.07.15

    住一 法定容積180%、法定建蔽率60%，基地 725.00 ㎡。
    最單純的一案：沒有獎勵、沒有容移，用來釘住 e~m 的基本鏈條。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 725.00},
            "zone": {"name": "住一", "far": 1.80, "coverage": 0.60},
            "bonuses": [],
            "transfer": {"pct": 0},
            "floors": {
                "mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075,
                "penthouse": {"coveragePct": 0.60, "floors": 3},
                "basement": {"digRate": 0.85, "floors": 1},
            },
        })

    def test_capacity(self):
        self.near(cell(self.out, "capacity", "base"), 1305.00, "a 法定基準容積")
        self.near(cell(self.out, "capacity", "allowed"), 1305.00, "d 合計允設容積")

    def test_floors(self):
        self.near(cell(self.out, "floors", "f"), 195.75, "f 機電設備")
        self.near(cell(self.out, "floors", "g"), 121.68, "g 梯廳")
        self.near(cell(self.out, "floors", "h"), 121.68, "h 陽台")
        self.near(cell(self.out, "floors", "i"), 163.13, "i 屋突")
        self.near(cell(self.out, "floors", "j"), 1744.11, "j 地上層不含屋突")
        self.near(cell(self.out, "floors", "k"), 1907.24, "k 地上層含屋突")
        self.near(cell(self.out, "floors", "l"), 616.25, "l 地下層")
        self.near(cell(self.out, "floors", "m"), 2523.49, "m 總樓地板")


class TestJiuSheTransfer(Case):
    """舊社段10 方案一（基準容積＋容移30%）—— 112.07.11

    容積移轉會計入機電設備的基數（f = 15% × 1,696.50，不是 15% × 1,305）。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 725.00},
            "zone": {"name": "住一", "far": 1.80, "coverage": 0.60},
            "bonuses": [],
            "transfer": {"pct": 0.30},
            "floors": {
                "mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075,
                "penthouse": {"coveragePct": 0.60, "floors": 3},
                "basement": {"digRate": 0.85, "floors": 2},
            },
        })

    def test_all(self):
        self.near(cell(self.out, "capacity", "transfer"), 391.50, "c 容積移轉")
        self.near(cell(self.out, "capacity", "allowed"), 1696.50, "d 合計")
        self.near(cell(self.out, "floors", "f"), 254.48, "f 機電（基數含容移）")
        self.near(cell(self.out, "floors", "g"), 158.19, "g 梯廳")
        self.near(cell(self.out, "floors", "h"), 158.19, "h 陽台")
        self.near(cell(self.out, "floors", "l"), 1232.50, "l 地下層")
        self.near(cell(self.out, "floors", "m"), 3662.97, "m 總樓地板")


class TestJiuSheUrbanRenewal(Case):
    """舊社段10 方案三（基準容積＋危老28%）—— 112.07.15

    危老獎勵一樣計入機電基數（f = 15% × 1,670.40）。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 725.00},
            "zone": {"name": "住一", "far": 1.80, "coverage": 0.60},
            "bonuses": [{"key": "danger", "label": "危老獎勵", "pct": 0.28,
                         "countsToMep": True}],
            "transfer": {"pct": 0},
            "floors": {
                "mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075,
                "penthouse": {"coveragePct": 0.60, "floors": 3},
                "basement": {"digRate": 0.85, "floors": 2},
            },
        })

    def test_all(self):
        self.near(cell(self.out, "capacity", "danger"), 365.40, "b 危老獎勵")
        self.near(cell(self.out, "capacity", "allowed"), 1670.40, "d 合計")
        self.near(cell(self.out, "floors", "f"), 250.56, "f 機電")
        self.near(cell(self.out, "floors", "g"), 155.75, "g 梯廳")
        self.near(cell(self.out, "floors", "h"), 155.75, "h 陽台")
        self.near(cell(self.out, "floors", "j"), 2232.47, "j 地上層")
        self.near(cell(self.out, "floors", "m"), 3628.09, "m 總樓地板")


class TestZhunanYiwen(Case):
    """苗栗縣竹南鎮藝文段28、29地號案 —— 109.10.01

    這一案是整組測試裡最重要的一個，因為它把「機電設備基數要排除
    非都市計畫法系獎勵」這件事釘死了：

        f. 機房面積=15%*(a)(退縮獎勵非都計法系、不含)  15% * 10,479.07

    基準容積 8,060.83 ＋ 容移 2,418.25 ＝ 10,479.08，
    退縮獎勵 1,350.00 被排除在外。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 2121.27},
            "zone": {"name": "商業區", "far": 3.80, "coverage": 0.80},
            "bonuses": [{
                "key": "setback", "label": "臨計畫道路3.5米以上退縮獎勵",
                "base": "absolute", "m2": 1350.00,
                # 退縮獎勵不是都市計畫法系，不計入機電基數
                "countsToMep": False,
            }],
            "transfer": {"pct": 0.30},
            "floors": {
                "mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075,
                "penthouse": {"coveragePct": 0.40, "floors": 2},
                "basement": {"digRate": 0.80, "floors": 2},
            },
        })

    def test_capacity(self):
        self.near(cell(self.out, "capacity", "base"), 8060.83, "a 基準容積")
        self.near(cell(self.out, "capacity", "transfer"), 2418.25, "c 容移30%")
        self.near(cell(self.out, "capacity", "allowed"), 11829.08, "d 合計")

    def test_mep_base_excludes_setback(self):
        """機電基數 = 基準 + 容移，不含退縮獎勵。"""
        self.near(cell(self.out, "floors", "f"), 1571.86, "f 機電")

    def test_floors(self):
        self.near(cell(self.out, "floors", "g"), 1086.56, "g 梯廳")
        self.near(cell(self.out, "floors", "h"), 1086.56, "h 陽台")
        self.near(cell(self.out, "floors", "i"), 212.13, "i 屋突")
        self.near(cell(self.out, "floors", "l"), 3394.03, "l 地下層")
        self.near(cell(self.out, "floors", "m"), 19180.23, "m 總樓地板")


class TestToufenXinyi(Case):
    """苗栗縣頭份市信義段666等地號案 方案六 —— 112.09.08

    綜合設計（開放空間）獎勵同樣不計入機電基數：
        f = 15% × 8,509.92 ＝ 7,091.60（基準）＋ 1,418.32（容移）

    梯廳這一案用 5%，陽台用 10%，跟舊社段的 7.5% 不同 ——
    證明這兩個比例必須可調，不能寫死。

    另註：表上寫「暫估開挖率75%」，但單層面積 2,482.06 ÷ 3,545.80
    ＝ 70.0%，實際採用的是 70%。這種標示與算式不一致的情況，正是
    我們每一列都要印出算式的理由。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 3545.80},
            "zone": {"name": "住宅區", "far": 2.00, "coverage": 0.60},
            "bonuses": [{
                "key": "openspace", "label": "綜合設計開放空間獎勵",
                "base": "absolute", "m2": 1205.57,
                "countsToMep": False,
            }],
            "transfer": {"pct": 0.20},
            "floors": {
                "mepPct": 0.15, "lobbyPct": 0.05, "balconyPct": 0.10,
                "penthouse": {"coveragePct": 0.50, "floors": 3},
                "basement": {"digRate": 0.70, "floors": 3},
            },
        })

    def test_capacity(self):
        self.near(cell(self.out, "capacity", "base"), 7091.60, "a 基準容積")
        self.near(cell(self.out, "capacity", "transfer"), 1418.32, "c 容移20%")
        self.near(cell(self.out, "capacity", "allowed"), 9715.49, "d 合計")

    def test_floors(self):
        self.near(cell(self.out, "floors", "f"), 1276.49, "f 機電（排除綜合設計獎勵）")
        self.near(cell(self.out, "floors", "g"), 578.53, "g 梯廳 5%")
        self.near(cell(self.out, "floors", "h"), 1157.05, "h 陽台 10%")
        self.near(cell(self.out, "floors", "i"), 664.84, "i 屋突")
        self.near(cell(self.out, "floors", "j"), 12727.56, "j 地上層")
        self.near(cell(self.out, "floors", "l"), 7446.18, "l 地下層")


class TestDatongTechZone(Case):
    """苗栗縣竹南鎮大同段680、681地號 —— 113.01.10

    科技商務專用區 360%/60%，兩項土管內獎勵合計 20%。
    這一案的表格式不同（獎勵先合計再算），只驗容積段。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 2543.15},
            "zone": {"name": "科技商務專用區", "far": 3.60, "coverage": 0.60},
            "bonuses": [
                {"key": "walkway", "label": "苗栗沿街步道退縮獎勵", "pct": 0.08},
                {"key": "block", "label": "大街廓整體開發獎勵", "pct": 0.12},
            ],
            "transfer": {"pct": 0},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.07, "balconyPct": 0.08,
                       "penthouse": {"coveragePct": 0.40, "floors": 3},
                       "basement": {"digRate": 0.80, "floors": 4}},
        })

    def test_capacity(self):
        self.near(cell(self.out, "capacity", "base"), 9155.34, "基準容積")
        self.near(cell(self.out, "capacity", "walkway"), 732.43, "沿街步道退縮 8%")
        self.near(cell(self.out, "capacity", "block"), 1098.64, "大街廓整體開發 12%")
        self.near(cell(self.out, "capacity", "allowed"), 10986.41, "合計允建容積")
        self.assertAlmostEqual(self.out["totals"]["farAllowed"], 432.00, delta=0.05)

    def test_site_derived(self):
        self.near(cell(self.out, "zone", "buildArea"), 1525.89, "最大建築面積")
        self.near(cell(self.out, "floors", "i"), 381.47, "屋突三層(建蔽率40%)")
        self.near(cell(self.out, "floors", "l"), 8138.08, "地下室80%開挖四層")


class TestZhongliaoParking(Case):
    """新竹市中寮段783-2地號等十筆 —— 停車與多筆地號合計

    法定停車：(8,324.74 − 300) ÷ 150 + 1 ＝ 54.50 → 55 輛
    """

    def setUp(self):
        self.parcels = [
            {"sect": "中寮段", "no": "783-2", "areaM2": 192.01},
            {"sect": "中寮段", "no": "787", "areaM2": 467.50},
            {"sect": "中寮段", "no": "788", "areaM2": 383.21},
            {"sect": "中寮段", "no": "788-1", "areaM2": 51.22},
            {"sect": "中寮段", "no": "789", "areaM2": 140.32},
            {"sect": "中寮段", "no": "790", "areaM2": 199.36},
            {"sect": "中寮段", "no": "800", "areaM2": 24.06},
            {"sect": "中寮段", "no": "801", "areaM2": 560.61},
            {"sect": "中寮段", "no": "802", "areaM2": 275.50},
            {"sect": "中寮段", "no": "803", "areaM2": 578.79},
        ]

    def test_parcel_sum(self):
        out = far.analyze({
            "site": {"parcels": self.parcels},
            "zone": {"name": "第一之一種住宅區", "far": 2.00, "coverage": 0.60},
            "transfer": {"pct": 0.20},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.05, "balconyPct": 0.10,
                       "basement": {"digRate": 0.75, "floors": 2}},
        })
        self.near(out["netAreaM2"], 2872.58, "十筆地號面積合計")
        self.near(cell(out, "capacity", "base"), 5745.16, "基準容積")
        self.near(cell(out, "capacity", "transfer"), 1149.03, "容移20%")
        self.near(cell(out, "zone", "buildArea"), 1723.55, "建築面積")
        self.near(cell(out, "zone", "openArea"), 1149.03, "法定空地")
        self.near(cell(out, "floors", "l"), 4308.87, "地下2層開挖75%")

    def test_legal_parking(self):
        """停車算式的形狀：(檢討面積 − 免設額度) ÷ 級距 + 起算，無條件進位。"""
        out = far.analyze({
            "site": {"parcels": self.parcels},
            "zone": {"far": 2.00, "coverage": 0.60},
            "transfer": {"pct": 0.20},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.05, "balconyPct": 0.10},
            "parking": {"basis": "e+f+g", "exemptM2": 300, "stepM2": 150,
                        "startCars": 1},
        })
        pk = [r for s in out["sections"] if s["key"] == "parking"
              for r in s["rows"] if r["key"] == "legalCar"][0]
        self.assertEqual(pk["cars"], 55, "法定汽車位應為 55 輛")


class TestSalesModels(Case):
    """銷售面積的三種算法，各自對到實際的事務所製表。

    這一組是補寫的。原本分子寫死成「允設容積＋機電＋陽台」，跟舊社段那份
    表差了 428 ㎡ —— 公設比的定義是公設佔總銷售的比例，分子再把免計容積
    加進去等於算了兩次。是使用者拿舊社段回頭對才發現的，測試沒守到。
    """

    def _sale(self, params):
        out = far.analyze(params)
        return cell(out, "sales", "sale")

    def test_jiushe_allowed_base(self):
        """舊社段三份表：允設容積 ÷ (1 − 1/3) = 允設容積 × 1.5。"""
        for far_pct, transfer, bonus, want in (
                (1.80, 0.0, None, 1957.50),      # 方案二 基準容積
                (1.80, 0.30, None, 2544.75),     # 方案一 ＋容移 30%
                (1.80, 0.0, 0.28, 2505.60)):     # 方案三 ＋危老 28%
            p = {
                "site": {"areaM2": 725.00},
                "zone": {"far": far_pct, "coverage": 0.60},
                "bonuses": ([{"key": "d", "label": "危老", "pct": bonus}]
                            if bonus else []),
                "transfer": {"pct": transfer},
                "floors": {"mepPct": 0.15, "lobbyPct": 0.075,
                           "balconyPct": 0.075},
                "sales": {"model": "ratio", "base": "allowed",
                          "commonRatio": 1.0 / 3.0},
            }
            self.near(self._sale(p), want, "舊社段 捌 預估總銷售")

    def test_zhongliao_allowed_plus_balcony_base(self):
        """新竹中寮段：(允設容積 + 陽台) ÷ (1 − 29.5%) = 10,959.8。

        該案允設容積 6,894.19（基準 5,745.16 ＋ 容移 1,149.03），
        陽台 832.47。
        """
        p = {
            "site": {"areaM2": 2872.58},
            "zone": {"far": 2.00, "coverage": 0.60},
            "transfer": {"pct": 0.20},
            # 這份表的梯廳是直接乘 5%（7,928.32 × 5% = 396.42），
            # 不是上立那種自我參照式
            "floors": {"mepPct": 0.15, "lobbyPct": 0.05, "balconyPct": 0.10,
                       "lobbyMode": "simple"},
            "sales": {"model": "ratio", "base": "allowed+bal",
                      "commonRatio": 0.295},
        }
        out = far.analyze(p)
        self.near(cell(out, "capacity", "allowed"), 6894.19, "允設容積")
        self.near(cell(out, "floors", "g"), 396.42, "梯廳（直接乘）")
        self.near(cell(out, "floors", "h"), 832.47, "陽台")
        self.near(self._sale(p), 10959.81, "中寮段 銷售面積")

    def test_lobby_modes_differ(self):
        """兩種梯廳寫法算出來必須不同，否則選項形同虛設。"""
        base = {
            "site": {"areaM2": 725.00},
            "zone": {"far": 1.80, "coverage": 0.60},
        }
        a = far.analyze(dict(base, floors={
            "mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075,
            "lobbyMode": "self"}))
        b = far.analyze(dict(base, floors={
            "mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075,
            "lobbyMode": "simple"}))
        self.near(cell(a, "floors", "g"), 121.68, "自我參照式（舊社段）")
        self.near(cell(b, "floors", "g"), 112.56, "直接乘")

    def test_base_choice_changes_result(self):
        """三種分子算出來的數字必須不同 —— 否則這個選項形同虛設。"""
        base = {
            "site": {"areaM2": 725.00},
            "zone": {"far": 1.80, "coverage": 0.60},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075},
        }
        vals = []
        for b in ("allowed", "allowed+bal", "allowed+mep+bal"):
            p = dict(base)
            p["sales"] = {"model": "ratio", "base": b, "commonRatio": 0.32}
            vals.append(self._sale(p))
        self.assertEqual(len(set(vals)), 3, "三種分子不該算出一樣的數字")
        self.assertLess(vals[0], vals[1])
        self.assertLess(vals[1], vals[2])

    def test_default_base_is_allowed(self):
        """沒指定時用允設容積 —— 這是最通行、也不會重複計入的定義。"""
        p = {
            "site": {"areaM2": 725.00},
            "zone": {"far": 1.80, "coverage": 0.60},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075},
            "sales": {"model": "ratio", "commonRatio": 1.0 / 3.0},
        }
        self.near(self._sale(p), 1957.50, "預設分子應為允設容積")


class TestUnitCount(Case):
    """預估戶數的三種算法。

    原本只有「銷售坪 ÷ 每戶坪數」，那是倒推：每戶坪數填成 9 就會算出
    91 戶，數字明顯不合理卻沒有任何東西擋下來。改成以樓層 × 每層戶數
    為預設，並反推每戶平均坪當作合理性檢查。
    """

    P = {
        "site": {"areaM2": 725.00},
        "zone": {"far": 1.80, "coverage": 0.60},
        "floors": {"mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075},
    }

    def _units(self, sales):
        out = far.analyze(dict(self.P, sales=sales))
        for s in out["sections"]:
            if s["key"] == "sales":
                for r in s["rows"]:
                    if r["key"] == "units":
                        return r
        return None

    def test_floors_mode_is_default(self):
        r = self._units({"model": "ratio", "commonRatio": 0.32,
                         "aboveFloors": 10, "unitsPerFloor": 2})
        self.assertEqual(r["units"], 20.0)
        self.assertIn("地上 10 層 × 每層 2 戶", r["formula"])

    def test_ground_floor_counted_separately(self):
        """一樓另計：大同段那份「一樓3戶，2~15樓每層12戶」。"""
        r = self._units({"model": "ratio", "commonRatio": 0.32,
                         "aboveFloors": 15, "unitsPerFloor": 12,
                         "groundUnits": 3})
        self.assertEqual(r["units"], 12 * 14 + 3)
        self.assertIn("一樓 3 戶", r["formula"])

    def test_direct_mode(self):
        r = self._units({"model": "ratio", "commonRatio": 0.32,
                         "unitsMode": "direct", "units": 22})
        self.assertEqual(r["units"], 22.0)

    def test_ping_mode_still_available(self):
        r = self._units({"model": "ratio", "commonRatio": 0.32,
                         "unitsMode": "ping", "pingPerUnit": 37})
        self.assertIsNotNone(r)
        self.assertIn("坪/戶", r["formula"])

    def test_average_ping_flags_outlier(self):
        """戶數離譜時要標出來 —— 舊版就是缺這個。"""
        out = far.analyze(dict(self.P, sales={
            "model": "ratio", "commonRatio": 0.32,
            "aboveFloors": 10, "unitsPerFloor": 10}))   # 100 戶，太多
        rows = [r for s in out["sections"] if s["key"] == "sales"
                for r in s["rows"] if r["key"] == "unitAvg"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("outlier"), "每戶約 5.9 坪，應標為異常")

    def test_average_ping_normal_not_flagged(self):
        out = far.analyze(dict(self.P, sales={
            "model": "ratio", "commonRatio": 0.32,
            "aboveFloors": 10, "unitsPerFloor": 2}))    # 20 戶
        rows = [r for s in out["sections"] if s["key"] == "sales"
                for r in s["rows"] if r["key"] == "unitAvg"]
        self.assertFalse(rows[0].get("outlier"))


class TestParkingPerUnit(Case):
    """依土管「一戶一車位」計算法定停車 —— 上立竹北家興段334、335地號案。

    那份表寫的是：
        n. 預估法定汽車停車：土管二十六條(一)住宅一戶一車位 = 22 輛
        　 預估法定來賓汽車停車：土管二十六條(三)應加設5%來賓停車空間
        　 且不得出售 5% = 2 輛
        o. 預估自設停車：2 輛
        p. 預估汽車停車合計：n+o = 26 輛
        q. 預估法定機車停車：土管為都審地區，一戶一機車位 = 22 輛

    法源順位在建築技術規則第59條第1項寫得很清楚：
    「依都市計畫法令或都市計畫書之規定，其未規定者，依下表規定」——
    土管有訂就從土管，附表是備位。原本只實作了附表那條路。
    """

    def setUp(self):
        self.out = far.analyze({
            "site": {"areaM2": 880.42},
            "zone": {"name": "住宅區", "far": 2.00, "coverage": 0.50},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075},
            "parking": {
                "mode": "perUnit", "carsPerUnit": 1, "guestPct": 0.05,
                "extraCars": 2, "motoPerUnit": 1,
                "lawNote": "變更高速鐵路新竹車站特定區計畫細部計畫"
                           "土地使用分區管制要點第26條第1款",
            },
            "sales": {"model": "ratio", "base": "allowed",
                      "commonRatio": 0.35,
                      "unitsMode": "direct", "units": 22},
        })

    def _car(self, key):
        for s in self.out["sections"]:
            if s["key"] == "parking":
                for r in s["rows"]:
                    if r["key"] == key:
                        return r
        return None

    def test_legal_is_one_per_unit(self):
        self.assertEqual(self._car("legalCar")["cars"], 22)

    def test_guest_five_percent(self):
        """22 × 5% = 1.1 → 進位 2 輛。"""
        self.assertEqual(self._car("guestCar")["cars"], 2)

    def test_total(self):
        self.assertEqual(self._car("totalCar")["cars"], 26)

    def test_motorcycle_one_per_unit(self):
        self.assertEqual(self._car("moto")["cars"], 22)

    def test_law_note_becomes_the_source(self):
        """土管條次是使用者填的，要當成法源顯示，沒填則標為無依據。"""
        r = self._car("legalCar")
        self.assertIsNotNone(r["source"])
        self.assertIn("第26條第1款", r["source"]["name"])
        self.assertFalse(r["assumed"])

    def test_priority_row_cites_article_59(self):
        r = self._car("legalBasis")
        self.assertIn("第 59 條", r["source"]["article"])

    def test_missing_law_note_is_flagged(self):
        out = far.analyze({
            "site": {"areaM2": 880.42},
            "zone": {"far": 2.00, "coverage": 0.50},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075},
            "parking": {"mode": "perUnit", "carsPerUnit": 1},
            "sales": {"model": "ratio", "unitsMode": "direct", "units": 22},
        })
        r = [x for s in out["sections"] if s["key"] == "parking"
             for x in s["rows"] if x["key"] == "legalCar"][0]
        self.assertTrue(r["assumed"])
        self.assertIn("土管條次", r["note"])

    def test_units_from_floors_feed_parking(self):
        """戶數由樓層算出時，法定車位要跟著走 —— 這是計算順序的測試。"""
        out = far.analyze({
            "site": {"areaM2": 880.42},
            "zone": {"far": 2.00, "coverage": 0.50},
            "floors": {"mepPct": 0.15, "lobbyPct": 0.075, "balconyPct": 0.075},
            "parking": {"mode": "perUnit", "carsPerUnit": 1,
                        "lawNote": "土管第26條"},
            "sales": {"model": "ratio", "aboveFloors": 11, "unitsPerFloor": 2},
        })
        r = [x for s in out["sections"] if s["key"] == "parking"
             for x in s["rows"] if x["key"] == "legalCar"][0]
        self.assertEqual(r["cars"], 22)

    def test_no_units_says_so(self):
        out = far.analyze({
            "site": {"areaM2": 880.42},
            "zone": {"far": 2.00, "coverage": 0.50},
            "floors": {"mepPct": 0.15},
            "parking": {"mode": "perUnit", "carsPerUnit": 1},
            "sales": {"model": "ratio", "unitsMode": "direct"},
        })
        r = [x for s in out["sections"] if s["key"] == "parking"
             for x in s["rows"] if x["key"] == "legalCar"][0]
        self.assertIsNone(r.get("cars"))
        self.assertIn("需先有戶數", r["formula"])


class TestBasement(Case):
    """地下層面積的三種給法。

    地下室不一定是全開挖，各層也不一定一樣大 —— B1 因車道與退縮而比
    B2 小是常態。原本只有「基地 × 開挖率 × 層數」一種，而且開挖率
    在畫面上還改不到，只能吃預設的 80%。
    """

    SITE = {"areaM2": 880.42}
    ZONE = {"far": 2.00, "coverage": 0.50}

    def _l(self, basement):
        out = far.analyze({
            "site": self.SITE, "zone": self.ZONE,
            "floors": {"mepPct": 0.15, "lobbyPct": 0.075,
                       "balconyPct": 0.075, "basement": basement},
        })
        for s in out["sections"]:
            if s["key"] == "floors":
                for r in s["rows"]:
                    if r["key"] == "l":
                        return r
        return None

    def test_rate_mode(self):
        r = self._l({"digRate": 0.80, "floors": 2})
        self.near(r["m2"], 880.42 * 0.80 * 2, "開挖率 80% × 2 層")
        self.assertIn("80.00%", r["formula"])

    def test_rate_is_adjustable(self):
        """開挖率不是法規值，改了就要跟著變。"""
        a = self._l({"digRate": 0.80, "floors": 2})["m2"]
        b = self._l({"digRate": 0.65, "floors": 2})["m2"]
        self.assertNotAlmostEqual(a, b, delta=1.0)
        self.near(b, 880.42 * 0.65 * 2, "開挖率 65%")

    def test_area_per_floor_mode(self):
        """設計者已知實際輪廓時，直接給單層面積。"""
        r = self._l({"mode": "area", "areaPerFloor": 646.63, "floors": 2})
        self.near(r["m2"], 1293.26, "竹北家興段：646.63 × 2 層")
        self.assertIn("單層", r["formula"])

    def test_per_floor_areas_mode(self):
        """逐層面積相加 —— B1 比 B2 小。"""
        r = self._l({"mode": "areas", "floorAreas": [520.0, 700.0, 700.0]})
        self.near(r["m2"], 1920.0, "B1 520 ＋ B2 700 ＋ B3 700")
        self.assertIn("B1", r["formula"])
        self.assertIn("B3", r["formula"])
        self.assertIn("3 層", r["note"])

    def test_per_floor_ignores_floor_count(self):
        """逐層給面積時，層數由清單長度決定，不看 floors 欄位。"""
        r = self._l({"mode": "areas", "floorAreas": [500.0, 500.0],
                     "floors": 9})
        self.near(r["m2"], 1000.0, "只有兩層")

    def test_manual_modes_are_flagged_assumed(self):
        """人工給的面積沒有任何依據，要標出來。"""
        for b in ({"mode": "area", "areaPerFloor": 600, "floors": 2},
                  {"mode": "areas", "floorAreas": [600, 600]}):
            self.assertTrue(self._l(b)["assumed"])

    def test_zero_floors_gives_zero(self):
        r = self._l({"digRate": 0.80, "floors": 0})
        self.assertAlmostEqual(r["m2"], 0.0, delta=0.01)


class TestProvenance(unittest.TestCase):
    """沒有法源的係數一定要被標記出來。

    使用者的要求是「所有來源都要有依據，不能瞎猜」。引擎做不到的部分，
    至少要誠實列出來是哪幾格 —— 這條測試防止有人日後把示警拿掉。
    """

    def test_bare_numbers_are_flagged(self):
        out = far.analyze({
            "site": {"areaM2": 1000},
            "zone": {"far": 2.0, "coverage": 0.5},
            "floors": {"mepPct": 0.15},
        })
        labels = [a["label"] for a in out["assumed"]]
        self.assertIn("法定容積率", labels)
        self.assertIn("法定建蔽率", labels)
        self.assertIn("機電設備空間", labels)

    def test_cited_numbers_are_not_flagged(self):
        src = {"law": "都市計畫法臺灣省施行細則", "article": "第32條",
               "url": "https://law.moj.gov.tw/"}
        out = far.analyze({
            "site": {"areaM2": 1000},
            "zone": {"far": {"value": 2.0, "source": src},
                     "coverage": {"value": 0.5, "source": src},
                     "source": src},
            "floors": {"mepPct": {"value": 0.15, "source": src}},
        })
        labels = [a["label"] for a in out["assumed"]]
        self.assertNotIn("法定容積率", labels)
        self.assertNotIn("機電設備空間", labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
