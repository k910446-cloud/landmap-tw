# -*- coding: utf-8 -*-
"""
開放資料集登錄表。

兩份圖資都來自政府資料開放平臺，提供機關為內政部國土管理署，
授權為「政府資料開放授權條款－第 1 版」，免費、免申請：

    非都市土地使用分區圖（112年）  https://data.gov.tw/dataset/169538
    非都市土地使用地編定圖（112年）https://data.gov.tw/dataset/169539

每個縣市一到兩個 SHP 壓縮檔，使用者在 App 裡按需下載，存進 data/ 之後離線可用。
屬性表帶有法定名稱，所以查詢結果是「特定農業區」「乙種建築用地」這種名稱，
不是拿圖磚顏色去猜的。

要新增圖層（例如某縣市自行公開的都市計畫使用分區 SHP），照 DATASETS 的格式
加一筆即可 —— 引擎與前端都不需要改。
"""

MOI_DOWNLOAD = ('https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api'
                '/dataset/{dataset}/resource/{resource}/download')

# 非都市土地使用分區圖（112年）
ZONE_UUID = 'C6367713-CC90-4581-A10F-0BB4B15B9097'
ZONE_COUNTIES = {
        '南投縣': [('6E49B266-7EF9-474D-8C23-0950D9947916', 10255207)],
        '嘉義縣': [('2F77EEC6-0CC0-40ED-917E-39B7AE1F45EF', 9561697)],
        '基隆市': [('96EB2EBD-5202-408C-AA0F-19A098FF0CAA', 750460)],
        '宜蘭縣': [('F8C839A4-AFB3-4CED-92CE-0B81D6E98416', 4328387)],
        '屏東縣': [('63907BA1-69B3-44B0-896F-63BCB7B18021', 7717638)],
        '彰化縣': [('5518E2CC-ABFF-406A-A97A-2EC6E2784ADC', 6072328)],
        '新北市': [('EF6A21FD-DA48-40E1-B66A-161975FF907E', 14034671)],
        '新竹市': [('11289AFC-C694-491D-966D-80B51AAB00D0', 609355)],
        '新竹縣': [('2C6A2A4C-5EB5-4951-8560-B6E76D626CD2', 6124585)],
        '桃園市': [('1EE060FF-C972-44B2-A7BC-5B6E24B9F078', 7449722)],
        '澎湖縣': [('3C629B8C-891F-4114-B719-C9826B181867', 1621856)],
        '臺中市': [('B4DA0BAC-00D9-46D2-BE39-18957ECFA92B', 7798669)],
        '臺南市': [('609AA3C2-52C0-474A-9F05-7E8D9CF7A174', 11191454)],
        '臺東縣': [('620F7051-B331-43ED-9E35-99999E691EDC', 4460240)],
        '花蓮縣': [('7F102FBE-B5E0-433A-AD54-B56CC3017486', 6731230)],
        '苗栗縣': [('D51E3C65-A185-4C59-A4AD-FD5B9FC27FC1', 9819488)],
        '雲林縣': [('828FABEC-8AFA-4920-B067-C40434402A98', 9074220)],
        '高雄市': [('A260DF26-5035-4C0D-964F-DE621554238D', 10105518)],
}

