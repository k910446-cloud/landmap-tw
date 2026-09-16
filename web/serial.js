/* 對「一次只肯服務一個連線」的主機排隊。
 *
 * 為什麼需要這個
 * --------------
 * 新竹縣智慧圖資雲（imap.hchg.gov.tw）的每一個端點單獨打都正常，
 * 但只要同時有兩個以上的連線，全部會被回 403（一頁 big5 的錯誤頁，
 * 不是 ArcGIS 的錯誤 JSON）。實測：
 *
 *     一次一個，連六次   → 六次都 200
 *     同時十二個         → 十二個全部 403
 *
 * 而 Leaflet 畫一個畫面就會同時要十幾張圖磚，所以新竹縣的地籍圖層
 * 一開就整層空白，連帶把同時發出的地號查詢也一起打掉 ——
 * 畫面上看到的是「新竹縣 的地籍服務目前無法使用：Failed to fetch」。
 * （fetch 讀不到 403 錯誤頁的 CORS 標頭，瀏覽器就報 Failed to fetch。）
 *
 * 這不是我們送錯參數，是對方主機的限制，只能配合：同一個主機的請求
 * 排成一列，一個做完才發下一個；萬一還是被擋，退一下再試。
 *
 * 代價是慢 —— 一個畫面的圖磚要一張一張load。但「慢慢地出現」
 * 比「整層空白」有用得多。
 */
(function (g) {
  'use strict';

  // 需要排隊的主機。判斷時比對整串網址而不是解析出來的 hostname ——
  // 走代理時網址長得像 https://…workers.dev/?u=https%3A%2F%2Fimap.hchg…，
  // 真正被限制的是後面那台，前面那台只是轉送。
  var SERIAL_HOSTS = ['imap.hchg.gov.tw'];

  // 被擋之後等多久再試。三次都失敗就放棄，讓呼叫端顯示錯誤，
  // 不要無限重試把使用者卡在轉圈圈。
  var RETRY_MS = [400, 1200, 2500];

  var chains = {};          // 主機 → 目前排到哪裡的 Promise

  function hostFor(url) {
    var u = String(url);
    for (var i = 0; i < SERIAL_HOSTS.length; i++) {
      if (u.indexOf(SERIAL_HOSTS[i]) >= 0) return SERIAL_HOSTS[i];
    }
    return null;
  }

  function wait(ms) {
    return new Promise(function (ok) { setTimeout(ok, ms); });
  }

  /* 把 job 接到這個主機的隊伍尾端。
   * 前一個成功或失敗都要接下去，否則一次失敗會讓整條隊伍卡死。 */
  function enqueue(host, job) {
    var prev = chains[host] || Promise.resolve();
    var next = prev.then(job, job);
    chains[host] = next.then(noop, noop);
    return next;
  }

  function noop() {}

  function attempt(url, opts, i) {
    return fetch(url, opts).then(function (r) {
      // 403 在這台主機上的意思是「同時連線太多」，不是「沒有權限」，
      // 所以值得重試；其他狀態碼照實回去讓呼叫端處理。
      if (r.status === 403 && i < RETRY_MS.length) {
        return wait(RETRY_MS[i]).then(function () { return attempt(url, opts, i + 1); });
      }
      return r;
    }, function (err) {
      if (i < RETRY_MS.length) {
        return wait(RETRY_MS[i]).then(function () { return attempt(url, opts, i + 1); });
      }
      throw err;
    });
  }

  /* 跟 fetch 一樣用，只是會自動排隊與重試。
   * 不在名單內的主機直接走原生 fetch，不付任何代價。 */
  function serialFetch(url, opts) {
    var host = hostFor(url);
    if (!host) return fetch(url, opts);
    return enqueue(host, function () { return attempt(url, opts, 0); });
  }

  g.SERIAL = { fetch: serialFetch, hostFor: hostFor };
}(window));
