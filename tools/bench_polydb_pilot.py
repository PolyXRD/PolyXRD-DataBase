#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polyDB 试产基准：实测「CIF 解析 + 峰计算 + 打包」的吞吐与产物规模。

用途
----
在正式量产（53 万条 COD CIF）之前，用小样本把三件事定死：
  1. 单条耗时（parse / peaks / 打包），据此推算全量工期与并行度；
  2. 每相峰数、位点数分布，据此推算 polyDB 各段体积；
  3. 峰口径与旧库是否逐条一致（--parity 模式，对 COD_inorganics.sqlite 抽样比对）。

峰口径（必须与 build_3cod.py 头部"峰口径"逐字一致）:
    λ=1.5406 Å, d≥1.0 Å (2θ 5~100.76°), 等价反射按 2θ 合并, I 归一 max=1000, 取前 100。

用法
----
    python tools/bench_polydb_pilot.py --n 60 --scope inorg
    python tools/bench_polydb_pilot.py --n 60 --scope all --json out.json
    python tools/bench_polydb_pilot.py --n 200 --scope inorg --parity
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COD_DIR = os.path.join(BASE, "COD")
MANIFEST = os.path.join(BASE, "inorg_manifest.sqlite")

WAVELENGTH = 1.5406
TTH_MIN = 5.0
TTH_MAX = math.degrees(2.0 * math.asin(min(1.0, WAVELENGTH / (2.0 * 1.0))))
SCALE = 1000.0
TOP_PEAKS = 100          # 与 build_3cod.TOP_POLY 一致
MAX_SITES_FOR_PEAKS = 1500
MAX_CELL_VOL_FOR_PEAKS = 30000
MAX_HKL = 30_000

#: polyDB 打包后的每峰字节（d: float32 + I: uint16）
BYTES_PER_PEAK = 6
#: polyDB 打包后的每位点字节（element: u8 + xyz: 3×f32 + occ: f32）
BYTES_PER_SITE = 17
#: d 分箱位图参数
BIN_WIDTH = 0.05
D_MIN, D_MAX = 0.4, 25.0
N_BINS = int((D_MAX - D_MIN) / BIN_WIDTH) + 1


def sample_rows(scope: str, n: int) -> list[tuple[int, str]]:
    """从 manifest 取 COD 样本（inorg=仅无机 / all=全量 / org=仅有机）。"""
    con = sqlite3.connect("file:%s?mode=ro" % MANIFEST, uri=True)
    where = {"inorg": "AND is_inorg=1", "org": "AND is_inorg=0", "all": ""}[scope]
    sql = ("SELECT cod_id, rel FROM files WHERE lib='COD' %s "
           "ORDER BY cod_id LIMIT ?" % where)
    rows = con.execute(sql, (n,)).fetchall()
    con.close()
    return [(int(c), str(r).replace("\\", "/")) for c, r in rows]


def process_one(cod_id: int, rel: str) -> dict:
    """处理单条 CIF，返回耗时与产物统计。"""
    path = os.path.join(COD_DIR, rel)
    t0 = time.perf_counter()
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8", errors="replace")
    except OSError as e:
        return {"cod_id": cod_id, "ok": False, "stage": "read", "err": str(e)}
    try:
        d = parse_cif(text)
    except Exception as e:  # noqa: BLE001 - 基准要统计失败率，不能崩
        return {"cod_id": cod_id, "ok": False, "stage": "parse",
                "err": "%s: %s" % (type(e).__name__, e)}
    t1 = time.perf_counter()

    vol = getattr(d, "volume", 0.0) or 0.0
    n_sites = 0
    n_peaks = 0
    peaks = None
    if vol and vol <= MAX_CELL_VOL_FOR_PEAKS and d.sites:
        try:
            coords, sp_list, _ = expand_sites(d.sites, d.symops)
            n_sites = len(sp_list)
            if 0 < n_sites <= MAX_SITES_FOR_PEAKS:
                rows, syms, occs = [], [], []
                for coord, sp in zip(coords, sp_list):
                    for el, o in sp.items():
                        o = float(o)
                        rows.append(coord)
                        syms.append(el)
                        occs.append(min(o, 1.0) if o > 0 else 1.0)
                dd, ii = FX.compute_pattern_arrays(
                    d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                    np.asarray(rows, dtype=float), syms, occs,
                    wavelength=WAVELENGTH, tth_range=(TTH_MIN, TTH_MAX),
                    max_hkl=MAX_HKL, half_sphere=True, scale=SCALE,
                    max_peaks=TOP_PEAKS)
                d_arr = np.asarray(dd, dtype=np.float64)
                i_arr = np.asarray(ii, dtype=np.float64)
                n_peaks = int(d_arr.size)
                if n_peaks:
                    peaks = (d_arr, i_arr)
        except Exception as e:  # noqa: BLE001
            return {"cod_id": cod_id, "ok": False, "stage": "peaks",
                    "err": "%s: %s" % (type(e).__name__, e),
                    "t_parse_ms": (t1 - t0) * 1e3}
    t2 = time.perf_counter()
    return {"cod_id": cod_id, "ok": peaks is not None,
            "t_parse_ms": (t1 - t0) * 1e3,
            "t_peaks_ms": (t2 - t1) * 1e3,
            "n_peaks": n_peaks, "n_sites": n_sites,
            "peaks": peaks}


