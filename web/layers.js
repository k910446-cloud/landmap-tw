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

  /* sample:true  = 可在「點位查詢」時抓取該圖層在點擊處的顏色。
   * legend:[...] = 官方圖例的主要色塊，供比對參考。
   */
  // 縣市的 ArcGIS 動態出圖服務：地籍圖本身就帶地號註記，
  // 用 export 端點依畫面範圍即時出圖。層級太小就不出（避免打爆對方主機）。
  function cadastre(id, name, base, layerIds, attr, note, serial) {
    return {
      group: '地籍圖（含地號）', id: id, name: name + '（含地號）',
      exportService: { base: base, layerIds: layerIds },
      opacity: 0.95, on: false, minZoom: 16, attr: attr, note: note,
      serial: !!serial
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

  /* 新竹縣的都市計畫只有竹東鎮公所自己架了一台 GeoServer 公開出來。
   *
   * 縣府的智慧圖資雲（imap.hchg.gov.tw）只有地籍、地價與非都市土地，
   * 沒有都市計畫；國土測繪中心的公開圖磚（444 層）裡也只有非都市土地
   * 那兩層。全國性的都市計畫圖資是國土管理署的付費介接服務，所以
   * 有沒有得看，完全取決於各縣市自己有沒有另外公開 —— 新竹縣目前
   * 只有竹東鎮這一份。涵蓋範圍就是竹東鎮，出了鎮界就是空的。 */
  var ZD = 'https://township.planning.hcctt.gov.tw:8080/geoserver/ows';

  // GeoServer 的 WMS 疊圖。走 Leaflet 內建的 L.tileLayer.wms。
  function wms(id, group, name, layers, attr, opacity, minZoom, note) {
    return {
      group: group, id: id, name: name,
      wms: { base: ZD, layers: layers },
      opacity: opacity == null ? 0.6 : opacity, on: false,
      minZoom: minZoom || 12, attr: attr, note: note
    };
  }

  /* 內政部地政司的開發區圖磚（免申請、免金鑰、有送 CORS 標頭）。
   * 每一種開發方式都分「辦理完成」與「辦理中」兩層 —— 對做開發的人來說
   * 「還在辦理中」那一層往往才是重點。 */
  function dev(id, name, layer, note) {
    return {
      group: '土地開發', id: id, name: name, on: false, opacity: 0.75,
      url: 'https://publands.land.moi.gov.tw/R02map/wmts/' + layer
        + '/default/EPSG:3857/{z}/{y}/{x}',
      maxNativeZoom: 20, attr: '開發區圖資 © 內政部地政司', note: note || undefined
    };
  }

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
      '都市計畫圖 © 新竹市政府', 0.85, 9,
      '含主要計畫區與細部計畫區。圖上那些孤零零的數字是新竹市政府給每個'
      + '主要計畫區的代碼（不是地號、也不是分區）：'
      + '1 新竹漁港特定區、2 擴大新竹市都市計畫（高速公路交流道附近地區）、'
      + '3 新竹市（朝山地區）、4 新竹科技特定區、5 新竹（含香山）、'
      + '6 新竹科學工業園區特定區、11 新竹市都市計畫。'
      + '想看名稱而不是代碼，改開「計畫區範圍（逐計畫區）」。'),
    urban('UR_CH', '計畫區範圍　彰化縣', CH, '14', '都市計畫圖 © 彰化縣政府', 0.85, 9),
    urban('UR_ML', '計畫區範圍　苗栗縣', ML, '1', '都市計畫圖 © 苗栗縣政府', 0.85, 9),

    // 名稱跟其他縣市一致寫「新竹縣」，才排得進由北到南的順序裡；
    // 但實際涵蓋的只有竹東鎮（全縣只有竹東鎮公所把都市計畫公開成圖服務），
    // 所以每一層的說明第一句就講清楚，免得有人在新豐、湖口打開卻空白。
    wms('UZ_ZD', '都市計畫', '使用分區　新竹縣', 'ZhuDong:JC_UseZoneAll',
      '都市計畫圖 © 新竹縣竹東鎮公所', 0.6, 13,
      '僅涵蓋竹東鎮 —— 新竹縣只有竹東鎮把都市計畫公開成圖服務，其他鄉鎮市查不到。'
      + '圖上有分區名稱註記。全縣的計畫區外框請開「計畫區範圍（逐計畫區）」。'),
    wms('UR_ZD', '都市計畫', '計畫區範圍　新竹縣', 'ZhuDong:JC_Uplan',
      '都市計畫圖 © 新竹縣竹東鎮公所', 0.9, 9,
      '僅涵蓋竹東鎮。竹東都市計畫區的外框（紅色虛線）。'
      + '全縣 16 個計畫區的外框請開「計畫區範圍（逐計畫區）」。'),

    // 這一層不是圖磚也不是出圖，是向量外框（見 urbanarea.js）。
    // 因為向量才算得出「這個點在不在框裡」，點一下就能明確回答
    // 屬於哪一個都市計畫區 —— 圖磚只能用眼睛看個大概。
    {
      group: '都市計畫', id: 'UPLAN_AREA', name: '計畫區範圍（逐計畫區）',
      vector: 'urbanArea', opacity: 1, on: false, minZoom: 10,
      attr: '都市計畫區範圍 © 內政部國土管理署城鄉發展分署',
      note: '各個都市計畫區的外框，滑過去會顯示計畫區名稱（例如「新豐(山崎地區)都市計畫」）。'
        + '框內走都市計畫法，框外走區域計畫法與非都市土地使用管制規則。'
        + '目前收錄新竹縣；本圖資僅供參考，實際範圍以公告發布實施之書圖為準。'
    },

    // 新竹縣沒有用 export：同一台主機的 export 每張圖磚要八秒，一個畫面
    // 要一分半，等於不能用；而快取圖磚只要 0.1 秒。所以改用兩張快取圖磚 ——
    // 界線一張、地號註記一張，兩張都開就等於其他縣市的「地籍圖（含地號）」。
    {
      group: '地籍圖（含地號）', id: 'HCHG_LAND', name: '地籍圖　新竹縣（宗地界線）',
      url: 'https://imap.hchg.gov.tw/arcgis/rest/services/Tiled3857/Land3857/MapServer/tile/{z}/{y}/{x}',
      opacity: 0.9, on: false, maxNativeZoom: 19, serial: true,
      attr: '地籍圖磚 © 新竹縣政府',
      note: '新竹縣的宗地界線。地號要另外開下面那一層。'
        + '這台主機一次只肯服務一個連線，所以圖磚是排隊一張一張載的，'
        + '會比其他縣市慢一點。'
    },
    {
      group: '地籍圖（含地號）', id: 'HCHG_LANDNO', name: '地籍圖　新竹縣（地號註記）',
      url: 'https://imap.hchg.gov.tw/arcgis/rest/services/Tiled3857/LandNumber3857/MapServer/tile/{z}/{y}/{x}',
      opacity: 1, on: false, maxNativeZoom: 19, serial: true,
      attr: '地籍圖磚 © 新竹縣政府',
      note: '把地號標在圖上。跟上面那一層一起開。'
    },
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

    /* 土地開發：區段徵收、市地重劃、農村社區土地重劃。
     *
     * 內政部把「土地開發資訊系統」併進了地籍圖資網路便民服務系統，
     * 全國一千一百多個開發區的範圍以公開 WMTS 發布（免申請、免金鑰、
     * 有送 CORS 標頭）。圖面本身就帶開發區名稱註記，
     * 例如湖口(王爺壟)區段徵收。
     *
     * 這跟「都市計畫區範圍」是兩回事：都市計畫區講的是這塊地適用哪一套
     * 法規，重劃／徵收講的是這塊地有沒有被納入某個開發案 ——
     * 對做開發的人來說兩個都要看。 */
    dev('DEV_A4', '區段徵收（辦理完成）', 'USEA4',
      '已公告完成的區段徵收開發區，圖上有開發區名稱。'),
    dev('DEV_A3', '區段徵收（辦理中）', 'USEA3',
      '還在辦理中的區段徵收 —— 對開發評估來說，這一層往往比已完成的更重要。'),
    dev('DEV_B4', '市地重劃（辦理完成）', 'USEB4', '已完成的市地重劃區。'),
    dev('DEV_B3', '市地重劃（辦理中）', 'USEB3', '還在辦理中的市地重劃區。'),
    dev('DEV_D4', '農村社區土地重劃（辦理完成）', 'USED4', null),
    dev('DEV_D3', '農村社區土地重劃（辦理中）', 'USED3', null),

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
    { group: '環境敏感', id: 'GeoSensitive2',     name: '地質敏感區（山崩與地滑）', url: url('GeoSensitive2'), opacity: 0.6, on: false }
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
