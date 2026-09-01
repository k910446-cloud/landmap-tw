#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心計算的單元測試。

為什麼要有
----------
這個專案最怕的不是當掉，是「安靜地算錯」——面積少一位數、地號補零補錯、
座標偏幾百公尺，畫面上都長得很正常，沒有人會發現。實際上也發生過：
「持分移轉」被當成特殊交易排除，把幾乎所有住宅成交都濾掉了，
是靠人眼看出中位數變得離譜才抓到的。

所以這裡測的都是純函式：給定輸入必然有唯一正確答案，改壞了會立刻紅燈。

執行
----
    python -m unittest discover -s tests -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_landuse  # noqa: E402
import build_laws  # noqa: E402
import build_prices  # noqa: E402
import geo  # noqa: E402
import start  # noqa: E402


class TestTM2(unittest.TestCase):
    """TWD97 二度分帶換算。"""

    def test_known_point(self):
        """臺北 101（25.0339N, 121.5645E）。

        期望值不寫死一個記來的數字，改成從投影本身推導：
        東距 = 250000 + 離中央經線的度數 × 每度長度 × cos(緯度)，
        北距 ≈ 緯度 × 每度緯線長。這樣期望值自己就說明了為什麼是這個數。
        """
        lat, lon = 25.0339, 121.5645
        x, y = geo.lonlat_to_tm2(lon, lat)
        want_x = 250000 + (lon - 121.0) * 111320 * math.cos(math.radians(lat))
        want_y = lat * 110570
        self.assertAlmostEqual(x, want_x, delta=400)
        self.assertAlmostEqual(y, want_y, delta=3000)

    def test_central_meridian(self):
        # 中央經線上，X 應該正好是假東距 250000
        x, _y = geo.lonlat_to_tm2(121.0, 24.0)
        self.assertAlmostEqual(x, 250000, delta=0.5)

    def test_monotonic(self):
        # 往東 X 變大、往北 Y 變大 —— 方向搞反過的話面積與距離全錯
        x1, y1 = geo.lonlat_to_tm2(120.5, 24.0)
        x2, y2 = geo.lonlat_to_tm2(120.6, 24.0)
        _x3, y3 = geo.lonlat_to_tm2(120.5, 24.1)
        self.assertGreater(x2, x1)
        self.assertAlmostEqual(y2, y1, delta=200)
        self.assertGreater(y3, y1)

    def test_penghu_zone(self):
        # 澎金馬用中央經線 119
        x, _y = geo.lonlat_to_tm2(119.0, 23.5, lon0=119.0)
        self.assertAlmostEqual(x, 250000, delta=0.5)


