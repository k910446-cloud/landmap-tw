# -*- coding: utf-8 -*-
"""
純標準函式庫的 Shapefile 圖徵查詢引擎。

政府開放資料的圖資是 ESRI Shapefile（.shp 幾何 + .dbf 屬性），座標系為
TWD97 二度分帶（EPSG:3826）。這裡做三件事：

  1. 解析 .shp 的 Polygon 記錄與 .dbf 的屬性
  2. 建立網格空間索引，讓點查詢不必掃過全部圖徵
  3. 射線法判斷點落在哪個多邊形裡，回傳該筆的屬性

不使用 geopandas / shapely / pyproj —— 使用者只要有 Python 就能跑。
"""

import array
import math
import os
import struct
import zipfile

# ── TWD97 二度分帶（與前端 twd97.js 同一組公式）───────────────────

_A = 6378137.0
_F = 1 / 298.257222101
_K0 = 0.9999
_DX = 250000.0


def lonlat_to_tm2(lon, lat, lon0=121.0):
    """WGS84 經緯度 → TWD97 TM2 (x, y)，單位公尺。"""
    e = _F * (2 - _F)
    e2 = e / (1 - e)
    phi = math.radians(lat)
    lam = math.radians(lon)
    lam0 = math.radians(lon0)

    sp, cp = math.sin(phi), math.cos(phi)
    tp = math.tan(phi)
    V = _A / math.sqrt(1 - e * sp * sp)
    T = tp * tp
    C = e2 * cp * cp
    a1 = (lam - lam0) * cp
    a2 = a1 * a1
    a3 = a2 * a1
    a4 = a3 * a1
    a5 = a4 * a1
    a6 = a5 * a1

    M = _A * ((1 - e / 4 - 3 * e * e / 64 - 5 * e ** 3 / 256) * phi
              - (3 * e / 8 + 3 * e * e / 32 + 45 * e ** 3 / 1024) * math.sin(2 * phi)
              + (15 * e * e / 256 + 45 * e ** 3 / 1024) * math.sin(4 * phi)
              - (35 * e ** 3 / 3072) * math.sin(6 * phi))

    x = _K0 * V * (a1 + (1 - T + C) * a3 / 6
                   + (5 - 18 * T + T * T + 72 * C - 58 * e2) * a5 / 120) + _DX
    y = _K0 * (M + V * tp * (a2 / 2
                             + (5 - T + 9 * C + 4 * C * C) * a4 / 24
                             + (61 - 58 * T + T * T + 600 * C - 330 * e2) * a6 / 720))
    return x, y


# ── DBF ─────────────────────────────────────────────────────────

def read_dbf(buf, encoding=None):
    """回傳 (欄位名稱 list, 每筆值的 list)。encoding 由 .cpg 決定，預設試 UTF-8 再退回 Big5。"""
    nrec, hlen, rlen = struct.unpack('<IHH', buf[4:12])

    fields = []
    off = 32
    while off < len(buf) and buf[off] != 0x0D:
        raw = buf[off:off + 11].split(b'\x00')[0]
        fields.append((raw, buf[off + 16]))
        off += 32

    encs = [encoding] if encoding else []
    encs += ['utf-8', 'cp950', 'big5']

    def dec(b):
        for en in encs:
            if not en:
                continue
            try:
                return b.decode(en).strip()
            except (UnicodeDecodeError, LookupError):
                continue
        return b.decode('utf-8', 'replace').strip()

    names = [dec(raw) for raw, _ in fields]

    rows = []
    pos = hlen
    for _ in range(nrec):
        rec = buf[pos:pos + rlen]
        pos += rlen
        if len(rec) < rlen or rec[:1] == b'*':      # 已刪除的記錄
            rows.append(None)
            continue
        vals = []
        o = 1
        for _, ln in fields:
            vals.append(dec(rec[o:o + ln]))
            o += ln
        rows.append(vals)
    return names, rows


# ── Shapefile ───────────────────────────────────────────────────

SHP_POLYGON = 5
SHP_POLYGON_Z = 15
SHP_POLYGON_M = 25


