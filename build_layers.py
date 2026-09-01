#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把政府圖資轉成靜態版（GitHub Pages）查得動的格式。

為什麼要有這支程式
------------------
有些圖層只有 shapefile，沒有可以即時查詢的服務：

  * 非都市土地的使用分區與編定 —— 政府沒有免費且允許瀏覽器直連的
    全國服務（官方介接自 115/1/1 起收費）
  * 新北市與高雄市的都市計畫分區 —— 這兩個縣市是發佈檔案而非服務

本機版靠 Python 在伺服器端解析這些 shapefile，放到 GitHub Pages 沒有
後端就查不到，所以要先轉成瀏覽器自己查得動的形式。

做法
----
1. 把多邊形依 TWD97 二度分帶切成方格（預設 4 公里）。
2. 每個縣市每種圖層輸出「一個大的 .bin ＋ 一個小的 .idx.json」。
   索引記錄每一格在 .bin 裡的位移與長度。
3. 瀏覽器點下去時，只用 HTTP Range request 抓需要的那一格
   （通常幾十 KB），在前端做點在多邊形內判斷。

   GitHub Pages 支援 Range request（實測回 206 Partial Content），
   所以不必把圖資切成上萬個小檔，git 也不會被檔案數拖垮。

座標用 0.25 公尺量化後做差分與 varint 編碼。0.25 公尺遠小於這份圖資
本身的測量誤差，不影響判斷結果，但讓檔案小很多。

用法
----
    python build_layers.py --measure           # 只估算大小，不寫檔
    python build_layers.py                     # 轉換已下載的縣市
    python build_layers.py --county 苗栗縣     # 只轉一個縣市
    python build_layers.py --key urban_zone    # 只轉某一種圖層
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datasets as DS  # noqa: E402
import geo  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_DIR = os.path.join(BASE_DIR, "web", "nurban")

CELL = 4096.0      # 方格邊長（公尺）
QUANT = 0.25       # 座標量化（公尺）

DATASET_KEYS = ("nurban_zone", "nurban_desig", "urban_zone")

# 都市計畫只預轉「沒有即時服務」的縣市。有服務的縣市走即時查詢，
# 資料永遠是最新的；預轉的是某一時點的快照，能不用就不用。
URBAN_PRECONVERT = ("新北市", "高雄市")


# ── varint（zigzag）───────────────────────────────────────────
def put_varint(buf, v):
    v = (v << 1) ^ (v >> 63) if v < 0 else (v << 1)
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            break


def put_uvarint(buf, v):
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            buf.append(b | 0x80)
        else:
            buf.append(b)
            break


# ── 讀圖層 ───────────────────────────────────────────────────
def zip_paths(key, county):
    """這個縣市已經下載了哪些檔（有的縣市分成好幾個檔）。"""
    out = []
    i = 0
    while True:
        p = os.path.join(DATA_DIR, "%s_%s_%d.zip" % (key, county, i))
        if not os.path.exists(p):
            break
        out.append(p)
        i += 1
    return out


def pick_field(fields, cands):
    for c in cands:
        if c in fields:
            return c
    for c in cands:
        for f in fields:
            if c in f or f in c:
                return f
    return None


def feature_xy(layer, i):
    """回傳這一筆的環（每環是 TWD97 二度分帶的 [(x, y), ...]）。"""
    start, npts = layer.ranges[i]
    if npts == 0:
        return []
    co = layer.coords
    partidx = list(layer.parts[i]) or [0]
    bounds = list(partidx) + [npts]
    rings = []
    for k in range(len(partidx)):
        a, b = bounds[k], bounds[k + 1]
        ring = []
        for j in range(start + a, start + b):
            x, y = co[2 * j], co[2 * j + 1]
            if layer.is_lonlat:
                x, y = geo.lonlat_to_tm2(x, y)
            ring.append((x, y))
        if len(ring) >= 3:
            rings.append(ring)
    return rings



