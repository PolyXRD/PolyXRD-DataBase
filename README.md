# PolyXRD-DataBase

**PolyXRD 外挂物相库（polyDB 格式）的构建代码、格式规范与发布产物。**

本仓库只放**代码与文档**；数据库本体以 [Releases](../../releases) 里的压缩包分发（单库 48 MB / 710 MB，
不入 git 历史）。数据源为 [Crystallography Open Database (COD)](http://www.crystallography.net/cod/)，
本仓库不转售、不改造原始 CIF，只做峰位/强度计算与索引打包。

---

## 1. 发布产物（Release `20261021`）

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

完整字段级规范见 [`docs/外挂库格式规范-polyDB-v1.md`](docs/外挂库格式规范-polyDB-v1.md)，
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

代码不下载数据。按 COD 官方方式获取 CIF 后，摆成如下布局（目录名固定）：

```
<data-root>/
├── COD/                     # 必需：COD 的 CIF（层级 3，如 COD/1/00/00/1000000.cif）
├── PCOD/                    # 可选：本仓库脚本支持，但 polyDB 发布版只用 COD
├── TCOD/                    # 可选
├── inorg_manifest.sqlite    # 由 tools/scan_inorg.py 生成
└── _atomic_scattering_params.json
```

生成清单（无机判定 + 统一编号 + 每文件一行）：

```bash
python tools/scan_inorg.py --workers 6
```

### 3.3 建库

```bash
python tools/build_polydb.py --scope inorg --workers 8     # → polydb/COD-Inorg-<今天>.polyDB
python tools/build_polydb.py --scope full  --workers 8     # → polydb/COD-Full-<今天>.polyDB
```

- 两阶段：并行切 unit（默认 2000 行/单元，已存在的 unit 自动跳过 → **断点续跑**）→ 串行合并写段。
- `--limit N` / `--out PATH` 可先试产；`--force` 忽略旧 part 重算；
  `--bins-only --out <现有库>` 只从 `peaks_d.f32` 重建 `bins.u8`（调 `--bins-top-m` 时秒级生效）。
- 收尾会打印**条数守恒检查**：`清单 = 入库 + skip`，不平就报警（断点续跑留下陈旧 part 的典型症状）。

### 3.4 实测工期（本机 4 核 / 机械盘 / COD 本机副本）

| 库 | 清单条数 | 入库 | skip | 分片阶段耗时 | 产物体积 |
|---|---|---|---|---|---|
| Inorg | 79,198 | 77,500 | 1,698（2.14%） | **531.7 s**（8 进程） | 85.8 MiB |
| Full | 535,166 | 521,361 | 13,805（2.58%） | **18,176 s ≈ 5.05 h**（8 进程） | 1056.3 MiB |

skip 全部可分类：`no_sites`（无原子位点）、`no_pattern`（展开/计算异常）、
`volume_too_large`（晶胞 > 30,000 Å³）、`no_volume`（无晶胞体积）。

---

## 4. 校验

```bash
python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB                # 含 sha256
python tools/verify_polydb.py polydb/COD-Full-20261021.polyDB --no-hash       # 大库省时
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
├── tools/                           构建/同步/验收脚本全集，索引见 tools/README.md
│   ├── build_polydb.py              polyDB 构建器（主入口）
│   ├── fastcif.py                   快速 CIF 解析 + 对称展开
│   ├── fastxrd.py                   峰位/强度计算（无温度因子，pymatgen 口径）
│   ├── build_dbs.py                 化学式/元素解析、无机判定
│   ├── scan_inorg.py                三库无机分类扫描 + 清单 inorg_manifest.sqlite
│   ├── verify_polydb.py             结构/校验和校验器（本仓库新增）
│   └── bench_polydb_pilot.py        小样本试产：单条耗时 / 峰数分布 / 与旧库峰位 parity
└── docs/
    ├── 外挂库格式规范-polyDB-v1.md   字段级规范（容器/峰口径/各段/reader 契约）
    ├── polyDB重建方案-20261021.md   设计取舍、13 试样消融、A/B 比对
    └── bench/                       建库报告与基准 JSON（含 Inorg 全链路实测）
```

> **格式收敛（2026-10-23）**：数据库格式只保留两种 —— 本仓库的 **polyDB**（PolyXRD 外挂库）
> 与 **xinDB**（XinMatch 原生库，见姊妹仓库
> [XinMatch-DataBase](https://github.com/PolyXRD/XinMatch-DataBase)）。早期的 3COD `.sqlite`
> 单体库及其打包规范、参考实现（原 `sync-COD-pack/`）**已废弃并从仓库移除**，不再维护、不再分发。
>
> `tools/` 里仍留有旧格式链路的脚本作为**只读存档**（口径与 polyDB 不同，勿混用，
> 详见 [`tools/README.md`](tools/README.md) C 组）。构建 polyDB 只需要 A 组 7 个脚本。

不入仓的目录（`.gitignore` 已排除）：`COD/ PCOD/ TCOD/ inorg_cif/ polydb/ xindb/`、
`*.sqlite`、`_polydb_parts/`、`_scan_parts/`。

---

## 6. 已知缺口（20261021 版实测，未修）

| 项 | 现状 | 影响 | 修法 |
|---|---|---|---|
| `entries.density` | **两库 100% 为 NULL**（Inorg 0/77,500、Full 0/521,361） | PolyXRD 候选列表的"密度"列空白；不影响峰位/检索/精修 | `build_polydb.py` 里 `B.formula_mass()` 实际不存在（`build_dbs` 无质量表），异常被 `try/except` 吞掉后写 None。补一张原子量表 + 只重建 `index.sqlite` 即可，无需重算峰 |
| `entries.tier` / `dup_group` | 全为 0（未分层、未合并同相复本） | 检索结果里同一物相的多条复本都出现 | 需按空间群+晶胞+元素做去重组，属后续工作 |
| 峰计算 skip | Inorg 1,698 条（2.14%）、Full 13,805 条（2.58%） | 这些条目不进库（多为无原子位点 / 晶胞 > 30,000 Å³） | 已按原因分类记录在 `meta.build.skip_reasons`，可逐类评估 |

> `density` 这一条是本仓库建立（2026-10-23）时复核发现的既有缺陷，两个已发布库原样保留
> （未改动产物，以免与校验值不符），代码侧待修。

## 7. 数据来源与许可

- **代码**：沿 PolyXRD 的双许可（学术非商业 / 商业另议），见 `LICENSE`、`LICENSE-CN`。
- **数据**：CIF 内容版权归 COD 及各原始文献作者。使用本仓库产物时请遵守
  [COD 的使用条款](http://www.crystallography.net/cod/) 并引用 COD 与相应原始文献。
  本仓库仅分发**派生索引**（峰位/强度/位点），不改写也不替代原始 CIF。
- 峰位/强度为**计算值**（无温度因子、无仪器/样品展宽），与实验卡片（ICDD PDF）存在
  系统性偏差（高角线偏强）。用于物相识别足够，用于定量须自行标定。

## 8. 版本

| 日期 | 事件 |
|---|---|
| 2026-10-21 | polyDB v1 格式定稿；`COD-Inorg` / `COD-Full` 两库建成 |
| 2026-10-23 | 本仓库建立并发布 `20261021` release（代码 + 两库 zip） |
| 2026-10-23 | 格式收敛：移除旧 3COD `.sqlite` 打包规范与参考代码（`sync-COD-pack/`）；此后只保留 **polyDB** 与 **xinDB** |