# 非都市土地使用地編定圖（112年）—— 部分縣市拆成兩個檔
DESIG_UUID = '6E149D6E-01C4-4406-A987-046E21B60E20'
DESIG_COUNTIES = {
        '南投縣': [('B7383847-8011-4D39-A648-D3ECE3BDF240', 18803758), ('9E98AD3B-2D89-4840-AE38-988FD56382E2', 17947673)],
        '嘉義縣': [('309CFA36-1C58-41C4-A872-028DD25D25A1', 19565546), ('A3B12384-420A-4B61-9C12-6994F672E111', 23003094)],
        '基隆市': [('0BD3FC87-0DC5-4786-9AAD-D5808AD07ACD', 3233922)],
        '宜蘭縣': [('6200D90C-8B4D-4E3A-AC42-897A576C0FC6', 21814619)],
        '屏東縣': [('4969DF4F-EDDE-4BB1-A57E-BEB8B19490E4', 19134931), ('B7FFACB1-449B-4192-8626-D26A4575CBDF', 15794393)],
        '彰化縣': [('8D08EB29-5AE0-495C-BFCD-8ADF47765E7B', 25240679), ('99D85349-593C-4B75-B64D-DECB37D19CB9', 18454122)],
        '新北市': [('25410D6E-56E6-4664-B1B3-A9347E1EF4CB', 26816882), ('D3AE0EBB-A6D4-41AA-8AE2-451EC3A0329F', 20062599)],
        '新竹市': [('0F081C76-D7B9-44E5-A8FE-04DCB73126AE', 4016174)],
        '新竹縣': [('6F9CB009-C042-4743-8F87-F01A93B98DE6', 14087452), ('96C7005B-47F9-492B-8989-9EB158F8E971', 23633058)],
        '桃園市': [('1DA4864B-B9C3-4AF5-BCF4-974DF61A2D10', 21493187), ('CE315BE6-C5FE-4A99-95D0-B2C44BBF0845', 21148936)],
        '澎湖縣': [('875070F7-37A1-45F4-9677-B4A1C734AD37', 10520830)],
        '臺中市': [('9D2C5CDB-4160-4392-A800-0FC99A6E4C85', 31312328)],
        '臺南市': [('017614E0-A15B-470E-A8A7-C24ED181B306', 23925056), ('43A11878-8C1F-43E3-AA80-ABC133366422', 21797133)],
        '臺東縣': [('928B3D83-AEDF-429B-B795-23F1782EBC2D', 19853319)],
        '花蓮縣': [('33C8413F-77AB-4ACB-AE28-77ABAD90B2D7', 23335164)],
        '苗栗縣': [('3A8B7C41-A1B8-4233-8FB0-E65695671875', 17674575), ('C825330B-C03D-4347-B61C-D6DBE2F07658', 28390009)],
        '雲林縣': [('E5F6D166-1C38-4EEA-8453-BF83D785988E', 29842038), ('8023EF23-4EA7-4D69-A781-88CE6AFA28CF', 18080613)],
        '高雄市': [('320448A6-8DA4-47F2-9A03-C74F1E67516A', 18873726), ('6B731471-B295-49D2-A2DA-C83C9BCF8ADA', 15382256)],
}


# ── 都市計畫使用分區（各縣市自行公開的開放資料）─────────────────
#
# 全國性的都市計畫分區 WMTS 自 115/1/1 起改為城鄉發展分署的付費介接服務，
# 但部分縣市自己把 SHP 放在開放資料平臺上，可以直接用。
# 這裡的值是完整下載網址，不走內政部的 resource id 格式。

# 靜態版（GitHub Pages）沒有後端可以解析 SHP，改用縣市的即時查詢服務。
# 這裡只放「允許瀏覽器直連（CORS）」的服務。
URBAN_LIVE_FOR_STATIC = {
    # 這個服務是 Web Mercator（102100），不是其他縣市慣用的 TWD97 二度分帶。
    # 一開始照慣例填了 102443，座標送過去落在地球另一邊，查什麼都是空的。
    # 圖層 2 是大比例尺（較精細），屬性有 使用分區、建蔽率、容積率。
    '臺北市': {
        'service': 'arcgis', 'cors': True, 'wkid': 102100,
        'url': ('https://www.historygis.udd.gov.taipei/arcgis/rest/services'
                '/UrbanPlan2/UrbanPlan2/MapServer/2/query'),
    },
}


