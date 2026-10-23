#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 gemmi 的 StructureFactorCalculatorX 独立计算指定 hkl 的 |F|²，
与 fastxrd 的结果对照，仲裁"最强线排序"差异是 CIF 造成的还是代码造成的。"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import gemmi  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WL = 1.5406


def fastxrd_f2(path, hkl):
    text = open(path, "rb").read().decode("utf-8", "replace")
    d = parse_cif(text)
    coords, sp_list, _ = expand_sites(d.sites, d.symops)
    rows, syms, occs = [], [], []
    for coord, sp in zip(coords, sp_list):
        for el, o in sp.items():
            o = float(o)
            rows.append(coord)
            syms.append(el)
            occs.append(min(o, 1.0) if o > 0 else 1.0)
    dd, ii, hkls = FX.compute_pattern_arrays(
        d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
        np.asarray(rows, dtype=float), syms, occs,
        wavelength=WL, tth_range=(5.0, 100.7609), max_hkl=30000,
        half_sphere=False, scale=1000.0, max_peaks=200000, return_hkl=True)
    want = tuple(hkl)
    for k, h in enumerate(hkls):
        if (int(h[0]), int(h[1]), int(h[2])) in (want, tuple(-x for x in want)):
            return float(ii[k]), float(dd[k])
    return None, None


def gemmi_f2(path, hkl):
    ss = gemmi.read_small_structure(path)
    ss.setup_cell_images()
    cell = ss.cell
    sfc = gemmi.StructureFactorCalculatorX(cell)
    f = sfc.calculate_sf_from_small_structure(ss, hkl)
    d = cell.calculate_d(hkl)
    return float(f.real ** 2 + f.imag ** 2), float(d)


def main():
    cifs = [
        ("COD 刚玉 9009671", "COD/9/00/96/9009671.cif"),
        ("COD 石英 1011172", "COD/1/01/11/1011172.cif"),
        ("COD 方解石 9000095", "COD/9/00/00/9000095.cif"),
    ]
    probes = {
        "COD 刚玉 9009671": [(1, 1, 3), (1, 1, -6), (1, 0, -4), (0, 1, 2)],
        "COD 石英 1011172": [(0, 1, 1), (0, 1, 0), (1, 1, -2)],
        "COD 方解石 9000095": [(0, 1, -4), (1, 1, -6), (1, 0, -8)],
    }
    for label, rel in cifs:
        p = os.path.join(BASE, rel.replace("/", os.sep))
        if not os.path.exists(p):
            # 兜底：从清单里按名字找
            import sqlite3
            con = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
            nm = os.path.basename(rel)
            r = con.execute("SELECT lib, rel FROM files WHERE rel LIKE ?",
                            ("%" + nm,)).fetchone()
            if not r:
                print(label, "找不到 CIF")
                continue
            p = os.path.join(BASE, r[0], r[1].replace("\\", "/"))
        print("=" * 72)
        print(label, "->", p)
        for hkl in probes[label]:
            try:
                gf2, gd = gemmi_f2(p, hkl)
            except Exception as e:
                print("  gemmi %s 失败: %s" % (hkl, e))
                continue
            fi2, fd = fastxrd_f2(p, hkl)
            note = ""
            if fi2 is None:
                note = "(fastxrd 该 hkl 不在表中)"
            else:
                ratio = fi2 / gf2 if gf2 else float("nan")
                note = "I_f/I_g = %.4f  Δd = %.2e Å" % (ratio, abs(fd - gd))
            print("  hkl %-12s d_gemmi=%.4f d_fast=%.4f  |F|²_g=%.6g |F|²_f=%.6g  %s"
                  % (str(hkl), gd, fd if fd else float("nan"), gf2,
                     fi2 if fi2 else float("nan"), note))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
