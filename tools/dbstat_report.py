#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按表/索引统计三个库的实际占据字节（dbstat），输出 CSV + 控制台摘要。
只读打开；顺序扫描，单进程，避免机械盘争抢。"""
import os, sqlite3, sys, time, csv

DBS = [
    ("Full", "D:/Project/XRD/PolyXRD-DataBase/3COD-Full-20261015.sqlite"),
    ("Inorg", "D:/Project/XRD/PolyXRD-DataBase/3COD-Inorg-20261016.sqlite"),
    ("Org", "D:/Project/XRD/PolyXRD-DataBase/3COD-Org-20261016.sqlite"),
]
OUT = "D:/Project/XRD/PolyXRD-DataBase/sync_logs/dbstat_20261019.csv"
rows = []
for tag, p in DBS:
    print(f"[{tag}] {os.path.basename(p)} ...", flush=True)
    t0 = time.time()
    con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True)
    try:
        cur = con.execute("SELECT name, SUM(pgsize) AS b, COUNT(*) AS n FROM dbstat GROUP BY name ORDER BY b DESC")
        agg = {}
        for name, b, n in cur:
            # 归并到"表"或"索引归属表"
            if name.startswith("sqlite_autoindex_") or name.startswith("sqlite_stat"):
                key = name
            else:
                key = name
            agg[key] = (b, n)
        tot = 0
        for name, (b, n) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            rows.append([tag, name, b, n])
            tot += b
        print(f"  dbstat total {tot:,} B  ({time.time()-t0:.1f}s)")
    except Exception as e:
        print("  ERR", e, flush=True)
    con.close()

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["db", "object", "bytes", "pages"])
    w.writerows(rows)
print("written", OUT, flush=True)
