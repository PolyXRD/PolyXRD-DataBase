#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MP (Materials Project) CIF → ``*.polyDB`` 目录容器（polyDB v4 规范）。

与 COD 建库器 (``build_polydb.py``) 的**本质差异** —— MP 的 CIF 是 pymatgen
导出的 **P1 原始胞**，而 polyDB 的侧车语义是「非对称单位 + 空间群」，下游
``expand_sites_by_symmetry`` 按 ``entries.space_group`` 的对称操作展开。
两者的坐标系必须自洽，否则会造出假峰（v4.1.1 Corundum R-3c 事故的同类）。

因此本构建器对每条 MP CIF 做三件事：

1. **原胞 → 常规胞**：``SpacegroupAnalyzer.get_conventional_standard_structure()``。
   常规胞的度规是「对称适配」的，��价反射的 |G| 严格相等；而原始胞（尤其是
   F/I/C 心晶格）的斜方度规会让等价反射的 2θ 出现 ~1e-7 量级的数值分裂，
   同一条物理线被拆成两条（实测 KBaSb 立方 (444)：原胞框架 29.761 + 9.920，
   常规胞框架正确合并为单线 39.681）。
2. **常规胞 → 非对称单位**：在常规胞坐标系里再跑一次 SGA 取等价位点组，
   存进 ``sites.bin``（17 B/点），``entries.space_group`` 写真实空间群。
   下游按真实 SG 展开 → 复原常规胞 ✅。
3. **峰在常规胞上计算**：口径（λ / 2θ 范围 / 按 2θ 合并 / I 归一 1000 /
   强度前 K=100 / u16 量化）与规范 §2 完全一致，但输入晶胞用常规胞，
   才能得到与实验一致的「一条物理线一条峰」。

**三级回退**（每条都保证下游拿到的是正确全胞，不会造假峰）：

===== ================================ ==========================================
级别  侧车                            space_group / 晶胞
===== ================================ ==========================================
L0    常规胞非对称单位（展开校验过）  真实 SG / 常规胞
L1    常规胞全部原子                   ``P 1``   / 常规胞
L2    原胞全部原子                     ``P 1``   / 原胞（常规胞过大或 SGA 失败）
===== ================================ ==========================================

用法::

    python tools/build_mp_polydb.py --workers 8
    python tools/build_mp_polydb.py --limit 2000 --out D:/tmp/mp_test.polyDB
    python tools/build_mp_polydb.py --manifest-only        # 只扫源目录出清单

源数据默认 ``D:/Project/MP-summary/cif``（可用 ``XRD_MP_CIF_DIR`` 覆盖），
产物默认写到本仓库 ``polydb/MP-20261031.polyDB``。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402

import build_polydb as BP  # noqa: E402  —— 复用 merge / build_bins / build_elem

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP_CIF_DIR = os.environ.get("XRD_MP_CIF_DIR") or r"D:\Project\MP-summary\cif"
MP_REPORT = os.environ.get("XRD_MP_REPORT") or r"D:\Project\MP-summary\report.csv"
PARTS_ROOT = os.path.join(REPO_ROOT, "_mp_polydb_parts")
POLYDB_DIR = os.path.join(REPO_ROOT, "polydb")

VARIANT = "mp-20261031"
DEFAULT_OUT = os.path.join(POLYDB_DIR, "MP-20261031.polyDB")

#: 峰口径 —— 与 build_polydb.py / 规范 §2 逐字一致
WAVELENGTH = BP.WAVELENGTH
TTH_MIN = BP.TTH_MIN
TTH_MAX = BP.TTH_MAX
SCALE = BP.SCALE
K = BP.K
MAX_PEAKS_CALC = BP.MAX_PEAKS_CALC
MAX_SITES_FOR_PEAKS = BP.MAX_SITES_FOR_PEAKS
MAX_CELL_VOL_FOR_PEAKS = BP.MAX_CELL_VOL_FOR_PEAKS
MAX_HKL = BP.MAX_HKL
SITE_BYTES = BP.SITE_BYTES
Z_OF = BP.Z_OF

#: SGA 容差：与 PolyXRD / pymatgen 常用值一致（0.1 Å 对 DFT 结构足够）
SYMPREC = 0.1
ANGLE_TOL = 5.0

