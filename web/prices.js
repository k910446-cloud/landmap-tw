/* 實價登錄成交紀錄 —— 依地號查。
 *
 * 資料由 build_prices.py 從內政部實價登錄批次資料整理而成。
 * 那份資料分成買賣主檔與土地明細兩個檔，土地明細帶「段名 ＋ 八碼地號」，
 * 跟這個 App 查地籍用的鍵一模一樣，所以能精準掛到宗地上，
 * 不必走地址地理編碼那種會失準的做法。
 *
 * 收錄十年份之後，一個縣市的資料太大（新北的 JSON 會超過 30 MB），
 * 所以改成「小索引 ＋ 二進位大檔」：索引記錄每個段在 .bin 裡的位移，
 * 點下去只用 HTTP Range 抓需要的那一段（通常幾十 KB）。
 * 跟非都市圖層是同一套做法。
 */
(function (g) {
  'use strict';

  var cache = {};
  var PING = 400 / 121;

  var sectCache = {};

  function load(county) {
    if (cache[county]) return cache[county];
    cache[county] = fetch('prices/' + encodeURIComponent(county) + '.idx.json')
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

  // ── varint 解碼 ────────────────────────────────────────────
  function Reader(bytes) { this.b = bytes; this.p = 0; }
  Reader.prototype.u = function () {
    var shift = 0, out = 0, b;
    do {
      b = this.b[this.p++];
      out += (b & 0x7f) * Math.pow(2, shift);
      shift += 7;
    } while (b & 0x80);
    return out;
  };
  Reader.prototype.s = function () {
    var n = this.u();
    return (n % 2) ? -(n + 1) / 2 : n / 2;
  };

  /* 解出一個段：{ 八碼地號: [ [年月, 總價萬, 單價元每坪, 面積, 類型,
   *                          旗標, 屋齡, 建案, 建物型態, 主要用途], ... ] }
   * 年月與單價在檔案裡是差分過的，這裡還原。
   */
  function decodeSection(bytes) {
    var r = new Reader(bytes);
    var nParcel = r.u();
    var out = {};
    for (var i = 0; i < nParcel; i++) {
      var no = r.u();
      var key = ('00000000' + no).slice(-8);
      var n = r.u();
      var rows = [];
      var ym = 0, unit = 0;
      for (var j = 0; j < n; j++) {
        ym += r.s();
        var total = r.u() / 10;
        unit += r.s();
        var area = r.u() / 10;
        var kind = r.u();
        var flags = r.u();
        var age = r.u() - 1;
        var proj = r.u() - 1;
        var btype = r.u() - 1;
        var use = r.u() - 1;
        rows.push([ym, total, unit, area, kind, flags, age, proj, btype, use]);
      }
      rows.sort(function (a, b) { return b[0] - a[0]; });   // 新到舊
      out[key] = rows;
    }
    return out;
  }

  function loadSection(county, sect) {
    var ck = county + '/' + sect;
    if (sectCache[ck]) return sectCache[ck];
    sectCache[ck] = load(county).then(function (meta) {
      var span = (meta.sections || {})[sect];
      if (!span) return null;
      var from = span[0], to = span[0] + span[1] - 1;
      return fetch('prices/' + encodeURIComponent(county) + '.bin', {
        headers: { Range: 'bytes=' + from + '-' + to }
      }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.arrayBuffer();
      }).then(function (buf) {
        var u8 = new Uint8Array(buf);
        // 伺服器不支援 Range 會回整包 200，自己切出需要的段
        if (u8.length > span[1]) u8 = u8.subarray(from, from + span[1]);
        return decodeSection(u8);
      });
    }).catch(function (e) {
      delete sectCache[ck];
      throw e;
    });
    return sectCache[ck];
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
  // 預售屋賣的是還沒蓋好的房子，價格性質跟成屋不同，另外算
  var PRESALE_KINDS = [5];

  /* 算中位數時先排除備註有特殊情形的成交（親友交易、含增建裝潢…）。
   * 排掉之後樣本不足三筆才放回來，並且回報有沒有含特殊交易 ——
   * 單一地號常常只有兩三筆成交，一筆親友交易就足以主導結果。
   *
   * 「持分移轉」（旗標 16）不算特殊：公寓大樓的土地本來就是每戶持分，
   * 把它當特殊交易排掉，等於把幾乎所有住宅成交都丟了。它只做標示。
   */
  var EXCLUDE_MASK = 1 | 2 | 4 | 8;
  function recentMedian(rows, kinds) {
    var all = rows.filter(function (r) {
      return r[2] > 0 && (!kinds || kinds.indexOf(r[4]) >= 0);
    });
    var clean = all.filter(function (r) { return !(r[5] & EXCLUDE_MASK); });
    var units = (clean.length >= MIN_SAMPLES) ? clean : all;
    var dirty = units.filter(function (r) { return r[5] & EXCLUDE_MASK; }).length;
    if (!units.length) return { median: 0, n: 0, months: 0, flagged: 0 };
    var newest = units.reduce(function (a, r) { return Math.max(a, r[0]); }, 0);
    var cut = shiftYm(newest, -RECENT_MONTHS + 1);
    var recent = units.filter(function (r) { return r[0] >= cut; });
    if (recent.length >= MIN_SAMPLES) {
      return { median: medianOf(recent.map(function (r) { return r[2]; })),
               n: recent.length, months: RECENT_MONTHS, newest: newest,
               flagged: recent.filter(function (r) { return r[5] & EXCLUDE_MASK; }).length,
               excluded: all.length - units.length };
    }
    return { median: medianOf(units.map(function (r) { return r[2]; })),
             n: units.length, months: 0, newest: newest, flagged: dirty,
             excluded: all.length - units.length };
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
        kind: (meta.kinds || {})[String(r[4])] || '其他',
        age: (r[6] != null && r[6] > 0) ? r[6] : null,
        project: (r[7] != null && r[7] >= 0)
          ? (meta.projects || [])[r[7]] : null,
        btype: (r[8] != null && r[8] >= 0) ? (meta.btypes || [])[r[8]] : null,
        use: (r[9] != null && r[9] >= 0) ? (meta.uses || [])[r[9]] : null,
        notes: Object.keys(meta.flags || {})
          .filter(function (bit) { return (r[5] || 0) & Number(bit); })
          .map(function (bit) { return meta.flags[bit]; })
      };
    });
  }

  /* 查一筆地號的成交紀錄，順便給同段的周邊行情。
   *
   * 同段的中位數比平均值實在 —— 一兩筆特別高或特別低的成交
   * （通常是親友間交易或含裝潢）會把平均值拉走。
   */


  /* 逐年的房價中位數 —— 收了十年資料，最有價值的就是看得出走勢。
   * 一樣排除特殊交易，且一年不足三筆就不列（樣本太少的點會誤導）。
   */
  function yearlyTrend(rows) {
    var by = {};
    rows.forEach(function (r) {
      if (r[2] <= 0 || (r[5] & EXCLUDE_MASK) || HOUSE_KINDS.indexOf(r[4]) < 0) return;
      var y = Math.floor(r[0] / 100);
      (by[y] = by[y] || []).push(r[2]);
    });
    return Object.keys(by).map(Number).sort(function (a, b) { return a - b; })
      .filter(function (y) { return by[y].length >= 3; })
      .map(function (y) {
        return { year: y, median: medianOf(by[y]), n: by[y].length };
      });
  }

  // 這一段有哪些建案（只有預售屋的資料帶建案名稱）
  function projectSummary(meta, sec) {
    var names = {};
    Object.keys(sec).forEach(function (no8) {
      sec[no8].forEach(function (r) {
        if (r[7] != null && r[7] >= 0) {
          var nm = (meta.projects || [])[r[7]];
          if (nm) names[nm] = (names[nm] || 0) + 1;
        }
      });
    });
    return Object.keys(names).sort(function (a, b) { return names[b] - names[a]; })
      .map(function (nm) { return { name: nm, count: names[nm] }; });
  }

  function query(county, sect, landNo) {
    if (!county || !sect) {
      return Promise.resolve({ status: 'need-parcel' });
    }
    return Promise.all([load(county), loadSection(county, sect)])
      .then(function (both) {
        var meta = both[0], sec = both[1];
        if (!sec) {
          return { status: 'no-section', county: county, sect: sect,
            seasons: meta.seasons, source: meta.source,
            message: sect + ' 在最近 ' + meta.seasons.length + ' 季沒有成交紀錄' };
        }
        var eight = toEight(landNo);
        var own = decorate(meta, eight ? sec[eight] : null);

        /* 同段周邊：把整段的紀錄攤平。
         *
         * 一筆交易可能橫跨好幾筆地號（例如一棟房子座落在三筆地上），
         * 那筆成交會掛在每一筆地號底下。攤平算整段行情時要去重，
         * 否則跨多筆地號的交易會被重複計入，等於給它較高的權重。
         * 用「年月＋總價＋單價＋面積」當識別，實務上足以區分不同交易。
         */
        var all = [], seen = {};
        Object.keys(sec).forEach(function (k) {
          sec[k].forEach(function (r) {
            var id = r[0] + '/' + r[1] + '/' + r[2] + '/' + r[3];
            if (seen[id]) return;
            seen[id] = 1;
            all.push(r);
          });
        });

        return {
          status: 'ok', county: county, sect: sect,
          seasons: meta.seasons, source: meta.source, licence: meta.licence,
          own: own,
          ownLand: recentMedian((eight && sec[eight]) || [], LAND_KINDS),
          ownHouse: recentMedian((eight && sec[eight]) || [], HOUSE_KINDS),
          sectionCount: all.length,
          sectionParcels: Object.keys(sec).length,
          land: recentMedian(all, LAND_KINDS),
          house: recentMedian(all, HOUSE_KINDS),
          presale: recentMedian(all, PRESALE_KINDS),
          projects: projectSummary(meta, sec),
          trend: yearlyTrend(all),
          recent: decorate(meta, all.slice()
            .sort(function (a, b) { return b[0] - a[0]; }).slice(0, 8))
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
   * 圖層一次要標畫面內幾十筆地號，逐筆去問會發出成百上千次查詢，
   * 所以直接拿整個段的資料（一次 Range 請求）在前端算完再交給圖層。
   */
  function sectionMedians(county, sect, mode) {
    var kinds = (mode === 'land') ? LAND_KINDS : HOUSE_KINDS;
    return loadSection(county, sect).then(function (sec) {
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
