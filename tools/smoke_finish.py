#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐 Inorg/Full 双项目实开冒烟里被 timeout 打断的三项（避开全表扫描的折中版）。

背景：PolyXRD `CIFDatabase.search_cod_phases()` 的**分子式**分支写法是
`formula = ? OR formula = ? OR formula LIKE ? OR space_group LIKE ? OR ...`，
带 LIKE 就走全表扫描；在 117 万相的 22 GB 库上、又有 Org 构建抢盘时实测
>40 min 跑不完。而**编号**分支（`cod_id = ? OR display_id = ? OR ref_id = ?`）
三个条件全部走索引，秒回。

因此本驱动分两部分：
  A. 现在跑（全部索引路径，秒级）：编号检索、库内分子式过滤（直连 SQL 走
     idx_phases_formula）、CODLocalDatabase（Full 侧）、XinMatch SQL 代理。
  B. 留待 Org 构建结束后再测：`search_cod_phases("O2 Si")` 的全表扫描耗时
     （如实记入报告的「性能」项，不冒充通过）。

用法:
    QT_QPA_PLATFORM=offscreen /e/GSASII/python.exe tools/smoke_finish.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import smoke_two_projects as S  # noqa: E402


def part_a():
    stamp = "20261015"
    inorg = os.path.join(BASE, "3COD-Inorg-%s.sqlite" % stamp)
    full = os.path.join(BASE, "3COD-Full-%s.sqlite" % stamp)
    sys.path.insert(0, "E:/TEMP/PolyXRD/src")
    from polyxrd.services.cif_database import CIFDatabase

    print("\n=== PolyXRD 实开：3COD-Inorg（索引路径）===")
    db = CIFDatabase(enable_cod_local=False)
    db._cod_conn = S.open_ro(inorg)

    # 1) 编号检索：三个条件全走索引（cod_id 主键 / display_id / ref_id）。
    #    ⚠️ 只测 "96-101-1097" 这种 9 位带 96/97 前缀的写法 —— 代码里只有这个分支
    #    三个条件都带索引；纯数字写法（"1011097"）会带上 `ref_id LIKE '%…%'` 而退化成
    #    全表扫描（117 万相、有并发时 >40 min 跑不完），故不在此处测。
    for q in ("96-101-1097",):
        t0 = time.time()
        hits = db.search_cod_phases(q, limit=20)
        dt = time.time() - t0
        S.rec("search_cod_phases(%r)（索引路径）" % q, bool(hits),
              "%d 条；%.2f s" % (len(hits), dt))
        if hits:
            h = hits[0]
            print("   Top-1: cod_id=%s formula=%r sg=%r n_peaks=%s"
                  % (h.get("cod_id"), h.get("formula"), h.get("space_group"),
                     h.get("n_peaks")))

    # 2) 库内分子式过滤：直连 SQL 走 idx_phases_formula（PolyXRD 的分子式分支
    #    会全表扫描，这里用等价的索引路径证明库侧分子式检索本身是快的）
    con = S.open_ro(inorg)
    for q in ("O2 Si", "C Ca O3", "Al2 O3"):
        t0 = time.time()
        rows = con.execute("SELECT cod_id, formula, space_group, n_peaks "
                           "FROM phases WHERE formula=? LIMIT 20", (q,)).fetchall()
        dt = time.time() - t0
        S.rec("库内分子式过滤 formula=%r（idx_phases_formula）" % q, bool(rows),
              "%d 条；%.2f s" % (len(rows), dt))
    t0 = time.time()
    rows = con.execute("SELECT COUNT(*) FROM phases WHERE formula LIKE 'O2 Si%'"
                       ).fetchone()
    S.rec("分子式前缀过滤 LIKE 'O2 Si%'", rows[0] > 0,
          "%s 条；%.2f s" % (f"{rows[0]:,}", time.time() - t0))
    con.close()

    S.polyxrd_full(full)
    S.xinmatch_proxy(inorg, full)


def main():
    part_a()
    bad = [r for r in S.RESULTS if not r[1]]
    print("\n合计 %d 项，通过 %d，失败 %d" % (len(S.RESULTS), len(S.RESULTS) - len(bad),
                                            len(bad)))


if __name__ == "__main__":
    main()
