# PolyXRD-DataBase

**Build code, format specification and release artifacts for the PolyXRD external phase database (polyDB format).**

This repository contains **only code and documentation**; the database itself is distributed as compressed
packages in [Releases](../../releases) (48 MB / 710 MB per database, not committed to git history). The
data sources are [Crystallography Open Database (COD)](http://www.crystallography.net/cod/) and
[Materials Project](https://materialsproject.org) (CC BY 4.0); this repository does not resell or modify
the original CIFs, and only performs peak-position/intensity calculation and index packaging.

---

## 1. Release artifacts (Release `20261020` / `20261021` / `20261031`)

### 1.1 MP-20261031 (Materials Project external database)

| Database | Phase count | Peak count | Site count | Uncompressed | Release package | SHA-256 (zip) |
|---|---|---|---|---|---|---|
| **MP** | 155,204 | 12,705,201 | 2,407,784 | 187,675,763 B (179.0 MiB) | `MP-20261031.polyDB.zip` (106.5 MB) | `ccfccf53…a16c22` |

- Data source: [Materials Project](https://materialsproject.org) summary (2025-09-25, CC BY 4.0).
  210,579 records deduplicated by reduced formula, keeping the lowest `energy_above_hull` configuration
  per group, giving 155,204 phases.
- MP's CIFs are **P1 primitive cells** exported by pymatgen: the builder performs
  "primitive cell → conventional cell → asymmetric unit", and peaks are computed on the conventional
  cell, to avoid F/I/C-centered lattices splitting equivalent reflections into spurious peaks (see the
  docstring of `tools/build_mp_polydb.py` for details).
- `entries.eid` = MP number (`mp-3207172` → `3207172`); `mvc-*` entries fall in the 900-million
  number range; `tier=2` (DFT theoretical structures, not experimental PDF cards).
- Build / validation: `tools/build_mp_polydb.py`, `tools/verify_mp_polydb.py`;
  measured structure validation 32/32 PASS, L3 recomputation
  max|Δd|=8.1×10⁻⁷ Å / max|ΔI|=0.015 (100 phases).

### 1.2 COD-20261021 (COD inorganic / full database)

| Database | Phase count | Peak count | Site count | Uncompressed | Release package | SHA-256 (zip) |
|---|---|---|---|---|---|---|
| **COD-Inorg** | 77,500 | 5,962,013 | 1,005,846 | 89,926,214 B (85.8 MiB) | `COD-Inorg-20261021.polyDB.zip` (48.1 MB) | `d9e57d11…33cf14` |
| **COD-Full** | 521,361 | 50,328,800 | 36,315,927 | 1,107,655,264 B (1056.3 MiB) | `COD-Full-20261021.polyDB.zip` (710.3 MB) | `191246b7…1bbd6e` |

> Full checksum values are in the `SHA256SUMS.txt` attached to the Release (it gives the sha256 of
> both the zip and each uncompressed segment; the latter is also written into each database's own
> `meta.json`).

- `COD-Inorg` = COD entries judged inorganic (no C, or containing C but no H); `COD-Full` = the full
  COD. The two are mutually exclusive, **install just one**, and PolyXRD automatically recognizes
  `meta.variant` (`cod-inorg` / `cod-full`).
- The `20261021` in the name is the **build date**; the source data snapshot time is in
  `meta.json.source.manifest_built_at` (2026-10-20 01:52:04).
- After extraction you get a `.polyDB` **directory** of the same name that can be mounted directly
  (local disk / external drive / NAS all work); direct mmap inside the zip is **not supported**.

```bash
# Usage (put any directory at any path, then point PolyXRD at that .polyDB directory)
unzip COD-Inorg-20261021.polyDB.zip
python tools/verify_polydb.py COD-Inorg-20261021.polyDB
```

### 1.3 TCOD / PCOD-20261020 (TCOD inorganic / full database + PCOD inorganic)

| Database | Phase count | Peak count | Site count | Uncompressed | Release package | SHA-256 (zip) |
|---|---|---|---|---|---|---|
| **TCOD-Inorg** | 46,541 | 3,767,731 | 754,606 | 55,138,528 B (52.6 MiB) | `TCOD-Inorg-20261020.polyDB.zip` (31.5 MB) | `783bc4f6…cc4ead` |
| **TCOD-Full** | 359,307 | 35,039,291 | 22,178,424 | 714,704,055 B (681.6 MiB) | `TCOD-Full-20261020.polyDB.zip` (466.6 MB) | `81ae572f…56ab47` |
| **PCOD-Inorg** | 1,061,817 | 106,160,732 | 32,522,180 | 1,481,618,146 B (1413.0 MiB) | `PCOD-Inorg-20261020.polyDB.zip` (936.9 MB) | `898dc822…89310f` |

> Full checksum values are in the `SHA256SUMS.txt` attached to the Release; the sha256 of the 8
> segments inside each database is written in its own `meta.json.sections`.

- `TCOD-Inorg` / `TCOD-Full` = the inorganic subset / the full TCOD (theoretical calculated
  structures) (the extra part of Full is mainly C/H organic phases, about 320,000 phases each);
  `PCOD-Inorg` = the full PCOD — **PCOD has no `Full` variant**: the 1,061,962 `is_inorg`
  entries in the manifest are all 1 (the GRINSP prediction set itself contains no organic phases),
  so `pcod-full` would be byte-for-byte identical to `pcod-inorg`.
- `variant` is `tcod-inorg` / `tcod-full` / `pcod-inorg` respectively, all different, and they can
  coexist with the COD databases. PolyXRD v4.x built-in slots only register `cod-inorg` /
  `cod-full`; these three databases go through "Custom mount" in the mount panel.
- The `20261020` in the name is the **official database sync date** (not the build date; built on
  2026-10-31).
- All three databases passed triple acceptance (structure 32/32, 200-phase sampled recomputation
  max|Δd| ≤ 9.5×10⁻⁷ Å, PolyXRD reader mount + search); details in
  [polyDB TCOD/PCOD build report 2026-10-20 (Chinese)](docs/polyDB-TCOD-PCOD构建报告-20261020.md).

```bash
python tools/build_polydb.py --lib TCOD --scope inorg --stamp 20261020 --workers 4
python tools/build_polydb.py --lib TCOD --scope full  --stamp 20261020 --workers 4
python tools/build_polydb.py --lib PCOD --scope inorg --stamp 20261020 --workers 4
```

---

## 2. What polyDB is

A `.polyDB` is a **directory container** that splits "the peak table used for search + the bitmap
inverted index + the atomic sites used for refinement" into fixed-length array segments, read on
demand via mmap, so even 520,000 phases can be "ready to use on open, with second-level search".

```
COD-Inorg-20261021.polyDB/
├── meta.json        self-describing: version / peak convention / shape+bytes+sha256 of each segment
├── index.sqlite     entry metadata (formula/space group/cell/density/elements/CIF relative path) + FTS5
├── peaks_d.f32      (N×100) float32  peak position d, sorted by intensity descending within each row
├── peaks_i.u16      (N×100) uint16   intensity quantization (u16/65535*1000)
├── bins.u8          (501×⌈N/8⌉)       d-bin bitmap inverted index (0.05 Å/bin, indexes the strongest 40 per phase)
├── elem.u8          (118×⌈N/8⌉)       element bitmap (Z=1..118)
├── sites.bin        atomic-site stream (17 B/site: Z + xyz + occ)
└── sites_off.i64    (N+1) int64      offsets into sites.bin
```

**Peak convention** (hard-coded into `meta.json.peak_convention`, consistent with this repository's code):

| Item | Value |
|---|---|
| Wavelength λ | 1.5406 Å (Cu Kα1) |
| 2θ range | 5.0 – 100.76° (equivalent to `d ≥ 1.0 Å`) |
| Equivalent reflections | merged by 2θ (including multiplicity), consistent with `fastxrd` |
| Intensity normalization | strongest peak per phase = 1000 |
| Peak selection | **take the top K=100 by intensity descending** (not truncated by d) |
| Temperature factor | no Debye-Waller (= pymatgen default convention) |
| Arrays | all little-endian, big-endian not supported |

For the complete field-level specification see [polyDB v4 format specification (Chinese)](docs/外挂库格式规范-polyDB-v4.md);
for design trade-offs and measured data see [polyDB rebuild plan 2026-10-21 (Chinese)](docs/polyDB重建方案-20261021.md).

> ⚠️ **The iron rule for row numbers**: array-segment row numbers must come from the
> `index.sqlite.entries.row_idx` column, **must not** use `eid-1`.
> `eid` is an `INTEGER PRIMARY KEY` (= rowid); COD numbers start at 1,000,000,
> so the two are not equal (measured across the entire database: 0 rows where they match). When
> writing a third-party reader, this is the easiest place to get a wholesale misalignment.

---

## 3. Building from scratch

### 3.1 Environment

| Dependency | Requirement | Notes |
|---|---|---|
| Python | 3.10+ | tested on 3.10.11 |
| numpy | required | peak calculation and array-segment writing |
| pymatgen | optional | if installed, uses its built-in scattering-factor table to guarantee exact agreement with the official convention; otherwise reads `_atomic_scattering_params.json` |
| Disk | about 2× the database size | Full database build peaks at about 3 GB of temporary space (`_polydb_parts/`) |
| Memory | 8 GB class | during the merge phase `peaks_d` uses memmap and is not fully resident |

```bash
pip install numpy
# Optional: pip install pymatgen
```

### 3.2 Preparing the COD data

The code does not download data. **The source data is not in this repository**: as of 2026-10-23 the
source data was moved out and is kept in one place:

```
D:/Project/XRD/sync-COD/          ← data root, shared by the PolyXRD and XinMatch databases
├── COD/                    required: COD CIFs (3-level layout, e.g. COD/1/00/00/1000000.cif)
├── PCOD/                   PCOD CIFs (2-level layout, all inorganic: GRINSP prediction set)
├── TCOD/                   TCOD CIFs (3-level layout, including powder/organic entries)
├── inorg_cif/{COD,PCOD,TCOD}/   inorganic subset copies (generated by scan_inorg.py)
└── inorg_manifest.sqlite        per-file manifest (generated by scan_inorg.py)
```

This directory also has its own repository: [**PolyXRD/sync-COD**](https://github.com/PolyXRD/sync-COD)
— it contains only data-side tools (3 data-validation + 10 official-sync tools) and layout notes; the
data is likewise not committed. Data integrity can be checked in one pass with its
`tools/verify_data_root.py`, which verifies 17 items.

When switching disks or machines, override with an environment variable; no need to change the code:

```bash
export XRD_DATA_ROOT=/path/to/sync-COD
```

Generate the manifest (inorganic classification + unified numbering + one line per file):

```bash
python tools/scan_inorg.py --workers 6
```

### 3.3 Building the databases

```bash
python tools/build_polydb.py --scope inorg --workers 8     # → polydb/COD-Inorg-<today>.polyDB
python tools/build_polydb.py --scope full  --workers 8     # → polydb/COD-Full-<today>.polyDB

# Other source databases: --lib COD|PCOD|TCOD (default COD, behavior unchanged) + --stamp to specify the date stamp
python tools/build_polydb.py --lib TCOD --scope full --stamp 20261020 --workers 4
python tools/build_polydb.py --lib PCOD --scope inorg --stamp 20261020 --workers 4
```

- Two phases: split units in parallel (default 2000 rows/unit, existing units are skipped
  automatically → **resumable from breakpoints**) → serial merge writing segments.
- `--limit N` / `--out PATH` for a trial build first; `--force` ignores old parts and recomputes;
  `--bins-only --out <existing database>` rebuilds only `bins.u8` from `peaks_d.f32` (takes effect in
  seconds when tuning `--bins-top-m`).
- At the end it prints a **count-conservation check**: `manifest = ingested + skip`; if unbalanced it
  raises an alarm (a typical symptom of stale parts left by a resumed run).
- `--max-skip-ratio` (default 0.20): if the skip rate exceeds the limit it aborts immediately and
  refuses to publish the database — preventing the class of accidents where "a missing
  scattering-factor table makes a worker swallow the exception and the run finishes with an empty
  shell database".
- Parts are separated by variant into directories (`_polydb_parts/<lib>-<scope>/`), so the three
  databases do not interfere with each other.

### 3.4 Measured build times (this machine: 4 cores / mechanical disk / local COD copy)

| Database | Manifest rows | Ingested | skip | Split-phase time | Artifact size |
|---|---|---|---|---|---|
| Inorg | 79,198 | 77,500 | 1,698 (2.14%) | **531.7 s** (8 processes) | 85.8 MiB |
| Full | 535,166 | 521,361 | 13,805 (2.58%) | **18,176 s ≈ 5.05 h** (8 processes) | 1056.3 MiB |

All skips are classifiable: `no_sites` (no atomic sites), `no_pattern` (expansion/calculation
error), `volume_too_large` (cell > 30,000 Å³), `no_volume` (no cell volume).

### 3.5 MP database (Materials Project, added 2026-10-31)

```bash
export XRD_MP_CIF_DIR=/path/to/mp_cif          # Default: D:\Project\MP-summary\cif
python tools/build_mp_polydb.py --workers 14 --out polydb/MP-<date>.polyDB
python tools/verify_mp_polydb.py polydb/MP-<date>.polyDB --sample 100   # L3 accuracy layer
```

- MP CIFs are pymatgen **P1 primitive cells**: each entry goes through "primitive cell →
  conventional cell → asymmetric unit", and peaks are computed on the conventional cell; three-level
  fallback L0 (real SG + asymmetric unit) → L1 (all conventional-cell atoms + `P 1`)
  → L2 (all primitive-cell atoms + `P 1`), summarized in `meta.build.cell_representations`.
- Resumable from breakpoints as above: `_mp_polydb_parts/<variant>/uNNNNN.*`, `--force` recomputes.
- Measured on this machine: 155,204 phases / 179 MB / about 60 min with 14 processes (of which one
  dense double-perovskite unit took 15 min).
- `entries.eid` = MP number; `mvc-*` entries fall in the 900-million number range; `tier=2`
  (theoretical).

---

## 4. Validation

```bash
python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB                # with sha256
python tools/verify_polydb.py polydb/COD-Full-20261021.polyDB --no-hash       # saves time on large databases
python tools/verify_mp_polydb.py polydb/MP-20261031.polyDB --sample 100       # MP: L3 recomputation
```

Pure standard-library implementation, 32 hard criteria: all segments present / byte counts / sha256 /
shapes of each segment self-consistent / `sites_off` monotonic with last value == `sites.bin` length
(divisible by 17) / `PRAGMA integrity_check` / `entries` row count == N / `row_idx` is a complete
unique permutation of 0..N-1 / sampled rows sorted by intensity descending with empty slots at the tail.

Measured results for the two released databases: **32/32 PASS each, 0 WARN**; the distributed zips
match the source directories file by file in CRC32 + byte count.

---

## 5. Directory structure

```
.
├── _atomic_scattering_params.json   Cromer-Mann coefficients (same data as pymatgen, 99 elements)
├── tools/                           only polyDB building and artifact validation, index in tools/README.md
│   ├── build_polydb.py              polyDB builder (main entry point)
│   ├── scan_inorg.py                inorganic-classification scan for the three databases + manifest inorg_manifest.sqlite
│   ├── cif_common.py                shared pure functions (chemical formula / inorganic classification / cell volume / molar mass)
│   ├── fastcif.py                   fast CIF parsing + symmetry expansion
│   ├── fastxrd.py                   peak-position/intensity calculation (no temperature factor, pymatgen convention)
│   └── verify_polydb.py             polyDB structure validator, 32 items
└── docs/
    ├── 外挂库格式规范-polyDB-v4.md   field-level specification (container / peak convention / segments / reader contract)
    ├── polyDB重建方案-20261021.md   design trade-offs, 13-sample ablation, A/B comparison
    └── bench/                       build reports and benchmark JSON (including full Inorg pipeline measurements)
```

The data root also has its own tools directory `<data root>/tools/` (**not in this repository**):
3 data-validation tools (`verify_data_root` / `verify_inorg_copy` / `verify_coverage`) + 10 sync
tools (disabled). The dividing line is "validating data" vs "validating artifacts" — the former
follows the data, the latter follows the build code.

> **Format consolidation (2026-10-23)**: only two database formats remain — this repository's
> **polyDB** (PolyXRD external database) and **xinDB** (XinMatch's native database, see the sister
> repository [XinMatch-DataBase](https://github.com/PolyXRD/XinMatch-DataBase)). The earlier 3COD
> `.sqlite` monolithic database, its packaging specification and reference implementation
> (formerly `sync-COD-pack/`) **have been deprecated and removed from the repository**; they are no
> longer maintained or distributed.
>
> 2026-10-23 also saw a code consolidation: the old-format build/validation machine and one-off
> diagnostic scripts (50) were deleted, leaving only 9 scripts; consult the git history if you need
> to dig into the past.

**The data is not in the repository** (`.gitignore` also excludes
`COD/ PCOD/ TCOD/ inorg_cif/ inorg_manifest.sqlite`, to prevent anyone from accidentally putting it
back). The only ignored artifact directory inside the repository is `polydb/`.

> **xinDB has been moved out** (2026-10-23): the three `.xinDB` files were moved from this
> repository's `xindb/` to the `data/` of the sister repository
> [XinMatch-DataBase](https://github.com/PolyXRD/XinMatch-DataBase), and the build code and tools
> moved there as well. This repository is responsible only for **polyDB**; the source data root
> `D:/Project/XRD/sync-COD` is shared by both databases and is contained in neither repository.

---

## 6. Known gaps (measured on the 20261021 build)

| Item | Current state of the two released databases | Impact | Status |
|---|---|---|---|
| `entries.density` | **100% NULL in both databases** (Inorg 0/77,500, Full 0/521,361) | the "density" column in PolyXRD's candidate list is blank; does not affect peak positions / search / refinement | **Fixed in code (2026-10-23)**: `formula_mass()` in `build_dbs.py` did not exist at all; the exception was swallowed by `try/except` and wrote None. An IUPAC standard atomic-weight table has now been added in `cif_common.py`; measured fill rate on a 196-phase slice is 94.4% (corundum Al₂O₃ computed 3.98 g/cm³, measured 3.99). **Published artifacts unchanged** (changing them would break the sha256 match); the next rebuild will be normal |
| `entries.tier` / `dup_group` | all 0 (no tiering, no merging of duplicate phases) | multiple duplicates of the same phase all appear in search results | untouched; needs phase de-duplication by space group + cell + elements |
| Peak-calculation skip | Inorg 1,698 entries (2.14%), Full 13,805 entries (2.58%) | these entries are not ingested (mostly no atomic sites / cell > 30,000 Å³) | classified and recorded by cause in `meta.build.skip_reasons`, can be assessed cause by cause |

## 7. Data sources and licensing

- **Code**: follows PolyXRD's dual license (academic non-commercial / commercial by separate
  agreement), see `LICENSE`, `LICENSE-CN`.
- **Data (COD)**: CIF content copyright belongs to COD and the authors of the original literature.
  When using this repository's artifacts, please comply with
  [COD's terms of use](http://www.crystallography.net/cod/) and cite COD and the corresponding
  original literature. This repository distributes only **derived indexes**
  (peak positions/intensities/sites); it does not rewrite or replace the original CIFs.
- **Data (MP)**: Materials Project summary data is provided under CC BY 4.0; when using it please
  cite [Materials Project](https://materialsproject.org) (APL Materials 4, 053501 (2016)).
  `MP-20261031` is likewise a derived index, and entries can be traced back to the source CIF file
  name via `entries.cif_rel`.
- Peak positions/intensities are **computed values** (no temperature factor, no
  instrumental/sample broadening), and have systematic deviations from experimental cards
  (ICDD PDF) (high-angle lines too strong). Sufficient for phase identification; for quantitative
  analysis you must calibrate yourself.

## 8. Version history

| Date | Event |
|---|---|
| 2026-10-21 | polyDB v4 format finalized; the `COD-Inorg` / `COD-Full` databases built |
| 2026-10-23 | this repository created and the `20261021` release published (code + two database zips) |
| 2026-10-23 | format consolidation: removed the old 3COD `.sqlite` packaging specification and reference code (`sync-COD-pack/`); from then on only **polyDB** and **xinDB** remain |
| 2026-10-23 | **source data moved out of the repository** → `D:/Project/XRD/sync-COD` (`COD/ PCOD/ TCOD/ inorg_cif/ inorg_manifest.sqlite`, shared by both databases), all scripts switched to `XRD_DATA_ROOT` |
| 2026-10-23 | **code consolidation**: `tools/` cut from 92 scripts to 6; old-format build/validation and one-off diagnostics all deleted |
| 2026-10-23 | 10 sync + 3 data-validation scripts moved out of the repository into `<data root>/tools/` (sync part disabled); the repository keeps only the build chain and artifact validation |
| 2026-10-23 | data-side tools spun off into the public repository [**PolyXRD/sync-COD**](https://github.com/PolyXRD/sync-COD) (data still not committed) |
| 2026-10-23 | added `formula_mass()` (IUPAC atomic weights), fixing the all-NULL `density` defect (takes effect on the next rebuild) |
| 2026-10-31 | added `tools/build_mp_polydb.py` / `verify_mp_polydb.py` / `cif_dir_to_polydb.py`: MP summary CIF → polyDB, L0/L1/L2 cell fallback |
| 2026-10-31 | published `20261031`: **MP** database with 155,204 phases (106.5 MB zip), structure 32/32 PASS, L3 recomputation passed |
