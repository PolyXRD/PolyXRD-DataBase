#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐阶段耗时剖析：找出全量构建的真实热点。

采样方式：从 COD（文件最大、占 110 GB）/ PCOD / TCOD 各随机抽 N 个真实 CIF，
按 build_dbs.py 的完全相同的调用序列计时，定位耗时占比。
"""
from __future__ import annotations

import gzip
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402
from fastxrd import compute_pattern_arrays  # noqa: E402
import build_dbs as B  # noqa: E402

SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 300


def collect(root: str, depth: int, n: int):
    dirs = B.list_dirs(root, depth)
    pool = []
    for rel, abs_dir in dirs:
        try:
            names = [x for x in os.listdir(abs_dir) if x.lower().endswith(".cif")]
        except OSError:
            continue
        pool.append((abs_dir, names))
    if not pool:
        return []
    random.shuffle(pool)
    out = []
    for abs_dir, names in pool:
        random.shuffle(names)
        for nm in names[:6]:
            out.append(os.path.join(abs_dir, nm))
            if len(out) >= n:
                return out
    return out


def main():
    print("numpy threads env: OMP=%s" % os.environ.get("OMP_NUM_THREADS"))
    tot = {"read": 0.0, "decode": 0.0, "parse": 0.0, "elem": 0.0,
           "gz6": 0.0, "gz1": 0.0, "expand": 0.0, "peaks": 0.0}
    n_inorg = n_peak = n_skip = 0
    files_all = []
    for lib, root, depth, _off in B.LIBS:
        if not os.path.isdir(root):
            continue
        files_all.append((lib, collect(root, depth, SAMPLE)))
    grand = 0
    for lib, files in files_all:
        print("\n=== %s: 采样 %d 个 CIF ===" % (lib, len(files)))
        t_all = time.time()
        for path in files:
            grand += 1
            t = time.time()
            with open(path, "rb") as fh:
                raw = fh.read()
            tot["read"] += time.time() - t
            t = time.time()
            text = raw.decode("utf-8", errors="replace")
            tot["decode"] += time.time() - t
            t = time.time()
            d = parse_cif(text)
            tot["parse"] += time.time() - t
            t = time.time()
            _el, _fr, counts = B.parse_elements(d.formula)
            tot["elem"] += time.time() - t
            t = time.time()
            g6 = gzip.compress(raw, compresslevel=6)
            tot["gz6"] += time.time() - t
            t = time.time()
            g1 = gzip.compress(raw, compresslevel=1)
            tot["gz1"] += time.time() - t
            if B.is_inorganic(counts) if counts else False:
                n_inorg += 1
                t = time.time()
                coords, sp_list, _ = expand_sites(d.sites, d.symops)
                tot["expand"] += time.time() - t
                if len(sp_list) > B.MAX_SITES_FOR_PEAKS or \
                        (d.volume or 0) > B.MAX_CELL_VOL_FOR_PEAKS:
                    n_skip += 1
                    continue
                rows, syms, occs = [], [], []
                for coord, sp in zip(coords, sp_list):
                    for el, o in sp.items():
                        o = float(o)
                        rows.append(coord)
                        syms.append(el)
                        occs.append(min(o, 1.0) if o > 0 else 1.0)
                t = time.time()
                dd, ii = compute_pattern_arrays(
                    d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                    np.asarray(rows, dtype=float), syms, occs,
                    wavelength=B.WL, tth_range=B.TTH,
                    max_peaks=B.MAX_PEAKS, scale=B.SCALE,
                    max_hkl=B.MAX_HKL)
                tot["peaks"] += time.time() - t
                if dd:
                    n_peak += 1
        el = time.time() - t_all
        print("  总 %.1f s,  %.1f ms/文件" % (el, el * 1000 / max(1, len(files))))

    print("\n=== 全部 %d 个文件 逐阶段汇总 ===" % grand)
    for k, v in tot.items():
        print("  %-8s %8.1f s   %7.2f ms/文件" % (k, v, v * 1000 / max(1, grand)))
    s = sum(tot.values())
    print("  合计      %8.1f s   %7.2f ms/文件" % (s, s * 1000 / max(1, grand)))
    print("  无机 %d, 算峰成功 %d, 超上限跳过 %d" % (n_inorg, n_peak, n_skip))
    print("  gzip L6/L1 体积比: %.3f" % (
        sum(len(gzip.compress(open(p, 'rb').read(), 6)) for _, fs in files_all for p in fs[:40]) /
        max(1, sum(len(gzip.compress(open(p, 'rb').read(), 1)) for _, fs in files_all for p in fs[:40]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
