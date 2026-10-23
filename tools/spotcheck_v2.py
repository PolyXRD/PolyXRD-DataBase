#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""2026-10-20 交付库数据完整性硬检查（只读）。

检查项与「不过就重建」的门槛对应：
  C1  phases.peaks_top_d / peaks_top_i IS NULL 计数必须为 0
      —— PolyXRD 走 BLOB 快路径时不判 NULL，为 NULL 会直接 AttributeError
  C2  peaks_top_d 长度 == 8*min(n_peaks,64)，且 peaks_top_d / peaks_top_i 等长
  C3  n_peaks 与实际 CSV 峰数一致；n_peaks=0 的条数
  C4  ref_id / display_id == '96-' + 库代号 + '-' + 7位序号
  C5  cod_id 区间分布（COD/PCOD/TCOD 偏移）
  C6  format:phase 行数守恒（entries vs phases vs peaks 覆盖的 entry 数）
  C7  cod_atomic_sites 覆盖条数
  C8  meta 关键键齐全且 variant 以 slim-index 打头

用法：
  python tools/spotcheck_v2.py --db Inorg
  python tools/spotcheck_v2.py --db Full
  python tools/spotcheck_v2.py --db both
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

BASE = "D:/Project/XRD/PolyXRD-DataBase"
PATHS = {
    "Full": os.path.join(BASE, "3COD-Full-20261020.sqlite"),
    "Inorg": os.path.join(BASE, "3COD-Inorg-20261020.sqlite"),
}


def ro(p: str) -> sqlite3.Connection:
    c = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True,
                        timeout=60.0)
    c.row_factory = sqlite3.Row
    return c


def one(c: sqlite3.Connection, sql: str, args=()):
    return c.execute(sql, args).fetchone()[0]


