#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""交付库交叉一致性抽查（只读，索引友好查询）。

检查项：
 A. 三库 cod_id 区间分布（COD / PCOD / TCOD 偏移是否正确）
 B. formula 里带引号/异常的条数（抽样窗口 + 索引扫描）
 C. phases 的 ref_id/display_id 与 cod_id 映射是否 == 96-XXX-XXXX
 D. phases.top-64 BLOB 与 peaks 行表前 64 强是否逐值一致
 E. phases.peaks_d 与 peaks 行表 d 集合是否一致
 F. cod_atomic_sites 覆盖条数
"""
import sqlite3, sys, json

BASE = "D:/Project/XRD/PolyXRD-DataBase/"
FULL = BASE + "3COD-Full-20261015.sqlite"
INORG = BASE + "3COD-Inorg-20261016.sqlite"
ORG = BASE + "3COD-Org-20261016.sqlite"


def ro(p):
    c = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def q(c, sql, args=()):
    return c.execute(sql, args).fetchall()


print("=" * 70)
print("A. cod_id 区间分布")
for tag, p, tab in (("Full", FULL, "cod_entries"), ("Inorg", INORG, "phases"), ("Org", ORG, "phases")):
    c = ro(p)
    rows = q(c, f"""
      SELECT CASE WHEN cod_id < 20000000 THEN 'COD'
                  WHEN cod_id < 100000000 THEN 'PCOD'
                  ELSE 'TCOD' END lib,
             COUNT(*), MIN(cod_id), MAX(cod_id)
      FROM {tab} GROUP BY lib ORDER BY lib""")
    print(f"  [{tag}] " + "  ".join(f"{r[0]}={r[1]:,}({r[2]}~{r[3]})" for r in rows))
    c.close()

print("=" * 70)
print("B. formula 质量抽检")
c = ro(FULL)
n_quote = q(c, "SELECT COUNT(*) FROM cod_entries WHERE formula LIKE '\"%\"'")[0][0]
n_null = q(c, "SELECT COUNT(*) FROM cod_entries WHERE formula IS NULL OR formula=''")[0][0]
n_elem_null = q(c, "SELECT COUNT(*) FROM cod_entries WHERE elements IS NULL OR elements=''")[0][0]
print(f"  Full.cod_entries  quotes={n_quote:,}  empty_formula={n_null:,}  empty_elements={n_elem_null:,}")
c.close()
c = ro(INORG)
n_quote = q(c, "SELECT COUNT(*) FROM phases WHERE formula LIKE '\"%\"'")[0][0]
n_null = q(c, "SELECT COUNT(*) FROM phases WHERE formula IS NULL OR formula=''")[0][0]
print(f"  Inorg.phases      quotes={n_quote:,}  empty_formula={n_null:,}")
c.close()
c = ro(ORG)
n_quote = q(c, "SELECT COUNT(*) FROM phases WHERE formula LIKE '\"%\"'")[0][0]
n_null = q(c, "SELECT COUNT(*) FROM phases WHERE formula IS NULL OR formula=''")[0][0]
print(f"  Org.phases        quotes={n_quote:,}  empty_formula={n_null:,}")
c.close()

print("=" * 70)
print("C. ref_id 映射抽检（10 条）")
c = ro(INORG)
rows = q(c, "SELECT cod_id, ref_id, display_id, formula FROM phases ORDER BY cod_id LIMIT 5")
for r in rows:
    exp = "96-%s-%04d" % (str(r["cod_id"]).zfill(7)[:3], int(str(r["cod_id"]).zfill(7)[3:]))
    print(f"  {r['cod_id']:>10} ref={r['ref_id']} display={r['display_id']} expect={exp} "
          f"{'OK' if r['ref_id']==exp and r['display_id']==exp else 'MISMATCH'}  {r['formula']}")
c.close()

print("=" * 70)
print("D/E. phases CSV+BLOB 与 peaks 行表一致性（抽 5 条）")
import numpy as np
c = ro(INORG)
sample = q(c, """SELECT cod_id, ref_id, n_peaks, peaks_d, peaks_i, peaks_top_d, peaks_top_i
                 FROM phases WHERE n_peaks BETWEEN 20 AND 80 LIMIT 5""")
for r in sample:
    eid = r["ref_id"]
    rows = q(c, "SELECT d,intensity FROM peaks WHERE entry_id=? ORDER BY intensity DESC", (eid,))
    d_csv = np.array([float(x) for x in r["peaks_d"].split(",") if x.strip()])
    i_csv = np.array([float(x) for x in r["peaks_i"].split(",") if x.strip()])
    top_d = np.frombuffer(r["peaks_top_d"], dtype="<f8") if r["peaks_top_d"] else np.empty(0)
    top_i = np.frombuffer(r["peaks_top_i"], dtype="<f8") if r["peaks_top_i"] else np.empty(0)
    n = min(64, len(top_d))
    row_top = np.array([x[0] for x in rows[:n]])
    d_top64 = np.sort(d_csv)[::-1][:n]
    ok_len = len(d_csv) == r["n_peaks"] and len(i_csv) == r["n_peaks"]
    print(f"  {r['cod_id']} n_peaks={r['n_peaks']} csv={len(d_csv)} peaks_rows={len(rows)} "
          f"topBLOB={len(top_d)}B/64={len(top_d)//8} int_max={i_csv.max():.1f} "
          f"csv_len_ok={ok_len} blob_vs_rows_dmax={np.abs(np.sort(top_d)[::-1]-np.sort(row_top)).max() if n else 'na'}")
c.close()

print("=" * 70)
print("F. 原子位点覆盖")
for tag, p in (("Inorg", INORG), ("Org", ORG), ("Full", FULL)):
    c = ro(p)
    n_id = q(c, "SELECT COUNT(DISTINCT cod_id) FROM cod_atomic_sites")[0][0]
    n_rows = q(c, "SELECT COUNT(*) FROM cod_atomic_sites")[0][0]
    if tag == "Full":
        n_ent = q(c, "SELECT COUNT(*) FROM cod_entries")[0][0]
    else:
        n_ent = q(c, "SELECT COUNT(*) FROM entries")[0][0]
    print(f"  [{tag}] sites cod_id={n_id:,} rows={n_rows:,} entries={n_ent:,} "
          f"覆盖率={100.0*n_id/n_ent:.2f}% 平均位点={n_rows/max(n_id,1):.1f}")
    c.close()
