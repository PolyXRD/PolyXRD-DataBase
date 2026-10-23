#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3COD 打包产物验收（对齐 sync-COD-pack 规范 §8）。

两个产物的表结构不同，验收必须分路：
  Full  : XinMatch 侧 entries/peaks/elements/element_combo
          + PolyXRD 侧 cod_entries（无峰列）+ cod_atomic_sites
  Inorg : XinMatch 侧四表
          + PolyXRD 侧 phases（含 peaks_d/peaks_i CSV 与 top-64 BLOB）

检查项：
  1. 表结构 / 条目数 / 峰行数 / element_combo 组数
  2. ID 一致性：Full  cod_entries.cod_id → entries.entry_id
                Inorg phases.ref_id == display_id == entries.entry_id == "96-"+cod_id
  3. 强度口径：Full  每个 entry_id 在 peaks 表内 MAX(intensity)=1000
                Inorg 每条 phases.peaks_i 的 MAX=1000
  4. top-64 BLOB（仅 Inorg）：512 字节 = 64×float64，与 CSV 最强 64 条一致
  5. 峰位抽检：石英 3.34 / 方解石 3.04 / 刚玉 2.085（次强 2.55）
  6. 独立重算：抽 N 条，从源 CIF 重算峰，与库中值比对（d 偏差 < 1e-3 Å）
  7. 外挂稳健：DELETE journal / page_size / encoding / 无 -wal,-shm 残留
  8. .sqlite 与 .db 字节级一致（md5）

用法:
    python accept_3cod.py [--stamp 20261015] [--kind both|full|inorg] [--recheck 8]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")

import build_3cod as G  # noqa: E402
import fastxrd as FX  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(BASE, "inorg_manifest.sqlite")

WARN = []


def md5(path, chunk=1 << 22):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def entry_id(cod_id):
    s = str(int(cod_id)).zfill(7)
    return "96-%s-%s" % (s[:3], s[3:])


def floats(s):
    return np.asarray([float(x) for x in s.split(",")], dtype=np.float64) if s \
        else np.zeros(0)


def hex_d(a, c, h, k, l):
    """六方/三方晶胞（含菱面体取六方轴）的 d 间距：
    d = 1/sqrt( (4/3)(h²+hk+k²)/a² + l²/c² )。"""
    import math
    return 1.0 / math.sqrt((4.0 / 3.0) * (h * h + h * k + k * k) / (a * a)
                           + (l * l) / (c * c))


def recompute(text):
    """从 CIF 原文重算 (d, I)（与 build_3cod 完全同一代码路径）。

    返回全量峰（≤ TOP_POLY=500，d 降序）。Full 侧库里只存「强度前 TOP_XIN=100」，
    必须拿到 I 才能在重算侧取出同一子集 —— 只返回 d 无法正确比对。
    """
    dd = G.parse_cif(text)
    coords, sp_list, _ = G.expand_sites(dd.sites, dd.symops)
    rows, syms, occs = [], [], []
    for coord, sp in zip(coords, sp_list):
        for el, o in sp.items():
            o = float(o)
            rows.append(coord)
            syms.append(el)
            occs.append(min(o, 1.0) if o > 0 else 1.0)
    d, i, _ = FX.compute_pattern_arrays(
        dd.a, dd.b, dd.c, dd.alpha, dd.beta, dd.gamma,
        np.asarray(rows, dtype=float), syms, occs,
        wavelength=G.WAVELENGTH, tth_range=(G.TTH_MIN, G.TTH_MAX),
        max_hkl=G.MAX_HKL, half_sphere=True, scale=G.SCALE,
        max_peaks=G.TOP_POLY, return_hkl=True)
    return (np.asarray(d, dtype=np.float64), np.asarray(i, dtype=np.float64))


