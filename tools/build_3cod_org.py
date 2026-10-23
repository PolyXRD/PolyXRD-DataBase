#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3COD-Org：有机物版数据库（= 3COD-Full 与 3COD-Inorg 的**差值集**）。

与 build_3cod.py 的关系（避免第二条实现漂移）:
  - 逐文件处理逻辑、峰口径、DDL、合并/索引/ANALYZE/VACUUM 流程**全部沿用**
    build_3cod（import 其常量与函数，不复制算法）。
  - 唯一区别：输入文件清单不是「全量三库」，而是「Full 有、Inorg 没有」的差值集；
    且只写有机物侧的表（XinMatch 四表 + PolyXRD phases / cod_atomic_sites）。
  - 产物挂载角色与 3COD-Inorg **完全相同**，故 schema 与 Inorg 逐字一致
    （schema_version=2，phases 带 peaks_top_* BLOB，cod_atomic_sites 无 u_iso）。

差值定义（用户指定「两则的差值」）:
    Org = Full.entries − Inorg.entries        （按 entry_id 取差）
  即构建侧 ``is_inorganic(parse_elements(formula)) == False`` 的文件，
  **含** formula 缺失导致的 117 条真实无机物（E-4，占差值 0.018%）——
  这是「差值」口径的定义后果，不是缺陷；该口径保证
      Inorg ∩ Org = ∅   且   Inorg ∪ Org = Full
  （117 条既不在 Inorg 也不在 Org 的「修正口径」需重建 Inorg，另行决策）。

产物:
    3COD-Org-<stamp>.sqlite           （单一格式；.db 副本已于 2026-10-18 废弃）

用法:
    # 1) 派生差值文件清单（只读 Full/Inorg，几分钟）
    python tools/build_3cod_org.py --plan
    # 2) 分片构建（4 进程，约 2.5 h 量级）
    python tools/build_3cod_org.py --build
    # 3) 合并 + 索引 + VACUUM + .db 副本（约 1.5~2.5 h）
    python tools/build_3cod_org.py --merge-only
    # 一键（build 完自动接 merge）:
    python tools/build_3cod_org.py
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_3cod as B3  # noqa: E402  常量 / DDL / entry_id_of / combo_hash / merge
import build_dbs as B   # noqa: E402  parse_elements / cell_volume
import fastxrd as FX     # noqa: E402  compute_pattern_arrays / top_peaks_of
from fastcif import parse_cif, expand_sites  # noqa: E402

STAMP = "20261016"
ORG_DB = os.path.join(BASE, "3COD-Org-%s.sqlite" % STAMP)
ORG_PARTS = os.path.join(BASE, "_3cod_org_parts")
ORG_LIST = os.path.join(BASE, "sync_logs", "org_files_%s.jsonl" % STAMP)
SHARDS = 24
WORKERS = 4

# 峰口径常量全部取自 build_3cod（同一代码路径，勿在此重复定义）
WAVELENGTH = B3.WAVELENGTH
TTH_MIN, TTH_MAX = B3.TTH_MIN, B3.TTH_MAX
SCALE = B3.SCALE
TOP_XIN = B3.TOP_XIN
TOP_POLY = B3.TOP_POLY
TOP_BLOB = B3.TOP_BLOB
MAX_SITES_FOR_PEAKS = B3.MAX_SITES_FOR_PEAKS
MAX_CELL_VOL_FOR_PEAKS = B3.MAX_CELL_VOL_FOR_PEAKS
MAX_HKL = B3.MAX_HKL


