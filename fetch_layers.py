#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把全部縣市的非都市土地圖資抓下來，供 build_layers.py 轉檔。

政府開放資料的檔案不小（全部約 400 MB），而且偶爾會斷線，
所以這支程式一個一個抓、失敗就報告，可以重跑接續。
已經抓好的會直接跳過。

    python fetch_layers.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)

import datasets as DS
import start as S

KEYS = ("nurban_zone", "nurban_desig")


def main():
    todo = []
    for key in KEYS:
        for cty in sorted(DS.DATASETS[key]["counties"]):
            if not S.is_cached(key, cty):
                todo.append((key, cty))

    if not todo:
        print("全部縣市都已下載。")
        return

    print("需要下載 %d 份：" % len(todo))
    ok = fail = 0
    for key, cty in todo:
        sys.stdout.write("  %s %s … " % (cty, key))
        if S.download_dataset(key, cty):
            print("完成")
            ok += 1
        else:
            print("失敗")
            fail += 1
    print("\n下載完成 %d 份，失敗 %d 份" % (ok, fail))
    if fail:
        print("失敗的可以重跑這支程式接續，已下載的會跳過。")


if __name__ == "__main__":
    main()
