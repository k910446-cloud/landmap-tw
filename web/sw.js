/* Service worker：只快取 app 本身的殼層，讓它能被「加到主畫面」後離線開啟。
 * 圖磚與 API（/proxy）一律走網路 — 那些由 start.py 端快取。
 */
var CACHE = 'landmap-tw-shell-v5';
var SHELL = [
  './',
  'index.html',
  'app.css',
  'app.js',
  'layers.js',
  'services.js',
  'serverless.js',
  'laws.js',
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

  // 殼層：網路優先，失敗才回快取，這樣改程式時不會拿到舊版
  e.respondWith(
    fetch(req).then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req).then(function (hit) {
        return hit || caches.match('index.html');
      });
    })
  );
});
