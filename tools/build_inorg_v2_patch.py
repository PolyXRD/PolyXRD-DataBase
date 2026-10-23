#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inorg-v2 补丁分片：把「formula 缺失但位点确为无机」的条目补进无机库。

背景（记忆 #19 / E-4）：478 条 CIF 无 `_chemical_formula_sum` → parse_elements
得空 → is_inorganic({})=False → 落进 Org。其中 142 条按 `_atom_site_type_symbol`
回推位点元素确为无机（classify_formula_gap.py 判定，见
sync_logs/inorg_v2_gap_20261016.json / org_exclude_20261016.json）。

本脚本产出 _3cod_parts/p999_v2patch_inorg.sqlite（与既有 inorg 分片同构）：
  XinMatch 侧  entries / peaks / elements —— entries/peaks 行从 Full 成品按
               entry_id 抄录（峰已算好，不重算）；elements 用位点回推值回填
               （Full 里这些条目 elements 为 NULL，正是漏收根因）。
  PolyXRD 侧   cod_atomic_sites(8 列, 无 u_iso) —— 从 Full 成品按 cod_id 抄录；
               phases —— Full 成品无此表，用与 build_3cod.worker 完全相同的
               口径从 CIF 重算（compute_pattern_arrays + top_peaks_of，
               含 vol≤30000 / expand≤1500 守卫）。

随后 Inorg-v2 = B3.merge("_3cod_parts/p*_inorg.sqlite")（补丁按文件名排最后，
与 24 个旧分片一并合并），产物 3COD-Inorg-20261016.sqlite/.db。

用法:
    python tools/build_inorg_v2_patch.py [--src-stamp 20261015]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("OMP_NUM_THREADS", "1")

import build_3cod as B3  # noqa: E402
import build_dbs as B    # noqa: E402  cell_volume
from fastcif import parse_cif, expand_sites  # noqa: E402
from classify_formula_gap import site_elements  # noqa: E402  同一归一化口径
import fastxrd as FX  # noqa: E402


