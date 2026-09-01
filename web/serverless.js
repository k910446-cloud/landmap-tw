/* 無伺服器模式 —— 由瀏覽器直接查各縣市的 ArcGIS 服務。
 *
 * 本機完整版有 Python 後端，查詢都走 /api/*；放到 GitHub Pages 之後沒有後端，
 * 就改用這裡的函式直接打縣市服務。只有會送 CORS 標頭的縣市能這樣用，
 * 名單在 services.js（由 build_static.py 從 datasets.py 產生）。
 *
 * 幾何與面積的算法刻意跟後端 start.py / geo.py 一致：
 * 統一取 WGS84 經緯度回來，換算成 TWD97 二度分帶後用平面公式求積。
 */
(function (g) {
  'use strict';

  var PING = 400 / 121;          // 1 坪 = 3.3057851 m²
  var R = 6378137.0;

  function toMercator(lon, lat) {
    return [
      lon * 20037508.34 / 180,
      Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180) * 20037508.34 / 180
    ];
  }

  function toTM2(lon, lat) {
    var p = TWD.toTM2(lat, lon);
    return [p.x, p.y];
  }

  // 依圖層座標系決定要送什麼座標進去
  function projectPoint(cfg, lon, lat) {
    var wkid = cfg.wkid || 102443;
    return (wkid === 102100 || wkid === 3857) ? toMercator(lon, lat) : toTM2(lon, lat);
  }

  function ringAreaM2(ringLonLat) {
    var pts = ringLonLat.map(function (p) { return toTM2(p[0], p[1]); });
    var s = 0;
    for (var i = 0, n = pts.length; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(s) / 2;
  }

  function pick(attrs, cands, exact) {
    if (!attrs || !cands) return null;
    for (var i = 0; i < cands.length; i++) {
      var c = cands[i];
      if (attrs[c] != null && String(attrs[c]).trim() !== '') return String(attrs[c]).trim();
    }
    if (exact) return null;
    for (var j = 0; j < cands.length; j++) {
      for (var k in attrs) {
        var v = attrs[k];
        if (v != null && String(v).trim() !== ''
          && (k.indexOf(cands[j]) >= 0 || cands[j].indexOf(k) >= 0)) return String(v).trim();
      }
    }
    return null;
  }

  // 地號在地政系統裡是 8 碼：母號 4 + 子號 4。子號 0000 時不顯示。
  function formatLandNo(cfg, attrs) {
    var ready = pick(attrs, cfg.landno || [], true);
    if (ready) return ready;

    var mother = null, child = null;
    var eight = pick(attrs, cfg.landno8 || [], true);
    if (eight && /^\d{8}$/.test(eight)) {
      mother = eight.slice(0, 4);
      child = eight.slice(4);
    } else {
      mother = pick(attrs, cfg.mother || [], true);
      child = pick(attrs, cfg.child || [], true);
    }
    if (mother == null) return null;
    var m = parseInt(mother, 10);
    var c = child ? parseInt(child, 10) : 0;
    if (isNaN(m)) return String(mother);
    return c ? (m + '-' + c) : String(m);
  }

  // 有些縣市的服務不送 CORS 標頭，瀏覽器不准直接讀，得繞自己的代理。
  // 沒設定代理時 needsProxy 的縣市會被擋在 guard() 那裡，不會走到這裡。
  function endpoint(cfg, qs) {
    var url = cfg.url + '?' + qs;
    if (cfg.needsProxy && window.PROXY_URL) {
      // 代理只看 u 參數，路徑不拘 —— 這樣同一段程式也能指向本機版的
      // /proxy 端點，方便在部署 Worker 之前先驗證整條路徑
      var base = window.PROXY_URL.replace(/\/+$/, '');
      return base + (base.indexOf('?') >= 0 ? '&' : '?') + 'u=' + encodeURIComponent(url);
    }
    return url;
  }

  // 需要代理卻沒設定時，講清楚是什麼情況、要怎麼解決
  function guard(cfg, county, title) {
    if (!cfg) {
      return { status: 'unavailable', county: county,
        message: '線上版沒有 ' + (county || '此縣市') + ' 的' + title };
    }
    if (cfg.needsProxy && !window.PROXY_URL) {
      return { status: 'unavailable', county: county,
        message: county + ' 的服務不允許瀏覽器直接連線（沒有送 CORS 標頭）。'
          + '要在線上版查這個縣市，需要自備一支代理 —— '
          + '原始碼與部署步驟在專案的 worker/ 資料夾。本機完整版不受影響。' };
    }
    return null;
  }

  function esriQuery(cfg, params) {
    var qs = Object.keys(params).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
    }).join('&');
    return fetch(endpoint(cfg, qs)).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (d) {
      if (d.error) throw new Error(d.error.message || '服務回應錯誤');
      return d;
    });
  }

  function smallestFirst(feats) {
    function area(f) {
      var a = f.attributes || {};
      var keys = ['Shape.STArea()', 'uarea', 'AREA', 'SHAPE_Area'];
      for (var i = 0; i < keys.length; i++) {
        var v = parseFloat(a[keys[i]]);
        if (!isNaN(v)) return v;
      }
      return Infinity;
    }
    return feats.slice().sort(function (a, b) { return area(a) - area(b); });
  }

  // ── 座標查地號 ──────────────────────────────────────────
  function cadastre(lat, lon, county, sectHint) {
    var cfg = (SERVICES.cadastre || {})[county];
    var stop = guard(cfg, county, '地籍服務');
    if (stop) return Promise.resolve(stop);
    var xy = projectPoint(cfg, lon, lat);
    return esriQuery(cfg, {
      f: 'json',
      geometry: JSON.stringify({ x: xy[0], y: xy[1], spatialReference: { wkid: cfg.wkid || 102443 } }),
      geometryType: 'esriGeometryPoint',
      spatialRel: 'esriSpatialRelIntersects',
      outFields: '*',
      returnGeometry: 'true',
      outSR: '4326'
    }).then(function (d) {
      var feats = smallestFirst(d.features || []);
      if (!feats.length) {
        return { status: 'no-feature', county: county,
          message: '此點查不到宗地（可能在道路、河川或圖籍空白處）' };
      }
      var f = feats[0], attrs = f.attributes || {};
      var rings = (f.geometry || {}).rings;
      var out = {
        status: 'ok', county: county,
        source: (cfg.source || '') + '（瀏覽器直連）',
        sect: pick(attrs, cfg.sect || [], true) || sectHint || null,
        sectCode: pick(attrs, cfg.sectcode || [], true),
        landNo: formatLandNo(cfg, attrs),
        town: pick(attrs, cfg.town || [], true),
        office: pick(attrs, cfg.office || [], true)
      };
      if (rings && rings.length) {
        out.rings = [rings[0].map(function (p) { return [p[1], p[0]]; })];
      }
      var a = parseFloat(pick(attrs, cfg.area || [], true));
      if (!isNaN(a) && a > 0) out.areaFrom = 'service';
      else if (rings && rings.length) { a = ringAreaM2(rings[0]); out.areaFrom = 'geometry'; }
      else a = NaN;
      if (!isNaN(a) && a > 0) {
        out.areaM2 = Math.round(a * 100) / 100;
        out.areaPing = Math.round(a / PING * 100) / 100;
      }
      return out;
    }).catch(function (e) {
      return { status: 'error', county: county,
        message: county + ' 的地籍服務目前無法使用：' + (e.message || e) };
    });
  }

  // ── 範圍內宗地（給地號標示用）──────────────────────────
  function parcels(county, w, s, e, n, limit) {
    limit = limit || 1200;
    var cfg = (SERVICES.cadastre || {})[county];
    var stop = guard(cfg, county, '地籍服務');
    if (stop) return Promise.resolve(stop);
    var a = projectPoint(cfg, w, s), b = projectPoint(cfg, e, n);
    return esriQuery(cfg, {
      f: 'json',
      geometry: JSON.stringify({
        xmin: a[0], ymin: a[1], xmax: b[0], ymax: b[1],
        spatialReference: { wkid: cfg.wkid || 102443 }
      }),
      geometryType: 'esriGeometryEnvelope',
      spatialRel: 'esriSpatialRelIntersects',
      outFields: '*',
      returnGeometry: 'true',
      outSR: '4326'
    }).then(function (d) {
      var out = [];
      (d.features || []).slice(0, limit).forEach(function (f) {
        var rings = (f.geometry || {}).rings;
        if (!rings || !rings.length) return;
        var no = formatLandNo(cfg, f.attributes || {});
        if (!no) return;
        out.push({
          landNo: no,
          sect: pick(f.attributes || {}, cfg.sect || [], true),
          ring: rings[0].map(function (p) { return [p[1], p[0]]; })
        });
      });
      return { status: 'ok', county: county, count: out.length,
        exceeded: !!d.exceededTransferLimit || out.length >= limit, parcels: out };
    }).catch(function (err) {
      return { status: 'error', county: county,
        message: county + ' 的地籍服務目前無法使用：' + (err.message || err) };
    });
  }

  // ── 使用分區 ────────────────────────────────────────────
  function zoning(lat, lon, county) {
    var F = SERVICES.urbanFields || { value: [], code: [], extra: [] };
    var layers = [];

    var cfg = (SERVICES.urban || {})[county];
    var urbanItem = {
      key: 'urban_zone', title: '都市計畫使用分區',
      source: '各直轄市／縣市政府 公開圖服務（瀏覽器直連）',
      sourceUrl: 'https://data.gov.tw/dataset/156197',
      licence: '各該市政府開放資料授權'
    };

    // 非都市分區與編定：讀 build_nurban.py 事先轉好的圖資，
    // 由瀏覽器自己做點在多邊形內判斷（見 nurban.js）
    var nurban = NUrban.datasets.map(function (k) {
      return NUrban.query(k, county, lat, lon);
    });

    function done() {
      return Promise.all(nurban).then(function (rows) {
        return { layers: [urbanItem].concat(rows) };
      });
    }

    var stop = guard(cfg, county, '都市計畫服務');
    if (stop) {
      urbanItem.status = stop.status;
      urbanItem.message = stop.message;
      return done();
    }

    var xy = projectPoint(cfg, lon, lat);
    return esriQuery(cfg, {
      f: 'json',
      geometry: JSON.stringify({ x: xy[0], y: xy[1], spatialReference: { wkid: cfg.wkid || 102443 } }),
      geometryType: 'esriGeometryPoint',
      spatialRel: 'esriSpatialRelIntersects',
      outFields: '*',
      returnGeometry: 'false'
    }).then(function (d) {
      var feats = smallestFirst(d.features || []);
      var attrs = null, value = null;
      for (var i = 0; i < feats.length; i++) {
        var v = pick(feats[i].attributes || {}, F.value, false);
        if (v) { attrs = feats[i].attributes; value = v; break; }
      }
      if (!attrs) {
        urbanItem.status = 'no-feature';
        urbanItem.message = '此點不在都市計畫範圍內（可能屬非都市土地）。';
      } else {
        urbanItem.status = 'ok';
        urbanItem.value = value;
        var code = pick(attrs, F.code, false);
        urbanItem.code = (code === value) ? null : code;
        urbanItem.extras = (F.extra || []).map(function (pair) {
          var v2 = pick(attrs, pair[1], true);
          return (v2 && v2 !== value) ? [pair[0], v2] : null;
        }).filter(Boolean);
      }
      return done();
    }).catch(function (e) {
      urbanItem.status = 'error';
      urbanItem.message = county + ' 的查詢服務目前無法使用：' + (e.message || e);
      return done();
    });
  }

  g.Serverless = {
    cadastre: cadastre,
    parcels: parcels,
    zoning: zoning,
    counties: function () {
      return {
        cadastre: Object.keys(SERVICES.cadastre || {}),
        urban: Object.keys(SERVICES.urban || {})
      };
    }
  };
})(window);
