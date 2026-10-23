#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测建库各环节速度：gzip 压缩 / CIF 正则解析 / CifParser / XRD 峰计算。
   用于估算 165 万条目的总耗时并决定并行策略。"""
import gzip
import os
import random
import time
import warnings

COD = "E:/rsync-COD/COD"
PCOD = "E:/rsync-COD/PCOD"


def sample(root, depth, n_dirs, per_dir, seed=7):
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


def bench_files(files, label):
    if not files:
        print("%s: 无样本" % label)
        return
    raws = []
    t0 = time.time()
    for f in files:
        with open(f, "rb") as fh:
            raws.append(fh.read())
    t_read = time.time() - t0
    nbytes = sum(len(r) for r in raws)

    t0 = time.time()
    for r in raws:
        gzip.compress(r, compresslevel=9)
    t_gz = time.time() - t0

    # 正则式轻量解析 (模拟 parse_cif_text)
    import re
    pats = [re.compile(r"_chemical_formula_sum\s+(.+)" .encode()),
            re.compile(rb"_cell_length_a\s+([0-9.\-()]+)"),
            re.compile(rb"_symmetry_space_group_name_H-M\s+(.+)")]
    t0 = time.time()
    for r in raws:
        for p in pats:
            p.search(r)
    t_re = time.time() - t0

    print("\n[%s] 样本 %d 个, 共 %.1f MB, 平均 %.1f KB" %
          (label, len(raws), nbytes / 1e6, nbytes / len(raws) / 1024))
    print("   读取     : %.1f ms/条  (%.1f MB/s)" %
          (t_read / len(raws) * 1000, nbytes / t_read / 1e6))
    print("   gzip -9  : %.1f ms/条  (%.1f MB/s)" %
          (t_gz / len(raws) * 1000, nbytes / t_gz / 1e6))
    print("   正则解析 : %.2f ms/条" % (t_re / len(raws) * 1000))
    return raws


def bench_xrd(raws, label, limit=40):
    from pymatgen.io.cif import CifParser
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    calc = XRDCalculator(wavelength=1.5406)
    n_ok = 0
    t_parse = 0.0
    t_xrd = 0.0
    for raw in raws[:limit]:
        txt = raw.decode("utf-8", "replace")
        t0 = time.time()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                st = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                    primitive=False)[0]
        except Exception:
            continue
        t_parse += time.time() - t0
        t0 = time.time()
        try:
            calc.get_pattern(st, two_theta_range=(5.0, 115.0))
        except Exception:
            continue
        t_xrd += time.time() - t0
        n_ok += 1
    if n_ok:
        print("   CifParser: %.1f ms/条   XRD 计算: %.1f ms/条  (成功 %d/%d)" %
              (t_parse / n_ok * 1000, t_xrd / n_ok * 1000, n_ok,
               min(limit, len(raws))))


if __name__ == "__main__":
    cod_files = sample(COD, 3, 40, 3)
    pcod_files = sample(PCOD, 2, 40, 3)
    r1 = bench_files(cod_files, "COD (大结构)")
    r2 = bench_files(pcod_files, "PCOD (小结构)")
    if r1:
        bench_xrd(r1, "COD")
    if r2:
        bench_xrd(r2, "PCOD")
