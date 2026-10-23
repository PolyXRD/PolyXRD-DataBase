#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一结构分别用 gemmi(ASU, 不合并多重性) 与 fastxrd(按 2θ 合并等价反射) 算峰,
两边都取**强度前 N** 后归一化到 1000, 逐条对比 d 与 I, 量化口径差异。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_dbs as B  # noqa: E402
import bench_gemmi_vs_fastxrd as BG  # noqa: E402


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    topn = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    random.seed(7)
    files = BG.collect(B.PCOD_ROOT if hasattr(B, "PCOD_ROOT") else B.LIBS[1][1], 2, n * 4)
    shown = 0
    print("每条结构: gemmi(ASU) vs fastxrd(含多重性), 两边均取强度前 %d 并归一到 1000" % topn)
    print("=" * 88)
    for f in files:
        try:
            with open(f, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
        except Exception:
            continue
        g = BG.gemmi_peaks(f, max_peaks=100)
        fx = BG.fastxrd_peaks(text, max_peaks=0)
        if g is None or fx is None:
            continue
        dg, ig, hkl = g
        df, ifr = fx
        if len(dg) < topn or len(df) < topn:
            continue
        ig_n = ig / ig.max() * 1000.0
        ifr_n = ifr / ifr.max() * 1000.0
        # fastxrd 取强度前 topn
        idx = np.argsort(-ifr_n)[:topn]
        df_t, if_t = df[idx], ifr_n[idx]
        print("\n结构: %s" % os.path.basename(f))
        print("  %-4s %-10s %-10s %-10s %-10s %-8s" % ("#", "d_gemmi", "d_fastxrd", "I_gemmi", "I_fastxrd", "比值"))
        for j in range(topn):
            ratio = if_t[j] / ig_n[j] if ig_n[j] > 0 else float("nan")
            print("  %-4d %-10.4f %-10.4f %-10.1f %-10.1f %-8.2f" % (
                j + 1, dg[j], df_t[j], ig_n[j], if_t[j], ratio))
        shown += 1
        if shown >= n:
            break
    print("=" * 88)


if __name__ == "__main__":
    main()
