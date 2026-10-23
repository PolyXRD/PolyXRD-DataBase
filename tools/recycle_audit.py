#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""清点 E:\$RECYCLE.BIN 的回收项（只读，不删除任何东西）

注意：PowerShell 的 Get-ChildItem 在回收站上会因“拒绝访问”被
-ErrorAction SilentlyContinue 静默吞掉，得出“0 个文件”的假结论；
本脚本以管理员权限直接枚举，才拿到真实数字。
"""
from __future__ import annotations

import os
import time

GiB = 1024.0 ** 3
BASE = "E:/" + chr(36) + "RECYCLE.BIN"


def dir_size(path: str):
    tot = 0
    n = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return tot, n


def main():
    rows = []
    for sid in os.listdir(BASE):
        d = os.path.join(BASE, sid)
        if not os.path.isdir(d):
            continue
        try:
            ents = list(os.scandir(d))
        except OSError as exc:
            print("skip %s (%s)" % (sid, exc))
            continue
        for e in ents:
            if not e.name.startswith(chr(36) + "R"):
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            if st.st_mode & 0o040000:
                tot, n = dir_size(e.path)
            else:
                tot, n = st.st_size, 1
            rows.append((tot, n, e.name, st.st_mtime))
    rows.sort(reverse=True)
    print("回收项 %d 个，合计 %.2f GiB" % (len(rows), sum(r[0] for r in rows) / GiB))
    for b, n, name, mt in rows[:30]:
        print("%10.2f GiB  %6d 子文件  %s  %s"
              % (b / GiB, n, time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)), name))


if __name__ == "__main__":
    main()
