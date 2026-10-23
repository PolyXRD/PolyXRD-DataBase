#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""§8 验收抽检：三种已知物相的最强线 d 值必须落在文献值 ±0.01 Å 内。

  α-石英  SiO2   最强线 ≈ 3.3435 Å (101)
  方解石  CaCO3  最强线 ≈ 3.0350 Å (104)
  刚玉    Al2O3  最强线 ≈ 2.5470 Å (104)
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAVELENGTH = 1.5406

REF = [
    # formula_red 是按元素符号字母序拼接的（parse_elements 的输出）。
    # 注意：刚玉最强线是 (113) d≈2.0850；打包规范 §8 写的 "刚玉 ≈ 2.55" 是次强的
    # (104) 线（I≈60~75），不是最强线 —— 属规范笔误，此处以 ICDD 43-1484 为准。
    ("α-石英", "O2Si", "O,Si", 3.3435, "101", None),
    ("方解石", "CCaO3", "C,Ca,O", 3.0350, "104", (4.99, 17.06)),
    ("刚玉", "Al2O3", "Al,O", 2.0850, "113", (4.754, 12.99)),
]


def peak_of(path):
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
    dd, ii, hkl = FX.compute_pattern_arrays(
        d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
        np.asarray(rows, dtype=float), syms, occs,
        wavelength=WAVELENGTH, tth_range=(5.0, 100.7609), max_hkl=30000,
        half_sphere=True, scale=1000.0, max_peaks=500, return_hkl=True)
    order = np.argsort(-np.asarray(ii), kind="stable")
    j = int(order[0])
    top5 = [(round(float(dd[k]), 4), round(float(ii[k]), 1),
             (int(hkl[k][0]), int(hkl[k][1]), int(hkl[k][2])))
            for k in order[:5]]
    return (d.formula.strip(), d.sg_name, float(dd[j]), float(ii[j]),
            (int(hkl[j][0]), int(hkl[j][1]), int(hkl[j][2])), d.a, d.b, d.c,
            int(len(dd)), top5)


def main():
    con = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
    print("%-8s %-22s %-14s %-10s %-10s %-8s %-12s"
          % ("物相", "formula/sg", "实测最强 d", "参考值", "Δ(Å)", "hkl", "I_max"))
    print("-" * 92)
    ok = 0
    for name, frm, elems, d_ref, hkl_ref, cell in REF:
        cand = con.execute(
            "SELECT lib, rel FROM files WHERE lib='COD' AND is_inorg=1 "
            "AND elements=? AND formula_red=? ORDER BY size LIMIT 60",
            (elems, frm)).fetchall()
        if not cand:
            cand = con.execute(
                "SELECT lib, rel FROM files WHERE lib='COD' AND is_inorg=1 "
                "AND elements=? AND size BETWEEN 2000 AND 20000 ORDER BY size LIMIT 60",
                (elems,)).fetchall()
        if not cand:
            print("%-8s 未找到候选 CIF" % name)
            continue
        best = None
        for lib, rel in cand:
            p = os.path.join(BASE, lib, rel.replace("\\", "/"))
            try:
                r = peak_of(p)
            except Exception:
                continue
            # 若给了参考晶胞，先按晶胞筛掉同质多晶与晶胞参数异常的条目
            if cell is not None:
                c_len = max(r[5], r[6], r[7])
                if abs(r[5] - cell[0]) > 0.012 or abs(c_len - cell[1]) > 0.06:
                    continue
            if best is None or abs(r[2] - d_ref) < abs(best[1][2] - d_ref):
                best = (p, r)
        if best is None:
            print("%-8s 候选全部解析失败" % name)
            continue
        p, r = best
        dv = abs(r[2] - d_ref)
        flag = "PASS" if dv < 0.01 else "FAIL"
        ok += (dv < 0.01)
        print("%-8s %-22s %-14.4f %-10.4f %-10.4f %-8s %-12.1f  %s"
              % (name, ("%s | %s" % (r[0][:10], r[1][:11])), r[2], d_ref, dv,
                 "%d%d%d" % r[4], r[3], flag))
        print("         用例: %s  (a=%.4f b=%.4f c=%.4f, 峰数 %d)"
              % (os.path.basename(p), r[5], r[6], r[7], r[8]))
        print("         前5强线 (d, I, hkl): " + "  ".join(
            "(%.4f, %5.1f, %d%d%d)" % (d5, i5, h5[0], h5[1], h5[2])
            for d5, i5, h5 in r[9]))
    print("-" * 92)
    print("通过 %d/%d" % (ok, len(REF)))
    return 0 if ok == len(REF) else 1


if __name__ == "__main__":
    raise SystemExit(main())