def field_indexes(layer, ds):
    """先把要用的欄位位置找好，省得每一筆都重找一次。

    回傳 {'value': i, 'code': i, 'extra': [(標籤, i), ...]}，找不到的是 -1。
    """
    def find(cands):
        f = pick_field(layer.fields, cands or [])
        return layer.fields.index(f) if f in layer.fields else -1

    out = {"value": find(ds.get("value_fields")), "code": find(ds.get("code_fields")),
           "extra": []}
    for label, cands in ds.get("extra_fields", []):
        i = find(cands)
        if i >= 0:
            out["extra"].append((label, i))
    return out


def cell_text(row, i):
    if i < 0 or i >= len(row) or row[i] is None:
        return ""
    return str(row[i]).strip()


def attributes(layer, i, ds, idxs):
    """一筆圖徵要存的屬性。

    非都市圖層只有一個名稱，存成字串就好；都市計畫還有代碼、建蔽率、
    容積率、所屬都市計畫等，存成物件。前端兩種都吃得下。
    """
    row = layer.rows[i] if i < len(layer.rows) else []
    value = cell_text(row, idxs["value"])
    if not ds.get("extra_fields") and idxs["code"] < 0:
        return value

    rec = {"v": value}
    code = cell_text(row, idxs["code"])
    if code and code != value:
        rec["c"] = code
    extras = []
    for label, j in idxs["extra"]:
        t = cell_text(row, j)
        if t and t != value:
            extras.append([label, t])
    if extras:
        rec["e"] = extras
    return rec


# ── 把環裁切到方格內（Sutherland–Hodgman）─────────────────────
#
# 不裁切的話，像「特定農業區」那種橫跨數十格的大多邊形，會在每一格
# 各存一份完整輪廓 —— 用圖徵數看複製率只有 1.17 倍，但用「點數」看
# 高得多，檔案直接大五倍。裁切之後每一格只留該格用得到的邊。
#
# 對「點在多邊形內」的判斷來說這是安全的：格子內的點，在原多邊形內
# 等價於在裁切後的多邊形內。內環（洞）各自裁切，用奇偶規則仍然正確。
def clip_ring(ring, xmin, ymin, xmax, ymax):
    def inside(p, edge):
        if edge == 0: return p[0] >= xmin
        if edge == 1: return p[0] <= xmax
        if edge == 2: return p[1] >= ymin
        return p[1] <= ymax

    def cut(a, b, edge):
        ax, ay = a
        bx, by = b
        if edge in (0, 1):
            x = xmin if edge == 0 else xmax
            t = (x - ax) / (bx - ax) if bx != ax else 0.0
            return (x, ay + (by - ay) * t)
        y = ymin if edge == 2 else ymax
        t = (y - ay) / (by - ay) if by != ay else 0.0
        return (ax + (bx - ax) * t, y)

    out = ring
    for edge in range(4):
        if not out:
            return []
        buf = []
        prev = out[-1]
        pin = inside(prev, edge)
        for cur in out:
            cin = inside(cur, edge)
            if cin:
                if not pin:
                    buf.append(cut(prev, cur, edge))
                buf.append(cur)
            elif pin:
                buf.append(cut(prev, cur, edge))
            prev, pin = cur, cin
        out = buf
    return out if len(out) >= 3 else []


