# polyDB v4 格式规范（PolyXRD 外挂物相库）

> 状态：**定稿（v1）**　日期：2026-10-21　对应方案：`docs/polyDB重建方案-20261021.md`（S4）
> 设计目标（按优先级）：**准确性 > 检索速度 > 体积**。所有近似项都必须经 13 试样消融验证。

---

## 1. 容器

一个 polyDB 是一个**目录**，目录名以 `.polyDB` 结尾：

```
COD-Inorg-20261021.polyDB/
├── meta.json           # 自描述：版本 / 峰口径 / 各段统计与校验和
├── index.sqlite        # 相元数据 + 字符串 + FTS5（小，<300 MB）
├── peaks_d.f32         # (N × K) float32，按 I 降序
├── peaks_i.u16         # (N × K) uint16，强度量化
├── bins.u8             # d 分箱位图倒排（bin-major）
├── elem.u8             # 元素位图（element-major）
├── sites.bin           # 原子位点流（侧车，懒加载）
└── sites_off.i64       # (N+1) int64 偏移，指向 sites.bin
```

- 目录可放在**任意路径**（本地盘 / 移动硬盘 / NAS），挂载时只读打开，绝不写回。
- 分发可整体打 zip（解压后使用；**不支持**在 zip 内直接 mmap）。
- 大端序不支持；所有数值一律 **little-endian**。

---

## 2. 峰口径（写入 `meta.json.peak_convention`）

| 键 | v1 取值 | 说明 |
|---|---|---|
| `wavelength` | 1.5406 | Cu Kα1，Å |
| `tth_min` / `tth_max` | 5.0 / 100.76 | 2θ 范围（tth_max 由 d_min 反算） |
| `d_min` | 1.0 | d ≥ 1.0 Å |
| `merge` | `2theta` | 等价反射按 2θ 合并（含多重性）——与 `fastxrd` 一致 |
| `intensity_scale` | 1000.0 | 归一化到最强峰 = 1000 |
| `peak_select` | `intensity_top` | **按强度降序取前 K 条**（不再"按 d 降序截断"） |
| `k` | 100 | 每相最多保留的峰数 |
| `quant_i` | `u16/65535*1000` | 强度量化方式（见 §4.2） |

> `peak_select` 相对旧库/旧脚本的"按 d 降序取前 100"是**有意变更**：按强度取能保住高角度强线，对识别更有利。该变更必须由 S2/S18 消融背书。

---

## 3. 坐标与寻址

- `N` = 相数；`K` = 每相峰槽位数（固定 100）。
- 第 `i` 相（按 `index.sqlite.entries.row_idx` 升序，0-based）：
  - 峰槽：`peaks_d.f32[i*K : (i+1)*K]`，未用槽位填 `0.0`（d=0 表示空）。
  - 位点：`sites_off[i] .. sites_off[i+1]` 指定字节区间。
- **`i` 必须等于 `entries.row_idx`，而不是 `rowid-1` / `eid-1`**。`eid` 是
  `INTEGER PRIMARY KEY`（= rowid），COD 原始编号从 1,000,000 起，因此
  `eid-1 ≠ row_idx`（实测 Inorg 库 77,500/77,500 全部不成立）。建库时必须
  显式写 `row_idx` 列并建唯一索引，reader 只认这一列（`polydb.py` 的
  `row_of_eid` / `eid_of_row`）。

  > 早期版本的规范写过"`i` 与 `rowid-1` 一致"，那在 COD 编号下是错的；
  > 2026-10-23 勘误为显式 `row_idx`。按旧描述实现的第三方 reader 会整体错位。


---

## 4. 各段格式

### 4.1 `peaks_d.f32` / `peaks_i.u16`

- 形状 `(N, K)`，行主序；每相内部**按强度降序**（`I` 相同则保持原始顺序，稳定排序）。
- `d` 存 float32（相对误差 ~1e-7，绝对误差在 d=10 Å 处 ~1e-6 Å，远小于 0.02 Å 容差）。
- 空槽 `d = 0.0`、`i = 0`。

