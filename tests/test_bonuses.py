#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""容積獎勵目錄的測試 —— 重點在「不能跨區套用」。

為什麼要有
----------
使用者講得很明白：「位置要屬實才能套入相對應的獎勵，不能跨區套用」。

這件事壞掉的時候完全看不出來：畫面上照樣列出一個獎勵項目、照樣有百分比、
照樣有法條連結，只是那部法規根本管不到這塊地。評估報告會多出一截容積，
而且是「有法源」的樣子。所以每一條轄區判斷都要有測試釘住。

執行
----
    python -m unittest tests.test_bonuses -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bonuses  # noqa: E402


def prog(result, key):
    for p in result.get("programs", []):
        if p.get("key") == key:
            return p
    return None


class TestWalkwayScope(unittest.TestCase):
    """苗栗縣騎樓沿街步道空間設置自治條例，只在苗栗縣的都市計畫地區有效。"""

    def test_applies_in_miaoli_urban(self):
        r = bonuses.applicable(county="苗栗縣", urban=True, zone_name="商業區",
                               area_m2=2121.27, frontage_m=128.57)
        w = prog(r, "walkway")
        self.assertIsNotNone(w, "苗栗縣都市計畫區應該要有沿街步道獎勵")
        self.assertNotIn("blocked", w)
        self.assertAlmostEqual(w["deltaFA"], 1349.99, delta=0.05)

    def test_not_offered_in_other_counties(self):
        """別的縣市完全不該出現這一項 —— 連「參考值」都不行。"""
        for c in ("新竹市", "新竹縣", "臺中市", "彰化縣", "臺北市", "高雄市"):
            r = bonuses.applicable(county=c, urban=True, zone_name="商業區",
                                   area_m2=2000, frontage_m=100)
            self.assertIsNone(prog(r, "walkway"),
                              "%s 不該出現苗栗縣的沿街步道獎勵" % c)

    def test_blocked_on_nonurban_land(self):
        """自治條例第2條寫的是「都市計畫地區內」。"""
        r = bonuses.applicable(county="苗栗縣", urban=False,
                               designation="乙種建築用地", area_m2=4860)
        self.assertIsNone(prog(r, "walkway"),
                          "非都市土地不該套用都市計畫地區的地方獎勵")

    def test_blocked_when_location_unconfirmed(self):
        """地號沒查到 = 沒有東西證明這塊地在苗栗縣。"""
        r = bonuses.applicable(county="苗栗縣", urban=True, zone_name="商業區",
                               area_m2=2000, frontage_m=100,
                               location_confirmed=False)
        w = prog(r, "walkway")
        self.assertTrue(w and w.get("blocked"), "位置未確認時應擋下")
        self.assertIn("無法確認", w["blockedReason"])

    def test_blocked_when_zone_mixed(self):
        """跨分區時鼓勵係數是 3 還是 2 無從判定，不能自己挑一個。"""
        r = bonuses.applicable(county="苗栗縣", urban=True, zone_name="商業區",
                               area_m2=2000, frontage_m=100, mixed_zone=True)
        w = prog(r, "walkway")
        self.assertTrue(w and w.get("blocked"))
        self.assertNotIn("deltaFA", w)

    def test_coefficient_by_zone(self):
        """商業區 I=3、其他分區 I=2（自治條例第6條）。"""
        c = bonuses.applicable(county="苗栗縣", urban=True, zone_name="商業區",
                               area_m2=2000, frontage_m=100)
        o = bonuses.applicable(county="苗栗縣", urban=True, zone_name="住宅區",
                               area_m2=2000, frontage_m=100)
        self.assertEqual(prog(c, "walkway")["coefUsed"], 3.0)
        self.assertEqual(prog(o, "walkway")["coefUsed"], 2.0)


class TestCommercialZoneMatch(unittest.TestCase):
    """鼓勵係數的分區判定 —— 曾經把「科技商務專用區」判成商業區。

    這個錯誤最危險的地方是它不會報錯：I 從 2 變成 3，獎勵面積直接多五成，
    畫面上還附著正確的法條連結，看起來完全正常。
    """

    def test_real_commercial_zones(self):
        for z in ("商業區", "第一種商業區", "鄰里商業區", "特定商業區",
                  "商一", "商二", "商四"):
            ok, note = bonuses.is_commercial_zone(z)
            self.assertTrue(ok, "%s 應判為商業區" % z)
            self.assertIsNone(note)

    def test_zones_that_merely_contain_the_character(self):
        """名稱有「商」字但不是商業區的，要取低的係數並提醒。"""
        for z in ("科技商務專用區", "工商綜合區", "商業服務專用區"):
            ok, note = bonuses.is_commercial_zone(z)
            self.assertFalse(ok, "%s 不該判為商業區" % z)
            self.assertIsNotNone(note, "%s 應提醒人工確認" % z)
            self.assertIn("I = 2", note)

    def test_ordinary_zones(self):
        for z in ("住宅區", "第一種住宅區", "工業區", "機關用地"):
            ok, note = bonuses.is_commercial_zone(z)
            self.assertFalse(ok)
            self.assertIsNone(note, "%s 不含商字，不該有提醒" % z)

    def test_tech_business_zone_gets_lower_coefficient(self):
        r = bonuses.applicable(county="苗栗縣", urban=True,
                               zone_name="科技商務專用區",
                               area_m2=2543.15, frontage_m=100)
        w = prog(r, "walkway")
        self.assertEqual(w["coefUsed"], 2.0)
        self.assertIsNotNone(w.get("coefCaution"))


