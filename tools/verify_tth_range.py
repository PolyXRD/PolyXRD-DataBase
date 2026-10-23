#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定官方无机库峰表的 2θ 上限与截断规则：对同一批条目用不同 2θ 上限重算，
   与库内 n_peaks / 末 d 值比对，找出最吻合的组合。"""
import gzip
import math
import sqlite3
import warnings

DB = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"
WL = 1.5406


def main():
    from pymatgen.io.cif import CifParser
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT cod_id, n_peaks, peaks_d, cif_gz FROM phases "
        "WHERE cif_gz IS NOT NULL AND n_peaks BETWEEN 100 AND 499 "
        "ORDER BY cod_id LIMIT 8").fetchall()
    conn.close()

    structs = []
    for r in rows:
        try:
            txt = gzip.decompress(r["cif_gz"]).decode("utf-8", "replace")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                st = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                    primitive=False)[0]
        except Exception:
            continue
        lib_d = [float(x) for x in (r["peaks_d"] or "").split(",") if x]
        structs.append((r["cod_id"], r["n_peaks"], lib_d, st))

    for top in (90, 100, 110, 115, 120, 125, 130, 140, 150, 160):
        hits = []
        for cid, n_lib, lib_d, st in structs:
            try:
                calc = XRDCalculator(wavelength=WL)
                pat = calc.get_pattern(st, two_theta_range=(5.0, float(top)))
            except Exception:
                continue
            n_calc = len(pat.x)
            d_calc = [WL / (2 * math.sin(math.radians(t / 2))) for t in pat.x]
            hits.append((cid, n_lib, n_calc, lib_d[-1] if lib_d else 0,
                         d_calc[-1] if d_calc else 0))
        diff_n = sum(abs(h[1] - h[2]) for h in hits)
        diff_d = sum(abs(h[3] - h[4]) for h in hits)
        print("2θ上限=%-4d  峰数总差=%-6d 末d总差=%.4f" % (top, diff_n, diff_d))
        if top in (110, 120, 130):
            for h in hits:
                print("      cod_id=%-9s 库内n=%-4d 算得n=%-4d 库内末d=%.4f 算得末d=%.4f"
                      % h)


if __name__ == "__main__":
    main()
