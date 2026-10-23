#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽样验证 phases 的 top-64 BLOB 与 peaks 行表逐值一致（只读）。

PolyXRD 在 ``max_ref_peaks <= 64`` 时只读 ``peaks_top_d/i`` BLOB，完全绕过
``peaks_d/i`` 与 peaks 行表。因此 BLOB 一旦错位，检索结果会静默出错。

检查（随机抽样 + 定点抽样各若干条）：
  S1 BLOB 长度 == 8*min(n_peaks,64)
  S2 BLOB 的 d 值（float64 小端）= peaks 行表按 intensity 降序的前 min(n,64) 个 d
  S3 BLOB 的 i 值单调不增（按强度降序存）
  S4 BLOB 的 d 值集合 ⊆ phases.peaks_d 的 d 集合

用法:
    python tools/spotcheck_blob_20261020.py --n 300
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import struct
import sys

BASE = "D:/Project/XRD/PolyXRD-DataBase"
DB = os.path.join(BASE, "3COD-Inorg-20261020.sqlite")


def ro(p: str) -> sqlite3.Connection:
    c = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True,
                        timeout=120.0)
    c.row_factory = sqlite3.Row
    return c


def entry_id_of(cod_id: int) -> str:
    s = str(int(cod_id)).zfill(7)
    return "96-%s-%s" % (s[:3], s[3:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--db", default=DB)
    a = ap.parse_args()

    c = ro(a.db)
    # 随机抽样：ROWID 取模避免 ORDER BY RANDOM() 全表排序
    rows = c.execute("""
        SELECT cod_id, n_peaks, peaks_d, peaks_i, peaks_top_d, peaks_top_i
        FROM phases
        WHERE cod_id % 4021 = 0
        LIMIT ?
    """, (a.n,)).fetchall()
    print(f"抽样 {len(rows)} 条（cod_id % 4021 == 0）")

    bad_len = bad_d = bad_mono = bad_subset = 0
    for r in rows:
        cid = r["cod_id"]
        npk = r["n_peaks"]
        bd = r["peaks_top_d"]
        bi = r["peaks_top_i"]
        exp_len = 8 * min(npk, 64)
        if len(bd) != exp_len or len(bi) != exp_len:
            bad_len += 1
            if bad_len <= 3:
                print(f"  !! len cod_id={cid} n={npk} "
                      f"len(d)={len(bd)} len(i)={len(bi)} 期望 {exp_len}")
            continue
        d_blob = list(struct.unpack("<%dd" % (len(bd) // 8), bd))
        i_blob = list(struct.unpack("<%dd" % (len(bi) // 8), bi))

        # S3 强度单调不增
        if any(i_blob[k] < i_blob[k + 1] - 1e-9 for k in range(len(i_blob) - 1)):
            bad_mono += 1

        # S2 与 peaks 行表比对
        pk = c.execute(
            "SELECT d, intensity FROM peaks WHERE entry_id=? "
            "ORDER BY intensity DESC LIMIT ?", (entry_id_of(cid), min(npk, 64))
        ).fetchall()
        if pk:
            d_ref = [float(p["d"]) for p in pk]
            i_ref = [float(p["intensity"]) for p in pk]
            if len(d_ref) != len(d_blob):
                bad_d += 1
                if bad_d <= 3:
                    print(f"  !! 行数不符 cod_id={cid} blob={len(d_blob)} "
                          f"peaks={len(d_ref)}")
            else:
                dm = max(abs(x - y) for x, y in zip(d_blob, d_ref))
                im = max(abs(x - y) for x, y in zip(i_blob, i_ref))
                if dm > 0.001 or im > 0.01:
                    bad_d += 1
                    if bad_d <= 3:
                        print(f"  !! 值不符 cod_id={cid} maxΔd={dm:.6f} maxΔi={im:.4f}")

        # S4 BLOB d 集合 ⊆ CSV d 集合
        csv_d = [float(x) for x in r["peaks_d"].split(",")] if r["peaks_d"] else []
        s_csv = set(round(x, 4) for x in csv_d)
        miss = [x for x in d_blob if round(x, 4) not in s_csv]
        if miss:
            bad_subset += 1
            if bad_subset <= 3:
                print(f"  !! BLOB d 不在 CSV cod_id={cid} 例: {miss[:3]}")
        if npk <= 64 and len(csv_d) != len(d_blob):
            print(f"  !! n<=64 但 CSV 与 BLOB 行数不同 cod_id={cid} "
                  f"csv={len(csv_d)} blob={len(d_blob)}")

    print()
    print("=" * 70)
    print(f"S1 长度不符      : {bad_len}")
    print(f"S2 与 peaks 不符 : {bad_d}")
    print(f"S3 强度非单调    : {bad_mono}")
    print(f"S4 d 不在 CSV 中 : {bad_subset}")
    verdict = "PASS" if (bad_len == bad_d == bad_mono == bad_subset == 0) else "FAIL"
    print(f"结论: {verdict}")
    c.close()
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