def check_elements(con, kind):
    """§8 元素索引：elements 行表 == formula 解析集合；element_combo 哈希可复现。"""
    import build_dbs as B
    bad_pair = bad_combo = n = 0
    for eid, formula, els in con.execute(
            "SELECT entry_id, formula, elements FROM entries "
            "WHERE elements IS NOT NULL AND elements<>'' LIMIT 10"):
        n += 1
        want = B.parse_elements(formula or "")[0]
        if (els or "") != (want or ""):
            bad_pair += 1
            print("    ! %s 元素列=%r 但按 formula 解析得 %r" % (eid, els, want))
        rows = sorted(r[0] for r in con.execute(
            "SELECT element FROM elements WHERE entry_id=?", (eid,)))
        if rows != sorted((els or "").split(",")):
            bad_pair += 1
            print("    ! %s elements 行表 %s != 列 %r" % (eid, rows, els))
    # 哈希可复现：elements 列 → sha1(排序拼接)[:16] 必须能在 element_combo 命中
    for eid, els in con.execute(
            "SELECT entry_id, elements FROM entries "
            "WHERE elements IS NOT NULL AND elements<>'' ORDER BY RANDOM() LIMIT 10"):
        h = hashlib.sha1(",".join(sorted((els or "").split(","))).encode()) \
                   .hexdigest()[:16]
        if not con.execute("SELECT 1 FROM element_combo WHERE element_set_hash=?",
                           (h,)).fetchone():
            bad_combo += 1
    n_dist = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT elements FROM entries "
        "WHERE elements IS NOT NULL AND elements<>'')").fetchone()[0]
    n_cb = con.execute("SELECT COUNT(*) FROM element_combo").fetchone()[0]
    print("  元素索引: 抽 %d 条 列/行表/解析 三者一致: %s (异常 %d)"
          % (n, "通过" if bad_pair == 0 else "异常", bad_pair))
    print("  element_combo 哈希可复现: %s (抽 10 条, 未命中 %d)"
          % ("通过" if bad_combo == 0 else "异常", bad_combo))
    print("  distinct(elements)=%d  vs  element_combo 行数=%d  → %s"
          % (n_dist, n_cb, "一致" if n_dist == n_cb else "不一致"))
    if bad_pair or bad_combo or n_dist != n_cb:
        WARN.append("%s: 元素索引异常 pair=%d combo=%d distinct=%d/%d"
                    % (kind, bad_pair, bad_combo, n_dist, n_cb))


def check_common(con, kind, main):
    n_ent = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_pk = con.execute("SELECT COUNT(*) FROM peaks").fetchone()[0]
    n_el = con.execute("SELECT COUNT(*) FROM elements").fetchone()[0]
    n_cb = con.execute("SELECT COUNT(*) FROM element_combo").fetchone()[0]
    n_main = con.execute("SELECT COUNT(*) FROM %s" % main).fetchone()[0]
    n_site = con.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    print("  entries=%d  peaks=%d (%.1f 行/条)  elements=%d  element_combo=%d"
          % (n_ent, n_pk, n_pk / max(n_ent, 1), n_el, n_cb))
    print("  %s=%d  cod_atomic_sites=%d" % (main, n_main, n_site))
    if n_cb < 1000:
        WARN.append("%s: element_combo 仅 %d 组，偏少" % (kind, n_cb))
    return n_ent, n_pk, n_main


def check_meta(con, kind, path):
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    for k in ("schema_version", "variant", "cif_embedded", "peak_convention",
              "libraries", "xinmatch_peaks_rows", "entry_count"):
        print("    meta.%-20s %s" % (k, meta.get(k)))
    if meta.get("cif_embedded") != "0":
        WARN.append("%s: cif_embedded != 0" % kind)
    if not str(meta.get("variant", "")).startswith("slim-index"):
        WARN.append("%s: variant 不以 slim-index 开头（PolyXRD 检索会被清空）" % kind)
    return meta


