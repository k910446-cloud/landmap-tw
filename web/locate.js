/* 定位系統 — 持續追蹤、精度圈、方位、即時座標、軌跡記錄。
 *
 * 瀏覽器只在 https 或 localhost 底下給 GPS 權限。手機要在區網用定位，
 * 請用 `python start.py --lan --https` 啟動（會自簽憑證，第一次要按「繼續前往」）。
 *
 * 位置資料只留在瀏覽器裡：畫在地圖上、算距離、存成軌跡，不會送到任何伺服器。
 * 唯一的例外是你自己按「查詢此處」時，座標會送到本機 start.py 做圖徵查詢。
 */
(function (g) {
  'use strict';

  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }

  function create(opts) {
    var map = opts.map, hint = opts.hint, onQuery = opts.onQuery, draw = opts.draw;

    var st = {
      watchId: null,
      follow: true,
      last: null,         // 最新的 GeolocationPosition
      dot: null,
      ring: null,
      arrow: null,
      recording: false,
      track: [],
      trackLayer: null
    };

    // ── 地圖上的呈現 ────────────────────────────────────
    function render(pos) {
      var ll = L.latLng(pos.coords.latitude, pos.coords.longitude);
      var acc = pos.coords.accuracy || 0;

      if (!st.dot) {
        st.ring = L.circle(ll, {
          radius: acc, color: '#2f6b52', weight: 1,
          fillColor: '#2f6b52', fillOpacity: 0.12, interactive: false
        }).addTo(map);
        st.dot = L.circleMarker(ll, {
          radius: 7, color: '#fff', weight: 3,
          fillColor: '#2f6b52', fillOpacity: 1, interactive: false
        }).addTo(map);
      } else {
        st.ring.setLatLng(ll).setRadius(acc);
        st.dot.setLatLng(ll);
      }

      // 有方位才畫箭頭（手機移動中才拿得到）
      var h = pos.coords.heading;
      if (h != null && !isNaN(h)) {
        var tip = destination(ll, h, Math.max(acc, 15));
        if (!st.arrow) {
          st.arrow = L.polyline([ll, tip], {
            color: '#2f6b52', weight: 3, opacity: 0.9, interactive: false
          }).addTo(map);
        } else {
          st.arrow.setLatLngs([ll, tip]);
        }
      }

      if (st.follow) map.setView(ll, Math.max(map.getZoom(), 17), { animate: true });

      if (st.recording) {
        var n = st.track.length;
        // 精度太差或原地不動就不記，免得軌跡變成一團毛球
        if (acc <= 50) {
          if (!n) st.track.push([ll.lat, ll.lng]);
          else {
            var prev = L.latLng(st.track[n - 1][0], st.track[n - 1][1]);
            if (prev.distanceTo(ll) >= 3) st.track.push([ll.lat, ll.lng]);
          }
        }
        drawTrack();
      }
      renderHUD();
    }

    function destination(ll, bearingDeg, metres) {
      var R = 6378137, b = bearingDeg * Math.PI / 180;
      var lat = ll.lat * Math.PI / 180, lng = ll.lng * Math.PI / 180;
      var d = metres / R;
      var lat2 = Math.asin(Math.sin(lat) * Math.cos(d) + Math.cos(lat) * Math.sin(d) * Math.cos(b));
      var lng2 = lng + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(lat),
        Math.cos(d) - Math.sin(lat) * Math.sin(lat2));
      return L.latLng(lat2 * 180 / Math.PI, lng2 * 180 / Math.PI);
    }

    function drawTrack() {
      if (st.trackLayer) map.removeLayer(st.trackLayer);
      if (st.track.length < 2) { st.trackLayer = null; return; }
      st.trackLayer = L.polyline(st.track.map(function (p) { return L.latLng(p[0], p[1]); }),
        { color: '#c2703a', weight: 4, opacity: 0.85, interactive: false }).addTo(map);
    }

    // ── 讀數面板 ────────────────────────────────────────
    function renderHUD() {
      var hud = document.getElementById('loc-hud');
      var box = document.getElementById('loc-info');
      var p = st.last;

      if (!p) {
        if (hud) { hud.hidden = true; }
        if (box) box.textContent = '';
        return;
      }
      var c = p.coords;
      var tm = TWD.toTM2(c.latitude, c.longitude);

      if (hud) {
        hud.hidden = false;
        hud.textContent = c.latitude.toFixed(6) + ', ' + c.longitude.toFixed(6)
          + '　±' + Math.round(c.accuracy) + ' m'
          + (st.recording ? '　● 記錄中 ' + fmtTrack() : '');
      }
      if (!box) return;
      box.textContent = '';
      var rows = [
        ['WGS84', c.latitude.toFixed(6) + ', ' + c.longitude.toFixed(6)],
        ['度分秒', TWD.toDMS(c.latitude, 'N', 'S') + '  ' + TWD.toDMS(c.longitude, 'E', 'W')],
        ['TWD97 TM2', 'X ' + tm.x.toFixed(2) + '   Y ' + tm.y.toFixed(2)],
        ['水平精度', '±' + Math.round(c.accuracy) + ' 公尺'],
        ['高程', c.altitude != null ? c.altitude.toFixed(1) + ' 公尺' +
          (c.altitudeAccuracy != null ? '（±' + Math.round(c.altitudeAccuracy) + '）' : '') : ''],
        ['方位', c.heading != null && !isNaN(c.heading) ? Math.round(c.heading) + '°' : ''],
        ['速度', c.speed != null && !isNaN(c.speed) ? (c.speed * 3.6).toFixed(1) + ' km/h' : ''],
        ['更新', new Date(p.timestamp).toLocaleTimeString('zh-TW')]
      ];
      rows.forEach(function (r) {
        if (!r[1]) return;
        box.appendChild(el('dt', null, r[0]));
        box.appendChild(el('dd', null, r[1]));
      });
    }

    function fmtTrack() {
      if (st.track.length < 2) return '0 m';
      return DrawTool.fmtLen(draw.trackLength(st.track));
    }

    // ── 開關 ────────────────────────────────────────────
    function start() {
      if (!navigator.geolocation) { hint('這個瀏覽器不支援定位'); return; }
      if (!window.isSecureContext) {
        hint('要用定位請走 https 或 localhost；區網請用 --https 啟動', 6000);
      }
      st.follow = true;
      st.watchId = navigator.geolocation.watchPosition(function (pos) {
        st.last = pos;
        render(pos);
      }, function (err) {
        stop();
        hint(err.code === 1 ? '定位被拒絕，請在瀏覽器允許位置權限'
          : err.code === 3 ? '定位逾時，請到收得到訊號的地方再試'
            : '定位失敗');
      }, { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 });
      hint('定位中…會持續跟隨你的位置，拖動地圖可解除跟隨', 4000);
      renderButtons();
    }

    function stop() {
      if (st.watchId != null) navigator.geolocation.clearWatch(st.watchId);
      st.watchId = null;
      st.last = null;
      [st.dot, st.ring, st.arrow].forEach(function (l) { if (l) map.removeLayer(l); });
      st.dot = st.ring = st.arrow = null;
      renderHUD();
      renderButtons();
    }

    // 使用者自己拖地圖就解除跟隨，但定位繼續跑
    map.on('dragstart', function () {
      if (st.watchId != null && st.follow) {
        st.follow = false;
        renderButtons();
      }
    });

    function renderButtons() {
      var b = document.getElementById('btn-locate');
      if (b) {
        b.classList.toggle('is-on', st.watchId != null);
        b.title = st.watchId == null ? '開始定位'
          : (st.follow ? '定位中（跟隨）' : '定位中（已解除跟隨）');
      }
      var t = document.getElementById('loc-toggle');
      if (t) t.textContent = st.watchId == null ? '開始定位' : '停止定位';
      var f = document.getElementById('loc-follow');
      if (f) {
        f.disabled = st.watchId == null;
        f.classList.toggle('is-on', st.follow);
        f.textContent = st.follow ? '跟隨中' : '重新跟隨';
      }
      var r = document.getElementById('loc-rec');
      if (r) {
        r.disabled = st.watchId == null;
        r.textContent = st.recording ? '停止記錄並存成軌跡' : '開始記錄軌跡';
        r.classList.toggle('primary', st.recording);
      }
      var q = document.getElementById('loc-query');
      if (q) q.disabled = st.last == null;
    }

    return {
      toggle: function () { if (st.watchId == null) start(); else stop(); },
      isOn: function () { return st.watchId != null; },
      setFollow: function (v) {
        st.follow = v;
        if (v && st.last) map.setView(L.latLng(st.last.coords.latitude, st.last.coords.longitude),
          Math.max(map.getZoom(), 17));
        renderButtons();
      },
      toggleRecording: function () {
        if (st.watchId == null) return;
        if (!st.recording) {
          st.recording = true;
          st.track = [];
          hint('開始記錄軌跡，走動時每 3 公尺記一點');
        } else {
          st.recording = false;
          if (st.track.length >= 2) {
            var len = DrawTool.fmtLen(draw.trackLength(st.track));
            draw.addTrack(st.track, '軌跡 ' + new Date().toLocaleString('zh-TW'));
            hint('軌跡已存進目前專案，長度 ' + len, 4000);
          } else {
            hint('軌跡點太少，沒有存檔');
          }
          st.track = [];
          if (st.trackLayer) { map.removeLayer(st.trackLayer); st.trackLayer = null; }
        }
        renderButtons();
        renderHUD();
      },
      queryHere: function () {
        if (!st.last) { hint('還沒有定位結果'); return; }
        onQuery(L.latLng(st.last.coords.latitude, st.last.coords.longitude));
      },
      current: function () {
        return st.last ? L.latLng(st.last.coords.latitude, st.last.coords.longitude) : null;
      },
      mount: function () { renderButtons(); renderHUD(); }
    };
  }

  g.Locate = { create: create };
})(window);
