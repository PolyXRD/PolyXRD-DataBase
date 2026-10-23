#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""2026-10-20 交付库内省（只读）。

与 inspect_deliverables.py 的区别：本脚本按 --stamp 定位产物，不再硬编码
旧日期；并额外打印**两个项目探测器**的判定结果（见 probe_two_projects.py）。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

BASE = "D:/Project/XRD/PolyXRD-DataBase"
DEFAULTS = [
    ("Full", os.path.join(BASE, "3COD-Full-20261020.sqlite")),
    ("Inorg", os.path.join(BASE, "3COD-Inorg-20261020.sqlite")),
]


def ro(p: str) -> sqlite3.Connection:
    return sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="20261020")
    ap.add_argument("--dbs", nargs="*", default=None)
    a = ap.parse_args()

    dbs = DEFAULTS
    if a.stamp != "20261020" or a.dbs:
        dbs = [
            ("Full", os.path.join(BASE, f"3COD-Full-{a.stamp}.sqlite")),
            ("Inorg", os.path.join(BASE, f"3COD-Inorg-{a.stamp}.sqlite")),
        ]

    for tag, p in dbs:
        print("=" * 80)
        if not os.path.exists(p):
            print(f"[{tag}] 缺失: {p}")
            continue
        sz = os.path.getsize(p)
        print(f"[{tag}] {os.path.basename(p)}   {sz:,} B  ({sz/2**30:.2f} GiB)")

        with open(p, "rb") as f:
            head = f.read(100)
        print("  magic:", head[:16])
        if head[:15] != b"SQLite format 3":
            print("  !! 不是 SQLite 文件头")
            continue
        ps = int.from_bytes(head[16:18], "big")
        print(f"  header: page_size={ps} write_ver={head[18]} read_ver={head[19]} "
              f"reserved={head[20]} payload_frac={head[21]}")

        t0 = time.time()
        c = ro(p)
        for k in ("journal_mode", "page_size", "freelist_count", "page_count",
                  "encoding", "auto_vacuum", "synchronous"):
            try:
                print(f"  PRAGMA {k} = {c.execute('PRAGMA ' + k).fetchone()[0]}")
            except Exception as e:
                print(f"  PRAGMA {k} ERR {e}")

        objs = c.execute("SELECT type,name FROM sqlite_master "
                         "WHERE type IN ('table','index') ORDER BY type,name").fetchall()
        tabs = [n for t, n in objs if t == "table" and not n.startswith("sqlite_")]
        idxs = [n for t, n in objs if t == "index" and not n.startswith("sqlite_")]
        print("  tables :", tabs)
        print("  indexes:", idxs)

        for t in tabs:
            try:
                n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f"    {t:22s} rows={n:,}")
            except Exception as e:
                print(f"    {t:22s} ERR {e}")

        if "meta" in tabs:
            print("  meta:")
            for k, v in c.execute("SELECT key,value FROM meta ORDER BY key"):
                s = str(v)
                print(f"    {k} = {s[:150]}{' ...' if len(s) > 150 else ''}")

        # 侧车文件检查（journal / wal / shm 残留会让只读打开失败或变慢）
        for suf in ("-journal", "-wal", "-shm"):
            if os.path.exists(p + suf):
                print(f"  !! 存在侧车文件 {os.path.basename(p)+suf} "
                      f"({os.path.getsize(p+suf):,} B)")
        print(f"  (elapsed {time.time()-t0:.1f}s)")
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
