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


  /* 行情要看「近期」而不是「兩年平均」。
   *
   * 房價在這兩年變動很大 —— 苗栗大同段 113 年 3 月約 20 萬/坪，
   * 114 年 7 月已經 34 萬。把兩年混在一起算中位數會低估現況。
   * 所以預設只取最近 12 個月；若樣本少於 3 筆才放寬到全部，
   * 並且一定回報實際用了哪個區間與幾筆，不要讓人以為是同一回事。
   */
  var RECENT_MONTHS = 12;
  var MIN_SAMPLES = 3;

  function shiftYm(ym, months) {
    var y = Math.floor(ym / 100), m = ym % 100;
    var t = y * 12 + (m - 1) + months;
    return Math.floor(t / 12) * 100 + (t % 12) + 1;
  }

  function medianOf(values) {
    if (!values.length) return 0;
    var v = values.slice().sort(function (a, b) { return a - b; });
    return v.length % 2 ? v[(v.length - 1) / 2]
      : Math.round((v[v.length / 2 - 1] + v[v.length / 2]) / 2);
  }

  /* 交易標的：0=土地 1=房地 2=建物 3=車位 4=房地+車位
   *
   * 分成地價與房價不是憑印象，是驗過的：拿 115S2 的苗栗、彰化、桃園、
   * 新北共 2.6 萬筆，算 (總價÷面積) ÷ 政府的「單價元平方公尺」欄位，
   * 看那個欄位到底是用哪個面積當分母 ——
   *
   *   交易標的          筆數     ÷土地面積   ÷建物面積
   *   土地             4853     1.000       —
   *   房地(土地+建物)   8934     3.340       1.000
   *   建物               64       —         1.000
   *   房地+車位        12132     6.331       0.922
   *
   * 土地類的分母是土地面積，房地類是建物面積 —— 兩者基準不同，
   * 混在一起算中位數會得出一個誰都不是的數字，所以分開。
   *
   * 房地+車位那列的 0.922 也說明了為什麼要用政府的單價欄位、
   * 不要自己拿總價除面積：總價含車位，但單價已經把車位價扣掉，
   * 自己算會高估約 8%。
   *
   * 車位（3）兩邊都不列入。建物（2）只有 64 筆、佔房地類 0.3%，
   * 分母同樣是建物面積，併入房價。
   */
  var LAND_KINDS = [0];
  var HOUSE_KINDS = [1, 2, 4];

  function recentMedian(rows, kinds) {
    var units = rows.filter(function (r) {
      return r[2] > 0 && (!kinds || kinds.indexOf(r[4]) >= 0);
    });
    if (!units.length) return { median: 0, n: 0, months: 0 };
    var newest = units.reduce(function (a, r) { return Math.max(a, r[0]); }, 0);
    var cut = shiftYm(newest, -RECENT_MONTHS + 1);
    var recent = units.filter(function (r) { return r[0] >= cut; });
    if (recent.length >= MIN_SAMPLES) {
      return { median: medianOf(recent.map(function (r) { return r[2]; })),
               n: recent.length, months: RECENT_MONTHS, newest: newest };
    }
    return { median: medianOf(units.map(function (r) { return r[2]; })),
             n: units.length, months: 0, newest: newest };
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
      var landStat = recentMedian(all, LAND_KINDS);
      var houseStat = recentMedian(all, HOUSE_KINDS);

      return {
        status: 'ok', county: county, sect: sect,
        seasons: meta.seasons, source: meta.source, licence: meta.licence,
        own: own,
        ownLand: recentMedian((eight && sec[eight]) || [], LAND_KINDS),
        ownHouse: recentMedian((eight && sec[eight]) || [], HOUSE_KINDS),
        sectionCount: all.length,
        sectionParcels: Object.keys(sec).length,
        land: landStat,
        house: houseStat,
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


  /* 給地圖圖層用：一次拿整段的「每筆地號近期單價中位數」。
   *
   * 逐筆去問會發出成百上千次查詢，所以直接把整個縣市的檔載進來
   * （最大的新北 4.9 MB，載一次就留著），在前端算好再交給圖層。
   */
  function sectionMedians(county, sect, mode) {
    var kinds = (mode === 'land') ? LAND_KINDS : HOUSE_KINDS;
    return load(county).then(function (meta) {
      var sec = (meta.sections || {})[sect];
      if (!sec) return null;
      var out = {};
      Object.keys(sec).forEach(function (no8) {
        var st = recentMedian(sec[no8], kinds);
        if (st.median) out[no8] = st.median;
      });
      return out;
    }).catch(function () { return null; });
  }

  g.Prices = { query: query, toEight: toEight, sectionMedians: sectionMedians };
})(window);
