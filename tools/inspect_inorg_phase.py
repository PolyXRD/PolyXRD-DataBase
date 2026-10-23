#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看 COD_inorganics.sqlite 的 phases 样例数据格式（峰表/ID 字段编码方式）。"""
import sqlite3

DB = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"

conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT cod_id, formula, space_group, cell_a, cell_b, cell_c, cell_alpha, "
    "cell_beta, cell_gamma, n_peaks, substr(peaks_d,1,80) AS d80, "
    "substr(peaks_i,1,80) AS i80, record_offset, record_size, ref_id, display_id, "
    "length(cif_gz) AS gz_len, typeof(peaks_top_d) AS td_type "
    "FROM phases ORDER BY cod_id LIMIT 5").fetchall()
for r in rows:
    print("-" * 70)
    for k in r.keys():
        print("  %-14s = %r" % (k, r[k]))

print("\n=== 统计 ===")
print("总相数:", conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0])
print("n_peaks 分布: min/avg/max =", conn.execute(
    "SELECT MIN(n_peaks), AVG(n_peaks), MAX(n_peaks) FROM phases").fetchone()[:])
print("peaks_d 为空:", conn.execute(
    "SELECT COUNT(*) FROM phases WHERE peaks_d IS NULL OR peaks_d=''").fetchone()[0])
print("cif_gz 非空:", conn.execute(
    "SELECT COUNT(*) FROM phases WHERE cif_gz IS NOT NULL").fetchone()[0])
print("peaks_top_d 非空:", conn.execute(
    "SELECT COUNT(*) FROM phases WHERE peaks_top_d IS NOT NULL").fetchone()[0])
print("ref_id 样例:", conn.execute(
    "SELECT ref_id, display_id FROM phases LIMIT 5").fetchall())
print("cod_id 范围:", conn.execute(
    "SELECT MIN(cod_id), MAX(cod_id) FROM phases").fetchone()[:])

# 原子位点样例
print("\n=== cod_atomic_sites 样例 ===")
for r in conn.execute("SELECT * FROM cod_atomic_sites LIMIT 5"):
    print("  ", tuple(r))

# 取一条有 cif_gz 的，看压缩内容开头
r = conn.execute(
    "SELECT cod_id, cif_gz FROM phases WHERE cif_gz IS NOT NULL LIMIT 1").fetchone()
if r:
    import gzip
    txt = gzip.decompress(r["cif_gz"]).decode("utf-8", "replace")
    print("\n=== cif_gz 解压开头 (cod_id=%s, 长度 %d 字节) ===" % (r["cod_id"], len(txt)))
    print(txt[:600])
conn.close()
