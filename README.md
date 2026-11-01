# PolyXRD-DataBase

**PolyXRD 外挂物相库（polyDB 格式）的构建代码、格式规范与发布产物。**

本仓库只放**代码与文档**；数据库本体以 [Releases](../../releases) 里的压缩包分发（单库 48 MB / 710 MB，
不入 git 历史）。数据源为 [Crystallography Open Database (COD)](http://www.crystallography.net/cod/)
与 [Materials Project](https://materialsproject.org)（CC BY 4.0）；本仓库不转售、不改造原始 CIF，
只做峰位/强度计算与索引打包。

---

## 1. 发布产物（Release `20261020` / `20261021` / `20261031`）

### 1.1 MP-20261031（Materials Project 外挂库）

| 库 | 物相数 | 峰数 | 位点数 | 解压后 | Release 压缩包 | SHA-256 (zip) |
|---|---|---|---|---|---|---|
| **MP** | 155,204 | 12,705,201 | 2,407,784 | 187,675,763 B（179.0 MiB） | `MP-20261031.polyDB.zip`（106.5 MB） | `ccfccf53…a16c22` |

- 数据源：[Materials Project](https://materialsproject.org) summary（2025-09-25，CC BY 4.0）。
  210,579 条记录按 reduced formula 去重、每组保留最低 `energy_above_hull` 构型，得 155,204 相。
- MP 的 CIF 是 pymatgen 导出的 **P1 原胞**：构建器做「原胞 → 常规胞 → 非对称单位」，
  峰在常规胞上计算，避免 F/I/C 心晶格把等价反射拆成假峰（详见 `tools/build_mp_polydb.py` 的文档字符串）。
- `entries.eid` = MP 编号（`mp-3207172` → `3207172`），`mvc-*` 条目落 9 亿号段；
  `tier=2`（DFT 理论结构，非实验 PDF 卡）。
- 构建 / 校验：`tools/build_mp_polydb.py`、`tools/verify_mp_polydb.py`；
  实测结构校验 32/32 PASS、L3 回算 max|Δd|=8.1×10⁻⁷ Å / max|ΔI|=0.015（100 相）。

### 1.2 COD-20261021（COD 无机 / 全库）

| 库 | 物相数 | 峰数 | 位点数 | 解压后 | Release 压缩包 | SHA-256 (zip) |
|---|---|---|---|---|---|---|
| **COD-Inorg** | 77,500 | 5,962,013 | 1,005,846 | 89,926,214 B（85.8 MiB） | `COD-Inorg-20261021.polyDB.zip`（48.1 MB） | `d9e57d11…33cf14` |
| **COD-Full** | 521,361 | 50,328,800 | 36,315,927 | 1,107,655,264 B（1056.3 MiB） | `COD-Full-20261021.polyDB.zip`（710.3 MB） | `191246b7…1bbd6e` |

> 完整校验值见 Release 附带的 `SHA256SUMS.txt`（同时给出 zip 与解压后各段的 sha256，
> 后者已写进各库自己的 `meta.json`）。

- `COD-Inorg` = COD 中判为无机的条目（不含 C，或含 C 但不含 H）；`COD-Full` = COD 全量。
  两者互不包含，**选一个装即可**，PolyXRD 会自动识别 `meta.variant`（`cod-inorg` / `cod-full`）。
- 命名里的 `20261021` 是**构建日期**；源数据快照时间见 `meta.json.source.manifest_built_at`
  （2026-10-20 01:52:04）。
- 解压后得到同名 `.polyDB` **目录**，可直接挂载（本地盘/移动硬盘/NAS 均可），
  **不支持**在 zip 内直接 mmap。

```bash
# 使用方式（任一目录放到任意路径后，在 PolyXRD 里指向该 .polyDB 目录）
unzip COD-Inorg-20261021.polyDB.zip
python tools/verify_polydb.py COD-Inorg-20261021.polyDB
```

### 1.3 TCOD / PCOD-20261020（TCOD 无机 / 全库 + PCOD 无机）

| 库 | 物相数 | 峰数 | 位点数 | 解压后 | Release 压缩包 | SHA-256 (zip) |
|---|---|---|---|---|---|---|
| **TCOD-Inorg** | 46,541 | 3,767,731 | 754,606 | 55,138,528 B（52.6 MiB） | `TCOD-Inorg-20261020.polyDB.zip`（31.5 MB） | `783bc4f6…cc4ead` |
| **TCOD-Full** | 359,307 | 35,039,291 | 22,178,424 | 714,704,055 B（681.6 MiB） | `TCOD-Full-20261020.polyDB.zip`（466.6 MB） | `81ae572f…56ab47` |
| **PCOD-Inorg** | 1,061,817 | 106,160,732 | 32,522,180 | 1,481,618,146 B（1413.0 MiB） | `PCOD-Inorg-20261020.polyDB.zip`（936.9 MB） | `898dc822…89310f` |

> 完整校验值见 Release 附带的 `SHA256SUMS.txt`；各库内部 8 段的 sha256 写在自身 `meta.json.sections`。

- `TCOD-Inorg` / `TCOD-Full` = TCOD（理论计算结构）的无机子集 / 全量（Full 多出的主要是 C/H 有机相，各约 32 万相）；
  `PCOD-Inorg` = PCOD 全量 —— **PCOD 没有 `Full` 变体**：清单里 1,061,962 条
  `is_inorg` 全为 1（GRINSP 预测集本身不含有机相），`pcod-full` 会与 `pcod-inorg` 逐字节相同。
- `variant` 分别为 `tcod-inorg` / `tcod-full` / `pcod-inorg`，互不相同，可与 COD 库共存。
  PolyXRD v4.x 的内置槽位只登记 `cod-inorg` / `cod-full`，这三个库走挂载面板「自定义挂载」。
- 命名里的 `20261020` 是**官方库同步日期**（非构建日；构建于 2026-10-31）。
- 三库均通过三重验收（结构 32/32、抽样 200 相回算 max|Δd| ≤ 9.5×10⁻⁷ Å、PolyXRD reader 挂载 + 检索），
  细节见 [`docs/polyDB-TCOD-PCOD构建报告-20261020.md`](docs/polyDB-TCOD-PCOD构建报告-20261020.md)。

```bash
python tools/build_polydb.py --lib TCOD --scope inorg --stamp 20261020 --workers 4
python tools/build_polydb.py --lib TCOD --scope full  --stamp 20261020 --workers 4
python tools/build_polydb.py --lib PCOD --scope inorg --stamp 20261020 --workers 4
```

---

## 2. polyDB 是什么

一个 `.polyDB` 是一个**目录容器**，把"检索要用的峰表 + 位图倒排 + 精修要用的原子位点"分成
定长数组段，用 mmap 按需读取，因此 52 万相也能做到"打开即用、检索秒级"。

```
COD-Inorg-20261021.polyDB/
├── meta.json        自描述：版本 / 峰口径 / 各段 shape+bytes+sha256
├── index.sqlite     条目元数据（公式/空间群/晶胞/密度/元素/CIF 相对路径）+ FTS5
├── peaks_d.f32      (N×100) float32  峰位 d，行内按强度降序
├── peaks_i.u16      (N×100) uint16   强度量化（u16/65535*1000）
├── bins.u8          (501×⌈N/8⌉)       d 分箱位图倒排（0.05 Å/箱，索引每相最强 40 条）
├── elem.u8          (118×⌈N/8⌉)       元素位图（Z=1..118）
├── sites.bin        原子位点流（17 B/点：Z + xyz + occ）
└── sites_off.i64    (N+1) int64      指向 sites.bin 的偏移
```

**峰口径**（写死进 `meta.json.peak_convention`，与本仓库代码一致）：

| 项 | 取值 |
|---|---|
| 波长 λ | 1.5406 Å（Cu Kα1） |
| 2θ 范围 | 5.0 – 100.76°（等价 `d ≥ 1.0 Å`） |
| 等价反射 | 按 2θ 合并（含多重性），与 `fastxrd` 一致 |
| 强度归一 | 每相最强峰 = 1000 |
| 峰选择 | **按强度降序取前 K=100 条**（不是按 d 截断） |
| 温度因子 | 无 Debye-Waller（= pymatgen 默认口径） |
| 阵列 | 全部 little-endian，不支持大端 |

完整字段级规范见 [`docs/外挂库格式规范-polyDB-v4.md`](docs/外挂库格式规范-polyDB-v4.md)，
设计取舍与实测数据见 [`docs/polyDB重建方案-20261021.md`](docs/polyDB重建方案-20261021.md)。

> ⚠️ **行号铁律**：数组段行号必须走 `index.sqlite.entries.row_idx` 列，**不能**用 `eid-1`。
> `eid` 是 `INTEGER PRIMARY KEY`（= rowid），COD 编号从 1,000,000 起，
> 两者不相等（实测全库 0 行成立）。写第三方 reader 时最容易在这里整体错位。

---

## 3. 从零构建

### 3.1 环境

| 依赖 | 要求 | 说明 |
|---|---|---|
| Python | 3.10+ | 实测 3.10.11 |
| numpy | 必需 | 峰计算与数组段写入 |
| pymatgen | 可选 | 装了就用它自带的散射因子表，保证与官方口径完全一致；否则读 `_atomic_scattering_params.json` |
| 磁盘 | 约 2× 库体积 | Full 库构建峰值约需 3 GB 临时空间（`_polydb_parts/`） |
| 内存 | 8 GB 级 | 合并阶段 `peaks_d` 走 memmap，不整体驻留 |

```bash
pip install numpy
# 可选：pip install pymatgen
```

### 3.2 准备 COD 数据

代码不下载数据。**源数据不在本仓库**：2026-10-23 起源数据迁出，统一放在

```
D:/Project/XRD/sync-COD/          ← 数据根，PolyXRD / XinMatch 两库共用
├── COD/                    必需：COD 的 CIF（3 级布局，如 COD/1/00/00/1000000.cif）
├── PCOD/                   PCOD 的 CIF（2 级布局，全为无机：GRINSP 预测集）
├── TCOD/                   TCOD 的 CIF（3 级布局，含粉末/有机条目）
├── inorg_cif/{COD,PCOD,TCOD}/   无机子集副本（由 scan_inorg.py 生成）
└── inorg_manifest.sqlite        逐条清单（由 scan_inorg.py 生成）
```

这个目录本身也有仓库：[**PolyXRD/sync-COD**](https://github.com/PolyXRD/sync-COD)
——只放数据侧工具（数据验收 3 个 + 与官方同步 10 个）和布局说明，数据同样不入库。
数据完整性可以用它的 `tools/verify_data_root.py` 一次验 17 项。

换盘或换机器时用环境变量覆盖，不必改代码：

```bash
export XRD_DATA_ROOT=/path/to/sync-COD
```

生成清单（无机判定 + 统一编号 + 每文件一行）：

```bash
python tools/scan_inorg.py --workers 6
```

### 3.3 建库

```bash
python tools/build_polydb.py --scope inorg --workers 8     # → polydb/COD-Inorg-<今天>.polyDB
python tools/build_polydb.py --scope full  --workers 8     # → polydb/COD-Full-<今天>.polyDB

# 其它来源库：--lib COD|PCOD|TCOD（缺省 COD，行为不变）+ --stamp 指定日期戳
python tools/build_polydb.py --lib TCOD --scope full --stamp 20261020 --workers 4
python tools/build_polydb.py --lib PCOD --scope inorg --stamp 20261020 --workers 4
```

- 两阶段：并行切 unit（默认 2000 行/单元，已存在的 unit 自动跳过 → **断点续跑**）→ 串行合并写段。
- `--limit N` / `--out PATH` 可先试产；`--force` 忽略旧 part 重算；
  `--bins-only --out <现有库>` 只从 `peaks_d.f32` 重建 `bins.u8`（调 `--bins-top-m` 时秒级生效）。
- 收尾会打印**条数守恒检查**：`清单 = 入库 + skip`，不平就报警（断点续跑留下陈旧 part 的典型症状）。
- `--max-skip-ratio`（默认 0.20）：跳过率超限直接中止、拒绝出库 —— 防"散射因子表缺失导致
  worker 吞异常、跑完出空壳库"那类事故。
- parts 按 variant 分目录（`_polydb_parts/<lib>-<scope>/`），三库互不干扰。

### 3.4 实测工期（本机 4 核 / 机械盘 / COD 本机副本）

| 库 | 清单条数 | 入库 | skip | 分片阶段耗时 | 产物体积 |
|---|---|---|---|---|---|
| Inorg | 79,198 | 77,500 | 1,698（2.14%） | **531.7 s**（8 进程） | 85.8 MiB |
| Full | 535,166 | 521,361 | 13,805（2.58%） | **18,176 s ≈ 5.05 h**（8 进程） | 1056.3 MiB |

skip 全部可分类：`no_sites`（无原子位点）、`no_pattern`（展开/计算异常）、
`volume_too_large`（晶胞 > 30,000 Å³）、`no_volume`（无晶胞体积）。

### 3.5 MP 库（Materials Project，2026-10-31 新增）

```bash
export XRD_MP_CIF_DIR=/path/to/mp_cif          # 默认 D:\Project\MP-summary\cif
python tools/build_mp_polydb.py --workers 14 --out polydb/MP-<日期>.polyDB
python tools/verify_mp_polydb.py polydb/MP-<日期>.polyDB --sample 100   # L3 精度层
```

- MP CIF 是 pymatgen 的 **P1 原胞**：逐条做「原胞 → 常规胞 → 非对称单位」，
  峰在常规胞上计算；三级回退 L0（真实 SG + 非对称单位）→ L1（常规胞全原子 + `P 1`）
  → L2（原胞全原子 + `P 1`），汇总在 `meta.build.cell_representations`。
- 断点续跑同上：`_mp_polydb_parts/<variant>/uNNNNN.*`，`--force` 重算。
- 本机实测：155,204 相 / 179 MB / 14 进程约 60 min（其中 1 个双钙钛矿密集单元 15 min）。
- `entries.eid` = MP 编号；`mvc-*` 条目落 9 亿号段；`tier=2`（理论）。

---

## 4. 校验

```bash
python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB                # 含 sha256
python tools/verify_polydb.py polydb/COD-Full-20261021.polyDB --no-hash       # 大库省时
python tools/verify_mp_polydb.py polydb/MP-20261031.polyDB --sample 100       # MP：L3 回算
```

纯标准库实现，32 项硬判据：段齐全 / 字节数 / sha256 / 各段 shape 自洽 /
`sites_off` 单调且末值 == `sites.bin` 长度（整除 17）/ `PRAGMA integrity_check` /
`entries` 行数 == N / `row_idx` 是 0..N-1 的完整唯一排列 / 抽样行内按强度降序且空槽在尾部。

两个发布库的实测结果：**各 32/32 PASS，0 WARN**；分发的 zip 与源目录逐文件 CRC32 + 字节数一致。

---

## 5. 目录结构

```
.
├── _atomic_scattering_params.json   Cromer-Mann 系数（pymatgen 同一份数据，99 元素）
├── tools/                           只保留 polyDB 构建与产物验收，索引见 tools/README.md
│   ├── build_polydb.py              polyDB 构建器（主入口）
│   ├── scan_inorg.py                三库无机分类扫描 + 清单 inorg_manifest.sqlite
│   ├── cif_common.py                共用纯函数（化学式/无机判定/晶胞体积/摩尔质量）
│   ├── fastcif.py                   快速 CIF 解析 + 对称展开
│   ├── fastxrd.py                   峰位/强度计算（无温度因子，pymatgen 口径）
│   └── verify_polydb.py             polyDB 结构 32 项验收器
└── docs/
    ├── 外挂库格式规范-polyDB-v4.md   字段级规范（容器/峰口径/各段/reader 契约）
    ├── polyDB重建方案-20261021.md   设计取舍、13 试样消融、A/B 比对
    └── bench/                       建库报告与基准 JSON（含 Inorg 全链路实测）
```

数据根另有自己的工具目录 `<数据根>/tools/`（**不在本仓库**）：数据验收 3 个
（`verify_data_root` / `verify_inorg_copy` / `verify_coverage`）+ 同步 10 个（停用）。
分界是"验数据"还是"验产物"——前者跟着数据走，后者跟着构建代码走。

> **格式收敛（2026-10-23）**：数据库格式只保留两种 —— 本仓库的 **polyDB**（PolyXRD 外挂库）
> 与 **xinDB**（XinMatch 原生库，见姊妹仓库
> [XinMatch-DataBase](https://github.com/PolyXRD/XinMatch-DataBase)）。早期的 3COD `.sqlite`
> 单体库及其打包规范、参考实现（原 `sync-COD-pack/`）**已废弃并从仓库移除**，不再维护、不再分发。
>
> 2026-10-23 同时做了代码收敛：旧格式构建/验收机与一次性诊断脚本（50 个）已删除，
> 只留 9 个脚本；需要考古时查 git 历史。

**数据不在仓库内**（`.gitignore` 也排除了 `COD/ PCOD/ TCOD/ inorg_cif/ inorg_manifest.sqlite`，
以防有人误放回来）。仓库内唯一被忽略的产物目录是 `polydb/`。

> **xinDB 已迁出**（2026-10-23）：三个 `.xinDB` 从本仓库的 `xindb/` 移到姊妹仓库
> [XinMatch-DataBase](https://github.com/PolyXRD/XinMatch-DataBase) 的 `data/`，
> 构建代码与工具也一并归到那边。本仓库只负责 **polyDB**；源数据根
> `D:/Project/XRD/sync-COD` 由两库共用、两个仓库都不包含它。

---

## 6. 已知缺口（20261021 版实测）

| 项 | 已发布两库的现状 | 影响 | 状态 |
|---|---|---|---|
| `entries.density` | **两库 100% 为 NULL**（Inorg 0/77,500、Full 0/521,361） | PolyXRD 候选列表的"密度"列空白；不影响峰位/检索/精修 | **代码已修（2026-10-23）**：`build_dbs.py` 里 `formula_mass()` 根本不存在，异常被 `try/except` 吞掉后写 None。现已在 `cif_common.py` 补上 IUPAC 标准原子量表，实测 196 相切片填充率 94.4%（刚玉 Al₂O₃ 算得 3.98 g/cm³，实测 3.99）。**已发布产物未改动**（改了 sha256 就对不上），下次重建即正常 |
| `entries.tier` / `dup_group` | 全为 0（未分层、未合并同相复本） | 检索结果里同一物相的多条复本都出现 | 未动，需按空间群+晶胞+元素做去重组 |
| 峰计算 skip | Inorg 1,698 条（2.14%）、Full 13,805 条（2.58%） | 这些条目不进库（多为无原子位点 / 晶胞 > 30,000 Å³） | 已按原因分类记录在 `meta.build.skip_reasons`，可逐类评估 |

## 7. 数据来源与许可

- **代码**：沿 PolyXRD 的双许可（学术非商业 / 商业另议），见 `LICENSE`、`LICENSE-CN`。
- **数据（COD）**：CIF 内容版权归 COD 及各原始文献作者。使用本仓库产物时请遵守
  [COD 的使用条款](http://www.crystallography.net/cod/) 并引用 COD 与相应原始文献。
  本仓库仅分发**派生索引**（峰位/强度/位点），不改写也不替代原始 CIF。
- **数据（MP）**：Materials Project summary 数据以 CC BY 4.0 提供，使用时请引用
  [Materials Project](https://materialsproject.org)（APL Materials 4, 053501 (2016)）。
  `MP-20261031` 同为派生索引，条目可经 `entries.cif_rel` 追溯到源 CIF 文件名。
- 峰位/强度为**计算值**（无温度因子、无仪器/样品展宽），与实验卡片（ICDD PDF）存在
  系统性偏差（高角线偏强）。用于物相识别足够，用于定量须自行标定。

## 8. 版本

| 日期 | 事件 |
|---|---|
| 2026-10-21 | polyDB v4 格式定稿；`COD-Inorg` / `COD-Full` 两库建成 |
| 2026-10-23 | 本仓库建立并发布 `20261021` release（代码 + 两库 zip） |
| 2026-10-23 | 格式收敛：移除旧 3COD `.sqlite` 打包规范与参考代码（`sync-COD-pack/`）；此后只保留 **polyDB** 与 **xinDB** |
| 2026-10-23 | **源数据迁出仓库** → `D:/Project/XRD/sync-COD`（`COD/ PCOD/ TCOD/ inorg_cif/ inorg_manifest.sqlite`，两库共用），全部脚本改走 `XRD_DATA_ROOT` |
| 2026-10-23 | **代码收敛**：`tools/` 从 92 个脚本收到 6 个，旧格式构建/验收与一次性诊断全部删除 |
| 2026-10-23 | 同步 10 个 + 数据验收 3 个脚本移出仓库，落到 `<数据根>/tools/`（同步部分停用）；仓库只留构建链与产物验收 |
| 2026-10-23 | 数据侧工具独立成公开仓库 [**PolyXRD/sync-COD**](https://github.com/PolyXRD/sync-COD)（数据仍不入库） |
| 2026-10-23 | 补 `formula_mass()`（IUPAC 原子量），修好 `density` 全 NULL 缺陷（下次重建生效） |
| 2026-10-31 | 新增 `tools/build_mp_polydb.py` / `verify_mp_polydb.py` / `cif_dir_to_polydb.py`：MP summary CIF → polyDB，L0/L1/L2 晶胞回退 |
| 2026-10-31 | 发布 `20261031`：**MP** 库 155,204 相（106.5 MB zip），结构 32/32 PASS、L3 回算通过 |
