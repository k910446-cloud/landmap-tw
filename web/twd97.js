/* 台灣常用座標轉換 — 純函式, 無相依。
 *
 * TWD97 TM2 (EPSG:3826 台灣本島 / EPSG:3825 澎金馬) 為橫麥卡托投影:
 *   橢球 GRS80, 中央經線 121°(本島) 或 119°(澎湖/金門/馬祖),
 *   尺度 0.9999, 橫座標平移 250000。
 * TWD67 採內政部公告之近似轉換式, 誤差約數公分, 一般查詢足用。
 */
(function (g) {
  'use strict';

  var A = 6378137.0;               // GRS80 長半徑
  var F = 1 / 298.257222101;       // GRS80 扁率
  var K0 = 0.9999;
  var DX = 250000;
  var D2R = Math.PI / 180, R2D = 180 / Math.PI;

  // 澎湖、金門、馬祖使用 119° 中央經線
  function lon0For(lon, lat) {
    if (lon < 120.0) return 119;                       // 澎湖(119.3~119.7)、金門(118.2~118.5)、馬祖(119.9)
    if (lat > 26.0 && lon < 120.6) return 119;         // 馬祖東引
    return 121;
  }

  function toTM2(lat, lon, lon0deg) {
    if (lon0deg == null) lon0deg = lon0For(lon, lat);
    var e = F * (2 - F);           // e^2
    var e2 = e / (1 - e);          // e'^2
    var phi = lat * D2R, lam = lon * D2R, lam0 = lon0deg * D2R;
    var sp = Math.sin(phi), cp = Math.cos(phi), tp = Math.tan(phi);

    var V = A / Math.sqrt(1 - e * sp * sp);
    var T = tp * tp;
    var C = e2 * cp * cp;
    var a1 = (lam - lam0) * cp;
    var a2 = a1 * a1, a3 = a2 * a1, a4 = a3 * a1, a5 = a4 * a1, a6 = a5 * a1;

    var M = A * ((1 - e / 4 - 3 * e * e / 64 - 5 * e * e * e / 256) * phi
      - (3 * e / 8 + 3 * e * e / 32 + 45 * e * e * e / 1024) * Math.sin(2 * phi)
      + (15 * e * e / 256 + 45 * e * e * e / 1024) * Math.sin(4 * phi)
      - (35 * e * e * e / 3072) * Math.sin(6 * phi));

    var x = K0 * V * (a1 + (1 - T + C) * a3 / 6
      + (5 - 18 * T + T * T + 72 * C - 58 * e2) * a5 / 120) + DX;
    var y = K0 * (M + V * tp * (a2 / 2
      + (5 - T + 9 * C + 4 * C * C) * a4 / 24
      + (61 - 58 * T + T * T + 600 * C - 330 * e2) * a6 / 720));

    return { x: x, y: y, lon0: lon0deg };
  }

  function fromTM2(x, y, lon0deg) {
    if (lon0deg == null) lon0deg = 121;
    var e = F * (2 - F);
    var e2 = e / (1 - e);
    var e1 = (1 - Math.sqrt(1 - e)) / (1 + Math.sqrt(1 - e));

    var M = y / K0;
    var mu = M / (A * (1 - e / 4 - 3 * e * e / 64 - 5 * e * e * e / 256));
    var p1 = mu
      + (3 * e1 / 2 - 27 * Math.pow(e1, 3) / 32) * Math.sin(2 * mu)
      + (21 * e1 * e1 / 16 - 55 * Math.pow(e1, 4) / 32) * Math.sin(4 * mu)
      + (151 * Math.pow(e1, 3) / 96) * Math.sin(6 * mu)
      + (1097 * Math.pow(e1, 4) / 512) * Math.sin(8 * mu);

    var sp = Math.sin(p1), cp = Math.cos(p1), tp = Math.tan(p1);
    var C1 = e2 * cp * cp;
    var T1 = tp * tp;
    var N1 = A / Math.sqrt(1 - e * sp * sp);
    var R1 = A * (1 - e) / Math.pow(1 - e * sp * sp, 1.5);
    var D = (x - DX) / (N1 * K0);
    var D2 = D * D, D3 = D2 * D, D4 = D3 * D, D5 = D4 * D, D6 = D5 * D;

    var lat = p1 - (N1 * tp / R1) * (D2 / 2
      - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * e2) * D4 / 24
      + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * e2 - 3 * C1 * C1) * D6 / 720);
    var lon = lon0deg * D2R + (D - (1 + 2 * T1 + C1) * D3 / 6
      + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * e2 + 24 * T1 * T1) * D5 / 120) / cp;

    return { lat: lat * R2D, lon: lon * R2D };
  }

  // TWD97 TM2 -> TWD67 TM2 (內政部近似式)
  function tm97to67(x, y) {
    var a = 0.00001549, b = 0.000006521;
    return {
      x: x - 807.8 - a * x - b * y,
      y: y + 248.6 - a * y - b * x
    };
  }

  function tm67to97(x, y) {
    var a = 0.00001549, b = 0.000006521;
    return {
      x: x + 807.8 + a * x + b * y,
      y: y - 248.6 + a * y + b * x
    };
  }

  // 25.033964 -> 25°02'02.27"N
  function toDMS(v, posChar, negChar) {
    var sign = v < 0 ? negChar : posChar;
    v = Math.abs(v);
    var d = Math.floor(v);
    var mF = (v - d) * 60;
    var m = Math.floor(mF);
    var s = (mF - m) * 60;
    return d + '°' + String(m).padStart(2, '0') + "'" + s.toFixed(2).padStart(5, '0') + '"' + sign;
  }

  g.TWD = {
    toTM2: toTM2,
    fromTM2: fromTM2,
    tm97to67: tm97to67,
    tm67to97: tm67to97,
    toDMS: toDMS,
    lon0For: lon0For
  };
})(window);
