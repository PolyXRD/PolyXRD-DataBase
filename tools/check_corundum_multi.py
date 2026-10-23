#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多刚玉 CIF 交叉核对 (113)/(116) 强度排序是否稳定 —— 判别 CIF 伪差 vs 系统偏差。"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
rows = con.execute(
    "SELECT rel FROM files WHERE lib='COD' AND is_inorg=1 AND elements='Al,O' "
    "AND formula_red='Al2O3' ORDER BY size LIMIT 600").fetchall()
print("候选 %d 个（按 size 前 600 逐个试，取晶胞符合刚玉的前 6 个）" % len(rows))
n = 0
for (rel,) in rows:
    p = os.path.join(BASE, "COD", rel.replace("\\", "/"))
    try:
        text = open(p, "rb").read().decode("utf-8", "replace")
        d = parse_cif(text)
        if not (d.a and d.b and d.c):
            continue
        if abs(d.a - 4.7541) > 0.02 or abs(d.c - 12.9901) > 0.06:
            continue
        coords, sp_list, _ = expand_sites(d.sites, d.symops)
        if not (20 <= len(coords) <= 40):
            continue
        R, S, O = [], [], []
        for c, sp in zip(coords, sp_list):
            for el, o in sp.items():
                o = float(o)
                R.append(c)
                S.append(el)
                O.append(min(o, 1.0) if o > 0 else 1.0)
        dd, ii, hk = FX.compute_pattern_arrays(
            d.a, d.b, d.c, d.alpha, d.beta, d.gamma, np.asarray(R), S, O,
            wavelength=1.5406, tth_range=(5.0, 100.7609), max_hkl=30000,
            half_sphere=True, scale=1000.0, max_peaks=500, return_hkl=True)
        if not len(dd):
            continue
        top = sorted(zip(dd, ii, hk), key=lambda t: -t[1])[:4]
        print("%-20s a=%.4f c=%.4f | " % (os.path.basename(rel), d.a, d.c)
              + "  ".join("d=%.4f I=%5.1f %d%d%d"
                          % (x[0], x[1], x[2][0], x[2][1], x[2][2]) for x in top))
        n += 1
        if n >= 6:
            break
    except Exception:
        continue
print("共核对 %d 个刚玉 CIF" % n)
