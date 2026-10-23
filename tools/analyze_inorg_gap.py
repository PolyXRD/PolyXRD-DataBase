#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化并归因「清单判无机 / 产物未收录」的缺口（E-4）。

对比集合：
  清单侧  inorg_manifest.files WHERE is_inorg=1        （驱动 inorg_cif 复制的口径）
  产物侧  分片 p*_inorg.sqlite 的 entries.entry_id     （即 3COD-Inorg 实际收录）

产物侧取分片而非 22 GB 成品库：两者 entries 行数一致，但分片读取代价小一个量级。

对每条缺口文件逐条核实：是否有 _chemical_formula_sum / _chemical_formula_structural
标签、_atom_site_type_symbol 能给出哪些元素 —— 用以判断「能否修复」以及化学本质。

用法:
    python analyze_inorg_gap.py [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = os.path.join(BASE, "_3cod_parts")
MANIFEST = os.path.join(BASE, "inorg_manifest.sqlite")

RE_SUM = re.compile(r"^\s*_chemical_formula_sum\s+(.*?)\s*$", re.M)
RE_STRUCT = re.compile(r"^\s*_chemical_formula_structural\s+(.*?)\s*$", re.M)

RE_EL = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")


def site_elements_from_cif(text):
    """从 CIF 提取 _atom_site_type_symbol 的元素集合。

    ⚠️ 它绝大多数出现在 **loop 列头**，值在后续数据行（每行第一个 token），
    而非"标签 + 同行值"。只匹配同行值会漏掉几乎所有条目（实测 421/452 误报为
    "位点不可判无机"）。
    """
    lines = text.splitlines()
    els = []
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("_atom_site_type_symbol"):
            continue
        rest = s[len("_atom_site_type_symbol"):].strip()
        if rest:                                  # 少见：同行给值
            toks = [rest]
        else:                                     # 常见：loop 列头，读后续数据行
            # 多列 loop 的列头是**连续多个 `_` 行**，须全部跳过，数据行在最后一个列头之后
            j = idx + 1
            while j < len(lines) and lines[j].strip().startswith("_"):
                j += 1
            toks = []
            for ln2 in lines[j:]:
                t = ln2.strip()
                if not t or t.startswith("_") or t.startswith("loop_") \
                        or t.startswith("#") or t.lower().startswith("data_"):
                    break
                if t[:1] in ("'", '"'):
                    m = re.match(r"(['\"])(.*?)\1", t)
                    tok = m.group(2) if m else t
                else:
                    tok = t.split()[0]
                toks.append(tok)
            # loop 情况下遇到 `_`/`loop_`/`#` 已 break，无需再过滤
            toks = toks
        for tok in toks:
            m = RE_EL.match(tok)
            if m:
                els.append(m.group(1))
        break
    return sorted(set(els))


def eid_to_cod(eid):
    s = eid.split("-")
    return int(s[1] + s[2])


def load_db_ids():
    ids = set()
    for p in sorted(glob.glob(os.path.join(PARTS, "p*_inorg.sqlite"))):
        con = sqlite3.connect("file:%s?mode=ro" % p.replace(os.sep, "/"),
                              uri=True, timeout=60)
        for (eid,) in con.execute("SELECT entry_id FROM entries"):
            try:
                ids.add(eid_to_cod(eid))
            except Exception:
                pass
        con.close()
    return ids


def load_manifest():
    con = sqlite3.connect("file:%s?mode=ro" % MANIFEST.replace(os.sep, "/"),
                          uri=True, timeout=60)
    man = {cid: (lib, rel) for cid, lib, rel in
           con.execute("SELECT cod_id, lib, rel FROM files")}
    inorg = {c for (c,) in con.execute("SELECT cod_id FROM files WHERE is_inorg=1")}
    tot = len(man)
    con.close()
    return man, inorg, tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(
        BASE, "sync_logs", "inorg_gap_20261015.json"))
    args = ap.parse_args()

    print("读分片 entries（产物侧）...")
    db_ids = load_db_ids()
    print("  产物 entries = %d" % len(db_ids))
    man, man_inorg, man_tot = load_manifest()
    print("  清单 total = %d  无机 = %d" % (man_tot, len(man_inorg)))

    only_man = man_inorg - db_ids     # 清单无机、产物未收录
    only_db = db_ids - man_inorg      # 产物收录、清单判非无机
    print()
    print("清单无机 / 产物未收录 : %d" % len(only_man))
    print("产物收录 / 清单非无机 : %d" % len(only_db))

    rows = []
    for tag, ids in (("MAN_ONLY", only_man), ("DB_ONLY", only_db)):
        for cid in sorted(ids):
            lib, rel = man[cid]
            p = os.path.join(BASE, lib, rel.replace("\\", "/"))
            try:
                text = open(p, "rb").read().decode("utf-8", "replace")
            except OSError:
                rows.append(dict(tag=tag, cod_id=cid, lib=lib, rel=rel,
                                 err="读文件失败"))
                continue
            fsum = (RE_SUM.search(text) or [None, ""])[1].strip()
            fstr = (RE_STRUCT.search(text) or [None, ""])[1].strip()
            els = site_elements_from_cif(text)
            rows.append(dict(tag=tag, cod_id=cid, lib=lib, rel=rel,
                             formula_sum=fsum[:120], formula_struct=fstr[:120],
                             n_typesym=len(els), site_elements=",".join(els),
                             has_c=("C" in els), has_h=("H" in els),
                             site_inorg=(bool(els) and (not ("C" in els)
                                                        or not ("H" in els)))))

    print()
    print("%-9s %-11s %-5s %-9s %-9s %-24s %s"
          % ("方向", "cod_id", "库", "有sum", "有结构式", "位点元素", "位点判无机"))
    for r in rows[:30]:
        print("%-9s %-11d %-5s %-9s %-9s %-24s %s"
              % (r["tag"], r["cod_id"], r["lib"],
                 "是" if r.get("formula_sum") else "否",
                 "是" if r.get("formula_struct") else "否",
                 r.get("site_elements", "")[:24], r.get("site_inorg")))

    agg = collections.Counter()
    for r in rows:
        if r.get("err"):
            agg[(r["tag"], "读文件失败")] += 1
            continue
        if not r["formula_sum"]:
            k = "无formula标签"
        elif not r["site_elements"]:
            k = "有formula标签"
        else:
            k = "有formula标签"
        # 位点口径细分：根本没有位点 / 位点判无机 / 位点判有机
        if not r["site_elements"]:
            sub = "无 _atom_site_type_symbol"
        elif r["site_inorg"]:
            sub = "位点判无机"
        else:
            sub = "位点判有机(同时含C与H)"
        agg[(r["tag"], k, sub)] += 1
    print()
    print("归因（方向 × formula标签 × 位点口径）：")
    for k in sorted(agg, key=lambda x: -agg[x]):
        print("   %-10s %-14s %-22s %d" % (k[0], k[1], k[2], agg[k]))

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(dict(n_db=len(db_ids), n_man_inorg=len(man_inorg),
                       n_only_man=len(only_man), n_only_db=len(only_db),
                       rows=rows), fh, ensure_ascii=False, indent=1)
    print()
    print("明细已写出 %s（%d 条）" % (args.json, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
