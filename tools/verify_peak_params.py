#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反推 PolyXRD 无机库 peaks_d/peaks_i 的生成参数。

取 COD_inorganics.sqlite 中已有条目，用 pymatgen XRDCalculator 重算，
与库内峰表比对（峰数、前若干个 d、最大强度），确认可复现后用于新库建库。
"""
import gzip
import sqlite3
import sys
import warnings

DB = "E:/TEMP/PolyXRD/cod_data/COD_inorganics.sqlite"


def main():
    from pymatgen.io.cif import CifParser
    from pymatgen.analysis.diffraction.xrd import XRDCalculator

    conn = sqlite3.connect("file:%s?mode=ro" % DB.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT cod_id, formula, space_group, cell_a, peaks_d, peaks_i, n_peaks, cif_gz "
        "FROM phases WHERE cif_gz IS NOT NULL AND n_peaks BETWEEN 50 AND 500 "
        "ORDER BY cod_id LIMIT 6").fetchall()
    conn.close()

    for wl, tth in ((1.5406, (5.0, 90.0)), (1.540598, (5.0, 90.0))):
        print("=" * 78)
        print("wavelength=%s  2theta=%s" % (wl, tth))
        for r in rows:
            try:
                txt = gzip.decompress(r["cif_gz"]).decode("utf-8", "replace")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    st = CifParser.from_str(txt, occupancy_tolerance=1.2).parse_structures(
                        primitive=False)[0]
                calc = XRDCalculator(wavelength=wl)
                pat = calc.get_pattern(st, two_theta_range=tth)
            except Exception as e:
                print("  cod_id=%s  解析失败: %s" % (r["cod_id"], e))
                continue
            n = len(pat.x)
            imax = max(pat.y) or 1.0
            i_norm = [1000.0 * v / imax for v in pat.y]
            # d 值
            import math
            d = [wl / (2 * math.sin(math.radians(t / 2))) for t in pat.x]
            lib_d = [float(x) for x in (r["peaks_d"] or "").split(",") if x]
            lib_i = [float(x) for x in (r["peaks_i"] or "").split(",") if x]
            print("  cod_id=%-9s 库内 n=%-4d 重算 n=%-4d  库内首d=%.4f 重算首d=%.4f  "
                  "库内末d=%.4f 重算末d=%.4f  库内Imax=%.1f"
                  % (r["cod_id"], r["n_peaks"], n,
                     lib_d[0] if lib_d else 0, d[0] if d else 0,
                     lib_d[-1] if lib_d else 0, d[-1] if d else 0,
                     max(lib_i) if lib_i else 0))
            # 前 6 个 d 比对
            print("     库内   :", ["%.4f" % v for v in lib_d[:6]])
            print("     库内I  :", ["%.1f" % v for v in lib_i[:6]])
            print("     重算   :", ["%.4f" % v for v in d[:6]])
            print("     重算I  :", ["%.1f" % v for v in i_norm[:6]])


if __name__ == "__main__":
    sys.exit(main())
