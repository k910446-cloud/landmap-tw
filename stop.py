#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""停止背景執行的伺服器。讀 start.py 寫下的 .server.pid，把那個行程關掉。"""

import os
import signal
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, ".server.pid")


def main():
    if not os.path.isfile(PID_FILE):
        print("找不到 .server.pid —— 伺服器應該沒有在跑。")
        return
    try:
        pid = int(open(PID_FILE, encoding="utf-8").read().strip())
    except (ValueError, OSError):
        print("PID 檔內容有問題，直接刪掉。")
        os.remove(PID_FILE)
        return

    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=20)
        else:
            os.kill(pid, signal.SIGTERM)
        print("已停止伺服器（PID %d）。" % pid)
    except Exception as e:
        print("停止失敗：%r" % (e,))
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
