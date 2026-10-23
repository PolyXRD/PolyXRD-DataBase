#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比 fastcif 与 CifParser 的元素计数，定位组成差异来源。"""
import sys, os, warnings, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastcif import parse_cif, build_structure

for path in sys.argv[1:]:
    txt = open(path, "r", encoding="utf-8", errors="replace").read()
    d = parse_cif(txt)
    st_fx = build_structure(d)
    from pymatgen.io.cif import CifParser
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            st_pm = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                primitive=False)[0]
        except Exception as e:
            print(path, "pm 失败", e)
            continue

    def amt(st):
        c = collections.Counter()
        for site in st:
            for sp, occ in site.species.items():
                sym = getattr(getattr(sp, "element", sp), "symbol", str(sp))
                c[sym] += occ
        return c

    a_pm, a_fx = amt(st_pm), amt(st_fx)
    print("=" * 70)
    print(os.path.basename(path), "原子数 pm=%d fx=%d" % (len(st_pm), len(st_fx)))
    keys = sorted(set(a_pm) | set(a_fx))
    for k in keys:
        v1, v2 = a_pm.get(k, 0), a_fx.get(k, 0)
        flag = "" if abs(v1 - v2) < 1e-6 else "   <<<< 差异"
        print("   %-4s pm=%12.4f  fx=%12.4f%s" % (k, v1, v2, flag))
    print("   symops: fx=%d, sites=%d, sg=%r" % (len(d.symops), len(d.sites), d.sg_name))
