#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A/B 对比 v3 (fs 全量预算, 循环外) vs v4 (fs 分块计算, 循环内) 的结构因子内环。

两者唯一区别: fs / w_all 的计算时机与 dtype (re/im 累加 f64 vs f32)。
同一进程交替计时, 消除后台构建负载的漂移影响。
"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import fastxrd as FX  # noqa: E402
import build_dbs as B  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402


def bench_one(path: str, n_rep: int = 3):
    """返回 (v3 ms, v4 ms, n_hkl, max|ΔI|) 或 None"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8", "replace")
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
    except Exception:
        return None

    frac = np.asarray(rows, dtype=float)
    occus = np.asarray(occs, dtype=float)
    symbols = list(syms)

    recip = FX.reciprocal_matrix(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
    wl, (tth_min, tth_max) = B.WL, B.TTH
    max_r = 2.0 * np.sin(np.radians(tth_max / 2.0)) / wl
    min_r = 2.0 * np.sin(np.radians(tth_min / 2.0)) / wl
    got = FX._gen_hkl(recip, max_r, min_r, True, B.MAX_HKL, (d.a, d.b, d.c))
    if got is None:
        return None
    H, G, gabs = got
    n_hkl = H.shape[0]
    if n_hkl == 0:
        return None

    params = FX._load_params()
    uniq = sorted(set(symbols))
    try:
        coeff = np.array([params[s] for s in uniq], dtype=float)
    except KeyError:
        return None
    zs = np.array([float(FX._Z[s]) for s in uniq], dtype=float)
    el_of_atom = np.array([uniq.index(s) for s in symbols], dtype=np.int64)

    s_arr = gabs / 2.0
    s2 = s_arr * s_arr
    theta = np.arcsin(np.clip(wl * gabs / 2.0, -1.0, 1.0))
    lp = (1.0 + np.cos(2.0 * theta) ** 2) / (np.sin(theta) ** 2 * np.cos(theta))

    chunk = 4096
    TWOPI = np.float32(2.0 * np.pi)
    H32 = H.astype(np.float32)
    frac32 = np.ascontiguousarray(frac, dtype=np.float32)
    occ32 = occus.astype(np.float32)

    def run_v3():
        # v3: fs 对全部 hkl 一次性算 (f64), w_all 全量 gather, cos/sin f32, 累加 f64
        s2c_all = s2[:, None]
        fs = zs[None, :] - 41.78214 * s2c_all * np.sum(
            coeff[None, :, :, 0] * np.exp(-coeff[None, :, :, 1] * s2c_all[:, :, None]), axis=2)
        fs32 = fs.astype(np.float32)
        w_all = fs32[:, el_of_atom]
        w_all *= occ32[None, :]
        intens = np.empty(n_hkl, dtype=float)
        for start in range(0, n_hkl, chunk):
            sl = slice(start, min(start + chunk, n_hkl))
            ph = H32[sl] @ frac32.T
            ph *= TWOPI
            w = w_all[sl]
            re = (w * np.cos(ph)).sum(axis=1, dtype=np.float64)
            im = (w * np.sin(ph)).sum(axis=1, dtype=np.float64)
            intens[sl] = (re * re + im * im) * lp[sl]
        return intens

    def run_v4():
        # v4: fs 逐块算 (f64 块内), cos/sin f32, 累加 f32
        intens = np.empty(n_hkl, dtype=float)
        for start in range(0, n_hkl, chunk):
            sl = slice(start, min(start + chunk, n_hkl))
            s2c = s2[sl][:, None]
            fs = zs[None, :] - 41.78214 * s2c * np.sum(
                coeff[None, :, :, 0] * np.exp(-coeff[None, :, :, 1] * s2c[:, :, None]), axis=2)
            w = fs.astype(np.float32)[:, el_of_atom]
            w *= occ32[None, :]
            ph = H32[sl] @ frac32.T
            ph *= TWOPI
            re = (w * np.cos(ph)).sum(axis=1)
            im = (w * np.sin(ph)).sum(axis=1)
            intens[sl] = (re * re + im * im) * lp[sl]
        return intens

    run_v3(); run_v4()  # 预热
    t3 = t4 = 0.0
    i3 = i4 = None
    for _ in range(n_rep):
        t0 = time.perf_counter(); i3 = run_v3(); t3 += time.perf_counter() - t0
        t0 = time.perf_counter(); i4 = run_v4(); t4 += time.perf_counter() - t0
    dmax = float(np.abs(i3 - i4).max())
    return t3 / n_rep * 1000, t4 / n_rep * 1000, n_hkl, dmax


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
        for nm in names[:4]:
            out.append(os.path.join(abs_dir, nm))
            if len(out) >= n:
                return out
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    random.seed(20261013)
    print("库    样本  v3 ms/条   v4 ms/条   加速比   平均hkl   max|ΔI|")
    for lib, root, depth, _off in B.LIBS[:2]:
        files = collect(root, depth, n)
        t3s, t4s, hkls, dmaxs = [], [], [], 0.0
        for f in files:
            r = bench_one(f)
            if r is None:
                continue
            t3, t4, nh, dmax = r
            t3s.append(t3); t4s.append(t4); hkls.append(nh)
            dmaxs = max(dmaxs, dmax)
        if not t3s:
            print("%-5s 无有效样本" % lib)
            continue
        m3 = sum(t3s) / len(t3s)
        m4 = sum(t4s) / len(t4s)
        ah = sum(hkls) / len(hkls)
        print("%-5s   %3d  %8.2f   %8.2f   %5.2fx  %8.0f   %.3g" % (
            lib, len(t3s), m3, m4, m3 / m4, ah, dmaxs))


if __name__ == "__main__":
    main()
