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


  /* 向縣市的逐筆土地服務取「登記面積」與公告地價。
   *
   * 地籍圖層給的常常是圖形面積 —— 把數化的宗地多邊形算出來的值，
   * 跟地政登記簿上的登記面積本來就會差一點（苗栗民族段 327：
   * 圖形 135.65、登記 134.98）。官方系統顯示的是登記面積，
   * 只給圖形面積的話，使用者拿去對就會覺得我們算錯。
   */
  function fetchDetail(cfg, x, y) {
    var d = cfg.detail;
    if (!d) return Promise.resolve(null);
    var qs = {
      f: 'json',
      geometry: x + ',' + y,
      geometryType: 'esriGeometryPoint',
      sr: String(d.wkid || 102443),
      layers: 'all',
      tolerance: '1',
      returnGeometry: 'false',
      mapExtent: (x - 50) + ',' + (y - 50) + ',' + (x + 50) + ',' + (y + 50),
      imageDisplay: '400,400,96'
    };
    var q = Object.keys(qs).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(qs[k]);
    }).join('&');
    var url = d.identify + '?' + q;
    if (cfg.needsProxy && window.PROXY_URL) {
      var base = window.PROXY_URL.replace(/\/+$/, '');
      url = base + (base.indexOf('?') >= 0 ? '&' : '?') + 'u=' + encodeURIComponent(url);
    }
    return fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      var res = (data.results || [])[0];
      if (!res) return null;
      var a = res.attributes || {};
      function num(keys) {
        var v = pick(a, keys || [], true);
        var f = parseFloat(v);
        return (!isNaN(f) && f > 0) ? f : null;
      }
      return { area: num(d.area), landValue: num(d.landValue), landPrice: num(d.landPrice) };
    }).catch(function () { return null; });   // 取不到就算了，不影響主查詢
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
        source: (cfg.source || '')
          + (cfg.needsProxy ? '（經自備代理）' : '（瀏覽器直連）'),
        sect: pick(attrs, cfg.sect || [], true) || sectHint || null,
        sectCode: pick(attrs, cfg.sectcode || [], true),
        landNo: formatLandNo(cfg, attrs),
        town: pick(attrs, cfg.town || [], true),
        office: pick(attrs, cfg.office || [], true)
      };
      if (rings && rings.length) {
        out.rings = [rings[0].map(function (p) { return [p[1], p[0]]; })];
      }
      function finish(detail) {
        // 面積優先序：登記面積 > 服務給的 > 自己по圖形算，並標明是哪一種
        var a = NaN;
        if (detail) {
          if (detail.area) { a = detail.area; out.areaFrom = 'registered'; }
          if (detail.landValue) out.landValue = detail.landValue;
          if (detail.landPrice) out.landPrice = detail.landPrice;
        }
        if (isNaN(a) || a <= 0) {
          a = parseFloat(pick(attrs, cfg.area || [], true));
          if (!isNaN(a) && a > 0) {
            out.areaFrom = (cfg.areaKind === 'registered') ? 'registered' : 'service';
          }
        }
        if ((isNaN(a) || a <= 0) && rings && rings.length) {
          a = ringAreaM2(rings[0]);
          out.areaFrom = 'geometry';
        }
        if (!isNaN(a) && a > 0) {
          out.areaM2 = Math.round(a * 100) / 100;
          out.areaPing = Math.round(a / PING * 100) / 100;
        }
        return out;
      }
      return fetchDetail(cfg, xy[0], xy[1]).then(finish);
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


  // ── 依段名／段碼 + 地號找宗地 ────────────────────────────
  //
  // 各縣市欄位名稱不同，但存的格式一致：段碼 4 碼、地號 8 碼
  //（母號 4 ＋ 子號 4）。有些縣市另外拆成 mother/child 兩欄，
  // 桃園則只有段碼沒有段名，所以用段名查不到 —— 那種情況直接說明，
  // 不要讓使用者對著空結果猜。

  function pad4(n) {
    n = String(parseInt(n, 10) || 0);
    while (n.length < 4) n = '0' + n;
    return n;
  }

  // 只留中文、英數與連字號 —— 這些值會進到 where 條件，
  // 單引號跳脫之外再擋一層，避免把奇怪的字串送進政府服務
  function safeText(t) {
    return String(t == null ? '' : t)
      .replace(/[^一-龥A-Za-z0-9\-]/g, '')
      .replace(/'/g, "''");
  }

  function firstField(list) {
    return (list && list.length) ? list[0] : null;
  }

  // 「880」「880-1」「880之1」→ { mother: 880, child: 1 }
  function parseLandNo(text) {
    var m = String(text || '').trim().match(/^(\d{1,4})\s*(?:[-－之]\s*(\d{1,4}))?$/);
    if (!m) return null;
    return { mother: m[1], child: m[2] || '0' };
  }

  function parcelWhere(cfg, sect, no) {
    var conds = [];
    var sectTxt = safeText(sect);

    if (/^\d{1,4}$/.test(sectTxt)) {
      var scf = firstField(cfg.sectcode);
      if (!scf) return { error: '這個縣市的圖層沒有段代碼欄位' };
      conds.push(scf + " = '" + pad4(sectTxt) + "'");
    } else {
      var snf = firstField(cfg.sect);
      if (!snf) {
        return { error: '這個縣市的圖層沒有段名欄位，請改用四碼段代碼查詢' };
      }
      conds.push(snf + " = '" + sectTxt + "'");
    }

    var eight = firstField(cfg.landno8);
    var mf = firstField(cfg.mother), cf = firstField(cfg.child);
    var lf = firstField(cfg.landno);
    if (eight) {
      conds.push(eight + " = '" + pad4(no.mother) + pad4(no.child) + "'");
    } else if (mf && cf) {
      conds.push(mf + " = '" + pad4(no.mother) + "'");
      conds.push(cf + " = '" + pad4(no.child) + "'");
    } else if (lf) {
      var human = String(parseInt(no.mother, 10))
        + (parseInt(no.child, 10) ? '-' + parseInt(no.child, 10) : '');
      conds.push(lf + " = '" + human + "'");
    } else {
      return { error: '這個縣市的圖層沒有地號欄位' };
    }
    return { where: conds.join(' AND ') };
  }

  function findParcel(county, sect, landNo) {
    var cfg = (SERVICES.cadastre || {})[county];
    var stop = guard(cfg, county, '地籍服務');
    if (stop) return Promise.resolve(stop);

    var no = parseLandNo(landNo);
    if (!no) {
      return Promise.resolve({ status: 'bad-input',
        message: '地號請填數字，子號用連字號，例如 880 或 880-1' });
    }
    var w = parcelWhere(cfg, sect, no);
    if (w.error) return Promise.resolve({ status: 'unsupported', message: w.error });

    return esriQuery(cfg, {
      f: 'json', where: w.where, outFields: '*',
      returnGeometry: 'true', outSR: '4326'
    }).then(function (d) {
      var feats = d.features || [];
      if (!feats.length) {
        return { status: 'not-found', county: county,
          message: '在 ' + county + ' ' + sect + ' 找不到 ' + landNo + ' 地號' };
      }
      var f = feats[0], attrs = f.attributes || {};
      var rings = (f.geometry || {}).rings || [];
      var out = {
        status: 'ok', county: county,
        sect: pick(attrs, cfg.sect || [], true) || sect,
        sectCode: pick(attrs, cfg.sectcode || [], true),
        landNo: formatLandNo(cfg, attrs),
        town: pick(attrs, cfg.town || [], true),
        matches: feats.length,
        rings: rings.map(function (r) {
          return r.map(function (p) { return [p[1], p[0]]; });
        })
      };
      // 面積來源與點位查詢用同一套規則 —— 兩條路徑給不同的數字才是最糟的
      var cx = 0, cy = 0;
      if (rings.length) {
        rings[0].forEach(function (p2) { cx += p2[0]; cy += p2[1]; });
        cx /= rings[0].length; cy /= rings[0].length;
      }
      var pxy = rings.length ? projectPoint(cfg, cx, cy) : [0, 0];
      return fetchDetail(cfg, pxy[0], pxy[1]).then(function (detail) {
        var a = NaN;
        if (detail) {
          if (detail.area) { a = detail.area; out.areaFrom = 'registered'; }
          if (detail.landValue) out.landValue = detail.landValue;
          if (detail.landPrice) out.landPrice = detail.landPrice;
        }
        if (isNaN(a) || a <= 0) {
          a = parseFloat(pick(attrs, cfg.area || [], true));
          if (!isNaN(a) && a > 0) {
            out.areaFrom = (cfg.areaKind === 'registered') ? 'registered' : 'service';
          }
        }
        if ((isNaN(a) || a <= 0) && rings.length) {
          a = ringAreaM2(rings[0]);
          out.areaFrom = 'geometry';
        }
        if (!isNaN(a) && a > 0) {
          out.areaM2 = Math.round(a * 100) / 100;
          out.areaPing = Math.round(a / PING * 100) / 100;
        }
        return out;
      });
    }).catch(function (e) {
      return { status: 'error', county: county,
        message: county + ' 的地籍服務目前無法使用：' + (e.message || e) };
    });
  }

  // ── 使用分區 ────────────────────────────────────────────
  function zoning(lat, lon, county) {
    var F = SERVICES.urbanFields || { value: [], code: [], extra: [] };
    var layers = [];

    var cfg = (SERVICES.urban || {})[county];
    var urbanItem = {
      key: 'urban_zone', title: '都市計畫使用分區',
      source: '各直轄市／縣市政府 公開圖服務'
        + (((SERVICES.urban || {})[county] || {}).needsProxy ? '（經自備代理）' : '（瀏覽器直連）'),
      sourceUrl: 'https://data.gov.tw/dataset/156197',
      licence: '各該市政府開放資料授權'
    };

    // 非都市分區與編定：讀 build_layers.py 事先轉好的圖資，
    // 由瀏覽器自己做點在多邊形內判斷（見 nurban.js）
    var nurban = NUrban.datasets.map(function (k) {
      return NUrban.query(k, county, lat, lon);
    });

    function done() {
      return Promise.all(nurban).then(function (rows) {
        return { layers: [urbanItem].concat(rows) };
      });
    }

    // 新北與高雄沒有即時服務，政府是發佈檔案 —— 改讀預轉圖資。
    // 其餘縣市走即時服務，資料比較新，預轉的只是某一時點的快照。
    if (!cfg && NUrban.urbanCounties.indexOf(county) >= 0) {
      return NUrban.query('urban_zone', county, lat, lon).then(function (r) {
        return Promise.all(nurban).then(function (rows) {
          return { layers: [r].concat(rows) };
        });
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
    findParcel: findParcel,
    parseLandNo: parseLandNo,
    zoning: zoning,
    counties: function () {
      return {
        cadastre: Object.keys(SERVICES.cadastre || {}),
        urban: Object.keys(SERVICES.urban || {})
      };
    }
  };
})(window);