URBAN_COUNTIES = {
    # 臺北市都市計畫使用分區圖（臺北市資料大平臺）
    # 細部計畫在前、主要計畫在後 —— 查詢時先問細部計畫，答案比較精確
    '臺北市': [
        ('https://data.taipei/api/dataset/3bab0a01-7936-4218-8cb5-f74dfcb43dda'
         '/resource/0cb6e68a-87c1-4846-b766-bcde3ebe179c/download', 4187541),
        ('https://data.taipei/api/dataset/3bab0a01-7936-4218-8cb5-f74dfcb43dda'
         '/resource/10196e7d-2460-4b8a-b1d2-84001d09d7a4/download', 2008868),
    ],
    # 高雄市：都市發展局逐都市計畫區提供 TWD97 TM2 Shapefile
    # https://urbangisdata.kcg.gov.tw/ODA/web_page/ODA020100.jsp
    # 屬性含使用分區名稱、簡稱、建蔽率、容積率
    '高雄市': [
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000130&PK03=A000000130_20240815165156.zip', 51023),  # 彌陀都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000129&PK03=A000000129_20240815165305.zip', 354286),  # 興達港漁業特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000128&PK03=A000000128_20251022120215.zip', 37856),  # 燕巢都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000127&PK03=A000000127_20260414135122.zip', 864739),  # 澄清湖特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000126&PK03=A000000126_20260827110721.zip', 3044056),  # 鳳山都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000125&PK03=A000000125_20240815165504.zip', 111300),  # 旗山都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000124&PK03=A000000124_20240815165528.zip', 347819),  # 路竹都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000123&PK03=A000000123_20250123105350.zip', 60495),  # 湖內都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000122&PK03=A000000122_20260827110827.zip', 158028),  # 湖內(大湖地區)都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000121&PK03=A000000121_20260325143937.zip', 163141),  # 鳥松(仁美地區)都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000120&PK03=A000000120_20240815170128.zip', 116582),  # 蚵子寮近海漁業特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000119&PK03=A000000119_20240815170200.zip', 42745),  # 梓官都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000118&PK03=A000000118_20260414135203.zip', 315793),  # 高雄新市鎮特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000117&PK03=A000000117_20251222143709.zip', 48571),  # 高雄多功能經貿園區特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000116&PK03=A000000116_20260827111001.zip', 4178207),  # 高雄市主要計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000115&PK03=A000000115_20251222143617.zip', 62779),  # 高雄市主要計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000114&PK03=A000000114_20251222143048.zip', 96662),  # 高速公路岡山交流道附近特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000113&PK03=A000000113_20240911135549.zip', 81575),  # 茄萣都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000112&PK03=A000000112_20240815170535.zip', 23386),  # 美濃湖風景特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000111&PK03=A000000111_20250610140839.zip', 504416),  # 美濃都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000110&PK03=A000000110_20260827111102.zip', 342711),  # 阿蓮都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000109&PK03=A000000109_20260127112033.zip', 523607),  # 岡山都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000108&PK03=A000000108_20240815170739.zip', 30072),  # 甲仙都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000107&PK03=A000000107_20240815170801.zip', 99640),  # 月世界風景特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000106&PK03=A000000106_20240815170820.zip', 89798),  # 六龜彩蝶谷風景特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000105&PK03=A000000105_20260225142141.zip', 348948),  # 仁武都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000104&PK03=A000000104_20240815170907.zip', 145858),  # 大樹都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000103&PK03=A000000103_20240815170931.zip', 89687),  # 大樹(九曲堂)都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000102&PK03=A000000102_20260604095242.zip', 319245),  # 大寮都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000101&PK03=A000000101_20260225142310.zip', 606141),  # 大社都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000100&PK03=A000000100_20260414135040.zip', 487488),  # 大坪頂特定區計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000099&PK03=A000000099_20260225142449.zip', 677351),  # 大坪頂以東地區都市計畫
        ('https://urbangisdata.kcg.gov.tw/ODA/web_script/downloadfile.jsp?PK01=A&PK02=A000000034&PK03=A000000034_20250909113036.zip', 40287),  # 大坪頂以東地區都市計畫
    ],

    # 桃園市：都市發展局的公開 ArcGIS 服務，直接點查詢，不必下載
    # 圖層 2 = 都市計畫使用分區_SDE_UseZoneAll，座標系 wkid 102443（TWD97 TM2）
    '桃園市': {
        'service': 'arcgis', 'cors': True,
        'url': ('https://urbandatasrv.tycg.gov.tw/server/rest/services'
                '/TY_UPGIS/TYMap_SDE/MapServer/2/query'),
        'wkid': 102443,
    },

    # 彰化縣：縣府公開 ArcGIS 服務，CITYPLANS 圖層 19 = USEZONE_FULL
    '彰化縣': {
        'service': 'arcgis', 'cors': True,
        'url': ('https://urbangis.chcg.gov.tw/arcgis/rest/services'
                '/CHCGMap/CITYPLANS/MapServer/19/query'),
        'wkid': 102443,
    },

    # 臺中市：都發局公開 ArcGIS 服務，URBAN97 圖層 1 = 都市計畫分區
    # 欄位是中文，且含建蔽率、容積率、上限容積、細部計畫區
    '臺中市': {
        'service': 'arcgis', 'cors': True,
        'url': ('https://mcgbm.taichung.gov.tw/arcgis/rest/services'
                '/URBAN97/MapServer/1/query'),
        'wkid': 102443,
    },

    # 新竹市：都發處公開 ArcGIS，Landuse_NoCache 圖層 1 = 都市計畫使用分區
    '新竹市': {
        'service': 'arcgis', 'cors': True,
        'url': ('https://urbanmap.hccg.gov.tw/server/rest/services'
                '/UrbanPlan/Landuse_NoCache/MapServer/1/query'),
        'wkid': 102443,
    },

    # 苗栗縣：「栗智網」空間資訊圖台的公開 ArcGIS，Urban_Planning 圖層 0
    # 涵蓋全縣各都市計畫（苗栗、竹南頭份…），含建蔽率、容積率
    '苗栗縣': {
        'service': 'arcgis',
        'url': ('https://ailand.miaoli.gov.tw/server/rest/services'
                '/Dynamic/Urban_Planning/MapServer/0/query'),
        'wkid': 102443,
    },

    # 新北市使用分區（新北市資料開放平臺，城鄉發展局）
    '新北市': [
        ('https://urban.planning.ntpc.gov.tw/opendataDownload/'
         '%E6%96%B0%E5%8C%97%E5%B8%82%E4%BD%BF%E7%94%A8%E5%88%86%E5%8D%80.zip', 78815382),
    ],
}


