#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三方仲裁 v2：|F|² 直接按定义求，多重性 m 用"同 d 值的 hkl 计数"严格确定，
不依赖任何对称操作解析式。粉末强度 ∝ m · |F|² · LP。
对照 fastxrd 的合并输出，若逐条吻合则 fastxrd 全链路得到独立验证。"""
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WL = 1.5406


def f_of(sym, s):
    p = FX._load_params()[sym]
    a = np.array([c[0] for c in p], float)
    b = np.array([c[1] for c in p], float)
    return FX._Z[sym] - 41.78214 * s * s * float(np.sum(a * np.exp(-b * s * s)))


def build_atoms(path):
    d = parse_cif(open(path, "rb").read().decode("utf-8", "replace"))
    coords, sp_list, _ = expand_sites(d.sites, d.symops)
    at = []
    for coord, sp in zip(coords, sp_list):
        for el, occ in sp.items():
            at.append((coord, el, float(occ)))
    return d, at


def F2(at, recip, hkl):
    h, k, l = hkl
    gvec = h * recip[0] + k * recip[1] + l * recip[2]
    g = float(np.linalg.norm(gvec))
    s = g / 2.0
    re = im = 0.0
    for coord, el, occ in at:
        f = f_of(el, s) * occ
        ph = 2 * math.pi * (h * coord[0] + k * coord[1] + l * coord[2])
        re += f * math.cos(ph)
        im += f * math.sin(ph)
    return re * re + im * im, 1.0 / g, s


def lp_of(d):
    th = math.asin(min(1.0, WL / (2 * d)))
    return (1 + math.cos(2 * th) ** 2) / (math.sin(th) ** 2 * math.cos(th))


def main():
    p = os.path.join(BASE, "COD", "9", "00", "96", "9009671.cif")
    d, at = build_atoms(p)
    recip = FX.reciprocal_matrix(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
    print("用例: %s   全胞原子数=%d   a=%.4f c=%.4f" % (p, len(at), d.a, d.c))

    # --- 多重性表：枚举 hkl, 按 d 值分组计数 ---
    lim = 20
    groups = defaultdict(list)
    for h in range(-lim, lim + 1):
        for k in range(-lim, lim + 1):
            for l in range(-lim, lim + 1):
                if (h, k, l) == (0, 0, 0):
                    continue
                g = float(np.linalg.norm(h * recip[0] + k * recip[1] + l * recip[2]))
                if g <= 0:
                    continue
                dd = 1.0 / g
                if dd < 1.0:
                    continue
                groups[round(dd, 5)].append((h, k, l))
    print("已枚举 hkl 群组 %d 个（d ≥ 1.0 Å）" % len(groups))

    probes = [(1, 1, 3), (1, 1, -6), (1, 0, 4), (0, 1, 2), (3, 0, 0), (1, 1, 0)]
    print()
    print("组内逐个求 |F|² 再求和（这才是粉末强度口径；菱方居中会使同 d 组内")
    print("混有 -h+k+l≠3n 的系统消光成员，其 |F|²=0，故不能简单乘组员数）")
    print()
    print("%-12s %9s %4s %12s %10s %12s %10s"
          % ("hkl", "d(Å)", "n", "Σ|F|²", "LP", "LP·Σ|F|²", "相对(%)"))
    rows = []
    for hkl in probes:
        key = None
        f2_0, dcal, s = F2(at, recip, hkl)
        key = round(dcal, 5)
        grp = groups.get(key, [])
        if not grp:
            print("  ! %s 不在 d≥1.0 枚举范围内 (d=%.4f)" % (hkl, dcal))
            continue
        tot = 0.0
        nz = 0
        for hh in grp:
            f2h, dh, sh = F2(at, recip, hh)
            tot += f2h
            if f2h > 1e-9:
                nz += 1
        I = lp_of(dcal) * tot
        rows.append((hkl, dcal, len(grp), nz, tot, lp_of(dcal), I))
    mx = max(r[6] for r in rows) or 1.0
    for hkl, dcal, n, nz, tot, L, I in rows:
        print("%-12s %9.4f %4d %12.1f %10.4f %12.6g %9.1f%%"
              % (str(hkl), dcal, n, tot, L, I, 100.0 * I / mx))

    # --- 对照 fastxrd ---
    coords = [a[0] for a in at]
    syms = [a[1] for a in at]
    occs = [a[2] for a in at]
    ddd, iii, hkk = FX.compute_pattern_arrays(
        d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
        np.asarray(coords, dtype=float), syms, occs,
        wavelength=WL, tth_range=(5.0, 100.7609), max_hkl=30000,
        half_sphere=True, scale=1000.0, max_peaks=500, return_hkl=True)
    ddd = np.asarray(ddd, float)
    iii = np.asarray(iii, float)
    print()
    print("=== 逐峰对照（按 d 降序, 前 12 条）===")
    print("%-10s %9s %4s %10s %10s %10s" % ("hkl", "d(Å)", "非零", "直算I/1000", "fastxrd", "偏差%"))
    fxi = dict()
    for k in range(len(ddd)):
        fxi[round(float(ddd[k]), 4)] = float(iii[k])
    rows.sort(key=lambda r: -r[1])
    for hkl, dcal, n, nz, tot, L, I in rows[:12]:
        fx = fxi.get(round(dcal, 4))
        dev = ("%.2f" % (100 * (fx - I / mx * 1000) / (I / mx * 1000))) if fx else "n/a"
        print("%-10s %9.4f %4d %10.1f %10s %10s"
              % (str(hkl), dcal, nz, I / mx * 1000,
                 ("%.1f" % fx) if fx else "n/a", dev))
    print()
    print("fastxrd 前 6 强线:")
    order = np.argsort(-iii)[:6]
    for j in order:
        print("   d=%.4f  I=%6.1f  hkl=%s"
              % (ddd[j], iii[j], tuple(int(x) for x in hkk[j])))


if __name__ == "__main__":
    main()