# ── 轉換一個縣市的一種圖層 ───────────────────────────────────
def convert(key, county, measure_only=False):
    paths = zip_paths(key, county)
    if not paths:
        return None

    ds = DS.DATASETS[key]
    cells = {}          # (cx, cy) -> [ (valueId, rings) ]
    values = []
    value_id = {}
    total_feats = 0

    for path in paths:
        layer = geo.PolygonLayer.from_zip(path)
        idxs = field_indexes(layer, ds)
        for i in range(len(layer.ranges)):
            if layer.boxes[i] is None:
                continue
            rings = feature_xy(layer, i)
            if not rings:
                continue
            rec = attributes(layer, i, ds, idxs)
            akey = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            if akey not in value_id:
                value_id[akey] = len(values)
                values.append(rec)
            vid = value_id[akey]

            xs = [p[0] for r in rings for p in r]
            ys = [p[1] for r in rings for p in r]
            cx0, cx1 = int(min(xs) // CELL), int(max(xs) // CELL)
            cy0, cy1 = int(min(ys) // CELL), int(max(ys) // CELL)
            total_feats += 1
            single = (cx0 == cx1 and cy0 == cy1)
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    if single:
                        cells.setdefault((cx, cy), []).append((vid, rings))
                        continue
                    # 稍微外擴一點，避免落在格線上的點被兩邊都判成外面
                    x0, y0 = cx * CELL - 1.0, cy * CELL - 1.0
                    x1, y1 = (cx + 1) * CELL + 1.0, (cy + 1) * CELL + 1.0
                    cut = [r for r in (clip_ring(r, x0, y0, x1, y1) for r in rings) if r]
                    if cut:
                        cells.setdefault((cx, cy), []).append((vid, cut))

    # ── 編碼 ──
    blob = bytearray()
    index = {}
    for (cx, cy), feats in sorted(cells.items()):
        off = len(blob)
        buf = bytearray()
        put_uvarint(buf, len(feats))
        # 每一格的座標都相對於該格左下角，數字才會小
        ox = int(cx * CELL / QUANT)
        oy = int(cy * CELL / QUANT)
        for vid, rings in feats:
            put_uvarint(buf, vid)
            put_uvarint(buf, len(rings))
            for ring in rings:
                put_uvarint(buf, len(ring))
                px, py = ox, oy
                for (x, y) in ring:
                    qx = int(round(x / QUANT))
                    qy = int(round(y / QUANT))
                    put_varint(buf, qx - px)
                    put_varint(buf, qy - py)
                    px, py = qx, qy
        blob += buf
        index["%d_%d" % (cx, cy)] = [off, len(buf)]

    meta = {
        "dataset": key,
        "title": ds["title"],
        "county": county,
        "source": ds.get("source", ""),
        "licence": ds.get("licence", ""),
        "cell": CELL,
        "quant": QUANT,
        "values": values,
        "cells": index,
        "featureCount": total_feats,
    }

    if measure_only:
        return {"bin": len(blob), "idx": len(json.dumps(meta, ensure_ascii=False)),
                "feats": total_feats, "cells": len(index),
                "stored": sum(len(v) for v in cells.values())}

    os.makedirs(OUT_DIR, exist_ok=True)
    stem = os.path.join(OUT_DIR, "%s_%s" % (key, county))
    with open(stem + ".bin", "wb") as f:
        f.write(bytes(blob))
    with open(stem + ".idx.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    return {"bin": len(blob), "idx": os.path.getsize(stem + ".idx.json"),
            "feats": total_feats, "cells": len(index),
            "stored": sum(len(v) for v in cells.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true", help="只估算大小，不寫檔")
    ap.add_argument("--county", action="append", help="只處理指定縣市（可重複）")
    ap.add_argument("--key", choices=DATASET_KEYS, help="只處理某一種圖層")
    args = ap.parse_args()

    keys = [args.key] if args.key else list(DATASET_KEYS)
    counties = args.county
    if not counties:
        found = set()
        for key in keys:
            for cty in DS.DATASETS[key]["counties"]:
                if zip_paths(key, cty):
                    found.add(cty)
        counties = sorted(found)

    if not counties:
        print("data/ 裡沒有已下載的非都市圖資。先在 App 裡按「下載圖資」，"
              "或用 start.py 下載後再跑這支程式。")
        return

    tot_bin = tot_idx = 0
    for cty in counties:
        for key in keys:
            if key == "urban_zone" and cty not in URBAN_PRECONVERT:
                continue
            r = convert(key, cty, args.measure)
            if r is None:
                continue
            tot_bin += r["bin"]
            tot_idx += r["idx"]
            dup = (r["stored"] / r["feats"]) if r["feats"] else 0
            print("%-14s %-13s %7d 圖徵  %4d 格  跨格複製 %.2f 倍  "
                  "bin %6.2f MB  idx %5.2f MB"
                  % (cty, key, r["feats"], r["cells"], dup,
                     r["bin"] / 1e6, r["idx"] / 1e6))

    print("\n合計：bin %.1f MB ＋ idx %.1f MB = %.1f MB"
          % (tot_bin / 1e6, tot_idx / 1e6, (tot_bin + tot_idx) / 1e6))
    if args.measure:
        print("（估算模式，未寫檔）")


if __name__ == "__main__":
    main()
