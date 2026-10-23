#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计 _scan_parts/w*.jsonl 的去重进度（只读 JSONL，不开 sqlite，避免加锁）。

输出：每库 唯一 cod_id 数 / 无机数 / 官方总数对照 / 剩余量。
"""
from __future__ import annotations

import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = os.path.join(BASE, "_scan_parts")

# 官方基线（rsync 统计）：COD 535181 / PCOD 1062044 / TCOD 57745
TARGET = {"COD": 535181, "PCOD": 1062044, "TCOD": 57745}


def main():
    seen = {k: set() for k in TARGET}
    inorg = {k: set() for k in TARGET}
    n_line = 0
    n_bad = 0
    for f in sorted(glob.glob(os.path.join(PARTS, "w*.jsonl"))):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n_line += 1
                try:
                    r = json.loads(line)
                except ValueError:
                    n_bad += 1
                    continue
                lib = r[1]
                if lib not in seen:
                    continue
                seen[lib].add(r[0])
                if r[6]:
                    inorg[lib].add(r[0])
    tot_u = sum(len(v) for v in seen.values())
    tot_i = sum(len(v) for v in inorg.values())
    print("=" * 64)
    print("JSONL 行数(含双跑重复) : %d   坏行: %d" % (n_line, n_bad))
    print("%-6s %10s %10s %10s %8s %10s" %
          ("库", "唯一条目", "官方总数", "缺口", "完成%", "无机条目"))
    for k in ("COD", "PCOD", "TCOD"):
        u, t, i = len(seen[k]), TARGET[k], len(inorg[k])
        print("%-6s %10d %10d %10d %7.1f%% %10d" %
              (k, u, t, t - u, 100.0 * u / t, i))
    print("-" * 64)
    tu = sum(TARGET.values())
    print("%-6s %10d %10d %10d %7.1f%% %10d" %
          ("合计", tot_u, tu, tu - tot_u, 100.0 * tot_u / tu, tot_i))
    print("无机占比: %.1f%%" % (100.0 * tot_i / max(tot_u, 1)))
    print("重复行数: %d (双跑叠加，merge 时按 cod_id 主键自动折叠)"
          % (n_line - n_bad - tot_u))


if __name__ == "__main__":
    sys.exit(main())
