#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测不同 gzip 级别的耗时与压缩率，为 full 库是否内嵌 CIF 原文提供决策依据。"""
import gzip
import os
import random
import time

COD = "E:/rsync-COD/COD"
rng = random.Random(3)

level = [("", COD)]
for _ in range(3):
    nxt = []
    for rel, p in level:
        try:
            names = os.listdir(p)
        except OSError:
            continue
        for nm in names:
            q = os.path.join(p, nm)
            if os.path.isdir(q):
                nxt.append((os.path.join(rel, nm), q))
    level = nxt
rng.shuffle(level)
files = []
for d, p in level[:30]:
    fs = [f for f in os.listdir(p) if f.endswith(".cif")]
    rng.shuffle(fs)
    files.extend(os.path.join(p, f) for f in fs[:4])

raws = []
for f in files:
    with open(f, "rb") as fh:
        raws.append(fh.read())
n = len(raws)
total = sum(len(r) for r in raws)
print("样本 %d 个, 原始 %.1f MB" % (n, total / 1e6))
print("%-8s %-14s %-14s %-10s" % ("级别", "耗时 ms/条", "吞吐 MB/s", "压缩率"))
for lv in (1, 3, 6, 9):
    t0 = time.time()
    out = [gzip.compress(r, compresslevel=lv) for r in raws]
    dt = time.time() - t0
    ct = sum(len(o) for o in out)
    print("%-8d %-14.1f %-14.1f %.1f%%" % (
        lv, dt / n * 1000, total / dt / 1e6, 100.0 * ct / total))