class TestTransferScope(unittest.TestCase):
    """容積移轉的道路寬度分級是各縣市自訂的，不能互相借用。"""

    def test_hsinchu_tiers(self):
        for w, want in ((6, 0.0), (8, 0.10), (12, 0.20), (20, 0.30)):
            p = bonuses.tdr_program("新竹市", w)
            self.assertAlmostEqual(p["pct"], want, delta=1e-9,
                                   msg="新竹市 臨路 %sm" % w)

    def test_miaoli_tiers(self):
        """苗栗縣的門檻是 8m，新竹市是 7.2m —— 7.5m 在兩地結果不同。"""
        self.assertAlmostEqual(bonuses.tdr_program("新竹市", 7.5)["pct"], 0.10)
        self.assertAlmostEqual(bonuses.tdr_program("苗栗縣", 7.5)["pct"], 0.0)
        for w, want in ((9, 0.10), (13, 0.20), (20, 0.30)):
            self.assertAlmostEqual(bonuses.tdr_program("苗栗縣", w)["pct"], want,
                                   msg="苗栗縣 臨路 %sm" % w)

    def test_unregistered_county_is_flagged(self):
        """沒查證過的縣市要明講，不能拿別人的級距頂替。"""
        p = bonuses.tdr_program("臺南市", 20)
        self.assertIn("unverified", p)
        self.assertNotIn("tiers", p)

    def test_no_local_tiers_without_location(self):
        r = bonuses.applicable(county="新竹市", urban=True, zone_name="住宅區",
                               area_m2=725, road_width_m=30,
                               location_confirmed=False)
        p = prog(r, "tdr")
        self.assertIn("unverified", p,
                      "位置未確認時不應套用新竹市的地方級距")
        self.assertIn("scopeWarning", r)


class TestProvincialCap(unittest.TestCase):
    """都市計畫法臺灣省施行細則第34條之3 —— 六都不適用。"""

    def test_applies_to_provincial_counties(self):
        for c in ("新竹市", "新竹縣", "苗栗縣", "彰化縣", "宜蘭縣"):
            r = bonuses.applicable(county=c, urban=True, zone_name="住宅區",
                                   area_m2=1000)
            self.assertIsNotNone(prog(r, "provincial_cap"), "%s 應適用省細則" % c)

    def test_excluded_for_municipalities(self):
        for c in ("臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市"):
            r = bonuses.applicable(county=c, urban=True, zone_name="住宅區",
                                   area_m2=1000)
            self.assertIsNone(prog(r, "provincial_cap"),
                              "%s 是直轄市，不適用臺灣省施行細則" % c)

    def test_cap_values(self):
        r = bonuses.applicable(county="苗栗縣", urban=True, zone_name="住宅區",
                               area_m2=1000)
        cap = prog(r, "provincial_cap")
        self.assertAlmostEqual(cap["normal"], 0.20)    # 1.2 倍法定容積
        self.assertAlmostEqual(cap["renewal"], 0.50)   # 1.5 倍法定容積


class TestNonUrban(unittest.TestCase):
    """非都市土地不適用都市計畫法系的任何容積獎勵。"""

    def test_only_nonurban_program(self):
        r = bonuses.applicable(county="苗栗縣", urban=False,
                               designation="乙種建築用地", area_m2=4860)
        keys = [p["key"] for p in r["programs"]]
        self.assertEqual(keys, ["nonurban"])
        for k in ("danger", "tdr", "renew", "openspace", "provincial_cap"):
            self.assertNotIn(k, keys, "非都市土地不該出現 %s" % k)

    def test_intensity_from_statute(self):
        """尖山段那案：鄉村區乙建 240% / 60%。"""
        nu = bonuses.nonurban_intensity("乙種建築用地")
        self.assertAlmostEqual(nu["far"]["value"], 2.40)
        self.assertAlmostEqual(nu["coverage"]["value"], 0.60)
        self.assertIn("第 9 條", nu["far"]["source"]["article"])

    def test_unknown_designation_returns_none(self):
        self.assertIsNone(bonuses.nonurban_intensity("農牧用地"))
        self.assertIsNone(bonuses.nonurban_intensity(None))


class TestDangerAutoItems(unittest.TestCase):
    """危老的規模與時程獎勵是算出來的，不是抄舊案的。"""

    def test_scale_bonus_formula(self):
        f = bonuses.danger_scale_bonus
        self.assertEqual(f(150)["pct"], 0.0)          # 未達 200 ㎡
        self.assertAlmostEqual(f(200)["pct"], 0.02)
        self.assertAlmostEqual(f(725)["pct"], 0.045)  # 舊社段
        self.assertAlmostEqual(f(1800)["pct"], 0.10)  # 滿額
        self.assertAlmostEqual(f(5000)["pct"], 0.10)  # 封頂

    def test_time_bonus_sunset(self):
        self.assertAlmostEqual(bonuses.danger_time_bonus("2019-01-01")["pct"], 0.10)
        self.assertAlmostEqual(bonuses.danger_time_bonus("2023-06-01")["pct"], 0.02)
        self.assertAlmostEqual(bonuses.danger_time_bonus("2025-05-12")["pct"], 0.0,
                               msg="114/05/12 起已無時程獎勵")

    def test_small_site_grades_disabled(self):
        """基地 ≥ 500 ㎡ 不適用綠建築、智慧建築的銅級與合格級。"""
        r = bonuses.applicable(county="苗栗縣", urban=True, zone_name="住宅區",
                               area_m2=725)
        items = {i["key"]: i for i in prog(r, "danger")["items"]}
        self.assertTrue(items["green_b"].get("disabled"))
        self.assertTrue(items["smart_p"].get("disabled"))
        self.assertFalse(items["green_s"].get("disabled"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