### 4.2 强度量化 `peaks_i.u16`

```
编码: u16 = round(I / 1000 * 65535)      # I 为归一化强度（0..1000）
解码: I   = u16 / 65535 * 1000
```
量化误差 ≤ 0.0076（1000 标度，约 0.0015% 相对），对排序与加权召回无实质影响；`I=1000` 编码为 65535（不溢出）。

### 4.3 `bins.u8`（d 分箱位图倒排）

| 项 | 值 |
|---|---|
| 箱宽 | **0.05 Å** |
| 箱数 | **501**（索引 0..499 = `d∈[0, 25.0)`；索引 500 = overflow，存 `d ≥ 25.0`） |
| 箱内格式 | 位图，`ceil(N/8)` 字节；第 `j` 相占 `byte j>>3` 的 `bit j&7`（低位先行） |
| 段大小 | `501 * ceil(N/8)` 字节（Inorg 77,500 相 → 501×9,688 = 4,853,688 B） |
| 写入规则 | 该相**最强 M=40 条**有效峰（`d>0`）各自置位（`bins_top_m` 记入 meta）；同相多峰落同箱只置一次 |

查询时对测量峰 d 取 `bin(d-tol_left) .. bin(d-tol_right)`，再并上 overflow 箱（当窗口上界 ≥ 25.0）。

**M 值的取舍（实测定档，勿随意改）**：位图段体积与 M 无关（每箱一张定长位图），
M 只影响"召回完整性 vs 池密度"。

| M | 13 试样 top-100 覆盖 | 说明 |
|---|---|---|
| 12 | 9/13 通过（最多漏 11 条） | 选择性好，但索引截断丢物相 |
| 100 | 覆盖率 99.6% 通过 → 预筛失效 | 无选择性 |
| **40（定档）** | **13/13 通过**（候选池 1500） | 40 = 打分层 `max_ref_peaks` 上限 |

`M ≥ max_ref_peaks` 时，"命中 ≥min_match 个测量峰" 是精确打分
"`n_matched_meas ≥ min_match`" 的**必要条件**（打分只取最强 40 条参考峰，
位图窗口又按 ±tol 展开），因此预筛候选集是精确结果的**超集** —— 这是
polyDB 敢用位图预筛的召回保证。

### 4.4 `elem.u8`（元素位图）

| 项 | 值 |
|---|---|
| 元素列表 | 固定 118 项（Z=1..118），`elem_index = Z-1` |
| 段大小 | `118 * ceil(N/8)` 字节 |
| 置位 | 该相化学式中出现该元素（按 `elements` 字段） |

用于"允许元素池 ⊆ 相元素集"的**位与**过滤：`mask = OR(elem[Z] for Z in allowed)`，不满足者剔除。

### 4.5 `sites.bin` / `sites_off.i64`（侧车）

每个位点 17 B：

| 字段 | 类型 | 字节 | 说明 |
|---|---|---|---|
| `Z` | uint8 | 1 | 原子序数（1..118） |
| `x`,`y`,`z` | float32 ×3 | 12 | 分数坐标（0..1） |
| `occ` | float32 | 4 | 占据数（0..1） |

`u_iso`、`label` 不入 v1（精修不依赖；需要时由 CIF 侧车提供）。
`sites_off` 长度 `N+1`，`sites_off[0]=0`，末元素 = `len(sites.bin)`。

### 4.6 `index.sqlite`

