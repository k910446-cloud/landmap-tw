/* 地籍圖 App 的 CORS 代理 —— 部署到 Cloudflare Workers（免費方案就夠）。
 *
 * 為什麼需要這個
 * --------------
 * 有些縣市政府的圖資服務回應正常，但不送 Access-Control-Allow-Origin 標頭。
 * 瀏覽器的同源政策因此不准網頁直接讀它的內容 —— 苗栗縣的地號與都市計畫、
 * 新竹縣的部分圖層都卡在這裡。本機版有 Python 後端可以代為轉送，
 * 放到 GitHub Pages 就沒有這個角色了。
 *
 * 這支 Worker 就是補上那個角色：代為向政府服務要資料，加上 CORS 標頭回傳。
 *
 * 安全性
 * ------
 * 這不是通用代理。它只肯轉送：
 *   1. https 的網址（不接受 http，避免被當成內網探測工具）
 *   2. 主機名在 ALLOWED_HOSTS 白名單內的政府網站
 *   3. GET 請求
 * 並且只接受 ALLOWED_ORIGINS 裡的網站來呼叫，別人拿不到你的免費額度。
 *
 * 沒有這些限制的話，任何人都能拿你的 Worker 去打任何網站，
 * 帳單和責任都會算在你頭上。
 */

// 允許轉送的目標主機（比對網域結尾）
const ALLOWED_HOSTS = [
  '.gov.tw',
  '.gov.taipei',
  'nominatim.openstreetmap.org',
  'data.taipei',
];

// 允許呼叫這支 Worker 的網站。
// 要改成你自己的網址：GitHub Pages 是 https://<你的帳號>.github.io
const ALLOWED_ORIGINS = [
  'https://k910446-cloud.github.io',
  'http://localhost:8777',
  'https://localhost:8777',
  'http://127.0.0.1:8777',
  'https://127.0.0.1:8777',
];

const MAX_BYTES = 25 * 1024 * 1024;   // 單次回應上限，避免被拿去傳大檔

function hostAllowed(hostname) {
  const h = hostname.toLowerCase();
  return ALLOWED_HOSTS.some(function (s) {
    return s.startsWith('.') ? h.endsWith(s) : h === s;
  });
}

function corsHeaders(origin) {
  const h = {
    'Access-Control-Allow-Methods': 'GET,OPTIONS',
    'Access-Control-Allow-Headers': 'Range,Content-Type',
    'Access-Control-Expose-Headers': 'Content-Length,Content-Range,Content-Type',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
  if (origin && ALLOWED_ORIGINS.indexOf(origin) >= 0) {
    h['Access-Control-Allow-Origin'] = origin;
  }
  return h;
}

function deny(msg, status, origin) {
  return new Response(msg + '\n', {
    status: status,
    headers: Object.assign({ 'Content-Type': 'text/plain; charset=utf-8' },
                           corsHeaders(origin)),
  });
}

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin');

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }
    if (request.method !== 'GET') {
      return deny('只接受 GET', 405, origin);
    }
    // 有 Origin 就必須在白名單內；沒有 Origin（例如直接用瀏覽器網址列打開）
    // 就讓它過，方便你自己測試，但那種情況本來也拿不到跨網域資料。
    if (origin && ALLOWED_ORIGINS.indexOf(origin) < 0) {
      return deny('這個網站沒有被授權使用這支代理', 403, origin);
    }

    const target = new URL(request.url).searchParams.get('u');
    if (!target) {
      return deny('用法：?u=<政府服務的完整網址>', 400, origin);
    }

    let dest;
    try {
      dest = new URL(target);
    } catch (e) {
      return deny('網址格式不正確', 400, origin);
    }
    if (dest.protocol !== 'https:') {
      return deny('只轉送 https', 400, origin);
    }
    if (!hostAllowed(dest.hostname)) {
      return deny('這個主機不在白名單內：' + dest.hostname, 403, origin);
    }

    let upstream;
    try {
      upstream = await fetch(dest.toString(), {
        method: 'GET',
        headers: {
          'User-Agent': 'landmap-tw/1.0 (+https://github.com/k910446-cloud/landmap-tw)',
          'Accept': request.headers.get('Accept') || '*/*',
        },
        // 政府服務的內容一天內不會變，讓 Cloudflare 邊緣快取擋掉重複請求，
        // 既省免費額度也讓使用者更快
        cf: { cacheTtl: 3600, cacheEverything: true },
      });
    } catch (e) {
      return deny('連不到目標服務：' + (e && e.message ? e.message : e), 502, origin);
    }

    const len = upstream.headers.get('Content-Length');
    if (len && Number(len) > MAX_BYTES) {
      return deny('回應太大，這支代理不轉送', 413, origin);
    }

    const out = new Headers(corsHeaders(origin));
    const ct = upstream.headers.get('Content-Type');
    if (ct) out.set('Content-Type', ct);
    out.set('Cache-Control', 'public, max-age=3600');

    return new Response(upstream.body, { status: upstream.status, headers: out });
  },
};