#: MP CIF 头部：``# mp-id: mp-XXXX | spacegroup: Xxx | energy_above_hull: ...``
#: 注意数值正则不能写成 ``[-+0-9.eE]+`` —— 那会把单位里的 ``e``（eV/atom）也吞进
#: 捕获组，float() 直接炸。而部分条目（MP 导出时 energy_above_hull 为空）的
#: 头部形如 ``energy_above_hull:  eV/atom`` —— 数值本身可缺，整行不可缺。
HDR_RE = re.compile(
    r"^#\s*mp-id:\s*((?:mp|mvc)-\d+)\s*\|\s*spacegroup:\s*(\S+)\s*\|"
    r"\s*energy_above_hull:\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)?",
    re.M)
#: 无 mp-id 头的老文件兜底号段（与 COD/PCOD/TCOD 号段都不冲突）
FALLBACK_EID_BASE = 900_000_000

#: MP 条目在 polyDB 里的 tier（规范：1=实验测定 2=理论/预测）
TIER_THEORY = 2


# ────────────────────────── 清单 ──────────────────────────
def scan_manifest(cif_dir: str, limit: int = 0) -> list[dict]:
    """扫源目录 → 清单（按 eid 升序）。

    每条记录: ``{eid, mp_id, sg_hdr, eah, rel, formula}``。
    ``formula`` 优先取 MP 的 ``_chemical_formula_structural``（= report.csv 的
    reduced_formula），缺失时退回文件名词干。
    """
    files = sorted(f for f in os.listdir(cif_dir) if f.lower().endswith(".cif"))
    if limit:
        files = files[:limit]
    rows: list[dict] = []
    seq = 0
    for fn in files:
        path = os.path.join(cif_dir, fn)
        try:
            with open(path, "rb") as fh:
                head = fh.read(2048).decode("utf-8", errors="replace")
        except OSError:
            continue
        m = HDR_RE.search(head)
        if m:
            mp_id = m.group(1)
            sg_hdr = m.group(2)
            eah = float(m.group(3)) if m.group(3) else None
            if mp_id.startswith("mp-"):
                eid = int(mp_id[3:])
            else:
                #: mvc-XXXX（MPContribs 条目）：落 9 亿兜底段，号段内唯一
                eid = FALLBACK_EID_BASE + int(mp_id.split("-", 1)[1])
        else:
            mp_id = ""
            sg_hdr = ""
            eah = None
            eid = FALLBACK_EID_BASE + seq
            seq += 1
        f_struct = ""
        fm = re.search(r"^_chemical_formula_structural\s+(.+)$", head, re.M)
        if fm:
            f_struct = fm.group(1).strip().strip("'\"")
        if not f_struct:
            f_struct = os.path.splitext(fn)[0]
        rows.append({"eid": eid, "mp_id": mp_id, "sg_hdr": sg_hdr, "eah": eah,
                     "rel": fn, "formula": f_struct})
    rows.sort(key=lambda r: r["eid"])
    return rows


