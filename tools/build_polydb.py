#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polyDB v4 构建器：COD CIF → `*.polyDB` 目录容器。

规范见 `PolyXRD/docs/外挂库格式规范-polyDB-v4.md`。要点：
  · 峰口径：λ=1.5406、2θ 5~100.76°（d≥1.0）、等价反射按 2θ 合并、I 归一 1000；
  · 每相保留 **强度前 K=100** 条峰（不是按 d 截断），行内按 I 降序；
  · 数组段：peaks_d.f32 / peaks_i.u16 / bins.u8（d 分箱位图）/ elem.u8（元素位图）；
  · 侧车：sites.bin + sites_off.i64（非对称单位点，17 B/点，懒加载）；
  · 元数据：index.sqlite（entries + FTS5）+ meta.json（自描述 + 校验和）。

两阶段：
  1) 并行：把清单切成 unit（默认 2000 行/单元），每个 unit 产出一组 part 文件；
     已存在的 unit 直接跳过 → **断点续跑**。
  2) 串行：按 unit 顺序合并 → 写最终数组段 / index.sqlite / meta.json。

用法：
    python tools/build_polydb.py --scope inorg --workers 8
    python tools/build_polydb.py --scope full  --workers 8
    python tools/build_polydb.py --scope inorg --limit 5000 --out D:/tmp/test.polyDB

源数据默认在 ``D:/Project/XRD/sync-COD``（内含 ``COD/`` 与
``inorg_manifest.sqlite``），可用环境变量 ``XRD_DATA_ROOT`` 覆盖。
产物默认写到本仓库的 ``polydb/``。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402

# ── 路径约定 ────────────────────────────────────────────────
# 代码与产物留在本仓库（polydb/、_polydb_parts/）；**源数据在仓库外**：
# COD/ 归档与 inorg_manifest.sqlite 清单由 PolyXRD / XinMatch 两库共用，
# 2026-10-23 起统一放在 `D:/Project/XRD/sync-COD`。
# 换机器或换盘时用环境变量覆盖：XRD_DATA_ROOT=<数据根>
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_ROOT = os.environ.get("XRD_DATA_ROOT") or r"D:\Project\XRD\sync-COD"
MANIFEST = os.path.join(DATA_ROOT, "inorg_manifest.sqlite")
COD_DIR = os.path.join(DATA_ROOT, "COD")
PARTS_ROOT = os.path.join(REPO_ROOT, "_polydb_parts")
#: 产物默认落点（仓库内 polydb/）
POLYDB_DIR = os.path.join(REPO_ROOT, "polydb")

FORMAT_NAME = "polyDB"
SCHEMA_VERSION = 1
TOOL_VERSION = "1.0"

# ── 峰口径（必须与规范 §2 一致） ─────────────────────────────
WAVELENGTH = 1.5406
TTH_MIN = 5.0
D_MIN = 1.0
TTH_MAX = math.degrees(2.0 * math.asin(min(1.0, WAVELENGTH / (2.0 * D_MIN))))
SCALE = 1000.0
K = 100                     # 每相峰槽位数
MAX_PEAKS_CALC = 500        # 计算侧上限（再从其中按强度取 K）
MAX_SITES_FOR_PEAKS = 1500
MAX_CELL_VOL_FOR_PEAKS = 30000
MAX_HKL = 30_000

# ── 索引参数 ────────────────────────────────────────────────
#: 位图倒排只索引每相**最强 M 条峰**。M 有两个约束：
#:   1. **下界 = 打分层上限**：精确打分只用 ``max_ref_peaks=40`` 条最强峰，
#:      因此只要 M ≥ 40，"命中 ≥min_match 个测量峰" 就是 "n_matched_meas
#:      ≥min_match" 的必要条件 —— 预筛结果成为精确结果的**超集**，不会因
#:      索引截断而丢物相；
#:   2. **上界 = 选择性**：M 越大位图越密，``counts>=min_match`` 通过率越高，
#:      预筛退化成弱过滤（M=100 时 99.6% 的相都通过）。
#: 位图段体积与 M **无关**（每箱是一张定长位图），所以 M 只在"召回完整性"
#: 与"池密度"之间权衡。实测（13 试样，top-100 全覆盖判据）：M=12 漏 4 个
#: 试样（最多漏 11 条），M=40 只漏 1 个试样的 2 条（提高候选池上限即补回）。
BINS_TOP_M = 40
BIN_WIDTH = 0.05
BIN_D_MAX = 25.0
N_BINS_DATA = int(BIN_D_MAX / BIN_WIDTH)          # 0..499 之外的 500 个数据箱
N_BINS = N_BINS_DATA + 1                          # +1 overflow（d >= 25）
SITE_BYTES = 17

