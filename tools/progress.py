#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询构建进度：统计各分片已写入的条目数，推算吞吐与剩余时间。"""
from __future__ import annotations

import glob
import os
import sqlite3
import sys
import time

TOTAL_FILES = 1_654_588
START = float(sys.argv[1]) if len(sys.argv) > 1 else None


def main():
    rows = []
    tot = 0
    for p in sorted(glob.glob("E:/rsync-COD/_parts/p*_full.sqlite")):
        sz = os.path.getsize(p)
        if sz < 5_000_000:
            continue
        try:
            c = sqlite3.connect("file:%s?mode=ro" % p.replace("\\", "/"),
                                uri=True, timeout=5)
            k = c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
            c.close()
        except sqlite3.Error as e:
            rows.append((os.path.basename(p), -1, sz, str(e)[:40]))
            continue
        rows.append((os.path.basename(p), k, sz, ""))
        tot += k
    for nm, k, sz, err in rows:
        print("  %-22s %9d 行  %7.0f MB %s" % (nm, k, sz / 1e6, err))
    print("已完成条目: %d / %d  (%.2f%%)"
          % (tot, TOTAL_FILES, 100.0 * tot / TOTAL_FILES))
    if START:
        el = time.time() - START
        rate = tot / max(1e-9, el)
        print("用时 %.0f s, 吞吐 %.1f 条目/s, 预计剩余 %.1f h"
              % (el, rate, (TOTAL_FILES - tot) / max(1e-9, rate) / 3600))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