DATASETS = {
    'nurban_zone': {
        'title': '非都市土地使用分區',
        'short': '分區',
        # DBF 欄位名上限 10 bytes，中文會被截短 —— 這份是「使用分」（名稱）「分區代」（代碼）
        'value_fields': ['使用分', '分區名', '分區名稱', 'ZONE_NAME'],
        'code_fields': ['分區代', '分區代碼', 'ZONE_CODE'],
        'source': '內政部國土管理署「非都市土地使用分區圖（112年）」',
        'source_url': 'https://data.gov.tw/dataset/169538',
        'licence': '政府資料開放授權條款－第 1 版',
        'dataset_uuid': ZONE_UUID,
        'counties': ZONE_COUNTIES,
        'missing_message': '這份資料沒有 %s（該縣市全域皆為都市計畫區）',
    },
    'urban_zone': {
        'title': '都市計畫使用分區',
        'short': '都計',
        # 各市欄位命名不同：臺北市「使用分區／分區簡稱／分區代碼」、
        # 新北市「ZONE」、高雄市「NAME／SHORTNAME」
        # 順序有意義：彰化縣同時有 ZONENAME（名稱）與 ZONE（代碼），
        # ZONENAME 必須排在 ZONE 前面，否則會把代碼當成名稱。
        # 新北市只有 ZONE，且存的是名稱，所以 ZONE 仍要留在候選裡。
        'value_fields': ['使用分區', 'ZONENAME', 'ZoningName', 'LANDUSE', 'LUSE',
                         'NAME', 'ZONE', '分區簡稱', '分區代碼'],
        'code_fields': ['分區代碼', '分區簡稱', 'SHORTNAME', 'PUBNO', 'BLOCK_DEF',
                        'ZONE', 'ZONE_CODE'],
        # 有就顯示，沒有就略過
        'extra_fields': [('建蔽率', ['BCRTEXT', 'B_RATIO', '建蔽率', 'bcr', 'BuildingCo']),
                         ('容積率', ['FARTEXT', 'F_RATIO', '容積率', 'fsifar', 'FloorAreaR']),
                         ('上限容積', ['上限容積']),
                         ('都市計畫', ['URBANNAME', 'MUPLAN', 'URBAN', '都市計畫區',
                                   'MainPlanNa', '計畫名稱']),
                         ('細部計畫', ['細部計畫區']),
                         ('備註', ['備註', 'Note'])],
        'source': '各直轄市／縣市政府 都市發展局（城鄉發展局）開放資料',
        'source_url': 'https://data.gov.tw/dataset/156197',
        'licence': '各該市政府開放資料授權',
        'dataset_uuid': None,
        'counties': URBAN_COUNTIES,
        'note': '各縣市自行公開的圖資，欄位與更新頻率不一致。',
        'empty_message': '此點不在都市計畫範圍內（可能屬非都市土地，見上一列）。',
        'missing_message': '尚未登錄 %s 的都市計畫分區開放資料',
    },
    'nurban_desig': {
        'title': '非都市土地使用地類別（編定）',
        'short': '類別',
        # 這份是「使用_1」（名稱）「使用地」（代碼）
        'value_fields': ['使用_1', '使用地類別', '編定名稱'],
        'code_fields': ['使用地', '編定代碼'],
        'source': '內政部國土管理署「非都市土地使用地編定圖（112年）」',
        'source_url': 'https://data.gov.tw/dataset/169539',
        'licence': '政府資料開放授權條款－第 1 版',
        'dataset_uuid': DESIG_UUID,
        'counties': DESIG_COUNTIES,
        'missing_message': '這份資料沒有 %s（該縣市全域皆為都市計畫區）',
    },
}


