/* 地籍圖 / 使用分區查詢 — 前端主程式
 *
 * 資料來源
 *   圖磚  國土測繪中心開放 WMTS  https://wmts.nlsc.gov.tw/wmts
 *   代碼  國土測繪中心開放 API   https://api.nlsc.gov.tw/other/...
 *   地名  OpenStreetMap Nominatim（僅作地名定位）
 * 兩者都經由本機 start.py 的 /proxy 轉送，以取得 CORS 標頭（canvas 取樣需要）與快取。
 */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var el = function (tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  };

  var SAMPLE_ZOOM = 18;     // 取樣用的圖磚層級
  var SAMPLE_BOX = 5;       // 取樣鄰域邊長（取眾數，避開反鋸齒邊緣）
  var STORE = 'landmap-tw.v1';

  // ── 儲存 ────────────────────────────────────────────────
  var store = {
    read: function () {
      try { return JSON.parse(localStorage.getItem(STORE)) || {}; }
      catch (e) { return {}; }
    },
    write: function (o) {
      try { localStorage.setItem(STORE, JSON.stringify(o)); } catch (e) { /* 隱私模式 */ }
    },
    get: function (k, dflt) {
      var v = store.read()[k];
      return v === undefined ? dflt : v;
    },
    set: function (k, v) { var o = store.read(); o[k] = v; store.write(o); }
  };

  var state = {
    latlng: null,
    marker: null,
    bases: {},
    overlays: {},
    activeBase: store.get('base', 'EMAP'),
    marks: store.get('marks', []),
    palette: store.get('palette', {}),   // { layerId: { "r,g,b": "名稱" } }
    sect: { county: null, town: null, sect: null }
  };

  // ── 小工具 ──────────────────────────────────────────────
  var hintTimer;
  function hint(msg, ms) {
    var h = $('#hint');
    h.textContent = msg;
    h.hidden = false;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(function () { h.hidden = true; }, ms || 2600);
  }

  // ── 執行模式 ────────────────────────────────────────────
  //
  // 本機完整版有 Python 後端，查詢走 /api/*，功能最齊。
  // 放到 GitHub Pages 之後沒有後端，就改由瀏覽器直接打各縣市服務
  // （只有會送 CORS 標頭的縣市能用，非都市分區則完全不支援）。
  // 這裡先探一次 /api/data 決定走哪一邊。

  var hasBackend = null;          // null = 還沒判定
  var backendReady = fetch('/api/data', { cache: 'no-store' })
    .then(function (r) { hasBackend = r.ok; })
    .catch(function () { hasBackend = false; })
    .then(function () {
      document.body.classList.toggle('no-backend', !hasBackend);
      renderModeNote();
      return hasBackend;
    });

  function renderModeNote() {
    var box = document.getElementById('mode-note');
    if (!box) return;
    if (hasBackend) {
      box.textContent = '完整版：所有查詢功能可用，含全國 18 縣市的非都市土地使用分區與編定。';
      box.className = 'fineprint';
      return;
    }
    var c = (window.Serverless ? Serverless.counties() : { cadastre: [], urban: [] });
    box.textContent = '線上版（無後端）：地號查詢支援 ' + c.cadastre.join('、')
      + '；都市計畫分區支援 ' + c.urban.join('、')
      + '。非都市土地使用分區與編定需要後端解析圖資，線上版無法提供 —— '
      + '要查那些請下載本機完整版。';
    box.className = 'fineprint warn-note';
  }

  // 沒有後端時，本來走 /proxy 的請求改成直連（那些服務都送 CORS 標頭）
  function proxy(u) { return hasBackend === false ? u : '/proxy?u=' + encodeURIComponent(u); }

  function fetchText(u) {
    return backendReady.then(function () {
      return fetch(proxy(u)).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      });
    });
  }

  function parseXML(t) {
    var d = new DOMParser().parseFromString(t, 'application/xml');
    if (d.getElementsByTagName('parsererror').length) throw new Error('XML 解析失敗');
    return d;
  }

  function tagText(node, name) {
    var e = node.getElementsByTagName(name)[0];
    return e ? e.textContent.trim() : '';
  }

  function copy(text) {
    var done = function () { hint('已複製'); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else { fallback(); }
    function fallback() {
      var ta = el('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); }
      catch (e) { hint('複製失敗，請手動選取'); }
      document.body.removeChild(ta);
    }
  }

  function fillDL(dl, pairs) {
    dl.textContent = '';
    pairs.forEach(function (p) {
      if (p[1] === '' || p[1] == null) return;
      dl.appendChild(el('dt', null, p[0]));
      dl.appendChild(el('dd', null, p[1]));
    });
    if (!dl.children.length) dl.appendChild(el('dd', 'muted', '無資料'));
  }

  // ── 地圖 ────────────────────────────────────────────────
  var map = L.map('map', {
    center: store.get('center', [23.7, 120.96]),
    zoom: store.get('zoom', 8),
    minZoom: 7,
    maxZoom: 20,
    zoomControl: false,
    attributionControl: true
  });
  L.control.zoom({ position: 'topleft' }).addTo(map);
  L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);
  map.attributionControl.setPrefix('');

  // ArcGIS 動態出圖：依每一塊圖磚的範圍向 MapServer 的 export 端點要圖。
  // 縣市的地籍圖多半只有這種發布方式，而它畫出來的圖本身就帶地號註記。
  L.TileLayer.ArcGISExport = L.TileLayer.extend({
    getTileUrl: function (coords) {
      var size = this.getTileSize();
      var nwPt = coords.scaleBy(size);
      var sePt = nwPt.add(size);
      var nw = this._map.unproject(nwPt, coords.z);
      var se = this._map.unproject(sePt, coords.z);
      var a = L.Projection.SphericalMercator.project(nw);
      var b = L.Projection.SphericalMercator.project(se);
      var q = [
        'bbox=' + [a.x, b.y, b.x, a.y].join(','),
        'bboxSR=3857', 'imageSR=3857',
        'size=' + size.x + ',' + size.y,
        'layers=show:' + this.options.layerIds,
        'format=png32', 'transparent=true', 'f=image'
      ].join('&');
      return this.options.base + '?' + q;
    }
  });

  function makeTile(url, opts) {
    // 不要設 crossOrigin：顯示用的圖磚不需要它，而有些縣市的圖磚主機
    // 沒送 Access-Control-Allow-Origin，設了反而整層被瀏覽器擋掉。
    // 顏色取樣走本機 /proxy（那邊會補上 CORS 標頭），跟這裡無關。
    return L.tileLayer(url, Object.assign({
      maxNativeZoom: CATALOG.maxNativeZoom,
      maxZoom: 20,
      attribution: CATALOG.attribution,
      detectRetina: false
    }, opts || {}));
  }

  // 圖層可以自帶出處與最大原生層級（OSM 系列跟國土測繪中心不同）
  function tileOpts(def, extra) {
    var o = Object.assign({}, extra || {});
    if (def.attr) o.attribution = def.attr;
    if (def.maxNativeZoom) o.maxNativeZoom = def.maxNativeZoom;
    return o;
  }

  // 底圖
  CATALOG.bases.forEach(function (b) {
    if (b.url) state.bases[b.id] = makeTile(b.url, tileOpts(b, { zIndex: 1 }));
  });
  function setBase(id) {
    Object.keys(state.bases).forEach(function (k) {
      if (map.hasLayer(state.bases[k])) map.removeLayer(state.bases[k]);
    });
    if (state.bases[id]) state.bases[id].addTo(map);
    state.activeBase = id;
    store.set('base', id);
    $$('#base-list .chip').forEach(function (c) {
      c.classList.toggle('is-on', c.dataset.id === id);
    });
  }

  // 疊圖
  function buildOverlay(o, opts) {
    if (o.exportService) {
      return new L.TileLayer.ArcGISExport('', Object.assign({
        base: o.exportService.base,
        layerIds: o.exportService.layerIds,
        maxZoom: 20,
        minZoom: o.minZoom || 0,
        attribution: o.attr || CATALOG.attribution
      }, opts));
    }
    return makeTile(o.url, tileOpts(o, opts));
  }

  var savedOv = store.get('overlays', null);
  CATALOG.overlays.forEach(function (o, i) {
    var saved = savedOv && savedOv[o.id];
    var on = saved ? saved.on : o.on;
    var op = saved ? saved.opacity : (o.opacity == null ? 1 : o.opacity);
    var layer = buildOverlay(o, { opacity: op, zIndex: 10 + i });
    state.overlays[o.id] = { def: o, layer: layer, on: on, opacity: op };
    if (on) layer.addTo(map);
  });

  function saveOverlays() {
    var out = {};
    Object.keys(state.overlays).forEach(function (k) {
      out[k] = { on: state.overlays[k].on, opacity: state.overlays[k].opacity };
    });
    store.set('overlays', out);
  }

  map.on('moveend', function () {
    store.set('center', [+map.getCenter().lat.toFixed(6), +map.getCenter().lng.toFixed(6)]);
    store.set('zoom', map.getZoom());
  });

  // ── 面板 ────────────────────────────────────────────────
  var panel = $('#panel');
  // persist 只在使用者自己開關時才寫入 — 否則「畫面一開始比較窄」這種
  // 暫時狀態會被記成永久偏好。
  function setPanel(open, persist) {
    panel.classList.toggle('is-closed', !open);
    document.body.classList.toggle('panel-closed', !open);
    $('#btn-panel').classList.toggle('is-on', open);
    if (persist) store.set('panelOpen', open);
    setTimeout(function () { map.invalidateSize({ pan: false }); }, 300);
  }
  $('#btn-panel').addEventListener('click', function () {
    setPanel(panel.classList.contains('is-closed'), true);
  });
  $('#grabber').addEventListener('click', function () { setPanel(true, true); });

  function showTab(name) {
    $$('#tabs .tab').forEach(function (t) { t.classList.toggle('is-on', t.dataset.tab === name); });
    $$('.pane').forEach(function (p) { p.classList.toggle('is-on', p.dataset.pane === name); });
    $('#panes').scrollTop = 0;
    if (name === 'sect') loadCounties();
    if (name === 'marks') { renderMarks(); renderPalette(); }
    if (name === 'about') loadCoverage();
    if (name === 'draw') { draw.mount(); locate.mount(); }
  }
  $$('#tabs .tab').forEach(function (t) {
    t.addEventListener('click', function () { showTab(t.dataset.tab); setPanel(true, true); });
  });

  // ── 圖層 UI ─────────────────────────────────────────────
  function buildLayerUI() {
    var bl = $('#base-list');
    CATALOG.bases.forEach(function (b) {
      var c = el('button', 'chip', b.name);
      c.dataset.id = b.id;
      c.addEventListener('click', function () { setBase(b.id); });
      bl.appendChild(c);
    });

    var host = $('#overlay-groups');
    var groups = [];
    CATALOG.overlays.forEach(function (o) {
      if (groups.indexOf(o.group) < 0) groups.push(o.group);
    });

    groups.forEach(function (gname) {
      var card = el('div', 'card');
      card.appendChild(el('h3', null, gname));
      CATALOG.overlays.filter(function (o) { return o.group === gname; }).forEach(function (o) {
        var st = state.overlays[o.id];
        var row = el('div', 'lyr');
        var head = el('div', 'lyr-head');

        var cb = el('input');
        cb.type = 'checkbox';
        cb.checked = st.on;
        cb.id = 'cb-' + o.id;

        var lab = el('label', 'lyr-name', o.name);
        lab.setAttribute('for', cb.id);

        head.appendChild(cb);
        head.appendChild(lab);
        row.appendChild(head);

        if (o.note) row.appendChild(el('p', 'lyr-note', o.note));

        var opRow = el('div', 'lyr-op');
        var rg = el('input');
        rg.type = 'range'; rg.min = 10; rg.max = 100; rg.step = 5;
        rg.value = Math.round(st.opacity * 100);
        var pct = el('span', null, rg.value + '%');
        opRow.appendChild(rg);
        opRow.appendChild(pct);
        row.appendChild(opRow);

        cb.addEventListener('change', function () {
          st.on = cb.checked;
          if (cb.checked) st.layer.addTo(map); else map.removeLayer(st.layer);
          saveOverlays();
          if (state.latlng) runSamples(state.latlng);
        });
        rg.addEventListener('input', function () {
          st.opacity = rg.value / 100;
          st.layer.setOpacity(st.opacity);
          pct.textContent = rg.value + '%';
        });
        rg.addEventListener('change', saveOverlays);

        card.appendChild(row);
      });
      host.appendChild(card);
    });
  }

  // ── 測繪工具 ────────────────────────────────────────────
  var draw = DrawTool.create({ map: map, store: store, hint: hint });

  $('#draw-project').addEventListener('change', function () { draw.switchProject(this.value); });
  $('#dw-new').addEventListener('click', function () {
    var n = window.prompt('新專案名稱', '新專案');
    if (n != null) draw.newProject(n.trim() || '新專案');
  });
  $('#dw-rename').addEventListener('click', function () {
    var sel = $('#draw-project');
    var n = window.prompt('專案改名', sel.selectedOptions[0] ? sel.selectedOptions[0].text : '');
    if (n != null && n.trim()) draw.renameProject(n.trim());
  });
  $('#dw-del').addEventListener('click', function () {
    if (!window.confirm('刪除目前專案與其中所有物件？')) return;
    if (!draw.deleteProject()) hint('至少要保留一個專案');
  });
  $('#dw-clear').addEventListener('click', function () {
    if (window.confirm('清空目前專案的所有物件？')) draw.clearProject();
  });
  $('#dw-export').addEventListener('click', draw.exportProject);
  $('#dw-geojson').addEventListener('click', draw.exportGeoJSON);
  $('#dw-import').addEventListener('click', function () { $('#file-project').click(); });
  $('#file-project').addEventListener('change', function () {
    var f = this.files[0];
    if (!f) return;
    f.text().then(function (t) { hint('已匯入「' + draw.importProject(t) + '」'); })
      .catch(function (e) { hint('匯入失敗：' + e.message); });
    this.value = '';
  });

  // ── 圖層位置校正 ────────────────────────────────────────
  //
  // 不同來源的圖資套疊常有幾公尺的偏差。這裡用 CSS 位移整個疊圖窗格，
  // 公尺換算成像素要跟著縮放層級重算。

  var offset = store.get('offset', { x: 0, y: 0 });

  function applyOffset() {
    var pane = map.getPane('overlayPane');
    if (!pane) return;
    var px = 0, py = 0;
    if (offset.x || offset.y) {
      var c = map.getCenter();
      // 該緯度下每像素代表幾公尺
      var mpp = 40075016.686 * Math.abs(Math.cos(c.lat * Math.PI / 180)) /
        Math.pow(2, map.getZoom() + 8);
      px = offset.x / mpp;
      py = -offset.y / mpp;          // 螢幕 y 往下為正，北方要反過來
    }
    Object.keys(state.overlays).forEach(function (k) {
      var el2 = state.overlays[k].layer.getContainer && state.overlays[k].layer.getContainer();
      if (el2) el2.style.transform = 'translate(' + px.toFixed(2) + 'px,' + py.toFixed(2) + 'px)';
    });
    Object.keys(customLayers || {}).forEach(function (k) {
      var el2 = customLayers[k].getContainer && customLayers[k].getContainer();
      if (el2) el2.style.transform = 'translate(' + px.toFixed(2) + 'px,' + py.toFixed(2) + 'px)';
    });
    var lbl = $('#off-val');
    if (lbl) lbl.textContent = '東西 ' + offset.x.toFixed(1) + ' m　南北 ' + offset.y.toFixed(1) + ' m';
  }

  function bindOffset(id, axis) {
    var r = $(id);
    r.value = offset[axis];
    r.addEventListener('input', function () {
      offset[axis] = parseFloat(r.value);
      applyOffset();
    });
    r.addEventListener('change', function () { store.set('offset', offset); });
  }
  bindOffset('#off-x', 'x');
  bindOffset('#off-y', 'y');
  $('#off-reset').addEventListener('click', function () {
    offset = { x: 0, y: 0 };
    $('#off-x').value = 0; $('#off-y').value = 0;
    store.set('offset', offset);
    applyOffset();
  });
  map.on('zoomend moveend layeradd', applyOffset);

  // ── 資料涵蓋範圍 ────────────────────────────────────────
  //
  // 各縣市的開放程度差很多，所以直接把「哪些縣市有、下載了沒」攤開給使用者看。

  var coverageLoaded = false;
  function loadCoverage() {
    if (coverageLoaded) return;
    coverageLoaded = true;
    var host = $('#coverage');
    if (hasBackend === false) {
      host.textContent = '';
      var c = Serverless.counties();
      host.appendChild(el('p', 'empty',
        '線上版：地號 ' + c.cadastre.join('、') + '；都市計畫 ' + c.urban.join('、')
        + '。非都市土地使用分區與編定請用本機完整版。'));
      return;
    }
    fetch('/api/data').then(function (r) { return r.json(); }).then(function (d) {
      host.textContent = '';
      (d.datasets || []).forEach(function (ds) {
        var box = el('div', 'cov');
        box.appendChild(el('div', 'smp-lyr', ds.title));
        var line = el('div', 'covline');
        ds.counties.forEach(function (c) {
          var t = el('span', 'covchip' + (c.cached ? ' is-on' : '') + (c.live ? ' is-live' : ''));
          t.textContent = c.county;
          t.title = c.live ? '即時查詢' : (c.cached ? '已下載，離線可用' : '尚未下載（' + c.sizeMB + ' MB）');
          line.appendChild(t);
        });
        if (!ds.counties.length) line.appendChild(el('span', 'empty', '（尚未登錄任何縣市）'));
        box.appendChild(line);
        host.appendChild(box);
      });
    }).catch(function (e) {
      host.textContent = '';
      host.appendChild(el('p', 'empty', '讀取失敗：' + (e.message || e)));
      coverageLoaded = false;
    });
  }

  // ── 自訂圖層 ────────────────────────────────────────────
  //
  // 都市計畫使用分區與宗地地籍圖都不在免申請的公開圖磚裡；取得授權網址後
  // 加在這裡就能疊上去，不用改程式。

  state.custom = store.get('custom', []);
  var customLayers = {};

  function addCustomToMap(c) {
    if (customLayers[c.id]) return;
    var l = makeTile(c.url, { opacity: c.opacity == null ? 0.7 : c.opacity, zIndex: 200 });
    customLayers[c.id] = l;
    if (c.on !== false) l.addTo(map);
  }

  function renderCustom() {
    var host = $('#cl-list');
    host.textContent = '';
    if (!state.custom.length) return;
    state.custom.forEach(function (c, i) {
      var row = el('div', 'lyr');
      var head = el('div', 'lyr-head');
      var cb = el('input');
      cb.type = 'checkbox';
      cb.checked = c.on !== false;
      var lab = el('label', 'lyr-name', c.name);
      var x = el('button', 'x', '✕');
      x.title = '移除';
      head.appendChild(cb); head.appendChild(lab); head.appendChild(x);
      row.appendChild(head);

      var op = el('div', 'lyr-op');
      var rg = el('input');
      rg.type = 'range'; rg.min = 10; rg.max = 100; rg.step = 5;
      rg.value = Math.round((c.opacity == null ? 0.7 : c.opacity) * 100);
      var pct = el('span', null, rg.value + '%');
      op.appendChild(rg); op.appendChild(pct);
      row.appendChild(op);

      cb.addEventListener('change', function () {
        c.on = cb.checked;
        var l = customLayers[c.id];
        if (l) { if (c.on) l.addTo(map); else map.removeLayer(l); }
        store.set('custom', state.custom);
      });
      rg.addEventListener('input', function () {
        c.opacity = rg.value / 100;
        pct.textContent = rg.value + '%';
        if (customLayers[c.id]) customLayers[c.id].setOpacity(c.opacity);
      });
      rg.addEventListener('change', function () { store.set('custom', state.custom); });
      x.addEventListener('click', function () {
        if (customLayers[c.id]) { map.removeLayer(customLayers[c.id]); delete customLayers[c.id]; }
        state.custom.splice(i, 1);
        store.set('custom', state.custom);
        renderCustom();
      });
      host.appendChild(row);
    });
  }

  $('#cl-add').addEventListener('click', function () {
    var name = $('#cl-name').value.trim();
    var url = $('#cl-url').value.trim();
    if (!name || !url) { hint('請填名稱與網址'); return; }
    if (!/\{z\}/.test(url) || !/\{x\}/.test(url) || !/\{y\}/.test(url)) {
      hint('網址需含 {z}、{x}、{y} 三個佔位符'); return;
    }
    var c = { id: 'c' + Date.now(), name: name, url: url, opacity: 0.7, on: true };
    state.custom.push(c);
    store.set('custom', state.custom);
    addCustomToMap(c);
    renderCustom();
    $('#cl-name').value = '';
    $('#cl-url').value = '';
    hint('已加入「' + name + '」');
  });

  // ── 點位查詢 ────────────────────────────────────────────
  var pinIcon = L.divIcon({ className: '', html: '<div class="pin"></div>', iconSize: [0, 0] });

  function setPoint(latlng, opts) {
    opts = opts || {};
    state.latlng = latlng;
    if (state.marker) state.marker.setLatLng(latlng);
    else state.marker = L.marker(latlng, { icon: pinIcon, keyboard: false }).addTo(map);

    $('#query-empty').hidden = true;
    $('#query-body').hidden = false;
    if (!opts.keepTab) { showTab('query'); setPanel(true); }

    renderCoords(latlng);
    lookupAdmin(latlng);
    runSamples(latlng);
  }

  // ── 地號標示：把畫面內每一筆宗地的地號標在圖上 ────────────────
  //
  // 底圖「臺灣通用電子地圖」標的是門牌（100號、112號那種），不是地號。
  // 這裡直接向縣市地籍服務要畫面範圍內的宗地，自己畫框、自己標地號。

  var parcelGroup = L.layerGroup();
  var showLandNo = store.get('showLandNo', false);
  var parcelSeq = 0;
  var PARCEL_MIN_ZOOM = 18;   // 再低會一次撈到上千筆，服務單次上限會截斷

  function setLandNoLayer(on) {
    showLandNo = on;
    store.set('showLandNo', on);
    var b = $('#btn-landno');
    if (b) b.classList.toggle('is-on', on);
    var cb = $('#cb-landno');
    if (cb) cb.checked = on;
    if (on) { parcelGroup.addTo(map); refreshParcels(); }
    else { map.removeLayer(parcelGroup); parcelGroup.clearLayers(); }
    updateLandNoHint();
  }

  function updateLandNoHint() {
    var el2 = $('#landno-note');
    if (!el2) return;
    if (!showLandNo) { el2.textContent = ''; return; }
    if (map.getZoom() < PARCEL_MIN_ZOOM) {
      el2.textContent = '放大到第 ' + PARCEL_MIN_ZOOM + ' 級以上才會標地號（目前第 '
        + map.getZoom() + ' 級）。';
    } else {
      el2.textContent = '';
    }
  }

  function refreshParcels() {
    if (!showLandNo) return;
    updateLandNoHint();
    if (map.getZoom() < PARCEL_MIN_ZOOM) { parcelGroup.clearLayers(); return; }
    var county = state.lastAdmin && state.lastAdmin.cty;
    if (!county) return;

    var b = map.getBounds();
    var seq = ++parcelSeq;
    backendReady.then(function () {
      if (hasBackend) {
        var url = '/api/parcels?county=' + encodeURIComponent(county) + '&bbox='
          + [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
            .map(function (v) { return v.toFixed(6); }).join(',');
        return fetch(url).then(function (r) { return r.json(); });
      }
      return Serverless.parcels(county, b.getWest(), b.getSouth(), b.getEast(), b.getNorth());
    }).then(function (d) {
      if (seq !== parcelSeq || !showLandNo) return;
      parcelGroup.clearLayers();
      if (d.status !== 'ok') {
        var n = $('#landno-note');
        if (n) n.textContent = d.message || '查不到';
        return;
      }
      d.parcels.forEach(function (p) {
        L.polygon(p.ring, {
          color: '#8a5a3b', weight: 1, opacity: 0.9,
          fill: true, fillOpacity: 0.02, interactive: false
        }).addTo(parcelGroup);
        L.marker(L.polygon(p.ring).getBounds().getCenter(), {
          interactive: false,
          icon: L.divIcon({ className: 'lnlabel', html: p.landNo, iconSize: [0, 0] })
        }).addTo(parcelGroup);
      });
      var n2 = $('#landno-note');
      if (n2) n2.textContent = d.exceeded
        ? '本畫面宗地太多，只標出 ' + d.count + ' 筆 —— 再放大一級就會標齊。'
        : '本畫面 ' + d.count + ' 筆，已全部標出。';
    }).catch(function () { /* 移動很快時取消是正常的 */ });
  }

  map.on('moveend zoomend', function () { if (showLandNo) refreshParcels(); });

  // ── 座標查地號 ──────────────────────────────────────────
  //
  // 國土測繪中心的座標查地號需申請介接，但部分縣市把自己的地籍圖
  // 以公開 ArcGIS 服務發布，可以直接查。查得到哪些縣市見「說明」頁。

  var cadSeq = 0;
  var parcelLayer = null;      // 命中的宗地輪廓
  var edgeLayer = L.layerGroup();   // 各邊長度標示
  var showEdges = store.get('showEdges', true);
  var lastRings = null;

  // 兩點在 TWD97 二度分帶上的距離 —— 跟測繪工具同一套算法
  function segLen(a, b) {
    var p = TWD.toTM2(a[0], a[1]), q = TWD.toTM2(b[0], b[1]);
    return Math.hypot(q.x - p.x, q.y - p.y);
  }

  function edgesOf(ring) {
    var out = [];
    for (var i = 0; i < ring.length - 1; i++) {
      var a = ring[i], b = ring[i + 1];
      var d = segLen(a, b);
      if (d < 0.05) continue;                 // 重複點跳過
      out.push({ a: a, b: b, len: d, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] });
    }
    return out;
  }

  /* 同一側的小段自動加總。
   *
   * 地籍圖形常把一條直線邊切成好幾個節點，逐段標出來會看到
   * 「0.18 m、0.36 m」這種沒有意義的碎值。實際要看的是「這一側有多長」，
   * 所以把方向幾乎一致的連續小段併成一條邊。
   *
   * 兩道門檻缺一不可：
   *   單段轉角  相鄰兩段的夾角要小於 TURN_TOL 才算同一側
   *   累計偏轉  整條併起來的邊相對起始方向不能偏超過 RUN_TOL ——
   *             否則一連串 8 度的小轉會被併成一條實際彎了 90 度的「直線」
   */
  var TURN_TOL = 12;   // 度
  var RUN_TOL = 20;    // 度

  function segDir(e) {
    var p = TWD.toTM2(e.a[0], e.a[1]), q = TWD.toTM2(e.b[0], e.b[1]);
    return Math.atan2(q.y - p.y, q.x - p.x) * 180 / Math.PI;
  }

  function angDiff(a, b) {
    var d = Math.abs(a - b) % 360;
    if (d > 180) d = 360 - d;
    return d;
  }

  // 沿著這串小段走到總長一半的位置，標籤放那裡才會在邊的中間
  function chainMid(segs) {
    var total = segs.reduce(function (s2, e) { return s2 + e.len; }, 0);
    var half = total / 2, acc = 0;
    for (var i = 0; i < segs.length; i++) {
      if (acc + segs[i].len >= half) {
        var t = (half - acc) / segs[i].len;
        return [segs[i].a[0] + (segs[i].b[0] - segs[i].a[0]) * t,
                segs[i].a[1] + (segs[i].b[1] - segs[i].a[1]) * t];
      }
      acc += segs[i].len;
    }
    return segs[segs.length - 1].mid;
  }

  function mergeSides(edges) {
    var n = edges.length;
    if (n < 2) return edges.map(function (e) {
      return { len: e.len, mid: e.mid, parts: 1, a: e.a, b: e.b };
    });

    var dirs = edges.map(segDir);

    // 從一個「真的是轉角」的地方開始，否則環的接縫會把一條邊切成兩截
    var start = 0;
    for (var i = 0; i < n; i++) {
      if (angDiff(dirs[i], dirs[(i - 1 + n) % n]) > TURN_TOL) { start = i; break; }
    }

    var sides = [], run = [], runDir = null;
    for (var k = 0; k < n; k++) {
      var idx = (start + k) % n;
      var e = edges[idx], d = dirs[idx];
      if (run.length
          && angDiff(d, dirs[(idx - 1 + n) % n]) <= TURN_TOL
          && angDiff(d, runDir) <= RUN_TOL) {
        run.push(e);
      } else {
        if (run.length) sides.push(run);
        run = [e];
        runDir = d;
      }
    }
    if (run.length) sides.push(run);

    return sides.map(function (segs) {
      return {
        len: segs.reduce(function (s2, e) { return s2 + e.len; }, 0),
        mid: chainMid(segs),
        parts: segs.length,
        a: segs[0].a,
        b: segs[segs.length - 1].b
      };
    });
  }

  var mergeEdges = store.get('mergeEdges', true);

  function sidesOf(ring) {
    var es = edgesOf(ring);
    return mergeEdges ? mergeSides(es)
      : es.map(function (e) {
          return { len: e.len, mid: e.mid, parts: 1, a: e.a, b: e.b };
        });
  }

  function renderEdges() {
    edgeLayer.clearLayers();
    if (!showEdges || !lastRings || !lastRings.length) return;
    sidesOf(lastRings[0]).forEach(function (e) {
      if (e.len < 1.5) return;                // 太短的邊不標，免得糊成一團
      L.marker(e.mid, {
        interactive: false,
        icon: L.divIcon({
          className: 'edgelabel',
          html: e.len.toFixed(2),
          iconSize: [0, 0]
        })
      }).addTo(edgeLayer);
    });
    if (!map.hasLayer(edgeLayer)) edgeLayer.addTo(map);
  }

  function renderEdgeList(host) {
    if (!lastRings || !lastRings.length) return;
    var es = sidesOf(lastRings[0]);
    if (!es.length) return;
    var total = es.reduce(function (s2, e) { return s2 + e.len; }, 0);

    var box = el('div', 'edgebox');
    var head = el('div', 'edgehead');
    var lab = el('label', 'edgetoggle');
    var cb = el('input');
    cb.type = 'checkbox';
    cb.checked = showEdges;
    cb.addEventListener('change', function () {
      showEdges = cb.checked;
      store.set('showEdges', showEdges);
      renderEdges();
    });
    lab.appendChild(cb);
    lab.appendChild(document.createTextNode(' 在圖上標各邊長度'));
    head.appendChild(lab);

    var lab2 = el('label', 'edgetoggle');
    var cb2 = el('input');
    cb2.type = 'checkbox';
    cb2.checked = mergeEdges;
    cb2.addEventListener('change', function () {
      mergeEdges = cb2.checked;
      store.set('mergeEdges', mergeEdges);
      renderEdges();
      var host2 = $('#cadastre');
      var oldBox = host2.querySelector('.edgebox');
      if (oldBox) { oldBox.remove(); renderEdgeList(host2); }
    });
    lab2.appendChild(cb2);
    lab2.appendChild(document.createTextNode(' 同一側自動加總'));
    head.appendChild(lab2);
    head.appendChild(el('span', 'edgetotal', '周長 ' + total.toFixed(2) + ' m'));
    box.appendChild(head);

    var list = el('div', 'edgelist');
    es.forEach(function (e, i) {
      var row = el('span', 'edgeitem');
      row.appendChild(el('b', null, 'L' + (i + 1)));
      row.appendChild(document.createTextNode(' ' + e.len.toFixed(2) + ' m'));
      if (e.parts > 1) row.appendChild(el('i', 'edgeparts', e.parts + ' 段'));
      list.appendChild(row);
    });
    box.appendChild(list);
    box.appendChild(el('p', 'fineprint', '邊長依宗地圖形節點計算（TWD97 二度分帶）。'
      + (mergeEdges ? '「同一側自動加總」會把方向幾乎一致的連續節點併成一條邊，'
          + '括號裡是併了幾段；取消勾選可看原始的每一節點。' : '')
      + '圖形節點與實地界址可能有測量誤差，正式尺寸請以地籍圖謄本或鑑界成果為準。'));
    host.appendChild(box);
  }

  function showParcel(rings) {
    if (parcelLayer) { map.removeLayer(parcelLayer); parcelLayer = null; }
    lastRings = rings || null;
    edgeLayer.clearLayers();
    if (!rings || !rings.length) return;
    parcelLayer = L.polygon(rings, {
      color: '#c2703a', weight: 3, opacity: 1,
      fillColor: '#c2703a', fillOpacity: 0.15, interactive: false
    }).addTo(map);
    renderEdges();
  }

  function runCadastre(ll, county, sectHint) {
    var seq = ++cadSeq;
    showParcel(null);
    var host = $('#cadastre');
    host.textContent = '';
    host.appendChild(el('p', 'empty', '查詢中…'));

    backendReady.then(function () {
      return hasBackend
        ? fetch('/api/cadastre?lat=' + ll.lat.toFixed(7) + '&lon=' + ll.lng.toFixed(7)
            + '&county=' + encodeURIComponent(county || '')
            + '&sect=' + encodeURIComponent(sectHint || '')).then(function (r) { return r.json(); })
        : Serverless.cadastre(ll.lat, ll.lng, county, sectHint);
    })
      .then(function (d) {
        if (seq !== cadSeq) return;
        host.textContent = '';
        if (d.status !== 'ok') {
          host.appendChild(el('p', 'empty', d.message || '查不到'));
          return;
        }
        showParcel(d.rings);
        if (showLandNo) refreshParcels();
        var big = el('div', 'zval');
        big.appendChild(el('b', null, (d.sect || '') + ' ' + (d.landNo || '') + ' 地號'));
        host.appendChild(big);

        var chips = el('div', 'zextra');
        function chip(label, val) {
          if (!val && val !== 0) return;
          var c = el('span', 'zchip');
          c.appendChild(el('b', null, label));
          c.appendChild(document.createTextNode(' ' + val));
          chips.appendChild(c);
        }
        chip('段碼', d.sectCode);
        if (d.areaM2) chip('面積', d.areaM2 + ' m²');
        if (d.areaPing) chip('約', d.areaPing + ' 坪');
        if (d.areaFrom === 'geometry') chip('面積', '由圖形計算');
        if (chips.children.length) host.appendChild(chips);

        var row = el('div', 'row');
        var cp = el('button', 'btn', '複製地號');
        cp.addEventListener('click', function () {
          copy([county, d.town || '', d.sect || '', (d.landNo || '') + '地號'].filter(Boolean).join(''));
        });
        row.appendChild(cp);
        var gm = el('button', 'btn', 'Google 地圖');
        gm.addEventListener('click', function () { openGoogle('map'); });
        row.appendChild(gm);
        var gs = el('button', 'btn', '街景');
        gs.addEventListener('click', function () { openGoogle('sv'); });
        row.appendChild(gs);
        host.appendChild(row);

        renderEdgeList(host);
        if (d.source) host.appendChild(el('div', 'fineprint', d.source));
        if (d.sect) renderPrices(host, county, d.sect, d.landNo);
      })
      .catch(function (e) {
        if (seq !== cadSeq) return;
        host.textContent = '';
        host.appendChild(el('p', 'empty', '查詢失敗：' + (e.message || e)));
      });
  }

  // ── 圖徵查詢：真實分區 / 類別名稱 ───────────────────────────
  //
  // 圖磚只給得出顏色。名稱來自政府資料開放平臺的 SHP 屬性表，
  // 由 start.py 按縣市下載後在本機做點在多邊形內的判斷。

  var zoningSeq = 0;
  function runZoning(ll, county) {
    var seq = ++zoningSeq;
    var host = $('#zoning');
    host.textContent = '';
    host.appendChild(el('p', 'empty', '查詢中…'));

    backendReady.then(function () {
      return hasBackend
        ? fetch('/api/zoning?lat=' + ll.lat.toFixed(7) + '&lon=' + ll.lng.toFixed(7)
            + '&county=' + encodeURIComponent(county || '')).then(function (r) { return r.json(); })
        : Serverless.zoning(ll.lat, ll.lng, county);
    }).then(function (d) {
      if (seq !== zoningSeq) return;
      host.textContent = '';
      // 有答案的排前面；「這個縣市沒有這份資料」之類的收到最後，免得洗版
      var rank = { ok: 0, 'needs-download': 1, 'no-feature': 2, error: 3, unavailable: 4 };
      var layers = (d.layers || []).slice().sort(function (a, b) {
        return (rank[a.status] == null ? 9 : rank[a.status])
             - (rank[b.status] == null ? 9 : rank[b.status]);
      });
      layers.forEach(function (L) { host.appendChild(zoningRow(L, ll, county)); });
      if (!host.children.length) host.appendChild(el('p', 'empty', '沒有可查詢的圖層。'));
    }).catch(function (e) {
      if (seq !== zoningSeq) return;
      host.textContent = '';
      host.appendChild(el('p', 'empty', '查詢失敗：' + (e.message || e)));
    });
  }

  // ── 法規依據 ────────────────────────────────────────────
  //
  // 查到分區之後接著會想知道「能蓋什麼、蓋多大」。條文取自全國法規資料庫，
  // 由 build_laws.py 產生 laws.js。這裡只做對照與呈現，不做法律判斷。

  var MUNICIPALITIES = ['臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市'];
  // 金門、連江屬福建省，「都市計畫法臺灣省施行細則」對它們沒有適用餘地。
  // 它們各自的施行細則我查不到可靠出處，所以只說明不適用，不亂指一部法規。
  var FUJIAN = ['金門縣', '連江縣'];

  // 圖資的分區名不一定跟條文字面一致（例：條文寫「保存區」，圖資標「古蹟保存區」）。
  // 找不到完全相同的名稱時，退而找條文列過、且是它字尾的那個名稱，
  // 但一定要回報是「對應」來的，不能讓使用者誤以為條文就那樣寫。
  function lookupZone(table, name) {
    if (!table || !name) return null;
    if (table[name] != null) return { value: table[name], matched: null };
    var best = null;
    for (var k in table) {
      if (k.length < 2 || k === name) continue;
      if (name.length > k.length && name.slice(-k.length) === k) {
        if (!best || k.length > best.length) best = k;
      }
    }
    return best ? { value: table[best], matched: best } : null;
  }

  function lawBox(title, kind, county) {
    if (!window.LAWS || !title) return null;
    var box = el('div', 'lawbox');
    var items = [];

    function caps(pairs, note) {
      var row = el('div', 'lawcaps');
      pairs.forEach(function (p) { row.appendChild(el('span', 'lawcap', p)); });
      box.appendChild(row);
      if (note) box.appendChild(el('p', 'lawnote', note));
    }

    if (kind === 'nurban_desig') {
      // 使用地類別 —— 非都市土地使用管制規則第 9 條定有上限
      var cap = LAWS.nonUrbanCaps[title];
      if (cap) {
        caps(['法定建蔽率上限 ' + cap.bcr + '%', '法定容積率上限 ' + cap.far + '%'],
          '這是法定上限。條文明定直轄市或縣（市）政府「得視實際需要酌予調降」，'
          + '實際管制值請向當地主管機關確認。');
      } else if (LAWS.nonUrbanDelegated[title]) {
        box.appendChild(el('p', 'lawnote',
          '第 9 條未列此類用地，其建蔽率與容積率由' + LAWS.nonUrbanDelegated[title]
          + '會同建築管理、地政機關另行訂定。'));
      }
      items.push('非都市土地使用管制規則§9', '非都市土地使用管制規則§6');

    } else if (kind === 'nurban_zone') {
      items.push('非都市土地使用管制規則§5', '非都市土地使用管制規則§6');

    } else if (kind === 'urban_zone') {
      // 認不出縣市就不能斷定適用哪一部 —— 臺灣省施行細則不適用於六都，
      // 猜錯會給出完全不對的建蔽率，寧可只列母法。
      if (!county) {
        box.appendChild(el('p', 'lawnote',
          '無法判定這個點屬於哪個縣市，因此不列建蔽率與容積率 ——'
          + '六都各有自己的自治法規，其餘縣市適用都市計畫法臺灣省施行細則，'
          + '兩者數字不同，猜錯會誤導。'));
        items.push('都市計畫法§32', '都市計畫法§39');
      } else if (FUJIAN.indexOf(county) >= 0) {
        box.appendChild(el('p', 'lawnote', county
          + '屬福建省，不適用都市計畫法臺灣省施行細則，'
          + '建蔽率與容積率請向' + county + '政府建設處查詢。'));
        items.push('都市計畫法§32', '都市計畫法§39');
      } else if (MUNICIPALITIES.indexOf(county) < 0) {
        // 六都以外適用都市計畫法臺灣省施行細則，該細則對各分區定有明確數字
        var bcr = lookupZone(LAWS.provinceBcr, title);
        var far = lookupZone(LAWS.provinceFar, title);
        var pub = lookupZone(LAWS.publicFacilityBcr, title);
        var list = [], inexact = null;
        if (bcr) { list.push('建蔽率上限 ' + bcr.value + '%'); inexact = inexact || bcr.matched; }
        else if (pub) { list.push('公共設施用地建蔽率上限 ' + pub.value + '%'); inexact = inexact || pub.matched; }
        if (far) { list.push('容積率上限 ' + far.value + '%'); inexact = inexact || far.matched; }

        if (list.length) {
          var note = '依都市計畫法臺灣省施行細則。條文另定：當地都市計畫書或'
            + '土地使用分區管制規則有較嚴格規定者，從其規定；'
            + '住宅區與商業區的容積率另依居住密度分級（見 §34 表格）。';
          if (inexact) {
            note = '條文列的是「' + inexact + '」，圖資標示為「' + title
              + '」，是依名稱對應過來的，請以都市計畫書的實際規定為準。' + note;
          }
          caps(list, note);
        } else {
          box.appendChild(el('p', 'lawnote',
            '施行細則的建蔽率（§32、§36）與容積率（§34）條文沒有列到「' + title
            + '」。這類分區的管制通常直接訂在該都市計畫的土地使用分區管制要點裡，'
            + '請向當地都市發展局查詢。'));
        }
        items.push('都市計畫法臺灣省施行細則§32', '都市計畫法臺灣省施行細則§34',
          '都市計畫法臺灣省施行細則§36', '都市計畫法臺灣省施行細則§35');
      } else {
        var rules = (LAWS.municipalRules || {})[county] || [];
        box.appendChild(el('p', 'lawnote', county
          + '是直轄市，各分區的允許使用、建蔽率與容積率規定在它自己的地方自治法規，'
          + '不適用臺灣省施行細則，所以這裡不列數字，以免給錯。'));
        if (rules.length) {
          var rl = el('div', 'lawrefs');
          rl.appendChild(el('span', 'lawreflabel', county + '的規定在'));
          rules.forEach(function (r) {
            var a = el('a', 'lawref', r.name);
            a.href = r.url; a.target = '_blank'; a.rel = 'noopener';
            rl.appendChild(a);
          });
          box.appendChild(rl);
        }
        items.push('都市計畫法§32', '都市計畫法§39');
      }
      box.appendChild(el('p', 'lawnote',
        '個別基地另受該都市計畫的「土地使用分區管制要點」拘束，'
        + '那是逐案訂在都市計畫書裡的，法規資料庫查不到。'));
    }

    items.forEach(function (key) {
      var art = LAWS.articles[key];
      if (!art) return;
      var det = el('details', 'lawart');
      var sum = el('summary');
      var law = LAWS.laws[art.law] || {};
      sum.textContent = art.law + ' 第 ' + art.no + ' 條'
        + (law.revision ? '（' + law.revision + '修正）' : '');
      det.appendChild(sum);
      det.appendChild(el('pre', 'lawtext', art.text));
      var a = el('a', 'lawlink', '看全國法規資料庫原文 ↗');
      a.href = art.url; a.target = '_blank'; a.rel = 'noopener';
      det.appendChild(a);
      box.appendChild(det);
    });

    var refs = el('div', 'lawrefs');
    refs.appendChild(el('span', 'lawreflabel', '相關法規'));
    (LAWS.referenceLinks || []).forEach(function (r) {
      var a = el('a', 'lawref', r.name);
      a.href = r.url; a.target = '_blank'; a.rel = 'noopener';
      refs.appendChild(a);
    });
    box.appendChild(refs);

    box.appendChild(el('p', 'lawdisc',
      '條文取自全國法規資料庫，數字由程式從條文本文解析，僅供對照參考，'
      + '不構成法律意見。法規時有修正，個案適用以主管機關認定與最新公告為準。'));
    return box;
  }

  function zoningRow(L, ll, county) {
    var row = el('div', 'zrow');
    row.appendChild(el('div', 'smp-lyr', L.title));

    if (L.status === 'ok') {
      var v = el('div', 'zval');
      v.appendChild(el('b', null, L.value || '（屬性無名稱欄位）'));
      if (L.code) v.appendChild(el('span', 'zcode', L.code));
      row.appendChild(v);
      // 建蔽率／容積率／所屬都市計畫 —— 有的縣市圖資才有
      if (L.extras && L.extras.length) {
        var ex = el('div', 'zextra');
        L.extras.forEach(function (p) {
          var chip = el('span', 'zchip');
          chip.appendChild(el('b', null, p[0]));
          chip.appendChild(document.createTextNode(' ' + p[1]));
          ex.appendChild(chip);
        });
        row.appendChild(ex);
      }
      var src = el('div', 'fineprint', L.source);
      src.style.marginTop = '2px';
      row.appendChild(src);
      var lb = lawBox(L.value, L.key, county);
      if (lb) row.appendChild(lb);

    } else if (L.status === 'needs-download') {
      row.appendChild(el('div', 'zmsg',
        '需要 ' + L.county + ' 的圖資（' + L.sizeMB + ' MB，政府開放資料，只需下載一次）'));
      var btn = el('button', 'btn primary', '下載 ' + L.county + ' 圖資');
      btn.addEventListener('click', function () {
        btn.disabled = true;
        btn.textContent = '下載中…';
        fetch('/api/data/fetch?key=' + encodeURIComponent(L.key)
          + '&county=' + encodeURIComponent(L.county))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.ok) { hint('已下載 ' + L.county); runZoning(ll, county); }
            else { btn.disabled = false; btn.textContent = '重試下載'; hint('下載失敗'); }
          })
          .catch(function () { btn.disabled = false; btn.textContent = '重試下載'; });
      });
      row.appendChild(btn);

    } else if (L.status === 'unavailable') {
      // 該縣市根本沒有這份資料 —— 一行帶過就好
      row.className = 'zrow zthin';
      row.textContent = '';
      row.appendChild(el('span', 'smp-lyr', L.title + '：'));
      row.appendChild(el('span', 'smp-lyr', L.message || '無資料'));

    } else {
      row.appendChild(el('div', 'zmsg', L.message || '無資料'));
    }
    return row;
  }

  // 繪製模式下，點地圖是在放頂點，不該同時觸發點位查詢、也不該把面板切走
  map.on('click', function (e) {
    if (draw && draw.isDrawing()) return;
    setPoint(e.latlng);
  });

  function renderCoords(ll) {
    var tm97 = TWD.toTM2(ll.lat, ll.lng);
    var tm67 = TWD.tm97to67(tm97.x, tm97.y);
    fillDL($('#coord-info'), [
      ['WGS84', ll.lat.toFixed(6) + ', ' + ll.lng.toFixed(6)],
      ['度分秒', TWD.toDMS(ll.lat, 'N', 'S') + '  ' + TWD.toDMS(ll.lng, 'E', 'W')],
      ['TWD97 TM2', 'X ' + tm97.x.toFixed(2) + '   Y ' + tm97.y.toFixed(2)],
      ['TWD67 TM2', 'X ' + tm67.x.toFixed(2) + '   Y ' + tm67.y.toFixed(2)],
      ['中央經線', tm97.lon0 + '°']
    ]);
  }

  var adminSeq = 0;
  function lookupAdmin(ll) {
    var seq = ++adminSeq;
    var dl = $('#admin-info');
    fillDL(dl, [['狀態', '查詢中…']]);
    var u = 'https://api.nlsc.gov.tw/other/TownVillagePointQuery/'
      + ll.lng.toFixed(6) + '/' + ll.lat.toFixed(6) + '/4326';

    fetchText(u).then(function (t) {
      if (seq !== adminSeq) return;
      var d = parseXML(t);
      var root = d.documentElement;
      var cty = tagText(root, 'ctyName'), town = tagText(root, 'townName');
      var sect = tagText(root, 'sectName'), sectC = tagText(root, 'sectCode');
      var office = tagText(root, 'officeName'), officeC = tagText(root, 'officeCode');
      var vil = tagText(root, 'villageName');

      if (!cty && !sect) { fillDL(dl, [['結果', '此點無資料（可能在海上或界外）']]); return; }

      fillDL(dl, [
        ['縣市', cty + (tagText(root, 'ctyCode') ? '（' + tagText(root, 'ctyCode') + '）' : '')],
        ['鄉鎮市區', town + (tagText(root, 'townCode') ? '（' + tagText(root, 'townCode') + '）' : '')],
        ['村里', vil],
        ['地政事務所', office + (officeC ? '（' + officeC + '）' : '')],
        ['地段', sect + (sectC ? '（' + sectC + '）' : '')]
      ]);
      state.lastAdmin = { cty: cty, town: town, sect: sect, sectC: sectC, office: office, officeC: officeC };
      // 有了縣市才知道要用哪一份開放資料
      runZoning(ll, cty);
      runCadastre(ll, cty, sect);
    }).catch(function (e) {
      if (seq !== adminSeq) return;
      fillDL(dl, [['查詢失敗', String(e.message || e)]]);
      $('#zoning').textContent = '';
      $('#zoning').appendChild(el('p', 'empty', '無法判定所在縣市，跳過圖徵查詢。'));
    });
  }

  // ── 圖磚顏色取樣 ────────────────────────────────────────
  function lngLatToTilePixel(lat, lng, z) {
    var n = Math.pow(2, z);
    var fx = (lng + 180) / 360 * n;
    var s = Math.sin(lat * Math.PI / 180);
    var fy = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n;
    return {
      x: Math.floor(fx), y: Math.floor(fy),
      px: Math.floor((fx - Math.floor(fx)) * 256),
      py: Math.floor((fy - Math.floor(fy)) * 256)
    };
  }

  var imgCache = {};
  function loadTile(url) {
    if (imgCache[url]) return imgCache[url];
    var p = new Promise(function (res, rej) {
      var im = new Image();
      im.crossOrigin = 'anonymous';
      im.onload = function () { res(im); };
      im.onerror = function () { rej(new Error('圖磚載入失敗')); };
      im.src = proxy(url);
    });
    imgCache[url] = p;
    return p;
  }

  // 取鄰域眾數色，避開邊界反鋸齒
  function modalColor(data, px, py) {
    var counts = {}, best = null, bestN = 0;
    var h = (SAMPLE_BOX - 1) / 2;
    for (var dy = -h; dy <= h; dy++) {
      for (var dx = -h; dx <= h; dx++) {
        var x = px + dx, y = py + dy;
        if (x < 0 || y < 0 || x > 255 || y > 255) continue;
        var i = (y * 256 + x) * 4;
        var a = data[i + 3];
        var key = a < 24 ? 'none' : data[i] + ',' + data[i + 1] + ',' + data[i + 2];
        counts[key] = (counts[key] || 0) + 1;
        if (counts[key] > bestN) { bestN = counts[key]; best = key; }
      }
    }
    return best;
  }

  var sampleSeq = 0;
  function runSamples(ll) {
    var seq = ++sampleSeq;
    var host = $('#samples');
    host.textContent = '';

    var targets = CATALOG.overlays.filter(function (o) {
      return o.sample && state.overlays[o.id].on;
    });

    if (!targets.length) {
      host.appendChild(el('p', 'empty',
        '目前沒有開啟可取樣的圖層。到「圖層」頁打開「非都市土地使用分區圖」或「使用地類別圖」。'));
      return;
    }

    var tp = lngLatToTilePixel(ll.lat, ll.lng, SAMPLE_ZOOM);
    var cv = $('#sampler');
    var ctx = cv.getContext('2d', { willReadFrequently: true });

    targets.forEach(function (o) {
      var row = el('div', 'smp');
      var sw = el('div', 'sw');
      var swi = el('i');
      sw.appendChild(swi);
      var txt = el('div', 'smp-txt');
      txt.appendChild(el('div', 'smp-lyr', o.name));
      var val = el('div', 'smp-val', '取樣中…');
      txt.appendChild(val);
      row.appendChild(sw);
      row.appendChild(txt);
      host.appendChild(row);

      var url = o.url
        .replace('{z}', SAMPLE_ZOOM).replace('{y}', tp.y).replace('{x}', tp.x);

      loadTile(url).then(function (im) {
        if (seq !== sampleSeq) return;
        ctx.clearRect(0, 0, 256, 256);
        ctx.drawImage(im, 0, 0, 256, 256);
        var d = ctx.getImageData(0, 0, 256, 256).data;
        var key = modalColor(d, tp.px, tp.py);

        if (key === 'none' || key == null) {
          swi.style.background = 'transparent';
          val.textContent = '此點無資料';
          val.classList.add('muted');
          return;
        }
        swi.style.background = 'rgb(' + key + ')';
        var named = (state.palette[o.id] || {})[key];
        val.textContent = '';
        if (named) {
          var b = el('b', null, named);
          val.appendChild(b);
          val.appendChild(document.createTextNode('  '));
        }
        var code = el('span', 'muted', 'rgb(' + key + ')');
        val.appendChild(code);
        var btn = el('button', 'btn', named ? '改名' : '命名');
        btn.style.cssText = 'padding:3px 9px;font-size:12px;margin-left:8px';
        btn.addEventListener('click', function () { nameColor(o, key, named); });
        val.appendChild(btn);
      }).catch(function (e) {
        if (seq !== sampleSeq) return;
        val.textContent = '取樣失敗：' + (e.message || e);
        val.classList.add('muted');
      });
    });
  }

  function nameColor(o, key, current) {
    var pool = o.id === 'nURBAN2' ? CATALOG.landuseNames
      : o.id === 'nURBAN1' ? CATALOG.zoneNames : [];
    var tip = '為 ' + o.name + ' 的顏色 rgb(' + key + ') 命名。';
    if (pool.length) tip += '\n\n常見名目：\n' + pool.join('、');
    var v = window.prompt(tip, current || '');
    if (v == null) return;
    v = v.trim();
    if (!state.palette[o.id]) state.palette[o.id] = {};
    if (v) state.palette[o.id][key] = v;
    else delete state.palette[o.id][key];
    store.set('palette', state.palette);
    if (state.latlng) runSamples(state.latlng);
    renderPalette();
  }

  // ── 收藏 ────────────────────────────────────────────────
  function renderMarks() {
    var host = $('#mark-list');
    host.textContent = '';
    if (!state.marks.length) {
      host.appendChild(el('p', 'empty', '還沒有收藏。在「點位」頁按「加入收藏」。'));
      return;
    }
    state.marks.forEach(function (m, i) {
      var row = el('div', 'mark');
      var body = el('div', 'mark-b');
      body.appendChild(el('div', 'mark-t', m.title || '未命名'));
      body.appendChild(el('div', 'mark-s', m.lat.toFixed(6) + ', ' + m.lng.toFixed(6)));
      body.addEventListener('click', function () {
        map.setView([m.lat, m.lng], Math.max(map.getZoom(), 17));
        setPoint(L.latLng(m.lat, m.lng));
      });
      var g = el('button', 'x', '↗');
      g.title = '在 Google 地圖開啟';
      g.addEventListener('click', function () {
        window.open(gmapUrl('map', L.latLng(m.lat, m.lng)), '_blank', 'noopener');
      });
      var x = el('button', 'x', '✕');
      x.title = '刪除';
      x.addEventListener('click', function () {
        state.marks.splice(i, 1);
        store.set('marks', state.marks);
        renderMarks();
      });
      row.appendChild(body);
      row.appendChild(g);
      row.appendChild(x);
      host.appendChild(row);
    });
  }

  function renderPalette() {
    var host = $('#palette-list');
    host.textContent = '';
    var any = false;
    Object.keys(state.palette).forEach(function (lid) {
      var entries = Object.keys(state.palette[lid]);
      if (!entries.length) return;
      any = true;
      var def = CATALOG.overlays.filter(function (o) { return o.id === lid; })[0];
      host.appendChild(el('div', 'smp-lyr', def ? def.name : lid));
      entries.forEach(function (key) {
        var row = el('div', 'smp');
        var sw = el('div', 'sw');
        var i = el('i');
        i.style.background = 'rgb(' + key + ')';
        sw.appendChild(i);
        var t = el('div', 'smp-txt');
        t.appendChild(el('div', 'smp-val', state.palette[lid][key]));
        t.appendChild(el('div', 'smp-lyr', 'rgb(' + key + ')'));
        var x = el('button', 'x', '✕');
        x.addEventListener('click', function () {
          delete state.palette[lid][key];
          store.set('palette', state.palette);
          renderPalette();
          if (state.latlng) runSamples(state.latlng);
        });
        row.appendChild(sw); row.appendChild(t); row.appendChild(x);
        host.appendChild(row);
      });
    });
    if (!any) host.appendChild(el('p', 'empty', '尚未建立任何對照。'));
  }

  // ── 地段瀏覽 ────────────────────────────────────────────
  var countiesLoaded = false;
  function loadCounties() {
    if (countiesLoaded) return;
    countiesLoaded = true;
    var sel = $('#sel-county');
    fetchText('https://api.nlsc.gov.tw/other/ListCounty').then(function (t) {
      var items = parseXML(t).getElementsByTagName('countyItem');
      sel.textContent = '';
      sel.appendChild(new Option('請選擇', ''));
      Array.prototype.forEach.call(items, function (it) {
        sel.appendChild(new Option(tagText(it, 'countyname'), tagText(it, 'countycode')));
      });
    }).catch(function (e) {
      sel.textContent = '';
      sel.appendChild(new Option('載入失敗：' + e.message, ''));
      countiesLoaded = false;
    });
  }

  $('#sel-county').addEventListener('change', function () {
    var c = this.value;
    var town = $('#sel-town'), sect = $('#sel-sect');
    town.textContent = ''; sect.textContent = '';
    sect.disabled = true;
    sect.appendChild(new Option('請先選鄉鎮市區', ''));
    updateSectInfo(null);
    if (!c) {
      town.disabled = true;
      town.appendChild(new Option('請先選縣市', ''));
      return;
    }
    town.disabled = true;
    town.appendChild(new Option('載入中…', ''));
    fetchText('https://api.nlsc.gov.tw/other/ListTown/' + encodeURIComponent(c)).then(function (t) {
      var items = parseXML(t).getElementsByTagName('townItem');
      town.textContent = '';
      town.appendChild(new Option('請選擇', ''));
      Array.prototype.forEach.call(items, function (it) {
        town.appendChild(new Option(tagText(it, 'townname'), tagText(it, 'towncode')));
      });
      town.disabled = false;
    }).catch(function (e) {
      town.textContent = '';
      town.appendChild(new Option('載入失敗：' + e.message, ''));
    });
  });

  $('#sel-town').addEventListener('change', function () {
    var c = $('#sel-county').value, t = this.value;
    var sect = $('#sel-sect');
    sect.textContent = '';
    updateSectInfo(null);
    if (!t) {
      sect.disabled = true;
      sect.appendChild(new Option('請先選鄉鎮市區', ''));
      return;
    }
    sect.disabled = true;
    sect.appendChild(new Option('載入中…', ''));
    fetchText('https://api.nlsc.gov.tw/other/ListLandSection/'
      + encodeURIComponent(c) + '/' + encodeURIComponent(t)).then(function (x) {
      var items = parseXML(x).getElementsByTagName('sectItem');
      sect.textContent = '';
      sect.appendChild(new Option('請選擇（共 ' + items.length + ' 段）', ''));
      Array.prototype.forEach.call(items, function (it) {
        var o = new Option(tagText(it, 'sectstr'), tagText(it, 'sectcode'));
        o.dataset.office = tagText(it, 'office');
        o.dataset.officestr = tagText(it, 'officestr');
        sect.appendChild(o);
      });
      sect.disabled = false;
    }).catch(function (e) {
      sect.textContent = '';
      sect.appendChild(new Option('載入失敗：' + e.message, ''));
    });
  });

  $('#sel-sect').addEventListener('change', function () {
    var o = this.selectedOptions[0];
    if (!this.value) { updateSectInfo(null); return; }
    updateSectInfo({
      countyName: $('#sel-county').selectedOptions[0].text,
      countyCode: $('#sel-county').value,
      townName: $('#sel-town').selectedOptions[0].text,
      townCode: $('#sel-town').value,
      sectName: o.text,
      sectCode: this.value,
      office: o.dataset.office,
      officeStr: o.dataset.officestr
    });
  });

  function updateSectInfo(s) {
    state.sect.sel = s;
    var dl = $('#sect-info');
    $('#btn-sect-copy').disabled = !s;
    $('#btn-sect-official').disabled = !s;
    var lin = $('#in-landno'), lbtn = $('#btn-landno-go');
    if (lin) lin.disabled = !s;
    if (lbtn) lbtn.disabled = !s;
    if (!s) { lin.value = ''; $('#landno-msg').textContent = ''; }
    if (!s) { dl.textContent = ''; return; }
    fillDL(dl, [
      ['縣市', s.countyName + '（' + s.countyCode + '）'],
      ['鄉鎮市區', s.townName + '（' + s.townCode + '）'],
      ['地政事務所', s.officeStr + '（' + s.office + '）'],
      ['段小段', s.sectName],
      ['段代碼', s.sectCode],
      ['事務所+段碼', s.office + s.sectCode]
    ]);
    // 開啟段籍圖，方便對照
    var ls = state.overlays.LANDSECT;
    if (ls && !ls.on) {
      ls.on = true; ls.layer.addTo(map);
      var cb = $('#cb-LANDSECT'); if (cb) cb.checked = true;
      saveOverlays();
    }
  }

  $('#btn-sect-copy').addEventListener('click', function () {
    var s = state.sect.sel;
    if (!s) return;
    copy([s.countyName, s.townName, s.sectName,
      '段代碼 ' + s.sectCode, '事務所 ' + s.officeStr + '(' + s.office + ')'].join('　'));
  });

  $('#btn-sect-official').addEventListener('click', function () {
    window.open('https://easymap.land.moi.gov.tw/', '_blank', 'noopener');
    hint('已開啟地籍圖資網路便民服務系統');
  });



  // ── 成交行情 ────────────────────────────────────────────
  //
  // 實價登錄的土地明細帶「段名 ＋ 八碼地號」，跟地籍圖的鍵一致，
  // 所以查到宗地之後可以直接把成交紀錄掛上來（見 prices.js）。

  var priceSeq = 0;

  function renderPrices(host, county, sect, landNo) {
    var seq = ++priceSeq;
    var box = el('div', 'pricebox');
    box.appendChild(el('div', 'pricehead', '成交行情'));
    var body = el('div', 'pricebody');
    body.appendChild(el('p', 'fineprint', '查詢中…'));
    box.appendChild(body);
    host.appendChild(box);

    Prices.query(county, sect, landNo).then(function (d) {
      if (seq !== priceSeq) return;
      body.textContent = '';

      if (d.status !== 'ok') {
        body.appendChild(el('p', 'fineprint', d.message || '沒有可顯示的成交資料'));
        return;
      }

      if (d.own.length) {
        // 大樓的基地一筆地號可能上百筆成交，全部攤開會蓋掉後面的資訊，
        // 先給最近 8 筆，其餘收起來
        var SHOW = 8;
        body.appendChild(el('div', 'pricesub',
          '這筆地號的成交紀錄（' + d.own.length + ' 筆）'));
        var list = el('div', 'pricelist');
        d.own.slice(0, SHOW).forEach(function (t) { list.appendChild(dealRow(t)); });
        body.appendChild(list);
        if (d.own.length > SHOW) {
          var more = el('details', 'pricemore');
          more.appendChild(el('summary', null,
            '看其餘 ' + (d.own.length - SHOW) + ' 筆'));
          var rest = el('div', 'pricelist');
          d.own.slice(SHOW).forEach(function (t) { rest.appendChild(dealRow(t)); });
          more.appendChild(rest);
          body.appendChild(more);
        }
      } else {
        body.appendChild(el('p', 'fineprint',
          '這筆地號在最近 ' + d.seasons.length + ' 季沒有成交紀錄。'));
      }

      if (d.medianPerPing) {
        var sum = el('div', 'pricestat');
        sum.appendChild(el('b', null, d.sect + ' 中位數'));
        sum.appendChild(document.createTextNode(
          ' ' + wan(d.medianPerPing) + ' 萬/坪　（' + d.sectionCount + ' 筆成交、'
          + d.sectionParcels + ' 筆地號）'));
        body.appendChild(sum);
        body.appendChild(el('p', 'fineprint',
          '用中位數而不是平均 —— 一兩筆特別高或特別低的成交（親友間交易、'
          + '含車位或裝潢）會把平均值拉走。'));
      }

      if (d.recent && d.recent.length) {
        var det = el('details', 'pricemore');
        det.appendChild(el('summary', null, '同段最近的成交（' + d.recent.length + ' 筆）'));
        var l2 = el('div', 'pricelist');
        d.recent.forEach(function (t) { l2.appendChild(dealRow(t)); });
        det.appendChild(l2);
        body.appendChild(det);
      }

      body.appendChild(el('p', 'fineprint',
        d.source + '　季別 ' + d.seasons.join('、')
        + '。單價由政府欄位的每平方公尺換算為每坪，未自行推算。'
        + '成交價受屋齡、樓層、車位、裝潢與交易條件影響很大，僅供參考。'));
    }).catch(function (e) {
      if (seq !== priceSeq) return;
      body.textContent = '';
      body.appendChild(el('p', 'fineprint', '讀取成交資料失敗：' + (e.message || e)));
    });
  }

  function wan(perPing) {
    return (perPing / 10000).toFixed(1);
  }

  function dealRow(t) {
    var row = el('div', 'dealrow');
    row.appendChild(el('span', 'dealdate', t.ymText));
    row.appendChild(el('span', 'dealkind', t.kind));
    row.appendChild(el('b', 'dealprice', t.totalWan + ' 萬'));
    if (t.unitPerPing) {
      row.appendChild(el('span', 'dealunit', wan(t.unitPerPing) + ' 萬/坪'));
    }
    if (t.areaPing) {
      row.appendChild(el('span', 'dealarea', t.areaPing + ' 坪'));
    }
    return row;
  }

  // ── 依地號定位 ──────────────────────────────────────────
  //
  // 「段名／段碼 + 地號」→ 直接向縣市地籍服務要那一筆的幾何，
  // 拉到畫面上並框起來。之所以能用段名查，是因為各縣市的地籍圖層
  // 大多帶段名欄位（桃園例外，只有段碼）。

  var foundLayer = L.layerGroup();
  var landnoSeq = 0;

  function clearFoundParcel() {
    foundLayer.clearLayers();
    if (map.hasLayer(foundLayer)) map.removeLayer(foundLayer);
  }

  function findLandNo(county, sect, no, msgEl) {
    var seq = ++landnoSeq;
    function say(t) { if (msgEl) msgEl.textContent = t; }

    if (!county) { say('請先選縣市'); hint('請先選縣市'); return; }
    if (!sect) { say('請先選段，或輸入四碼段代碼'); hint('請先選段'); return; }
    if (!no) { say('請輸入地號'); return; }

    say('查詢中…');
    backendReady.then(function () {
      return hasBackend
        ? fetch('/api/parcel-find?county=' + encodeURIComponent(county)
            + '&sect=' + encodeURIComponent(sect)
            + '&no=' + encodeURIComponent(no)).then(function (r) { return r.json(); })
        : Serverless.findParcel(county, sect, no);
    }).then(function (d) {
      if (seq !== landnoSeq) return;
      if (d.status !== 'ok') {
        say(d.message || '查不到');
        hint(d.message || '查不到這筆地號');
        return;
      }

      clearFoundParcel();
      var bounds = null;
      (d.rings || []).forEach(function (ring) {
        var poly = L.polygon(ring, {
          color: '#e8590c', weight: 3, fillColor: '#ff922b', fillOpacity: 0.25
        }).addTo(foundLayer);
        bounds = bounds ? bounds.extend(poly.getBounds()) : poly.getBounds();
      });
      foundLayer.addTo(map);

      var label = [d.sect || sect, (d.landNo || no) + '地號'].join(' ');
      if (bounds) {
        map.fitBounds(bounds, { maxZoom: 19, padding: [40, 40] });
        // 順手把這一點也當成查詢點，右邊面板就會帶出分區、法條等資訊
        setPoint(bounds.getCenter());
      }
      var extra = d.areaPing ? ('　' + d.areaM2 + ' m²（約 ' + d.areaPing + ' 坪）') : '';
      say('已定位：' + label + extra
        + (d.matches > 1 ? '　（同段同號有 ' + d.matches + ' 筆，顯示第一筆）' : ''));
      hint('已定位到 ' + label);
    }).catch(function (e) {
      if (seq !== landnoSeq) return;
      say('查詢失敗：' + (e.message || e));
    });
  }

  (function wireLandNo() {
    var input = $('#in-landno');
    var btn = $('#btn-landno-go');
    var msg = $('#landno-msg');
    if (!input || !btn) return;

    function go() {
      var sel = state.sect.sel;
      findLandNo(sel && sel.countyName, sel && sel.sectCode,
        input.value.trim(), msg);
    }
    btn.addEventListener('click', go);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.keyCode === 13) { e.preventDefault(); go(); this.blur(); }
    });
  }());

  // ── 搜尋 ────────────────────────────────────────────────
  /* 接受的寫法（順序、標點都不拘）:
   *   25.033, 121.565            WGS84 經緯度
   *   121.565 25.033             同上，經度在前也可以
   *   TWD97 250823 2652539       二度分帶，中央經線 121
   *   119 220000 2600000         澎金馬，中央經線 119
   *   TWD67 250000 2650000       TWD67 二度分帶
   * 「TWD97」「WGS84」裡的數字會先剔除，不會被誤當成座標。
   */

  /* 地號寫法：
   *   中苗段880           用目前選定或上次查到的縣市
   *   苗栗縣中苗段880-1    自己指定縣市
   *   苗栗縣 0212 880      段代碼也可以
   * 縣市判斷順序：字串裡寫的 → 地段瀏覽選的 → 上次點擊的位置。
   */
  function parseLandQuery(q) {
    var t = q.replace(/\s+/g, ' ').trim();
    var county = null;
    var mc = t.match(/(臺北市|台北市|新北市|桃園市|臺中市|台中市|臺南市|台南市|高雄市|基隆市|新竹市|嘉義市|新竹縣|苗栗縣|彰化縣|南投縣|雲林縣|嘉義縣|屏東縣|宜蘭縣|花蓮縣|臺東縣|台東縣|澎湖縣|金門縣|連江縣)/);
    if (mc) { county = mc[1].replace(/^台/, '臺'); t = t.replace(mc[1], ' '); }

    // 段名（可含小段）＋地號
    var m = t.match(/([一-龥]{1,10}段(?:[一-龥]{1,8}小段)?)\s*(\d{1,4}(?:\s*[-－之]\s*\d{1,4})?)\s*(?:地號)?$/);
    if (m) return { county: county, sect: m[1], no: m[2].replace(/\s|之|－/g, function (c) { return c === ' ' ? '' : '-'; }) };

    // 四碼段代碼＋地號
    var m2 = t.match(/(?:^|\s)(\d{4})\s+(\d{1,4}(?:\s*[-－之]\s*\d{1,4})?)\s*(?:地號)?$/);
    if (m2 && county) return { county: county, sect: m2[1], no: m2[2].replace(/\s|之|－/g, function (c) { return c === ' ' ? '' : '-'; }) };

    return null;
  }

  function parseCoords(q) {
    var toks = q.match(/-?\d+(\.\d+)?/g);
    if (!toks || toks.length < 2) return null;

    var is67 = /twd\s*-?67/i.test(q);
    // 中央經線提示：把 5 位以上的數字（座標值本身）挖掉後，還看得到獨立的 119 才算
    var lon0 = /(^|\D)119(\D|$)/.test(q.replace(/\d{5,}/g, ' ')) ? 119 : 121;

    var big = [], vals = toks.map(parseFloat);
    vals.forEach(function (v) { if (Math.abs(v) >= 10000) big.push(v); });

    // 二度分帶：X 約 150000~350000，Y 約 2400000~2900000
    if (big.length >= 2) {
      var x = big[0], y = big[1];
      if (x > y) { var sw = x; x = y; y = sw; }
      if (x < 100000 || x > 400000 || y < 2300000 || y > 3000000) return null;
      if (is67) { var c = TWD.tm67to97(x, y); x = c.x; y = c.y; }
      var r = TWD.fromTM2(x, y, lon0);
      return L.latLng(r.lat, r.lon);
    }

    // 經緯度：台灣約 lat 21.5~26.5、lon 118~123。兩個範圍不重疊，可各自認領。
    var lat = null, lng = null;
    vals.forEach(function (v) {
      if (lat === null && v >= 20 && v <= 27) lat = v;
      else if (lng === null && v >= 117 && v <= 124) lng = v;
    });
    if (lat === null || lng === null) return null;
    return L.latLng(lat, lng);
  }

  function doSearch() {
    var q = $('#search').value.trim();
    if (!q) return;

    var ll = parseCoords(q);
    if (ll) {
      map.setView(ll, Math.max(map.getZoom(), 17));
      setPoint(ll);
      hint('已定位到座標');
      return;
    }

    // 地號優先於地名 —— 「中苗段880」不該被當成地名去搜
    var lq = parseLandQuery(q);
    if (lq) {
      var sel = state.sect.sel;
      var cty = lq.county
        || (sel && sel.countyName)
        || (state.lastAdmin && state.lastAdmin.cty);
      if (!cty) {
        hint('請在地號前面加上縣市，例如「苗栗縣中苗段880」', 6000);
        return;
      }
      findLandNo(cty, lq.sect, lq.no, null);
      return;
    }

    hint('搜尋地名中…', 6000);
    var u = 'https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=tw&q='
      + encodeURIComponent(q);
    fetchText(u).then(function (t) {
      var arr = JSON.parse(t);
      if (!arr.length) { hint('找不到「' + q + '」，可改用座標或地標名稱'); return; }
      var p = L.latLng(parseFloat(arr[0].lat), parseFloat(arr[0].lon));
      map.setView(p, 17);
      setPoint(p);
      hint(arr[0].display_name.split(',').slice(0, 3).join('、'), 4000);
    }).catch(function (e) {
      hint('搜尋失敗：' + (e.message || e));
    });
  }
  $('#btn-search').addEventListener('click', doSearch);
  $('#search').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.keyCode === 13) { e.preventDefault(); doSearch(); this.blur(); }
  });

  // ── 定位 ────────────────────────────────────────────────
  var locate = Locate.create({
    map: map, hint: hint, draw: draw,
    onQuery: function (ll) { setPoint(ll); }
  });
  $('#btn-locate').addEventListener('click', function () { locate.toggle(); });
  $('#btn-landno').addEventListener('click', function () { setLandNoLayer(!showLandNo); });
  $('#cb-landno').addEventListener('change', function () { setLandNoLayer(this.checked); });
  $('#loc-toggle').addEventListener('click', function () { locate.toggle(); });
  $('#loc-follow').addEventListener('click', function () { locate.setFollow(true); });
  $('#loc-query').addEventListener('click', function () { locate.queryHere(); });
  $('#loc-rec').addEventListener('click', function () { locate.toggleRecording(); });

  // ── 點位頁按鈕 ──────────────────────────────────────────
  $('#btn-copy').addEventListener('click', function () {
    if (!state.latlng) return;
    var ll = state.latlng, tm = TWD.toTM2(ll.lat, ll.lng);
    copy('WGS84 ' + ll.lat.toFixed(6) + ', ' + ll.lng.toFixed(6)
      + '　TWD97 TM2 X=' + tm.x.toFixed(2) + ' Y=' + tm.y.toFixed(2));
  });

  $('#btn-mark').addEventListener('click', function () {
    if (!state.latlng) return;
    var a = state.lastAdmin;
    var dflt = a ? (a.cty + a.town + ' ' + a.sect) : '';
    var title = window.prompt('收藏名稱', dflt);
    if (title == null) return;
    state.marks.unshift({
      title: title.trim() || dflt || '未命名',
      lat: state.latlng.lat, lng: state.latlng.lng
    });
    store.set('marks', state.marks);
    hint('已收藏');
    renderMarks();
  });

  // ── 連動 Google 地圖 ────────────────────────────────────
  //
  // 用官方的 Maps URLs 格式，手機上會直接喚起 Google 地圖 App。

  function gmapUrl(kind, ll) {
    var q = ll.lat.toFixed(7) + ',' + ll.lng.toFixed(7);
    if (kind === 'sv') {
      return 'https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=' + q;
    }
    if (kind === 'nav') {
      return 'https://www.google.com/maps/dir/?api=1&destination=' + q;
    }
    if (kind === 'earth') {
      return 'https://earth.google.com/web/@' + ll.lat.toFixed(7) + ','
        + ll.lng.toFixed(7) + ',0a,300d,35y,0h,0t,0r';
    }
    return 'https://www.google.com/maps/search/?api=1&query=' + q;
  }

  function openGoogle(kind) {
    if (!state.latlng) { hint('請先在地圖上點一個位置'); return; }
    window.open(gmapUrl(kind, state.latlng), '_blank', 'noopener');
  }

  $('#btn-gmap').addEventListener('click', function () { openGoogle('map'); });
  $('#btn-gsv').addEventListener('click', function () { openGoogle('sv'); });
  $('#btn-gnav').addEventListener('click', function () { openGoogle('nav'); });
  $('#btn-gearth').addEventListener('click', function () { openGoogle('earth'); });

  // ── 匯出 / 匯入 ─────────────────────────────────────────
  $('#btn-export').addEventListener('click', function () {
    var data = JSON.stringify({ marks: state.marks, palette: state.palette }, null, 2);
    var blob = new Blob([data], { type: 'application/json' });
    var a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'landmap-tw-備份.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); document.body.removeChild(a); }, 1000);
  });

  $('#btn-import').addEventListener('click', function () { $('#file-import').click(); });
  $('#file-import').addEventListener('change', function () {
    var f = this.files[0];
    if (!f) return;
    f.text().then(function (t) {
      var o = JSON.parse(t);
      if (Array.isArray(o.marks)) {
        state.marks = o.marks.concat(state.marks);
        store.set('marks', state.marks);
      }
      if (o.palette && typeof o.palette === 'object') {
        Object.keys(o.palette).forEach(function (lid) {
          state.palette[lid] = Object.assign(state.palette[lid] || {}, o.palette[lid]);
        });
        store.set('palette', state.palette);
      }
      renderMarks(); renderPalette();
      hint('匯入完成');
    }).catch(function (e) { hint('匯入失敗：' + e.message); });
    this.value = '';
  });

  // ── 啟動 ────────────────────────────────────────────────
  buildLayerUI();
  if (showLandNo) setLandNoLayer(true);
  state.custom.forEach(addCustomToMap);
  applyOffset();
  renderCustom();
  setBase(state.activeBase);
  setPanel(store.get('panelOpen', window.innerWidth >= 720));
  renderMarks();
  renderPalette();

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () { /* 非致命 */ });
    });
  }
})();
