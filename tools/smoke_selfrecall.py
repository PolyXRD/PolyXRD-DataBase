#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PolyXRD 检索的**自洽性**检验（比手抄 ICDD 峰更能定位问题）。

思路：从交付库里取一个真实条目，用**它自己的** peaks_d / peaks_i 作为
"实测谱"去检索，看它自己能否排进前列。若不能，说明是库内峰数据或检索
参数的问题；若能，说明库本身没问题，之前 Top1 不中只是手抄参考峰的容差
设置过宽。

用法:
    python tools/smoke_selfrecall.py --db Inorg --ids 1011097,1011029,1010360
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

BASE = "D:/Project/XRD/PolyXRD-DataBase"
POLY = "D:/Project/XRD/PolyXRD/src"
INORG = os.path.join(BASE, "3COD-Inorg-20261020.sqlite")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, POLY)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="1011097,1011029,1010360")
    ap.add_argument("--tol", type=float, default=0.02)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--max-ref", type=int, default=40)
    ap.add_argument("--nmeas", type=int, default=10, help="取前 N 强峰当实测谱")
    a = ap.parse_args()

    ids = [int(x) for x in a.ids.split(",") if x.strip()]

    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase(enable_cod_local=False)
    conn = sqlite3.connect("file:" + INORG.replace("\\", "/") + "?mode=ro",
                           uri=True, timeout=120.0)
    conn.row_factory = sqlite3.Row
    db._cod_conn = conn

    for cid in ids:
        row = conn.execute(
            "SELECT cod_id, formula, space_group, n_peaks, peaks_d, peaks_i "
            "FROM phases WHERE cod_id=?", (cid,)).fetchone()
        if row is None:
            print(f"cod_id={cid} 不在库中，跳过")
            continue
        ds = [float(x) for x in row["peaks_d"].split(",")]
        is_ = [float(x) for x in row["peaks_i"].split(",")]
        pairs = sorted(zip(is_, ds), reverse=True)[:a.nmeas]
        meas_i = [p[0] for p in pairs]
        meas_d = [p[1] for p in pairs]
        print("=" * 76)
        print(f"cod_id={cid} formula={row['formula']!r} sg={row['space_group']!r} "
              f"n_peaks={row['n_peaks']}")
        print(f"  实测谱(前{a.nmeas}强): d={[round(x,4) for x in meas_d]}")
        print(f"                       i={[round(x,1) for x in meas_i]}")
        t0 = time.time()
        res = db.search_cod_by_d_peaks(
            measured_d=meas_d, measured_i=meas_i,
            tolerance=a.tol, min_match=3, limit=a.topk,
            max_ref_peaks=a.max_ref,
        )
        dt = time.time() - t0
        rank = next((i + 1 for i, r in enumerate(res)
                     if int(r.get("cod_id", -1)) == cid), None)
        print(f"  检索 {len(res)} 条, {dt:.1f} s, 自身排名 = "
              f"{rank if rank else '未进前 ' + str(a.topk)}")
        for i, r in enumerate(res[:5]):
            mark = "  <== 自身" if int(r.get("cod_id", -1)) == cid else ""
            print(f"    #{i+1} cod_id={r.get('cod_id')} formula={r.get('formula')!r} "
                  f"sg={r.get('space_group')!r} score={r.get('score', 0):.4f}{mark}")

    conn.close()
    db._cod_conn = None
    return 0


if __name__ == "__main__":
    sys.exit(main())