def service(key, county):
    """若該縣市是走即時查詢服務（而非下載圖資），回傳它的設定，否則 None。"""
    ds = DATASETS.get(key)
    if not ds:
        return None
    entry = ds['counties'].get(county)
    return entry if isinstance(entry, dict) and entry.get('service') else None


def parts(key, county):
    """回傳該縣市的 [(下載網址, 位元組數), ...]，可能不只一個檔。
    走即時查詢服務的縣市沒有可下載的檔案，回空 list。"""
    ds = DATASETS.get(key)
    if not ds:
        return []
    if isinstance(ds['counties'].get(county), dict):
        return []
    out = []
    for ref, size in ds['counties'].get(county, []):
        # 內政部的資料只記 resource id，縣市的資料直接記完整網址
        url = ref if ref.startswith('http') else MOI_DOWNLOAD.format(
            dataset=ds['dataset_uuid'], resource=ref)
        out.append((url, size))
    return out


def total_size(key, county):
    return sum(size for _, size in parts(key, county))

# ── 地籍：座標查地號 ────────────────────────────────────────────
#
# 國土測繪中心的「座標查地號」需申請介接，但部分縣市把自己的地籍圖
# 以公開 ArcGIS 服務發布，可以直接對座標做點查詢。
# 各縣市欄位命名差很多，所以每個縣市自帶欄位對照。
# 這些圖層只有段名、段碼、地號、面積等圖籍屬性，沒有所有權人等個資。

