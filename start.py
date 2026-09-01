#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地籍圖 / 使用分區查詢 App - 本機啟動器

用法:
    python start.py                 # 只有本機可連 (127.0.0.1)
    python start.py --lan           # 同一個 Wi-Fi 的手機也能連
    python start.py --port 8080
    python start.py --no-browser

伺服器職責:
  1. 提供 web/ 靜態檔案
  2. /proxy?u=<urlencoded>  代理政府圖磚與 API
     - 加上 CORS 標頭, 讓前端能用 canvas 取樣圖磚顏色
     - 繞過 Python 3.13 對部分政府憑證的 strict 驗證問題
     - 只允許 allowlist 內的網域, 且不偽造 Referer
"""

import argparse
import gzip
import io
import json
import math
import mimetypes
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from collections import OrderedDict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import datasets as DS
import geo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")

# 只代理這些網域 (字尾比對)
ALLOWED_HOST_SUFFIXES = (
    ".nlsc.gov.tw",
    ".moi.gov.tw",
    ".nlma.gov.tw",
    ".gov.tw",
    "nominatim.openstreetmap.org",
    "data.taipei",
)

UA = "landmap-tw/1.0 (local desktop app; +https://github.com/)"

# Python 3.13 預設開啟 VERIFY_X509_STRICT, 部分政府憑證缺 Subject Key Identifier
# 會直接被拒。這裡只關掉 strict 附加檢查, 仍然完整驗證憑證鏈與主機名稱。
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

_CACHE_MAX = 1500
_cache = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key):
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        body, ctype, stamp = hit
        if time.time() - stamp > 86400:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return body, ctype


def _cache_put(key, body, ctype):
    if len(body) > 2_000_000:
        return
    with _cache_lock:
        _cache[key] = (body, ctype, time.time())
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


# ── 簡易速率限制 ──────────────────────────────────────────────
#
# 服務放到公網之後，比較怕的是有人猛打 /api/data/fetch（一次觸發幾十 MB 下載）
# 或狂查各縣市的圖服務 —— 那些請求都是從這台機器的 IP 發出去的，
# 打太兇可能害自己被對方擋掉。這裡按來源 IP 做很粗的節流。

_rate = {}
_rate_lock = threading.Lock()


def rate_ok(ip, bucket, limit, window):
    """同一個 IP 在 window 秒內最多 limit 次。超過回 False。"""
    now = time.time()
    key = (ip, bucket)
    with _rate_lock:
        hits = [t for t in _rate.get(key, ()) if now - t < window]
        if len(hits) >= limit:
            _rate[key] = hits
            return False
        hits.append(now)
        _rate[key] = hits
        if len(_rate) > 5000:            # 別讓字典無限長大
            cutoff = now - 3600
            for k in [k for k, v in _rate.items() if not v or v[-1] < cutoff]:
                _rate.pop(k, None)
    return True


def host_allowed(host):
    host = (host or "").lower().split(":")[0]
    return any(host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_HOST_SUFFIXES)


# ── 圖徵查詢：開放資料 SHP 的點查詢 ──────────────────────────────
#
# 圖磚只能給顏色，給不了名稱。政府資料開放平臺的 SHP 帶屬性表，
# 所以下載之後就能回答「這個點是特定農業區」而不是「這個點是黃色」。

_layers = OrderedDict()          # (key, county) -> PolygonLayer，最多留 3 個縣市
_layers_lock = threading.Lock()
_downloading = {}                # (key, county) -> threading.Event


def norm_county(name):
    return (name or "").strip().replace("台", "臺")


def cache_path(key, county, idx):
    return os.path.join(DATA_DIR, "%s_%s_%d.zip" % (key, county, idx))


def cached_parts(key, county):
    """已下載的分檔路徑；沒下齊就回空 list。"""
    want = DS.parts(key, county)
    if not want:
        return []
    paths = []
    for i in range(len(want)):
        p = cache_path(key, county, i)
        if not (os.path.isfile(p) and os.path.getsize(p) > 1024):
            return []
        paths.append(p)
    return paths


def is_cached(key, county):
    return bool(cached_parts(key, county))


class MergedLayer:
    """一個縣市可能拆成好幾個 SHP（分區/編定的 _01 _02、臺北的細部+主要計畫），
    查詢時依登錄順序問過去，先問到的優先。"""

    def __init__(self, layers):
        self.layers = layers

    def query_all(self, lon, lat, tm2):
        out = []
        for lay in self.layers:
            x, y = lay.to_layer_xy(lon, lat, tm2)
            out.extend(lay.query_all(x, y))
        return out


def get_layer(key, county):
    """載入（並快取）某縣市圖層；沒下載齊就回 None。"""
    ck = (key, county)
    with _layers_lock:
        if ck in _layers:
            _layers.move_to_end(ck)
            return _layers[ck]
    paths = cached_parts(key, county)
    if not paths:
        return None
    merged = MergedLayer([geo.PolygonLayer.from_zip(p, county) for p in paths])
    with _layers_lock:
        _layers[ck] = merged
        _layers.move_to_end(ck)
        while len(_layers) > 3:
            _layers.popitem(last=False)
    return merged


def download_dataset(key, county):
    """下載一個縣市的全部分檔到 data/。同一份同時只會下載一次。"""
    ck = (key, county)
    with _layers_lock:
        ev = _downloading.get(ck)
        if ev is None:
            ev = _downloading[ck] = threading.Event()
            owner = True
        else:
            owner = False
    if not owner:
        ev.wait(900)
        return is_cached(key, county)

    try:
        want = DS.parts(key, county)
        if not want:
            return False
        os.makedirs(DATA_DIR, exist_ok=True)
        for i, (url, _size) in enumerate(want):
            dest = cache_path(key, county, i)
            if os.path.isfile(dest) and os.path.getsize(dest) > 1024:
                continue
            tmp = dest + ".part"
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            resp = urllib.request.urlopen(req, timeout=600, context=_SSL_CTX)
            with resp, open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
            # 確認是可讀的 shapefile 壓縮檔才啟用，免得半路斷線留下壞檔
            with zipfile.ZipFile(tmp) as z:
                if not any(n.lower().endswith(".shp") for n in z.namelist()):
                    raise ValueError("下載內容不是 shapefile")
            os.replace(tmp, dest)
        return True
    except Exception as e:
        sys.stderr.write("下載失敗 %s/%s: %r\n" % (key, county, e))
        for i in range(len(DS.parts(key, county))):
            try:
                os.remove(cache_path(key, county, i) + ".part")
            except OSError:
                pass
        return False
    finally:
        with _layers_lock:
            _downloading.pop(ck, None)
        ev.set()


def pick_value(attrs, candidates, exact=False):
    """欄位名可能被 DBF 截短或各縣市略有差異，先精確比對再退回子字串比對。

    exact=True 時只做精確比對 —— 附加欄位（建蔽率之類）寧可不顯示，
    也不要用模糊比對硬湊出一個錯的數字。
    """
    if not attrs:
        return None
    for c in candidates:
        if c in attrs and attrs[c]:
            return attrs[c]
    if exact:
        return None
    for c in candidates:
        for k, v in attrs.items():
            if v and (c in k or k in c):
                return v
    return None


def to_mercator(lon, lat):
    """WGS84 經緯度 -> Web Mercator，給 wkid 102100/3857 的圖層用。"""
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * 20037508.34 / 180.0


def ring_area_m2(ring_lonlat):
    """用 TWD97 二度分帶把宗地環的面積算出來（平面 shoelace）。

    服務沒給面積欄位時就用這個補。實測跟有面積欄位的縣市對照，
    誤差在 0.1% 以內（另有 1~2% 的案例，那是登記面積與圖形面積本來就會有的差）。
    """
    pts = [geo.lonlat_to_tm2(p[0], p[1]) for p in ring_lonlat]
    s2 = 0.0
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        s2 += a[0] * b[1] - b[0] * a[1]
    return abs(s2) / 2.0


def query_arcgis(cfg, x, y, lon=None, lat=None, want_geometry=False):
    """向縣市公開的 ArcGIS MapServer 做點查詢，回傳屬性 dict（沒命中回 None）。

    有些縣市把都市計畫使用分區或地籍圖以公開的 ArcGIS 服務發布，
    直接查就好，不必下載整份圖資。
    x/y 是 TWD97 二度分帶；若圖層用 Web Mercator 就改送換算後的座標。
    """
    wkid = cfg.get("wkid", 102443)
    if wkid in (102100, 3857) and lon is not None:
        x, y = to_mercator(lon, lat)
    geom = json.dumps({"x": x, "y": y,
                       "spatialReference": {"wkid": wkid}})
    params = {
        "f": "json",
        "geometry": geom,
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true" if want_geometry else "false",
        # 不要加 resultRecordCount：舊版 ArcGIS Server 不認得，會整個請求回 400
    }
    # 幾何一律要經緯度回來，各縣市圖層座標系不同，統一比較好處理。
    # outSR 不能送空值，所以只在真的要幾何時才帶。
    if want_geometry:
        params["outSR"] = "4326"
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(cfg["url"] + "?" + qs, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "服務回應錯誤"))
    feats = data.get("features") or []
    if not feats:
        return None
    # 面積最小的那筆最精確（跟本機圖資的處理一致）
    def area(f):
        a = f.get("attributes", {})
        for k in ("Shape.STArea()", "uarea", "AREA", "SHAPE_Area"):
            try:
                return float(a.get(k))
            except (TypeError, ValueError):
                continue
        return float("inf")
    feats.sort(key=area)
    best = feats[0]
    # 有些服務的空欄位是空白字串或全形空白，統一清掉，免得畫面出現「備註= 」
    attrs = {k: ("" if v is None else str(v).strip())
             for k, v in best.get("attributes", {}).items()}
    if want_geometry:
        rings = (best.get("geometry") or {}).get("rings")
        if rings:
            attrs["__rings"] = rings
    return attrs


PING = 400.0 / 121.0            # 1 坪 = 3.3057851 m²


def format_landno(cfg, attrs):
    """把各縣市不同寫法的地號整理成「1165」「47-2」這種標準顯示法。

    地政系統裡地號是 8 碼：母號 4 碼 + 子號 4 碼。子號 0000 時不顯示。
    有些縣市已經幫忙格式化好（LAND_NO），有的只給 8 碼或母子號分欄。
    """
    ready = pick_value(attrs, cfg.get("landno", []), exact=True)
    if ready:
        return str(ready).strip()

    eight = pick_value(attrs, cfg.get("landno8", []), exact=True)
    mother = child = None
    if eight and str(eight).strip().isdigit() and len(str(eight).strip()) == 8:
        e = str(eight).strip()
        mother, child = e[:4], e[4:]
    else:
        mother = pick_value(attrs, cfg.get("mother", []), exact=True)
        child = pick_value(attrs, cfg.get("child", []), exact=True)
    if mother is None:
        return None
    try:
        m = int(str(mother))
        c = int(str(child)) if child not in (None, "") else 0
    except ValueError:
        return str(mother)
    return "%d-%d" % (m, c) if c else "%d" % m


def query_cadastre(lat, lon, county, sect_hint=None):
    """座標查地號。只有登錄了公開地籍圖服務的縣市查得到。

    sect_hint 是前端從國土測繪中心點位反查拿到的段名 —— 有些縣市的地籍圖層
    只存段碼不存段名，就用這個補上。
    """
    county = norm_county(county)
    cfg = DS.cadastre(county)
    if not cfg:
        return {
            "status": "unavailable",
            "county": county,
            "message": "尚未登錄 %s 的公開地籍圖服務" % (county or "此縣市"),
        }
    x, y = geo.lonlat_to_tm2(lon, lat)
    try:
        attrs = query_arcgis(cfg, x, y, lon, lat, want_geometry=True)
    except Exception as e:
        return {"status": "error", "county": county,
                "message": "%s 的地籍服務目前無法使用：%s" % (county, e)}
    if not attrs:
        return {"status": "no-feature", "county": county,
                "message": "此點查不到宗地（可能在道路、河川或圖籍空白處）"}

    out = {
        "status": "ok",
        "county": county,
        "source": cfg.get("source", ""),
        "sect": pick_value(attrs, cfg.get("sect", []), exact=True) or (sect_hint or None),
        "sectCode": pick_value(attrs, cfg.get("sectcode", []), exact=True),
        "landNo": format_landno(cfg, attrs),
        "town": pick_value(attrs, cfg.get("town", []), exact=True),
        "office": pick_value(attrs, cfg.get("office", []), exact=True),
    }
    rings = attrs.pop("__rings", None)
    if rings:
        # 宗地輪廓給前端畫在地圖上（只取外環）
        out["rings"] = [[[p[1], p[0]] for p in r] for r in rings[:1]]

    area = pick_value(attrs, cfg.get("area", []), exact=True)
    a = None
    try:
        a = float(area)
        if a <= 0:
            a = None
        else:
            out["areaFrom"] = "service"
    except (TypeError, ValueError):
        a = None
    if a is None and rings:
        a = ring_area_m2(rings[0])
        out["areaFrom"] = "geometry"
    if a:
        out["areaM2"] = round(a, 2)
        out["areaPing"] = round(a / PING, 2)
    if out["sect"] and out["landNo"]:
        out["full"] = "%s%s %s地號" % (out.get("town") or "", out["sect"], out["landNo"])
    return out


def find_parcel(county, sect, land_no):
    """依「段名或段碼 + 地號」找宗地，回傳幾何供前端定位。

    各縣市欄位名稱不同，但存的格式一致：段碼 4 碼、地號 8 碼
    （母號 4 ＋ 子號 4）。有些縣市拆成 mother/child 兩欄；桃園只有段碼
    沒有段名，用段名就查不到 —— 那種情況直接說明，不要讓使用者對著
    空結果猜。
    """
    county = norm_county(county)
    cfg = DS.cadastre(county)
    if not cfg:
        return {"status": "unavailable", "county": county,
                "message": "尚未登錄 %s 的公開地籍圖服務" % (county or "此縣市")}

    m = re.match(r"^(\d{1,4})\s*(?:[-－之]\s*(\d{1,4}))?$", (land_no or "").strip())
    if not m:
        return {"status": "bad-input",
                "message": "地號請填數字，子號用連字號，例如 880 或 880-1"}
    mother, child = m.group(1), m.group(2) or "0"

    # 這些值會進到 where 條件，只留中文、英數與連字號
    sect_txt = re.sub(r"[^一-龥A-Za-z0-9\-]", "", (sect or "").strip())
    if not sect_txt:
        return {"status": "bad-input", "message": "請指定段名或四碼段代碼"}

    def first(key):
        v = cfg.get(key) or []
        return v[0] if v else None

    conds = []
    if re.match(r"^\d{1,4}$", sect_txt):
        f = first("sectcode")
        if not f:
            return {"status": "unsupported", "message": "這個縣市的圖層沒有段代碼欄位"}
        conds.append("%s = '%s'" % (f, sect_txt.zfill(4)))
    else:
        f = first("sect")
        if not f:
            return {"status": "unsupported",
                    "message": "這個縣市的圖層沒有段名欄位，請改用四碼段代碼查詢"}
        conds.append("%s = '%s'" % (f, sect_txt))

    eight, mf, cf, lf = first("landno8"), first("mother"), first("child"), first("landno")
    if eight:
        conds.append("%s = '%s'" % (eight, mother.zfill(4) + child.zfill(4)))
    elif mf and cf:
        conds.append("%s = '%s'" % (mf, mother.zfill(4)))
        conds.append("%s = '%s'" % (cf, child.zfill(4)))
    elif lf:
        human = str(int(mother)) + ("-%d" % int(child) if int(child) else "")
        conds.append("%s = '%s'" % (lf, human))
    else:
        return {"status": "unsupported", "message": "這個縣市的圖層沒有地號欄位"}

    params = {
        "f": "json", "where": " AND ".join(conds), "outFields": "*",
        "returnGeometry": "true", "outSR": "4326",
    }
    url = cfg["url"] + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        if data.get("error"):
            raise RuntimeError(data["error"].get("message", "服務回應錯誤"))
    except Exception as e:
        return {"status": "error", "county": county,
                "message": "%s 的地籍服務目前無法使用：%s" % (county, e)}

    feats = data.get("features") or []
    if not feats:
        return {"status": "not-found", "county": county,
                "message": "在 %s %s 找不到 %s 地號" % (county, sect_txt, land_no)}

    f0 = feats[0]
    attrs = f0.get("attributes") or {}
    rings = (f0.get("geometry") or {}).get("rings") or []
    out = {
        "status": "ok", "county": county, "matches": len(feats),
        "sect": pick_value(attrs, cfg.get("sect") or [], exact=True) or sect_txt,
        "sectCode": pick_value(attrs, cfg.get("sectcode") or [], exact=True),
        "landNo": format_landno(cfg, attrs),
        "town": pick_value(attrs, cfg.get("town") or [], exact=True),
        "rings": [[[p[1], p[0]] for p in ring] for ring in rings],
    }
    a = None
    try:
        a = float(pick_value(attrs, cfg.get("area") or [], exact=True))
    except (TypeError, ValueError):
        a = None
    if (a is None or a <= 0) and rings:
        a = ring_area_m2(rings[0])
    if a and a > 0:
        out["areaM2"] = round(a, 2)
        out["areaPing"] = round(a / PING, 2)
    return out


def query_parcels(county, xmin, ymin, xmax, ymax, limit=1200):
    """把一個矩形範圍內的宗地全部撈出來，給前端在圖上標地號。

    用 esriGeometryEnvelope 做範圍查詢。回傳的幾何統一要經緯度，
    前端直接畫多邊形並在形心標上地號。
    """
    county = norm_county(county)
    cfg = DS.cadastre(county)
    if not cfg:
        return {"status": "unavailable", "county": county,
                "message": "尚未登錄 %s 的公開地籍圖服務" % (county or "此縣市")}

    wkid = cfg.get("wkid", 102443)
    if wkid in (102100, 3857):
        a = to_mercator(xmin, ymin)
        b = to_mercator(xmax, ymax)
        env = {"xmin": a[0], "ymin": a[1], "xmax": b[0], "ymax": b[1],
               "spatialReference": {"wkid": wkid}}
    else:
        a = geo.lonlat_to_tm2(xmin, ymin)
        b = geo.lonlat_to_tm2(xmax, ymax)
        env = {"xmin": a[0], "ymin": a[1], "xmax": b[0], "ymax": b[1],
               "spatialReference": {"wkid": wkid}}

    params = {
        "f": "json",
        "geometry": json.dumps(env),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
    }
    url = cfg["url"] + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"status": "error", "county": county,
                "message": "%s 的地籍服務無法使用：%s" % (county, e)}
    if data.get("error"):
        return {"status": "error", "county": county,
                "message": data["error"].get("message", "服務回應錯誤")}

    out = []
    for f in (data.get("features") or [])[:limit]:
        attrs = {k: ("" if v is None else str(v).strip())
                 for k, v in (f.get("attributes") or {}).items()}
        rings = (f.get("geometry") or {}).get("rings")
        if not rings:
            continue
        no = format_landno(cfg, attrs)
        if not no:
            continue
        out.append({
            "landNo": no,
            "sect": pick_value(attrs, cfg.get("sect", []), exact=True),
            "ring": [[p[1], p[0]] for p in rings[0]],
        })
    # 服務自己截斷，或撞到我們這邊的上限，都算沒標齊
    truncated = bool(data.get("exceededTransferLimit")) or len(out) >= limit
    return {"status": "ok", "county": county, "count": len(out),
            "exceeded": truncated, "parcels": out}


def query_zoning(lat, lon, county):
    """回傳各已登錄圖層在該點的查詢結果。"""
    county = norm_county(county)
    x, y = geo.lonlat_to_tm2(lon, lat)
    out = []
    for key, ds in DS.DATASETS.items():
        item = {
            "key": key,
            "title": ds["title"],
            "source": ds["source"],
            "sourceUrl": ds["source_url"],
            "licence": ds["licence"],
        }
        if county not in ds["counties"]:
            item["status"] = "unavailable"
            item["message"] = ds.get("missing_message", "這份資料沒有 %s 的檔案") % (county or "此縣市")
            out.append(item)
            continue
        svc = DS.service(key, county)
        if svc:
            # 走縣市自己的公開查詢服務，不需要下載
            try:
                attrs = query_arcgis(svc, x, y, lon, lat)
                hits = [attrs] if attrs else []
            except Exception as e:
                item["status"] = "error"
                item["message"] = "%s 的查詢服務目前無法使用：%s" % (county, e)
                out.append(item)
                continue
            item["live"] = True
        else:
            if not is_cached(key, county):
                item["status"] = "needs-download"
                item["county"] = county
                item["sizeMB"] = round(DS.total_size(key, county) / 1048576.0, 1)
                out.append(item)
                continue
            try:
                layer = get_layer(key, county)
                hits = layer.query_all(lon, lat, (x, y)) if layer else []
            except Exception as e:
                item["status"] = "error"
                item["message"] = "讀取失敗：%r" % (e,)
                out.append(item)
                continue

        # hits 已由小到大排序。圖資常含「計畫範圍」這種涵蓋全區、屬性是空的大多邊形，
        # 所以取第一個真的有分區名稱的。
        attrs = None
        value = None
        for h in hits:
            v = pick_value(h, ds["value_fields"])
            if v:
                attrs, value = h, v
                break

        if not attrs:
            item["status"] = "no-feature"
            item["message"] = ds.get("empty_message") or \
                "此點不在非都市土地範圍內（多半代表它屬於都市計畫區或國家公園）"
        else:
            item["status"] = "ok"
            item["value"] = value
            code = pick_value(attrs, ds["code_fields"])
            # 有些圖資（例如新北市）只有一個欄位，代碼比對會退回抓到同一個值 —— 那就別重複顯示
            item["code"] = None if code == value else code
            extras = []
            for label, cands in ds.get("extra_fields", []):
                v = pick_value(attrs, cands, exact=True)
                v = v.strip() if isinstance(v, str) else v
                if v and v != value:
                    extras.append([label, v])
            item["extras"] = extras
            item["attrs"] = attrs
        item["county"] = county
        out.append(item)
    return {"lat": lat, "lon": lon, "twd97": {"x": round(x, 2), "y": round(y, 2)}, "layers": out}


def dataset_status():
    out = []
    for key, ds in DS.DATASETS.items():
        counties = []
        for c in sorted(ds["counties"]):
            live = DS.service(key, c) is not None
            counties.append({
                "county": c,
                "live": live,
                "sizeMB": 0 if live else round(DS.total_size(key, c) / 1048576.0, 1),
                "cached": live or is_cached(key, c),
            })
        out.append({
            "key": key, "title": ds["title"], "short": ds["short"],
            "source": ds["source"], "sourceUrl": ds["source_url"],
            "licence": ds["licence"], "counties": counties,
        })
    return out


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    # 安靜一點, 只印錯誤
    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/proxy":
            return self.handle_proxy(parsed)
        if parsed.path.startswith("/api/") and not rate_ok(self.client_ip(), "api", 240, 60):
            return self.fail(429, "請求太頻繁，請稍後再試")
        if parsed.path == "/api/zoning":
            return self.handle_zoning(parsed)
        if parsed.path == "/api/cadastre":
            return self.handle_cadastre(parsed)
        if parsed.path == "/api/parcels":
            return self.handle_parcels(parsed)
        if parsed.path == "/api/parcel-find":
            return self.handle_parcel_find(parsed)
        if parsed.path == "/api/data":
            return self.json_ok({"datasets": dataset_status()})
        if parsed.path == "/api/data/fetch":
            return self.handle_fetch(parsed)
        return super().do_GET()

    def handle_zoning(self, parsed):
        q = urllib.parse.parse_qs(parsed.query)
        try:
            lat = float((q.get("lat") or [""])[0])
            lon = float((q.get("lon") or [""])[0])
        except ValueError:
            return self.fail(400, "lat/lon 格式錯誤")
        county = (q.get("county") or [""])[0]
        try:
            return self.json_ok(query_zoning(lat, lon, county))
        except Exception as e:
            return self.fail(500, "查詢失敗：%r" % (e,))

    def handle_cadastre(self, parsed):
        q = urllib.parse.parse_qs(parsed.query)
        try:
            lat = float((q.get("lat") or [""])[0])
            lon = float((q.get("lon") or [""])[0])
        except ValueError:
            return self.fail(400, "lat/lon 格式錯誤")
        county = (q.get("county") or [""])[0]
        sect = (q.get("sect") or [""])[0]
        try:
            return self.json_ok(query_cadastre(lat, lon, county, sect))
        except Exception as e:
            return self.fail(500, "查詢失敗：%r" % (e,))

    def handle_parcels(self, parsed):
        q = urllib.parse.parse_qs(parsed.query)
        try:
            bbox = [float(v) for v in (q.get("bbox") or [""])[0].split(",")]
            if len(bbox) != 4:
                raise ValueError
        except ValueError:
            return self.fail(400, "bbox 需為 lonMin,latMin,lonMax,latMax")
        county = (q.get("county") or [""])[0]
        try:
            return self.json_ok(query_parcels(county, *bbox))
        except Exception as e:
            return self.fail(500, "查詢失敗：%r" % (e,))

    def handle_parcel_find(self, parsed):
        q = urllib.parse.parse_qs(parsed.query)
        county = (q.get("county") or [""])[0]
        sect = (q.get("sect") or [""])[0]
        no = (q.get("no") or [""])[0]
        try:
            return self.json_ok(find_parcel(county, sect, no))
        except Exception as e:
            return self.fail(500, "查詢失敗：%r" % (e,))

    def client_ip(self):
        # 經過 Cloudflare Tunnel 時真實來源在這個標頭裡
        return (self.headers.get("CF-Connecting-IP")
                or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def handle_fetch(self, parsed):
        # 下載很貴，同一個 IP 每 10 分鐘最多 6 次
        if not rate_ok(self.client_ip(), "fetch", 6, 600):
            return self.fail(429, "下載請求太頻繁，請稍後再試")
        q = urllib.parse.parse_qs(parsed.query)
        key = (q.get("key") or [""])[0]
        county = norm_county((q.get("county") or [""])[0])
        if key not in DS.DATASETS:
            return self.fail(400, "未知的資料集")
        if county not in DS.DATASETS[key]["counties"]:
            return self.fail(404, "這份資料沒有 %s" % county)
        if is_cached(key, county):
            return self.json_ok({"ok": True, "cached": True})
        ok = download_dataset(key, county)
        return self.json_ok({"ok": ok, "cached": ok})

    def json_ok(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def end_headers(self):
        # 開發用: 不要讓瀏覽器快取住 app 檔案
        if self.path.endswith((".js", ".css", ".html", "/")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def handle_proxy(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        target = (qs.get("u") or [""])[0]
        if not target:
            return self.fail(400, "missing u")

        sp = urllib.parse.urlsplit(target)
        if sp.scheme not in ("http", "https"):
            return self.fail(400, "bad scheme")
        if not host_allowed(sp.netloc):
            return self.fail(403, "host not allowed: %s" % sp.netloc)

        cached = _cache_get(target)
        if cached:
            body, ctype = cached
            return self.ok(body, ctype, cache_hit=True)

        req = urllib.request.Request(
            target,
            headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        pass
                ctype = r.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            return self.fail(e.code, "upstream %s" % e.code)
        except Exception as e:
            return self.fail(502, "upstream error: %s" % e.__class__.__name__)

        _cache_put(target, raw, ctype)
        self.ok(raw, ctype)

    def ok(self, body, ctype, cache_hit=False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Proxy-Cache", "HIT" if cache_hit else "MISS")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def fail(self, code, msg):
        body = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass


def find_openssl():
    """Windows 上 openssl 通常不在 PATH，但 Git for Windows 有帶。"""
    import shutil
    p = shutil.which("openssl")
    if p:
        return p
    for cand in (r"C:\Program Files\Git\usr\bin\openssl.exe",
                 r"C:\Program Files\Git\mingw64\bin\openssl.exe",
                 r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
                 "/usr/bin/openssl"):
        if os.path.isfile(cand):
            return cand
    return None


def ensure_cert(ip):
    """產生（或沿用）自簽憑證。

    手機瀏覽器只在 https 或 localhost 底下給 GPS 權限，
    所以要在區網用定位就得走 https。自簽憑證第一次會跳安全警告，
    選「繼續前往」即可 —— 這是你自己電腦上的伺服器。
    """
    cert_dir = os.path.join(BASE_DIR, "certs")
    crt = os.path.join(cert_dir, "landmap.crt")
    key = os.path.join(cert_dir, "landmap.key")
    marker = os.path.join(cert_dir, "issued-for.txt")

    if all(os.path.isfile(f) for f in (crt, key, marker)):
        try:
            if open(marker, encoding="utf-8").read().strip() == ip:
                return crt, key
        except OSError:
            pass

    exe = find_openssl()
    if not exe:
        return None, None

    os.makedirs(cert_dir, exist_ok=True)
    san = "subjectAltName=DNS:localhost,IP:127.0.0.1"
    if ip and ip != "127.0.0.1":
        san += ",IP:" + ip
    cmd = [exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
           "-keyout", key, "-out", crt, "-days", "3650",
           "-subj", "/CN=landmap-tw", "-addext", san]
    try:
        import subprocess
        subprocess.run(cmd, check=True, capture_output=True, timeout=90)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(ip or "")
        return crt, key
    except Exception as e:
        sys.stderr.write("憑證產生失敗：%r\n" % (e,))
        return None, None


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="地籍圖 / 使用分區查詢 App")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--lan", action="store_true", help="開放區網 (手機可連)")
    ap.add_argument("--https", action="store_true",
                    help="用自簽憑證走 https —— 手機在區網要用 GPS 定位就需要這個")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    mimetypes.add_type("application/manifest+json", ".webmanifest")
    mimetypes.add_type("text/javascript", ".js")

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((host, args.port), Handler)
    srv.daemon_threads = True

    ip = lan_ip()
    scheme = "http"
    if args.https:
        crt, key = ensure_cert(ip)
        if crt:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(crt, key)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            scheme = "https"
        else:
            print("  !! 找不到 openssl，無法產生憑證，改用 http")

    local = "%s://127.0.0.1:%d/" % (scheme, args.port)
    print("=" * 58)
    print("  地籍圖 / 使用分區查詢")
    print("=" * 58)
    print("  本機   %s" % local)
    if args.lan:
        print("  手機   %s://%s:%d/   (同一個 Wi-Fi)" % (scheme, ip, args.port))
        if scheme == "http":
            print("         注意：http 下手機瀏覽器不給 GPS 權限，")
            print("               要用定位請改加 --https")
        else:
            print("         第一次會跳憑證警告，選「進階 → 繼續前往」即可")
    print("  停止   Ctrl+C")
    print("=" * 58)

    # 把當下的網址寫成檔案 —— IP 是 DHCP 取得的，重開機後可能會變，
    # 開機自動啟動時沒有終端機可看，就從這個檔案查。
    try:
        lines = ["地籍圖 / 使用分區查詢",
                 "更新時間：" + time.strftime("%Y-%m-%d %H:%M:%S"),
                 "",
                 "電腦：" + local]
        if args.lan:
            lines.append("手機：%s://%s:%d/   （要連同一個 Wi-Fi）" % (scheme, ip, args.port))
            if scheme == "https":
                lines += ["", "手機第一次開會跳憑證警告，選「進階 → 繼續前往」即可。"]
        with open(os.path.join(BASE_DIR, "目前網址.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        # 記下自己的 PID，讓「停止伺服器.bat」找得到要關哪一個
        with open(os.path.join(BASE_DIR, ".server.pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(local)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n再見。")
    finally:
        srv.server_close()
        try:
            os.remove(os.path.join(BASE_DIR, ".server.pid"))
        except OSError:
            pass


if __name__ == "__main__":
    main()
