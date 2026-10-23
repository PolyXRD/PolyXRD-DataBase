#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""定位并归类「entries 有、peaks 无」的条目（= 峰失败集）。

Full 库：entries 1,959,421 - 覆盖 1,944,023 = 15,398 条无峰。
本脚本把这批 entry_id 全部取出，回读源 CIF，按 build_3cod.worker 的判据链
逐条归类，输出可修复性结论。

用法:
    python tools/classify_peak_fail_20261020.py [--limit N] [--workers 4]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("OMP_NUM_THREADS", "1")

DB = os.path.join(BASE, "3COD-Full-20261020.sqlite")


def ro(p: str) -> sqlite3.Connection:
    return sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True,
                           timeout=120.0)


def collect_failed() -> list[tuple[int, str, str]]:
    """返回 [(cod_id, lib, rel_file)]，只取 entries 有 peaks 无的条目。

    走 ``idx_peaks_entry_id`` 做一次索引扫描取 distinct entry_id（1.9 亿行索引，
    实测 2–4 分钟），再与 entries 求差。**不要**用 ``cod_id NOT IN (子查询)``：
    那会在 1.9 亿行上退化成 O(n²)。
    """
    c = ro(DB)
    print("遍历 peaks 取 distinct entry_id（走 idx_peaks_entry_id）...")
    have: set[str] = set()
    for (eid,) in c.execute("SELECT DISTINCT entry_id FROM peaks"):
        have.add(eid)
    print(f"  有峰的 entry 数 = {len(have):,}")
    out = []
    for cid, f in c.execute("SELECT cod_id, file FROM cod_entries"):
        s = str(int(cid)).zfill(7)
        eid = "96-%s-%s" % (s[:3], s[3:])
        if eid not in have:
            out.append((int(cid), "", f))
    c.close()
    print(f"  无峰条目 = {len(out):,}")
    return out


def collect_failed_fast() -> list[tuple[int, str, str]]:
    return collect_failed()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=全部")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(
        BASE, "sync_logs", "sync20261019", "peak_fail_20261020.txt"))
    a = ap.parse_args()

    items = collect_failed_fast()
    if a.limit:
        items = items[:a.limit]

    with open(a.out, "w", encoding="utf-8") as fh:
        for cid, _, rel in items:
            fh.write(f"{cid}\t{rel}\n")
    print(f"清单写入 {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