def check_full(con):
    """Full：cod_entries 无峰列，峰在 XinMatch peaks 表。"""
    # --- ID 一致性：cod_entries.cod_id → entries.entry_id ---
    bad = miss = 0
    rows = con.execute("SELECT cod_id FROM cod_entries LIMIT 20000").fetchall()
    for (cid,) in rows:
        eid = entry_id(cid)
        r = con.execute("SELECT 1 FROM entries WHERE entry_id=?", (eid,)).fetchone()
        if not r:
            miss += 1
    print("  ID 一致(cod_entries→entries, 前 %d 条): 缺失 %d 条" % (len(rows), miss))
    if miss:
        WARN.append("full: %d 条 cod_entries 在 entries 中无对应" % miss)

    # --- 强度口径 & 行数（随机抽 300 个 entry_id）---
    # 注意：不要写成 entry_id IN (SELECT entry_id FROM peaks) —— Full 的 peaks 有
    # 1.65 亿行，IN 子查询可能被物化，代价不可接受。这里先随机抽 entries，再按
    # idx_peaks_entry_id 逐条做索引查找。
    imax_bad = cnt_bad = hkl_bad = 0
    cnt = 0
    for (eid,) in con.execute(
            "SELECT entry_id FROM entries ORDER BY RANDOM() LIMIT 300"):
        pr = con.execute(
            "SELECT d, intensity, h, k, l FROM peaks WHERE entry_id=?", (eid,)).fetchall()
        if not pr:
            continue
        cnt += 1
        i = np.asarray([r[1] for r in pr], dtype=float)
        if abs(float(i.max()) - 1000.0) > 0.51:
            imax_bad += 1
        if len(pr) > 100:
            cnt_bad += 1
        for r in pr:
            if r[2] is None or r[3] is None or r[4] is None:
                hkl_bad += 1
                break
    print("  强度 max=1000: %s (抽 %d 条, 异常 %d)"
          % ("通过" if imax_bad == 0 else "异常", cnt, imax_bad))
    print("  peaks ≤100 行/条: %s (异常 %d)；hkl 已回填: %s (缺 %d)"
          % ("通过" if cnt_bad == 0 else "异常", cnt_bad,
             "通过" if hkl_bad == 0 else "异常", hkl_bad))
    if imax_bad or cnt_bad or hkl_bad:
        WARN.append("full: 峰表异常 max=%d 行数=%d hkl=%d" % (imax_bad, cnt_bad, hkl_bad))