```sql
CREATE TABLE entries (
    eid          INTEGER PRIMARY KEY,   -- COD 原号（PCOD/TCOD 预留 +2e7/+1e8）
    formula      TEXT,                  -- 原化学式
    formula_red  TEXT,                  -- 约化化学式
    mineral      TEXT,
    space_group  TEXT,
    sg_number    INTEGER,
    elements     TEXT,                  -- "Al,C,H,O,P"
    a REAL, b REAL, c REAL,
    alpha REAL, beta REAL, gamma REAL,
    volume REAL, density REAL,
    z            INTEGER,               -- 化学式单位数
    n_peaks      INTEGER,               -- 有效峰数（≤K）
    tier         INTEGER DEFAULT 0,     -- 0=未分层 1=实验测定 2=理论/预测
    dup_group    INTEGER DEFAULT 0,     -- 同相复本组号（0=唯一）
    cif_rel      TEXT,                  -- 源 CIF 相对路径（可选，供追溯）
    src_mtime    INTEGER,
    row_idx      INTEGER                -- 数组段行号 (0..N-1), 与 eid 不同义
);
CREATE UNIQUE INDEX idx_entries_row ON entries(row_idx);   -- 必需: reader 双向查
CREATE INDEX idx_entries_formula ON entries(formula);
CREATE INDEX idx_entries_mineral ON entries(mineral);
CREATE INDEX idx_entries_dup ON entries(dup_group);
CREATE VIRTUAL TABLE entries_fts USING fts5(
    formula, mineral, content='entries', content_rowid='eid'
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
```

> `entries.eid` 是 `INTEGER PRIMARY KEY`（等价 rowid），**不是**数组行号；
> 数组行号一律走显式 `row_idx`（见 §3）。`meta` 表实际可以为空 —— 权威
> 元信息在 `meta.json`；`meta.json` 还会额外写 `total_bytes` 与
> `element_phase_counts`（元素规模展示用），属可选字段。

---

## 5. `meta.json`

```jsonc
{
  "format": "polyDB",
  "schema_version": 1,
  "variant": "cod-inorg",            // cod-inorg | cod-full
  "peak_convention": { ... },         // §2 全字段
  "counts": { "phases": 77500, "peaks": 5962013, "sites": 1005846, "k": 100 },
  "sections": {
    "peaks_d.f32": {"dtype": "float32", "shape": [77500, 100], "bytes": 31000000, "sha256": "..."},
    "peaks_i.u16": {"dtype": "uint16",  "shape": [77500, 100], "bytes": 15500000, "sha256": "..."},
    "bins.u8":     {"dtype": "uint8",   "shape": [501, 9688],  "bytes": 4853688,  "sha256": "..."},
    "elem.u8":     {"dtype": "uint8",   "shape": [118, 9688],  "bytes": 1143184,  "sha256": "..."},
    "sites.bin":   {"dtype": "raw",     "bytes": 17099382,     "sha256": "..."},
    "sites_off.i64": {"dtype": "int64", "shape": [77501],      "bytes": 620008,   "sha256": "..."},
    "index.sqlite": {"bytes": 19709952, "sha256": "..."}
  },
  "total_bytes": 89926214,
  "source": { "lib": "COD", "root": "D:/Project/XRD/PolyXRD-DataBase/COD",
              "manifest": "inorg_manifest.sqlite", "manifest_built_at": "2026-10-20 01:52:04",
              "n_manifest": 79198, "scope": "inorg" },
  "build": { "tool": "build_polydb.py", "tool_version": "1.0", "started_at": "...",
             "elapsed_s": 531.7, "workers": 8, "skipped": 1698,
             "skip_reasons": { "no_sites": 1065, "no_pattern": 336,
                               "volume_too_large": 179, "no_volume": 118 } },
  "element_phase_counts": { "O": 46511, "Si": 11853, "...": 0 }
}
```

> 上面是 2026-10-21 实测的 `COD-Inorg-20261021.polyDB` 真值（77,500 相 /
> 89.9 MB / 532 s）。`sites.bin` 实测 17,099,382 B ÷ 1,005,846 位点 =
> **精确 17 B/位点**，与 §4.5 一致。

**版本策略**：`schema_version` 变化 = 不兼容；新增可选段或可选列 = `schema_version` 不变，reader 必须容忍缺失段（向后兼容）。禁止改动既有段的语义与字节布局。

---

## 6. 检索流程（reader 契约）

