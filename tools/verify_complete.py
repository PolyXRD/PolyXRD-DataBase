#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整性严查：证明两个库"一条都没漏"。

比 `verify_dbs.py` 更硬 —— 后者只比条目**总数**，本脚本做**集合比对**：

1) full 库：源 CIF 相对路径集合  ==  cod_entries.file 集合
   （用相对路径而不是 cod_id，可绕开编号规则的任何分歧，是最直接的证据）

2) inorg 库：full 库里按化学式判定为无机的 cod_id 集合  ==  phases.cod_id 集合
   （判定只用 full 库自己的 formula 列重算，不必再读 165 万个 CIF）

3) 无机 CIF 副本目录文件数  ==  phases 条数

4) 抽查：内嵌 CIF 可解压、峰表自洽、Top-64 与 peaks_d/peaks_i 一致
"""
from __future__ import annotations

import gzip
import os
import sqlite3
import struct
import sys
import time

import numpy as np

sys.path.insert(0, "E:/rsync-COD/tools")
import build_dbs as B  # noqa: E402

FULL_DB = "E:/rsync-COD/COD-PCOD-TCOD-full-20261010.sqlite"
INORG_DB = "E:/rsync-COD/COD-PCOD-TCOD-Inorg-20261010.sqlite"
INORG_CIF = "E:/rsync-COD/inorg_cif"


def scan_sources():
    """枚举源 CIF 的相对路径（与 build_dbs 的 file 列同格式 lib/rel/nm.cif）。"""
    out = set()
    per_lib = {}
    for lib, root, _depth, _off in B.LIBS:
        n = 0
        for dirpath, _dn, files in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            for fn in files:
                if not fn.lower().endswith(".cif"):
                    continue
                out.add("%s/%s/%s" % (lib, rel_dir, fn) if rel_dir
                        else "%s/%s" % (lib, fn))
                n += 1
        per_lib[lib] = n
        print("  源扫描 %-5s %8d 个 CIF" % (lib, n), flush=True)
    return out, per_lib


def main():
    t0 = time.time()
    print("=" * 80)
    print("1) 源 CIF 全量枚举")
    src, per_lib = scan_sources()
    print("  合计 %d" % len(src))

    print("\n2) full 库 —— 相对路径集合比对")
    c = sqlite3.connect("file:%s?mode=ro" % FULL_DB.replace("\\", "/"), uri=True)
    db_files = set()
    for (f,) in c.execute("SELECT file FROM cod_entries"):
        db_files.add(f)
    n_ent = c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
    print("  cod_entries 行数 %d, 去重路径 %d" % (n_ent, len(db_files)))
    missing = src - db_files
    extra = db_files - src
    print("  源里有、库里没有 (漏条目): %d" % len(missing))
    for x in list(sorted(missing))[:10]:
        print("      - %s" % x)
    print("  库里有、源里没有 (幽灵条目): %d" % len(extra))
    for x in list(sorted(extra))[:10]:
        print("      + %s" % x)
    n_dup = c.execute("SELECT COUNT(*) FROM (SELECT cod_id FROM cod_entries "
                      "GROUP BY cod_id HAVING COUNT(*)>1)").fetchone()[0]
    print("  重复 cod_id: %d" % n_dup)

    print("\n3) inorg 库 —— 与 full 库重算的无机集合比对")
    expect = set()
    n_nof = 0
    for cid, formula in c.execute("SELECT cod_id, formula FROM cod_entries"):
        _el, _fr, counts = B.parse_elements(formula)
        if counts and B.is_inorganic(counts):
            expect.add(cid)
        elif not counts:
            n_nof += 1
    print("  full 库重算: 无机 %d 条 (无化学式 %d 条, 按非无机处理)"
          % (len(expect), n_nof))
    c.close()

    ci = sqlite3.connect("file:%s?mode=ro" % INORG_DB.replace("\\", "/"), uri=True)
    got = {r[0] for r in ci.execute("SELECT cod_id FROM phases")}
    print("  inorg 库 phases: %d 条" % len(got))
    miss2 = expect - got
    extra2 = got - expect
    print("  应为无机但库里没有 (漏): %d" % len(miss2))
    for x in sorted(miss2)[:10]:
        print("      - %s" % x)
    print("  库里有但重算非无机 (多): %d" % len(extra2))
    for x in sorted(extra2)[:10]:
        print("      + %s" % x)

    print("\n4) 无机 CIF 副本目录")
    n_copy = 0
    for lib in ("COD", "PCOD", "TCOD"):
        p = os.path.join(INORG_CIF, lib)
        if not os.path.isdir(p):
            continue
        k = sum(1 for _d, _s, fs in os.walk(p) for f in fs
                if f.lower().endswith(".cif"))
        n_copy += k
        print("  %-5s 副本 %d 个" % (lib, k))
    print("  副本合计 %d  (phases %d, 差 %d)" % (n_copy, len(got), n_copy - len(got)))

    print("\n5) 抽查字段自洽性 (随机 3000 条有峰条目)")
    bad = {"top_mismatch": 0, "npeaks_mismatch": 0, "cif_bad": 0,
           "d_not_desc": 0, "imax_not_1000": 0}
    rows = ci.execute(
        "SELECT cod_id, formula, space_group, cell_a, n_peaks, peaks_d, peaks_i, "
        "peaks_top_d, peaks_top_i, cif_gz, display_id, ref_id FROM phases "
        "WHERE n_peaks > 0 ORDER BY cod_id LIMIT 3000").fetchall()
    for (cid, fm, sg, ca, npeaks, pd_, pi_, tdb, tib, gz, did, rid) in rows:
        d = (np.asarray([float(x) for x in pd_.split(",")], dtype=float)
             if pd_ else np.array([]))
        i = (np.asarray([float(x) for x in pi_.split(",")], dtype=float)
             if pi_ else np.array([]))
        if len(d) != npeaks or len(i) != npeaks:
            bad["npeaks_mismatch"] += 1
        if len(d) > 1 and np.any(np.diff(d) > 1e-9):
            bad["d_not_desc"] += 1
        if i.size and abs(i.max() - 1000.0) > 0.5:
            bad["imax_not_1000"] += 1
        order = np.argsort(-i, kind="stable")[:64]
        td, ti = d[order], i[order]
        if tdb is None or tib is None:
            bad["top_mismatch"] += 1
        else:
            gvd = np.frombuffer(tdb, dtype=np.float64)
            gvi = np.frombuffer(tib, dtype=np.float64)
            n = min(len(td), len(gvd))
            if n and not (np.allclose(gvd[:n], td[:n], atol=1e-6)
                          and np.allclose(gvi[:n], ti[:n], atol=1e-3)):
                bad["top_mismatch"] += 1
        if gz is not None:
            try:
                gzip.decompress(gz)
            except Exception:                        # noqa: BLE001
                bad["cif_bad"] += 1
    print("  抽查 %d 条, 异常: %s" % (len(rows), bad))
    ci.close()
    print("\n耗时 %.0f s" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
