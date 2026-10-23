#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""org_cif 清单 ↔ 3COD-Org 产物 双向核对。

证明「按清单从三库打包」的完整性：
  A) 清单 → 产物：664,365 个清单文件（按 lib 偏移折算 cod_id → entry_id）
     每一个都在 Org.entries 中有对应行（逐一解析成功的打包不变量）；
  B) 产物 → 清单：Org.entries 的每个 entry_id 都能映射回清单中的一个文件
     （无多、无少、无错位）；
  C) 库构成：COD/PCOD/TCOD 计数（预期 PCOD=0）；
  D) 抽样存在性：随机 2,000 个清单路径在磁盘上真实存在。

用法:
    python tools/verify_org_manifest.py [--stamp 20261016]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)

MANIFEST = os.path.join(BASE, "sync_logs", "org_cif_manifest_20261016.txt")
OFF = {"COD": 0, "PCOD": 20_000_000, "TCOD": 100_000_000}


def eid_of(cid: int) -> str:
    s = str(cid).zfill(7)
    return "96-%s-%s" % (s[:3], s[3:])


def cod_of_eid(eid: str) -> int:
    return int(eid.replace("-", "")[2:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="20261016")
    args = ap.parse_args()
    t0 = time.time()
    fails = []

    def check(name, ok, detail=""):
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("：" + detail) if detail else ""), flush=True)
        if not ok:
            fails.append(name)

    # ---- 清单 → (cod_id, rel) ----
    man = {}   # cod_id -> rel path
    lib_cnt = {"COD": 0, "PCOD": 0, "TCOD": 0}
    for ln in open(MANIFEST, encoding="utf-8"):
        rel = ln.strip()
        if not rel:
            continue
        lib = rel.split("/", 1)[0]
        lib_cnt[lib] = lib_cnt.get(lib, 0) + 1
        cid = int(os.path.splitext(os.path.basename(rel))[0]) + OFF.get(lib, 0)
        man[cid] = rel
    print("清单：%d 个文件，库构成 %s" % (len(man), lib_cnt), flush=True)

    con = sqlite3.connect(
        "file:%s?mode=ro" % os.path.join(
            BASE, "3COD-Org-%s.sqlite" % args.stamp).replace(os.sep, "/"),
        uri=True, timeout=300)
    org_cids = {cod_of_eid(r[0]) for r in
                con.execute("SELECT entry_id FROM entries")}
    print("Org.entries：%d 条" % len(org_cids), flush=True)

    # ---- A) 清单 ⊆ 产物 ----
    missing = [c for c in man if c not in org_cids]
    check("A 清单→产物：每个清单文件都有 entries 行",
          not missing, "缺失 %d（例：%s）"
          % (len(missing), [man[c] for c in missing[:3]]))

    # ---- B) 产物 ⊆ 清单 ----
    extra = [c for c in org_cids if c not in man]
    check("B 产物→清单：每个 entries 行都来自清单文件",
          not extra, "多余 %d（例：%s）"
          % (len(extra), [extra[:3]]))

    # ---- C) 库构成 ----
    org_lib = {"COD": 0, "PCOD": 0, "TCOD": 0}
    for c in org_cids:
        if c >= 100_000_000:
            org_lib["TCOD"] += 1
        elif c >= 20_000_000:
            org_lib["PCOD"] += 1
        else:
            org_lib["COD"] += 1
    check("C 库构成一致且 PCOD=0", org_lib == lib_cnt,
          "清单 %s vs 产物 %s" % (lib_cnt, org_lib))

    # ---- D) 抽样 2,000 个清单文件在磁盘存在 ----
    random.seed(20261017)
    sample = random.sample(sorted(man.keys()), 2000)
    miss_disk = [man[c] for c in sample
                 if not os.path.exists(os.path.join(BASE,
                                                    *man[c].split("/")))]
    check("D 抽样 2000 个清单文件磁盘存在", not miss_disk,
          "缺失 %d（例：%s）" % (len(miss_disk), miss_disk[:3]))

    con.close()
    print("== 双向核对：%s（用时 %.1f min）=="
          % ("全部通过" if not fails else "FAIL %d 项" % len(fails),
             (time.time() - t0) / 60))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
