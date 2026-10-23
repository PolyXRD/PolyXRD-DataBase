#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inorg-v2 重分类差集：对「formula/elements 解析为空」的条目，由 CIF 原子位点
回推元素集合，再用同一 is_inorganic 规则重新判定。

背景（E-4 / 记忆 #19）：约 478 条 CIF 没有 `_chemical_formula_sum`（或公式解析
不出元素），构建侧 `parse_elements(formula)` 得空 counts → `is_inorganic({})=False`
→ 被判"非无机"落进差值集（Org）。其中一部分按真实位点确为无机（典型 ab initio /
constrained Rietveld 型，如 Ca10(VxP1-xO4)6F2 磷灰石）。修法：formula 为空时改由
`_atom_site_type_symbol` / 原子位点回推元素集合再判无机——分类与元素索引同时纠正。

产物：
  sync_logs/inorg_v2_gap_20261016.json   全部 478 条的明细（位点元素、判定）
  sync_logs/org_exclude_20261016.json    其中判为无机的 cod_id 列表
                                         （Org 合并时排除；Inorg-v2 补丁收录）

用法:
    python tools/classify_formula_gap.py [--src-stamp 20261015]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("OMP_NUM_THREADS", "1")

import build_3cod as B3  # noqa: E402  entry_id_of
import build_dbs as B    # noqa: E402  ISOTOPE_TO_H / is_inorganic
from fastcif import parse_cif  # noqa: E402


def _load_valid_els():
    """权威元素表：pymatgen Cromer-Mann 系数表覆盖的 99 元素。"""
    p = os.path.join(BASE, "_atomic_scattering_params.json")
    with open(p, encoding="utf-8") as fh:
        return set(json.load(fh).keys())


VALID_ELS = _load_valid_els()


def site_elements(d):
    """由 CIF 原子位点回推元素集合（ASU 位点即可，展开不引入新元素）。

    同位素 D/T 归一为 H（与 parse_elements 同一规则，ISOTOPE_TO_H）。
    大小写归一：源 CIF 存在 type_symbol='o' 之类的笔误（如 COD 7052302
    的水氧 Ow1），'o'→'O'、'co'→'Co'；归一后不在 99 元素表内的丢弃。
    返回 (排序元素列表, counts dict)。
    """
    els = set()
    for s in d.sites:
        try:
            el = s[1]
        except (IndexError, TypeError):
            continue
        if not el:
            continue
        el = B.ISOTOPE_TO_H.get(el, el)
        # 防御：位点标签若带电荷/氧化态等装饰，只留字母部分
        el = "".join(ch for ch in el if ch.isalpha())
        if not el:
            continue
        el = el[0].upper() + el[1:].lower()
        if el in VALID_ELS:
            els.add(el)
    els = sorted(els)
    return els, {e: 1.0 for e in els}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-stamp", default="20261015")
    args = ap.parse_args()

    full_db = os.path.join(BASE, "3COD-Full-%s.sqlite" % args.src_stamp)
    con = sqlite3.connect("file:%s?mode=ro" % full_db.replace(os.sep, "/"),
                          uri=True, timeout=180)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT e.entry_id, e.formula, e.elements, c.cod_id, c.file "
        "FROM entries e JOIN cod_entries c ON c.cod_id = "
        "CAST(substr(replace(e.entry_id,'-',''),3) AS INTEGER) "
        "WHERE IFNULL(e.elements,'')=''").fetchall()
    print("elements 为空的条目：%d 条" % len(rows), flush=True)

    out, inorg_ids, stat = [], [], {"no_sites": 0, "inorg": 0, "org": 0,
                                    "read_fail": 0, "parse_fail": 0}
    for r in rows:
        cod_id = int(r["cod_id"])
        eid = r["entry_id"]
        # entry_id 反推 cod_id 可能对 8~10 位号段不成立，直接用 cod_entries 的
        parts = (r["file"] or "").replace("\\", "/").split("/")
        rec = {"cod_id": cod_id, "entry_id": eid,
               "lib": parts[0] if len(parts) > 1 else "",
               "rel": "/".join(parts[1:-1]) if len(parts) > 2 else "",
               "name": parts[-1] if parts else "",
               "abs": os.path.join(BASE, *parts) if len(parts) > 1 else "",
               "old_formula": r["formula"]}
        try:
            d = parse_cif(open(rec["abs"], "rb").read()
                          .decode("utf-8", "replace"))
        except Exception as e:
            rec["status"] = "parse_fail(%s)" % type(e).__name__
            rec["site_elements"] = []
            rec["verdict"] = "org(无法判定)"
            stat["parse_fail"] += 1
            out.append(rec)
            continue
        els, counts = site_elements(d)
        rec["site_elements"] = els
        if not els:
            rec["status"] = "no_sites"
            rec["verdict"] = "org(无位点可判)"
            stat["no_sites"] += 1
            out.append(rec)
            continue
        if B.is_inorganic(counts):
            rec["status"] = "reclassified"
            rec["verdict"] = "INORG(位点回推)"
            rec["elements"] = ",".join(els)
            inorg_ids.append(cod_id)
            stat["inorg"] += 1
        else:
            rec["status"] = "confirmed_org"
            rec["verdict"] = "org(位点确证含C且含H)"
            rec["elements"] = ",".join(els)
            stat["org"] += 1
        out.append(rec)
    con.close()

    os.makedirs(os.path.join(BASE, "sync_logs"), exist_ok=True)
    jp = os.path.join(BASE, "sync_logs", "inorg_v2_gap_20261016.json")
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump({"stat": stat, "rows": out}, fh, ensure_ascii=False, indent=1)
    ep = os.path.join(BASE, "sync_logs", "org_exclude_20261016.json")
    with open(ep, "w", encoding="utf-8") as fh:
        json.dump({"cod_ids": inorg_ids}, fh, ensure_ascii=False)
    print("判定结果：%s" % json.dumps(stat, ensure_ascii=False))
    print("  → 转入无机（Org 排除 / Inorg-v2 收录）：%d 条" % len(inorg_ids))
    for rec in out:
        if rec.get("status") == "reclassified":
            print("    cod_id=%-10d %-16s 位点元素=%s"
                  % (rec["cod_id"], rec["verdict"], ",".join(rec["site_elements"])))
    print("已写 %s / %s" % (jp, ep))


if __name__ == "__main__":
    main()