```
ordered_candidates(measured_d, measured_i, tol, min_match) -> (rows, prefix_keys)
  1. 资格：bins 位图按测量峰累加 counts（uint16），保留 counts >= min_match
     （M=40 时该集合是精确结果的**超集**，见 §4.3）
  2. 元素过滤（若给定）用 elem 位图 AND
  3. 前置键分层：对每相 top-12 条峰**精确复刻**打分主键的前三个分量
       mh   = main_peak_match                  （与精确值完全相等）
       p5   = top_precision                    （与精确值完全相等）
       wrec = intensity_weighted_top_recall     （安全上界，重叠窗按并集算）
     排序键 = mh → p5 → wrec → counts（降序）
  4. 返回**不截断**的全序，交给检索入口自适应扩池
search_by_d_peaks(...)
  5. 先取前 max(limit*4, 3000) 行做精确打分（`_hanawalt_metric`）
  6. 若"下一行的前置键"严格小于当前第 limit 名的精确键 → 收工；
     否则把候选池翻倍再打分，直到安全或触顶（`_BOUND_CEIL`=12000；触顶会
     打 warning 日志，因为此时正确性只能靠经验而非证明）
fetch_peaks(row_idx)  -> (d float32[K], i float32[K])   # u16 解码
fetch_sites(row_idx)  -> [(Z, x, y, z, occ), ...]
```

⚠️ **第 3/6 步的两次翻车与定档（实现必须按现行版本）**：

| 做法 | 13 试样 top-100 覆盖 | 备注 |
|---|---|---|
| 按 `(counts, wsum)` 截断 800 | 9/13（漏 24~100 条） | 召回型指标偏爱峰多而密的物相 |
| 近似上界（最近测量峰 + 列命中数） | **12/13**（5-1 丢 3 条） | 2026-10-23 实测：上界并不成立，top-300 里 200~294 行的分量被低估（最大 0.375） |
| **精确前置键 + 自适应扩池（现行）** | 13/13，且逐条等于全量暴力结果 | 13 试样 × 77,500 相暴力比对 PASS（`search` top-100 == brute top-100） |

**三个必须精确的细节**（近似上界实现全踩过）：

1. `top_precision` 的分子是"**前 5 个去重峰里有几个被观察到**"（每条最多算 1），
   不是"被覆盖的测量峰个数"——两个测量峰落进同一参考峰容差窗时只能算 1。
2. `intensity_weighted_top_recall` 的分子是"被**全部** top-12 去重峰覆盖的测量峰
   强度权重和"（重叠窗按并集计权），不是只被前 5 条覆盖的那部分。
3. 贪心去重只与**已保留**项比较、容差取**候选自身**的 `_tol(d)`（不对称、`<=`、
   顺序敏感），与 `cif_database._dedupe_by_tol` 逐条一致。

**打分必须复用 `cif_database` 现有实现**（`_match_positions` / `_dedupe_by_tol` / `_interval_hit`），polyDB 只提供数据。

**实测耗时（COD-Inorg 77,500 相，默认寻峰 44~92 条测量峰）**：候选生成
0.29~0.34 s（77,000+ 行做精确前置键）＋ 精确打分 0.25~0.35 s ≈ **0.5~0.7 s/样本**；
旧 sqlite 链路 6.3~11 s。注意规范早期写的 0.1~0.3 s 是按 25 条测量峰估的，
实际默认寻峰会检出 44~92 条，耗时随测量峰数线性增长。

---

## 7. 建库与校验

| 环节 | 工具 | 说明 |
|---|---|---|
| 建库 | `PolyXRD-DataBase/tools/build_polydb.py` | 支持 `--scope inorg\|full`、`--workers`、`--limit`、断点续跑 |
| 校验 | `PolyXRD/scripts/polydb_verify.py` | 结构与校验和 + 抽样 200 相用 `fastxrd` 重算比对 |
| 精度判据 | d：`|Δ| ≤ 1e-4 Å`（f32 量化）；I：`|Δ| ≤ 0.05`（u16 量化） | 见 §4.1 / §4.2 |
