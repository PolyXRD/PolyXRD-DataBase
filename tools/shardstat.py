#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看 _parts 下各分片的行数 / 续跑标记 / 体积，用于估算构建进度。"""
from __future__ import annotations

import glob
import os
import sqlite3


def main():
    tot = 0
    rows = []
    for p in sorted(glob.glob("E:/rsync-COD/_parts/p*_full.sqlite")):
        n, done = -1, "-"
        try:
            c = sqlite3.connect("file:%s?mode=ro" % p.replace("\\", "/"),
                                uri=True, timeout=5)
            n = c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
            try:
                d = c.execute(
                    "SELECT value FROM meta WHERE key='shard_done'").fetchone()
                done = d[0] if d else "-"
            except sqlite3.Error as e:
                done = "ERR"
            c.close()
        except sqlite3.Error:
            pass
        rows.append((os.path.basename(p), n, done, os.path.getsize(p) / 1e6))
        if n > 0:
            tot += n
    for nm, n, done, mb in rows:
        print("  %-22s rows=%-9s done=%-4s %7.0f MB" % (nm, n, done, mb))
    print("合计已入库条目: %d" % tot)
    print("--- 活跃 tmp 分片 ---")
    for p in sorted(glob.glob("E:/rsync-COD/_parts/*.tmp")):
        print("  %-26s %7.0f MB" % (os.path.basename(p), os.path.getsize(p) / 1e6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
