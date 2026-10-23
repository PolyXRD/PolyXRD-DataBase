#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 formula='O2 Si' 的条目：最强线为何中位在 6.09 Å 而非 α-石英的 3.34 Å。

只走 idx_phases_formula 索引取 505 行，代价很小。
判据：真 α-石英晶胞 a≈4.913、c≈5.405，最强线 (101) d≈3.3435 Å。
"""
import sqlite3
import sys

import numpy as np

DB = sys.argv[1] if len(sys.argv) > 1 else "E:/rsync-COD/3COD-Inorg-20261015.sqlite"


def nums(s):
    return np.asarray([float(x) for x in s.split(",")], dtype=float) if s else np.zeros(0)


def main():
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=120)
    rows = con.execute(
        "SELECT cod_id, cell_a, cell_b, cell_c, cell_alpha, cell_gamma, "
        "n_peaks, space_group, peaks_d, peaks_i FROM phases "
        "WHERE formula='O2 Si'").fetchall()
    con.close()
    print("formula='O2 Si' 共 %d 条" % len(rows))

    buckets = {"真石英(a≈4.91,c≈5.41)": 0, "其他": 0}
    strong = []
    for cid, a, b, c, al, ga, npk, sg, pds, pis in rows:
        d = nums(pds)
        i = nums(pis)
        if d.size == 0:
            continue
        ds = float(d[int(np.argmax(i))])
        is_quartz = a and abs(a - 4.913) < 0.15 and c and abs(c - 5.405) < 0.15 \
            and sg and "63" in str(sg)
        buckets["真石英(a≈4.91,c≈5.41)" if is_quartz else "其他"] += 1
        strong.append((cid, ds, float(i.max()), a, b, c, npk, sg, is_quartz))

    for k, v in buckets.items():
        print("  %-24s %d" % (k, v))

    q = [r for r in strong if r[8]]
    o = [r for r in strong if not r[8]]
    for tag, grp in (("真 α-石英", q), ("其他 'O2 Si'", o)):
        if not grp:
            continue
        ds = np.asarray([r[1] for r in grp])
        near = int(np.sum(np.abs(ds - 3.3435) < 0.06))
        print("  %-14s n=%d  最强线中位 %.3f Å  命中 3.3435±0.06 的 %d 条 (%.0f%%)"
              % (tag, len(grp), float(np.median(ds)), near, 100.0 * near / len(grp)))

    print("  其他组样例（cod_id, 最强线 d, 晶胞 a/b/c, n_peaks, sg）:")
    for r in sorted(o, key=lambda x: -x[1])[:8]:
        print("    %10d  d=%.3f  a=%.3f b=%.3f c=%.3f  n=%s  sg=%s"
              % (r[0], r[1], r[3] or 0, r[4] or 0, r[5] or 0, r[6], r[7]))
    print("  其他组中 d 最大/最小: %.3f / %.3f"
          % (max(r[1] for r in o), min(r[1] for r in o)))
    if q:
        print("  真石英组中未命中 3.3435 的样例:")
        for r in [x for x in q if abs(x[1] - 3.3435) >= 0.06][:8]:
            print("    %10d  d=%.3f  a=%.3f c=%.3f  n=%s  sg=%s"
                  % (r[0], r[1], r[3] or 0, r[5] or 0, r[6], r[7]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
