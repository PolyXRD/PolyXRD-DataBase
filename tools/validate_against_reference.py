#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""与 PolyXRD 官方 COD_inorganics.sqlite 直接对拍，确定峰表的权威约定。

目的
----
1) 反推官方库用的 2θ 范围与峰数上限（我们现在的 5–115°/500 峰是猜的）
2) 验证 fastcif + fastxrd 与官方峰表逐数值一致（d 与 I）
3) 确认 peaks_top_d/peaks_top_i 的编码（float64 / Top-64 / I 降序）

方法：取参考库中自带 cif_gz 的条目，解压后用自己的管线重算，与库内
peaks_d / peaks_i / peaks_top_d / peaks_top_i 逐条比对。
"""
from __future__ import annotations

import gzip
import sqlite3
import sys

import numpy as np

sys.path.insert(0, "E:/rsync-COD/tools")
from fastcif import parse_cif, expand_sites          # noqa: E402
from fastxrd import compute_pattern_arrays           # noqa: E402

REF = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"
WL = 1.5406
RANGES = [(5.0, 90.0), (5.0, 115.0), (5.0, 120.0), (10.0, 90.0)]


def main():
    c = sqlite3.connect("file:%s?mode=ro" % REF, uri=True)
    rows = c.execute(
        "SELECT cod_id, formula, space_group, cell_a, cell_b, cell_c, "
        "cell_alpha, cell_beta, cell_gamma, n_peaks, peaks_d, peaks_i, "
        "peaks_top_d, peaks_top_i, cif_gz FROM phases "
        "WHERE cif_gz IS NOT NULL AND n_peaks BETWEEN 80 AND 500 "
        "LIMIT 12").fetchall()
    print("对拍条目数: %d" % len(rows))
    print("=" * 88)
    for (cid, formula, sg, a, b, cc, al, be, ga, n_peaks, pd_, pi_,
         top_d, top_i, gz) in rows:
        d_ref = np.array([float(x) for x in pd_.split(",")])
        i_ref = np.array([float(x) for x in pi_.split(",")])
        print("\ncod_id=%s %s  sg=%s  n_peaks=%d  d范围 %.4f–%.4f Å"
              % (cid, formula, sg, n_peaks, d_ref.max(), d_ref.min()))
        # ── 解码官方 top 列 ──
        td = np.frombuffer(top_d, dtype=np.float64)
        ti = np.frombuffer(top_i, dtype=np.float64)
        # 用我们存储的峰表按官方算法重算 top，验证语义
        order = np.argsort(-i_ref, kind="stable")[:len(td)]
        td_calc, ti_calc = d_ref[order], i_ref[order]
        print("  top列: len=%d dtype=f64  I降序=%s  与重算一致=%s (maxΔd=%.2e, maxΔI=%.2e)"
              % (len(td), bool(np.all(np.diff(ti) <= 1e-9)),
                 bool(np.allclose(td, td_calc) and np.allclose(ti, ti_calc)),
                 np.abs(td - td_calc).max() if td.size else 0,
                 np.abs(ti - ti_calc).max() if ti.size else 0))

        # ── 用我们管线重算 ──
        try:
            text = gzip.decompress(gz).decode("utf-8", "replace")
        except Exception as e:                        # noqa: BLE001
            print("  CIF 解压失败: %s" % e)
            continue
        d = parse_cif(text)
        coords, sp_list, _ = expand_sites(d.sites, d.symops)
        rows_, syms, occs = [], [], []
        for coord, sp in zip(coords, sp_list):
            for el, o in sp.items():
                o = float(o)
                rows_.append(coord)
                syms.append(el)
                occs.append(min(o, 1.0) if o > 0 else 1.0)
        print("  展开位点 %d (非对称 %d)" % (len(syms), len(d.sites)))
        best = None
        for tth in RANGES:
            dd, ii = compute_pattern_arrays(
                d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                np.asarray(rows_, dtype=float), syms, occs,
                wavelength=WL, tth_range=tth, max_peaks=0, scale=1000.0,
                max_hkl=300000)
            dd = np.asarray(dd)
            ii = np.asarray(ii)
            n = min(len(dd), len(d_ref))
            if n == 0:
                print("    2θ %s → 0 峰" % (tth,))
                continue
            ddif = np.abs(dd[:n] - d_ref[:n]).max()
            idif = np.abs(ii[:n] - i_ref[:n]).max()
            print("    2θ %-12s 峰数 %4d (参考 %4d)  前%d条: maxΔd=%.2e maxΔI=%.3f"
                  % ("%g–%g" % tth, len(dd), len(d_ref), n, ddif, idif))
            if best is None or (len(dd) == len(d_ref) and ddif < best[1]):
                best = (tth, ddif, idif, len(dd))
        if best:
            print("  → 最佳匹配 2θ=%s, 峰数 %d" % (best[0], best[3]))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