class TestArea(unittest.TestCase):
    """宗地面積。"""

    def square_ring(self, side_m, lat=24.0, lon=120.8):
        """做一個邊長大約 side_m 公尺的正方形（回傳經緯度環）。"""
        dlat = side_m / 110540.0
        dlon = side_m / (111320.0 * math.cos(math.radians(lat)))
        return [[lon, lat], [lon + dlon, lat],
                [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]

    def test_square_area(self):
        ring = self.square_ring(100.0)
        a = start.ring_area_m2(ring)
        self.assertAlmostEqual(a, 10000, delta=120)     # 100m × 100m

    def test_ping_conversion(self):
        # 1 坪 = 400/121 m²，約 3.3058
        self.assertAlmostEqual(start.PING, 3.3057851, places=6)
        self.assertAlmostEqual(1000 / start.PING, 302.5, delta=0.1)

    def test_winding_does_not_matter(self):
        """順時針逆時針都該得到同樣的正面積。"""
        ring = self.square_ring(50.0)
        self.assertAlmostEqual(start.ring_area_m2(ring),
                               start.ring_area_m2(list(reversed(ring))), places=6)


class TestLandNo(unittest.TestCase):
    """地號格式：八碼 = 母號 4 + 子號 4。"""

    CFG = {"landno": ["NOPE"], "landno8": ["AA49"],
           "mother": ["MM"], "child": ["CC"]}

    def test_eight_digit(self):
        self.assertEqual(start.format_landno(self.CFG, {"AA49": "08800000"}), "880")
        self.assertEqual(start.format_landno(self.CFG, {"AA49": "08800001"}), "880-1")
        self.assertEqual(start.format_landno(self.CFG, {"AA49": "00020007"}), "2-7")

    def test_mother_child(self):
        self.assertEqual(start.format_landno(self.CFG, {"MM": "0880", "CC": "0000"}), "880")
        self.assertEqual(start.format_landno(self.CFG, {"MM": "0001", "CC": "0012"}), "1-12")

    def test_missing(self):
        self.assertIsNone(start.format_landno(self.CFG, {}))


class TestFindParcelWhere(unittest.TestCase):
    """依地號查詢時組出來的 where 條件。"""

    def test_bad_input_rejected(self):
        r = start.find_parcel("苗栗縣", "中苗段", "abc")
        self.assertEqual(r["status"], "bad-input")

    def test_missing_section_rejected(self):
        r = start.find_parcel("苗栗縣", "", "880")
        self.assertEqual(r["status"], "bad-input")

    def test_unknown_county(self):
        r = start.find_parcel("火星縣", "某段", "1")
        self.assertEqual(r["status"], "unavailable")


class TestVarint(unittest.TestCase):
    """成交資料的 varint 編碼 —— 前端要靠這個解回原值。"""

    def roundtrip_u(self, v):
        buf = bytearray()
        build_prices.put_uvarint(buf, v)
        return self.read_u(buf, 0)[0]

    def roundtrip_s(self, v):
        buf = bytearray()
        build_prices.put_svarint(buf, v)
        n, _p = self.read_u(buf, 0)
        return -(n + 1) // 2 if n % 2 else n // 2

    @staticmethod
    def read_u(buf, p):
        shift = 0
        out = 0
        while True:
            b = buf[p]
            p += 1
            out += (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return out, p

    def test_unsigned(self):
        for v in (0, 1, 127, 128, 300, 16383, 16384, 1000000):
            self.assertEqual(self.roundtrip_u(v), v, "u %d" % v)

    def test_signed(self):
        for v in (0, 1, -1, 63, -64, 300, -300, 99999, -99999):
            self.assertEqual(self.roundtrip_s(v), v, "s %d" % v)

    def test_section_roundtrip(self):
        """整個段編碼後解回來，欄位要一模一樣。"""
        parcels = {
            "08800000": [[11502, 1452.0, 312621, 153.5, 4, 0, 3, -1, 2, 1],
                         [11410, 1702.0, 324833, 173.2, 1, 16, 21, -1, 0, 0]],
            "00020007": [[11312, 40.0, 13000, 30.8, 0, 1, -1, -1, -1, -1]],
        }
        blob = build_prices.encode_section(parcels)
        got = self.decode_section(bytes(blob))
        self.assertEqual(set(got), set(parcels))
        for key in parcels:
            want = sorted(parcels[key], key=lambda r: r[0])
            self.assertEqual(len(got[key]), len(want))
            for a, b in zip(got[key], want):
                self.assertEqual(a[0], b[0])                      # 年月
                self.assertAlmostEqual(a[1], b[1], places=1)      # 總價
                self.assertEqual(a[2], b[2])                      # 單價
                self.assertAlmostEqual(a[3], b[3], places=1)      # 面積
                self.assertEqual(a[4:], b[4:])                    # 類型之後

    def decode_section(self, blob):
        """跟 web/prices.js 的解碼邏輯一致，用來驗證編碼器。"""
        p = 0
        n, p = self.read_u(blob, p)
        out = {}
        for _ in range(n):
            no, p = self.read_u(blob, p)
            key = "%08d" % no
            cnt, p = self.read_u(blob, p)
            rows = []
            ym = unit = 0
            for _j in range(cnt):
                d, p = self.read_u(blob, p)
                ym += -(d + 1) // 2 if d % 2 else d // 2
                total, p = self.read_u(blob, p)
                d2, p = self.read_u(blob, p)
                unit += -(d2 + 1) // 2 if d2 % 2 else d2 // 2
                area, p = self.read_u(blob, p)
                kind, p = self.read_u(blob, p)
                flags, p = self.read_u(blob, p)
                age, p = self.read_u(blob, p)
                proj, p = self.read_u(blob, p)
                btype, p = self.read_u(blob, p)
                use, p = self.read_u(blob, p)
                rows.append([ym, total / 10.0, unit, area / 10.0, kind, flags,
                             age - 1, proj - 1, btype - 1, use - 1])
            out[key] = rows
        return out


class TestPriceFlags(unittest.TestCase):
    """特殊交易的備註判讀。"""

    def test_family_deal(self):
        v = build_prices.note_flags("親友、員工、共有人或其他特殊關係間之交易")
        self.assertTrue(v & 1)

    def test_unregistered_building(self):
        self.assertTrue(build_prices.note_flags("含未登記建物") & 4)

    def test_plain_note_is_clean(self):
        self.assertEqual(build_prices.note_flags("含增建部分"), 4)
        self.assertEqual(build_prices.note_flags(""), 0)
        self.assertEqual(build_prices.note_flags("公共設施保留地"), 0)

    def test_share_flag_is_separate(self):
        """持分移轉不能混進備註旗標 —— 公寓的土地本來就是持分，
        當成特殊交易排掉會濾掉幾乎所有住宅成交。"""
        self.assertEqual(build_prices.note_flags("持分移轉"), 0)
        self.assertEqual(build_prices.SHARE_FLAG, 16)


class TestLawParsing(unittest.TestCase):
    """法規條文的數字解析。"""

    def test_chinese_numbers(self):
        cases = {"五": 5, "十": 10, "十五": 15, "二十": 20, "六十": 60,
                 "八十": 80, "一百": 100, "一百二十": 120, "二百四十": 240,
                 "三百": 300, "四百": 400}
        for text, want in cases.items():
            self.assertEqual(build_laws.cn_number(text), want, text)

    def test_percent_list(self):
        text = "一、住宅區：百分之六十。二、商業區：百分之八十。三、工業區：百分之七十。"
        got = build_laws.parse_percent_list(text)
        self.assertEqual(got["住宅區"], 60)
        self.assertEqual(got["商業區"], 80)
        self.assertEqual(got["工業區"], 70)

    def test_compound_names_split(self):
        """「郵政、電信、變電所專用區」要能用其中任一個名稱查到。"""
        text = "一、郵政、電信、變電所專用區：百分之六十。"
        got = build_laws.parse_percent_list(text)
        self.assertEqual(got["郵政、電信、變電所專用區"], 60)
        self.assertEqual(got["變電所專用區"], 60)
        self.assertEqual(got["郵政專用區"], 60)

    def test_paren_variants(self):
        """條文寫「加油（氣）站專用區」，圖資只寫「加油站專用區」。"""
        text = "一、加油（氣）站專用區：百分之四十。"
        got = build_laws.parse_percent_list(text)
        self.assertEqual(got["加油（氣）站專用區"], 40)
        self.assertEqual(got["加油站專用區"], 40)


class TestLandUseParsing(unittest.TestCase):
    """附表一的編號判讀。"""

    def test_halfwidth_parens_normalised(self):
        self.assertEqual(build_landuse.norm("(十五)動物保護"), "（十五）動物保護")

    def test_clean_keeps_law_text(self):
        """clean 只去空白，不能動到條文的字。"""
        self.assertEqual(build_landuse.clean("使用面積 一百五十 平方公尺"),
                         "使用面積一百五十平方公尺")
        self.assertEqual(build_landuse.clean("(一)沿海自然保護區"),
                         "(一)沿海自然保護區")

    def test_header_detection(self):
        self.assertTrue(build_landuse.is_header("使用地類別容許使用項目"))
        self.assertFalse(build_landuse.is_header("甲種建築用地"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