ELEMENTS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
    "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
    "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au "
    "Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr "
    "Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split()
Z_OF = {s: i + 1 for i, s in enumerate(ELEMENTS)}


# ────────────────────────── worker ──────────────────────────
_W = {}


def _init_worker() -> None:
    """worker 进程初始化：导入重模块 + 原子散射参数。"""
    import cif_common as B  # noqa: F401
    import fastxrd as FX  # noqa: F401
    from fastcif import parse_cif, expand_sites  # noqa: F401
    _W["B"] = B
    _W["FX"] = FX
    _W["parse_cif"] = parse_cif
    _W["expand_sites"] = expand_sites
    _W["FX"]._load_params()      # 预热散射因子表


def _element_mask_bits(elements_csv: str) -> np.uint64:
    """元素串 → 前 64 个元素的位图（仅用于快速统计，正式位图另建）。"""
    m = 0
    for s in (elements_csv or "").split(","):
        z = Z_OF.get(s.strip())
        if z and z <= 64:
            m |= 1 << (z - 1)
    return np.uint64(m)


def process_unit(task: tuple) -> dict:
    """处理一个 unit，产出 part 文件。返回统计。"""
    unit_idx, rows, parts_dir, k = task
    npz_path = os.path.join(parts_dir, "u%05d.npz" % unit_idx)
    jsonl_path = os.path.join(parts_dir, "u%05d.jsonl" % unit_idx)
    sites_path = os.path.join(parts_dir, "u%05d.sites" % unit_idx)
    if os.path.exists(npz_path) and os.path.exists(jsonl_path) and os.path.exists(sites_path):
        try:
            with np.load(npz_path, allow_pickle=False) as z:
                n = int(z["ids"].size)
            return {"unit": unit_idx, "resumed": True, "n": n, "skip": 0, "peaks": 0,
                    "sites": 0, "secs": 0.0, "reasons": {}, "attempted": n}
        except Exception:  # noqa: BLE001 - 损坏则重建
            pass

    FX = _W["FX"]
    parse_cif = _W["parse_cif"]
    expand_sites = _W["expand_sites"]

    t0 = time.perf_counter()
    ids: list[int] = []
    d_rows: list[np.ndarray] = []
    i_rows: list[np.ndarray] = []
    nsite_rows: list[int] = []
    site_buf = bytearray()
    meta_lines: list[str] = []
    n_skip = 0
    n_peaks_total = 0
    n_sites_total = 0
    #: skip 原因分类（S7 判据要求"skip 率可分类"，不许只说"跳过了 N 条"）
    reasons: dict[str, int] = {}

    def _skip(reason: str) -> None:
        nonlocal n_skip
        n_skip += 1
        reasons[reason] = reasons.get(reason, 0) + 1

    for cod_id, rel in rows:
        path = os.path.join(COD_DIR, str(rel).replace("\\", "/"))
        try:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8", errors="replace")
            d = parse_cif(text)
        except Exception:  # noqa: BLE001 - 单条失败不拖垮整个 unit
            _skip("read_parse")
            continue

        # ---- 峰 ----
        dd = ii = None
        vol = getattr(d, "volume", 0.0) or 0.0
        if not vol:
            _skip("no_volume")
            continue
        if vol > MAX_CELL_VOL_FOR_PEAKS:
            _skip("volume_too_large")
            continue
        if not d.sites:
            _skip("no_sites")
            continue
        try:
            coords, sp_list, _u = expand_sites(d.sites, d.symops)
            if 0 < len(sp_list) <= MAX_SITES_FOR_PEAKS:
                rr, ss, oo = [], [], []
                for c, sp in zip(coords, sp_list):
                    for el, o in sp.items():
                        o = float(o)
                        rr.append(c)
                        ss.append(el)
                        oo.append(min(o, 1.0) if o > 0 else 1.0)
                out = FX.compute_pattern_arrays(
                    d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                    np.asarray(rr, dtype=float), ss, oo,
                    wavelength=WAVELENGTH, tth_range=(TTH_MIN, TTH_MAX),
                    max_hkl=MAX_HKL, half_sphere=True, scale=SCALE,
                    max_peaks=MAX_PEAKS_CALC)
                if len(out) == 2:
                    dd, ii = out
        except Exception:  # noqa: BLE001
            dd = None
        if not dd:
            _skip("no_pattern")
            continue

        d_arr = np.asarray(dd, dtype=np.float64)
        i_arr = np.asarray(ii, dtype=np.float64)
        if d_arr.size == 0 or i_arr.size == 0:
            _skip("empty_pattern")
            continue
        m = min(d_arr.size, i_arr.size)
        d_arr, i_arr = d_arr[:m], i_arr[:m]
        # 按强度降序取前 K（稳定排序）
        order = np.argsort(-i_arr, kind="stable")[:k]
        d_top = np.zeros(k, dtype=np.float32)
        i_top = np.zeros(k, dtype=np.uint16)
        dd_k = d_arr[order].astype(np.float32)
        ii_k = np.clip(np.rint(i_arr[order] / SCALE * 65535.0), 0, 65535).astype(np.uint16)
        d_top[:dd_k.size] = dd_k
        i_top[:ii_k.size] = ii_k

        # ---- 位点（非对称单位，17 B/点）----
        n_site = 0
        for s in (d.sites or []):
            try:
                _label, el, x, y, z, occ, _u = s
            except (ValueError, TypeError):
                continue
            zz = Z_OF.get(str(el).strip())
            if not zz:
                continue
            site_buf += bytes((zz,))
            site_buf += np.asarray((x, y, z, occ if occ else 1.0),
                                   dtype="<f4").tobytes()
            n_site += 1

        # ---- 元数据 ----
        B = _W["B"]
        try:
            elements, formula_red, counts = B.parse_elements(d.formula or "")
        except Exception:  # noqa: BLE001
            elements, formula_red, counts = "", "", {}
        mass = None
        try:
            mass = B.formula_mass(counts) if counts else None
        except Exception:  # noqa: BLE001
            mass = None
        znum = int(getattr(d, "z", 0) or 0)
        density = None
        if mass and vol and znum:
            density = mass * znum / (vol * 0.6022140857)

        ids.append(int(cod_id))
        d_rows.append(d_top)
        i_rows.append(i_top)
        nsite_rows.append(n_site)
        n_peaks_total += int(dd_k.size)
        n_sites_total += n_site
        meta_lines.append(json.dumps({
            "eid": int(cod_id),
            "formula": d.formula or "",
            "formula_red": formula_red or "",
            "mineral": d.name or "",
            "space_group": d.sg_name or "",
            "sg_number": int(d.sg_number or 0),
            "elements": elements or "",
            "a": d.a, "b": d.b, "c": d.c,
            "alpha": d.alpha, "beta": d.beta, "gamma": d.gamma,
            "volume": vol or None,
            "density": density,
            "z": znum,
            "n_peaks": int(dd_k.size),
            "cif_rel": rel.replace("\\", "/"),
        }, ensure_ascii=False))

    if ids:
        np.savez(
            npz_path,
            ids=np.asarray(ids, dtype=np.int64),
            d=np.vstack(d_rows).astype(np.float32),
            i=np.vstack(i_rows).astype(np.uint16),
            nsite=np.asarray(nsite_rows, dtype=np.int32),
        )
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(meta_lines))
        with open(sites_path, "wb") as fh:
            fh.write(site_buf)
    else:
        # 空 unit 也要落标记，避免每次重跑
        np.savez(npz_path, ids=np.zeros(0, np.int64), d=np.zeros((0, k), np.float32),
                 i=np.zeros((0, k), np.uint16), nsite=np.zeros(0, np.int32))
        open(jsonl_path, "w").close()
        open(sites_path, "wb").close()

    return {"unit": unit_idx, "resumed": False, "n": len(ids), "skip": n_skip,
            "peaks": n_peaks_total, "sites": n_sites_total,
            "secs": round(time.perf_counter() - t0, 1),
            "reasons": reasons, "attempted": len(rows)}


