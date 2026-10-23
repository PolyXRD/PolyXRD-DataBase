#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 float32 结构因子路径相对 pymatgen 的精度损失量级。

比较口径：两边都用"不截断"(max_peaks=0) 的完整峰表逐点比对，
避免按角度截断造成的错位假象。
"""
from __future__ import annotations

import gzip
import sqlite3
import sys
import time
import warnings

import numpy as np

sys.path.insert(0, "E:/rsync-COD/tools")
from fastcif import parse_cif, expand_sites        # noqa: E402
from fastxrd import compute_pattern_arrays         # noqa: E402

REF = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"
WL = 1.5406
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def main():
    from pymatgen.io.cif import CifParser
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    c = sqlite3.connect("file:%s?mode=ro" % REF, uri=True)
    rows = c.execute(
        "SELECT cod_id, formula, n_peaks, peaks_d, cif_gz FROM phases "
        "WHERE cif_gz IS NOT NULL AND n_peaks BETWEEN 50 AND 500 LIMIT %d"
        % N).fetchall()
    md = mi = 0.0
    nn = 0
    t_me = t_pm = 0.0
    for cid, formula, n_peaks, pd_, gz in rows:
        txt = gzip.decompress(gz).decode("utf-8", "replace")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                st = CifParser.from_str(txt, occupancy_tolerance=1.2
                                        ).parse_structures(primitive=False)[0]
            except Exception:                          # noqa: BLE001
                continue
        t = time.perf_counter()
        pat = XRDCalculator(wavelength=WL).get_pattern(st,
                                                       two_theta_range=(5.0, 115.0))
        t_pm += time.perf_counter() - t
        d_pm = WL / (2.0 * np.sin(np.radians(np.asarray(pat.x) / 2.0)))
        i_pm = np.asarray(pat.y) * 10.0

        d = parse_cif(txt)
        coords, sp_list, _ = expand_sites(d.sites, d.symops)
        rr, ss, oo = [], [], []
        for co, sp in zip(coords, sp_list):
            for el, oc in sp.items():
                oc = float(oc)
                rr.append(co)
                ss.append(el)
                oo.append(min(oc, 1.0) if oc > 0 else 1.0)
        t = time.perf_counter()
        dd, ii = compute_pattern_arrays(
            d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
            np.asarray(rr, dtype=float), ss, oo,
            wavelength=WL, tth_range=(5.0, 115.0), max_peaks=0,
            scale=1000.0, max_hkl=30000)
        t_me += time.perf_counter() - t
        dd = np.asarray(dd)
        ii = np.asarray(ii)
        k = min(len(dd), len(d_pm))
        if k == 0:
            continue
        md = max(md, np.abs(dd[:k] - d_pm[:k]).max())
        mi = max(mi, np.abs(ii[:k] - i_pm[:k]).max())
        nn += 1
    print("样本 %d 条 (两边均不截断, 逐点比对)" % nn)
    print("  max|Δd| = %.3e Å" % md)
    print("  max|ΔI| = %.4f  (强度归一化到 1000)" % mi)
    print("  速度: 我 %.2f s vs pymatgen %.2f s → %.1fx"
          % (t_me, t_pm, t_pm / max(1e-9, t_me)))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
