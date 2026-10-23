#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复现 build_3cod 峰计算 100% 失败的根因。"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAVELENGTH = 1.5406
TTH_MIN = 5.0
TTH_MAX = 100.7609

import sqlite3
con = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
for lib in ("COD", "PCOD", "TCOD"):
    rel, size = con.execute(
        "SELECT rel, size FROM files WHERE lib=? AND is_inorg=1 LIMIT 1", (lib,)).fetchone()
    path = os.path.join(BASE, lib, rel.replace("\\", "/"))
    print("=" * 70)
    print("用例:", lib, rel, size, "存在:", os.path.exists(path))
    text = open(path, "rb").read().decode("utf-8", "replace")
    try:
        d = parse_cif(text)
    except Exception:
        traceback.print_exc()
        continue
    print("  a,b,c = %s %s %s | sg=%s | nsites=%d | vol=%s"
          % (d.a, d.b, d.c, d.sg_name, len(d.sites), d.volume))
    try:
        coords, sp_list, _ = expand_sites(d.sites, d.symops)
    except Exception:
        traceback.print_exc()
        continue
    rows, syms, occs = [], [], []
    for coord, sp in zip(coords, sp_list):
        for el, o in sp.items():
            o = float(o)
            rows.append(coord)
            syms.append(el)
            occs.append(min(o, 1.0) if o > 0 else 1.0)
    print("  expanded sites =", len(rows))
    try:
        out = FX.compute_pattern_arrays(
            d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
            np.asarray(rows, dtype=float), syms, occs,
            wavelength=WAVELENGTH, tth_range=(TTH_MIN, TTH_MAX),
            max_hkl=30000, half_sphere=True, scale=1000.0,
            max_peaks=500, return_hkl=True)
        print("  OK, len(out) =", len(out))
        if len(out) == 3:
            dd, ii, hkl = out
            print("  npeaks =", len(dd), " d[:5] =", dd[:5])
    except Exception:
        traceback.print_exc()
