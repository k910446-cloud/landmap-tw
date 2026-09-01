/* 這個檔案由 build_static.py 從 datasets.py 產生，不要手動改。
 *
 * 靜態版（GitHub Pages）沒有後端，地籍與都市計畫查詢由瀏覽器直接
 * 打各縣市的 ArcGIS 服務。只有會送 CORS 標頭的服務能這樣用，
 * 所以這裡的縣市會比本機完整版少。
 */
window.SERVICES = {
  "cadastre": {
    "臺中市": {
      "url": "https://mcgbm.taichung.gov.tw/arcgis/rest/services/urpd_tccgupMap/MapServer/1/query",
      "wkid": 102443,
      "sect": [
        "landdesc"
      ],
      "sectcode": [
        "sectno"
      ],
      "mother": [
        "landmon"
      ],
      "child": [
        "landchild"
      ],
      "area": [
        "Shape.STArea()"
      ],
      "town": [
        "zondesc"
      ],
      "source": "臺中市政府都市發展局 公開圖服務"
    },
    "臺北市": {
      "url": "https://www.historygis.udd.gov.taipei/arcgis/rest/services/Urban/Land_Dynamic/MapServer/5/query",
      "wkid": 102443,
      "sect": [
        "sect_name"
      ],
      "sectcode": [
        "sect_id"
      ],
      "landno": [
        "land_no"
      ],
      "mother": [
        "land_pnum"
      ],
      "child": [
        "land_snum"
      ],
      "area": [
        "Shape_Area"
      ],
      "town": [
        "dist_name"
      ],
      "source": "臺北市政府都市發展局 公開圖服務"
    },
    "桃園市": {
      "url": "https://urbandatasrv.tycg.gov.tw/server/rest/services/TY_UPGIS/TYMap_SDE/MapServer/1/query",
      "wkid": 102443,
      "sect": [],
      "sectcode": [
        "section"
      ],
      "landno": [
        "sc"
      ],
      "landno8": [
        "LANDNO8"
      ],
      "area": [
        "Shape.STArea()"
      ],
      "source": "桃園市政府都市發展局 公開圖服務"
    },
    "新竹市": {
      "url": "https://urbanmap.hccg.gov.tw/server/rest/services/Land/Land/MapServer/0/query",
      "wkid": 102443,
      "sect": [
        "SECNAME"
      ],
      "sectcode": [
        "SECT"
      ],
      "landno": [
        "LAND_NO"
      ],
      "landno8": [
        "LANDNO8"
      ],
      "area": [
        "AREA"
      ],
      "town": [
        "TNAME"
      ],
      "source": "新竹市政府都市發展處 公開圖服務"
    },
    "新竹縣": {
      "url": "https://imap.hchg.gov.tw/arcgis/rest/services/Tiled3857/Land3857/MapServer/1/query",
      "wkid": 102100,
      "sect": [
        "KCNT"
      ],
      "sectcode": [
        "AA48"
      ],
      "landno8": [
        "AA49"
      ],
      "area": [
        "AA10"
      ],
      "office": [
        "UNIT"
      ],
      "source": "新竹縣政府 智慧圖資雲 公開圖服務"
    },
    "苗栗縣": {
      "url": "https://ailand.miaoli.gov.tw/server/rest/services/Dynamic/LandNo/MapServer/0/query",
      "wkid": 102443,
      "sect": [
        "KCNT"
      ],
      "sectcode": [
        "AA48"
      ],
      "landno": [
        "LandNo"
      ],
      "landno8": [
        "AA49"
      ],
      "area": [
        "Shape.STArea()"
      ],
      "office": [
        "UNIT"
      ],
      "source": "苗栗縣政府 栗智網 公開圖服務",
      "needsProxy": true
    },
    "彰化縣": {
      "url": "https://urbangis.chcg.gov.tw/arcgis/rest/services/CHCGMap/LAND/MapServer/0/query",
      "wkid": 102443,
      "sect": [
        "SECNAME"
      ],
      "sectcode": [
        "SECT"
      ],
      "landno": [
        "LAND_NO"
      ],
      "landno8": [
        "LANDNO8"
      ],
      "area": [
        "AREA"
      ],
      "town": [
        "TNAME"
      ],
      "source": "彰化縣政府 公開圖服務"
    }
  },
  "urban": {
    "桃園市": {
      "url": "https://urbandatasrv.tycg.gov.tw/server/rest/services/TY_UPGIS/TYMap_SDE/MapServer/2/query",
      "wkid": 102443
    },
    "彰化縣": {
      "url": "https://urbangis.chcg.gov.tw/arcgis/rest/services/CHCGMap/CITYPLANS/MapServer/19/query",
      "wkid": 102443
    },
    "臺中市": {
      "url": "https://mcgbm.taichung.gov.tw/arcgis/rest/services/URBAN97/MapServer/1/query",
      "wkid": 102443
    },
    "新竹市": {
      "url": "https://urbanmap.hccg.gov.tw/server/rest/services/UrbanPlan/Landuse_NoCache/MapServer/1/query",
      "wkid": 102443
    },
    "苗栗縣": {
      "url": "https://ailand.miaoli.gov.tw/server/rest/services/Dynamic/Urban_Planning/MapServer/0/query",
      "wkid": 102443,
      "needsProxy": true
    },
    "臺北市": {
      "url": "https://www.historygis.udd.gov.taipei/arcgis/rest/services/UrbanPlan2/UrbanPlan2/MapServer/2/query",
      "wkid": 102100
    }
  },
  "urbanFields": {
    "value": [
      "使用分區",
      "ZONENAME",
      "ZoningName",
      "LANDUSE",
      "LUSE",
      "NAME",
      "ZONE",
      "分區簡稱",
      "分區代碼"
    ],
    "code": [
      "分區代碼",
      "分區簡稱",
      "SHORTNAME",
      "PUBNO",
      "BLOCK_DEF",
      "ZONE",
      "ZONE_CODE"
    ],
    "extra": [
      [
        "建蔽率",
        [
          "BCRTEXT",
          "B_RATIO",
          "建蔽率",
          "bcr",
          "BuildingCo"
        ]
      ],
      [
        "容積率",
        [
          "FARTEXT",
          "F_RATIO",
          "容積率",
          "fsifar",
          "FloorAreaR"
        ]
      ],
      [
        "上限容積",
        [
          "上限容積"
        ]
      ],
      [
        "都市計畫",
        [
          "URBANNAME",
          "MUPLAN",
          "URBAN",
          "都市計畫區",
          "MainPlanNa",
          "計畫名稱"
        ]
      ],
      [
        "細部計畫",
        [
          "細部計畫區"
        ]
      ],
      [
        "備註",
        [
          "備註",
          "Note"
        ]
      ]
    ]
  },
  "nonUrbanCounties": [
    "南投縣",
    "嘉義縣",
    "基隆市",
    "宜蘭縣",
    "屏東縣",
    "彰化縣",
    "新北市",
    "新竹市",
    "新竹縣",
    "桃園市",
    "澎湖縣",
    "臺中市",
    "臺南市",
    "臺東縣",
    "花蓮縣",
    "苗栗縣",
    "雲林縣",
    "高雄市"
  ]
};
