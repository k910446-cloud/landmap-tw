/* 非都市土地圖層 —— 靜態版（GitHub Pages）用的查詢。
 *
 * 本機完整版由 Python 在伺服器端解析 shapefile；靜態版沒有後端，
 * 改讀 build_nurban.py 事先轉好的檔：
 *
 *   nurban/<圖層>_<縣市>.idx.json   幾 KB 的索引：每個方格在 .bin 裡的位移
 *   nurban/<圖層>_<縣市>.bin        全縣市的多邊形，依方格排好
 *
 * 點下去時只用 HTTP Range request 抓需要的那一格（通常幾十 KB），
 * 不必把整個縣市載下來 —— 苗栗的編定圖層有 9 MB，整包載會等很久。
 *
 * 判斷用奇偶規則（ray casting）。一筆圖徵的所有環一起算交點次數，
 * 這樣內環（洞）會自動被排除。
 */
(function (g) {
  'use strict';

  var idxCache = {};   // 索引只載一次
  var cellCache = {};  // 已解碼的方格，避免在同一區反覆點時重抓

  function idxUrl(ds, county) {
    return 'nurban/' + ds + '_' + encodeURIComponent(county) + '.idx.json';
  }
  function binUrl(ds, county) {
    return 'nurban/' + ds + '_' + encodeURIComponent(county) + '.bin';
  }

  function loadIndex(ds, county) {
    var key = ds + '/' + county;
    if (idxCache[key]) return idxCache[key];
    idxCache[key] = fetch(idxUrl(ds, county)).then(function (r) {
      if (!r.ok) throw new Error('no-data');
      return r.json();
    }).catch(function (e) {
      delete idxCache[key];          // 失敗不要記住，下次還能重試
      throw e;
    });
    return idxCache[key];
  }

  // ── varint 解碼 ────────────────────────────────────────────
  function Reader(bytes) {
    this.b = bytes;
    this.p = 0;
  }
  Reader.prototype.uvarint = function () {
    var shift = 0, result = 0, b;
    do {
      b = this.b[this.p++];
      result += (b & 0x7f) * Math.pow(2, shift);
      shift += 7;
    } while (b & 0x80);
    return result;
  };
  Reader.prototype.varint = function () {
    var n = this.uvarint();
    return (n % 2) ? -(n + 1) / 2 : n / 2;
  };

  // 一個方格：[{ v: 值編號, rings: [[x,y,x,y,...], ...] }, ...]
  function decodeCell(bytes, meta, cx, cy) {
    var r = new Reader(bytes);
    var n = r.uvarint();
    var ox = Math.round(cx * meta.cell / meta.quant);
    var oy = Math.round(cy * meta.cell / meta.quant);
    var feats = [];
    for (var i = 0; i < n; i++) {
      var vid = r.uvarint();
      var nring = r.uvarint();
      var rings = [];
      for (var k = 0; k < nring; k++) {
        var np = r.uvarint();
        var ring = new Float64Array(np * 2);
        var px = ox, py = oy;
        for (var j = 0; j < np; j++) {
          px += r.varint();
          py += r.varint();
          ring[2 * j] = px * meta.quant;
          ring[2 * j + 1] = py * meta.quant;
        }
        rings.push(ring);
      }
      feats.push({ v: vid, rings: rings });
    }
    return feats;
  }

  // 奇偶規則：一筆圖徵的所有環一起數交點
  function hit(feat, x, y) {
    var inside = false;
    for (var k = 0; k < feat.rings.length; k++) {
      var r = feat.rings[k], n = r.length / 2;
      for (var i = 0, j = n - 1; i < n; j = i++) {
        var xi = r[2 * i], yi = r[2 * i + 1];
        var xj = r[2 * j], yj = r[2 * j + 1];
        if ((yi > y) !== (yj > y)
            && x < (xj - xi) * (y - yi) / (yj - yi) + xi) {
          inside = !inside;
        }
      }
    }
    return inside;
  }

  function ringArea(feat) {
    var r = feat.rings[0], n = r.length / 2, s = 0;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      s += r[2 * j] * r[2 * i + 1] - r[2 * i] * r[2 * j + 1];
    }
    return Math.abs(s) / 2;
  }

  function loadCell(ds, county, meta, cx, cy) {
    var ck = ds + '/' + county + '/' + cx + '_' + cy;
    if (cellCache[ck]) return cellCache[ck];
    var span = meta.cells[cx + '_' + cy];
    if (!span) return Promise.resolve([]);
    var from = span[0], to = span[0] + span[1] - 1;
    cellCache[ck] = fetch(binUrl(ds, county), {
      headers: { Range: 'bytes=' + from + '-' + to }
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.arrayBuffer();
    }).then(function (buf) {
      // 伺服器若不支援 Range 會回整包 200，這裡自己切出需要的段
      var u8 = new Uint8Array(buf);
      if (u8.length > span[1]) u8 = u8.subarray(from, from + span[1]);
      return decodeCell(u8, meta, cx, cy);
    }).catch(function (e) {
      delete cellCache[ck];
      throw e;
    });
    return cellCache[ck];
  }

  function query(ds, county, lat, lon) {
    return loadIndex(ds, county).then(function (meta) {
      var p = TWD.toTM2(lat, lon);
      var cx = Math.floor(p.x / meta.cell);
      var cy = Math.floor(p.y / meta.cell);
      return loadCell(ds, county, meta, cx, cy).then(function (feats) {
        var best = null, bestArea = Infinity;
        for (var i = 0; i < feats.length; i++) {
          if (!hit(feats[i], p.x, p.y)) continue;
          var a = ringArea(feats[i]);
          if (a < bestArea) { best = feats[i]; bestArea = a; }
        }
        if (!best) {
          return {
            key: ds, title: meta.title, status: 'no-feature',
            message: '此點不在非都市土地範圍內（多半代表它屬於都市計畫區或國家公園）'
          };
        }
        return {
          key: ds, title: meta.title, status: 'ok',
          value: meta.values[best.v] || '（屬性無名稱）',
          source: meta.source + '（瀏覽器直接讀取預轉圖資）',
          licence: meta.licence
        };
      });
    }).catch(function (e) {
      if (e && e.message === 'no-data') {
        return {
          key: ds, title: DS_TITLE[ds] || ds, status: 'unavailable',
          message: '線上版還沒有 ' + county + ' 的這份圖資'
        };
      }
      return {
        key: ds, title: DS_TITLE[ds] || ds, status: 'error',
        message: '讀取圖資失敗：' + (e.message || e)
      };
    });
  }

  var DS_TITLE = {
    nurban_zone: '非都市土地使用分區',
    nurban_desig: '非都市土地使用地類別（編定）'
  };

  g.NUrban = {
    query: query,
    datasets: ['nurban_zone', 'nurban_desig'],
    title: function (ds) { return DS_TITLE[ds] || ds; }
  };
})(window);