CADASTRE_COUNTIES = {
    '臺中市': {
        'service': 'arcgis', 'wkid': 102443, 'cors': True,
        'url': ('https://mcgbm.taichung.gov.tw/arcgis/rest/services'
                '/urpd_tccgupMap/MapServer/1/query'),
        'sect': ['landdesc'], 'sectcode': ['sectno'],
        'mother': ['landmon'], 'child': ['landchild'], 'town': ['zondesc'],
        'area': ['Shape.STArea()'],
        'source': '臺中市政府都市發展局 公開圖服務',
    },
    '臺北市': {
        'service': 'arcgis', 'wkid': 102443, 'cors': True,
        'url': ('https://www.historygis.udd.gov.taipei/arcgis/rest/services'
                '/Urban/Land_Dynamic/MapServer/5/query'),
        'sect': ['sect_name'], 'sectcode': ['sect_id'], 'landno': ['land_no'],
        'mother': ['land_pnum'], 'child': ['land_snum'],
        'town': ['dist_name'], 'area': ['Shape_Area'],
        'source': '臺北市政府都市發展局 公開圖服務',
    },
    '桃園市': {
        'service': 'arcgis', 'wkid': 102443, 'cors': True,
        'url': ('https://urbandatasrv.tycg.gov.tw/server/rest/services'
                '/TY_UPGIS/TYMap_SDE/MapServer/1/query'),
        # 這個圖層只給段碼不給段名，段名用國土測繪中心的點位反查補上
        'sect': [], 'sectcode': ['section'], 'landno': ['sc'], 'landno8': ['LANDNO8'],
        'area': ['Shape.STArea()'],
        'source': '桃園市政府都市發展局 公開圖服務',
    },
    '新竹市': {
        'service': 'arcgis', 'wkid': 102443, 'cors': True,
        'url': ('https://urbanmap.hccg.gov.tw/server/rest/services'
                '/Land/Land/MapServer/0/query'),
        'sect': ['SECNAME'], 'sectcode': ['SECT'], 'landno': ['LAND_NO'],
        'landno8': ['LANDNO8'], 'area': ['AREA'], 'town': ['TNAME'],
        'source': '新竹市政府都市發展處 公開圖服務',
    },
    '新竹縣': {
        'service': 'arcgis', 'wkid': 102100, 'cors': True,
        'url': ('https://imap.hchg.gov.tw/arcgis/rest/services'
                '/Tiled3857/Land3857/MapServer/1/query'),
        'sect': ['KCNT'], 'sectcode': ['AA48'], 'landno8': ['AA49'],
        'area': ['AA10'], 'office': ['UNIT'],
        'source': '新竹縣政府 智慧圖資雲 公開圖服務',
    },
    '苗栗縣': {
        'service': 'arcgis', 'wkid': 102443,
        'url': ('https://ailand.miaoli.gov.tw/server/rest/services'
                '/Dynamic/LandNo/MapServer/0/query'),
        'sect': ['KCNT'], 'sectcode': ['AA48'], 'landno8': ['AA49'],
        'landno': ['LandNo'], 'office': ['UNIT'], 'area': ['Shape.STArea()'],
        'source': '苗栗縣政府 栗智網 公開圖服務',
    },
    '彰化縣': {
        'service': 'arcgis', 'wkid': 102443, 'cors': True,
        'url': ('https://urbangis.chcg.gov.tw/arcgis/rest/services'
                '/CHCGMap/LAND/MapServer/0/query'),
        'sect': ['SECNAME'], 'sectcode': ['SECT'], 'landno': ['LAND_NO'],
        'landno8': ['LANDNO8'], 'area': ['AREA'], 'town': ['TNAME'],
        'source': '彰化縣政府 公開圖服務',
    },
}


def cadastre(county):
    return CADASTRE_COUNTIES.get(county)
