#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3COD（COD + PCOD + TCOD）→ PolyXRD / XinMatch 双项目可外挂数据库。

依据 E:\\rsync-COD\\sync-COD-pack\\COD打包规范_CIF到SQLite.md（权威）与
reference/{xinmatch,polyxrd}/*.sql 的逐字 DDL。

产物（单一格式 .sqlite；旧 .db 副本已按用户决定废弃）:
    3COD-Full-20261015.sqlite
        XinMatch 侧: entries / peaks / elements / element_combo
        PolyXRD  侧: cod_entries / cod_atomic_sites(含 u_iso) / meta
    3COD-Inorg-20261015.sqlite
        XinMatch 侧: entries / peaks / elements / element_combo
        PolyXRD  侧: phases / cod_atomic_sites(无 u_iso) / meta

统一编号（三库原始编号互相重叠，必须错位）:
    COD 原号 / PCOD +20,000,000 / TCOD +100,000,000
    entry_id = ref_id = display_id = "96-" + zfill(7)[:3] + "-" + zfill(7)[3:]
              （与 XinMatch _entry_id_for_cod 逐字同式；8~9 位号段同样唯一）
峰口径（用户选定：fastxrd 合并口径）:
    λ=1.5406 Å, d ≥ 1.0 Å, 等价反射按 2θ 合并（真实粉末强度，含多重性），
    强度归一 max=1000。XinMatch peaks 取强度前 100 并回填 h/k/l；
    PolyXRD phases 存全量 CSV（d 降序）+ 最强 64 条 float64 小端 BLOB。
不内嵌 cif_gz，故 meta.variant 必须以 "slim-index" 开头（运行时契约 §2）。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import math
import os
import re
import shutil
import sqlite3
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np  # noqa: E402
import build_dbs as B  # noqa: E402
import fastxrd as FX  # noqa: E402
from fastcif import parse_cif, expand_sites  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = os.path.join(BASE, "_3cod_parts")
STAMP = "20261015"
FULL_DB = os.path.join(BASE, "3COD-Full-%s.sqlite" % STAMP)
INORG_DB = os.path.join(BASE, "3COD-Inorg-%s.sqlite" % STAMP)

LIBS = [
    ("COD", os.path.join(BASE, "COD"), 3, 0),
    ("PCOD", os.path.join(BASE, "PCOD"), 2, 20_000_000),
    ("TCOD", os.path.join(BASE, "TCOD"), 3, 100_000_000),
]

WAVELENGTH = 1.5406
TTH_MIN = 5.0
TTH_MAX = math.degrees(2.0 * math.asin(min(1.0, WAVELENGTH / (2.0 * 1.0))))  # 100.76°
SCALE = 1000.0
TOP_XIN = 100        # XinMatch peaks 行表条数
TOP_POLY = 100       # PolyXRD phases CSV 上限（2026-10-19：500→100，检索耗时 ≈ 表字节数）
TOP_BLOB = 64        # PolyXRD 预截断 BLOB（cif_database._PEAK_TOP_N）
MAX_SITES_FOR_PEAKS = 1500
MAX_CELL_VOL_FOR_PEAKS = 30000
MAX_HKL = 30_000
EST_TOTAL_FILES = 1_838_367   # 2026-10-14 核验值：COD 535,166 + PCOD 1,061,964 + TCOD 241,237

# 标准原子量（用于从 formula + 晶胞 + Z 反算密度，XinMatch entries.density）
ATOMIC_MASS = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81, "C": 12.011,
    "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180, "Na": 22.990, "Mg": 24.305,
    "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06, "Cl": 35.45, "Ar": 39.948,
    "K": 39.098, "Ca": 40.078, "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996,
    "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904, "Kr": 83.798,
    "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224, "Nb": 92.906, "Mo": 95.95,
    "Tc": 98.0, "Ru": 101.07, "Rh": 102.91, "Pd": 106.42, "Ag": 107.87, "Cd": 112.41,
    "In": 114.82, "Sn": 118.71, "Sb": 121.76, "Te": 127.60, "I": 126.90, "Xe": 131.29,
    "Cs": 132.91, "Ba": 137.33, "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24,
    "Pm": 145.0, "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93, "Dy": 162.50,
    "Ho": 164.93, "Er": 167.26, "Tm": 168.93, "Yb": 173.05, "Lu": 174.97, "Hf": 178.49,
    "Ta": 180.95, "W": 183.84, "Re": 186.21, "Os": 190.23, "Ir": 192.22, "Pt": 195.08,
    "Au": 196.97, "Hg": 200.59, "Tl": 204.38, "Pb": 207.2, "Bi": 208.98, "Po": 209.0,
    "At": 210.0, "Rn": 222.0, "Fr": 223.0, "Ra": 226.0, "Ac": 227.0, "Th": 232.04,
    "Pa": 231.04, "U": 238.03, "Np": 237.0, "Pu": 244.0, "Am": 243.0, "Cm": 247.0,
    "Bk": 247.0, "Cf": 251.0, "Es": 252.0, "Fm": 257.0, "Md": 258.0, "No": 259.0,
    "Lr": 262.0, "Rf": 267.0, "Db": 268.0, "Sg": 269.0, "Bh": 270.0, "Hs": 269.0,
    "Mt": 278.0, "Ds": 281.0, "Rg": 282.0, "Cn": 285.0, "Nh": 286.0, "Fl": 289.0,
    "Mc": 290.0, "Lv": 293.0, "Ts": 294.0, "Og": 294.0, "D": 2.014,
}


def formula_mass(counts: dict) -> float | None:
    """由元素计数算摩尔质量；有任一未知元素则返回 None。"""
    if not counts:
        return None
    tot = 0.0
    for el, n in counts.items():
        m = ATOMIC_MASS.get(el)
        if m is None:
            return None
        tot += m * float(n)
    return tot or None


def density_of(counts: dict, z, volume) -> float | None:
    """ρ = Z·M / (N_A·V)  →  g/cm³（V 单位 Å³，0.6022 = N_A×1e-24）。"""
    m = formula_mass(counts)
    if not m or not volume or not z:
        return None
    try:
        rho = float(z) * m / (0.6022 * float(volume))
    except (TypeError, ZeroDivisionError):
        return None
    return round(rho, 4) if 0.1 < rho < 30.0 else None


_RE_DIGIT = re.compile(r"(\d+)")

# ---------------------------------------------------------------------------
# DDL：逐字取自 sync-COD-pack/reference
# ---------------------------------------------------------------------------
XINMATCH_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    entry_id       TEXT PRIMARY KEY,
    formula        TEXT,
    mineral_name   TEXT,
    space_group    TEXT,
    crystal_system TEXT,
    a              REAL,
    b              REAL,
    c              REAL,
    alpha          REAL,
    beta           REAL,
    gamma          REAL,
    volume         REAL,
    density        REAL,
    color          TEXT,
    year           INTEGER,
    author         TEXT,
    journal        TEXT,
    quality        TEXT,
    elements       TEXT
);
CREATE TABLE IF NOT EXISTS peaks (
    entry_id  TEXT NOT NULL,
    d         REAL NOT NULL,
    intensity REAL,
    h         INTEGER,
    k         INTEGER,
    l         INTEGER,
    FOREIGN KEY (entry_id) REFERENCES entries(entry_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS elements (
    entry_id TEXT NOT NULL,
    element  TEXT NOT NULL,
    PRIMARY KEY (entry_id, element)
);
CREATE TABLE IF NOT EXISTS element_combo (
    element_set_hash TEXT PRIMARY KEY,
    entry_ids        TEXT NOT NULL
);
"""

POLY_FULL_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS cod_entries (
    cod_id        INTEGER PRIMARY KEY,
    file          TEXT NOT NULL,
    mineral_name  TEXT,
    formula       TEXT,
    formula_red   TEXT,
    elements      TEXT,
    space_group   TEXT,
    space_group_number INTEGER DEFAULT 0,
    a             REAL DEFAULT 0,
    b             REAL DEFAULT 0,
    c             REAL DEFAULT 0,
    alpha         REAL DEFAULT 90,
    beta          REAL DEFAULT 90,
    gamma         REAL DEFAULT 90,
    volume        REAL DEFAULT 0,
    z_value       INTEGER DEFAULT 0,
    last_updated  INTEGER DEFAULT 0,
    parse_ok      INTEGER DEFAULT 1,
    cif_gz        BLOB
);
CREATE TABLE IF NOT EXISTS cod_atomic_sites (
    cod_id     INTEGER NOT NULL,
    site_idx   INTEGER NOT NULL,
    label      TEXT,
    element    TEXT NOT NULL,
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    z          REAL NOT NULL,
    occupancy  REAL DEFAULT 1.0,
    u_iso      REAL,
    PRIMARY KEY (cod_id, site_idx)
);
"""

POLY_INORG_SQL = """
CREATE TABLE IF NOT EXISTS phases (
    cod_id        INTEGER PRIMARY KEY,
    formula       TEXT,
    space_group   TEXT,
    cell_a        REAL,
    cell_b        REAL,
    cell_c        REAL,
    cell_alpha    REAL,
    cell_beta     REAL,
    cell_gamma    REAL,
    n_peaks       INTEGER,
    peaks_d       TEXT,
    peaks_i       TEXT,
    record_offset INTEGER,
    record_size   INTEGER,
    ref_id        TEXT,
    display_id    TEXT,
    peaks_top_d   BLOB,
    peaks_top_i   BLOB,
    cif_gz        BLOB
);
CREATE TABLE IF NOT EXISTS cod_atomic_sites (
    cod_id     INTEGER NOT NULL,
    site_idx   INTEGER NOT NULL,
    label      TEXT,
    element    TEXT NOT NULL,
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    z          REAL NOT NULL,
    occupancy  REAL DEFAULT 1.0,
    PRIMARY KEY (cod_id, site_idx)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

XIN_IDX = """
CREATE INDEX IF NOT EXISTS idx_elements_element_entry ON elements(element, entry_id);
CREATE INDEX IF NOT EXISTS idx_peaks_d ON peaks(d);
CREATE INDEX IF NOT EXISTS idx_peaks_entry_id ON peaks(entry_id);
CREATE INDEX IF NOT EXISTS idx_entries_formula ON entries(formula);
CREATE INDEX IF NOT EXISTS idx_entries_space_group ON entries(space_group);
CREATE INDEX IF NOT EXISTS idx_entries_crystal_system ON entries(crystal_system);
CREATE INDEX IF NOT EXISTS idx_entries_year ON entries(year);
CREATE INDEX IF NOT EXISTS idx_entries_mineral_name ON entries(mineral_name);
CREATE INDEX IF NOT EXISTS idx_entries_author ON entries(author);
CREATE INDEX IF NOT EXISTS idx_entries_journal ON entries(journal);
"""
FULL_IDX = """
CREATE INDEX IF NOT EXISTS idx_formula_red ON cod_entries(formula_red);
CREATE INDEX IF NOT EXISTS idx_elements ON cod_entries(elements);
CREATE INDEX IF NOT EXISTS idx_sg_number ON cod_entries(space_group_number);
CREATE INDEX IF NOT EXISTS idx_sg_name ON cod_entries(space_group);
CREATE INDEX IF NOT EXISTS idx_volume ON cod_entries(volume);
CREATE INDEX IF NOT EXISTS idx_parse_ok ON cod_entries(parse_ok);
CREATE INDEX IF NOT EXISTS idx_name_fts ON cod_entries(mineral_name);
CREATE INDEX IF NOT EXISTS idx_cif_file ON cod_entries(file);
"""
# 注：idx_sites_cod_id(cod_id) 与主键 (cod_id, site_idx) 是同前缀冗余索引，
# 2026-10-19 起不再创建（三库合计省约 2.2 GB），cod_id 查询直接走主键。
INORG_IDX = """
CREATE INDEX IF NOT EXISTS idx_phases_formula ON phases(formula);
CREATE INDEX IF NOT EXISTS idx_phases_sg ON phases(space_group);
CREATE INDEX IF NOT EXISTS idx_phases_display_id ON phases(display_id);
CREATE INDEX IF NOT EXISTS idx_phases_match_ref ON phases(ref_id);
"""


def clean_text(s, limit=250):
    """'?' / '.' / 空串 一律当 NULL（CIF 的未知值占位符不能进库）。"""
    if not s:
        return None
    s = str(s).strip().strip('"').strip("'").strip()
    if s in ("?", ".", "", "n/a", "N/A"):
        return None
    return s[:limit]


def entry_id_of(cod_id: int) -> str:
    """与 XinMatch ``_entry_id_for_cod`` 逐字同式。"""
    s = str(int(cod_id)).zfill(7)
    return "96-%s-%s" % (s[:3], s[3:])


def combo_hash(elements_csv: str) -> str:
    return hashlib.sha1(",".join(sorted(elements_csv.split(","))).encode()).hexdigest()[:16]


def _shard_stats(path: str):
    """探测分片库：返回 None 表示不可用（未做过/损坏，需重跑）。"""
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path.replace(os.sep, "/"), uri=True,
                              timeout=5)
        n = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        done = con.execute("SELECT value FROM meta WHERE key='shard_done'").fetchone()
        con.close()
        return (n, 1 if done else 0)
    except sqlite3.Error:
        return None


def worker(args):
    shard_id, units, resume, limit_per_unit = args
    fdb = os.path.join(PARTS, "p%03d_full.sqlite" % shard_id)
    idb = os.path.join(PARTS, "p%03d_inorg.sqlite" % shard_id)

    if not resume:
        for p in (fdb, idb):
            if os.path.exists(p):
                os.remove(p)

    done = set()
    if resume:
        for p in (fdb, idb):
            st = _shard_stats(p)
            if st and st[1]:
                pass
        # 以两个库中已记录的目录单元为准
        for p in (fdb, idb):
            if not os.path.exists(p):
                continue
            try:
                con = sqlite3.connect("file:%s?mode=ro" % p.replace(os.sep, "/"),
                                      uri=True, timeout=5)
                for (u,) in con.execute("SELECT unit FROM units_done"):
                    done.add(u)
                con.close()
            except sqlite3.Error:
                pass

    # 分片是**中间产物**，追求写入速度：journal_mode=OFF + synchronous=OFF。
    # 注意：这只用于分片；合并出去成品库必须用 WAL（2026-10-19 的成品损坏就是
    # 合并阶段用 OFF 且收尾无门禁造成的）。
    cf = sqlite3.connect(fdb, timeout=300.0)
    ci = sqlite3.connect(idb, timeout=300.0)
    for con, sql in ((cf, XINMATCH_SQL + POLY_FULL_SQL), (ci, XINMATCH_SQL + POLY_INORG_SQL)):
        con.executescript(sql)
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA busy_timeout=300000")
        con.execute("PRAGMA cache_size=-65536")     # 64 MB
        con.execute("PRAGMA temp_store=MEMORY")
        try:
            con.execute("CREATE TABLE IF NOT EXISTS units_done (unit TEXT PRIMARY KEY)")
        except sqlite3.Error:
            pass

    n_file = n_inorg = n_peak_ok = n_peak_fail = n_parse_fail = 0
    ent_rows, pk_rows, el_rows = [], [], []          # XinMatch（两侧共用形态）
    pent_rows = []                                    # PolyXRD cod_entries
    site_rows = []                                    # 原子位点（full：含 u_iso）
    ph_rows = []                                      # PolyXRD phases
    isite_rows = []                                   # 原子位点（inorg：无 u_iso）
    f_ent, i_ent, f_pk, i_pk, f_el, i_el = [], [], [], [], [], []
    first_peak_err = None
    t0 = time.time()

    def flush():
        # XinMatch 侧
        if f_ent:
            cf.executemany("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", f_ent)
            f_ent.clear()
        if f_pk:
            cf.executemany("INSERT INTO peaks VALUES (?,?,?,?,?,?)", f_pk)
            f_pk.clear()
        if f_el:
            cf.executemany("INSERT OR REPLACE INTO elements VALUES (?,?)", f_el)
            f_el.clear()
        if i_ent:
            ci.executemany("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", i_ent)
            i_ent.clear()
        if i_pk:
            ci.executemany("INSERT INTO peaks VALUES (?,?,?,?,?,?)", i_pk)
            i_pk.clear()
        if i_el:
            ci.executemany("INSERT OR REPLACE INTO elements VALUES (?,?)", i_el)
            i_el.clear()
        # PolyXRD 侧
        if pent_rows:
            cf.executemany(
                "INSERT OR REPLACE INTO cod_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                pent_rows)
            pent_rows.clear()
        if site_rows:
            cf.executemany("INSERT OR REPLACE INTO cod_atomic_sites VALUES (?,?,?,?,?,?,?,?,?)", site_rows)
            site_rows.clear()
        if ph_rows:
            ci.executemany(
                "INSERT OR REPLACE INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ph_rows)
            ph_rows.clear()
        if isite_rows:
            ci.executemany("INSERT OR REPLACE INTO cod_atomic_sites VALUES (?,?,?,?,?,?,?,?)", isite_rows)
            isite_rows.clear()

    for lib, rel_dir, abs_dir, off in units:
        key = "%s/%s" % (lib, rel_dir)
        if key in done:
            continue
        try:
            names = sorted(x for x in os.listdir(abs_dir) if x.lower().endswith(".cif"))
        except OSError:
            names = []
        if limit_per_unit:
            names = names[:limit_per_unit]
        for nm in names:
            src = os.path.join(abs_dir, nm)
            try:
                st = os.stat(src)
                if st.st_size == 0:
                    continue
                with open(src, "rb") as fh:
                    raw = fh.read()
                text = raw.decode("utf-8", "replace")
            except (OSError, UnicodeDecodeError):
                continue
            n_file += 1
            try:
                d = parse_cif(text)
            except Exception:
                n_parse_fail += 1
                continue
            parse_ok = int(bool(d.ok and d.a and d.b and d.c))
            if not parse_ok:
                n_parse_fail += 1
            elements, formula_red, counts = B.parse_elements(d.formula)
            inorg = B.is_inorganic(counts)
            m = _RE_DIGIT.search(nm)
            if m:
                cod_id = int(m.group(1)) + off
            else:
                cod_id = 800_000_000 + shard_id * 1_000_000 + n_file
            eid = entry_id_of(cod_id)
            vol = d.volume or B.cell_volume(d.a, d.b, d.c, d.alpha, d.beta, d.gamma)
            rel = "%s/%s/%s" % (lib, rel_dir, nm) if rel_dir else "%s/%s" % (lib, nm)

            # ---- XinMatch entries（Full 与 Inorg 各一份）----
            rho = density_of(counts, getattr(d, "z", 0), vol)
            row_e = (eid, clean_text(d.formula),
                     clean_text(d.name),
                     d.sg_name, d.crystal_system,
                     d.a, d.b, d.c, d.alpha, d.beta, d.gamma, vol,
                     rho, None, d.year, d.author, d.journal, None, elements or None)
            f_ent.append(row_e)
            for el in (elements.split(",") if elements else []):
                f_el.append((eid, el))
            if inorg:
                n_inorg += 1
                i_ent.append(row_e)
                for el in (elements.split(",") if elements else []):
                    i_el.append((eid, el))

            # ---- PolyXRD cod_entries（Full）----
            pent_rows.append((
                cod_id, rel, clean_text(d.name),
                clean_text(d.formula), formula_red or None,
                elements or None, d.sg_name, int(d.sg_number or 0),
                d.a, d.b, d.c, d.alpha, d.beta, d.gamma, vol,
                int(d.z or 0) if getattr(d, "z", None) else 0,
                int(st.st_mtime), parse_ok, None))

            # ---- 原子位点 ----
            for idx, s in enumerate(d.sites):
                try:
                    label, el, x, y, z, occ, u = s
                except ValueError:
                    continue
                o = occ if occ else 1.0
                site_rows.append((cod_id, idx, label, el, x, y, z, o, u))
                if inorg:
                    isite_rows.append((cod_id, idx, label, el, x, y, z, o))

            # ---- 峰表 ----
            dd = ii = hkl = None
            if (inorg or True) and vol and vol <= MAX_CELL_VOL_FOR_PEAKS and d.sites:
                try:
                    coords, sp_list, _ = expand_sites(d.sites, d.symops)
                    if 0 < len(sp_list) <= MAX_SITES_FOR_PEAKS:
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
                except Exception as e:
                    dd = None
                    if first_peak_err is None:
                        first_peak_err = "%s: %s" % (type(e).__name__, e)
            if dd is None or len(dd) == 0:
                n_peak_fail += 1
            else:
                n_peak_ok += 1
                d_arr = np.asarray(dd, dtype=np.float64)
                i_arr = np.asarray(ii, dtype=np.float64)
                h_arr = np.asarray(hkl, dtype=np.int64)
                # XinMatch：强度前 TOP_XIN 行 + hkl（两侧同数据）
                order = np.argsort(-i_arr, kind="stable")[:TOP_XIN]
                pk = [(eid, float(d_arr[j]), float(i_arr[j]),
                       int(h_arr[j][0]), int(h_arr[j][1]), int(h_arr[j][2]))
                      for j in order]
                f_pk.extend(pk)
                if inorg:
                    i_pk.extend(pk)
                    # PolyXRD phases：全量 CSV（d 降序，即 2θ 升序）+ top-64 BLOB
                    td, ti = FX.top_peaks_of(d_arr, i_arr, TOP_BLOB)
                    ph_rows.append((
                        cod_id, clean_text(d.formula), d.sg_name,
                        d.a, d.b, d.c, d.alpha, d.beta, d.gamma,
                        int(len(d_arr)),
                        ",".join("%.4f" % v for v in d_arr),
                        ",".join("%.2f" % v for v in i_arr),
                        None, None, eid, eid,
                        sqlite3.Binary(np.asarray(td, dtype="<f8").tobytes()),
                        sqlite3.Binary(np.asarray(ti, dtype="<f8").tobytes()),
                        None))

            if len(f_ent) >= 500 or len(f_pk) >= 20000 or len(site_rows) >= 10000:
                flush()
                cf.commit()
                ci.commit()

        flush()
        for con in (cf, ci):
            con.execute("INSERT OR REPLACE INTO units_done VALUES (?)", (key,))
            con.commit()

    flush()
    cf.commit(); ci.commit()
    for con, tbl in ((cf, "cod_entries"), (ci, "phases")):
        con.execute("INSERT OR REPLACE INTO meta VALUES ('shard_done','1')")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('files',?)", (str(n_file),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('inorg',?)", (str(n_inorg),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('peak_ok',?)", (str(n_peak_ok),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('peak_fail',?)", (str(n_peak_fail),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('parse_fail',?)", (str(n_parse_fail),))
        con.commit()
    cf.close(); ci.close()
    return (shard_id, n_file, n_inorg, n_peak_ok, n_peak_fail, n_parse_fail,
            round(time.time() - t0, 1), first_peak_err)


# 合并时分表写出**显式列名**：分片 DDL 一旦与主 DDL 存在列顺序差异，
# `INSERT ... SELECT *` 会静默错位（2026-10-19 Inorg 库的 93 行“formula 里存数字”
# 就是这么来的）。任何新增列都必须同时出现在这里。
MERGE_COLUMNS_FULL_SITES = "cod_id, site_idx, label, element, x, y, z, occupancy, u_iso"
MERGE_COLUMNS_INORG_SITES = "cod_id, site_idx, label, element, x, y, z, occupancy"
MERGE_COLUMNS = {
    "entries": ("entry_id, formula, mineral_name, space_group, crystal_system, "
                "a, b, c, alpha, beta, gamma, volume, density, color, year, author, "
                "journal, quality, elements"),
    "peaks": "entry_id, d, intensity, h, k, l",
    "elements": "entry_id, element",
    "cod_entries": ("cod_id, file, mineral_name, formula, formula_red, elements, "
                    "space_group, space_group_number, a, b, c, alpha, beta, gamma, "
                    "volume, z_value, last_updated, parse_ok, cif_gz"),
    "phases": ("cod_id, formula, space_group, cell_a, cell_b, cell_c, cell_alpha, "
               "cell_beta, cell_gamma, n_peaks, peaks_d, peaks_i, record_offset, "
               "record_size, ref_id, display_id, peaks_top_d, peaks_top_i, cif_gz"),
    "cod_atomic_sites": MERGE_COLUMNS_FULL_SITES,
}


def merge(target: str, pattern: str, schema_sql: str, indexes: str, kind: str,
          drop: bool = False, vacuum: bool = True):
    """把分片合并成最终库，建索引 → ANALYZE → DELETE 模式 → VACUUM。"""
    parts = sorted(glob.glob(pattern))
    if os.path.exists(target):
        os.remove(target)
    con = sqlite3.connect(target, timeout=300.0)
    con.executescript(schema_sql)
    # WAL + NORMAL：崩溃安全（DELETE 模式下大事务中断最容易留下半提交 b-tree），
    # 速度接近 OFF。交付前统一转回 DELETE。
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-262144")     # 256 MB
    con.execute("PRAGMA temp_store=FILE")
    # 两个产物都带 XinMatch 侧表，element_combo 恒需构建
    con.create_function("combo_hash", 1, combo_hash)
    t0 = time.time()
    for p in parts:
        try:
            con.execute("ATTACH DATABASE ? AS src", (p,))
        except sqlite3.Error as e:
            raise SystemExit("!! 分片无法挂载 %s: %s" % (p,))
        for tbl in ("entries", "peaks", "elements", "cod_entries", "phases",
                    "cod_atomic_sites"):
            try:
                con.execute("SELECT COUNT(*) FROM src.%s" % tbl).fetchone()
            except sqlite3.Error:
                continue
            cols = MERGE_COLUMNS[tbl]
            if tbl == "cod_atomic_sites":
                cols = (MERGE_COLUMNS_FULL_SITES if kind == "full"
                        else MERGE_COLUMNS_INORG_SITES)
            try:
                con.execute("INSERT OR REPLACE INTO main.%s (%s) "
                            "SELECT %s FROM src.%s" % (tbl, cols, cols, tbl))
            except sqlite3.Error as e:
                raise SystemExit("!! %s 合并失败（%s）: %s"
                                 % (tbl, os.path.basename(p), e))
        con.commit()
        con.execute("DETACH DATABASE src")
    print("  合并 %d 个分片用时 %.1f min" % (len(parts), (time.time() - t0) / 60.0))

    n_combo = con.execute(
        "INSERT OR REPLACE INTO element_combo "
        "SELECT combo_hash(elements), group_concat(entry_id, char(10)) "
        "FROM entries WHERE elements IS NOT NULL AND elements != '' "
        "GROUP BY combo_hash(elements)").rowcount
    con.commit()
    print("  element_combo 组数: %d" % n_combo)

    t0 = time.time()
    con.executescript(indexes)
    print("  建索引 %.1f min" % ((time.time() - t0) / 60.0))
    t0 = time.time()
    con.execute("ANALYZE")
    print("  ANALYZE %.1f min" % ((time.time() - t0) / 60.0))

    n = con.execute("SELECT COUNT(*) FROM %s" %
                    ("cod_entries" if kind == "full" else "phases")).fetchone()[0]
    n_sites = con.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
    n_ent = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_pk = con.execute("SELECT COUNT(*) FROM peaks").fetchone()[0]

    # ---- 交付前门禁 1：PolyXRD 的 top-64 快路径不判 NULL，NULL 会让它 AttributeError ----
    if kind == "inorg":
        n_null = con.execute("SELECT COUNT(*) FROM phases WHERE peaks_top_d IS NULL").fetchone()[0]
        if n_null:
            raise SystemExit("!! phases.peaks_top_d 有 %d 行为 NULL —— PolyXRD 默认检索会崩溃，"
                             "拒绝交付。" % n_null)
        n_bad = con.execute("SELECT COUNT(*) FROM phases WHERE n_peaks IS NULL OR n_peaks <= 0").fetchone()[0]
        if n_bad:
            raise SystemExit("!! phases.n_peaks 有 %d 行为空/0，拒绝交付。" % n_bad)
        if n_ent != con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]:
            raise SystemExit("!! entries 与 phases 不一致")

    # ---- 每次交付都记录数据快照，便于日后追溯（上一版 tar_source 指着已消失的 E 盘）----
    snap = {}
    for lib in ("COD", "PCOD", "TCOD"):
        try:
            snap[lib] = str(sum(1 for _ in glob.iglob(
                os.path.join(BASE, lib, "**", "*.cif"), recursive=True)))
        except Exception:
            snap[lib] = "?"
    meta = {
        "schema_version": "1" if kind == "full" else "2",
        "entry_count": str(n),
        "build_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_build_time": str(int(time.time())),
        "cif_source": "rsync://www.crystallography.net/{cif,pcod-cif} + "
                      "http://www.crystallography.net/tcod/cif",
        "source_root": "D:/Project/XRD/PolyXRD-DataBase/{COD,PCOD,TCOD}",
        "source_snapshot": "COD=%s;PCOD=%s;TCOD=%s" % (snap["COD"], snap["PCOD"], snap["TCOD"]),
        "cif_embedded": "0",
        "cif_missing": str(n),
        "atomic_sites_rows": str(n_sites),
        "variant": "slim-index-3cod-%s" % kind,
        "xinmatch_entries": str(n_ent),
        "xinmatch_peaks_rows": str(n_pk),
        "peak_convention": "lambda=1.5406 CuKa1; d>=1.0A; I_norm=1000; "
                           "equivalent reflections merged by 2theta; "
                           "phases CSV top-%d by intensity, top-64 BLOB" % TOP_POLY,
        "libraries": "COD+PCOD+TCOD",
        "id_offset": "COD=0;PCOD=+20000000;TCOD=+100000000",
        "license": "COD: CC-BY / public scientific data (crystallography.net); "
                   "PCOD: public domain; TCOD: public domain",
        "builder": "build_3cod.py v2 (2026-10-19)",
        "parsed_with": "fastcif.py (quoted formula stripped; crystal_system/density/"
                       "year/author/journal backfilled)",
    }
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", list(meta.items()))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()
    if vacuum:
        t0 = time.time()
        con = sqlite3.connect(target)
        con.execute("VACUUM")
        con.close()
        print("  VACUUM %.1f min" % ((time.time() - t0) / 60.0))
    else:
        print("  VACUUM 跳过（--no-vacuum）")
    # ---- 交付前门禁 2：完整性（上一版 Full/Inorg 都是坏的，就是缺这一步）----
    t0 = time.time()
    con = sqlite3.connect("file:%s?mode=ro" % target.replace(os.sep, "/"), uri=True)
    res = con.execute("PRAGMA integrity_check").fetchall()
    print("  integrity_check: %s (%.1f min)"
          % (res[0][0] if len(res) == 1 else "**FAILED** %d 条" % len(res),
             (time.time() - t0) / 60.0))
    print("  journal_mode: %s" % con.execute("PRAGMA journal_mode").fetchone()[0])
    con.close()
    if len(res) != 1 or res[0][0] != "ok":
        raise SystemExit("!! 完整性检查未通过，产物 %s 不合格：\n  %s"
                         % (os.path.basename(target), "\n  ".join(r[0] for r in res[:10])))
    if drop:
        for p in parts:
            try:
                os.remove(p)
            except OSError:
                pass
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4,
                    help="本机只有 4 核，默认 4（超订会因内存/寻道反而变慢）")
    ap.add_argument("--shards", type=int, default=24)
    ap.add_argument("--limit-per-unit", type=int, default=0)
    ap.add_argument("--max-units", type=int, default=0,
                    help="只取前 N 个目录单元（冒烟测试用）")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--finalize-only", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--db-copy", action="store_true",
                    help="额外生成 .db 副本（默认不生成，只交付 .sqlite）")
    ap.add_argument("--merge-kind", default="both", choices=["full", "inorg", "both"],
                    help="只合并指定产物（先出 Inorg 再出 Full）")
    ap.add_argument("--no-vacuum", action="store_true",
                    help="跳过 VACUUM（25GB 库在机械盘上很慢）")
    ap.add_argument("--stamp", default=STAMP, help="产物名日期戳（冒烟测试用）")
    args = ap.parse_args()
    global FULL_DB, INORG_DB
    FULL_DB = os.path.join(BASE, "3COD-Full-%s.sqlite" % args.stamp)
    INORG_DB = os.path.join(BASE, "3COD-Inorg-%s.sqlite" % args.stamp)

    os.makedirs(PARTS, exist_ok=True)

    # 目录单元 → 分片
    units = []
    for lib, root, depth, off in LIBS:
        for rel, abs_dir in B.list_dirs(root, depth):
            units.append((lib, rel, abs_dir, off))
    if args.max_units:
        units = units[:args.max_units]
    if args.plan:
        print("目录单元: %d 个；分片数 %d → 每片约 %d 个单元"
              % (len(units), args.shards, len(units) // args.shards))
        return

    if not args.merge_only and not args.finalize_only:
        groups = [units[i::args.shards] for i in range(args.shards)]
        print("单元 %d 个 → %d 分片, %d 进程并行" % (len(units), args.shards, args.workers))
        seen_err = None
        t0 = time.time()
        tot = [0, 0, 0, 0]
        with Pool(args.workers) as pool:
            for (sid, nf, ni, npok, npf, nparse, secs, ferr) in pool.imap_unordered(
                    worker, [(i, g, args.resume, args.limit_per_unit)
                             for i, g in enumerate(groups)]):
                tot[0] += nf; tot[1] += ni; tot[2] += npok; tot[3] += npf
                if ferr and not seen_err:
                    seen_err = ferr
                done = sum(1 for _ in glob.glob(os.path.join(PARTS, "p*_full.sqlite")))
                print("[%d/%d] 分片 p%03d: 文件 %d, 无机 %d, 峰成功 %d, 峰失败 %d, "
                      "解析失败 %d, %d s%s"
                      % (done, args.shards, sid, nf, ni, npok, npf, nparse, secs,
                         ("  ⚠ 首个峰异常: " + ferr) if ferr else ""),
                      flush=True)
        print("分片构建总耗时 %.1f h；合计 文件 %d, 无机 %d, 峰成功 %d, 峰失败 %d"
              % ((time.time() - t0) / 3600.0, tot[0], tot[1], tot[2], tot[3]))

        # ---- 防线：峰失败率过高说明口径/资源出了系统性问题，绝不能让空峰库流出去 ----
        # 教训：_atomic_scattering_params.json 缺失时 _load_params() 对每个文件都抛
        # RuntimeError，被 worker 的 except Exception 吞掉 → 100% 峰失败但流程"正常"跑完。
        # 注意必须放在本分支内：--merge-only 不会给 tot 赋值。
        if tot[0] and tot[3] / tot[0] > 0.20:
            import fastxrd as _FX
            raise SystemExit(
                "!! 峰失败率 %.1f%%（峰成功 %d / 峰失败 %d），超过 20%% 阈值，已中止合并。\n"
                "   最常见原因：原子散射因子参数表缺失 —— 应位于\n"
                "   %s\n"
                "   （取自 pymatgen analysis/diffraction/data/atomic_scattering_params.json，\n"
                "    本机副本见 E:/TEMP/PolyXRD/dist/PolyXRD/_internal/pymatgen/...）。\n"
                "   分片保留在 %s，修复后加 --resume 续跑。"
                % (100.0 * tot[3] / tot[0], tot[2], tot[3], _FX._PARAMS_PATH, PARTS))

    kind = args.merge_kind
    if not args.finalize_only:
        # Inorg 先合并先交付（peaks 行数约为 Full 的 2/3，索引与 VACUUM 更快）
        if kind in ("inorg", "both"):
            print("=== 合并 3COD-Inorg ===")
            merge(INORG_DB, os.path.join(PARTS, "p*_inorg.sqlite"),
                  XINMATCH_SQL + POLY_INORG_SQL, XIN_IDX + INORG_IDX, "inorg",
                  vacuum=not args.no_vacuum)
        if kind in ("full", "both"):
            print("=== 合并 3COD-Full ===")
            merge(FULL_DB, os.path.join(PARTS, "p*_full.sqlite"),
                  XINMATCH_SQL + POLY_FULL_SQL, XIN_IDX + FULL_IDX, "full",
                  vacuum=not args.no_vacuum)

    # 单一格式交付（2026-10-18 用户决定）：只保留 .sqlite，XinMatch 侧将直接支持
    # 该扩展名。历史双格式（.sqlite + .db 各一份，内容字节级相同）已废弃，
    # 如需兼容旧挂载流程可用 --db-copy 显式生成 .db 副本。
    if args.db_copy:
        srcs = []
        if kind in ("inorg", "both"):
            srcs.append(INORG_DB)
        if kind in ("full", "both"):
            srcs.append(FULL_DB)
        for src in srcs:
            if not os.path.exists(src):
                continue
            dst = src[:-7] + ".db"
            if os.path.exists(dst):
                os.remove(dst)
            shutil.copyfile(src, dst)
            print("副本: %s (%.2f GB)" % (os.path.basename(dst),
                                          os.path.getsize(dst) / 1e9))


if __name__ == "__main__":
    main()
