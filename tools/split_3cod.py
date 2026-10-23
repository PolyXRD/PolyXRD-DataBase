"""Split the 3COD slim-index database into three by source (COD / PCOD / TCOD).

Why
---
PolyXRD keeps exactly **one** database per slot (``cod_db_path``,
``pdf2_db_path``, ``cod_index_db_path``, ``xinmatch_db_path``), and
``mount_databases()`` keeps only the first file of each kind.  A single
1.19 M-entry library is therefore both (a) unusable interactively and
(b) the only library PolyXRD can mount in that slot.

Splitting by provenance gives each consumer what it actually needs:

===============  ==================================  ==========================
output           tables                              consumer / PolyXRD slot
===============  ==================================  ==========================
COD              entries, peaks, elements,           PolyXRD ``cod_inorganics``
                 element_combo, phases,              (phas) + XinMatch native
                 cod_atomic_sites
PCOD             entries, peaks, elements,           XinMatch native / PolyXRD
                 element_combo                       ``xinmatch`` (optional)
TCOD             same as PCOD                        same as PCOD
===============  ==================================  ==========================

Dropping ``phases`` from PCOD/TCOD is deliberate: it keeps them out of the
``cod_inorganics`` slot (so PolyXRD still mounts the experimental COD library
there) while leaving them mountable through the XinMatch-compatible slot.

Rows are **copied** from an existing 3COD build rather than re-derived from
CIF, so peak data stays byte-identical to what was already validated.

Usage
-----
    python tools/split_3cod.py                       # all three, default source
    python tools/split_3cod.py --only cod            # just the PolyXRD library
    python tools/split_3cod.py --no-vacuum --out-dir D:\\tmp\\split
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
STAMP = "20261020"
DEFAULT_SOURCE = BASE / f"3COD-Inorg-{STAMP}.sqlite"

# entry_id is "96-XXX-XXXX..."; the numeric tail is the cod_id, and the builder
# offset PCOD by +2e7 and TCOD by +1e8 so that ids stay globally unique.
PARTS = {
    "cod": ("COD", 0, 20_000_000),
    "pcod": ("PCOD", 20_000_000, 100_000_000),
    "tcod": ("TCOD", 100_000_000, None),
}

ENTRY_COLS = (
    "entry_id, formula, mineral_name, space_group, crystal_system, a, b, c, "
    "alpha, beta, gamma, volume, density, color, year, author, journal, "
    "quality, elements"
)
PEAK_COLS = "entry_id, d, intensity, h, k, l"
PHASE_COLS = (
    "cod_id, formula, space_group, cell_a, cell_b, cell_c, cell_alpha, "
    "cell_beta, cell_gamma, n_peaks, peaks_d, peaks_i, record_offset, "
    "record_size, ref_id, display_id, peaks_top_d, peaks_top_i, cif_gz"
)
SITE_COLS = "cod_id, site_idx, label, element, x, y, z, occupancy"

SCHEMA_COMMON = """
CREATE TABLE entries (
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
CREATE TABLE peaks (
    entry_id  TEXT NOT NULL,
    d         REAL NOT NULL,
    intensity REAL,
    h         INTEGER,
    k         INTEGER,
    l         INTEGER
);
CREATE TABLE elements (
    entry_id TEXT NOT NULL,
    element  TEXT NOT NULL,
    PRIMARY KEY (entry_id, element)
);
CREATE TABLE element_combo (
    element_set_hash TEXT PRIMARY KEY,
    entry_ids        TEXT NOT NULL
);
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Matches the layout PolyXRD's `cod_inorganics` reader expects (and the one
# 3COD already ships, so the top-64 fast path keeps working unchanged).
SCHEMA_PHASES = """
CREATE TABLE phases (
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
CREATE TABLE cod_atomic_sites (
    cod_id    INTEGER NOT NULL,
    site_idx  INTEGER NOT NULL,
    label     TEXT,
    element   TEXT NOT NULL,
    x         REAL NOT NULL,
    y         REAL NOT NULL,
    z         REAL NOT NULL,
    occupancy REAL DEFAULT 1.0,
    PRIMARY KEY (cod_id, site_idx)
);
"""

# idx_peaks_d is intentionally absent: idx_peaks_d_entry already covers its
# leftmost column.  idx_peaks_entry_id is absent too - (entry_id, intensity)
# serves both the per-entry fetch and the top-K scan.
INDEXES_COMMON = """
CREATE INDEX idx_peaks_d_entry        ON peaks(d, entry_id);
CREATE INDEX idx_peaks_entry_intensity ON peaks(entry_id, intensity DESC);
CREATE INDEX idx_elements_element_entry ON elements(element, entry_id);
CREATE INDEX idx_entries_formula      ON entries(formula);
CREATE INDEX idx_entries_space_group  ON entries(space_group);
CREATE INDEX idx_entries_crystal_system ON entries(crystal_system);
CREATE INDEX idx_entries_year         ON entries(year);
CREATE INDEX idx_entries_mineral_name ON entries(mineral_name);
"""
INDEXES_PHASES = """
CREATE INDEX idx_phases_formula   ON phases(formula);
CREATE INDEX idx_phases_sg        ON phases(space_group);
CREATE INDEX idx_phases_ref       ON phases(ref_id);
CREATE INDEX idx_phases_display   ON phases(display_id);
"""


def combo_hash(elements_csv: str | None) -> str:
    import hashlib

    parts = sorted(p for p in (elements_csv or "").split(",") if p)
    return hashlib.sha1(",".join(parts).encode()).hexdigest()[:16]


def id_predicate(lo: int, hi: int | None) -> tuple[str, tuple]:
    expr = "CAST(replace(substr(entry_id, 4), '-', '') AS INTEGER)"
    if hi is None:
        return f"{expr} >= ?", (lo,)
    return f"{expr} >= ? AND {expr} < ?", (lo, hi)


def copy_part(source: Path, out: Path, name: str, lo: int, hi: int | None,
              *, with_phases: bool, batch: int = 5000, vacuum: bool = True) -> int:
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out, timeout=300.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-262144")
    con.executescript(SCHEMA_COMMON)
    if with_phases:
        con.executescript(SCHEMA_PHASES)
    con.create_function("combo_hash", 1, combo_hash)
    # Plain path, not a file: URI - ATTACH only honours URIs when the connection
    # itself was opened with uri=True.  The source is only ever read here.
    con.execute("ATTACH DATABASE ? AS src", (str(source),))

    pred, params = id_predicate(lo, hi)
    t0 = time.time()
    con.execute("CREATE TEMP TABLE sel (entry_id TEXT PRIMARY KEY)")
    con.execute(f"INSERT INTO temp.sel SELECT entry_id FROM src.entries WHERE {pred}", params)
    con.commit()
    ids = [r[0] for r in con.execute("SELECT entry_id FROM temp.sel")]
    print(f"  [{name}] selected {len(ids):,} entries  ({time.time() - t0:.1f} s)", flush=True)

    t0 = time.time()
    con.execute(f"INSERT INTO main.entries ({ENTRY_COLS}) "
                f"SELECT {ENTRY_COLS} FROM src.entries WHERE {pred}", params)
    con.commit()
    print(f"  [{name}] entries   {time.time() - t0:.1f} s", flush=True)

    for label, sql in (
        ("peaks", f"INSERT INTO main.peaks ({PEAK_COLS}) SELECT {PEAK_COLS} "
                  f"FROM src.peaks WHERE entry_id IN (%s)"),
        ("elements", "INSERT INTO main.elements (entry_id, element) "
                     "SELECT entry_id, element FROM src.elements "
                     "WHERE entry_id IN (%s)"),
    ):
        t0 = time.time()
        done = 0
        for i in range(0, len(ids), batch):
            chunk = ids[i:i + batch]
            con.execute(sql % ",".join("?" * len(chunk)), chunk)
            done += len(chunk)
            if done % (batch * 20) == 0:
                print(f"  [{name}] {label} {done:,}/{len(ids):,} "
                      f"({time.time() - t0:.0f} s)", flush=True)
        con.commit()
        print(f"  [{name}] {label:<8s} {time.time() - t0:.1f} s", flush=True)

    t0 = time.time()
    con.execute(
        "INSERT INTO main.element_combo "
        "SELECT combo_hash(elements), group_concat(entry_id, char(10)) FROM entries "
        "WHERE elements IS NOT NULL AND elements != '' GROUP BY combo_hash(elements)"
    )
    con.commit()
    print(f"  [{name}] element_combo {time.time() - t0:.1f} s", flush=True)

    if with_phases:
        t0 = time.time()
        con.execute(f"INSERT INTO main.phases ({PHASE_COLS}) SELECT {PHASE_COLS} "
                    f"FROM src.phases WHERE cod_id >= ?"
                    + ("" if hi is None else " AND cod_id < ?"),
                    (lo,) if hi is None else (lo, hi))
        con.execute(f"INSERT INTO main.cod_atomic_sites ({SITE_COLS}) "
                    f"SELECT {SITE_COLS} FROM src.cod_atomic_sites WHERE cod_id >= ?"
                    + ("" if hi is None else " AND cod_id < ?"),
                    (lo,) if hi is None else (lo, hi))
        con.commit()
        n_ph = con.execute("SELECT COUNT(*) FROM main.phases").fetchone()[0]
        print(f"  [{name}] phases {n_ph:,} + atomic sites  "
              f"({time.time() - t0:.1f} s)", flush=True)

    t0 = time.time()
    con.executescript(INDEXES_COMMON)
    if with_phases:
        con.executescript(INDEXES_PHASES)
    print(f"  [{name}] indexes {time.time() - t0:.1f} s", flush=True)

    t0 = time.time()
    con.execute("ANALYZE")
    print(f"  [{name}] ANALYZE {time.time() - t0:.1f} s", flush=True)

    n_ent = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_pk = con.execute("SELECT COUNT(*) FROM peaks").fetchone()[0]
    meta = {
        "schema_version": "3",
        "variant": f"split-{name.lower()}-{STAMP}",
        "source_database": source.name,
        "source_stamp": STAMP,
        "taxonomy": "by provenance: COD=experimental, PCOD=predicted, TCOD=theoretical",
        "this_library": name,
        "entry_count": str(n_ent),
        "peaks_rows": str(n_pk),
        "xinmatch_entries": str(n_ent),
        "xinmatch_peaks_rows": str(n_pk),
        "has_phases": "1" if with_phases else "0",
        "peak_convention": "lambda=1.5406 CuKa1; d>=1.0A; I_norm=1000; "
                           "equivalent reflections merged by 2theta; top-100 by intensity",
        "cif_embedded": "0",
        "cif_source": "rsync://www.crystallography.net/{cif,pcod-cif} + "
                      "http://www.crystallography.net/tcod/cif",
        "license": "COD: CC-BY / public scientific data (crystallography.net); "
                   "PCOD: public domain; TCOD: public domain",
        "index_policy": "idx_peaks_d_entry covers d; idx_peaks_entry_intensity "
                        "replaces idx_peaks_entry_id; idx_peaks_d dropped",
        "build_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_build_time": str(int(time.time())),
    }
    if with_phases:
        meta["polyxrd_slot"] = "cod_inorganics"
    else:
        meta["polyxrd_slot"] = "xinmatch (optional; experimental COD belongs in cod_inorganics)"
    con.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    sorted(meta.items()))
    con.commit()
    con.execute("DETACH DATABASE src")

    if vacuum:
        t0 = time.time()
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("VACUUM")
        print(f"  [{name}] VACUUM {time.time() - t0:.1f} s", flush=True)
    con.close()
    return n_ent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out-dir", type=Path, default=BASE)
    ap.add_argument("--stamp", default=STAMP)
    ap.add_argument("--only", choices=("cod", "pcod", "tcod"), action="append",
                    help="build just this part (repeatable; default: all three)")
    ap.add_argument("--no-vacuum", action="store_true")
    args = ap.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source database not found: {args.source}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    wanted = args.only or ["cod", "pcod", "tcod"]

    print(f"source: {args.source.name} ({args.source.stat().st_size / 2**30:.2f} GiB)")
    for key in wanted:
        label, lo, hi = PARTS[key]
        out = args.out_dir / f"{label}-Inorg-{args.stamp}.sqlite"
        print(f"\n=== {label}  ->  {out.name}", flush=True)
        t0 = time.time()
        n = copy_part(args.source, out, label, lo, hi,
                      with_phases=(key == "cod"), vacuum=not args.no_vacuum)
        print(f"  [{label}] done: {n:,} entries, "
              f"{out.stat().st_size / 2**30:.2f} GiB, "
              f"{(time.time() - t0) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