def ro(path: str) -> sqlite3.Connection:
    con = sqlite3.connect("file:%s?mode=ro" % path.replace(os.sep, "/"),
                          uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# 阶段 A：派生差值文件清单
# ---------------------------------------------------------------------------
def derive_org_files(src_stamp: str, out_path: str) -> dict:
    """Org = Full.cod_entries − Inorg.entries（按 entry_id）。

    Full.cod_entries 同时给出统一 cod_id 与相对路径（file 列，Windows 反斜杠），
    因此不需要再从文件名反解编号，也避免 _RE_DIGIT 的歧义。
    """
    full_db = os.path.join(BASE, "3COD-Full-%s.sqlite" % src_stamp)
    inorg_db = os.path.join(BASE, "3COD-Inorg-%s.sqlite" % src_stamp)
    for p in (full_db, inorg_db):
        if not os.path.exists(p):
            raise SystemExit("!! 缺源库 %s" % p)

    t0 = time.time()
    ci = ro(inorg_db)
    inorg_ids = {r[0] for r in ci.execute("SELECT entry_id FROM entries")}
    n_inorg_ent = ci.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_inorg_ph = ci.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
    ci.close()
    print("Inorg：entries %s / phases %s（entry_id 集合 %s）"
          % (f"{n_inorg_ent:,}", f"{n_inorg_ph:,}", f"{len(inorg_ids):,}"))

    cf = ro(full_db)
    n_full_ent = cf.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_full_cod = cf.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
    print("Full：entries %s / cod_entries %s"
          % (f"{n_full_ent:,}", f"{n_full_cod:,}"))

    rows, missing, by_lib = [], [], {}
    n_scan = 0
    for cod_id, f in cf.execute("SELECT cod_id, file FROM cod_entries"):
        n_scan += 1
        eid = B3.entry_id_of(int(cod_id))
        if eid in inorg_ids:
            continue
        parts = (f or "").replace("\\", "/").split("/")
        if len(parts) < 2:
            missing.append((cod_id, f))
            continue
        lib, nm = parts[0], parts[-1]
        rel_dir = "/".join(parts[1:-1])
        # 不在此处做 os.path.exists：66 万次 stat 在机械盘上要十几分钟，
        # 且与其它任务抢盘。文件缺失改由构建期 process_one 的 read_fail 记账。
        rows.append({"cod_id": int(cod_id), "lib": lib, "rel": rel_dir,
                     "name": nm,
                     "abs": os.path.join(BASE, *parts)})
        by_lib[lib] = by_lib.get(lib, 0) + 1
    cf.close()

    # 对账：差集计数必须等于两个 entries 计数之差
    expect = n_full_ent - n_inorg_ent
    print("差值条目 %s（Full entries − Inorg entries = %s）按库分布 %s"
          % (f"{len(rows):,}", f"{expect:,}", by_lib))
    if len(rows) != expect:
        raise SystemExit("!! 差值计数 %d 与预期 %d 不一致——两侧 entries 口径可能被改过"
                         % (len(rows), expect))
    if missing:
        print("! 路径畸形 %d 条（未写入清单）" % len(missing))
        for m in missing[:5]:
            print("   ", m)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("清单已写 %s（%s 行，%.1f s）"
          % (out_path, f"{len(rows):,}", time.time() - t0))
    return {"org": len(rows), "full_entries": n_full_ent,
            "inorg_entries": n_inorg_ent, "by_lib": by_lib,
            "missing": len(missing)}


# ---------------------------------------------------------------------------
# 阶段 B：分片构建（逐文件逻辑与 build_3cod.worker 一致，org=True）
# ---------------------------------------------------------------------------
def _shard_sql() -> str:
    return (B3.XINMATCH_SQL + B3.POLY_INORG_SQL +
            "CREATE TABLE IF NOT EXISTS units_done (unit TEXT PRIMARY KEY);")


def process_one(rec: dict):
    """处理单个文件，返回 (entries_row, peak_rows, element_rows, phase_row,
    site_rows, status)。status ∈ ok / peak_fail / skip_big / no_data /
    parse_fail / read_fail / empty。

    判定与 build_3cod.worker **逐条对齐**（同一常量、同一函数），只是把
    「不算峰」的原因分开计数，便于报告：
      skip_big   晶胞 > MAX_CELL_VOL_FOR_PEAKS 或展开位点 > MAX_SITES_FOR_PEAKS
      no_data    无晶胞或无位点（没什么可算）
      peak_fail  compute_pattern_arrays 抛异常或返回空（真正的失败，设 20% 防线）
    """
    src = rec["abs"]
    cod_id = rec["cod_id"]
    try:
        st = os.stat(src)
        if st.st_size == 0:
            return None, [], [], None, [], "empty"
        with open(src, "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return None, [], [], None, [], "read_fail"

    try:
        d = parse_cif(text)
    except Exception:
        return None, [], [], None, [], "parse_fail"

    elements, _formula_red, _counts = B.parse_elements(d.formula)
    eid = B3.entry_id_of(cod_id)
    vol = d.volume or B.cell_volume(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)

    row_e = (eid,
             d.formula[:250] if d.formula else None,
             d.name[:250] if d.name else None,
             d.sg_name, None,
             d.a, d.b, d.c, d.alpha, d.beta, d.gamma, vol,
             None, None, None, None, None, None,
             elements or None)
    el_rows = [(eid, el) for el in (elements.split(",") if elements else []) if el]

    site_rows = []
    for idx, s in enumerate(d.sites):
        try:
            label, el, x, y, z, occ, _u = s
        except ValueError:
            continue
        site_rows.append((cod_id, idx, label, el, x, y, z,
                          occ if occ else 1.0))

    # ---- 峰（与 build_3cod 同一判定与同一函数）----
    dd = ii = hkl = None
    if not vol:
        return row_e, [], el_rows, None, site_rows, "no_data"
    if vol > MAX_CELL_VOL_FOR_PEAKS:
        return row_e, [], el_rows, None, site_rows, "skip_big"
    if not d.sites:
        return row_e, [], el_rows, None, site_rows, "no_data"
    try:
        coords, sp_list, _ = expand_sites(d.sites, d.symops)
        if len(sp_list) > MAX_SITES_FOR_PEAKS:
            return row_e, [], el_rows, None, site_rows, "skip_big"
        if len(sp_list) > 0:
            rows, syms, occs = [], [], []
            for coord, sp in zip(coords, sp_list):
                for el, o in sp.items():
                    o = float(o)
                    rows.append(coord)
                    syms.append(el)
                    occs.append(min(o, 1.0) if o > 0 else 1.0)
            out = FX.compute_pattern_arrays(
                d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                np.asarray(rows, dtype=float), syms, occs,
                wavelength=WAVELENGTH, tth_range=(TTH_MIN, TTH_MAX),
                max_hkl=MAX_HKL, half_sphere=True, scale=SCALE,
                max_peaks=TOP_POLY, return_hkl=True)
            if len(out) == 3:
                dd, ii, hkl = out
    except Exception:
        dd = None

    if dd is None or len(dd) == 0:
        return row_e, [], el_rows, None, site_rows, "peak_fail"

    d_arr = np.asarray(dd, dtype=np.float64)
    i_arr = np.asarray(ii, dtype=np.float64)
    h_arr = np.asarray(hkl, dtype=np.int64)
    order = np.argsort(-i_arr, kind="stable")[:TOP_XIN]
    pk_rows = [(eid, float(d_arr[j]), float(i_arr[j]),
                int(h_arr[j][0]), int(h_arr[j][1]), int(h_arr[j][2]))
               for j in order]
    td, ti = FX.top_peaks_of(d_arr, i_arr, TOP_BLOB)
    ph_row = (cod_id,
              d.formula[:250] if d.formula else None,
              d.sg_name,
              d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
              int(len(d_arr)),
              ",".join("%.5f" % v for v in d_arr),
              ",".join("%.2f" % v for v in i_arr),
              None, None, eid, eid,
              sqlite3.Binary(np.asarray(td, dtype="<f8").tobytes()),
              sqlite3.Binary(np.asarray(ti, dtype="<f8").tobytes()),
              None)
    return row_e, pk_rows, el_rows, ph_row, site_rows, "ok"


def worker(args):
    shard_id, recs, resume = args
    sdb = os.path.join(ORG_PARTS, "p%03d_org.sqlite" % shard_id)
    if not resume and os.path.exists(sdb):
        os.remove(sdb)
    for suf in ("-wal", "-shm"):
        p = sdb + suf
        if os.path.exists(p):
            os.remove(p)

    done = set()
    if resume and os.path.exists(sdb):
        try:
            c = ro(sdb)
            done = {r[0] for r in c.execute("SELECT unit FROM units_done")}
            c.close()
        except sqlite3.Error:
            pass

    con = sqlite3.connect(sdb, timeout=300.0)
    con.executescript(_shard_sql())
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA busy_timeout=300000")
    con.execute("PRAGMA cache_size=-32768")
    con.execute("PRAGMA temp_store=MEMORY")

    stat = dict(file=0, ok=0, peak_fail=0, parse_fail=0, read_fail=0,
                empty=0, skip_big=0, no_data=0, phases=0, peaks=0, sites=0,
                entries=0)
    f_ent, f_pk, f_el, ph_rows, site_rows = [], [], [], [], []
    t0 = time.time()

    def flush():
        if f_ent:
            con.executemany(
                "INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                f_ent)
            f_ent.clear()
        if f_pk:
            con.executemany("INSERT INTO peaks VALUES (?,?,?,?,?,?)", f_pk)
            f_pk.clear()
        if f_el:
            con.executemany("INSERT OR REPLACE INTO elements VALUES (?,?)", f_el)
            f_el.clear()
        if ph_rows:
            con.executemany(
                "INSERT OR REPLACE INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ph_rows)
            ph_rows.clear()
        if site_rows:
            con.executemany(
                "INSERT OR REPLACE INTO cod_atomic_sites VALUES (?,?,?,?,?,?,?,?)",
                site_rows)
            site_rows.clear()

    cur_unit = None
    for rec in recs:
        unit = "%s/%s" % (rec["lib"], rec["rel"])
        if cur_unit is not None and unit != cur_unit:
            con.execute("INSERT OR REPLACE INTO units_done VALUES (?)", (cur_unit,))
            con.commit()
        cur_unit = unit
        if unit in done:
            continue
        stat["file"] += 1
        row_e, pk, el, ph, st_rows, status = process_one(rec)
        if status in ("read_fail", "parse_fail", "empty"):
            stat[status] += 1
            continue
        stat[status] += 1
        if row_e is not None:
            f_ent.append(row_e)
            stat["entries"] += 1
        if el:
            f_el.extend(el)
        if pk:
            f_pk.extend(pk)
            stat["peaks"] += len(pk)
        if ph is not None:
            ph_rows.append(ph)
            stat["phases"] += 1
        if st_rows:
            site_rows.extend(st_rows)
            stat["sites"] += len(st_rows)
        if (len(f_ent) >= 500 or len(f_pk) >= 20000
                or len(site_rows) >= 10000):
            flush()
            con.commit()
    if cur_unit is not None:
        con.execute("INSERT OR REPLACE INTO units_done VALUES (?)", (cur_unit,))
    flush()
    con.commit()
    con.execute("INSERT OR REPLACE INTO meta VALUES ('shard_done','1')")
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()
    stat["secs"] = round(time.time() - t0, 1)
    return shard_id, stat


def build(list_path: str, shards: int, workers: int, resume: bool,
          limit: int = 0) -> None:
    recs = []
    with open(list_path, encoding="utf-8") as fh:
        for line in fh:
            recs.append(json.loads(line))
    if limit:
        recs = recs[:limit]
    # 按目录单元分组后**连续**分片 —— 与 build_3cod 的轮询 units[i::shards] **不同**，
    # 这是本脚本针对机械盘的刻意改动：
    #   实测（2026-10-16 18:30，轮询分片 + 4 worker）：PhysicalDisk 92% 忙、
    #   磁盘队列长 1.87、读吞吐仅 ~5.3 MB/s —— 典型寻道受限。原因是轮询分片让
    #   每个 worker 在整套 40 GB 归档里逐单元跳跃，4 条读写流互相打断，磁臂反复扫全盘。
    #   连续分片后每个 worker 顺序扫过自己那段归档（按累计文件数切分，体量均衡），
    #   随机寻道退化为顺序读。断点粒度仍是目录单元（units_done），--resume 语义不变。
    units: dict[str, list] = {}
    for r in recs:
        units.setdefault("%s/%s" % (r["lib"], r["rel"]), []).append(r)
    keys = sorted(units)
    counts = [len(units[k]) for k in keys]
    total = sum(counts)
    groups = [[] for _ in range(shards)]
    gi, acc = 0, 0
    for k, c in zip(keys, counts):
        groups[gi].extend(sorted(units[k], key=lambda x: x["name"]))
        acc += c
        if gi < shards - 1 and acc >= total * (gi + 1) / shards:
            gi += 1
    groups = [g for g in groups if g]
    sizes = [len(g) for g in groups]
    print("差值文件 %s → %d 个目录单元 → %d 分片，%d 进程；分片体量 %s ~ %s（极差 %.1f%%）"
          % (f"{len(recs):,}", len(keys), len(groups), workers,
             f"{min(sizes):,}", f"{max(sizes):,}",
             100.0 * (max(sizes) - min(sizes)) / max(sizes)), flush=True)
    os.makedirs(ORG_PARTS, exist_ok=True)
    print("差值文件 %s → %d 个目录单元 → %d 分片，%d 进程"
          % (f"{len(recs):,}", len(keys), len(groups), workers), flush=True)

    tot = dict(file=0, ok=0, peak_fail=0, parse_fail=0, read_fail=0,
               empty=0, skip_big=0, no_data=0, phases=0, peaks=0, sites=0,
               entries=0)
    t0 = time.time()
    with Pool(workers) as pool:
        for sid, st in pool.imap_unordered(
                worker, [(i, g, resume) for i, g in enumerate(groups)]):
            for k in tot:
                tot[k] += st.get(k, 0)
            print("[%d/%d] 分片 p%03d：文件 %d，峰成功 %d，峰失败 %d，"
                  "超限跳过 %d，无数据 %d，解析失败 %d，phases %d，peaks %d，%d s"
                  % (sid + 1, len(groups), sid, st["file"], st["ok"],
                     st["peak_fail"], st["skip_big"], st["no_data"],
                     st["parse_fail"], st["phases"], st["peaks"],
                     st["secs"]), flush=True)
    dt = time.time() - t0
    print("分片构建总耗时 %.2f h；%s" % (dt / 3600.0, json.dumps(tot, ensure_ascii=False)))

    # 防线：与 build_3cod 同思路。注意有机物里「超限跳过」（大晶胞/多位点）与
    # 「无数据」（无晶胞/无位点）都**不是失败**，不计入失败率；只对真正的峰失败
    # （compute_pattern_arrays 异常或返回空）设 20% 阈值。
    n_attempt = tot["ok"] + tot["peak_fail"]
    if n_attempt and tot["peak_fail"] / n_attempt > 0.20:
        raise SystemExit(
            "!! 峰失败率 %.1f%%（成功 %d / 失败 %d），超过 20%% 阈值，已中止合并。\n"
            "   最常见原因：原子散射因子参数表缺失 —— 应位于\n   %s\n"
            "   分片保留在 %s，修复后加 --resume 续跑。"
            % (100.0 * tot["peak_fail"] / n_attempt, tot["ok"], tot["peak_fail"],
               FX._PARAMS_PATH, ORG_PARTS))


# ---------------------------------------------------------------------------
# 阶段 C/D：合并 + .db 副本 + md5
# ---------------------------------------------------------------------------
def apply_exclusions(db_path: str, exclude_json: str) -> None:
    """合并后剔除「位点回推后应归无机」的条目（E-4 / 记忆 #19 修正）。

    142 条 formula 缺失但位点确为无机的条目已转入 Inorg-v2（补丁分片
    p999_v2patch_inorg），Org 差值集必须同步剔除，保持 Inorg ∪ Org = Full、
    Inorg ∩ Org = ∅ 两个不变量。XinMatch 侧按 entry_id、PolyXRD 侧按 cod_id；
    element_combo 按 elements 全量重建（142 条散布的 combo 无法增量维护）。
    """
    with open(exclude_json, encoding="utf-8") as fh:
        cod_ids = json.load(fh)["cod_ids"]
    eids = [B3.entry_id_of(c) for c in cod_ids]
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("CREATE TEMP TABLE ids (cod_id INTEGER PRIMARY KEY)")
    con.executemany("INSERT OR IGNORE INTO ids VALUES (?)", [(c,) for c in cod_ids])
    con.execute("CREATE TEMP TABLE eids (entry_id TEXT PRIMARY KEY)")
    con.executemany("INSERT OR IGNORE INTO eids VALUES (?)", [(e,) for e in eids])
    for tbl, col in (("entries", "entry_id"), ("peaks", "entry_id"),
                     ("elements", "entry_id"), ("phases", "cod_id"),
                     ("cod_entries", "cod_id"), ("cod_atomic_sites", "cod_id")):
        try:
            n = con.execute("DELETE FROM %s WHERE %s IN (SELECT %s FROM %s)"
                            % (tbl, col, "entry_id" if col == "entry_id" else "cod_id",
                               "eids" if col == "entry_id" else "ids")).rowcount
            print("  排除 %s: -%d 行" % (tbl, n))
        except sqlite3.OperationalError as e:
            print("  排除 %s 跳过: %s" % (tbl, e))
    con.commit()
    # meta 必须随剔除刷新，否则 D4 自洽检查失败（entry_count 等是排除前值）
    n_ph = con.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
    n_ent = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_pk = con.execute("SELECT COUNT(*) FROM peaks").fetchone()[0]
    n_site = con.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [
        ("entry_count", str(n_ph)), ("xinmatch_entries", str(n_ent)),
        ("xinmatch_peaks_rows", str(n_pk)), ("atomic_sites_rows", str(n_site))])
    con.commit()
    con.create_function("combo_hash", 1, B3.combo_hash)
    t0 = time.time()
    con.execute("DELETE FROM element_combo")
    con.execute("INSERT OR REPLACE INTO element_combo "
                "SELECT combo_hash(elements), group_concat(entry_id, char(10)) "
                "FROM entries WHERE elements IS NOT NULL AND elements != '' "
                "GROUP BY combo_hash(elements)")
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()
    print("  element_combo 已重建（%.1f min）" % ((time.time() - t0) / 60.0))


def merge_and_finalize(vacuum: bool = True, keep_parts: bool = True,
                       exclude_json: str | None = None) -> dict:
    parts = sorted(glob.glob(os.path.join(ORG_PARTS, "p*_org.sqlite")))
    if not parts:
        raise SystemExit("!! 没有分片：%s" % ORG_PARTS)
    n = B3.merge(ORG_DB, os.path.join(ORG_PARTS, "p*_org.sqlite"),
                 B3.XINMATCH_SQL + B3.POLY_INORG_SQL,
                 B3.XIN_IDX + B3.INORG_IDX, "org", vacuum=False)
    print("合并完成：phases %s" % f"{n:,}")
    if exclude_json:
        apply_exclusions(ORG_DB, exclude_json)
    if vacuum:
        t0 = time.time()
        con = sqlite3.connect(ORG_DB)
        con.execute("VACUUM")
        con.close()
        print("VACUUM %.1f min" % ((time.time() - t0) / 60.0))
    con = sqlite3.connect(ORG_DB)
    print("integrity_check: %s" % con.execute("PRAGMA integrity_check").fetchone()[0])
    print("journal_mode: %s" % con.execute("PRAGMA journal_mode").fetchone()[0])
    con.close()

    # 单一格式交付（2026-10-18 用户决定）：只出 .sqlite，不再复制 .db。
    info = {}
    for p in (ORG_DB,):
        h = hashlib.md5()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        info[os.path.basename(p)] = {"bytes": os.path.getsize(p),
                                     "md5": h.hexdigest()}
        print("产物 %-30s %s B  md5=%s"
              % (os.path.basename(p), format(os.path.getsize(p), ","),
                 h.hexdigest()))
    if not keep_parts:
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass
    with open(os.path.join(BASE, "sync_logs",
                           "build_3cod_org_%s.json" % STAMP), "w",
              encoding="utf-8") as fh:
        json.dump({"stamp": STAMP, "products": info,
                   "shards": len(parts)}, fh, ensure_ascii=False, indent=1)
    return info


def main():
    global STAMP, ORG_DB, ORG_PARTS, ORG_LIST
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-stamp", default="20261015",
                    help="作为差值源的 Full/Inorg 产物日期戳")
    ap.add_argument("--stamp", default=STAMP, help="Org 产物日期戳")
    ap.add_argument("--plan", action="store_true", help="只派生差值文件清单")
    ap.add_argument("--build", action="store_true", help="只跑分片构建")
    ap.add_argument("--merge-only", action="store_true", help="只合并+收尾")
    ap.add_argument("--no-vacuum", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--shards", type=int, default=SHARDS)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个文件（冒烟）")
    ap.add_argument("--exclude-codids", default=None,
                    help="合并时剔除的 cod_id JSON（位点回推判无机的条目）")
    args = ap.parse_args()

    STAMP = args.stamp
    ORG_DB = os.path.join(BASE, "3COD-Org-%s.sqlite" % STAMP)
    ORG_PARTS = os.path.join(BASE, "_3cod_org_parts")
    ORG_LIST = os.path.join(BASE, "sync_logs", "org_files_%s.jsonl" % STAMP)

    if args.plan:
        derive_org_files(args.src_stamp, ORG_LIST)
        return
    if not os.path.exists(ORG_LIST):
        print("清单缺失，先派生：")
        derive_org_files(args.src_stamp, ORG_LIST)
    if args.merge_only:
        merge_and_finalize(vacuum=not args.no_vacuum,
                           exclude_json=args.exclude_codids)
        return
    build(ORG_LIST, args.shards, args.workers, args.resume, args.limit)
    merge_and_finalize(vacuum=not args.no_vacuum,
                       exclude_json=args.exclude_codids)


if __name__ == "__main__":
    main()
