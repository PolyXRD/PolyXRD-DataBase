#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐条深挖：参考库峰表 vs 我管线重算，定位 d 偏差与 2θ 范围的真实来源。"""
from __future__ import annotations

import gzip
import math
import sqlite3
import sys

import numpy as np

sys.path.insert(0, "E:/rsync-COD/tools")
from fastcif import parse_cif, expand_sites          # noqa: E402
from fastxrd import compute_pattern_arrays           # noqa: E402

REF = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"
WL = 1.5406
CIDS = sys.argv[1:] or ["1000022", "1000007"]


def d_to_tth(d):
    s = WL / (2.0 * d)
    return math.degrees(2 * math.asin(min(1.0, s)))


def main():
    c = sqlite3.connect("file:%s?mode=ro" % REF, uri=True)
    for cid in CIDS:
        r = c.execute(
            "SELECT cod_id, formula, space_group, cell_a, cell_b, cell_c, "
            "cell_alpha, cell_beta, cell_gamma, n_peaks, peaks_d, peaks_i, cif_gz "
            "FROM phases WHERE cod_id=?", (int(cid),)).fetchone()
        if not r:
            print("%s 不存在" % cid)
            continue
        (cid, formula, sg, a, b, cc, al, be, ga, n_peaks, pd_, pi_, gz) = r
        d_ref = np.array([float(x) for x in pd_.split(",")])
        i_ref = np.array([float(x) for x in pi_.split(",")])
        txt = gzip.decompress(gz).decode("utf-8", "replace")
        d = parse_cif(txt)
        print("\n" + "=" * 84)
        print("cod_id=%s %s sg=%s n_peaks=%d" % (cid, formula, sg, n_peaks))
        print("  库内晶胞 : %.4f %.4f %.4f  %.3f %.3f %.3f" % (a, b, cc, al, be, ga))
        print("  CIF 晶胞 : %.4f %.4f %.4f  %.3f %.3f %.3f"
              % (d.a, d.b, d.c, d.alpha, d.beta, d.gamma))
        print("  CIF 空间群: %r  位点(非对称) %d" % (d.sg_name, len(d.sites)))
        print("  参考 d 范围: %.4f – %.4f Å  → 2θ %.2f° – %.2f°"
              % (d_ref.max(), d_ref.min(), d_to_tth(d_ref.max()),
                 d_to_tth(d_ref.min())))
        print("  参考 d 单调降序? %s" % bool(np.all(np.diff(d_ref) <= 1e-9)))
        print("  参考尾部 12 条 d:", np.round(d_ref[-12:], 4).tolist())
        print("  参考尾部 12 条 I:", np.round(i_ref[-12:], 1).tolist())

        coords, sp_list, _ = expand_sites(d.sites, d.symops)
        rows_, syms, occs = [], [], []
        for coord, sp in zip(coords, sp_list):
            for el, o in sp.items():
                o = float(o)
                rows_.append(coord)
                syms.append(el)
                occs.append(min(o, 1.0) if o > 0 else 1.0)
        # 用极宽范围看看到底能出多少峰、最小 d 是多少
        dd, ii = compute_pattern_arrays(
            d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
            np.asarray(rows_, dtype=float), syms, occs,
            wavelength=WL, tth_range=(0.5, 179.0), max_peaks=0,
            scale=1000.0, max_hkl=2_000_000)
        dd = np.asarray(dd)
        ii = np.asarray(ii)
        print("  全空间(0.5–179°)重算: %d 峰, d %.4f–%.4f"
              % (len(dd), dd.max(), dd.min()))
        # 前 25 条逐条对比
        n = min(25, len(dd), len(d_ref))
        print("  前 %d 条对比 (参考 d / 重算 d / Δd / 参考 I / 重算 I):" % n)
        for k in range(n):
            print("    %2d  %8.4f %8.4f  %+8.4f   %8.1f %8.1f"
                  % (k + 1, d_ref[k], dd[k], dd[k] - d_ref[k],
                     i_ref[k], ii[k]))
        # 参考里有没有重算里没有的 d（说明参考含消光峰/多余峰）
        set_ref = set(np.round(d_ref, 3))
        set_cal = set(np.round(dd, 3))
        print("  仅在参考中: %s" % sorted(set_ref - set_cal)[:10])
        print("  仅在重算中: %s" % sorted(set_cal - set_ref)[:10])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
