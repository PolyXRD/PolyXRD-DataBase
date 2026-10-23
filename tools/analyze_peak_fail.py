#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计峰计算失败的原因分布（抽样），判断哪些是"可归一化救回"的。

失败路径（fastxrd.compute_pattern_arrays）：
  A. params 表（99 元素）里没有该符号           → ValueError 缺少散射因子系数
  B. fastxrd._Z（H..Cm，96 个）里没有该符号      → KeyError
  C. 其它（内存/网格过大/无坐标等）

抽样：从 inorg_manifest 按库随机取 N 条，跑 fastcif 解析 + 对称展开，
对展开后的元素符号集合做归类。
"""
import os
import random
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = set(FX._load_params())
ZS = set(FX._Z)
ELEM = set("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
           "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
           "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg "
           "Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg "
           "Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split())


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    random.seed(20261015)
    con = sqlite3.connect(os.path.join(BASE, "inorg_manifest.sqlite"))
    rows = con.execute("SELECT lib, rel FROM files").fetchall()
    random.shuffle(rows)
    rows = rows[:n]
    print("抽样 %d 条（三库混合）" % len(rows))
    print("params 表元素数 = %d ； _Z 元素数 = %d" % (len(PARAMS), len(ZS)))

    cnt = {}
    bad_syms = {}
    n_ok = n_fail = 0
    for lib, rel in rows:
        p = os.path.join(BASE, lib, rel.replace("\\", "/"))
        try:
            text = open(p, "rb").read().decode("utf-8", "replace")
            d = parse_cif(text)
            if not (d.ok and d.a and d.b and d.c and d.sites):
                cnt["D_解析失败"] = cnt.get("D_解析失败", 0) + 1
                continue
            coords, sp_list, _ = expand_sites(d.sites, d.symops)
            syms = set()
            for sp in sp_list:
                syms |= set(sp.keys())
            miss_p = syms - PARAMS
            miss_z = syms - ZS
            if miss_p or miss_z:
                n_fail += 1
                for s in (miss_p | miss_z):
                    bad_syms[s] = bad_syms.get(s, 0) + 1
                if all(s in ELEM or (len(s) >= 1 and s[0].upper() + s[1:].lower() in ELEM)
                       for s in (miss_p | miss_z)):
                    k = "A_仅大小写/可归一化"
                elif any(len(s) > 2 or not s[:1].isalpha() for s in (miss_p | miss_z)):
                    k = "C_明显垃圾符号"
                else:
                    k = "B_真元素但表外"
                cnt[k] = cnt.get(k, 0) + 1
            else:
                n_ok += 1
        except Exception as e:
            cnt["E_其它异常:" + type(e).__name__] = cnt.get("E_其它异常:" + type(e).__name__, 0) + 1
    print()
    print("可正常计算 : %d (%.2f%%)" % (n_ok, 100.0 * n_ok / len(rows)))
    print("不可计算   : %d (%.2f%%)" % (n_fail, 100.0 * n_fail / len(rows)))
    print()
    print("分类：")
    for k in sorted(cnt):
        print("   %-24s %d" % (k, cnt[k]))
    print()
    print("出现次数最多的异常元素符号（前 25）：")
    for s, c in sorted(bad_syms.items(), key=lambda kv: -kv[1])[:25]:
        inZ = "在_Z" if s in ZS else "不在_Z"
        inP = "在params" if s in PARAMS else "不在params"
        print("   %-8r %6d   %s %s" % (s, c, inZ, inP))


if __name__ == "__main__":
    main()
