#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 fastxrd 与 pymatgen XRDCalculator 的峰表是否一致（峰位/强度）。"""
import gzip
import os
import random
import sqlite3
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    files = (sample("E:/rsync-COD/PCOD", 2, 25, 2, 11)
             + sample("E:/rsync-COD/COD", 3, 30, 2, 12)
             + sample("E:/rsync-COD/TCOD", 3, 15, 2, 13))

    n_cmp = 0
    worst_d = 0.0
    worst_i = 0.0
    worst_n = 0
    t_fast = 0.0
    t_pm = 0.0
    rows = []
    for fp in files:
        with open(fp, "rb") as fh:
            raw = fh.read()
        txt = raw.decode("utf-8", "replace")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                st = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                    primitive=False)[0]
        except Exception:
            continue
        t0 = time.time()
        try:
            pat = calc.get_pattern(st, two_theta_range=TTH)
        except Exception:
            continue
        t_pm += time.time() - t0
        if len(pat.x) == 0:
            continue
        # pymatgen: 归一化到 100 → 换算成 d 与相对强度
        y = [float(v) for v in pat.y]
        imax = max(y) or 1.0
        x = [float(v) for v in pat.x]
        d_pm = [WL / (2 * __import__("math").sin(__import__("math").radians(t / 2)))
                for t in x]
        i_pm = [v / imax * 1000.0 for v in y]

        t0 = time.time()
        try:
            d_fx, i_fx = compute_pattern(st, wavelength=WL, tth_range=TTH,
                                         half_sphere=True)
        except Exception as e:
            print("  fastxrd 失败 %s: %s" % (os.path.basename(fp), e))
            continue
        t_fast += time.time() - t0
        if not d_fx:
            continue

        n_cmp += 1
        dn = abs(len(d_pm) - len(d_fx))
        # 对齐比较前 min(n) 个峰
        m = min(len(d_pm), len(d_fx))
        dd = max(abs(d_pm[j] - d_fx[j]) for j in range(m)) if m else 0.0
        di = max(abs(i_pm[j] - i_fx[j]) for j in range(m)) if m else 0.0
        worst_d = max(worst_d, dd)
        worst_i = max(worst_i, di)
        worst_n = max(worst_n, dn)
        rows.append((os.path.basename(fp), len(d_pm), len(d_fx), dd, di))

    print("对比条目数: %d" % n_cmp)
    print("%-16s %8s %8s %12s %12s" % ("文件", "pm峰数", "fx峰数", "d最大偏差", "I最大偏差"))
    for r in rows[:25]:
        print("%-16s %8d %8d %12.6f %12.4f" % r)
    print("\n汇总: 峰数最大差=%d, d 最大偏差=%.6f Å, 强度最大偏差=%.4f (相对1000)"
          % (worst_n, worst_d, worst_i))
    print("耗时: pymatgen %.2f s / fastxrd %.2f s  →  加速 %.1fx"
          % (t_pm, t_fast, (t_pm / t_fast) if t_fast else 0))


if __name__ == "__main__":
    main()
