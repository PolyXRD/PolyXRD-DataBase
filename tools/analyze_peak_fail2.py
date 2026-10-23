#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精确复刻 build_3cod.worker 的峰计算判据链，对随机样本分类"峰失败"的真实原因。

worker 的峰失败分支（dd 最终为 None 或长度 0）共 5 条路径：
  A 体积缺失/为 0                     → 静默跳过（无异常）
  B 胞体积 > MAX_CELL_VOL_FOR_PEAKS   → 静默跳过
  C 无原子位点                        → 静默跳过
  D 对称展开后位点数 == 0 或 > 上限    → 静默跳过
  E 计算抛异常
  F 算出 0 条峰（全落在 2θ 窗口外/全消光）
"""
import os
import random
import sqlite3
import sys
from collections import Counter
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
import build_3cod as B3  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def work(chunk):
    c = Counter()
    examples = {}
    for lib, rel in chunk:
        p = os.path.join(BASE, lib, rel.replace("\\", "/"))
        try:
            text = open(p, "rb").read().decode("utf-8", "replace")
            d = parse_cif(text)
        except Exception as e:
            c["G_读/解析异常"] += 1
            examples.setdefault("G_读/解析异常", "%s: %s" % (type(e).__name__, e))
            continue
        if not (d.a and d.b and d.c):
            c["H_晶胞参数不全"] += 1
            continue
        vol = d.volume or B.cell_volume(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
        if not vol:
            c["A_无体积"] += 1
            examples.setdefault("A_无体积", os.path.basename(p))
            continue
        if vol > B3.MAX_CELL_VOL_FOR_PEAKS:
            c["B_胞体积过大"] += 1
            examples.setdefault("B_胞体积过大", "%.0f Å³ %s" % (vol, os.path.basename(p)))
            continue
        if not d.sites:
            c["C_无原子位点"] += 1
            examples.setdefault("C_无原子位点", os.path.basename(p))
            continue
        try:
            coords, sp_list, _ = expand_sites(d.sites, d.symops)
        except Exception as e:
            c["G_对称展开异常"] += 1
            examples.setdefault("G_对称展开异常", "%s: %s" % (type(e).__name__, e))
            continue
        if not (0 < len(sp_list) <= B3.MAX_SITES_FOR_PEAKS):
            c["D_展开位点数越界"] += 1
            examples.setdefault("D_展开位点数越界",
                                "%d 位点 %s" % (len(sp_list), os.path.basename(p)))
            continue
        rows, syms, occs = [], [], []
        for coord, sp in zip(coords, sp_list):
            for el, o in sp.items():
                o = float(o)
                rows.append(coord)
                syms.append(el)
                occs.append(min(o, 1.0) if o > 0 else 1.0)
        try:
            out = FX.compute_pattern_arrays(
                d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                np.asarray(rows, dtype=float), syms, occs,
                wavelength=B3.WAVELENGTH, tth_range=(B3.TTH_MIN, B3.TTH_MAX),
                max_hkl=B3.MAX_HKL, half_sphere=True, scale=B3.SCALE,
                max_peaks=B3.TOP_POLY, return_hkl=True)
        except Exception as e:
            k = "E_异常:" + type(e).__name__
            c[k] += 1
            examples.setdefault(k, "%s: %s" % (type(e).__name__, e))
            continue
        dd = out[0] if len(out) == 3 else None
        if dd is None or len(dd) == 0:
            c["F_算出0条峰"] += 1
            examples.setdefault("F_算出0条峰", os.path.basename(p))
            continue
        c["OK_峰成功"] += 1
    return c, examples


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    random.seed(20261015)
    con = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
    rows = con.execute("SELECT lib, rel FROM files").fetchall()
    random.shuffle(rows)
    rows = rows[:n]
    print("抽样 %d 条；4 进程并行" % len(rows))
    w = 4
    chunks = [rows[i::w] for i in range(w)]
    tot = Counter()
    ex = {}
    with Pool(w) as pool:
        for c, e in pool.imap_unordered(work, chunks):
            tot.update(c)
            for k, v in e.items():
                ex.setdefault(k, v)
    print()
    for k in sorted(tot):
        print("   %-22s %6d  (%.3f%%)" % (k, tot[k], 100.0 * tot[k] / len(rows)))
    print()
    print("每类示例：")
    for k in sorted(ex):
        print("   %-22s %s" % (k, ex[k][:110]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
