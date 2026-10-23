#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位 inorg_manifest 与构建产物之间的无机判定差异（逐条）。

两侧用的分子式解析器不同：
  清单  scan_inorg.extract_formula —— 只抓 _chemical_formula_sum 的正则
  产物  fastcif.parse_cif + build_dbs.parse_elements —— 完整 CIF 解析
本工具把差异逐条列出，并用两种解析器分别复算，给出"谁判为无机"。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import build_dbs as B  # noqa: E402
import scan_inorg as SI  # noqa: E402
from fastcif import parse_cif  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def eid_to_cod(eid):
    s = eid.split("-")
    return int(s[1] + s[2])


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "3COD-Inorg-20261015.sqlite")
    print("读 %s 的 entries ..." % os.path.basename(db))
    con = sqlite3.connect("file:%s?mode=ro" % db.replace(os.sep, "/"), uri=True, timeout=60)
    db_ids = set()
    for (eid,) in con.execute("SELECT entry_id FROM entries"):
        try:
            db_ids.add(eid_to_cod(eid))
        except Exception:
            pass
    con.close()
    print("  产物 entries = %d" % len(db_ids))

    mf = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
    man = {}
    for cid, lib, rel in mf.execute("SELECT cod_id, lib, rel FROM files"):
        man[cid] = (lib, rel)
    man_inorg = {c for (c,) in mf.execute("SELECT cod_id FROM files WHERE is_inorg=1")}
    print("  清单 total = %d  无机 = %d" % (len(man), len(man_inorg)))

    only_db = db_ids - man_inorg      # 产物判无机、清单判非无机
    only_man = man_inorg - db_ids     # 清单判无机、产物未收录
    print()
    print("产物有 / 清单非无机 : %d" % len(only_db))
    print("清单无机 / 产物无   : %d" % len(only_man))

    rows = []
    for tag, ids in (("DB_ONLY", only_db), ("MAN_ONLY", only_man)):
        for cid in sorted(ids)[:400]:
            lib, rel = man[cid]
            p = os.path.join(BASE, lib, rel.replace("\\", "/"))
            try:
                text = open(p, "rb").read().decode("utf-8", "replace")
            except OSError:
                continue
            # 清单口径
            f_man = SI.extract_formula(text)
            _, _, c_man = B.parse_elements(f_man)
            inorg_man = B.is_inorganic(c_man)
            # 产物口径
            try:
                d = parse_cif(text)
                f_db = d.formula
                _, _, c_db = B.parse_elements(f_db)
                inorg_db = B.is_inorganic(c_db)
            except Exception as e:
                f_db = "<解析异常 %s>" % type(e).__name__
                inorg_db = None
            rows.append((tag, cid, lib, os.path.basename(rel), f_man, inorg_man, f_db, inorg_db))
    print()
    print("%-9s %-11s %-5s %-14s %-8s %-24s %-8s %-24s"
          % ("方向", "cod_id", "库", "文件", "清单判", "清单公式", "产物判", "产物公式"))
    for tag, cid, lib, nm, fm, im, fd, idb in rows[:60]:
        print("%-9s %-11d %-5s %-14s %-8s %-24s %-8s %-24s"
              % (tag, cid, lib, nm[:14], str(im), (fm or "")[:24], str(idb), (fd or "")[:24]))
    print()
    # 归因统计
    agg = {}
    for tag, cid, lib, nm, fm, im, fd, idb in rows:
        k = (tag, im, idb)
        agg[k] = agg.get(k, 0) + 1
    print("归因（方向, 清单判, 产物判）→ 条数：")
    for k in sorted(agg, key=lambda t: -agg[t]):
        print("   %-10s 清单=%-6s 产物=%-6s  %d" % (k[0], k[1], k[2], agg[k]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
