#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测 1 进程 vs 4 进程的聚合吞吐，判断并行效率。

用法: python tools/bench_parallel.py [--per 6]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _init():
    import build_3cod as B3
    B3.PARTS = os.path.join(BASE, "_bench_par")


def run_one(args):
    import build_3cod as B3
    sid, units = args
    return B3.worker((sid, units, False, 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=6, help="每组单元数")
    args = ap.parse_args()

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import build_3cod as B3
    import build_dbs as B
    B3.PARTS = os.path.join(BASE, "_bench_par")
    os.makedirs(B3.PARTS, exist_ok=True)

    units = []
    for lib, root, depth, off in B3.LIBS:
        for rel, absd in B.list_dirs(root, depth):
            units.append((lib, rel, absd, off))
    cod = [u for u in units if u[0] == "COD"][:args.per]
    tcod = [u for u in units if u[0] == "TCOD" and u[1].startswith("40/3")][:args.per]
    pcod = [u for u in units if u[0] == "PCOD"][:args.per]

    for tag, group in (("COD", cod), ("PCOD", pcod), ("TCOD", tcod)):
        t = time.time()
        r = run_one((0, group))
        el = max(time.time() - t, 1e-9)
        print("%s 单进程: %d 文件 / %.1f s = %.1f 条/s"
              % (tag, r[1], el, r[1] / el), flush=True)

    for tag, group in (("COD", cod), ("PCOD", pcod), ("TCOD", tcod)):
        t = time.time()
        with Pool(4) as p:
            res = p.map(run_one, [(i, [u]) for i, u in enumerate(group)])
        el = max(time.time() - t, 1e-9)
        nf = sum(x[1] for x in res)
        print("%s 4 进程: %d 文件 / %.1f s = %.1f 条/s（单进程等效 %.1f）"
              % (tag, nf, el, nf / el, nf / el / 4), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
