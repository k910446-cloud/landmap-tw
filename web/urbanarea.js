/* 都市計畫區範圍 —— 向量疊圖與點位判斷。
 *
 * 為什麼是向量而不是圖磚
 * ----------------------
 * 「這塊地在不在都市計畫區內、屬於哪一個計畫區」是做土地開發時的第一個問題：
 * 框內走都市計畫法與各縣市施行細則，框外走區域計畫法與非都市土地使用管制規則，
 * 兩套法規完全不同。
 *
 * 圖磚只能讓人用眼睛看個大概；向量可以直接算點在不在多邊形裡，
 * 所以點一下地圖就能明確回答「新豐(山崎地區)都市計畫」。
 * 資料量也不大 —— 一個縣市十幾個計畫區、幾千個點，大約幾十 KB。
 *
 * 資料由 build_urban_areas.py 產生，來源是國土管理署城鄉發展分署的
 * 全國土地使用分區資料查詢系統。
 */
(function (g) {
  'use strict';

  var DIR = 'urban_areas/';
  var index = null;          // {counties:[{county,bbox,plans}]}
  var loaded = {};           // 縣市 → {plans:[...]}
  var pending = {};

  function getIndex() {
    if (index) return Promise.resolve(index);
    return fetch(DIR + 'index.json', { cache: 'no-cache' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { index = d || { counties: [] }; return index; })
      .catch(function () { index = { counties: [] }; return index; });
  }

  function getCounty(name) {
    if (loaded[name]) return Promise.resolve(loaded[name]);
    if (pending[name]) return pending[name];
    pending[name] = fetch(DIR + encodeURIComponent(name) + '.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        loaded[name] = d || { plans: [] };
        return loaded[name];
      })
      .catch(function () { loaded[name] = { plans: [] }; return loaded[name]; });
    return pending[name];
  }

  // bbox 是 [西, 南, 東, 北]
  function hits(bbox, b) {
    return !(bbox[0] > b.getEast() || bbox[2] < b.getWest()
      || bbox[1] > b.getNorth() || bbox[3] < b.getSouth());
  }

  function countiesIn(bounds) {
    return getIndex().then(function (idx) {
      return (idx.counties || []).filter(function (c) {
        return hits(c.bbox, bounds);
      }).map(function (c) { return c.county; });
    });
  }

  /* 射線法。跟 app.js 判斷宗地內部用的是同一套規則（奇偶），
   * 邊界上的點算在裡面或外面都可以 —— 計畫區的框差一公尺不影響判斷。 */
  function inRing(lon, lat, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat)
        && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  /* 一個計畫區可能有好幾個環（例如竹科新竹縣部分是兩塊）。
   * 這份資料沒有區分外環與內環（孔洞），所以只要落在任何一個環裡就算 ——
   * 計畫區極少有孔洞，寧可簡單而可預期。 */
  function inPlan(lon, lat, plan) {
    for (var i = 0; i < plan.rings.length; i++) {
      if (inRing(lon, lat, plan.rings[i])) return true;
    }
    return false;
  }

  /* 這個點在哪一個都市計畫區裡？查不到就回 null（代表非都市土地或還沒收錄）。 */
  function find(lat, lon) {
    var b = L.latLngBounds([lat, lon], [lat, lon]);
    return countiesIn(b).then(function (names) {
      if (!names.length) return null;
      return Promise.all(names.map(getCounty)).then(function (files) {
        for (var i = 0; i < files.length; i++) {
          var plans = files[i].plans || [];
          for (var j = 0; j < plans.length; j++) {
            if (inPlan(lon, lat, plans[j])) {
              return { code: plans[j].code, name: plans[j].name,
                county: names[i], source: files[i].source,
                notice: files[i].notice };
            }
          }
        }
        return null;
      });
    });
  }

  /* 疊圖：依畫面範圍載入需要的縣市，畫外框並標上計畫區名稱。 */
  function makeLayer(style) {
    var group = L.layerGroup();
    var drawn = {};
    var map = null;

    function refresh() {
      if (!map) return;
      var b = map.getBounds();
      countiesIn(b).then(function (names) {
        names.forEach(function (n) {
          if (drawn[n]) return;
          drawn[n] = true;
          getCounty(n).then(function (d) {
            (d.plans || []).forEach(function (p) {
              var latlngs = p.rings.map(function (r) {
                return r.map(function (c) { return [c[1], c[0]]; });
              });
              var poly = L.polygon(latlngs, style || {
                color: '#d6336c', weight: 2, opacity: 0.9,
                fillColor: '#d6336c', fillOpacity: 0.06, dashArray: '6,4'
              });
              poly.bindTooltip(p.name, { sticky: true });
              group.addLayer(poly);
            });
          });
        });
      });
    }

    group.onAdd = function (m) {
      L.LayerGroup.prototype.onAdd.call(this, m);
      map = m;
      m.on('moveend', refresh);
      refresh();
    };
    group.onRemove = function (m) {
      m.off('moveend', refresh);
      L.LayerGroup.prototype.onRemove.call(this, m);
      map = null;
    };
    return group;
  }

  g.UrbanArea = { find: find, layer: makeLayer, index: getIndex };
}(window));
