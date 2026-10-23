#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 Org 产物 peaks 重复行（被杀进程重做单元导致的 2 倍插入）。

背景：首轮分片构建被杀时有 4 个在飞单元，重启 --resume 后这些单元重做——
entries（PK）/ phases（PK）/ cod_atomic_sites（UNIQUE）经 INSERT OR REPLACE
自动去重，唯 peaks 无任何约束 → 受影响 entry 的峰行翻倍（A5 实测多 17,700 行）。

修复（三步，全部走索引，避开 65M 行全表排序）：
  1) 逐分片定位受影响 entry_id：分片内 GROUP BY entry_id 走 idx_peaks_entry_id，
     判据 COUNT(*) > COUNT(DISTINCT 六列键)（重复倍数不限）或 COUNT(*) > 100；
  2) 产物内对每个受影响 entry 删重复行（保留每组最小 rowid）；
  3) 复核：受影响 entry 的行数与 Full 一致 + 产物总行数 == Full(org 部分)。

用法:
    python tools/fix_org_peaks_dup.py [--stamp 20261016] [--apply]
    （不带 --apply 只诊断，不写库）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)

KEY = ("printf('%.17g|%.17g|%.17g|%d|%d|%d', d, intensity, h, k, l)")


def ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path.replace(os.sep, "/"),
                           uri=True, timeout=300)


def scan_shard(path):
    """返回该分片中受影响（有重复行）的 entry_id 列表。"""
    con = ro(path)
    rows = con.execute(
        "SELECT entry_id, COUNT(*) c, COUNT(DISTINCT %s) dc FROM peaks "
        "GROUP BY entry_id HAVING c > dc OR c > 100" % KEY).fetchall()
    con.close()
    return rows  # [(entry_id, dup_total, distinct_n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="20261016")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    org_db = os.path.join(BASE, "3COD-Org-%s.sqlite" % args.stamp)
    full_db = os.path.join(BASE, "3COD-Full-20261015.sqlite")

    # ---- 1) 逐分片诊断 ----
    import glob
    shards = sorted(glob.glob(os.path.join(BASE, "_3cod_org_parts",
                                           "p*_org.sqlite")))
    print("诊断 %d 个分片…" % len(shards), flush=True)
    affected = {}   # entry_id -> (dup_total, distinct_n)
    for p in shards:
        rows = scan_shard(p)
        if rows:
            print("  %s：%d 个受影响 entry" % (os.path.basename(p), len(rows)))
        for eid, c, dc in rows:
            affected[eid] = (c, dc)
    n_extra_shard = sum(c - dc for c, dc in affected.values())
    print("分片诊断完成：受影响 entry %d 个，多余行 %d（用时 %.1f min）"
          % (len(affected), n_extra_shard, (time.time() - t0) / 60), flush=True)

    # ---- 2) 产物修复 ----
    con = sqlite3.connect(org_db, timeout=300)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA cache_size=-262144")
    n_extra_prod = 0
    fixed = 0
    for i, (eid, _cd) in enumerate(sorted(affected.items())):
        before = con.execute("SELECT COUNT(*) FROM peaks WHERE entry_id=?",
                             (eid,)).fetchone()[0]
        con.execute("DELETE FROM peaks WHERE entry_id=? AND rowid NOT IN "
                    "(SELECT MIN(rowid) FROM peaks WHERE entry_id=? "
                    "GROUP BY d, intensity, h, k, l)", (eid, eid))
        after = con.execute("SELECT COUNT(*) FROM peaks WHERE entry_id=?",
                            (eid,)).fetchone()[0]
        n_extra_prod += before - after
        fixed += 1
        if (i + 1) % 100 == 0:
            con.commit()
            print("  已修复 %d/%d" % (i + 1, len(affected)), flush=True)
    con.commit()
    print("产物修复：%d entry，删除重复行 %d（与分片诊断 %d 应一致）"
          % (fixed, n_extra_prod, n_extra_shard), flush=True)

    # ---- 3) 复核 ----
    con.execute("ATTACH DATABASE ? AS f", (full_db.replace(os.sep, "/"),))
    con.execute("CREATE TEMP TABLE ok_ids(entry_id TEXT PRIMARY KEY)")
    con.executemany("INSERT OR IGNORE INTO ok_ids VALUES (?)",
                    [(e,) for e in affected])
    bad = 0
    for (eid,) in con.execute("SELECT entry_id FROM ok_ids"):
        a = con.execute("SELECT COUNT(*) FROM peaks WHERE entry_id=?",
                        (eid,)).fetchone()[0]
        b = con.execute("SELECT COUNT(*) FROM f.peaks WHERE entry_id=?",
                        (eid,)).fetchone()[0]
        if a != b:
            bad += 1
    check1 = bad == 0
    print("复核1 受影响 entry 行数与 Full 一致：%s（不一致 %d）"
          % ("PASS" if check1 else "FAIL", bad), flush=True)

    n_total = con.execute("SELECT COUNT(*) FROM peaks").fetchone()[0]
    n_full_org = con.execute(
        "SELECT COUNT(*) FROM f.peaks p WHERE p.entry_id IN "
        "(SELECT entry_id FROM main.entries)").fetchone()[0]
    check2 = n_total == n_full_org
    print("复核2 产物 peaks 总数 == Full(org 部分)：%s（%d vs %d）"
          % ("PASS" if check2 else "FAIL", n_total, n_full_org), flush=True)
    con.execute("DETACH DATABASE f")
    con.commit()
    con.close()

    if args.apply and check1 and check2:
        import shutil
        dst = org_db[:-7] + ".db"
        print("同步 .db 副本（copyfile %.2f GB）…"
              % (os.path.getsize(org_db) / 1e9), flush=True)
        t = time.time()
        shutil.copyfile(org_db, dst)
        print(".db 已同步（%.1f min）" % ((time.time() - t) / 60), flush=True)
    elif not args.apply:
        print("（诊断模式，未写库；加 --apply 执行修复与 .db 同步）")

    print("== 总用时 %.1f min ==" % ((time.time() - t0) / 60))
    sys.exit(0 if (check1 and check2) else 1)


if __name__ == "__main__":
    main()