def parity_check(peaks_by_id: dict, limit: int = 200) -> dict:
    """与现有 COD_inorganics.sqlite 逐条比对 d/I（同一峰口径应完全一致）。"""
    db = r"D:/Project/XRD/PolyXRD/cod_data/COD_inorganics.sqlite"
    if not os.path.exists(db):
        return {"available": False, "reason": "no_db"}
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    n = 0
    n_zero = 0
    worst_d = 0.0
    worst_i = 0.0
    for cod_id, (d_arr, i_arr) in list(peaks_by_id.items())[:limit]:
        row = con.execute(
            "SELECT peaks_d, peaks_i FROM phases WHERE cod_id=?", (cod_id,)
        ).fetchone()
        if not row or not row[0]:
            continue
        rd = np.fromstring(row[0], dtype=np.float64, sep=",")
        ri = np.fromstring(row[1], dtype=np.float64, sep=",")
        m = min(len(rd), len(d_arr))
        if m == 0:
            n_zero += 1
            continue
        worst_d = max(worst_d, float(np.max(np.abs(rd[:m] - d_arr[:m]))))
        worst_i = max(worst_i, float(np.max(np.abs(ri[:m] - i_arr[:m]))))
        n += 1
    con.close()
    return {"available": True, "compared": n, "missing_in_old": n_zero,
            "max_abs_d": worst_d, "max_abs_i": worst_i}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--scope", choices=("inorg", "org", "all"), default="inorg")
    ap.add_argument("--json", default="")
    ap.add_argument("--parity", action="store_true")
    args = ap.parse_args(argv)

    rows = sample_rows(args.scope, args.n)
    print("sample: %d (scope=%s)" % (len(rows), args.scope))

    t_all = time.perf_counter()
    stats = [process_one(c, r) for c, r in rows]
    wall = time.perf_counter() - t_all

    ok = [s for s in stats if s.get("ok")]
    fail = [s for s in stats if not s.get("ok")]
    stages: dict[str, int] = {}
    for s in fail:
        stages[s.get("stage", "?")] = stages.get(s.get("stage", "?"), 0) + 1

    n = max(1, len(ok))
    tp = sum(s.get("t_parse_ms", 0.0) for s in ok) / n
    tk = sum(s.get("t_peaks_ms", 0.0) for s in ok) / n
    npk = sum(s.get("n_peaks", 0) for s in ok) / n
    nst = sum(s.get("n_sites", 0) for s in ok) / n

    # 全量外推：按 manifest 的 COD 条数
    con = sqlite3.connect("file:%s?mode=ro" % MANIFEST, uri=True)
    tot = con.execute("SELECT COUNT(*) FROM files WHERE lib='COD'").fetchone()[0]
    tot_i = con.execute(
        "SELECT COUNT(*) FROM files WHERE lib='COD' AND is_inorg=1").fetchone()[0]
    con.close()

    per = tp + tk
    out = {
        "sample": len(rows), "ok": len(ok), "fail": len(fail),
        "fail_stages": stages,
        "ms_parse": round(tp, 2), "ms_peaks": round(tk, 2),
        "ms_per_cif": round(per, 2),
        "avg_peaks": round(npk, 1), "avg_sites": round(nst, 1),
        "n_COD": tot, "n_COD_inorg": tot_i,
        "est_core_hours_full": round(tot * per / 3.6e6, 2),
        "est_core_hours_inorg": round(tot_i * per / 3.6e6, 2),
        "est_size_mb": {
            "full_peaks": round(tot * npk * BYTES_PER_PEAK / 2**20, 1),
            "full_bins": round(N_BINS * math.ceil(tot / 8) / 2**20, 1),
            "full_sites": round(tot * nst * BYTES_PER_SITE / 2**20, 1),
            "inorg_peaks": round(tot_i * npk * BYTES_PER_PEAK / 2**20, 1),
            "inorg_bins": round(N_BINS * math.ceil(tot_i / 8) / 2**20, 1),
            "inorg_sites": round(tot_i * nst * BYTES_PER_SITE / 2**20, 1),
        },
        "bins": N_BINS,
    }
    if args.parity:
        out["parity"] = parity_check(
            {s["cod_id"]: s["peaks"] for s in ok if s.get("peaks")})

    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("wall %.1f s for %d cifs" % (wall, len(rows)))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
