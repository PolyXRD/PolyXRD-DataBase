#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""org_cif/ 差值副本：把 Org 差值集（664,507 − 142 排除 = 664,365 个 CIF）
按 inorg_cif/ 同款布局 {lib}/{rel}/{name} 复制，供两软件随包携带。

输入：sync_logs/org_files_20261016.jsonl（字段 cod_id/lib/rel/name/abs）
      sync_logs/org_exclude_20261016.json（位点回推判无机的 142 条，剔除）
校验：逐文件复制后字节数对账（源头 stat 与落盘 stat），不一致计错。

用法:
    python tools/copy_org_cif.py [--dry-run] [--workers 4]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)

EXCLUDE = os.path.join(BASE, "sync_logs", "org_exclude_20261016.json")
ORG_LIST = os.path.join(BASE, "sync_logs", "org_files_20261016.jsonl")
DEST = os.path.join(BASE, "org_cif")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    with open(EXCLUDE, encoding="utf-8") as fh:
        excl = set(json.load(fh)["cod_ids"])
    print("排除（转入 Inorg-v2）：%d 条" % len(excl), flush=True)

    tasks, miss = [], 0
    for line in open(ORG_LIST, encoding="utf-8"):
        r = json.loads(line)
        if int(r["cod_id"]) in excl:
            continue
        src = r["abs"]
        try:
            size = os.stat(src).st_size
        except OSError:
            miss += 1
            continue
        dst = os.path.join(DEST, r["lib"], r["rel"], r["name"])
        tasks.append((src, dst, size))
    print("待复制：%d 个文件（清单外缺失 %d），共 %.2f GB"
          % (len(tasks), miss, sum(t[2] for t in tasks) / 1e9), flush=True)
    if args.dry_run:
        return

    n_ok = n_err = 0
    t0 = time.time()

    def cp(t):
        src, dst, size = t
        d = os.path.dirname(dst)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        shutil.copy2(src, dst)
        return os.path.getsize(dst) == size

    with ThreadPoolExecutor(args.workers) as ex:
        for i, ok in enumerate(ex.map(cp, tasks, chunksize=64)):
            if ok:
                n_ok += 1
            else:
                n_err += 1
            if (i + 1) % 100000 == 0:
                print("  %d/%d  %.1f min" % (i + 1, len(tasks),
                                             (time.time() - t0) / 60), flush=True)
    print("复制完成：成功 %d，字节不符 %d，用时 %.1f min"
          % (n_ok, n_err, (time.time() - t0) / 60))
    if n_err or miss:
        sys.exit(1)


if __name__ == "__main__":
    main()
