/* 測繪工具 — 點、線、面、圓的繪製與距離／面積量測，以及專案管理。
 *
 * 面積與距離都先把經緯度換成 TWD97 二度分帶再用平面公式算。
 * 台灣範圍內二度分帶的長度變形在萬分之一以內，實務量測夠用，
 * 而且跟地政圖資同一個座標系，數字對得起來。
 *
 * 單位換算採台灣慣用：1 坪 = 3.305785 m²，1 甲 = 9699.17 m²。
 */
(function (g) {
  'use strict';

  var PING = 3.3057851239669422;   // 1 坪 = 400/121 m²
  var JIA = 9699.173553719009;     // 1 甲 = 2934 坪

  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }

  function tm(ll) {
    var p = TWD.toTM2(ll.lat, ll.lng);
    return [p.x, p.y];
  }

  function lengthOf(latlngs) {
    var total = 0;
    for (var i = 1; i < latlngs.length; i++) {
      var a = tm(latlngs[i - 1]), b = tm(latlngs[i]);
      total += Math.hypot(b[0] - a[0], b[1] - a[1]);
    }
    return total;
  }

  function areaOf(latlngs) {
    if (latlngs.length < 3) return 0;
    var pts = latlngs.map(tm);
    var s = 0;
    for (var i = 0, n = pts.length; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(s) / 2;
  }

  function fmtLen(m) {
    if (m < 1000) return m.toFixed(m < 10 ? 2 : 1) + ' 公尺';
    return (m / 1000).toFixed(3) + ' 公里';
  }

  function fmtArea(m2) {
    var out = [];
    out.push(m2 < 10000 ? m2.toFixed(1) + ' m²' : (m2 / 10000).toFixed(4) + ' 公頃');
    out.push((m2 / PING).toFixed(2) + ' 坪');
    if (m2 >= JIA) out.push((m2 / JIA).toFixed(4) + ' 甲');
    return out.join('　');
  }

  // ── 主體 ────────────────────────────────────────────────
  function create(opts) {
    var map = opts.map, store = opts.store, hint = opts.hint;

    var state = {
      features: store.get('features', []),
      projects: store.get('projects', []),
      current: store.get('currentProject', null),
      mode: null,
      draft: [],          // 進行中的頂點
      draftLayer: null,
      ghost: null,        // 滑鼠預覽線
      layers: {}          // id -> leaflet layer
    };

    if (!state.projects.length) {
      state.projects = [{ id: 'p0', name: '預設專案', created: 0 }];
      state.current = 'p0';
      save();
    }
    if (!state.current || !state.projects.some(function (p) { return p.id === state.current; })) {
      state.current = state.projects[0].id;
    }

    function save() {
      store.set('features', state.features);
      store.set('projects', state.projects);
      store.set('currentProject', state.current);
    }

    function defaultStyle() {
      return { color: '#c2703a', weight: 3, opacity: 0.9, fill: 0.2 };
    }

    // ── 繪製到地圖 ──────────────────────────────────────
    function styleOf(f) {
      var s = f.style || defaultStyle();
      return {
        color: s.color, weight: s.weight, opacity: s.opacity,
        fillColor: s.color, fillOpacity: s.fill
      };
    }

    function measureText(f) {
      if (f.type === 'point') return '';
      if (f.type === 'line') return fmtLen(lengthOf(toLatLngs(f)));
      if (f.type === 'circle') {
        var a = Math.PI * f.radius * f.radius;
        return '半徑 ' + fmtLen(f.radius) + '\n' + fmtArea(a);
      }
      var lls = toLatLngs(f);
      return fmtArea(areaOf(lls)) + '\n周長 ' + fmtLen(lengthOf(lls.concat([lls[0]])));
    }

    function toLatLngs(f) {
      return f.pts.map(function (p) { return L.latLng(p[0], p[1]); });
    }

    function buildLayer(f) {
      var st = styleOf(f), lay;
      if (f.type === 'point') {
        lay = L.circleMarker(toLatLngs(f)[0], Object.assign({ radius: 7 }, st));
      } else if (f.type === 'line') {
        lay = L.polyline(toLatLngs(f), st);
      } else if (f.type === 'circle') {
        lay = L.circle(toLatLngs(f)[0], Object.assign({ radius: f.radius }, st));
      } else {
        lay = L.polygon(toLatLngs(f), st);
      }
      var label = (f.name || '') + (measureText(f) ? (f.name ? '\n' : '') + measureText(f) : '');
      if (label) {
        lay.bindTooltip(label, { permanent: false, direction: 'top', className: 'meas-tip' });
      }
      lay.on('click', function (e) {
        // 繪製中不要攔截 —— 讓這一下落在既有物件上的點擊照樣變成新頂點
        if (state.mode) return;
        L.DomEvent.stop(e);
        selectFeature(f.id);
      });
      return lay;
    }

    function redraw() {
      Object.keys(state.layers).forEach(function (id) {
        map.removeLayer(state.layers[id]);
        delete state.layers[id];
      });
      state.features.forEach(function (f) {
        if (f.project !== state.current) return;
        var lay = buildLayer(f);
        lay.addTo(map);
        state.layers[f.id] = lay;
      });
    }

    // ── 繪製互動 ────────────────────────────────────────
    function setMode(mode) {
      cancelDraft();
      state.mode = mode;
      map.getContainer().style.cursor = mode ? 'crosshair' : '';
      renderToolbar();
      if (mode) {
        hint(mode === 'point' ? '點一下地圖放置點位'
          : mode === 'circle' ? '先點圓心，再點一下決定半徑'
            : '依序點選頂點，按「完成」或按 Enter 結束（Esc 取消）', 5000);
      }
    }

    function cancelDraft() {
      state.draft = [];
      if (state.draftLayer) { map.removeLayer(state.draftLayer); state.draftLayer = null; }
      if (state.ghost) { map.removeLayer(state.ghost); state.ghost = null; }
      renderDraftInfo();
    }

    function refreshDraft() {
      if (state.draftLayer) { map.removeLayer(state.draftLayer); state.draftLayer = null; }
      if (!state.draft.length) return;
      var lls = state.draft.map(function (p) { return L.latLng(p[0], p[1]); });
      var st = { color: '#2f6b52', weight: 2, dashArray: '6 4', fillOpacity: 0.12, fillColor: '#2f6b52' };
      if (state.mode === 'polygon' && lls.length >= 3) state.draftLayer = L.polygon(lls, st);
      else if (lls.length >= 2) state.draftLayer = L.polyline(lls, st);
      else state.draftLayer = L.circleMarker(lls[0], Object.assign({ radius: 5 }, st));
      state.draftLayer.addTo(map);
      renderDraftInfo();
    }

    function renderDraftInfo() {
      var box = document.getElementById('draw-live');
      if (!box) return;
      if (!state.draft.length) { box.textContent = ''; box.hidden = true; return; }
      var lls = state.draft.map(function (p) { return L.latLng(p[0], p[1]); });
      var txt = '頂點 ' + lls.length;
      if (state.mode === 'line' && lls.length >= 2) txt += '　長度 ' + fmtLen(lengthOf(lls));
      if (state.mode === 'polygon' && lls.length >= 3) txt += '　面積 ' + fmtArea(areaOf(lls));
      box.textContent = txt;
      box.hidden = false;
    }

    function finishDraft() {
      var need = state.mode === 'polygon' ? 3 : 2;
      if (state.mode === 'line' || state.mode === 'polygon') {
        if (state.draft.length < need) { hint('至少需要 ' + need + ' 個頂點'); return; }
        addFeature(state.mode, state.draft.slice());
      }
      cancelDraft();
    }

    function addFeature(type, pts, radius) {
      var f = {
        id: 'f' + Date.now() + Math.floor(Math.random() * 1000),
        type: type, pts: pts, radius: radius || 0,
        name: '', style: defaultStyle(), project: state.current
      };
      state.features.push(f);
      save();
      redraw();
      renderList();
      hint('已新增' + typeName(type));
      return f;
    }

    function typeName(t) {
      return { point: '點', line: '線', polygon: '面', circle: '圓' }[t] || t;
    }

    map.on('click', function (e) {
      if (!state.mode) return;
      var p = [e.latlng.lat, e.latlng.lng];
      if (state.mode === 'point') { addFeature('point', [p]); setMode(null); return; }
      if (state.mode === 'circle') {
        if (!state.draft.length) { state.draft.push(p); refreshDraft(); return; }
        var c = L.latLng(state.draft[0][0], state.draft[0][1]);
        addFeature('circle', [state.draft[0]], lengthOf([c, e.latlng]));
        cancelDraft(); setMode(null); return;
      }
      state.draft.push(p);
      refreshDraft();
    });

    map.on('mousemove', function (e) {
      if (!state.mode || !state.draft.length) return;
      if (state.ghost) { map.removeLayer(state.ghost); state.ghost = null; }
      var last = state.draft[state.draft.length - 1];
      state.ghost = L.polyline([L.latLng(last[0], last[1]), e.latlng],
        { color: '#2f6b52', weight: 1, dashArray: '3 4', opacity: 0.7 }).addTo(map);
    });

    map.on('dblclick', function (e) {
      if (state.mode === 'line' || state.mode === 'polygon') {
        L.DomEvent.stop(e);
        finishDraft();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (!state.mode) return;
      if (e.key === 'Escape' || e.keyCode === 27) { setMode(null); hint('已取消'); }
      else if (e.key === 'Enter' || e.keyCode === 13) { e.preventDefault(); finishDraft(); }
    });

    // ── 面板 ────────────────────────────────────────────
    var TOOLS = [
      ['point', '點'], ['line', '線'], ['polygon', '面'], ['circle', '圓']
    ];

    function renderToolbar() {
      var host = document.getElementById('draw-tools');
      if (!host) return;
      host.textContent = '';
      TOOLS.forEach(function (t) {
        var b = el('button', 'chip' + (state.mode === t[0] ? ' is-on' : ''), t[1]);
        b.addEventListener('click', function () { setMode(state.mode === t[0] ? null : t[0]); });
        host.appendChild(b);
      });
      var fin = el('button', 'chip', '完成');
      fin.addEventListener('click', finishDraft);
      var esc = el('button', 'chip', '取消');
      esc.addEventListener('click', function () { setMode(null); });
      host.appendChild(fin);
      host.appendChild(esc);
    }

    function renderProjects() {
      var sel = document.getElementById('draw-project');
      if (!sel) return;
      sel.textContent = '';
      state.projects.forEach(function (p) {
        var o = new Option(p.name, p.id);
        if (p.id === state.current) o.selected = true;
        sel.appendChild(o);
      });
    }

    var selected = null;
    function selectFeature(id) {
      selected = id;
      renderList();
      var f = state.features.filter(function (x) { return x.id === id; })[0];
      if (f) {
        var lay = state.layers[id];
        if (lay && lay.openTooltip) lay.openTooltip();
      }
    }

    function renderList() {
      var host = document.getElementById('draw-list');
      if (!host) return;
      host.textContent = '';
      var mine = state.features.filter(function (f) { return f.project === state.current; });
      if (!mine.length) {
        host.appendChild(el('p', 'empty', '這個專案還沒有物件。用上面的工具開始畫。'));
        return;
      }
      mine.forEach(function (f) {
        var row = el('div', 'dwrow' + (selected === f.id ? ' is-sel' : ''));

        var head = el('div', 'dwhead');
        var sw = el('span', 'dwdot');
        sw.style.background = f.style.color;
        head.appendChild(sw);
        var nm = el('span', 'dwname', (f.name || '未命名') + '（' + typeName(f.type) + '）');
        nm.addEventListener('click', function () {
          var lls = toLatLngs(f);
          if (f.type === 'point') map.setView(lls[0], Math.max(map.getZoom(), 18));
          else if (f.type === 'circle') map.fitBounds(L.circle(lls[0], { radius: f.radius }).getBounds());
          else map.fitBounds(L.latLngBounds(lls).pad(0.2));
          selectFeature(f.id);
        });
        head.appendChild(nm);
        var x = el('button', 'x', '✕');
        x.title = '刪除';
        x.addEventListener('click', function () {
          state.features = state.features.filter(function (o) { return o.id !== f.id; });
          save(); redraw(); renderList();
        });
        head.appendChild(x);
        row.appendChild(head);

        var m = measureText(f);
        if (m) row.appendChild(el('div', 'dwmeas', m.replace(/\n/g, '　')));

        if (selected === f.id) {
          var edit = el('div', 'dwedit');

          var nin = el('input');
          nin.type = 'text';
          nin.placeholder = '物件名稱';
          nin.value = f.name || '';
          nin.addEventListener('change', function () {
            f.name = nin.value.trim(); save(); redraw(); renderList();
          });
          edit.appendChild(nin);

          var srow = el('div', 'dwstyle');
          var col = el('input');
          col.type = 'color'; col.value = f.style.color; col.title = '顏色';
          col.addEventListener('change', function () {
            f.style.color = col.value; save(); redraw();
          });
          srow.appendChild(col);

          [['weight', '線寬', 1, 10, 1], ['opacity', '不透明', 0.1, 1, 0.1], ['fill', '填滿', 0, 1, 0.1]]
            .forEach(function (cfg) {
              var wrap = el('label', 'dwslider');
              wrap.appendChild(el('span', null, cfg[1]));
              var r = el('input');
              r.type = 'range'; r.min = cfg[2]; r.max = cfg[3]; r.step = cfg[4];
              r.value = f.style[cfg[0]];
              r.addEventListener('input', function () {
                f.style[cfg[0]] = parseFloat(r.value);
                var lay = state.layers[f.id];
                if (lay && lay.setStyle) lay.setStyle(styleOf(f));
              });
              r.addEventListener('change', save);
              wrap.appendChild(r);
              srow.appendChild(wrap);
            });
          edit.appendChild(srow);
          row.appendChild(edit);
        }
        host.appendChild(row);
      });
    }

    // ── 匯出／匯入 ──────────────────────────────────────
    function exportProject() {
      var p = state.projects.filter(function (x) { return x.id === state.current; })[0];
      var data = {
        kind: 'landmap-tw.project',
        project: p,
        features: state.features.filter(function (f) { return f.project === state.current; })
      };
      var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      var a = el('a');
      a.href = URL.createObjectURL(blob);
      a.download = (p.name || 'project') + '.json';
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); document.body.removeChild(a); }, 1000);
    }

    function importProject(text) {
      var d = JSON.parse(text);
      if (!d || !Array.isArray(d.features)) throw new Error('不是專案檔');
      var id = 'p' + Date.now();
      var name = (d.project && d.project.name ? d.project.name : '匯入的專案');
      state.projects.push({ id: id, name: name, created: 0 });
      d.features.forEach(function (f) {
        f.id = 'f' + Date.now() + Math.floor(Math.random() * 100000);
        f.project = id;
        if (!f.style) f.style = defaultStyle();
        state.features.push(f);
      });
      state.current = id;
      save(); renderProjects(); redraw(); renderList();
      return name;
    }

    // 匯出成 GeoJSON，可丟進 QGIS / Google Earth
    function exportGeoJSON() {
      var feats = state.features.filter(function (f) { return f.project === state.current; })
        .map(function (f) {
          var coords, type;
          if (f.type === 'point') { type = 'Point'; coords = [f.pts[0][1], f.pts[0][0]]; }
          else if (f.type === 'line') { type = 'LineString'; coords = f.pts.map(function (p) { return [p[1], p[0]]; }); }
          else if (f.type === 'circle') {
            // 圓用 64 邊形近似
            type = 'Polygon';
            var c = L.latLng(f.pts[0][0], f.pts[0][1]), ring = [];
            for (var i = 0; i <= 64; i++) {
              var ang = i / 64 * 2 * Math.PI;
              var dLat = (f.radius * Math.cos(ang)) / 111320;
              var dLng = (f.radius * Math.sin(ang)) / (111320 * Math.cos(c.lat * Math.PI / 180));
              ring.push([c.lng + dLng, c.lat + dLat]);
            }
            coords = [ring];
          } else {
            type = 'Polygon';
            var r = f.pts.map(function (p) { return [p[1], p[0]]; });
            r.push(r[0]);
            coords = [r];
          }
          return {
            type: 'Feature',
            properties: { name: f.name || '', 類型: typeName(f.type), 量測: measureText(f).replace(/\n/g, ' ') },
            geometry: { type: type, coordinates: coords }
          };
        });
      var blob = new Blob([JSON.stringify({ type: 'FeatureCollection', features: feats }, null, 2)],
        { type: 'application/geo+json' });
      var p = state.projects.filter(function (x) { return x.id === state.current; })[0];
      var a = el('a');
      a.href = URL.createObjectURL(blob);
      a.download = (p.name || 'project') + '.geojson';
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); document.body.removeChild(a); }, 1000);
    }

    // ── 對外 ────────────────────────────────────────────
    return {
      mount: function () {
        renderToolbar();
        renderProjects();
        renderList();
        redraw();
      },
      newProject: function (name) {
        var id = 'p' + Date.now();
        state.projects.push({ id: id, name: name || '新專案', created: 0 });
        state.current = id;
        save(); renderProjects(); redraw(); renderList();
      },
      renameProject: function (name) {
        var p = state.projects.filter(function (x) { return x.id === state.current; })[0];
        if (p) { p.name = name; save(); renderProjects(); }
      },
      deleteProject: function () {
        if (state.projects.length <= 1) return false;
        var id = state.current;
        state.projects = state.projects.filter(function (p) { return p.id !== id; });
        state.features = state.features.filter(function (f) { return f.project !== id; });
        state.current = state.projects[0].id;
        save(); renderProjects(); redraw(); renderList();
        return true;
      },
      switchProject: function (id) {
        state.current = id; save(); redraw(); renderList();
      },
      clearProject: function () {
        state.features = state.features.filter(function (f) { return f.project !== state.current; });
        save(); redraw(); renderList();
      },
      exportProject: exportProject,
      exportGeoJSON: exportGeoJSON,
      importProject: importProject,
      setMode: setMode,
      isDrawing: function () { return !!state.mode; },
      // 給定位模組用：把走出來的軌跡直接存成目前專案的一條線
      addTrack: function (pts, name) {
        if (!pts || pts.length < 2) return null;
        var f = addFeature('line', pts.slice());
        f.name = name || '軌跡';
        f.style.color = '#2f6b52';
        save(); redraw(); renderList();
        return f;
      },
      trackLength: function (pts) {
        return lengthOf(pts.map(function (p) { return L.latLng(p[0], p[1]); }));
      },
      redraw: redraw,
      fmtLen: fmtLen,
      fmtArea: fmtArea
    };
  }

  g.DrawTool = { create: create, fmtLen: fmtLen, fmtArea: fmtArea };
})(window);