def build_patch(exclude_json: str, src_stamp: str) -> None:
    t0 = time.time()
    with open(exclude_json, encoding="utf-8") as fh:
        cod_ids = json.load(fh)["cod_ids"]
    print("补丁条目（cod_id）：%d" % len(cod_ids), flush=True)

    full_db = os.path.join(BASE, "3COD-Full-%s.sqlite" % src_stamp)
    fs = sqlite3.connect("file:%s?mode=ro" % full_db.replace(os.sep, "/"),
                         uri=True, timeout=180)
    fs.row_factory = sqlite3.Row

    patch_path = os.path.join(B3.PARTS, "p999_v2patch_inorg.sqlite")
    if os.path.exists(patch_path):
        os.remove(patch_path)
    con = sqlite3.connect(patch_path)
    con.executescript(B3.XINMATCH_SQL + B3.POLY_INORG_SQL)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA cache_size=-32768")

    n_ent = n_pk = n_site = n_ph = n_peak_fail = 0
    first_err = None
    for cid in cod_ids:
        eid = B3.entry_id_of(cid)

        # ---- 位点元素（与分类脚本同一口径）----
        rel = fs.execute("SELECT file FROM cod_entries WHERE cod_id=?",
                         (cid,)).fetchone()["file"]
        abs_p = os.path.join(BASE, *rel.replace("\\", "/").split("/"))
        d = parse_cif(open(abs_p, "rb").read().decode("utf-8", "replace"))
        els, _counts = site_elements(d)
        el_str = ",".join(els) if els else None

        # ---- XinMatch entries（Full 行 + elements 回填）----
        er = fs.execute("SELECT * FROM entries WHERE entry_id=?", (eid,)).fetchone()
        if er is None:
            print("  ! cod_id=%d entry_id=%s 不在 Full.entries" % (cid, eid))
            continue
        row = list(er)
        row[er.keys().index("elements")] = el_str
        con.execute("INSERT OR REPLACE INTO entries VALUES (%s)"
                    % ",".join("?" * len(row)), row)
        n_ent += 1
        for el in (els or []):
            con.execute("INSERT OR REPLACE INTO elements VALUES (?,?)", (eid, el))

        # ---- XinMatch peaks（按 entry_id 抄录）----
        for pr in fs.execute("SELECT * FROM peaks WHERE entry_id=?", (eid,)):
            con.execute("INSERT INTO peaks VALUES (?,?,?,?,?,?)", tuple(pr))
            n_pk += 1

        # ---- cod_atomic_sites（9→8 列，丢末列 u_iso）----
        for sr in fs.execute("SELECT * FROM cod_atomic_sites WHERE cod_id=?",
                             (cid,)):
            con.execute("INSERT OR REPLACE INTO cod_atomic_sites VALUES (?,?,?,?,?,?,?,?)",
                        tuple(sr)[:8])
            n_site += 1

        # ---- phases（同 worker 口径从 CIF 重算）----
        vol = d.volume or B.cell_volume(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
        if vol and vol <= B3.MAX_CELL_VOL_FOR_PEAKS and d.sites:
            try:
                coords, sp_list, _ = expand_sites(d.sites, d.symops)
                if 0 < len(sp_list) <= B3.MAX_SITES_FOR_PEAKS:
                    rows_c, syms, occs = [], [], []
                    for coord, sp in zip(coords, sp_list):
                        for el, o in sp.items():
                            o = float(o)
                            rows_c.append(coord)
                            syms.append(el)
                            occs.append(min(o, 1.0) if o > 0 else 1.0)
                    out = FX.compute_pattern_arrays(
                        d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                        np.asarray(rows_c, dtype=float), syms, occs,
                        wavelength=B3.WAVELENGTH,
                        tth_range=(B3.TTH_MIN, B3.TTH_MAX),
                        max_hkl=B3.MAX_HKL, half_sphere=True, scale=B3.SCALE,
                        max_peaks=B3.TOP_POLY, return_hkl=True)
                    if len(out) == 3:
                        dd, ii, _hkl = out
                else:
                    dd = None
            except Exception as e:  # noqa: BLE001 —— 与 worker 同策略：吞并记录
                dd = None
                if first_err is None:
                    first_err = "cod_id=%d %s: %s" % (cid, type(e).__name__, e)
        else:
            dd = None
        if dd is None or len(dd) == 0:
            n_peak_fail += 1
            continue
        d_arr = np.asarray(dd, dtype=np.float64)
        i_arr = np.asarray(ii, dtype=np.float64)
        td, ti = FX.top_peaks_of(d_arr, i_arr, B3.TOP_BLOB)
        con.execute(
            "INSERT OR REPLACE INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, d.formula[:250] if d.formula else None, d.sg_name,
             d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
             int(len(d_arr)),
             ",".join("%.5f" % v for v in d_arr),
             ",".join("%.2f" % v for v in i_arr),
             None, None, eid, eid,
             sqlite3.Binary(np.asarray(td, dtype="<f8").tobytes()),
             sqlite3.Binary(np.asarray(ti, dtype="<f8").tobytes()),
             None))
        n_ph += 1
    fs.close()

    con.execute("INSERT OR REPLACE INTO meta VALUES ('shard_done','1')")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('kind','inorg-v2-patch')")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('entries',?)", (str(n_ent),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('phases',?)", (str(n_ph),))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('peak_fail',?)",
                (str(n_peak_fail),))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("补丁完成：entries %d, peaks %d, sites %d, phases %d, peak_fail %d, %.1f s"
          % (n_ent, n_pk, n_site, n_ph, n_peak_fail, time.time() - t0))
    if first_err:
        print("首个峰失败详情：%s" % first_err)
    if n_peak_fail > max(1, int(0.2 * len(cod_ids))):
        raise SystemExit("!! 峰失败率超 20%%（%d/%d），中止——先排查再合并"
                         % (n_peak_fail, len(cod_ids)))


def merge_inorg_v2(src_stamp: str) -> None:
    """旧 24 分片 + 补丁 → 3COD-Inorg-20261016.sqlite（复用 B3.merge 全链）。"""
    target = os.path.join(BASE, "3COD-Inorg-20261016.sqlite")
    n = B3.merge(target, os.path.join(BASE, "_3cod_parts", "p*_inorg.sqlite"),
                 B3.XINMATCH_SQL + B3.POLY_INORG_SQL,
                 B3.XIN_IDX + B3.INORG_IDX, "inorg", vacuum=True)
    print("Inorg-v2 合并完成：phases %s" % f"{n:,}")
    import hashlib
    # 单一格式交付（2026-10-18 用户决定）：只出 .sqlite，不再复制 .db。
    for p in (target,):
        h = hashlib.md5()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        print("产物 %-30s %s B  md5=%s"
              % (os.path.basename(p), format(os.path.getsize(p), ","),
                 h.hexdigest()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-stamp", default="20261015")
    ap.add_argument("--exclude", default=os.path.join(
        BASE, "sync_logs", "org_exclude_20261016.json"))
    ap.add_argument("--merge-only", action="store_true")
    args = ap.parse_args()
    if not args.merge_only:
        build_patch(args.exclude, args.src_stamp)
    merge_inorg_v2(args.src_stamp)


if __name__ == "__main__":
    main()
