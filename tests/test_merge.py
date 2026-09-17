#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多筆地號合併評估：逐筆納入／排除、面積覆寫、跨分區分算。

為什麼要有
----------
事務所的表幾乎沒有一份是單筆地號。實務上的合併評估長這樣：

  頭份信義段：「包括國有地662-1、662-2，不包括頭份市有地660-1」
  尖山段　　：「不含河川區29地號面積、含國有地70地號面積」
  德義段　　：「211、219、218部分、212、212-6…等8筆」

也就是說：有些地號要排除、有些只納入一部分。這些判斷會直接改變基地面積，
進而改變基準容積、危老規模獎勵、綜合設計門檻 —— 一路影響到最後的可售坪。
少算或多算一筆，表上完全看不出來，所以每一條都要有測試。

跨分區更危險：拿第一筆的分區去套整塊地，在「商業區帶住宅區」的臨街基地
會多算好幾百坪，而且畫面上一切正常。

執行
----
    python -m unittest tests.test_merge -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import far  # noqa: E402


def cell(res, sk, rk):
    for s in res["sections"]:
        if s["key"] == sk:
            for r in s["rows"]:
                if r["key"] == rk:
                    return r
    return None


def rows(res, sk):
    for s in res["sections"]:
        if s["key"] == sk:
            return s["rows"]
    return []


ZHONGLIAO = [
    ("783-2", 192.01), ("787", 467.50), ("788", 383.21), ("788-1", 51.22),
    ("789", 140.32), ("790", 199.36), ("800", 24.06), ("801", 560.61),
    ("802", 275.50), ("803", 578.79),
]


def parcels(**over):
    out = []
    for no, a in ZHONGLIAO:
        p = {"sect": "中寮段", "no": no, "areaM2": a, "areaFrom": "registered",
             "source": {"kind": "地政", "name": "新竹市地籍圖公開服務"}}
        p.update(over.get(no, {}))
        out.append(p)
    return out


BASE = {"zone": {"far": 2.00, "coverage": 0.60},
        "floors": {"mepPct": 0.15, "lobbyPct": 0.05, "balconyPct": 0.10}}


class TestParcelSum(unittest.TestCase):
    """十筆合計 2,872.58 ㎡ —— 中寮段那份表的第一行。"""

    def test_all_included(self):
        out = far.analyze(dict(BASE, site={"parcels": parcels()}))
        self.assertAlmostEqual(out["netAreaM2"], 2872.58, delta=0.02)
        self.assertAlmostEqual(cell(out, "capacity", "base")["m2"], 5745.16,
                               delta=0.02)


class TestExclude(unittest.TestCase):
    """逐筆排除 —— 頭份信義段「不包括頭份市有地660-1」那種。"""

    def setUp(self):
        self.out = far.analyze(dict(BASE, site={"parcels": parcels(**{
            "801": {"include": False, "note": "市有地，未取得"},
            "803": {"include": False, "note": "河川區，不計入"},
        })}))

    def test_area_excludes_them(self):
        want = 2872.58 - 560.61 - 578.79
        self.assertAlmostEqual(self.out["netAreaM2"], want, delta=0.02)

    def test_capacity_follows(self):
        want = (2872.58 - 560.61 - 578.79) * 2.0
        self.assertAlmostEqual(cell(self.out, "capacity", "base")["m2"], want,
                               delta=0.02)

    def test_excluded_parcels_still_listed(self):
        """排除的地號要留在表上並註明理由。

        直接消失的話，看表的人沒辦法核對「這筆為什麼沒算」——
        而那正是合併評估最需要交代的一件事。
        """
        out = [r for r in rows(self.out, "site") if r.get("excluded")]
        self.assertEqual(len(out), 2)
        labels = " ".join(r["label"] for r in out)
        self.assertIn("801", labels)
        self.assertIn("803", labels)
        self.assertIn("市有地", out[0]["note"])

    def test_summary_counts_both(self):
        g = cell(self.out, "site", "gross")
        self.assertIn("8 筆納入", g["formula"])
        self.assertIn("2 筆排除", g["formula"])


