# -*- coding: utf-8 -*-
"""
MP polyDB 验收脚本（L3 精度层 + 元数据一致性）

与 PolyXRD-DataBase/tools/verify_polydb.py（结构层）互补：
  · 结构层：段齐全 / 校验和 / 形状 / row_idx 排列 —— 直接跑官方校验器
  · 精度层：抽样相 → 取侧车位点 + entries.space_group → 按运行时契约展开成
            全胞 → fastxrd 重算峰 → 与库内 peaks_d/peaks_i 逐条比对
  · 元数据：eid ↔ 源 CIF 头 mp-id ↔ formula 三者一致

用法:
    python verify/verify_mp_polydb.py <db.polyDB> --sample 100
"""
import sys, os, json, math, random, argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = HERE
POLYXRD = os.environ.get("POLYXRD_ROOT") or os.path.join(os.path.dirname(os.path.dirname(HERE)), "PolyXRD")
MP_CIF = os.environ.get("XRD_MP_CIF_DIR") or os.path.join(os.path.dirname(os.path.dirname(HERE)), "MP-summary", "cif")
sys.path.insert(0, os.path.join(POLYXRD, "src"))
sys.path.insert(0, TOOLS)

from polyxrd.services.polydb import PolyDatabase, probe  # noqa: E402
from polyxrd.services.phase_cif import expand_sites_by_symmetry  # noqa: E402
import fastxrd as FX  # noqa: E402

LAMBDA = 1.5406
TTH_MIN = 5.0
TTH_MAX = math.degrees(2.0 * math.asin(min(1.0, LAMBDA / 2.0)))
D_TOL = 2e-4
I_TOL = 0.05


def recompute(ph, sites):
    exp = expand_sites_by_symmetry(sites, ph["space_group"])
    if not exp:
        return None, "expand_failed"
    rr, ss, oo = [], [], []
    for s in exp:
        rr.append((s["x"], s["y"], s["z"]))
        ss.append(s["element"])
        oo.append(min(float(s.get("occupancy") or 1.0), 1.0))
    out = FX.compute_pattern_arrays(
        ph["cell_a"], ph["cell_b"], ph["cell_c"],
        ph["cell_alpha"], ph["cell_beta"], ph["cell_gamma"],
        np.asarray(rr, dtype=float), ss, oo,
        wavelength=LAMBDA, tth_range=(TTH_MIN, TTH_MAX),
        max_hkl=30000, half_sphere=True, scale=1000.0, max_peaks=500)
    if not out or len(out) != 2:
        return None, "no_pattern"
    return out, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    FX._load_params()
    ok, msg = probe(args.db)
    print("probe:", ok, msg)
    if not ok:
        return 2
    res = {"db": args.db, "ok": True, "checks": {}, "fail": [], "warn": []}

    def fail(m):
        res["fail"].append(m); res["ok"] = False; print("  [FAIL]", m)

    with PolyDatabase(args.db) as P:
        n = len(P)
        st = P.stats()
        res["checks"]["phases"] = n
        res["checks"]["meta_phases"] = st.phases
        if n != st.phases:
            fail("len(P)=%d != meta.phases=%d" % (n, st.phases))
        print("  phases=%d peaks=%s sites=%s" % (n, st.peaks, st.sites))

        rng = random.Random(20261031)
        rows = sorted(rng.sample(range(n), min(args.sample, n)))
        worst_d = worst_i = 0.0
        n_cmp = 0
        mp_mismatch = []
        formula_mismatch = []
        expand_fail = 0
        for r in rows:
            eid = P.eid_of_row(r)
            ph = P.get_phase(eid)
            sites = P.get_atomic_sites(eid)
            if not ph or not sites:
                fail("row %d 取不到元数据/位点" % r)
                continue
            # eid ↔ CIF 头 mp-id
            cif = os.path.join(MP_CIF, os.path.basename(ph["cif_rel"]))
            if os.path.exists(cif):
                with open(cif, "r", encoding="utf-8", errors="replace") as fh:
                    head = fh.read(300)
                mm = head.split("|")[0]
                mid = mm.split(":")[1].strip() if ":" in mm else ""
                want = int(mid[3:]) if mid.startswith("mp-") else 900_000_000 + int(mid.split("-")[1])
                if want != eid:
                    mp_mismatch.append((ph["cif_rel"], mid, eid))
            # 文件名 ↔ formula
            stem = os.path.splitext(os.path.basename(ph["cif_rel"]))[0]
            if stem != ph["formula"] and stem != ph["formula"] + "_1":
                formula_mismatch.append((ph["cif_rel"], ph["formula"]))

            out, err = recompute(ph, sites)
            if out is None:
                expand_fail += 1
                fail("row %d (%s) 重算失败: %s" % (r, ph["cif_rel"], err))
                continue
            d_ref = np.asarray(out[0], dtype=np.float64)
            i_ref = np.asarray(out[1], dtype=np.float64)
            if d_ref.size == 0:
                fail("row %d (%s) 重算空峰" % (r, ph["cif_rel"]))
                continue
            k = st.k
            order = np.argsort(-i_ref, kind="stable")[:k]
            d_exp = d_ref[order]
            i_exp = np.clip(np.rint(i_ref[order] / 1000.0 * 65535.0), 0, 65535) / 65535.0 * 1000.0
            d_lib = np.asarray(ph["peaks_d_list"], dtype=np.float64)
            i_lib = np.asarray(ph["peaks_i_list"], dtype=np.float64)
            m = min(d_lib.size, d_exp.size)
            if m == 0:
                fail("row %d 峰数为 0" % r)
                continue
            dd = float(np.max(np.abs(np.sort(d_lib[:m]) - np.sort(d_exp[:m]))))
            # 强度按 d 对齐后比较
            oi = np.argsort(d_lib[:m]); oj = np.argsort(d_exp[:m])
            di = float(np.max(np.abs(i_lib[:m][oi] - i_exp[:m][oj])))
            worst_d = max(worst_d, dd); worst_i = max(worst_i, di); n_cmp += 1

        res["checks"].update({
            "sample": len(rows), "compared": n_cmp,
            "max_abs_d": worst_d, "max_abs_i": worst_i,
            "expand_fail": expand_fail,
            "mp_id_mismatch": len(mp_mismatch),
            "formula_mismatch": len(formula_mismatch),
        })
        print("  L3: compared=%d max|Δd|=%.2e max|ΔI|=%.3f" % (n_cmp, worst_d, worst_i))
        if n_cmp and worst_d > D_TOL:
            fail("L3 d 偏差 %.2e > %.1e" % (worst_d, D_TOL))
        if n_cmp and worst_i > I_TOL:
            fail("L3 I 偏差 %.3f > %.2f" % (worst_i, I_TOL))
        if mp_mismatch:
            fail("eid ↔ CIF 头 mp-id 不一致 %d 例: %s" % (len(mp_mismatch), mp_mismatch[:3]))
        if formula_mismatch:
            fail("文件名 ↔ formula 不一致 %d 例: %s" % (len(formula_mismatch), formula_mismatch[:3]))
        if expand_fail:
            fail("侧车展开失败 %d 例" % expand_fail)

    print("RESULT:", "PASS" if res["ok"] else "FAIL",
          "| phases=%d compared=%d" % (res["checks"]["phases"], res["checks"]["compared"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
