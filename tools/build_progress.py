#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3COD 构建进度与 ETA（适配 _3cod_parts，24 分片 / 4 进程）。

信息源（不干扰构建，全部只读）:
  1. 构建日志里已完成分片的行：`[k/24] 分片 pXXX: 文件 N, ... T s`
  2. `_3cod_parts/p*.sqlite` 的 mtime 与体积（在写 = 活跃）
  3. 分片库 meta.shard_done 标记（存在 = 该分片处理完毕）

用法:
    python build_progress.py [--log sync_logs/build_3cod_20261015_inorg.log]
                             [--shards 24] [--total 1838364]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = os.path.join(BASE, "_3cod_parts")

RE_SHARD = re.compile(
    r"\[(\d+)/(\d+)\]\s+分片\s+p(\d+):\s+文件\s+(\d+),\s+无机\s+(\d+),"
    r"\s+峰成功\s+(\d+),\s+峰失败\s+(\d+),\s+解析失败\s+(\d+),\s+([\d.]+)\s*s")


def parse_log(path):
    done = {}
    start = None
    m_total = None
    if not os.path.exists(path):
        return done, start, m_total
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.search(r"单元\s+(\d+)\s+个\s+→\s+(\d+)\s+分片", line)
            if m:
                m_total = int(m.group(1))
            m = RE_SHARD.search(line)
            if m:
                sid = int(m.group(3))
                done[sid] = dict(nfiles=int(m.group(4)), n_inorg=int(m.group(5)),
                                 n_ok=int(m.group(6)), n_fail=int(m.group(7)),
                                 n_parse=int(m.group(8)), secs=float(m.group(9)))
    return done, start, m_total


def units_of_shard(sid, shards, total_units):
    """--shards 分片按 units[i::shards] 切分，返回该分片的单元数。"""
    if total_units <= 0:
        return 0
    return len(range(sid, total_units, shards))


def shard_state(path):
    """返回 (rows, done_flag, mb)。打不开就退化为体积。"""
    mb = os.path.getsize(path) / 1e6
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path.replace(os.sep, "/"),
                            uri=True, timeout=3)
        n = c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
        d = c.execute("SELECT value FROM meta WHERE key='shard_done'").fetchone()
        c.close()
        return n, ("yes" if d else "-"), mb
    except sqlite3.Error:
        return -1, "?", mb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(BASE, "sync_logs",
                                                  "build_3cod_20261015_inorg.log"))
    ap.add_argument("--shards", type=int, default=24)
    ap.add_argument("--units", type=int, default=8502)
    ap.add_argument("--total", type=int, default=1838364)
    ap.add_argument("--per-unit", type=float, default=0.0,
                    help="平均每单元文件数（不给则由已算分片的实际均值推断）")
    args = ap.parse_args()

    done, _, m_total = parse_log(args.log)
    units_total = m_total or args.units

    fulls = sorted(glob.glob(os.path.join(PARTS, "p*_full.sqlite")))
    rows = []
    n_done_files = n_done_units = 0
    thr = []
    for sid in sorted(done):
        d = done[sid]
        n_done_files += d["nfiles"]
        n_done_units += units_of_shard(sid, args.shards, units_total)
        if d["secs"] > 0:
            thr.append(d["nfiles"] / d["secs"])
    avg_thr = sum(thr) / len(thr) if thr else 0.0

    print("=== 已完成分片（日志）===")
    for sid in sorted(done):
        d = done[sid]
        print("  p%03d  单元 %4d  文件 %7d  无机 %6d  峰成功 %6d  失败 %5d  "
              "%6.0f s  %5.1f 文件/s"
              % (sid, units_of_shard(sid, args.shards, units_total), d["nfiles"],
                 d["n_inorg"], d["n_ok"], d["n_fail"], d["secs"],
                 d["nfiles"] / max(d["secs"], 1e-9)))
    n_shard_done = len(done)
    print("  小计: %d/%d 分片, %d 单元, %d 文件"
          % (n_shard_done, args.shards, n_done_units, n_done_files))

    print()
    print("=== 全部分片文件状态 ===")
    for p in fulls:
        n, flag, mb = shard_state(p)
        age = (time.time() - os.path.getmtime(p)) / 60.0
        print("  %-24s rows=%-9s done=%-4s %8.1f MB  %5.1f min 前写入"
              % (os.path.basename(p), n, flag, mb, age))

    if avg_thr > 0:
        per_unit = args.per_unit or (n_done_files / max(n_done_units, 1))
        rem_units = units_total - n_done_units
        eta_h = rem_units * per_unit / avg_thr / 3600.0
        print()
        print("平均吞吐 %.1f 文件/s（%d 个已算分片）；平均每单元 %.1f 文件"
              % (avg_thr, n_shard_done, per_unit))
        print("剩余 %d 单元 ≈ %.2f M 文件；单进程串行 ETA %.1f h，"
              "4 进程并行 ETA ≈ %.1f h"
              % (rem_units, rem_units * per_unit / 1e6, eta_h, eta_h / 4.0))
    else:
        print()
        print("尚无完成的分片，无法推算吞吐。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
