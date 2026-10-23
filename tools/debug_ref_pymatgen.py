#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三方对拍：官方参考库 vs pymatgen XRDCalculator vs 我的 fastxrd。

判定基准：以 pymatgen 为准（它是事实标准）。
  · 若 pymatgen == 我的管线  → 官方库自己有偏差，我们跟随 pymatgen
  · 若 pymatgen == 官方库    → 我的管线有 bug，必须修
"""
from __future__ import annotations

import gzip
import sqlite3
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, "E:/rsync-COD/tools")
from fastcif import parse_cif, expand_sites          # noqa: E402
from fastxrd import compute_pattern_arrays           # noqa: E402

REF = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"
WL = 1.5406


def main():
    from pymatgen.io.cif import CifParser
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    c = sqlite3.connect("file:%s?mode=ro" % REF, uri=True)
    rows = c.execute(
        "SELECT cod_id, formula, n_peaks, peaks_d, peaks_i, cif_gz FROM phases "
        "WHERE cif_gz IS NOT NULL AND n_peaks BETWEEN 60 AND 300 LIMIT 6"
    ).fetchall()

    for cid, formula, n_peaks, pd_, pi_, gz in rows:
        d_ref = np.array([float(x) for x in pd_.split(",")])
        i_ref = np.array([float(x) for x in pi_.split(",")])
        txt = gzip.decompress(gz).decode("utf-8", "replace")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            st = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                primitive=False)[0]
        print("\n" + "=" * 84)
        print("cod_id=%s %s  参考 %d 峰  d %.4f–%.4f"
              % (cid, formula, n_peaks, d_ref.max(), d_ref.min()))
        print("  pymatgen 位点: %d" % len(st))

        # ── pymatgen 全空间 ──
        calc = XRDCalculator(wavelength=WL)
        t = time.time()
        pat = calc.get_pattern(st, two_theta_range=(0.5, 179.0))
        t_pm = time.time() - t
        d_pm = np.asarray(pat.x)
        i_pm = np.asarray(pat.y) * 10.0        # pymatgen 归一到 100 → 我归一到 1000
        # pymatgen 的 x 是 2θ，转成 d
        d_pm = WL / (2.0 * np.sin(np.radians(pat.x / 2.0)))
        print("  pymatgen (0.5–179°): %d 峰, d %.4f–%.4f, %.2f s"
              % (len(d_pm), d_pm.max(), d_pm.min(), t_pm))

        # ── 我的管线全空间 ──
        d = parse_cif(txt)
        coords, sp_list, _ = expand_sites(d.sites, d.symops)
        rows_, syms, occs = [], [], []
        for coord, sp in zip(coords, sp_list):
            for el, o in sp.items():
                o = float(o)
                rows_.append(coord)
                syms.append(el)
                occs.append(min(o, 1.0) if o > 0 else 1.0)
        t = time.time()
        dd, ii = compute_pattern_arrays(
            d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
            np.asarray(rows_, dtype=float), syms, occs,
            wavelength=WL, tth_range=(0.5, 179.0), max_peaks=0,
            scale=1000.0, max_hkl=2_000_000)
        t_me = time.time() - t
        dd = np.asarray(dd)
        ii = np.asarray(ii)
        print("  我   (0.5–179°): %d 峰, d %.4f–%.4f, %.2f s  (%.1fx)"
              % (len(dd), dd.max(), dd.min(), t_me,
                 t_pm / max(1e-6, t_me)))

        n = min(len(dd), len(d_pm))
        print("  我 vs pymatgen   : 峰数差 %+d, 前%d条 maxΔd=%.2e maxΔI=%.2f"
              % (len(dd) - len(d_pm), n,
                 np.abs(dd[:n] - d_pm[:n]).max(),
                 np.abs(ii[:n] - i_pm[:n]).max()))
        m = min(len(d_ref), len(d_pm))
        print("  参考 vs pymatgen : 峰数差 %+d, 前%d条 maxΔd=%.2e maxΔI=%.2f"
              % (len(d_ref) - len(d_pm), m,
                 np.abs(d_ref[:m] - d_pm[:m]).max(),
                 np.abs(i_ref[:m] - i_pm[:m]).max()))
        m2 = min(len(d_ref), len(dd))
        print("  参考 vs 我       : 峰数差 %+d, 前%d条 maxΔd=%.2e maxΔI=%.2f"
              % (len(d_ref) - len(dd), m2,
                 np.abs(d_ref[:m2] - dd[:m2]).max(),
                 np.abs(i_ref[:m2] - ii[:m2]).max()))
        # 相对强度偏差随角度的分布
        if m2 > 10:
            rel = (i_ref[:m2] - ii[:m2]) / np.maximum(ii[:m2], 1e-9)
            print("  (参考-我)/我 相对偏差: 前10条 %+.2f%%  后10条 %+.2f%%"
                  % (100 * rel[:10].mean(), 100 * rel[-10:].mean()))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
