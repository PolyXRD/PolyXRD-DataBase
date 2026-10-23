#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽样扫描本地 COD / PCOD / TCOD，统计可用于"有机物/无机物"判别的 CIF 字段覆盖率，
   并按化学式规则给出分类分布。

判别依据见 accompanying report；本脚本只做统计，不修改任何数据。
"""
import os
import re
import sys
import csv
import random
from collections import Counter

# ---- 元素周期表：非类金属的非金属元素（其余一律视为金属） ----
NONMETALS = {
    "H", "He", "B", "C", "N", "O", "F", "Ne",
    "Si", "P", "S", "Cl", "Ar",
    "Ge", "As", "Se", "Br", "Kr",
    "Sb", "Te", "I", "Xe",
    "At", "Rn",
}

# 需检测的 CIF 字段（IUPAC coreCIF / pdCIF 常用）
FIELDS = {
    "formula_sum": "_chemical_formula_sum",
    "formula_structural": "_chemical_formula_structural",
    "formula_moiety": "_chemical_formula_moiety",
    "name_common": "_chemical_name_common",
    "name_systematic": "_chemical_name_systematic",
    "compound_source": "_chemical_compound_source",
    "space_group": "_symmetry_space_group_name_H-M",
}

RE_FORMULA = re.compile(r"_chemical_formula_sum\s+('[^']+'|\"[^\"]+\"|[^\s'\"][^\n]*)")
RE_FIELD = {}
for k, v in FIELDS.items():
    RE_FIELD[k] = re.compile(r"(?m)^\s*" + re.escape(v) + r"\b")

RE_ELEMENT = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")

# 氘(D)/氚(T) 在中子衍射结构里替代 H，必须并入 H，否则氘代有机物会被误判为无机
ISOTOPE_TO_H = {"D": "H", "T": "H"}


def parse_formula(text):
    """从 _chemical_formula_sum 文本解析元素集合与计数。返回 dict 或 None。"""
    if not text:
        return None
    t = text.strip().strip("'\"").strip()
    # 去掉 Hill 公式里可能的空格与电荷后缀
    t = t.replace(" ", "")
    if not t:
        return None
    elems = {}
    for sym, cnt in RE_ELEMENT.findall(t):
        if not sym:
            continue
        sym = ISOTOPE_TO_H.get(sym, sym)
        try:
            n = float(cnt) if cnt else 1.0
        except ValueError:
            n = 1.0
        elems[sym] = elems.get(sym, 0.0) + n
    # 丢弃解析失败（例如只剩数字/括号残留）的情况
    if not elems:
        return None
    return elems


def classify(elems):
    """按化学式规则分类。返回类别字符串。"""
    if not elems:
        return "unknown(无formula)"
    e = set(elems.keys())
    metals = e - NONMETALS
    has_c = "C" in e
    has_h = "H" in e
    if has_c and has_h:
        if metals:
            return "organometallic/有机盐"
        return "organic(有机物)"
    if has_c and not has_h:
        return "carbon-inorganic(无机碳)"
    if has_h and not has_c:
        return "inorganic(含H无机物)"
    return "inorganic(无机物)"


def list_dirs(root, depth):
    """列出 root 下固定深度的子目录（相对路径）。"""
    dirs = []
    level = [("", os.path.join(root))]
    for _ in range(depth):
        nxt = []
        for rel, path in level:
            try:
                names = os.listdir(path)
            except OSError:
                continue
            for n in names:
                p = os.path.join(path, n)
                if os.path.isdir(p):
                    r = os.path.join(rel, n) if rel else n
                    nxt.append((r, p))
        level = nxt
        if not level:
            break
    dirs = [r for r, _ in level]
    return dirs


def sample_files(root, n_dirs, per_dir, depth, seed):
    """两阶段抽样：先随机选若干叶子目录，再在目录内随机取文件。"""
    rng = random.Random(seed)
    leaves = list_dirs(root, depth)
    if not leaves:
        leaves = list_dirs(root, depth - 1)
    if not leaves:
        leaves = list_dirs(root, 1)
    rng.shuffle(leaves)
    picked = []
    for d in leaves[:n_dirs]:
        p = os.path.join(root, d)
        try:
            fs = [f for f in os.listdir(p) if f.lower().endswith(".cif")]
        except OSError:
            continue
        if not fs:
            continue
        rng.shuffle(fs)
        for f in fs[:per_dir]:
            picked.append(os.path.join(p, f))
    return picked, len(leaves)


def scan(root, n_dirs, per_dir, depth, seed=20261011):
    files, n_leaves = sample_files(root, n_dirs, per_dir, depth, seed)
    stat = Counter()
    field_hit = Counter()
    examples = {}
    for i, fp in enumerate(files, 1):
        if i % 1000 == 0:
            print("    ... %d/%d" % (i, len(files)), flush=True)
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(400000)      # 化学信息一般在文件前部
        except OSError:
            stat["read_error"] += 1
            continue
        stat["total"] += 1
        for k, rx in RE_FIELD.items():
            if rx.search(head):
                field_hit[k] += 1
        m = RE_FORMULA.search(head)
        elems = parse_formula(m.group(1)) if m else None
        cat = classify(elems)
        stat[cat] += 1
        if cat not in examples and elems:
            examples[cat] = (os.path.relpath(fp, root), "".join(sorted(elems.keys())))
    return stat, field_hit, examples, n_leaves, len(files)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "E:/rsync-COD"
    out_csv = os.path.join(base, "tools", "organic_scan_result.csv")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)

    #           库名   路径                            目录数  每目录  目录深度
    plan = [
        ("COD", os.path.join(base, "COD"), 250, 20, 3),
        ("PCOD", os.path.join(base, "PCOD"), 150, 20, 2),
        ("TCOD", os.path.join(base, "TCOD"), 100, 25, 3),
    ]

    rows = []
    for name, root, nd, per, depth in plan:
        if not os.path.isdir(root):
            print("跳过（目录不存在）: %s" % root)
            continue
        print("扫描 %s ..." % name, flush=True)
        stat, field_hit, ex, n_leaves, n_files = scan(root, nd, per, depth)
        total = stat["total"] or 1
        rows.append({
            "库": name,
            "抽样文件数": n_files,
            "叶子目录总数": n_leaves,
            "_chemical_formula_sum覆盖率%": round(100.0 * field_hit["formula_sum"] / total, 2),
            "_chemical_name_common覆盖率%": round(100.0 * field_hit["name_common"] / total, 2),
            "_chemical_name_systematic覆盖率%": round(100.0 * field_hit["name_systematic"] / total, 2),
            "_chemical_compound_source覆盖率%": round(100.0 * field_hit["compound_source"] / total, 2),
            "organic(有机物)%": round(100.0 * stat["organic(有机物)"] / total, 2),
            "organometallic/有机盐%": round(100.0 * stat["organometallic/有机盐"] / total, 2),
            "carbon-inorganic(无机碳)%": round(100.0 * stat["carbon-inorganic(无机碳)"] / total, 2),
            "inorganic(含H无机物)%": round(100.0 * stat["inorganic(含H无机物)"] / total, 2),
            "inorganic(无机物)%": round(100.0 * stat["inorganic(无机物)"] / total, 2),
            "unknown(无formula)%": round(100.0 * stat["unknown(无formula)"] / total, 2),
        })
        print("  样例:", ex)
        print("  完成:", rows[-1], flush=True)

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("结果已写入:", out_csv)


if __name__ == "__main__":
    main()
