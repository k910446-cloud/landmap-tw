/* 線上版要用的 CORS 代理位址。
 *
 * 有些縣市（苗栗的地號與都市計畫、部分縣市的圖層）的服務不送 CORS 標頭，
 * 瀏覽器不准網頁直接讀。本機版有 Python 後端可以代轉，線上版沒有，
 * 所以需要一支自己的代理 —— 原始碼與部署步驟在 worker/ 資料夾。
 *
 * 部署好之後，把 Worker 的網址填到下面（結尾不要加斜線）：
 *
 *     window.PROXY_URL = 'https://landmap-proxy.你的帳號.workers.dev';
 *
 * 留空的話，需要代理的縣市會顯示「線上版查不到」，其餘功能一切正常。
 *
 * 想先試不同的代理而不改這個檔，可以在網址後面加 ?proxy=https://...
 * 這個設定只留在你自己的瀏覽器，不影響別人。
 */
window.PROXY_URL = 'https://landmap-proxy.k910446.workers.dev';

(function () {
  'use strict';
  try {
    var q = new URLSearchParams(location.search).get('proxy');
    if (q !== null) {
      if (q) localStorage.setItem('landmap.proxy', q);
      else localStorage.removeItem('landmap.proxy');
    }
    var saved = localStorage.getItem('landmap.proxy');
    if (saved) window.PROXY_URL = saved;
  } catch (e) {
    /* 無痕視窗或封鎖儲存時，就用上面寫死的預設值 */
  }
}());