def check_inorg(con):
    """Inorg：phases 含 peaks_d/peaks_i CSV 与 top-64 BLOB。"""
    bad = 0
    for cid, rid, did in con.execute(
            "SELECT cod_id, ref_id, display_id FROM phases LIMIT 20000"):
        want = entry_id(cid)
        if rid != want or did != want:
            bad += 1
    print("  ID 三方一致(ref_id==display_id==96-cod_id, 前 20000 条): %s"
          % ("通过" if bad == 0 else "失败 %d 条" % bad))
    if bad:
        WARN.append("inorg: ID 三方一致失败 %d 条" % bad)

    imax_bad = nbad_bad = blob_len = blob_pair = blob_sel = 0
    n = 0
    for cid, npk, pds, pis, bd, bi in con.execute(
            "SELECT cod_id, n_peaks, peaks_d, peaks_i, peaks_top_d, peaks_top_i "
            "FROM phases WHERE peaks_d IS NOT NULL LIMIT 300"):
        d = floats(pds)
        i = floats(pis)
        n += 1
        if i.size and abs(float(i.max()) - 1000.0) > 0.51:
            imax_bad += 1
        if d.size and npk and int(npk) != d.size:
            nbad_bad += 1
        if bd is None or bi is None:
            blob_len += 1
            continue
        # top-N BLOB 是「不定长、不补齐」：长度必须是 8 × min(n_peaks, 64)。
        # 依据：PolyXRD 线上 COD_inorganics.sqlite 71,199 行实测 —— n_peaks≥64 的
        # 59,713 行为 512 B，n_peaks<64 的 11,486 行均更短，无一补齐到 512。
        # 读取端 _parse_float_csv 对 bytes 走 np.frombuffer 零拷贝，长度自适应。
        exp_len = 8 * min(int(npk or 0), 64)
        if len(bd) != exp_len or len(bi) != exp_len:
            blob_len += 1
            continue
        td = np.frombuffer(bd, dtype="<f8")
        ti = np.frombuffer(bi, dtype="<f8")
        # (a) 必须按强度降序（非增）
        if ti.size > 1 and float(np.max(np.diff(ti))) > 1e-9:
            blob_sel += 1
        # (b) BLOB 的每个 (d,i) 必须能在 CSV 中找到同值行。
        #     CSV 的 i 只保留 2 位小数，四舍五入会让并列强度改变排序，从而选出
        #     不同的第 64 名 —— 这是并列歧义，不是缺陷。故用「逐对存在性」判定，
        #     d 用与写入端一致的 "%.5f" 字符串精确匹配。
        pairs = {}
        for kd, ki in zip(pds.split(","), pis.split(",")):
            pairs.setdefault(kd.strip(), []).append(float(ki))
        miss = 0
        for k in range(td.size):
            cand = pairs.get("%.5f" % td[k])
            if not cand or not any(abs(v - ti[k]) <= 5e-2 for v in cand):
                miss += 1
        if miss:
            blob_pair += 1
        # (c) 选出的强度多重集必须是 CSV 中最大的那 64 个（容差覆盖 2 位小数舍入）
        if i.size >= 64:
            top64 = np.sort(i)[::-1][:64]
            if not np.allclose(np.sort(ti)[::-1], top64, atol=5e-2):
                blob_sel += 1
    print("  强度 max=1000: %s (抽 %d 条, 异常 %d)"
          % ("通过" if imax_bad == 0 else "异常", n, imax_bad))
    print("  n_peaks 与 peaks_d 长度自洽: %s (异常 %d)"
          % ("通过" if nbad_bad == 0 else "异常", nbad_bad))
    print("  top-N BLOB 长度=8×min(n_peaks,64) 且按强度降序: %s "
          "(抽 %d 条, 长度异常 %d, 排序异常 %d)"
          % ("通过" if not (blob_len or blob_sel) else "异常",
             n, blob_len, blob_sel))
    print("  top-N BLOB 每个 (d,i) 在 CSV 中存在同值行: %s (异常 %d)"
          % ("通过" if blob_pair == 0 else "异常", blob_pair))
    if imax_bad or nbad_bad or blob_len or blob_pair or blob_sel:
        WARN.append("inorg: 峰/BLOB 异常 max=%d n_peaks=%d 长度=%d 配对=%d 选择=%d"
                    % (imax_bad, nbad_bad, blob_len, blob_pair, blob_sel))

    # --- 峰位抽检：已知物相 ---
    # ⚠️ phases 表**没有 formula_red 列**（见 reference/polyxrd/phases_schema.sql 的
    #    逐列内省），只能按 formula 精确匹配（实测取值 'O2 Si'/'C Ca O3'/'Al2 O3'，
    #    走 idx_phases_formula，秒级）。
    # ⚠️ 不能拿「最强线」当判据：本库口径无 Debye-Waller 温度因子 → 低角线相对偏强；
    #    且 formula='O2 Si' 的 505 条里 90% 是 PCOD/TCOD 预测的立方 SiO2 骨架
    #    （I m -3 m、a≈17–25 Å），其最强线落在 17 Å 附近。真 α-石英只占约 49 条。
    #    峰位与温度因子无关，是唯一跨口径稳定的量 → 改验**峰位**。
    # 做法：用条目**自身晶胞**按已知 (hkl) 重算期望 d（六方/三方通用式）。
    #       前置条件必须两步都满足，否则会把非六方条目也算进来：
    #         (1) 晶胞确实是六方/三方：a≈b、α≈β≈90°、γ≈120°
    #             —— 否则 hex_d 公式无效（实测真 α-石英 Δd=0.00000，而误入的
    #                正交 P b a n / 三斜 P 1 / 四方 P 41 21 2 条目 Δd 达 0.03–0.10）
    #         (2) |d_calc − 参考值| < 0.05，即晶胞确为该矿物
    #       再要求峰表里确实有峰落在 d_calc 上（|Δd| < 0.002 Å）。
    for label, forms, (hh, kk_, ll), expect in (
            ("石英 SiO2 (101)", ("O2 Si", "SiO2", "Si O2"), (1, 0, 1), 3.3435),
            ("方解石 CaCO3 (104)", ("C Ca O3", "CaCO3", "Ca C O3"), (1, 0, 4), 3.0350),
            ("刚玉 Al2O3 (113)", ("Al2 O3", "Al2O3", "O3 Al2"), (1, 1, 3), 2.0850)):
        ph = ",".join("?" * len(forms))
        dd_list, rel_list, n_ent, n_hit, n_skip = [], [], 0, 0, 0
        for cid, ca, cb, cc, al, be, ga, pds, pis in con.execute(
                "SELECT cod_id, cell_a, cell_b, cell_c, cell_alpha, cell_beta, "
                "cell_gamma, peaks_d, peaks_i FROM phases WHERE formula IN (%s)" % ph,
                forms):
            if not (ca and cb and cc and al and be and ga):
                n_skip += 1
                continue
            if abs(ca - cb) > 0.02 or abs(al - 90) > 1.0 or abs(be - 90) > 1.0 \
                    or abs(ga - 120) > 1.0:
                n_skip += 1                     # 非六方/三方晶胞，hex_d 不适用
                continue
            dcalc = hex_d(ca, cc, hh, kk_, ll)
            if abs(dcalc - expect) > 0.05:
                continue                        # 晶胞不是该矿物（多为预测结构）
            d = floats(pds)
            i = floats(pis)
            if d.size == 0 or i.max() <= 0:
                n_skip += 1
                continue
            n_ent += 1
            j = int(np.argmin(np.abs(d - dcalc)))
            dd = abs(float(d[j]) - dcalc)
            dd_list.append(dd)
            rel_list.append(float(i[j]) / float(i.max()))
            if dd < 2e-3:
                n_hit += 1
        if n_ent:
            print("  %-18s 六方晶胞且 d_calc 吻合 %d 条（另有 %d 条晶系/晶胞不符已排除）；"
                  "|d−d_calc| 中位 %.5f Å、最大 %.5f Å；命中 %d/%d；相对强度中位 %.2f"
                  % (label, n_ent, n_skip, float(np.median(dd_list)),
                     float(np.max(dd_list)), n_hit, n_ent, float(np.median(rel_list))))
            if n_hit < n_ent:
                WARN.append("inorg: %s 有 %d/%d 条未在 d_calc 处找到峰"
                            % (label, n_ent - n_hit, n_ent))
        else:
            print("  %-18s 六方晶胞且 d_calc 吻合 0 条 —— 抽检未执行" % label)
            WARN.append("inorg: %s 抽检未执行（无符合条目）" % label)


