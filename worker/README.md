# 讓線上版也查得到苗栗的地號

## 為什麼需要這一步

苗栗縣政府的地籍與都市計畫服務是好的，回應也正常，但它**沒有送
`Access-Control-Allow-Origin` 這個標頭**。瀏覽器的同源政策因此不准網頁
直接讀它的內容。

本機版（`啟動.bat`）不受影響，因為它有 Python 後端可以代為轉送。
但 GitHub Pages 上的線上版沒有後端，所以查苗栗會顯示「不允許瀏覽器直接連線」。

補上一支自己的代理就能解決。Cloudflare Workers 的免費方案（每天 10 萬次請求）
遠遠夠用 —— 這個 App 一次查詢只打一兩次。

**要你自己做的只有註冊帳號和按幾下**，程式碼已經寫好了。

---

## 步驟

### 1. 註冊 Cloudflare 帳號

到 <https://dash.cloudflare.com/sign-up> 用 email 註冊，免費，不需要信用卡。

### 2. 建立 Worker

1. 登入後左邊選單點 **Compute (Workers)** → **Workers & Pages**
2. 按 **Create** → **Start with Hello World!** → **Get started**
3. 名稱填 `landmap-proxy`（填別的也可以，記住就好）
4. 按 **Deploy**

### 3. 貼上程式碼

1. 部署完成後按 **Edit code**（或進去後點 **</> Edit code**）
2. 把編輯器裡原本的範例程式**全部刪掉**
3. 打開這個資料夾裡的 [`landmap-proxy.js`](landmap-proxy.js)，**全部複製貼上**
4. 按右上角 **Deploy**

### 4. 記下網址

部署後畫面上會出現類似這樣的網址：

```
https://landmap-proxy.你的帳號.workers.dev
```

把它複製起來。

### 5. 告訴 App 這個網址

打開 [`web/proxy.js`](../web/proxy.js)，把第一行改成你的網址：

```js
window.PROXY_URL = 'https://landmap-proxy.你的帳號.workers.dev';
```

存檔後推上 GitHub，等 GitHub Pages 重新部署（約一兩分鐘）就生效了。

> 想先試試看再決定要不要寫進去，可以直接在網址後面加參數：
> `https://k910446-cloud.github.io/landmap-tw/?proxy=https://landmap-proxy.你的帳號.workers.dev`
> 這個設定只留在你自己的瀏覽器，不會影響別人。

---

## 安全性：這支代理做了哪些限制

**這不是通用代理**，不會變成任何人都能拿去打任何網站的跳板。
程式裡有三道限制：

| 限制 | 說明 |
|---|---|
| 目標白名單 | 只轉送 `.gov.tw`、`.gov.taipei` 等政府網站，其他一律拒絕 |
| 來源白名單 | 只有你的 GitHub Pages 網站和本機能呼叫，別人拿不到你的免費額度 |
| 只接受 GET | 不轉送任何會改動資料的請求 |

另外還限制單次回應最大 25 MB，並讓 Cloudflare 邊緣快取一小時，
既省免費額度，使用者也更快。

**如果你的 GitHub 帳號名稱不是 `k910446-cloud`**，記得改
`landmap-proxy.js` 裡的 `ALLOWED_ORIGINS`，把你的網址加進去，否則會被自己擋掉。

---

## 這樣做完之後

| | 線上版（做代理前） | 線上版（做代理後） | 本機版 |
|---|---|---|---|
| 非都市分區／編定 | 18 縣市 | 18 縣市 | 18 縣市 |
| 法條對照 | 有 | 有 | 有 |
| 都市計畫分區 | 5 縣市 | **6 縣市**（＋苗栗） | 8 縣市 |
| 地號、面積、邊長 | 6 縣市 | **7 縣市**（＋苗栗） | 7 縣市 |

線上版的地籍涵蓋範圍就跟本機版一樣了。

都市計畫還差新北與高雄，那兩個縣市的線上版走的是下載的 SHP、
不是即時服務，跟 CORS 無關，是另一件事。

---

## 之後要停用

Cloudflare 後台把那個 Worker 刪掉，再把 `web/proxy.js` 的網址清空即可。
清空後苗栗會退回顯示「線上版查不到」，其他功能一切正常。
