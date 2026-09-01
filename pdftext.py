#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 PDF 取出帶座標的文字。只用標準函式庫。

為什麼要自己寫
--------------
非都市土地「哪一種使用地能做什麼」訂在《非都市土地使用管制規則》附表一，
法規資料庫只提供 PDF。這個 App 的原則是條文一律取自官方來源、不憑印象寫，
所以得把那份 PDF 的表格內容解出來。

專案本身不裝任何第三方套件（使用者只要有 Python 就能跑），所以這裡自己
處理 PDF 的物件、串流解壓與 CID 字型的 ToUnicode 對照表。

做得到與做不到
--------------
做得到：取出每個文字片段與它的 x/y 座標，據此還原「列」與「欄」。
做不到：沒有文字層的掃描檔（那種只有圖），本程式會直接回報取不到文字，
        不會硬猜。
"""

import re
import sys
import zlib


# ── PDF 物件 ────────────────────────────────────────────────
def parse_objects(data):
    """回傳 {物件編號: (字典區原文, 串流位元組或 None)}。"""
    objs = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", data, re.S):
        num = int(m.group(1))
        body = m.group(3)
        sm = re.search(rb"stream\r?\n(.*?)\r?\nendstream", body, re.S)
        stream = None
        if sm:
            raw = sm.group(1)
            head = body[:sm.start()]
            if b"FlateDecode" in head:
                try:
                    stream = zlib.decompress(raw)
                except zlib.error:
                    try:
                        stream = zlib.decompressobj().decompress(raw)
                    except zlib.error:
                        stream = None
            else:
                stream = raw
            body = head
        objs[num] = (body, stream)
    return objs


def object_streams(objs):
    """PDF 1.5 之後物件可能包在 ObjStm 裡，一併展開。"""
    out = {}
    for num, (body, stream) in list(objs.items()):
        if b"/ObjStm" not in body or not stream:
            continue
        n = int(re.search(rb"/N\s+(\d+)", body).group(1))
        first = int(re.search(rb"/First\s+(\d+)", body).group(1))
        header = stream[:first].split()
        for i in range(n):
            onum = int(header[2 * i])
            off = int(header[2 * i + 1])
            end = int(header[2 * i + 3]) + first if i + 1 < n else len(stream)
            out[onum] = (stream[first + off:end], None)
    return out


# ── ToUnicode CMap ─────────────────────────────────────────
def parse_cmap(data):
    """把 bfchar / bfrange 解成 {碼: 字元}。"""
    cmap = {}
    text = data.decode("latin-1", "replace")

    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            cmap[int(src, 16)] = _utf16(dst)

    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        # <lo> <hi> <dst>
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            base = int(dst, 16)
            for i in range(int(lo, 16), int(hi, 16) + 1):
                cmap[i] = chr(base + i - int(lo, 16))
        # <lo> <hi> [ <d1> <d2> ... ]
        for lo, hi, arr in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", block, re.S):
            items = re.findall(r"<([0-9A-Fa-f]+)>", arr)
            for i, dst in enumerate(items):
                cmap[int(lo, 16) + i] = _utf16(dst)
    return cmap


def _utf16(hexstr):
    b = bytes.fromhex(hexstr if len(hexstr) % 2 == 0 else "0" + hexstr)
    try:
        return b.decode("utf-16-be")
    except UnicodeDecodeError:
        return ""


# ── 內容串流 ────────────────────────────────────────────────
_TOKEN = re.compile(rb"""
    (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<str>\((?:\\.|[^\\()])*\))
  | (?P<num>-?\d+\.?\d*)
  | (?P<name>/[^\s/\[\]<>()]+)
  | (?P<op>[A-Za-z'"*]+)
  | (?P<arr>[\[\]])
""", re.X)


def extract_page(content, fonts):
    """回傳 [(x, y, 文字), ...]。座標是文字矩陣的位移量。"""
    out = []
    stack = []
    tm = [1, 0, 0, 1, 0, 0]
    tlm = list(tm)
    font = None
    leading = 0.0

    def emit(pieces):
        if not pieces:
            return
        txt = "".join(pieces)
        if txt.strip():
            out.append((round(tm[4], 1), round(tm[5], 1), txt))

    for m in _TOKEN.finditer(content):
        kind = m.lastgroup
        tok = m.group()
        if kind in ("num",):
            stack.append(float(tok))
        elif kind in ("hex", "str", "name", "arr"):
            stack.append(tok)
        elif kind == "op":
            op = tok.decode("latin-1")
            if op == "Tf" and len(stack) >= 2:
                nm = stack[-2]
                if isinstance(nm, bytes):
                    font = fonts.get(nm.decode("latin-1")[1:])
            elif op == "Tm" and len(stack) >= 6:
                tm = [float(v) for v in stack[-6:]]
                tlm = list(tm)
            elif op in ("Td", "TD") and len(stack) >= 2:
                tlm[4] += float(stack[-2])
                tlm[5] += float(stack[-1])
                if op == "TD":
                    leading = -float(stack[-1])
                tm = list(tlm)
            elif op == "T*":
                tlm[5] -= leading
                tm = list(tlm)
            elif op == "TL" and stack:
                leading = float(stack[-1])
            elif op == "BT":
                tm = [1, 0, 0, 1, 0, 0]
                tlm = list(tm)
            elif op in ("Tj", "TJ", "'", '"'):
                pieces = []
                for item in stack:
                    if isinstance(item, bytes) and item[:1] == b"<":
                        pieces.append(decode_hex(item, font))
                    elif isinstance(item, bytes) and item[:1] == b"(":
                        pieces.append(decode_lit(item, font))
                emit(pieces)
            stack = []
    return out


def decode_hex(tok, font):
    h = re.sub(rb"\s", b"", tok[1:-1]).decode("latin-1")
    if len(h) % 2:
        h += "0"
    raw = bytes.fromhex(h)
    return decode_bytes(raw, font)


def decode_lit(tok, font):
    body = tok[1:-1]
    body = re.sub(rb"\\([nrtbf()\\])", lambda m: {
        b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
        b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}[m.group(1)], body)
    return decode_bytes(body, font)


def decode_bytes(raw, font):
    cmap = (font or {}).get("cmap")
    two = (font or {}).get("two", True)
    if not cmap:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    out = []
    if two:
        for i in range(0, len(raw) - 1, 2):
            out.append(cmap.get((raw[i] << 8) | raw[i + 1], ""))
    else:
        for b in raw:
            out.append(cmap.get(b, ""))
    return "".join(out)


# ── 對外 ────────────────────────────────────────────────────
def page_texts(path):
    """回傳每一頁的 [(x, y, 文字), ...]。"""
    with open(path, "rb") as f:
        data = f.read()
    objs = parse_objects(data)
    objs.update(object_streams(objs))

    # 字型 → ToUnicode
    cmaps = {}
    for num, (body, _s) in objs.items():
        if b"/Font" not in body:
            continue
        tm = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if not tm:
            continue
        tgt = objs.get(int(tm.group(1)))
        if tgt and tgt[1]:
            cmaps[num] = {
                "cmap": parse_cmap(tgt[1]),
                "two": b"/Identity" in body or b"Type0" in body,
            }

    def fonts_of(body):
        """這個資源字典裡的字型代號 → ToUnicode 對照表。"""
        out = {}
        res = re.search(rb"/Font\s*<<(.*?)>>", body, re.S)
        if res:
            for nm, ref in re.findall(rb"/([^\s/]+)\s+(\d+)\s+0\s+R", res.group(1)):
                f = cmaps.get(int(ref))
                if f:
                    out[nm.decode("latin-1")] = f
        # /Font 指向另一個物件的情況
        ref = re.search(rb"/Font\s+(\d+)\s+0\s+R", body)
        if ref:
            o = objs.get(int(ref.group(1)))
            if o:
                for nm, r2 in re.findall(rb"/([^\s/]+)\s+(\d+)\s+0\s+R", o[0]):
                    f = cmaps.get(int(r2))
                    if f:
                        out[nm.decode("latin-1")] = f
        return out

    def refs_in(body, key):
        out = []
        for cm in re.finditer(key + rb"\s+(?:(\d+)\s+0\s+R|\[(.*?)\])", body, re.S):
            if cm.group(1):
                out.append(int(cm.group(1)))
            else:
                out += [int(r) for r in re.findall(rb"(\d+)\s+0\s+R", cm.group(2))]
        return out

    def collect(body, stream, depth=0):
        """一個頁面或表單的文字。表單（XObject）會遞迴進去。

        這份附表的內容整個包在 Form XObject 裡，頁面本身只有一個 /XObject
        參照 —— 不遞迴的話什麼都取不到。
        """
        if depth > 4:
            return []
        items = []
        fonts = fonts_of(body)
        if stream:
            items += extract_page(stream, fonts)
        xo = re.search(rb"/XObject\s*<<(.*?)>>", body, re.S)
        names = []
        if xo:
            names = [int(r) for _n, r in
                     re.findall(rb"/([^\s/]+)\s+(\d+)\s+0\s+R", xo.group(1))]
        else:
            ref = re.search(rb"/XObject\s+(\d+)\s+0\s+R", body)
            if ref:
                o = objs.get(int(ref.group(1)))
                if o:
                    names = [int(r) for _n, r in
                             re.findall(rb"/([^\s/]+)\s+(\d+)\s+0\s+R", o[0])]
        for n in names:
            o = objs.get(n)
            if o and b"/Form" in o[0]:
                items += collect(o[0], o[1], depth + 1)
        return items

    # 頁面順序要照 /Pages 的 /Kids 走，物件編號跟閱讀順序無關 ——
    # 照編號排的話這份附表的標題頁會跑到最後面
    def page_order():
        roots = [n for n, (b, _s) in objs.items()
                 if b"/Type" in b and b"/Pages" in b and b"/Parent" not in b]
        order = []
        seen = set()

        def walk(num, depth=0):
            if num in seen or depth > 12:
                return
            seen.add(num)
            o = objs.get(num)
            if not o:
                return
            body = o[0]
            if b"/Kids" in body:
                km = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
                if km:
                    for r in re.findall(rb"(\d+)\s+0\s+R", km.group(1)):
                        walk(int(r), depth + 1)
            elif b"/Page" in body:
                order.append(num)

        for r in roots:
            walk(r)
        if not order:      # 找不到樹就退回照編號
            order = [n for n, (b, _s) in sorted(objs.items())
                     if b"/Page" in b and b"/Pages" not in b]
        return order

    pages = []
    for num in page_order():
        body, stream = objs[num]
        if b"/Page" not in body or b"/Pages" in body:
            continue
        contents = b""
        for r in refs_in(body, rb"/Contents"):
            o = objs.get(r)
            if o and o[1]:
                contents += o[1] + b"\n"
        pages.append(collect(body, contents))
    return pages


def rows_of(items, ytol=3.0):
    """把同一列（y 相近）的片段收在一起，並依 x 由左到右排。"""
    rows = []
    for x, y, t in sorted(items, key=lambda v: (-v[1], v[0])):
        if rows and abs(rows[-1][0] - y) <= ytol:
            rows[-1][1].append((x, t))
        else:
            rows.append((y, [(x, t)]))
            rows[-1] = (y, rows[-1][1])
    return [(y, sorted(cells)) for y, cells in rows]


if __name__ == "__main__":
    for i, page in enumerate(page_texts(sys.argv[1]), 1):
        print("── 第 %d 頁（%d 個片段）" % (i, len(page)))
        for y, cells in rows_of(page)[:40]:
            print("  %8.1f | %s" % (y, "  ".join(t for _x, t in cells))[:200])
        if i >= int(sys.argv[2] if len(sys.argv) > 2 else 2):
            break
