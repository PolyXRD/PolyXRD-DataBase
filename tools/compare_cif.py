#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证：fastcif(快解析+对称展开) 与 pymatgen CifParser 得到的结构是否等价，
   以及由此算出的峰表是否与 pymatgen XRDCalculator 一致。"""
import os
import random
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastcif import parse_cif, build_structure, expand_sites  # noqa: E402
from fastxrd import compute_pattern  # noqa: E402

WL = 1.5406
TTH = (5.0, 115.0)


def sample(root, depth, n_dirs, per_dir, seed):
    rng = random.Random(seed)
    level = [("", root)]
    for _ in range(depth):
        nxt = []
        for rel, p in level:
            try:
                names = os.listdir(p)
            except OSError:
                continue
            for nm in names:
                q = os.path.join(p, nm)
                if os.path.isdir(q):
                    nxt.append((os.path.join(rel, nm) if rel else nm, q))
        level = nxt
        if not level:
            break
    rng.shuffle(level)
    out = []
    for d, p in level[:n_dirs]:
        try:
            fs = [f for f in os.listdir(p) if f.endswith(".cif")]
        except OSError:
            continue
        rng.shuffle(fs)
        out.extend(os.path.join(p, f) for f in fs[:per_dir])
    return out


def main():
    from pymatgen.io.cif import CifParser
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    calc = XRDCalculator(wavelength=WL)
    files = (sample("E:/rsync-COD/COD", 3, 20, 2, 21)
             + sample("E:/rsync-COD/PCOD", 2, 20, 2, 22)
             + sample("E:/rsync-COD/TCOD", 3, 10, 2, 23))

    n_ok = n_bad = 0
    diag = []
    pk_diag = []
    worst_natom = 0
    worst_coord = 0.0
    worst_d = 0.0
    worst_i = 0.0
    t_fast = t_pm = 0.0
    bad_cases = []

    for fp in files:
        with open(fp, "rb") as fh:
            txt = fh.read().decode("utf-8", "replace")
        t0 = time.time()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                st_pm = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                    primitive=False)[0]
        except Exception:
            continue
        try:
            pat = calc.get_pattern(st_pm, two_theta_range=TTH)
        except Exception:
            continue
        t_pm += time.time() - t0
        if len(pat.x) == 0:
            continue
        import math
        d_pm = [WL / (2 * math.sin(math.radians(float(t) / 2))) for t in pat.x]
        y = [float(v) for v in pat.y]
        imax = max(y) or 1.0
        i_pm = [v / imax * 1000.0 for v in y]

        t0 = time.time()
        d = parse_cif(txt)
        st_fx = build_structure(d)
        if st_fx is None:
            n_bad += 1
            bad_cases.append((os.path.basename(fp), "structure fail: " + d.err))
            continue
        try:
            d_fx, i_fx = compute_pattern(st_fx, wavelength=WL, tth_range=TTH,
                                         half_sphere=True, max_hkl=30000)
        except Exception as e:
            n_bad += 1
            bad_cases.append((os.path.basename(fp), "xrd fail: %s" % e))
            continue
        t_fast += time.time() - t0

        n_ok += 1
        # 结构比对
        if abs(len(st_pm) - len(st_fx)) > 0:
            diag.append((os.path.basename(fp), len(st_pm), len(st_fx),
                         d.sg_name or d.sg_number, len(d.symops), len(d.sites)))
        worst_natom = max(worst_natom, abs(len(st_pm) - len(st_fx)))
        c1 = np.sort(np.asarray(st_pm.frac_coords) % 1.0, axis=0)
        c2 = np.sort(np.asarray(st_fx.frac_coords) % 1.0, axis=0)
        m = min(len(c1), len(c2))
        if m:
            dd = float(np.abs(c1[:m] - c2[:m]).max())
            worst_coord = max(worst_coord, dd)
        # 峰表比对
        m2 = min(len(d_pm), len(d_fx))
        if m2:
            md = max(abs(d_pm[j] - d_fx[j]) for j in range(m2))
            mi = max(abs(i_pm[j] - i_fx[j]) for j in range(m2))
            worst_d = max(worst_d, md)
            worst_i = max(worst_i, mi)
            if len(d_pm) != len(d_fx) or md > 1e-6 or mi > 1.0:
                pk_diag.append((os.path.basename(fp), len(st_pm), len(st_fx),
                                len(d_pm), len(d_fx),
                                str(st_pm.composition.reduced_formula),
                                str(st_fx.composition.reduced_formula),
                                round(md, 5), round(mi, 2)))

    print("样本: %d, 成功比对: %d, fastcif 失败: %d" % (len(files), n_ok, n_bad))
    print("原子数最大差: %d" % worst_natom)
    print("分数坐标最大差: %.6f" % worst_coord)
    print("峰位 d 最大差: %.6f Å" % worst_d)
    print("峰强最大差(相对1000): %.4f" % worst_i)
    print("耗时 pymatgen %.2f s / fastcif+fastxrd %.2f s → 加速 %.1fx"
          % (t_pm, t_fast, t_pm / t_fast if t_fast else 0))
    for c in bad_cases[:15]:
        print("  失败:", c)
    print("\n峰表不一致明细 (文件, pm原子, fx原子, pm峰数, fx峰数, pm式, fx式, d差, I差):")
    for r in pk_diag[:20]:
        print("  ", r)
    print("\n原子数不一致明细 (文件, pm原子数, fx原子数, 空间群, symop数, 非对称单元原子数):")
    for r in diag[:20]:
        print("  ", r)


if __name__ == "__main__":
    import numpy as np  # noqa: E402
    main()
