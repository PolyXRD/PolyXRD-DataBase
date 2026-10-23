#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读检查 PolyXRD 现有可挂载数据库的 schema 与规模，作为新库格式参照。"""
import sqlite3
import sys
import os

DBS = [
    "E:/TEMP/PolyXRD/cod_data/cod_index.sqlite",
    "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite",
    "E:/TEMP/PolyXRD/cod_data/COD_inorganics_index.sqlite",
    "E:/TEMP/PolyXRD/cod_data/PDF2_2004.sqlite",
]


def show(path):
    print("=" * 78)
    print("DB:", path)
    if not os.path.exists(path):
        print("  (不存在)")
        return
    print("  文件大小: %.2f GB" % (os.path.getsize(path) / 1024**3))
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=30)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        print("  表:", tables)
        for t in tables:
            if t.startswith("sqlite_"):
                continue
            cols = conn.execute("PRAGMA table_info(%s)" % t).fetchall()
            print("\n  --- %s (%d 列) ---" % (t, len(cols)))
            for c in cols:
                print("      %-28s %-10s notnull=%s dflt=%s pk=%s" % (
                    c[1], c[2], c[3], c[4], c[5]))
            try:
                n = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                print("      行数: %d" % n)
            except Exception as e:
                print("      行数查询失败:", e)
            idxs = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
                (t,)).fetchall()
            for nm, sql in idxs:
                if nm:
                    print("      IDX %-28s %s" % (nm, (sql or "").replace("\n", " ")[:110]))
        # meta 内容
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
            print("\n  meta:", rows[:20])
        except Exception:
            pass
    finally:
        conn.close()


if __name__ == "__main__":
    for p in DBS:
        try:
            show(p)
        except Exception as e:
            print("ERROR on %s: %s" % (p, e))
