#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 15,398 条「峰失败」逐条归类（精确复刻 build_3cod.worker 的判据链）。

输入 sync_logs/sync20261019/peak_fail_20261020.txt（cod_id<TAB>相对路径）。
输出：每类计数 + 每类 2 个示例 + 可修复性结论。

判据链（与 worker 一致）：
  H_晶胞参数不全      d.a/d.b/d.c 有缺失
  A_无体积           volume 为 0
  B_胞体积过大        > MAX_CELL_VOL_FOR_PEAKS
  C_无原子位点        d.sites 空
  G_对称展开异常      expand_sites 抛异常
  D_展开位点数越界    0 < n <= MAX_SITES_FOR_PEAKS 不满足
  E_异常:类型         compute_pattern_arrays 抛异常（含元素符号污染）
  F_算出0条峰         全落在 2θ 窗口外或全消光
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
import build_3cod as B3  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402


def work(chunk):
    c = Counter()
    ex: dict[str, str] = {}
    for cid, rel in chunk:
        p = os.path.join(BASE, rel.replace("\\", "/").replace("/", os.sep))
        try:
            text = open(p, "rb").read().decode("utf-8", "replace")
            d = parse_cif(text)
        except FileNotFoundError:
            c["Z_文件缺失"] += 1
            ex.setdefault("Z_文件缺失", rel)
            continue
        except Exception as e:  # noqa: BLE001
            c["G_解析异常"] += 1
            ex.setdefault("G_解析异常", f"{cid} {type(e).__name__}: {e}")
            continue

        if not (d.a and d.b and d.c):
            c["H_晶胞参数不全"] += 1
            ex.setdefault("H_晶胞参数不全", f"{cid} a={d.a} b={d.b} c={d.c}")
            continue
        vol = d.volume or B.cell_volume(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
        if not vol:
            c["A_无体积"] += 1
            ex.setdefault("A_无体积", f"{cid}")
            continue
        if vol > B3.MAX_CELL_VOL_FOR_PEAKS:
            c["B_胞体积过大"] += 1
            ex.setdefault("B_胞体积过大", f"{cid} {vol:.0f} A^3")
            continue
        if not d.sites:
            c["C_无原子位点"] += 1
            ex.setdefault("C_无原子位点", f"{cid} formula={getattr(d,'formula','')!r}")
            continue
        try:
            coords, sp_list, _ = expand_sites(d.sites, d.symops)
        except Exception as e:  # noqa: BLE001
            c["G_对称展开异常"] += 1
            ex.setdefault("G_对称展开异常", f"{cid} {type(e).__name__}: {e}")
            continue
        if not (0 < len(sp_list) <= B3.MAX_SITES_FOR_PEAKS):
            c["D_展开位点数越界"] += 1
            ex.setdefault("D_展开位点数越界", f"{cid} {len(sp_list)} 位点")
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
        except Exception as e:  # noqa: BLE001
            k = "E_异常:" + type(e).__name__
            c[k] += 1
            ex.setdefault(k, f"{cid} {e}")
            # 额外记录"元素符号污染"这一类
            msg = str(e)
            if "散射因子" in msg or "scattering" in msg.lower():
                c["E1_元素符号不在表内"] += 1
                bad = msg.split(":")[-1].strip().strip("'\"")
                ex.setdefault("E1_元素符号不在表内", f"{cid} {msg}")
            continue
        dd = out[0] if len(out) == 3 else out
        if dd is None or len(dd) == 0:
            c["F_算出0条峰"] += 1
            ex.setdefault("F_算出0条峰", f"{cid}")
            continue
        c["OK_实际能算（构建时失败）"] += 1
        ex.setdefault("OK_实际能算（构建时失败）", f"{cid}")
    return c, ex


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--list", default=os.path.join(
        BASE, "sync_logs", "sync20261019", "peak_fail_20261020.txt"))
    a = ap.parse_args()

    items = []
    with open(a.list, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln:
                continue
            cid, rel = ln.split("\t", 1)
            items.append((int(cid), rel))
    print(f"待归类 {len(items):,} 条，{a.workers} 进程")

    w = a.workers
    chunks = [items[i::w] for i in range(w)]
    tot = Counter()
    ex: dict[str, str] = {}
    with Pool(w) as pool:
        for c, e in pool.imap_unordered(work, chunks):
            tot.update(c)
            for k, v in e.items():
                ex.setdefault(k, v)

    print()
    print("=" * 78)
    print("峰失败归类")
    print("=" * 78)
    for k in sorted(tot):
        print(f"  {k:<28} {tot[k]:>7,}  ({100.0*tot[k]/len(items):5.2f}%)")
    print()
    print("每类示例：")
    for k in sorted(ex):
        print(f"  {k:<28} {ex[k][:130]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
