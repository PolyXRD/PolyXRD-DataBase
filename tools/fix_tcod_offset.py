#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 TCOD/cif/ 下的错层文件归位到 TCOD/。

背景：2026-10-19 第二轮 wget 误用 --cut-dirs=1，把 URL /tcod/cif/40/24/00/x.cif
落成了 TCOD/cif/40/24/00/x.cif，多出一层 "cif"。本脚本把 TCOD/cif/** 全部
移动到 TCOD/**（目标已存在则跳过，不覆盖）。

用法: python tools/fix_tcod_offset.py [--dry]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "TCOD", "cif")
DST = os.path.join(BASE, "TCOD")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(SRC):
        print("没有错层目录，无需处理")
        return 0

    n_move = n_skip = n_dir = 0
    for root, dirs, files in os.walk(SRC):
        rel = os.path.relpath(root, SRC)
        tgt_dir = DST if rel == "." else os.path.join(DST, rel)
        for nm in files:
            if not nm.lower().endswith(".cif"):
                continue
            s = os.path.join(root, nm)
            t = os.path.join(tgt_dir, nm)
            if os.path.exists(t):
                n_skip += 1
                continue
            if args.dry:
                print("MOVE", rel, nm)
            else:
                os.makedirs(tgt_dir, exist_ok=True)
                shutil.move(s, t)
            n_move += 1
        n_dir += 1

    print("目录 %d，移动 %d，已存在跳过 %d%s"
          % (n_dir, n_move, n_skip, "（dry-run）" if args.dry else ""))

    if not args.dry:
        left = 0
        for root, dirs, files in os.walk(SRC):
            left += sum(1 for x in files if x.lower().endswith(".cif"))
        print("TCOD/cif 剩余 .cif: %d" % left)
        if left == 0:
            shutil.rmtree(SRC, ignore_errors=True)
            print("已删除空的 TCOD/cif 目录树")
    return 0


if __name__ == "__main__":
    sys.exit(main())
