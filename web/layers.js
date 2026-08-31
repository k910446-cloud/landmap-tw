/* 圖層目錄 — 全部取自內政部國土測繪中心「國土測繪圖資網路地圖服務系統」
 * 開放圖磚 (WMTS)，免申請、免金鑰。
 *   服務網址   https://wmts.nlsc.gov.tw/wmts
 *   圖磚格式   /{圖層}/default/EPSG:3857/{TileMatrix}/{TileRow}/{TileCol}
 *              對應 Leaflet 的 {z}/{y}/{x}
 */
(function (g) {
  'use strict';

  var NLSC = 'https://wmts.nlsc.gov.tw/wmts/{L}/default/EPSG:3857/{z}/{y}/{x}';
  var ATTR = '圖資 © <a href="https://maps.nlsc.gov.tw/" target="_blank" rel="noopener">內政部國土測繪中心</a>';

  function url(layer) { return NLSC.replace('{L}', layer); }

  var BASES = [
    { id: 'EMAP',      name: '通用電子地圖',       url: url('EMAP') },
    { id: 'PHOTO_MIX', name: '正射影像（混合）',   url: url('PHOTO_MIX') },
    { id: 'PHOTO2',    name: '正射影像',           url: url('PHOTO2') },
    { id: 'EMAP01',    name: '電子地圖（灰階）',   url: url('EMAP01') },
    { id: 'B5000',     name: '1/5000 基本地形圖',  url: url('B5000') },
    { id: 'RUDY',      name: '魯地圖（OSM 台灣）',
      url: 'https://tile.happyman.idv.tw/map/rudy/{z}/{x}/{y}.png',
      attr: '圖磚 © <a href="https://rudy.dev.moi.gov.tw/" target="_blank" rel="noopener">魯地圖</a>，資料 © OpenStreetMap 貢獻者' },
    { id: 'OSM',       name: 'OpenStreetMap',
      url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      attr: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> 貢獻者' },
    { id: 'BLANK',     name: '空白（只看疊圖）',   url: null }
  ];

  // 中央研究院人社中心 GIS 專題中心「臺灣百年歷史地圖」
  // 圖磚格式：/tileserver/file-exists.php?img={圖層}-png-{z}-{x}-{y}
  var SINICA = 'https://gis.sinica.edu.tw/tileserver/file-exists.php?img={L}-png-{z}-{x}-{y}';
  var SINICA_ATTR = '歷史圖資 © <a href="https://gis.sinica.edu.tw/" target="_blank" rel="noopener">中研院人社中心 GIS 專題中心</a>';
  function hist(id, name, note) {
    return {
      group: '歷史圖資', id: 'SINICA_' + id, name: name,
      url: SINICA.replace('{L}', id), opacity: 0.8, on: false,
      maxNativeZoom: 17, attr: SINICA_ATTR, note: note
    };
  }

  /* sample:true  = 可在「點位查詢」時抓取該圖層在點擊處的顏色。
   * legend:[...] = 官方圖例的主要色塊，供比對參考。
   */
  // 縣市的 ArcGIS 動態出圖服務：地籍圖本身就帶地號註記，
  // 用 export 端點依畫面範圍即時出圖。層級太小就不出（避免打爆對方主機）。
  function cadastre(id, name, base, layerIds, attr, note) {
    return {
      group: '地籍圖（含地號）', id: id, name: name + '（含地號）',
      exportService: { base: base, layerIds: layerIds },
      opacity: 0.95, on: false, minZoom: 16, attr: attr, note: note
    };
  }

  // 都市計畫：使用分區圖與計畫區範圍。同樣走縣市 ArcGIS 的動態出圖。
  function urban(id, name, base, layerIds, attr, opacity, minZoom, note) {
    return {
      group: '都市計畫', id: id, name: name,
      exportService: { base: base, layerIds: layerIds },
      opacity: opacity == null ? 0.6 : opacity, on: false,
      minZoom: minZoom || 12, attr: attr, note: note
    };
  }

  var TP = 'https://www.historygis.udd.gov.taipei/arcgis/rest/services';
  var TY = 'https://urbandatasrv.tycg.gov.tw/server/rest/services/TY_UPGIS/TYMap_SDE/MapServer/export';
  var TC = 'https://mcgbm.taichung.gov.tw/arcgis/rest/services/urpd_tccgupMap/MapServer/export';
  var HC = 'https://urbanmap.hccg.gov.tw/server/rest/services/UrbanPlan';
  var CH = 'https://urbangis.chcg.gov.tw/arcgis/rest/services/CHCGMap/CITYPLANS/MapServer/export';
  var ML = 'https://ailand.miaoli.gov.tw/server/rest/services/Dynamic/Urban_Planning/MapServer/export';

  var OVERLAYS = [
    {
      group: '地籍', id: 'LANDSECT', name: '段籍圖（地段外圍）', url: url('LANDSECT'),
      opacity: 1, on: true,
      note: '顯示「段」的界線與段名。宗地（單筆地號）層級的地籍圖屬須申請介接的圖資，未內含。'
    },
    {
      group: '地籍', id: 'LANDSECT2', name: '段籍圖（依類別著色）', url: url('LANDSECT2'),
      opacity: 0.75, on: false
    },
    {
      group: '地籍', id: 'LAND_OPENDATA', name: '公有土地地籍圖', url: url('LAND_OPENDATA'),
      opacity: 0.7, on: false,
      note: '各級政府所有之土地，宗地層級。'
    },
    {
      group: '地籍', id: 'HCHG_LAND', name: '宗地界線　新竹縣（快取圖磚，較快）',
      url: 'https://imap.hchg.gov.tw/arcgis/rest/services/Tiled3857/Land3857/MapServer/tile/{z}/{y}/{x}',
      opacity: 0.9, on: false, maxNativeZoom: 19,
      attr: '地籍圖磚 © 新竹縣政府',
      note: '宗地界線，只涵蓋新竹縣。縣府智慧圖資雲的公開圖磚。'
    },
    {
      group: '地籍', id: 'HCHG_LANDNO', name: '地號註記　新竹縣（快取圖磚）',
      url: 'https://imap.hchg.gov.tw/arcgis/rest/services/Tiled3857/LandNumber3857/MapServer/tile/{z}/{y}/{x}',
      opacity: 1, on: false, maxNativeZoom: 19,
      attr: '地籍圖磚 © 新竹縣政府'
    },
    {
      group: '地籍', id: 'MIAOLI_LAND', name: '宗地界線　苗栗縣（快取圖磚，較快）',
      url: 'https://ailand.miaoli.gov.tw/server/rest/services/Tiled3857/Land3857/MapServer/tile/{z}/{y}/{x}',
      opacity: 0.9, on: false, maxNativeZoom: 19,
      attr: '地籍圖磚 © 苗栗縣政府',
      note: '宗地界線，只涵蓋苗栗縣。「栗智網」的公開圖磚。'
    },
    urban('UZ_TP', '使用分區　臺北市', TP + '/UrbanPlan2/UrbanPlan2/MapServer/export', '0,2',
      '都市計畫圖 © 臺北市政府', 0.6, 13),
    urban('UZ_TY', '使用分區　桃園市', TY, '2,26', '都市計畫圖 © 桃園市政府', 0.6, 13),
    urban('UZ_TC', '使用分區　臺中市', TC, '2', '都市計畫圖 © 臺中市政府', 0.6, 13),
    urban('UZ_HC', '使用分區　新竹市', HC + '/Landuse_NoCache/MapServer/export', '1,2',
      '都市計畫圖 © 新竹市政府', 0.6, 13),
    urban('UZ_CH', '使用分區　彰化縣', CH, '19,20', '都市計畫圖 © 彰化縣政府', 0.6, 13),
    urban('UZ_ML', '使用分區　苗栗縣', ML, '0', '都市計畫圖 © 苗栗縣政府', 0.6, 13),

    urban('UR_TY', '計畫區範圍　桃園市', TY, '22', '都市計畫圖 © 桃園市政府', 0.85, 9,
      '都市計畫區的外框。框外就是非都市土地。'),
    urban('UR_TC', '計畫區範圍　臺中市', TC, '4,6', '都市計畫圖 © 臺中市政府', 0.85, 9),
    urban('UR_HC', '計畫區範圍　新竹市', HC + '/MainSubPlan/MapServer/export', '1,2',
      '都市計畫圖 © 新竹市政府', 0.85, 9, '含主要計畫區與細部計畫區。'),
    urban('UR_CH', '計畫區範圍　彰化縣', CH, '14', '都市計畫圖 © 彰化縣政府', 0.85, 9),
    urban('UR_ML', '計畫區範圍　苗栗縣', ML, '1', '都市計畫圖 © 苗栗縣政府', 0.85, 9),

    cadastre('CAD_HCHG', '地籍圖　新竹縣',
      'https://imap.hchg.gov.tw/arcgis/rest/services/Tiled3857/Land3857/MapServer/export',
      '0,1,2', '地籍圖 © 新竹縣政府',
      '含段界、地號與地段範圍。同群組的「宗地界線　新竹縣」是快取圖磚，載入較快但沒有地號。'),
    cadastre('CAD_TP', '地籍圖　臺北市',
      'https://www.historygis.udd.gov.taipei/arcgis/rest/services/Urban/Land_Dynamic/MapServer/export',
      '3,5', '地籍圖 © 臺北市政府'),
    cadastre('CAD_TY', '地籍圖　桃園市',
      'https://urbandatasrv.tycg.gov.tw/server/rest/services/TY_UPGIS/TYMap_SDE/MapServer/export',
      '1', '地籍圖 © 桃園市政府',
      '這一組是縣市的動態出圖，圖面本身就帶地號註記。放大到第 16 級以上才會出圖，'
      + '免得一次向對方主機要太多張。'),
    cadastre('CAD_TC', '地籍圖　臺中市',
      'https://mcgbm.taichung.gov.tw/arcgis/rest/services/urpd_tccgupMap/MapServer/export',
      '1', '地籍圖 © 臺中市政府'),
    cadastre('CAD_HC', '地籍圖　新竹市',
      'https://urbanmap.hccg.gov.tw/server/rest/services/Land/Land/MapServer/export',
      '0', '地籍圖 © 新竹市政府'),
    cadastre('CAD_CH', '地籍圖　彰化縣',
      'https://urbangis.chcg.gov.tw/arcgis/rest/services/CHCGMap/LAND/MapServer/export',
      '0', '地籍圖 © 彰化縣政府'),
    cadastre('CAD_ML', '地籍圖　苗栗縣',
      'https://ailand.miaoli.gov.tw/server/rest/services/Dynamic/LandNo/MapServer/export',
      '0', '地籍圖 © 苗栗縣政府'),

    {
      group: '使用分區 / 類別', id: 'nURBAN1', name: '非都市土地使用分區圖', url: url('nURBAN1'),
      opacity: 0.55, on: true, sample: true,
      note: '一般農業區、特定農業區、山坡地保育區、森林區、鄉村區、工業區…等 11 種分區。'
    },
    {
      group: '使用分區 / 類別', id: 'nURBAN2', name: '非都市土地使用地類別圖', url: url('nURBAN2'),
      opacity: 0.55, on: false, sample: true,
      note: '甲乙丙丁種建築用地、農牧、林業、養殖、交通、水利、水土保持…等 19 種編定類別。'
    },
    {
      group: '使用分區 / 類別', id: 'LUIMAP', name: '國土利用現況調查', url: url('LUIMAP'),
      opacity: 0.6, on: false, sample: true,
      note: '實際使用情形（非法定分區），可與法定編定對照看有無不一致。'
    },

    {
      group: '行政與參考', id: 'EMAP2', name: '電子地圖註記（透明）', url: url('EMAP2'),
      opacity: 0.9, on: false,
      note: '疊在正射影像上時可看到路名與地標。'
    },
    { group: '行政與參考', id: 'BUILDX',     name: '分棟建物框',       url: url('BUILDX'),     opacity: 0.9, on: false },
    { group: '行政與參考', id: 'Village',    name: '村里界',           url: url('Village'),    opacity: 0.8, on: false },
    { group: '行政與參考', id: 'TOWN',       name: '鄉鎮市區界',       url: url('TOWN'),       opacity: 0.8, on: false },
    { group: '行政與參考', id: 'CITY',       name: '縣市界',           url: url('CITY'),       opacity: 0.8, on: false },
    { group: '行政與參考', id: 'LandOffice', name: '地政事務所轄區',   url: url('LandOffice'), opacity: 0.6, on: false },

    { group: '環境敏感', id: 'MOI_SLOPEP_LV7_2',  name: '坡度分級（7 級）',   url: url('MOI_SLOPEP_LV7_2'),  opacity: 0.6, on: false, sample: true },
    { group: '環境敏感', id: 'MOI_SLOPEP_GT30_2', name: '坡度 30% 以上',      url: url('MOI_SLOPEP_GT30_2'), opacity: 0.6, on: false },
    { group: '環境敏感', id: 'SoilLiquefaction2', name: '土壤液化潛勢（中級）', url: url('SoilLiquefaction2'), opacity: 0.6, on: false, sample: true },
    { group: '環境敏感', id: 'GeoSensitive',      name: '地質敏感區',         url: url('GeoSensitive'),      opacity: 0.6, on: false },
    { group: '環境敏感', id: 'GeoSensitive2',     name: '地質敏感區（山崩與地滑）', url: url('GeoSensitive2'), opacity: 0.6, on: false },

    hist('JM25K_1921', '日治二萬五千分之一地形圖（1921）', '可與現況比對舊河道、聚落範圍與土地變遷。'),
    hist('AM25K_1944A', '美軍地形圖（1944）'),
    hist('AM25K_1944B', '美軍航照圖（1944）'),
    hist('JM20K_1904', '日治臺灣堡圖 明治版（1904）'),
    hist('JM20K_1921', '日治臺灣堡圖 大正版（1921）'),
    hist('JM25K_1942', '日治二萬五千分之一地形圖 昭和修正版（1942）'),
    hist('JM100K_1905', '日治十萬分一臺灣圖（1905）')
  ];

  /* 非都市土地使用分區 / 使用地類別的法定名目。
   * 用於「顏色對照表」的下拉選項 — 讓使用者把在圖上取樣到的顏色
   * 對應到正確名稱後存起來，之後同色即可自動辨識。
   */
  var ZONE_NAMES = [
    '特定農業區', '一般農業區', '工業區', '鄉村區', '森林區',
    '山坡地保育區', '風景區', '國家公園區', '河川區', '特定專用區', '礦業用地區'
  ];

  var LANDUSE_NAMES = [
    '甲種建築用地', '乙種建築用地', '丙種建築用地', '丁種建築用地',
    '農牧用地', '林業用地', '養殖用地', '鹽業用地', '礦業用地', '窯業用地',
    '交通用地', '水利用地', '遊憩用地', '古蹟保存用地', '生態保護用地',
    '國土保安用地', '殯葬用地', '海域用地', '特定目的事業用地'
  ];

  g.CATALOG = {
    bases: BASES,
    overlays: OVERLAYS,
    attribution: ATTR,
    maxNativeZoom: 20,
    zoneNames: ZONE_NAMES,
    landuseNames: LANDUSE_NAMES
  };
})(window);
