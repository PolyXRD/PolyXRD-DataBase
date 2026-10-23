#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastcif import parse_cif, build_structure, _symop_strings, _atom_site_rows

path = sys.argv[1] if len(sys.argv) > 1 else "E:/rsync-COD/COD/3/00/00/3000034.cif"
txt = open(path, "r", encoding="utf-8", errors="replace").read()
print("文件:", path, "大小", len(txt))

d = parse_cif(txt)
print("fastcif: ok=%s a=%s b=%s c=%s sg=%r sg_num=%s formula=%r"
      % (d.ok, d.a, d.b, d.c, d.sg_name, d.sg_number, d.formula))
print("  symops(%d):" % len(d.symops), d.symops[:4])
print("  sites(%d):" % len(d.sites), d.sites[:4])
st = build_structure(d)
print("  structure 原子数:", None if st is None else len(st))

from pymatgen.io.cif import CifParser
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        st_pm = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(primitive=False)[0]
        print("pymatgen 原子数:", len(st_pm))
        print("  pm 前 5 位点:", [(str(s.specie), [round(v, 4) for v in s.frac_coords]) for s in st_pm[:5]])
    except Exception as e:
        print("pymatgen 失败:", e)
