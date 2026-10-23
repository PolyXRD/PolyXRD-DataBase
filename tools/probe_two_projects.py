#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用两个项目的**官方探测代码**验证交付库的库型归属（只读，不写配置）。

PolyXRD 侧：``polyxrd.services.db_import.inspect_db_file``
    —— GUI「挂载任意位置」用的就是这个函数，判定结果决定库落到哪个槽位。
XinMatch 侧：``xinmatch.core.db.polyxrd.detect_source``
    —— 原生四表直接打开；判成 PolyXRD 库则要转侧车。

本脚本只 import 与探测，**不调用 apply_import / set_*_db_path**，
因此不会污染 ~/.polyxrd/user_db_paths.json。
"""
from __future__ import annotations

import os
import sys
import traceback

BASE = "D:/Project/XRD/PolyXRD-DataBase"
POLY = "D:/Project/XRD/PolyXRD/src"
XIN = "D:/Project/XRD/XinMatch"

DBS = [
    ("Full", os.path.join(BASE, "3COD-Full-20261020.sqlite")),
    ("Inorg", os.path.join(BASE, "3COD-Inorg-20261020.sqlite")),
]


def probe_polyxrd():
    print("=" * 80)
    print("PolyXRD  db_import.inspect_db_file()")
    print("=" * 80)
    if POLY not in sys.path:
        sys.path.insert(0, POLY)
    try:
        from polyxrd.services.db_import import inspect_db_file, KIND_BY_KEY
    except Exception:
        print("!! import 失败：")
        traceback.print_exc()
        return
    for tag, p in DBS:
        ins = inspect_db_file(p)
        print(f"[{tag}] {os.path.basename(p)}")
        print(f"   ok={ins.ok}  kind={ins.kind}  table={ins.table}  rows={ins.rows:,}")
        print(f"   has_top_peaks={ins.has_top_peaks}  size_mb={ins.size_mb}  "
              f"error={ins.error or '-'}  hint={ins.hint or '-'}")
        if ins.kind:
            spec = KIND_BY_KEY[ins.kind]
            print(f"   -> 槽位 config_key={spec.config_key}  label={spec.label_key}")
        print(f"   columns({len(ins.columns)}): {', '.join(ins.columns)}")


def probe_xinmatch():
    print()
    print("=" * 80)
    print("XinMatch  polyxrd.detect_source()")
    print("=" * 80)
    if XIN not in sys.path:
        sys.path.insert(0, XIN)
    try:
        from xinmatch.core.db.polyxrd import detect_source
        from xinmatch.core.db import polyxrd as px
    except Exception:
        print("!! import 失败：")
        traceback.print_exc()
        return

    kinds = {v: k for k, v in vars(px).items() if k.startswith("SCHEMA_")}
    for tag, p in DBS:
        src = detect_source(p)
        print(f"[{tag}] {os.path.basename(p)}")
        print(f"   kind={src.kind}  ({kinds.get(src.kind, '?')})")
        print(f"   table={src.table}  id_column={src.id_column}  "
              f"formula_column={src.formula_column}  row_count={src.row_count:,}")
        print(f"   cell_columns={src.cell_columns}")
        if src.reason:
            print(f"   reason={src.reason}")


if __name__ == "__main__":
    probe_polyxrd()
    probe_xinmatch()
