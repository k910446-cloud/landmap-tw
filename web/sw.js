/* Service worker：只快取 app 本身的殼層，讓它能被「加到主畫面」後離線開啟。
 * 圖磚與 API（/proxy）一律走網路 — 那些由 start.py 端快取。
 */
var CACHE = 'landmap-tw-shell-v47';
var SHELL = [
  './',
  'index.html',
  'app.css',
  'app.js',
  'layers.js',
  'services.js',
  'proxy.js',
  'serverless.js',
  'nurban.js',
  'prices.js',
  'laws.js',
  'landuse.js',
  'draw.js',
  'locate.js',
  'twd97.js',
  'manifest.webmanifest',
  'icons/icon.svg',
  'vendor/leaflet.js',
  'vendor/leaflet.css',
  'vendor/images/marker-icon.png',
  'vendor/images/marker-icon-2x.png',
  'vendor/images/marker-shadow.png',
  'vendor/images/layers.png',
  'vendor/images/layers-2x.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE)
      .then(function (c) { return c.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys()
      .then(function (ks) {
        return Promise.all(ks.map(function (k) {
          return k === CACHE ? null : caches.delete(k);
        }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;   // 外部資源不攔
  if (url.pathname === '/proxy') return;             // 圖磚 / API 交給網路

  // 非都市圖資是用 Range request 抓片段的，回應是 206。
  // 206 放不進 Cache Storage（cache.put 會直接丟例外），而且存了也沒意義 ——
  // 快取的是「某一段位元組」，下次要的段不一樣就對不上。直接讓它走網路。
  if (req.headers.get('range')) return;

  // 殼層：網路優先，失敗才回快取，這樣改程式時不會拿到舊版。
  //
  // 這裡刻意用 cache: 'no-cache' —— GitHub Pages 會給快取存活時間，
  // 光是重新整理，瀏覽器仍可能拿 HTTP 快取裡的舊檔，更新後要等十分鐘
  // 才會生效。no-cache 是「一定回源核對」而不是「不要快取」，
  // 沒改的檔案回 304，幾乎不花流量，但改過的立刻拿到新版。
  e.respondWith(
    fetch(req, { cache: 'no-cache' }).then(function (res) {
      if (res && res.status === 200) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); }).catch(function () {});
      }
      return res;
    }).catch(function () {
      return caches.match(req).then(function (hit) {
        return hit || caches.match('index.html');
      });
    })
  );
});
