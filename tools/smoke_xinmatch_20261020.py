#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""XinMatch 原生检索冒烟（只读）。

两个交付库都被 XinMatch 的 ``detect_source`` 判为原生 ``SCHEMA_XINMATCH``，
因此不需要转侧车。本脚本直接用 XinMatch 自己的查询函数验证：

  X1  detect_source -> xinmatch，四表齐全（entries/peaks/elements/element_combo）
  X2  query_peaks.search_by_d      峰位检索（2θ 窗口模式）
  X3  query_filter.search_by_elements  元素集过滤
  X4  query_filter.search_by_formula   化学式检索
  X5  query_filter.search_combined     组合过滤
  X6  element_combo 组合索引可用性

用法:
    python tools/smoke_xinmatch_20261020.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

BASE = "D:/Project/XRD/PolyXRD-DataBase"
XIN = "D:/Project/XRD/XinMatch"
sys.path.insert(0, XIN)

DBS = [
    ("Full", os.path.join(BASE, "3COD-Full-20261020.sqlite")),
    ("Inorg", os.path.join(BASE, "3COD-Inorg-20261020.sqlite")),
]

FAIL: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAIL.append(msg)


def ro(p: str) -> sqlite3.Connection:
    c = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True,
                        timeout=120.0)
    c.row_factory = sqlite3.Row
    return c


# 石英 10 条主峰（实测 d）
QUARTZ_D = [3.3435, 4.2553, 2.4573, 2.2817, 2.2371, 2.1274, 1.9790, 1.8178,
            1.6708, 1.5418]
# 刚玉 8 条主峰
CORUNDUM_D = [2.0850, 2.5510, 1.6014, 3.4795, 2.3790, 1.5470, 2.5488, 1.4027]


def main() -> int:
    from xinmatch.core.db.polyxrd import detect_source
    from xinmatch.core.db import query_peaks as QP
    from xinmatch.core.db import query_filter as QF

    for tag, p in DBS:
        print("=" * 78)
        print(f"[{tag}] {os.path.basename(p)}")
        print("=" * 78)

        # ── X1 探测 ──
        src = detect_source(p)
        ok(src.kind == "xinmatch", f"detect_source -> {src.kind}")
        ok(src.row_count > 0, f"entries row_count = {src.row_count:,}")

        conn = ro(p)

        # ── X2 峰位检索 ──
        for name, ds in (("α-石英", QUARTZ_D), ("刚玉", CORUNDUM_D)):
            t0 = time.time()
            try:
                res = QP.search_by_d(
                    conn, ds, wavelength=1.5406, window_deg=0.3,
                    min_matches=3, max_candidates=50,
                )
            except Exception as e:  # noqa: BLE001
                ok(False, f"search_by_d({name}) 抛异常 {type(e).__name__}: {e}")
                continue
            dt = time.time() - t0
            print(f"  search_by_d({name}) -> {len(res)} 候选, {dt*1000:.0f} ms")
            # 取 Top1 的 formula 看是否是目标物相族
            if res:
                eid = res[0][0]
                f = conn.execute(
                    "SELECT formula, space_group FROM entries WHERE entry_id=?",
                    (eid,)).fetchone()
                print(f"      Top1 {eid} formula={f['formula']!r} sg={f['space_group']!r}")
            ok(len(res) > 0, f"search_by_d({name}) 有候选")

        # ── X3 元素过滤 ──
        t0 = time.time()
        try:
            ids = QF.search_by_elements(conn, ["Si", "O"])
        except Exception as e:  # noqa: BLE001
            ok(False, f"search_by_elements 抛异常 {type(e).__name__}: {e}")
            ids = []
        print(f"  search_by_elements(['Si','O']) -> {len(ids)} 条, "
              f"{(time.time()-t0)*1000:.0f} ms")
        ok(len(ids) > 0, "search_by_elements 有结果")

        # ── X4 化学式 ──
        t0 = time.time()
        try:
            ids = QF.search_by_formula(conn, "O2 Si")
        except Exception as e:  # noqa: BLE001
            ok(False, f"search_by_formula 抛异常 {type(e).__name__}: {e}")
            ids = []
        print(f"  search_by_formula('O2 Si') -> {len(ids)} 条, "
              f"{(time.time()-t0)*1000:.0f} ms")
        ok(len(ids) > 0, "search_by_formula 有结果")

        # ── X5 组合过滤 ──
        try:
            ids = QF.search_combined(conn, elements=["Si", "O"], crystal_system="trigonal")
            print(f"  search_combined(elements=Si,O + trigonal) -> {len(ids)} 条")
            ok(True, "search_combined 未崩溃")
        except Exception as e:  # noqa: BLE001
            ok(False, f"search_combined 抛异常 {type(e).__name__}: {e}")

        # ── X6 element_combo ──
        n_combo = conn.execute("SELECT COUNT(*) FROM element_combo").fetchone()[0]
        empty_combo = conn.execute(
            "SELECT COUNT(*) FROM element_combo WHERE entry_ids IS NULL "
            "OR entry_ids=''").fetchone()[0]
        print(f"  element_combo 组数={n_combo:,}  空值={empty_combo}")
        sample = conn.execute(
            "SELECT element_set_hash, substr(entry_ids,1,60) FROM element_combo LIMIT 3"
        ).fetchall()
        for r in sample:
            print(f"      {r[0]} -> {r[1]}...")
        ok(n_combo > 0 and empty_combo == 0, "element_combo 非空且无空 entry_ids")

        # ── 附加：peaks 表覆盖与 hkl ──
        n_pk = conn.execute("SELECT COUNT(*) FROM peaks").fetchone()[0]
        n_hkl = conn.execute("SELECT COUNT(*) FROM peaks WHERE h IS NOT NULL").fetchone()[0]
        print(f"  peaks 行数={n_pk:,}  hkl 非空={n_hkl:,} ({n_hkl/n_pk*100:.1f}%)")
        ok(n_hkl > 0, "peaks 带 hkl 索引")

        conn.close()
    print()
    print("=" * 78)
    if FAIL:
        print(f"结果：{len(FAIL)} 项 FAIL")
        for f in FAIL:
            print("  -", f)
        return 1
    print("结果：全部 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
