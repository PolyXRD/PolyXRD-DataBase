#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速内省三个交付库：文件头/PRAGMA/表清单/行数/meta。只读打开，不做重查询。"""
import os, sqlite3, sys, time

DBS = [
    ("Full", "D:/Project/XRD/PolyXRD-DataBase/3COD-Full-20261015.sqlite"),
    ("Inorg", "D:/Project/XRD/PolyXRD-DataBase/3COD-Inorg-20261016.sqlite"),
    ("Org", "D:/Project/XRD/PolyXRD-DataBase/3COD-Org-20261016.sqlite"),
]

for tag, p in DBS:
    print("=" * 78)
    print(f"[{tag}] {os.path.basename(p)}  {os.path.getsize(p):,} B")
    with open(p, "rb") as f:
        head = f.read(100)
    print("  magic:", head[:16])
    if head[:15] != b"SQLite format 3":
        print("  !! 不是 SQLite 文件头")
        continue
    page_size = int.from_bytes(head[16:18], "big")
    print(f"  header page_size={page_size} write_ver={head[18]} read_ver={head[19]} payload_frac={head[21]}")
    uri = "file:" + p.replace("\\", "/") + "?mode=ro"
    t0 = time.time()
    con = sqlite3.connect(uri, uri=True)
    for k in ("journal_mode", "page_size", "freelist_count", "page_count", "encoding", "auto_vacuum"):
        try:
            print(f"  PRAGMA {k} = {con.execute('PRAGMA '+k).fetchone()[0]}")
        except Exception as e:
            print(f"  PRAGMA {k} ERR {e}")
    objs = con.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','index') ORDER BY type,name").fetchall()
    tabs = [n for t, n in objs if t == "table"]
    idxs = [n for t, n in objs if t == "index"]
    print("  tables:", tabs)
    print("  indexes:", idxs)
    for t in tabs:
        if t.startswith("sqlite_"):
            continue
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"    {t:22s} rows={n:,}")
        except Exception as e:
            print(f"    {t:22s} ERR {e}")
    if "meta" in tabs:
        print("  meta:")
        for k, v in con.execute("SELECT key,value FROM meta"):
            print(f"    {k} = {str(v)[:120]}")
    print(f"  (elapsed {time.time()-t0:.1f}s)")
    con.close()