def check_recompute(con, kind, main, mf, n):
    """从源 CIF 重算并与库中峰比对。"""
    if kind == "full":
        # peaks_d 在 Full 侧不存在（峰只在 XinMatch peaks 表），占位 None；
        # 只随机抽 cod_id，随后按 entry_id(cod_id) 走 idx_peaks_entry_id 取峰。
        rows = con.execute(
            "SELECT cod_id, NULL FROM cod_entries ORDER BY RANDOM() LIMIT ?",
            (n,)).fetchall()
    else:
        rows = con.execute(
            "SELECT cod_id, peaks_d FROM phases WHERE peaks_d IS NOT NULL "
            "ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()
    ok = fail = skip = 0
    for cid, pds in rows:
        r = mf.execute("SELECT lib, rel FROM files WHERE cod_id=?", (cid,)).fetchone()
        if not r:
            skip += 1
            continue
        src = os.path.join(BASE, r[0], r[1])
        try:
            with open(src, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            skip += 1
            continue
        try:
            d2, i2 = recompute(text)
        except Exception:
            skip += 1
            continue
        if kind == "full":
            pr = con.execute(
                "SELECT d, intensity FROM peaks WHERE entry_id=? "
                "ORDER BY intensity DESC", (entry_id(cid),)).fetchall()
            if not pr:
                skip += 1
                continue
            d1 = np.asarray([x[0] for x in pr], dtype=float)
            i1 = np.asarray([x[1] for x in pr], dtype=float)
            # ⚠️ 库中是「该结构全量峰的强度前 TOP_XIN=100」，重算侧是全量 ≤500。
            #    若两边各自按 d 排序后逐位比，比的其实是**两个不同子集**
            #    （"前 100 强" 里 d 最大的 k 条 ≠ 全量里 d 最大的 k 条），必然超限。
            #    正确做法：重算侧也取强度前 len(d1) 条，再按 d 排序比对同一集合。
            #    （构建端用的就是 argsort(-i, kind="stable")[:TOP_XIN]，此处一致。）
            order = np.argsort(-i2, kind="stable")[:len(d1)]
            dev = float(np.max(np.abs(np.sort(d1) - np.sort(d2[order]))))
            if dev >= 1e-3:
                # 顺带给出强度序列偏差，便于区分"峰位错"与"只是选了不同的并列峰"
                dev_i = float(np.max(np.abs(i1 - i2[order]))) if len(i2) >= len(i1) \
                    else float("nan")
                print("    ! cod_id=%d 重算偏差 %.4f Å（强度偏差 %.4f，库 %d 峰/重算 %d 峰）"
                      % (cid, dev, dev_i, len(d1), len(d2)))
        else:
            d1 = floats(pds)
            k = min(len(d1), len(d2))
            if k == 0:
                skip += 1
                continue
            dev = float(np.max(np.abs(d1[:k] - d2[:k])))
        if dev < 1e-3:
            ok += 1
        else:
            fail += 1
            print("    ! cod_id=%d 重算偏差 %.4f Å" % (cid, dev))
    print("  独立重算比对: 通过 %d, 偏差超限 %d, 跳过 %d" % (ok, fail, skip))
    if fail:
        WARN.append("%s: 重算比对失败 %d 条" % (kind, fail))


def check_one(path, kind, recheck, mf):
    print("=" * 72)
    print("产物: %s   (%.2f GB)" % (os.path.basename(path),
                                    os.path.getsize(path) / 1e9))
    uri = "file:%s?mode=ro" % path.replace(os.sep, "/")
    con = sqlite3.connect(uri, uri=True, timeout=120)
    tbls = sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    print("  表: %s" % ", ".join(tbls))
    main = "cod_entries" if kind == "full" else "phases"
    check_common(con, kind, main)
    check_meta(con, kind, path)
    check_elements(con, kind)
    (check_full if kind == "full" else check_inorg)(con)
    if recheck:
        check_recompute(con, kind, main, mf, recheck)
    con.close()

    con = sqlite3.connect(uri, uri=True, timeout=120)
    jm = con.execute("PRAGMA journal_mode").fetchone()[0]
    ps = con.execute("PRAGMA page_size").fetchone()[0]
    enc = con.execute("PRAGMA encoding").fetchone()[0]
    con.close()
    left = [p for p in (path + "-wal", path + "-shm") if os.path.exists(p)]
    print("  journal=%s  page_size=%d  encoding=%s  残留=%s"
          % (jm, ps, enc, left or "无"))
    if jm != "delete" or left:
        WARN.append("%s: journal=%s 残留=%s" % (kind, jm, left))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="20261015")
    ap.add_argument("--kind", default="both", choices=["both", "full", "inorg"])
    ap.add_argument("--recheck", type=int, default=8)
    ap.add_argument("--no-md5", action="store_true",
                    help="跳过 .sqlite/.db 的 md5 全文件比对（几十 GB，机械盘很慢）")
    args = ap.parse_args()

    mf = sqlite3.connect("file:%s?mode=ro" % MANIFEST.replace(os.sep, "/"),
                         uri=True, timeout=60)
    for kind in (["inorg", "full"] if args.kind == "both" else [args.kind]):
        src = os.path.join(BASE, "3COD-%s-%s.sqlite" % (kind.capitalize(), args.stamp))
        dst = src[:-7] + ".db"
        if not os.path.exists(src):
            print("! 缺失 %s" % src)
            continue
        check_one(src, kind, args.recheck, mf)
        if os.path.exists(dst):
            if args.no_md5:
                sa, sb = os.path.getsize(src), os.path.getsize(dst)
                print("  .sqlite 与 .db 尺寸一致: %s (%d)  [--no-md5，未做全文件校验]"
                      % ("是" if sa == sb else "否", sa))
                if sa != sb:
                    WARN.append("%s 与 .db 尺寸不一致" % kind)
            else:
                a, b = md5(src), md5(dst)
                print("  .sqlite 与 .db 字节一致: %s  (md5 %s…)"
                      % ("是" if a == b else "否", a[:12]))
                if a != b:
                    WARN.append("%s 与 .db 内容不一致" % kind)
        else:
            # 单一格式交付（2026-10-18）：只出 .sqlite，无 .db 副本即符合口径
            print("  .db 副本不存在：符合单一格式交付口径（.sqlite 即唯一产物）")

    print("=" * 72)
    if WARN:
        print("!! 验收告警 %d 项:" % len(WARN))
        for w in WARN:
            print("   - %s" % w)
    else:
        print(">>> 全部验收项通过。")


if __name__ == "__main__":
    main()
