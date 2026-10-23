#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计分片产物中 formula 缺失的条目（只读分片，不碰 22 GB 成品库）。

背景：部分 COD CIF（多为 ab initio / constrained Rietveld 型）没有
`_chemical_formula_sum` → fastcif.parse_cif 得空 formula →
build_3cod 的 elements 列为 NULL → is_inorganic({}) = False →
这类**化学上确为无机**的条目被漏收进 3COD-Inorg。

注意：分片产物**未建索引**，任何按 cod_id 关联 cod_atomic_sites 的子查询都会
退化成全表扫描（实测 11 分钟无进展），因此这里只做纯 COUNT 全表扫描。
"能否由原子位点补出元素集" 的可行性分析在 diff_inorg_manifest_vs_db 侧
针对具体条目（数百个）逐文件做，代价可控。
"""
import glob
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = os.path.join(BASE, "_3cod_parts")


def scan(kind, main):
    files = sorted(glob.glob(os.path.join(PARTS, "p*_%s.sqlite" % kind)))
    t = {"ent": 0, "nf": 0, "main": 0, "mnf": 0}
    for i, p in enumerate(files):
        con = sqlite3.connect("file:%s?mode=ro" % p.replace(os.sep, "/"),
                              uri=True, timeout=60)
        for key, sql in (("ent", "SELECT COUNT(*) FROM entries"),
                         ("nf", "SELECT COUNT(*) FROM entries "
                                "WHERE IFNULL(formula,'')=''"),
                         ("main", "SELECT COUNT(*) FROM %s" % main),
                         ("mnf", "SELECT COUNT(*) FROM %s "
                                 "WHERE IFNULL(formula,'')=''" % main)):
            try:
                t[key] += con.execute(sql).fetchone()[0] or 0
            except sqlite3.Error as e:
                print("  ! %s: %s" % (os.path.basename(p), e))
        con.close()
        print("  [%2d/%d] %s  entries=%d 空=%d  %s=%d 空=%d"
              % (i + 1, len(files), os.path.basename(p), t["ent"], t["nf"],
                 main, t["main"], t["mnf"]), flush=True)
    print("  --- %s 小计 ---" % kind)
    print("    entries=%d  formula 空=%d (%.3f%%)"
          % (t["ent"], t["nf"], 100.0 * t["nf"] / max(t["ent"], 1)))
    print("    %s=%d  formula 空=%d (%.3f%%)"
          % (main, t["main"], t["mnf"], 100.0 * t["mnf"] / max(t["main"], 1)))
    return t


def main():
    print("读分片（只读）:", PARTS)
    scan("full", "cod_entries")
    scan("inorg", "phases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
