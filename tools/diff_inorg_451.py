#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核实「清单判无机」与「Inorg 库实收」的 451 条差异（只读）。

两侧口径：
  清单侧  inorg_manifest.files WHERE is_inorg=1        -> 1,188,103
          判据：scan_inorg.py 用 _chemical_formula_sum 解析出的元素集
  产物侧  3COD-Inorg-*.sqlite  entries.entry_id        -> 1,187,652
          判据：build_3cod.py 用 fastcif.parse_cif 的 d.formula（可能来自
                _chemical_formula_structural 等其它标签）

差集 451 条逐条回读 CIF，输出：有无 _chemical_formula_sum、位点元素集、
两侧公式，用于判断属于"真实漏收"还是"判据口径差异"。

用法:
    python tools/diff_inorg_451.py [--out sync_logs/xxx.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)

MANIFEST = os.path.join(BASE, "inorg_manifest.sqlite")
DB = os.path.join(BASE, "3COD-Inorg-20261020.sqlite")

RE_SUM = re.compile(r"^\s*_chemical_formula_sum\s+(.*?)\s*$", re.M)
RE_STRUCT = re.compile(r"^\s*_chemical_formula_structural\s+(.*?)\s*$", re.M)
RE_MOIETY = re.compile(r"^\s*_chemical_formula_moiety\s+(.*?)\s*$", re.M)

RE_EL = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")


def entry_id_of(cod_id: int) -> str:
    s = str(int(cod_id)).zfill(7)
    return "96-%s-%s" % (s[:3], s[3:])


def site_elements(text: str) -> list[str]:
    """从 _atom_site_type_symbol 的 loop 列头 + 数据行取元素集合。"""
    lines = text.splitlines()
    out: set[str] = set()
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("_atom_site_type_symbol"):
            continue
        rest = s[len("_atom_site_type_symbol"):].strip()
        if rest:
            toks = [rest]
        else:
            j = idx + 1
            ncol = 1
            # 统计连续 `_` 列头个数（多列 loop），数据行在最后一个列头之后
            while j < len(lines) and lines[j].strip().startswith("_"):
                j += 1
                ncol += 1
            toks = []
            for ln2 in lines[j:]:
                if ln2.strip().startswith("_") or ln2.strip().startswith("loop_"):
                    break
                parts = ln2.split()
                if not parts:
                    continue
                toks.append(parts[0])
                if len(toks) > 5000:
                    break
        for t in toks:
            el = "".join(ch for ch in t if ch.isalpha())
            if not el:
                continue
            el = el[0].upper() + el[1:].lower()
            if len(el) <= 2:
                out.add(el)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        BASE, "sync_logs", "sync20261019", "diff_inorg_451.json"))
    a = ap.parse_args()

    m = sqlite3.connect("file:" + MANIFEST.replace("\\", "/") + "?mode=ro", uri=True)
    man = {r[0]: r for r in m.execute(
        "SELECT cod_id, lib, rel, formula, elements FROM files WHERE is_inorg=1")}
    print(f"清单 is_inorg=1 : {len(man):,}")

    d = sqlite3.connect("file:" + DB.replace("\\", "/") + "?mode=ro", uri=True)
    got = {int(r[0].replace("96-", "").replace("-", "")) for r in
           d.execute("SELECT entry_id FROM entries")}
    print(f"Inorg.entries   : {len(got):,}")

    only_man = sorted(set(man) - got)
    only_db = sorted(got - set(man))
    print(f"清单有/库无     : {len(only_man):,}")
    print(f"库有/清单无     : {len(only_db):,}")

    rows = []
    for cid in only_man:
        _, lib, rel, formula, elements = man[cid]
        p = os.path.join(BASE, "inorg_cif", lib, rel.replace("\\", "/").replace("/", os.sep))
        rec = {"cod_id": cid, "lib": lib, "rel": rel,
               "manifest_formula": formula, "manifest_elements": elements}
        if not os.path.exists(p):
            # 副本缺失时回落到源目录
            p2 = os.path.join(BASE, lib, rel.replace("\\", "/").replace("/", os.sep))
            p = p2 if os.path.exists(p2) else p
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                txt = fh.read(200000)
            rec["has_sum"] = bool(RE_SUM.search(txt))
            rec["sum"] = (RE_SUM.search(txt).group(1).strip()
                          if RE_SUM.search(txt) else "")
            rec["structural"] = (RE_STRUCT.search(txt).group(1).strip()
                                 if RE_STRUCT.search(txt) else "")
            rec["moiety"] = (RE_MOIETY.search(txt).group(1).strip()
                             if RE_MOIETY.search(txt) else "")
            rec["site_elements"] = site_elements(txt)
            rec["file_exists"] = True
        except OSError as e:
            rec["file_exists"] = False
            rec["err"] = str(e)
        rows.append(rec)

    # 归类
    from collections import Counter
    cat = Counter()
    for r in rows:
        if not r.get("file_exists"):
            cat["文件不可读"] += 1
        elif not r.get("has_sum"):
            cat["无 _chemical_formula_sum（位点回推可得元素）"] += 1
        else:
            cat["有 sum 但仍未收录（判据差异）"] += 1
    print("\n分类：")
    for k, v in cat.most_common():
        print(f"  {k}: {v}")

    print("\n前 15 条明细：")
    for r in rows[:15]:
        print(f"  {r['cod_id']} [{r['lib']}] sum={r.get('sum')!r} "
              f"struct={r.get('structural')!r} sites={r.get('site_elements')} "
              f"manifest={r['manifest_formula']!r}")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f"\n明细写入 {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