def load_report_map(report_path: str) -> dict[str, dict]:
    """report.csv → ``{cif_file: row}``（补充 energy_above_hull / is_stable）。"""
    out: dict[str, dict] = {}
    if not os.path.isfile(report_path):
        return out
    try:
        csv.field_size_limit(10 ** 9)
        with open(report_path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("is_kept") != "True":
                    continue
                out[r["cif_file"]] = r
    except Exception:  # noqa: BLE001 - 报表只是补充信息，读不到不影响建库
        pass
    return out


# ────────────────────────── worker ──────────────────────────
_W: dict = {}


def _init_worker() -> None:
    """worker 进程初始化：导入重模块 + 预热散射因子表。

    注意：Windows 的 multiprocessing 用 spawn，worker 会**重新导入本模块**，
    所以任何运行期参数（含 ``--cif-dir``）都必须经 task 元组传进来，不能靠
    模块级全局量。
    """
    import cif_common as B  # noqa: F401
    import fastxrd as FX  # noqa: F401
    from fastcif import parse_cif, expand_sites  # noqa: F401
    _W["B"] = B
    _W["FX"] = FX
    _W["parse_cif"] = parse_cif
    _W["expand_sites"] = expand_sites
    FX._load_params()
    # 下游展开口径（校验「非对称单位 + SG → 复原常规胞」用）
    _W["poly_src"] = os.path.join(os.path.dirname(REPO_ROOT), "PolyXRD", "src")
    if _W["poly_src"] not in sys.path:
        sys.path.insert(0, _W["poly_src"])


def _group_sites(frac: np.ndarray, elems: list[str], occs: list[float]):
    """同坐标的多个元素合并成一个混占位点 → ``(coords, species_dict)`` 列表。

    MP 的 CIF 里混占位点是**按元素分行**写的（同一坐标两行 Al 0.512 / Si 0.488），
    直接当两个独立位点塞给 pymatgen 会让 SGA 误判对称性。

    .. note:: 2026-10-31 修复：原实现返回 ``PeriodicSite`` 却未传 ``lattice``
       （``PeriodicSite`` 的必填参数），导致每条 CIF 都抛 ``TypeError`` 被
       上层吞掉，整库退化成 L2（原胞 P1）—— 这正是本构建器想避免的假峰来源。
       现在改为直接返回 pymatgen ``Structure`` 可吃的 ``(coords, {el: occ})``。
    """
    buckets: dict[tuple, list[tuple[str, float]]] = {}
    order: list[tuple] = []
    for c, el, oc in zip(frac, elems, occs):
        key = (round(float(c[0]), 6), round(float(c[1]), 6), round(float(c[2]), 6))
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append((str(el), float(oc)))
    coords, species = [], []
    for key in order:
        occ_by_el: dict[str, float] = {}
        for el, oc in buckets[key]:
            occ_by_el[el] = occ_by_el.get(el, 0.0) + (min(oc, 1.0) if oc > 0 else 1.0)
        coords.append(list(key))
        species.append(occ_by_el)
    return coords, species


def _build_structure(d, frac, elems, occs):
    """原胞 → pymatgen ``Structure``。"""
    from pymatgen.core import Lattice, Structure

    lat = Lattice.from_parameters(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
    coords, species = _group_sites(np.asarray(frac, dtype=float), elems, occs)
    return Structure(lat, species, coords, coords_are_cartesian=False)


def _structure_to_arrays(struct):
    """pymatgen Structure → (frac, elems, occs)（按位点/物种展开）。"""
    frac, elems, occs = [], [], []
    for site in struct:
        for spc, oc in site.species.items():
            el = getattr(getattr(spc, "element", spc), "symbol", None) or str(spc)
            frac.append(site.frac_coords)
            elems.append(str(el))
            occs.append(float(oc))
    return (np.asarray(frac, dtype=float) if frac else np.zeros((0, 3)),
            elems, occs)


def _site_records(struct):
    """Structure → [(element, x, y, z, occ)]（混占位点按物种拆成多条）。"""
    out = []
    for site in struct:
        for spc, oc in site.species.items():
            el = getattr(getattr(spc, "element", spc), "symbol", None) or str(spc)
            out.append((str(el), float(site.frac_coords[0]),
                        float(site.frac_coords[1]), float(site.frac_coords[2]),
                        float(oc)))
    return out


def _compute_peaks(a, b, c, al, be, ga, frac, elems, occs):
    """按规范 §2 的口径算峰（λ / 2θ 范围 / 按 2θ 合并 / I 归一 1000）。"""
    FX = _W["FX"]
    if frac is None or len(frac) == 0 or len(elems) == 0:
        return None, None
    if len(elems) > MAX_SITES_FOR_PEAKS:
        return None, None
    out = FX.compute_pattern_arrays(
        a, b, c, al, be, ga,
        np.asarray(frac, dtype=float), list(elems), list(occs),
        wavelength=WAVELENGTH, tth_range=(TTH_MIN, TTH_MAX),
        max_hkl=MAX_HKL, half_sphere=True, scale=SCALE,
        max_peaks=MAX_PEAKS_CALC)
    if len(out) != 2:
        return None, None
    return out


def process_unit(task: tuple) -> dict:
    """处理一个 unit，产出 part 文件。返回统计。"""
    unit_idx, rows, parts_dir, k, cif_dir = task
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
    B = _W["B"]

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
    reasons: dict[str, int] = {}
    #: 回退级别统计（L0 理想 / L1 常规胞全原子 / L2 原胞）
    levels: dict[str, int] = {}

    def _skip(reason: str) -> None:
        nonlocal n_skip
        n_skip += 1
        reasons[reason] = reasons.get(reason, 0) + 1

    for row in rows:
        path = os.path.join(cif_dir, str(row["rel"]).replace("\\", "/"))
        try:
            with open(path, "rb") as fh:
                text = fh.read().decode("utf-8", errors="replace")
            d = parse_cif(text)
        except Exception:  # noqa: BLE001 - 单条失败不拖垮整个 unit
            _skip("read_parse")
            continue

        vol_prim = getattr(d, "volume", 0.0) or 0.0
        if not vol_prim:
            _skip("no_volume")
            continue
        if not d.sites:
            _skip("no_sites")
            continue

        # ---- 原胞：展开 CIF 位点 ----
        try:
            coords, sp_list, _u = expand_sites(d.sites, d.symops)
        except Exception:  # noqa: BLE001
            _skip("expand_sites")
            continue
        if coords is None or len(coords) == 0:
            _skip("no_sites")
            continue
        frac_p, elem_p, occ_p = [], [], []
        for c, sp in zip(coords, sp_list):
            for el, o in sp.items():
                o = float(o)
                frac_p.append(c)
                elem_p.append(el)
                occ_p.append(min(o, 1.0) if o > 0 else 1.0)
        n_spec_prim = len(elem_p)

        # ---- 常规胞（SGA）----
        conv = None
        sg_sym = ""
        sg_num = 0
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

            st_prim = _build_structure(d, frac_p, elem_p, occ_p)
            sga = SpacegroupAnalyzer(st_prim, symprec=SYMPREC, angle_tolerance=ANGLE_TOL)
            conv = sga.get_conventional_standard_structure()
            sg_num = int(sga.get_space_group_number())
            sg_sym = str(sga.get_space_group_symbol() or "")
        except Exception:  # noqa: BLE001 - SGA 失败 → 退回 L2
            conv = None

        # ---- 选级别 ----
        level = "L2"
        use_conv = False
        if conv is not None:
            cfrac, celem, cocc = _structure_to_arrays(conv)
            p = conv.lattice.parameters
            v_conv = float(conv.volume)
            if (len(celem) <= MAX_SITES_FOR_PEAKS
                    and v_conv <= MAX_CELL_VOL_FOR_PEAKS):
                use_conv = True
            else:
                _skip("conv_too_large")
        if use_conv:
            # L0：常规胞非对称单位（须能展开复原常规胞）
            asym = None
            try:
                from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

                sga2 = SpacegroupAnalyzer(conv, symprec=SYMPREC, angle_tolerance=ANGLE_TOL)
                ss = sga2.get_symmetrized_structure()
                groups = getattr(ss, "equivalent_sites", None) or ss.equivalent_site_groups
                asym = []
                for g in groups:
                    site = g[0]
                    for spc, oc in site.species.items():
                        el = getattr(getattr(spc, "element", spc), "symbol", None) or str(spc)
                        asym.append({
                            "label": "X", "element": str(el),
                            "x": float(site.frac_coords[0]),
                            "y": float(site.frac_coords[1]),
                            "z": float(site.frac_coords[2]),
                            "occupancy": float(oc)})
            except Exception:  # noqa: BLE001
                asym = None
            if asym:
                try:
                    from polyxrd.services.phase_cif import expand_sites_by_symmetry

                    exp = expand_sites_by_symmetry(asym, sg_sym, strict=True)
                except Exception:  # noqa: BLE001
                    exp = None
                if exp is not None and len(exp) == len(celem):
                    level = "L0"
                    sidecar = [(a["element"], a["x"], a["y"], a["z"], a["occupancy"])
                               for a in asym]
                    sg_out = sg_sym
                else:
                    level = "L1"
                    sidecar = _site_records(conv)
                    sg_out = "P 1"
            else:
                level = "L1"
                sidecar = _site_records(conv)
                sg_out = "P 1"
            cell = (float(p[0]), float(p[1]), float(p[2]),
                    float(p[3]), float(p[4]), float(p[5]))
            vol = v_conv
            frac_peak, elem_peak, occ_peak = cfrac, celem, cocc
            n_spec = len(celem)
        else:
            # L2：原胞全部原子 + P 1
            level = "L2"
            sidecar = [(elem_p[i], float(frac_p[i][0]), float(frac_p[i][1]),
                        float(frac_p[i][2]), float(occ_p[i]))
                       for i in range(n_spec_prim)]
            sg_out = "P 1"
            cell = (float(d.a), float(d.b), float(d.c),
                    float(d.alpha), float(d.beta), float(d.gamma))
            vol = vol_prim
            frac_peak, elem_peak, occ_peak = frac_p, elem_p, occ_p
            n_spec = n_spec_prim

        # ---- 峰 ----
        dd, ii = _compute_peaks(*cell, frac_peak, elem_peak, occ_peak)
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
        order = np.argsort(-i_arr, kind="stable")[:k]     # 强度降序取前 K
        d_top = np.zeros(k, dtype=np.float32)
        i_top = np.zeros(k, dtype=np.uint16)
        dd_k = d_arr[order].astype(np.float32)
        ii_k = np.clip(np.rint(i_arr[order] / SCALE * 65535.0), 0, 65535).astype(np.uint16)
        d_top[:dd_k.size] = dd_k
        i_top[:ii_k.size] = ii_k

        # ---- 侧车位点（17 B/点）----
        n_site = 0
        for el, x, y, z, occ in sidecar:
            zz = Z_OF.get(str(el).strip())
            if not zz:
                continue
            site_buf += bytes((zz,))
            site_buf += np.asarray((x, y, z, occ if occ else 1.0),
                                   dtype="<f4").tobytes()
            n_site += 1

        # ---- 元数据 ----
        formula_display = row.get("formula") or ""
        try:
            elements, formula_red, counts = B.parse_elements(d.formula or "")
        except Exception:  # noqa: BLE001
            elements, formula_red, counts = "", "", {}
        if not elements and formula_display:
            try:
                elements, formula_red, counts = B.parse_elements(formula_display)
            except Exception:  # noqa: BLE001
                elements, formula_red, counts = "", "", {}
        mass = None
        try:
            mass = B.formula_mass(counts) if counts else None
        except Exception:  # noqa: BLE001
            mass = None
        z_prim = int(getattr(d, "z", 0) or 0)
        ratio = (n_spec / n_spec_prim) if n_spec_prim else 1.0
        z_num = int(round(z_prim * ratio)) if z_prim else 0
        density = None
        if mass and vol and z_num:
            density = mass * z_num / (vol * 0.6022140857)

        ids.append(int(row["eid"]))
        d_rows.append(d_top)
        i_rows.append(i_top)
        nsite_rows.append(n_site)
        n_peaks_total += int(dd_k.size)
        n_sites_total += n_site
        levels[level] = levels.get(level, 0) + 1
        meta_lines.append(json.dumps({
            "eid": int(row["eid"]),
            "formula": formula_display,
            "formula_red": formula_red or "",
            "mineral": (str(row.get("mp_id") or "")) or "",
            "space_group": sg_out,
            "sg_number": int(sg_num) if level == "L0" else 1,
            "elements": elements or "",
            "a": cell[0], "b": cell[1], "c": cell[2],
            "alpha": cell[3], "beta": cell[4], "gamma": cell[5],
            "volume": vol or None,
            "density": density,
            "z": z_num,
            "n_peaks": int(dd_k.size),
            "cif_rel": str(row["rel"]).replace("\\", "/"),
            "level": level,
            "mp_id": row.get("mp_id") or "",
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
        np.savez(npz_path, ids=np.zeros(0, np.int64), d=np.zeros((0, k), np.float32),
                 i=np.zeros((0, k), np.uint16), nsite=np.zeros(0, np.int32))
        open(jsonl_path, "w").close()
        with open(sites_path, "wb") as fh:
            fh.write(b"")

    return {"unit": unit_idx, "resumed": False, "n": len(ids), "skip": n_skip,
            "peaks": n_peaks_total, "sites": n_sites_total,
            "secs": round(time.perf_counter() - t0, 1),
            "reasons": reasons, "levels": levels, "attempted": len(rows)}


# ────────────────────────── main ──────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cif-dir", default=MP_CIF_DIR)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--variant", default=VARIANT)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--unit", type=int, default=2000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="忽略已有 part 重算")
    ap.add_argument("--manifest-only", action="store_true", help="只扫源目录出清单")
    ap.add_argument("--keep-parts", action="store_true", default=True)
    args = ap.parse_args(argv)

    t_scan = time.perf_counter()
    rows = scan_manifest(args.cif_dir, args.limit)
    print("源目录 %s" % args.cif_dir)
    print("清单 %d 条，扫描用时 %.1fs" % (len(rows), time.perf_counter() - t_scan))
    n_nohdr = sum(1 for r in rows if not r["mp_id"])
    print("  带 mp-id 头 %d，无头（兜底号段）%d"
          % (len(rows) - n_nohdr, n_nohdr))
    if args.manifest_only:
        out_json = os.path.join(PARTS_ROOT, "manifest.jsonl")
        os.makedirs(PARTS_ROOT, exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("清单已写 %s" % out_json)
        return 0

    parts_dir = os.path.join(PARTS_ROOT, args.variant)
    if args.force and os.path.isdir(parts_dir):
        shutil.rmtree(parts_dir)
    os.makedirs(parts_dir, exist_ok=True)

    units = [rows[i:i + args.unit] for i in range(0, len(rows), args.unit)]
    tasks = [(i, u, parts_dir, K, args.cif_dir) for i, u in enumerate(units)]
    print("units=%d workers=%d out=%s" % (len(tasks), args.workers, args.out))

    import multiprocessing as mp
    t0 = time.perf_counter()
    done = 0
    total_n = 0
    total_skip = 0
    total_attempted = 0
    total_reasons: dict[str, int] = {}
    total_levels: dict[str, int] = {}
    with mp.Pool(max(1, args.workers), initializer=_init_worker) as pool:
        for r in pool.imap_unordered(process_unit, tasks):
            done += 1
            total_n += r["n"]
            total_skip += r["skip"]
            total_attempted += r.get("attempted", 0)
            for kk, vv in (r.get("reasons") or {}).items():
                total_reasons[kk] = total_reasons.get(kk, 0) + int(vv)
            for kk, vv in (r.get("levels") or {}).items():
                total_levels[kk] = total_levels.get(kk, 0) + int(vv)
            el = time.perf_counter() - t0
            eta = el / done * (len(tasks) - done)
            print("  unit %d/%d  n=%d skip=%d  %.1fs elapsed, ETA %.0fs%s"
                  % (r["unit"] + 1, len(tasks), r["n"], r["skip"], el, eta,
                     " (resumed)" if r["resumed"] else ""), flush=True)

    build_info = {
        "tool": "build_mp_polydb.py", "tool_version": "1.0",
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "workers": args.workers, "skipped": int(total_skip),
        "skip_reasons": dict(sorted(total_reasons.items())),
        "cell_representations": dict(sorted(total_levels.items())),
        "attempted": int(total_attempted),
        "unit_size": args.unit,
        "symprec": SYMPREC, "angle_tolerance": ANGLE_TOL,
    }
    listed = len(rows)
    if total_attempted != listed or total_n + total_skip != listed:
        print("\n⚠️  条数不守恒：清单 %d，尝试 %d，入库 %d + 跳过 %d = %d"
              % (listed, total_attempted, total_n, total_skip,
                 total_n + total_skip))
        print("    多半是 parts 目录里有陈旧 part 文件（断点续跑）。用 --force 重算。")
    if total_reasons:
        print("  skip 原因：" + ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(total_reasons.items())))
    if total_levels:
        print("  晶胞表示：" + ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(total_levels.items())))

    report_map = load_report_map(MP_REPORT)
    source_meta = {
        "lib": "MP",
        "root": args.cif_dir,
        "dataset": "Materials Project summary (CIF 导出)",
        "report": MP_REPORT if os.path.isfile(MP_REPORT) else "",
        "n_manifest": listed,
        "n_report_rows": len(report_map),
        "scope": "mp",
    }
    meta = BP.merge(parts_dir, len(tasks), args.out, args.variant,
                    source_meta, build_info)

    # tier 修正：MP 条目全部是「理论/预测」（规范 §4.6 tier=2）。
    # merge() 固定写 0，这里改写并刷新 meta.json 里 index.sqlite 的校验和。
    import sqlite3
    conn = sqlite3.connect(os.path.join(args.out, "index.sqlite"))
    conn.execute("UPDATE entries SET tier=?", (TIER_THEORY,))
    conn.commit()
    conn.close()
    meta_path = os.path.join(args.out, "meta.json")
    with open(meta_path, encoding="utf-8") as fh:
        meta = json.load(fh)
    idx_path = os.path.join(args.out, "index.sqlite")
    meta["sections"]["index.sqlite"]["bytes"] = os.path.getsize(idx_path)
    meta["sections"]["index.sqlite"]["sha256"] = BP._sha256(idx_path)
    meta["total_bytes"] = sum(int(v.get("bytes", 0)) for v in meta["sections"].values())
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print("\nDONE  %s" % args.out)
    print("  phases=%d k=%d total=%.1f MB"
          % (meta["counts"]["phases"], meta["counts"]["k"],
             meta["total_bytes"] / 2 ** 20))
    print("  skipped=%d elapsed=%.0fs"
          % (build_info["skipped"], build_info["elapsed_s"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