class PolygonLayer:
    """一個縣市的面圖層，載入後常駐記憶體。"""

    __slots__ = ('fields', 'rows', 'boxes', 'parts', 'coords',
                 'ranges', 'grid', 'cell', 'extent', 'name', 'is_lonlat')

    def __init__(self, name):
        self.name = name
        self.fields = []
        self.rows = []
        self.boxes = []      # 每筆的 (xmin, ymin, xmax, ymax)
        self.parts = []      # 每筆的環起點 index（相對於該筆的點序列）
        self.coords = array.array('d')
        self.ranges = []     # 每筆在 coords 裡的 (起點索引, 點數)
        self.grid = {}
        self.cell = 2000.0   # 索引網格 2 公里
        self.extent = None

    # ---- 載入 ----

    @classmethod
    def from_zip(cls, zip_path, name=None):
        """一個 zip 裡可能不只一個圖層（例如同時有「線」和「面」），
        所以依主檔名配對，再挑真正的面圖層裡最大的那個。"""
        z = zipfile.ZipFile(zip_path)

        groups = {}
        for n in z.namelist():
            if '.' not in n:
                continue
            stem, ext = n.rsplit('.', 1)
            ext = ext.lower()
            if ext in ('shp', 'dbf', 'cpg', 'prj'):
                groups.setdefault(stem, {})[ext] = n

        best = None
        for stem, m in groups.items():
            if 'shp' not in m or 'dbf' not in m:
                continue
            info = z.getinfo(m['shp'])
            with z.open(m['shp']) as fh:
                head = fh.read(100)
            if len(head) < 36:
                continue
            stype = struct.unpack('<i', head[32:36])[0]
            if stype not in (SHP_POLYGON, SHP_POLYGON_Z, SHP_POLYGON_M):
                continue                                  # 線、點圖層跳過
            if best is None or info.file_size > best[0]:
                best = (info.file_size, m)
        if best is None:
            raise ValueError('壓縮檔內找不到面圖層（.shp/.dbf）')
        m = best[1]

        enc = None
        if 'cpg' in m:
            enc = z.read(m['cpg']).decode('ascii', 'ignore').strip() or None

        layer = cls(name or os.path.basename(zip_path))
        layer._load_dbf(z.read(m['dbf']), enc)
        layer._load_shp(z.read(m['shp']))
        layer._build_index()
        return layer

    def _load_dbf(self, buf, enc):
        self.fields, self.rows = read_dbf(buf, enc)

    def _load_shp(self, buf):
        n = len(buf)
        pos = 100                                   # 檔頭固定 100 bytes
        coords = self.coords
        while pos + 8 <= n:
            _num, clen = struct.unpack('>ii', buf[pos:pos + 8])
            body = pos + 8
            pos = body + clen * 2                   # clen 以 16-bit word 計
            if body + 4 > len(buf):
                break
            stype = struct.unpack('<i', buf[body:body + 4])[0]
            if stype not in (SHP_POLYGON, SHP_POLYGON_Z, SHP_POLYGON_M):
                self.boxes.append(None)
                self.parts.append(())
                self.ranges.append((0, 0))
                continue

            box = struct.unpack('<4d', buf[body + 4:body + 36])
            nparts, npoints = struct.unpack('<ii', buf[body + 36:body + 44])
            p0 = body + 44
            partidx = struct.unpack('<%di' % nparts, buf[p0:p0 + 4 * nparts])
            c0 = p0 + 4 * nparts
            start = len(coords) // 2
            coords.frombytes(buf[c0:c0 + 16 * npoints])

            self.boxes.append(box)
            self.parts.append(partidx)
            self.ranges.append((start, npoints))

    def _build_index(self):
        cell = self.cell
        grid = self.grid
        xmin = ymin = float('inf')
        xmax = ymax = float('-inf')
        for i, box in enumerate(self.boxes):
            if box is None:
                continue
            bx0, by0, bx1, by1 = box
            xmin = min(xmin, bx0); ymin = min(ymin, by0)
            xmax = max(xmax, bx1); ymax = max(ymax, by1)
            for gx in range(int(bx0 // cell), int(bx1 // cell) + 1):
                for gy in range(int(by0 // cell), int(by1 // cell) + 1):
                    grid.setdefault((gx, gy), []).append(i)
        self.extent = None if xmin == float('inf') else (xmin, ymin, xmax, ymax)
        # 有些開放資料沒附 .prj。用座標範圍判斷是二度分帶還是經緯度：
        # TM2 的 X 是六位數、Y 是七位數；經緯度絕對值不會超過 180。
        self.is_lonlat = bool(self.extent) and abs(xmax) <= 180 and abs(ymax) <= 90

    def to_layer_xy(self, lon, lat, tm2_xy):
        """把查詢點換成這個圖層自己的座標系。"""
        return (lon, lat) if self.is_lonlat else tm2_xy

    # ---- 查詢 ----

    def contains(self, x, y):
        """回傳所有包含 (x, y) 的圖徵索引。"""
        bucket = self.grid.get((int(x // self.cell), int(y // self.cell)))
        if not bucket:
            return []
        hits = []
        for i in bucket:
            box = self.boxes[i]
            if box[0] <= x <= box[2] and box[1] <= y <= box[3] and self._hit(i, x, y):
                hits.append(i)
        return hits

    def _hit(self, i, x, y):
        """射線法。所有環一起算交叉次數 — 奇數在內，因此內環（洞）自動被扣掉。"""
        start, npts = self.ranges[i]
        if npts == 0:
            return False
        c = self.coords
        partidx = self.parts[i]
        inside = False
        for p in range(len(partidx)):
            a = partidx[p]
            b = partidx[p + 1] if p + 1 < len(partidx) else npts
            base = (start + a) * 2
            cnt = b - a
            jx = c[base + (cnt - 1) * 2]
            jy = c[base + (cnt - 1) * 2 + 1]
            for k in range(cnt):
                ix = c[base + k * 2]
                iy = c[base + k * 2 + 1]
                if (iy > y) != (jy > y):
                    if x < (jx - ix) * (y - iy) / (jy - iy) + ix:
                        inside = not inside
                jx, jy = ix, iy
        return inside

    def attrs(self, i):
        row = self.rows[i] if i < len(self.rows) else None
        if not row:
            return {}
        return dict(zip(self.fields, row))

    def query_all(self, x, y):
        """回傳所有命中圖徵的屬性，由小到大排序。

        圖資常常同時含有「計畫範圍」這種涵蓋全區的大多邊形，和真正的分區小多邊形；
        面積小的才是我們要的答案，所以依外接矩形面積排序交給呼叫端挑。
        """
        hits = []
        for i in self.contains(x, y):
            a = self.attrs(i)
            if not a:
                continue
            b = self.boxes[i]
            hits.append(((b[2] - b[0]) * (b[3] - b[1]), a))
        hits.sort(key=lambda t: t[0])
        return [a for _, a in hits]

    def query(self, x, y):
        """回傳最小的命中圖徵，沒有就回 None。"""
        hits = self.query_all(x, y)
        return hits[0] if hits else None

    @property
    def feature_count(self):
        return sum(1 for b in self.boxes if b is not None)