def check_inorg(tag: str, p: str) -> None:
    print("=" * 80)
    print(f"[{tag}] {os.path.basename(p)}  phases 深度检查")
    print("=" * 80)
    c = ro(p)

    # ── C1 NULL 门禁 ──
    t0 = time.time()
    n_tot = one(c, "SELECT COUNT(*) FROM phases")
    n_null_d = one(c, "SELECT COUNT(*) FROM phases WHERE peaks_top_d IS NULL")
    n_null_i = one(c, "SELECT COUNT(*) FROM phases WHERE peaks_top_i IS NULL")
    print(f"C1 phases 总数 = {n_tot:,}")
    print(f"   peaks_top_d IS NULL = {n_null_d:,}   "
          f"{'PASS' if n_null_d == 0 else 'FAIL !!'}")
    print(f"   peaks_top_i IS NULL = {n_null_i:,}   "
          f"{'PASS' if n_null_i == 0 else 'FAIL !!'}")
    print(f"   (elapsed {time.time()-t0:.1f}s)")

    # ── C2 BLOB 长度 ──
    t0 = time.time()
    bad_len = one(c, """
        SELECT COUNT(*) FROM phases
        WHERE LENGTH(peaks_top_d) <> 8 * MIN(n_peaks, 64)
           OR LENGTH(peaks_top_i) <> 8 * MIN(n_peaks, 64)
    """)
    bad_len2 = one(c, "SELECT COUNT(*) FROM phases "
                      "WHERE LENGTH(peaks_top_d) <> LENGTH(peaks_top_i)")
    print(f"C2 BLOB 长度不符 = {bad_len:,} {'' if bad_len==0 else 'FAIL !!'}"
          f"   两者不等长 = {bad_len2:,}")
    # 长度分布
    dist = c.execute("""
        SELECT LENGTH(peaks_top_d) len, COUNT(*) n FROM phases
        GROUP BY len ORDER BY len
    """).fetchall()
    print("   BLOB 长度分布:", ", ".join(f"{r['len']}B={r['n']:,}" for r in dist))
    print(f"   (elapsed {time.time()-t0:.1f}s)")

    # ── C3 n_peaks 与 CSV 峰数 ──
    # ⚠️ peaks_d / peaks_i 是**逗号**分隔的纯数值串（不是 'd,i;d,i'）。
    # 首版检查脚本按分号计数得出"全表不符"的假结论，务必按逗号数。
    t0 = time.time()
    n_zero = one(c, "SELECT COUNT(*) FROM phases WHERE n_peaks IS NULL OR n_peaks <= 0")
    print(f"C3 n_peaks<=0 的条数 = {n_zero:,}")
    sample = c.execute("""
        SELECT cod_id, n_peaks, peaks_d, peaks_i FROM phases
        WHERE n_peaks > 0 ORDER BY cod_id LIMIT 5
    """).fetchall()
    for r in sample:
        nd = r["peaks_d"].count(",") + 1 if r["peaks_d"] else 0
        ni = r["peaks_i"].count(",") + 1 if r["peaks_i"] else 0
        flag = "OK" if (nd == ni == r["n_peaks"]) else f"!! n_peaks={r['n_peaks']} d={nd} i={ni}"
        print(f"   cod_id={r['cod_id']} n_peaks={r['n_peaks']} "
              f"csv_d={nd} csv_i={ni}  {flag}")
    print(f"   (elapsed {time.time()-t0:.1f}s)")

    # ── C3b 全量 CSV 峰数 vs n_peaks（全表，1.18M 行只读两列，可接受）──
    t0 = time.time()
    bad = 0
    checked = 0
    for n_pk, pd, pi in c.execute("SELECT n_peaks, peaks_d, peaks_i FROM phases"):
        checked += 1
        nd = pd.count(",") + 1 if pd else 0
        ni = pi.count(",") + 1 if pi else 0
        if nd != n_pk or ni != n_pk:
            bad += 1
            if bad <= 5:
                print(f"   !! cod_id 扫描中不符: n_peaks={n_pk} d={nd} i={ni}")
    print(f"C3b 全表 {checked:,} 条中 CSV 峰数 != n_peaks 的 = {bad}")
    print(f"   (elapsed {time.time()-t0:.1f}s)")

    # ── C4 ref_id / display_id ──
    t0 = time.time()
    sample = c.execute("""
        SELECT cod_id, ref_id, display_id FROM phases
        ORDER BY cod_id LIMIT 3
    """).fetchall()
    for r in sample:
        print(f"   cod_id={r['cod_id']} ref_id={r['ref_id']} display_id={r['display_id']}")
    bad_ref = one(c, "SELECT COUNT(*) FROM phases WHERE ref_id IS NULL OR display_id IS NULL")
    print(f"C4 ref_id/display_id 为 NULL = {bad_ref:,}")
    # 抽查映射：display_id 尾 7 位应等于 (cod_id % 区段)
    for cid in (1000000, 9000001, 20000000 + 1000000, 100000000 + 1000000):
        r = c.execute("SELECT cod_id, ref_id, display_id FROM phases WHERE cod_id=?",
                      (cid,)).fetchone()
        if r:
            print(f"   映射 cod_id={cid} -> {r['ref_id']} / {r['display_id']}")
    print(f"   (elapsed {time.time()-t0:.1f}s)")

    # ── C7 atomic sites ──
    t0 = time.time()
    n_sites = one(c, "SELECT COUNT(*) FROM cod_atomic_sites")
    n_site_ids = one(c, "SELECT COUNT(DISTINCT cod_id) FROM cod_atomic_sites")
    print(f"C7 cod_atomic_sites 行={n_sites:,}  覆盖条目={n_site_ids:,}  "
          f"({n_site_ids/n_tot*100:.1f}% of phases)")
    print(f"   (elapsed {time.time()-t0:.1f}s)")

    # ── C8 meta ──
    meta = {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM meta")}
    need = ("variant", "entry_count", "schema_version", "peak_convention")
    miss = [k for k in need if k not in meta]
    print(f"C8 meta 缺失键 = {miss or '无'}")
    print(f"   variant = {meta.get('variant')}  "
          f"{'PASS(slim-index)' if str(meta.get('variant','')).startswith('slim-index') else 'FAIL !!'}")

    c.close()


def check_full(tag: str, p: str) -> None:
    print("=" * 80)
    print(f"[{tag}] {os.path.basename(p)}  cod_entries 检查")
    print("=" * 80)
    c = ro(p)

    t0 = time.time()
    n = one(c, "SELECT COUNT(*) FROM cod_entries")
    print(f"cod_entries = {n:,}")
    print(f"(elapsed {time.time()-t0:.1f}s)")

    # 区间分布
    rows = c.execute("""
        SELECT CASE WHEN cod_id < 20000000 THEN 'COD'
                    WHEN cod_id < 100000000 THEN 'PCOD'
                    ELSE 'TCOD' END lib,
               COUNT(*), MIN(cod_id), MAX(cod_id)
        FROM cod_entries GROUP BY lib ORDER BY lib
    """).fetchall()
    for r in rows:
        print(f"   {r[0]} = {r[1]:,}  ({r[2]} ~ {r[3]})")

    # parse_ok / cif_gz / elements
    t0 = time.time()
    print("parse_ok:", dict(c.execute(
        "SELECT parse_ok, COUNT(*) FROM cod_entries GROUP BY parse_ok").fetchall()))
    n_cif = one(c, "SELECT COUNT(*) FROM cod_entries WHERE cif_gz IS NOT NULL")
    print(f"cif_gz 非空 = {n_cif:,}  (slim-index 期望 0)")
    n_el = one(c, "SELECT COUNT(*) FROM cod_entries WHERE elements IS NULL OR elements=''")
    print(f"elements 为空 = {n_el:,}")
    n_f = one(c, "SELECT COUNT(*) FROM cod_entries WHERE formula IS NULL OR formula=''")
    print(f"formula 为空 = {n_f:,}")
    n_q = one(c, "SELECT COUNT(*) FROM cod_entries WHERE formula LIKE '\"%\"'")
    print(f"formula 带引号污染 = {n_q:,}")
    print(f"(elapsed {time.time()-t0:.1f}s)")

    # file 列形态
    for r in c.execute("SELECT cod_id,file FROM cod_entries ORDER BY cod_id LIMIT 3"):
        print(f"   file 样本: cod_id={r[0]} -> {r[1]!r}")

    # entries / peaks 守恒
    t0 = time.time()
    n_e = one(c, "SELECT COUNT(*) FROM entries")
    n_p = one(c, "SELECT COUNT(*) FROM peaks")
    n_pe = one(c, "SELECT COUNT(DISTINCT entry_id) FROM peaks")
    print(f"entries={n_e:,}  peaks={n_p:,}  覆盖 entry={n_pe:,}  "
          f"无峰条目={n_e-n_pe:,}")
    print(f"(elapsed {time.time()-t0:.1f}s)")

    meta = {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM meta")}
    print(f"variant = {meta.get('variant')}  entry_count = {meta.get('entry_count')}")
    c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="both", choices=("Full", "Inorg", "both"))
    ap.add_argument("--stamp", default="20261020")
    a = ap.parse_args()

    paths = {
        "Full": os.path.join(BASE, f"3COD-Full-{a.stamp}.sqlite"),
        "Inorg": os.path.join(BASE, f"3COD-Inorg-{a.stamp}.sqlite"),
    }
    if a.db in ("Inorg", "both"):
        check_inorg("Inorg", paths["Inorg"])
    if a.db in ("Full", "both"):
        check_full("Full", paths["Full"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