# ────────────────────────── 合并 ──────────────────────────
def _sha256(path: str, chunk: int = 4 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _set_bits(bits: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> None:
    """在 2D uint8 位图 `bits[box, byte]` 上把 (rows, cols) 位置位。"""
    if rows.size == 0:
        return
    byte_idx = cols >> 3
    values = (np.uint8(1) << (cols & 7).astype(np.uint8)).astype(np.uint8)
    np.bitwise_or.at(bits, (rows, byte_idx), values)


def build_bins(d: np.ndarray, top_m: int = BINS_TOP_M) -> np.ndarray:
    """(N,K) d 矩阵 → (N_BINS, ceil(N/8)) 位图，**只索引每相最强 top_m 条峰**。

    d 矩阵行内已按强度降序（见 process_unit），故"前 top_m 列"即最强峰。
    """
    n, k = d.shape
    m = min(int(top_m), k)
    nbytes = (n + 7) // 8
    bins = np.zeros((N_BINS, nbytes), dtype=np.uint8)
    d_top = np.asarray(d[:, :m])
    phase = np.repeat(np.arange(n, dtype=np.int64), m)
    flat = d_top.reshape(-1)
    valid = flat > 0
    phase = phase[valid]
    dv = flat[valid].astype(np.float64)
    bin_idx = np.floor(dv / BIN_WIDTH).astype(np.int64)
    bin_idx = np.clip(bin_idx, 0, N_BINS - 1)   # d>=25 落入 overflow 箱
    _set_bits(bins, bin_idx, phase)
    return bins


def build_elem(elements_list: list[str]) -> tuple[np.ndarray, dict]:
    """元素串列表 → (118, ceil(N/8)) 位图。"""
    n = len(elements_list)
    nbytes = (n + 7) // 8
    arr = np.zeros((118, nbytes), dtype=np.uint8)
    rows_idx, cols_idx = [], []
    z_counts: dict[int, int] = {}
    for i, els in enumerate(elements_list):
        for s in (els or "").split(","):
            z = Z_OF.get(s.strip())
            if not z:
                continue
            rows_idx.append(z - 1)
            cols_idx.append(i)
            z_counts[z] = z_counts.get(z, 0) + 1
    _set_bits(arr, np.asarray(rows_idx, dtype=np.int64),
              np.asarray(cols_idx, dtype=np.int64))
    return arr, z_counts


def merge(parts_dir: str, n_units: int, out_dir: str, variant: str,
          manifest_meta: dict, build_info: dict, progress=print,
          bins_top_m: int = BINS_TOP_M) -> dict:
    """按 unit 顺序合并 part → 最终 polyDB。"""
    os.makedirs(out_dir, exist_ok=True)
    # 幂等：重跑 merge 时清掉上一次的 index.sqlite（数组段用 "wb" 重写，不会残留）
    try:
        os.remove(os.path.join(out_dir, "index.sqlite"))
    except OSError:
        pass
    probe = os.path.join(parts_dir, "u00000.npz")
    k = k_of_parts(probe)
    nbytes_cache: list[int] = []

    # ---- 1) 统计总数（用于预分配）----
    total = 0
    unit_n: list[int] = []
    for u in range(n_units):
        with np.load(os.path.join(parts_dir, "u%05d.npz" % u), allow_pickle=False) as z:
            nu = int(z["ids"].size)
        unit_n.append(nu)
        total += nu
    progress("merge: %d units, %d phases, K=%d" % (n_units, total, k))

    # ---- 2) 写数组段 ----
    f_d = open(os.path.join(out_dir, "peaks_d.f32"), "wb")
    f_i = open(os.path.join(out_dir, "peaks_i.u16"), "wb")
    f_s = open(os.path.join(out_dir, "sites.bin"), "wb")
    offs = np.zeros(total + 1, dtype=np.int64)
    pos = 0
    for u in range(n_units):
        if unit_n[u] == 0:
            continue
        with np.load(os.path.join(parts_dir, "u%05d.npz" % u), allow_pickle=False) as z:
            f_d.write(z["d"].astype(np.float32).tobytes())
            f_i.write(z["i"].astype(np.uint16).tobytes())
            nsite = z["nsite"].astype(np.int64)
        with open(os.path.join(parts_dir, "u%05d.sites" % u), "rb") as fh:
            f_s.write(fh.read())
        # 位点偏移（累计）
        cum = np.cumsum(nsite) * SITE_BYTES
        offs[pos + 1:pos + 1 + nsite.size] = offs[pos] + cum
        pos += nsite.size
    f_d.close()
    f_i.close()
    f_s.close()
    np.asarray(offs[:pos + 1], dtype="<i8").tofile(os.path.join(out_dir, "sites_off.i64"))

    # ---- 3) 位图段（从 d 矩阵重算，避免 part 里冗余存储）----
    d_all = np.memmap(os.path.join(out_dir, "peaks_d.f32"), dtype=np.float32,
                      mode="r", shape=(pos, k))
    bins = build_bins(np.asarray(d_all), bins_top_m)
    del d_all
    bins.tofile(os.path.join(out_dir, "bins.u8"))

    # ---- 4) entries + 元素位图 ----
    conn = sqlite3.connect(os.path.join(out_dir, "index.sqlite"))
    conn.executescript("""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE entries (
            eid INTEGER PRIMARY KEY, formula TEXT, formula_red TEXT, mineral TEXT,
            space_group TEXT, sg_number INTEGER, elements TEXT,
            a REAL, b REAL, c REAL, alpha REAL, beta REAL, gamma REAL,
            volume REAL, density REAL, z INTEGER, n_peaks INTEGER,
            tier INTEGER DEFAULT 0, dup_group INTEGER DEFAULT 0,
            cif_rel TEXT, src_mtime INTEGER,
            row_idx INTEGER
        );
        CREATE VIRTUAL TABLE entries_fts USING fts5(
            formula, mineral, content='entries', content_rowid='eid'
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    elements_list: list[str] = []
    batch: list[tuple] = []
    n_peaks_total = 0
    row_idx = 0                       # 数组段行号（与写入顺序严格一致）
    for u in range(n_units):
        if unit_n[u] == 0:
            continue
        with open(os.path.join(parts_dir, "u%05d.jsonl" % u), encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                m = json.loads(line)
                batch.append((
                    m["eid"], m["formula"], m["formula_red"], m["mineral"],
                    m["space_group"], m["sg_number"], m["elements"],
                    m["a"], m["b"], m["c"], m["alpha"], m["beta"], m["gamma"],
                    m["volume"], m["density"], m["z"], m["n_peaks"],
                    0, 0, m["cif_rel"], 0, row_idx))
                row_idx += 1
                elements_list.append(m["elements"])
                n_peaks_total += int(m["n_peaks"])
                if len(batch) >= 20000:
                    conn.executemany(
                        "INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        batch)
                    batch.clear()
                    progress("  entries %d/%d" % (len(elements_list), total))
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch)
    conn.commit()
    conn.executescript("""
        CREATE INDEX idx_entries_formula ON entries(formula);
        CREATE INDEX idx_entries_mineral ON entries(mineral);
        CREATE INDEX idx_entries_dup ON entries(dup_group);
        CREATE UNIQUE INDEX idx_entries_row ON entries(row_idx);
        INSERT INTO entries_fts(rowid, formula, mineral)
            SELECT eid, formula, mineral FROM entries;
    """)
    elem_bits, z_counts = build_elem(elements_list)
    elem_bits.tofile(os.path.join(out_dir, "elem.u8"))
    conn.close()

    # ---- 5) meta.json ----
    shapes = {
        "peaks_d.f32": ("float32", [pos, k]),
        "peaks_i.u16": ("uint16", [pos, k]),
        "bins.u8": ("uint8", [N_BINS, (pos + 7) // 8]),
        "elem.u8": ("uint8", [118, (pos + 7) // 8]),
        "sites_off.i64": ("int64", [pos + 1]),
    }
    sections = {}
    for name, (dtype, shape) in shapes.items():
        p = os.path.join(out_dir, name)
        sections[name] = {"dtype": dtype, "shape": shape,
                          "bytes": os.path.getsize(p), "sha256": _sha256(p)}
    for name in ("sites.bin", "index.sqlite"):
        p = os.path.join(out_dir, name)
        sections[name] = {"bytes": os.path.getsize(p), "sha256": _sha256(p)}

    total_bytes = sum(v["bytes"] for v in sections.values())
    meta = {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "variant": variant,
        "peak_convention": {
            "wavelength": WAVELENGTH, "tth_min": TTH_MIN,
            "tth_max": round(TTH_MAX, 2), "d_min": D_MIN,
            "merge": "2theta", "intensity_scale": SCALE,
            "peak_select": "intensity_top", "k": int(k),
            "quant_i": "u16/65535*1000",
            "bins_top_m": int(bins_top_m),
        },
        "counts": {
            "phases": int(pos), "k": int(k),
            "peaks": int(n_peaks_total),
            "sites": int(offs[pos] // SITE_BYTES),
        },
        "sections": sections,
        "total_bytes": total_bytes,
        "source": manifest_meta,
        "build": build_info,
        "element_phase_counts": {ELEMENTS[z - 1]: c for z, c in sorted(z_counts.items())},
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return meta


def k_of_parts(npz_path: str) -> int:
    with np.load(npz_path, allow_pickle=False) as z:
        return int(z["d"].shape[1]) if z["d"].size else 0


def rebuild_bins(db_dir: str, top_m: int = BINS_TOP_M) -> dict:
    """只重建 `bins.u8`（从已有 peaks_d.f32），并刷新 meta 的字节数/校验和。

    用途：调整「索引哪几条强峰」时无需重算 53 万条 CIF（重算是小时级，这里秒级）。
    """
    meta_path = os.path.join(db_dir, "meta.json")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    n = int(meta["counts"]["phases"])
    k = int(meta["counts"]["k"])
    d = np.memmap(os.path.join(db_dir, "peaks_d.f32"), dtype=np.float32,
                  mode="r", shape=(n, k))
    bins = build_bins(np.asarray(d), top_m)
    path = os.path.join(db_dir, "bins.u8")
    bins.tofile(path)
    meta["sections"]["bins.u8"] = {
        "dtype": "uint8", "shape": [int(bins.shape[0]), int(bins.shape[1])],
        "bytes": os.path.getsize(path), "sha256": _sha256(path)}
    meta.setdefault("peak_convention", {})["bins_top_m"] = int(top_m)
    meta["total_bytes"] = sum(int(v.get("bytes", 0))
                              for v in meta["sections"].values())
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return {"db": db_dir, "bins_top_m": int(top_m),
            "bytes": os.path.getsize(path), "n": n, "k": k}


# ────────────────────────── main ──────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=("inorg", "full"), default="inorg")
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--unit", type=int, default=2000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="忽略已有 part 重算")
    ap.add_argument("--keep-parts", action="store_true", default=True)
    ap.add_argument("--bins-top-m", type=int, default=BINS_TOP_M,
                    help="位图倒排索引的强峰条数（默认 40，须 ≥ max_ref_peaks）")
    ap.add_argument("--bins-only", action="store_true",
                    help="只从已有 peaks_d.f32 重建 bins.u8（需配合 --out 指向现有库）")
    args = ap.parse_args(argv)

    if args.bins_only:
        if not args.out or not os.path.isdir(args.out):
            print("--bins-only 需要 --out 指向一个已存在的 polyDB 目录")
            return 2
        rep = rebuild_bins(args.out, args.bins_top_m)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    variant = "cod-inorg" if args.scope == "inorg" else "cod-full"
    stamp = datetime.now().strftime("%Y%m%d")
    out_dir = args.out or os.path.join(
        POLYDB_DIR, "COD-%s-%s.polyDB" % ("Inorg" if args.scope == "inorg" else "Full", stamp))
    parts_dir = os.path.join(PARTS_ROOT, variant)
    if args.force and os.path.isdir(parts_dir):
        shutil.rmtree(parts_dir)
    os.makedirs(parts_dir, exist_ok=True)
    if args.limit and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)

    # 清单
    con = sqlite3.connect("file:%s?mode=ro" % MANIFEST, uri=True)
    where = "AND is_inorg=1" if args.scope == "inorg" else ""
    sql = ("SELECT cod_id, rel FROM files WHERE lib='COD' %s ORDER BY cod_id" % where)
    if args.limit:
        sql += " LIMIT %d" % int(args.limit)
    rows = [(int(c), r) for c, r in con.execute(sql)]
    meta_row = dict(con.execute("SELECT key, value FROM meta").fetchall())
    con.close()
    print("scope=%s phases=%d out=%s" % (args.scope, len(rows), out_dir))

    units = [rows[i:i + args.unit] for i in range(0, len(rows), args.unit)]
    tasks = [(i, u, parts_dir, K) for i, u in enumerate(units)]
    t0 = time.perf_counter()
    done = 0
    total_n = 0
    total_skip = 0
    total_attempted = 0
    total_reasons: dict[str, int] = {}
    import multiprocessing as mp
    with mp.Pool(max(1, args.workers), initializer=_init_worker) as pool:
        for r in pool.imap_unordered(process_unit, tasks):
            done += 1
            total_n += r["n"]
            total_skip += r["skip"]
            total_attempted += r.get("attempted", 0)
            for kk, vv in (r.get("reasons") or {}).items():
                total_reasons[kk] = total_reasons.get(kk, 0) + int(vv)
            el = time.perf_counter() - t0
            eta = el / done * (len(tasks) - done)
            print("  unit %d/%d  n=%d skip=%d  %.1fs elapsed, ETA %.0fs%s"
                  % (r["unit"] + 1, len(tasks), r["n"], r["skip"], el, eta,
                     " (resumed)" if r["resumed"] else ""), flush=True)

    build_info = {
        "tool": "build_polydb.py", "tool_version": TOOL_VERSION,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "workers": args.workers, "skipped": int(total_skip),
        "skip_reasons": dict(sorted(total_reasons.items())),
        "attempted": int(total_attempted),
        "unit_size": args.unit,
    }
    # 守恒检查：输入条数 == 入库条数 + 跳过条数。不平就是断点续跑留下的陈旧
    # part（历史事故：79,198 条输入只入库 72,149，却只报了 1,345 条 skip）。
    listed = len(rows)
    if total_attempted != listed or total_n + total_skip != listed:
        print("\n⚠️  条数不守恒：清单 %d，尝试 %d，入库 %d + 跳过 %d = %d"
              % (listed, total_attempted, total_n, total_skip,
                 total_n + total_skip))
        print("    多半是 parts 目录里有陈旧 part 文件（断点续跑）。用 --force 重算。")
    if total_reasons:
        print("  skip 原因：" + ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(total_reasons.items())))
    manifest_meta = {
        "lib": "COD", "root": COD_DIR, "manifest": MANIFEST,
        "manifest_built_at": meta_row.get("built_at", ""),
        "n_manifest": len(rows), "scope": args.scope,
    }
    meta = merge(parts_dir, len(tasks), out_dir, variant, manifest_meta, build_info,
                 bins_top_m=args.bins_top_m)
    print("\nDONE  %s" % out_dir)
    print("  phases=%d k=%d total=%.1f MB"
          % (meta["counts"]["phases"], meta["counts"]["k"],
             meta["total_bytes"] / 2**20))
    print("  skipped=%d elapsed=%.0fs"
          % (build_info["skipped"], build_info["elapsed_s"]))
    if not args.keep_parts:
        shutil.rmtree(parts_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
