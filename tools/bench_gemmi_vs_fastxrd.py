#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gemmi(规范 §5 口径) vs fastxrd(现行, pymatgen 等价) 双口径实测。

目的:
  1. 量化两者的**强度口径差异** —— gemmi 用 ReciprocalAsu 去重(不合并多重性),
     fastxrd/pymatgen 按 2θ 合并等价反射(含多重性), 归一化后相对强度会不同;
  2. 量化**速度**, 判断 165 万条目用 gemmi 三重 Python 循环是否可行。
"""
from __future__ import annotations

import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import gemmi  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

WL = 1.5406
DMIN = 1.0
# d >= 1.0 Å 对应的最大 2θ
TTH_MAX = math.degrees(2.0 * math.asin(min(1.0, WL / (2.0 * DMIN))))
TTH_MIN = 5.0
SCALE = 1000.0


def gemmi_peaks(path: str, max_peaks: int = 100, dmin: float = DMIN):
    """规范 §5 口径: gemmi ReciprocalAsu + StructureFactorCalculatorX(逐 hkl 三重循环)"""
    try:
        ss = gemmi.read_small_structure(str(path))
    except Exception:
        return None
    if ss.cell is None or ss.spacegroup is None:
        return None
    try:
        ss.setup_cell_images()
    except Exception:
        return None
    cell = ss.cell
    try:
        hmax, kmax, lmax = cell.get_hkl_limits(dmin)
    except Exception:
        return None
    if hmax <= 0 or kmax <= 0 or lmax <= 0:
        return None
    asu = gemmi.ReciprocalAsu(ss.spacegroup)
    sfc = gemmi.StructureFactorCalculatorX(cell)
    acc = {}
    for h in range(-hmax, hmax + 1):
        for k in range(-kmax, kmax + 1):
            for ell in range(-lmax, lmax + 1):
                hkl = (h, k, ell)
                try:
                    d = cell.calculate_d(hkl)
                except Exception:
                    continue
                if not np.isfinite(d) or d < dmin:
                    continue
                if not asu.is_in(hkl):
                    continue
                try:
                    f = sfc.calculate_sf_from_small_structure(ss, hkl)
                    f2 = float(f.real ** 2 + f.imag ** 2)
                except Exception:
                    continue
                if f2 <= 0.0:
                    continue
                theta = math.asin(min(1.0, WL / (2.0 * d)))
                s = math.sin(theta)
                c = math.cos(theta)
                if s <= 0.0 or c <= 0.0:
                    continue
                # 2θ 下限 5° 对齐 fastxrd 的 tth_range
                if math.degrees(2 * theta) < TTH_MIN:
                    continue
                lp = (1.0 + math.cos(2.0 * theta) ** 2) / (s * s * c)
                acc[hkl] = f2 * lp
    if not acc:
        return None
    items = sorted(acc.items(), key=lambda kv: -kv[1])[:max_peaks]
    d_arr = np.array([cell.calculate_d(hkl) for hkl, _ in items], dtype=np.float64)
    i_arr = np.array([v for _, v in items], dtype=np.float64)
    hkl_arr = np.array([hkl for hkl, _ in items], dtype=np.int64)
    return d_arr, i_arr, hkl_arr


def fastxrd_peaks(text: str, max_peaks: int = 500):
    """fastxrd: 对称展开 + 向量化 |F|², 按 2θ 合并等价反射(含多重性)"""
    d = parse_cif(text)
    if not (d.ok and d.a and d.b and d.c):
        return None
    vol = d.volume or B.cell_volume(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
    if vol > B.MAX_CELL_VOL_FOR_PEAKS:
        return None
    coords, sp_list, _ = expand_sites(d.sites, d.symops)
    if not len(sp_list) or len(sp_list) > B.MAX_SITES_FOR_PEAKS:
        return None
    rows, syms, occs = [], [], []
    for coord, sp in zip(coords, sp_list):
        for el, o in sp.items():
            o = float(o)
            rows.append(coord)
            syms.append(el)
            occs.append(min(o, 1.0) if o > 0 else 1.0)
    dd, ii = FX.compute_pattern_arrays(
        d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
        np.asarray(rows, dtype=float), syms, occs,
        wavelength=WL, tth_range=(TTH_MIN, TTH_MAX),
        max_hkl=B.MAX_HKL, half_sphere=True, scale=SCALE,
        max_peaks=max_peaks)
    if not len(dd):
        return None
    return np.asarray(dd, dtype=float), np.asarray(ii, dtype=float)


def compare(dg, ig, df, ifr, topn=20):
    """比较两条卡的峰: 返回 (max|Δd|, 匹配率, 平均相对强度偏差, 排序一致率)"""
    ig_n = ig / ig.max() * SCALE if len(ig) else ig
    ifr_n = ifr / ifr.max() * SCALE if len(ifr) else ifr
    # fastxrd 输出 d 降序; gemmi 输出强度降序 -> 统一按 d 降序
    dg_s = dg[np.argsort(-dg)]
    ig_s = ig_n[np.argsort(-dg)]
    df_s = df[np.argsort(-df)]
    if_s = ifr_n[np.argsort(-df)]
    # 按 d 匹配
    devs = []
    for d_, i_ in zip(dg_s, ig_s):
        j = int(np.argmin(np.abs(df_s - d_)))
        if abs(df_s[j] - d_) <= 0.002:
            devs.append(abs(i_ - if_s[j]) / max(i_, 1e-9))
    dtop = float(np.abs(dg_s[:topn] - df_s[:min(topn, len(df_s))]).max()) \
        if min(topn, len(df_s)) else float("nan")
    # 前 N 强线的集合重合度(按 d, 容差 0.002)
    g_top = set(np.round(dg_s[:topn], 3))
    f_top = set(np.round(df_s[:topn], 3))
    overlap = len(g_top & f_top) / max(len(g_top), 1)
    return dtop, (len(devs) / max(len(dg_s), 1)), (float(np.mean(devs)) if devs else float("nan")), overlap


def collect(root: str, depth: int, n: int):
    pool = []
    for rel, abs_dir in B.list_dirs(root, depth):
        try:
            names = [x for x in os.listdir(abs_dir) if x.lower().endswith(".cif")]
        except OSError:
            continue
        if names:
            pool.append((abs_dir, names))
    random.shuffle(pool)
    out = []
    for abs_dir, names in pool:
        random.shuffle(names)
        for nm in names[:3]:
            out.append(os.path.join(abs_dir, nm))
            if len(out) >= n:
                return out
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    random.seed(20261015)
    print("d 截断: %.2f Å  →  2θ ∈ [%.1f°, %.2f°]" % (DMIN, TTH_MIN, TTH_MAX))
    print("库     样本  gemmi ms/条  fastxrd ms/条  加速比  max|Δd|前20  匹配率  平均相对强度偏差  前20线重合度")
    tg_all, tf_all = [], []
    for lib, root, depth, _off in B.LIBS[:2]:
        files = collect(root, depth, n)
        rows = []
        for f in files:
            try:
                with open(f, "rb") as fh:
                    text = fh.read().decode("utf-8", "replace")
            except Exception:
                continue
            t0 = time.perf_counter()
            g = gemmi_peaks(f)
            tg = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            fx = fastxrd_peaks(text)
            tf = (time.perf_counter() - t0) * 1000
            if g is None or fx is None:
                continue
            dg, ig, _hk = g
            df, ifr = fx
            if len(dg) < 5 or len(df) < 5:
                continue
            dtop, match, dev, ov = compare(dg, ig, df, ifr)
            rows.append((tg, tf, dtop, match, dev, ov))
        if not rows:
            print("%-5s 无有效样本" % lib)
            continue
        mg = sum(r[0] for r in rows) / len(rows)
        mf = sum(r[1] for r in rows) / len(rows)
        md = max(r[2] for r in rows)
        mm = sum(r[3] for r in rows) / len(rows)
        mv = sum(r[4] for r in rows if not math.isnan(r[4])) / len(rows)
        mo = sum(r[5] for r in rows) / len(rows)
        tg_all += [r[0] for r in rows]
        tf_all += [r[1] for r in rows]
        print("%-5s   %2d  %10.1f  %13.1f  %6.1fx  %11.4f  %6.1f%%  %14.1f%%  %11.1f%%" % (
            lib, len(rows), mg, mf, mg / max(mf, 1e-9), md, mm * 100, mv * 100, mo * 100))
    if tg_all:
        print("---")
        print("总体: gemmi %.1f ms/条, fastxrd %.1f ms/条 → fastxrd 快 %.1f 倍" % (
            sum(tg_all) / len(tg_all), sum(tf_all) / len(tf_all),
            (sum(tg_all) / len(tg_all)) / max(sum(tf_all) / len(tf_all), 1e-9)))
        nent = 1_654_588
        for name, tv in (("gemmi", sum(tg_all) / len(tg_all)), ("fastxrd", sum(tf_all) / len(tf_all))):
            h = nent * tv / 1000.0 / 3600.0
            print("  165 万条目 × %s: 单线程 %.1f h, 6 进程并行 %.1f h" % (name, h, h / 6))


if __name__ == "__main__":
    main()
