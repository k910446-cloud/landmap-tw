/* 實價登錄成交紀錄 —— 依地號查。
 *
 * 資料由 build_prices.py 從內政部實價登錄批次資料整理而成。
 * 那份資料分成買賣主檔與土地明細兩個檔，土地明細帶「段名 ＋ 八碼地號」，
 * 跟這個 App 查地籍用的鍵一模一樣，所以能精準掛到宗地上，
 * 不必走地址地理編碼那種會失準的做法。
 *
 * 一個縣市一個 JSON，第一次用到才載入，之後留在記憶體重複使用。
 */
(function (g) {
  'use strict';

  var cache = {};
  var PING = 400 / 121;

  function load(county) {
    if (cache[county]) return cache[county];
    cache[county] = fetch('prices/' + encodeURIComponent(county) + '.json')
      .then(function (r) {
        if (!r.ok) throw new Error('no-data');
        return r.json();
      })
      .catch(function (e) {
        delete cache[county];
        throw e;
      });
    return cache[county];
  }

  // 「880」「880-1」→ 八碼 08800000
  function toEight(landNo) {
    var m = String(landNo || '').trim().match(/^(\d{1,4})(?:\s*[-－之]\s*(\d{1,4}))?$/);
    if (!m) return null;
    function pad(n) {
      n = String(parseInt(n, 10) || 0);
      while (n.length < 4) n = '0' + n;
      return n;
    }
    return pad(m[1]) + pad(m[2] || 0);
  }

  function decorate(meta, rows) {
    return (rows || []).map(function (r) {
      var ym = r[0];
      return {
        year: Math.floor(ym / 100),
        month: ym % 100,
        ymText: Math.floor(ym / 100) + '年' + ('0' + (ym % 100)).slice(-2) + '月',
        totalWan: r[1],
        unitPerPing: r[2],
        areaM2: r[3],
        areaPing: r[3] ? Math.round(r[3] / PING * 100) / 100 : 0,
        kind: (meta.kinds || {})[String(r[4])] || '其他'
      };
    });
  }

  /* 查一筆地號的成交紀錄，順便給同段的周邊行情。
   *
   * 同段的中位數比平均值實在 —— 一兩筆特別高或特別低的成交
   * （通常是親友間交易或含裝潢）會把平均值拉走。
   */
  function query(county, sect, landNo) {
    if (!county || !sect) {
      return Promise.resolve({ status: 'need-parcel' });
    }
    return load(county).then(function (meta) {
      var sec = (meta.sections || {})[sect];
      if (!sec) {
        return { status: 'no-section', county: county, sect: sect,
          seasons: meta.seasons, source: meta.source,
          message: sect + ' 在最近 ' + meta.seasons.length + ' 季沒有成交紀錄' };
      }
      var eight = toEight(landNo);
      var own = decorate(meta, eight ? sec[eight] : null);

      // 同段周邊：把整段的紀錄攤平，算中位數
      var all = [];
      Object.keys(sec).forEach(function (k) {
        (sec[k] || []).forEach(function (r) { all.push(r); });
      });
      var units = all.map(function (r) { return r[2]; })
        .filter(function (v) { return v > 0; })
        .sort(function (a, b) { return a - b; });
      var median = units.length
        ? (units.length % 2 ? units[(units.length - 1) / 2]
            : Math.round((units[units.length / 2 - 1] + units[units.length / 2]) / 2))
        : 0;

      return {
        status: 'ok', county: county, sect: sect,
        seasons: meta.seasons, source: meta.source, licence: meta.licence,
        own: own,
        sectionCount: all.length,
        sectionParcels: Object.keys(sec).length,
        medianPerPing: median,
        recent: decorate(meta, all.slice().sort(function (a, b) { return b[0] - a[0]; }).slice(0, 8))
      };
    }).catch(function (e) {
      if (e && e.message === 'no-data') {
        return { status: 'unavailable', county: county,
          message: '還沒有 ' + county + ' 的實價登錄資料' };
      }
      return { status: 'error', message: '讀取成交資料失敗：' + (e.message || e) };
    });
  }

  g.Prices = { query: query, toEight: toEight };
})(window);