class TestAreaOverride(unittest.TestCase):
    """面積覆寫 —— 德義段「218部分」那種只納入一部分的情形。"""

    def test_override_wins(self):
        out = far.analyze(dict(BASE, site={"parcels": parcels(**{
            "801": {"areaOverride": 200.00, "note": "僅部分納入"},
        })}))
        want = 2872.58 - 560.61 + 200.00
        self.assertAlmostEqual(out["netAreaM2"], want, delta=0.02)

    def test_override_is_flagged_as_assumed(self):
        """人工填的面積沒有地政依據，要標出來。"""
        out = far.analyze(dict(BASE, site={"parcels": parcels(**{
            "801": {"areaOverride": 200.00, "note": "僅部分納入"},
        })}))
        r = [x for x in rows(out, "site")
             if x["key"] == "parcel" and "801" in x["label"]][0]
        self.assertTrue(r["assumed"])
        self.assertIn("人工填入", r["note"])

    def test_blank_override_ignored(self):
        """空字串不能被當成 0，否則那筆地號會憑空消失。"""
        out = far.analyze(dict(BASE, site={"parcels": parcels(**{
            "801": {"areaOverride": ""},
        })}))
        self.assertAlmostEqual(out["netAreaM2"], 2872.58, delta=0.02)


class TestMixedZone(unittest.TestCase):
    """跨分區分算：基準容積 = Σ(各分區面積 × 該分區容積率)。"""

    def setUp(self):
        # 臨街三筆是商業區 400%，其餘住宅區 200%
        comm = {"zoneName": "商業區", "zoneFar": 4.00, "zoneCoverage": 0.80}
        res = {"zoneName": "住宅區", "zoneFar": 2.00, "zoneCoverage": 0.60}
        over = {}
        for no, _ in ZHONGLIAO:
            over[no] = dict(comm if no in ("787", "788", "788-1") else res)
        self.parcels = parcels(**over)
        self.out = far.analyze(dict(BASE, site={"parcels": self.parcels}))

    def test_groups_detected(self):
        self.assertTrue(self.out["mixedZone"])
        names = [g["name"] for g in self.out["zoneGroups"]]
        self.assertEqual(sorted(names), ["住宅區", "商業區"])

    def test_base_is_area_weighted(self):
        comm_a = 467.50 + 383.21 + 51.22
        res_a = 2872.58 - comm_a
        want = comm_a * 4.00 + res_a * 2.00
        self.assertAlmostEqual(cell(self.out, "capacity", "base")["m2"], want,
                               delta=0.05)

    def test_not_the_naive_single_zone_answer(self):
        """用第一筆的分區套全部會得到不一樣的數字 —— 這正是要避免的錯。"""
        naive_first_zone = 2872.58 * 2.00      # 783-2 是住宅區
        got = cell(self.out, "capacity", "base")["m2"]
        self.assertNotAlmostEqual(got, naive_first_zone, delta=1.0)
        self.assertGreater(got, naive_first_zone)

    def test_build_area_also_weighted(self):
        comm_a = 467.50 + 383.21 + 51.22
        res_a = 2872.58 - comm_a
        want = comm_a * 0.80 + res_a * 0.60
        self.assertAlmostEqual(cell(self.out, "zone", "buildArea")["m2"], want,
                               delta=0.05)

    def test_breakdown_rows_present(self):
        detail = [r for r in rows(self.out, "capacity") if r["key"] == "zoneBase"]
        self.assertEqual(len(detail), 2)
        total = sum(r["m2"] for r in detail)
        self.assertAlmostEqual(total, cell(self.out, "capacity", "base")["m2"],
                               delta=0.05)

    def test_excluded_parcel_leaves_its_zone_group(self):
        """把商業區那三筆全部排除，就只剩住宅區一組。"""
        ps = []
        for p in self.parcels:
            q = dict(p)
            if q["no"] in ("787", "788", "788-1"):
                q["include"] = False
            ps.append(q)
        out = far.analyze(dict(BASE, site={"parcels": ps}))
        self.assertFalse(out["mixedZone"])
        self.assertEqual([g["name"] for g in out["zoneGroups"]], ["住宅區"])


class TestSingleZoneUnchanged(unittest.TestCase):
    """只有一種分區時，行為必須跟以前一模一樣。"""

    def test_same_as_before(self):
        ps = parcels()
        for p in ps:
            p.update({"zoneName": "第一之一種住宅區", "zoneFar": 2.00,
                      "zoneCoverage": 0.60})
        out = far.analyze(dict(BASE, site={"parcels": ps}))
        self.assertFalse(out["mixedZone"])
        self.assertAlmostEqual(cell(out, "capacity", "base")["m2"], 5745.16,
                               delta=0.02)
        self.assertAlmostEqual(cell(out, "zone", "buildArea")["m2"], 1723.55,
                               delta=0.02)


if __name__ == "__main__":
    unittest.main(verbosity=2)
