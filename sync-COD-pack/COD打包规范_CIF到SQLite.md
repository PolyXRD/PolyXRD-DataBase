# COD CIF → SQLite 打包规范（PolyXRD / XinMatch 双项目通用外挂版）

> 目标：从 **COD 官方 CIF 集合** 重新打包出 **COD-Full** 与 **COD-Inorg** 两个 SQLite 库，
> 使同一份文件能被 **PolyXRD** 和 **XinMatch** 两个项目**直接外挂使用**（零代码改动）。
> 本文所有结论均基于对两项目现有数据库的实测内省（2026-10-13），非文档转述。

---

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| 现状能否直接挂载？ | **不能**。两项目 schema 完全不同（见 §1），XinMatch 的 `multi_db.open_library()` 只接受 XinMatch-schema 连接 |
| 推荐方案 | **单文件双 schema（Dual-Schema）**：一个 `.sqlite` 内同时含两套表，两项目各读各的表，互不干扰（§2） |
| 峰口径 | 两套表**分表存放**，可用同一份 gemmi 计算结果双写，无需 pymatgen（§5） |
| 代码改动 | 两项目**均零改动**；只需一个新构建脚本（独立工具，不动现有代码）+ 把产物放到约定路径（§7） |

---

## 1. 为什么现状不能直接挂载（实测对比）

| 维度 | PolyXRD `COD_inorganics.sqlite`（1.25 GB） | PolyXRD `cod_index.sqlite`（452 MB） | XinMatch `cod_inorganics.db`（537 MB） |
|---|---|---|---|
| 主表 | `phases`（71,199 行） | `cod_entries`（113,223 行） | `entries`（71,206 行） |
| 峰存储 | `peaks_d`/`peaks_i` **CSV 字符串**（d 降序，强度归一到 max=1000）+ `peaks_top_d`/`peaks_top_i` **BLOB**（top-64，float64 小端裸字节，512 B） | **无峰表** | `peaks` **行表**（6,214,072 行：entry_id, d, intensity, h, k, l） |
| 元素索引 | 无（运行时从 `formula` 文本解析） | `elements` 文本列 | `elements` 行表 + `element_combo` 预计算哈希表 |
| 主键/ID | `cod_id` INTEGER PK + `ref_id`/`display_id`（如 `96-100-0005`） | `cod_id` + `file` | `entry_id` TEXT PK（如 `96-100-0005`） |
| 原子位点 | `cod_atomic_sites`（311,126 行，无 u_iso） | `cod_atomic_sites`（5,135,262 行，**含 u_iso**） | 无 |

XinMatch 对 PolyXRD 格式库的既有做法是**转换/侧车**（`tools/build_cod_xinmatch.py`、`pdf2_index.py`、`build_cod_full_xinmatch.py`），从无"原地挂载"路径——这就是必须重新打包的原因。

---

## 2. 方案：单文件双 schema

每个产物文件同时包含两套表，**两项目各读各的表、互相看不见对方**（SQLite 多表共存，无命名冲突）：

```
COD-Inorg.sqlite（双 schema）
├─ XinMatch 侧：entries / peaks / elements / element_combo   ← XinMatch 检索只读这些
└─ PolyXRD 侧：phases / cod_atomic_sites / meta              ← PolyXRD 检索只读这些

COD-Full.sqlite（双 schema）
├─ XinMatch 侧：entries / peaks / elements / element_combo
└─ PolyXRD 侧：cod_entries / cod_atomic_sites / meta         ← 全库无峰表（PolyXRD 全库定位为结构/成分检索，不做粉末检索）
```

**收益**：一份数据、两个项目、四个挂载路径（§7）；峰表分存后两边强度口径互不传染（§5）。

---

## 3. 输入约定（COD 官方 CIF 集合）

| 项 | 规范 |
|---|---|
| 目录布局 | `{id首位}/{id[1:3]}/{id[3:5]}/{id:07d}.cif`，如 `1000005` → `1/00/00/1000005.cif`（XinMatch `cif_store.cod_cif_path` 已实测固化的布局，与 COD 官方归档一致） |
| cod_id | CIF 文件名的数值部分（7 位零填充） |
| entry_id / ref_id / display_id | **三处同一值**：`96-{前3位}-{后4位}`，如 cod_id `1000005` → `96-100-0005`（PolyXRD `ref_id` 与 XinMatch `entry_id` 格式本就一致，可直接对齐） |
| 解析器 | `gemmi.read_small_structure()`（两项目都已依赖 gemmi；**不需要 pymatgen**，见 §5） |
| formula | 必须取 `_chemical_formula_sum` 归一化值。⚠️ 实测 PolyXRD 历史库有 605 条 formula 被误写成空间群符号（如 `P 63 m c`），会导致元素过滤误杀——打包时禁止此形态，空则留空 |
| 晶胞 | 优先 `_cell_length_a..c` / `_cell_angle_*`；`volume` 由 gemmi 重算；缺失留 NULL（勿填 0） |
| elements | 从 formula 解析出的元素符号集合，存为逗号分隔文本（`"Ca,C,O"`） |

---

## 4. 输出 schema 规范（逐表逐列）

### 4.1 XinMatch 侧（DDL 以 `xinmatch/core/db/schema.sql` 为准）

```sql
entries(entry_id TEXT PK, formula, mineral_name, space_group, crystal_system,
        a,b,c,alpha,beta,gamma REAL, volume REAL, density, color, year INT,
        author, journal, quality, elements TEXT)      -- elements 逗号分隔
peaks(entry_id TEXT, d REAL, intensity REAL, h INT, k INT, l INT)
elements(entry_id, element, PK(entry_id, element))
element_combo(element_set_hash TEXT PK, entry_ids TEXT)  -- entry_ids 以 \n 连接
```

- **element_combo 哈希**：`sha1(",".join(sorted(elements)).encode())[:16]`（16 位十六进制）。
- **mineral_name**：纯数字或空则置空（COD 的 mineral 字段常是数字编号）。
- **crystal_system**：当前两项目构建器均不填（可空）；如需填须由 space_group 推导，勿猜。
- **索引（必须建，与 schema.sql 一致）**：
  `idx_elements_element_entry`、`idx_peaks_d`、`idx_peaks_entry_id`、
  `idx_entries_formula/space_group/crystal_system/year/mineral_name/author/journal`。

### 4.2 PolyXRD 侧 — COD-Inorg 用 `phases` 表

```sql
phases(cod_id INTEGER PK, formula TEXT, space_group TEXT,
       cell_a,cell_b,cell_c,cell_alpha,cell_beta,cell_gamma REAL,
       n_peaks INTEGER, peaks_d TEXT, peaks_i TEXT,      -- CSV，d 降序
       record_offset INTEGER, record_size INTEGER,        -- 可置 NULL
       ref_id TEXT, display_id TEXT,                      -- 同 entry_id
       peaks_top_d BLOB, peaks_top_i BLOB,                -- top-64，float64 小端裸字节
       cif_gz BLOB)                                       -- 可选，见 §9
```

- `peaks_d`/`peaks_i`：`,` 连接，**按 d 降序**（PolyXRD 实测口径；XinMatch 随包库同源数据亦此序）。
- `peaks_top_*`：各条目**最强 64 条**，按强度降序，`np.asarray(v, dtype='<f8').tobytes()` 直接存裸字节（读取端 `_parse_float_csv` 对 bytes 走 `np.frombuffer` 零拷贝；CSV 文本也兼容，但推荐 BLOB）。
- **索引（必须建，实测现有库同款）**：`idx_phases_formula`、`idx_phases_sg`、`idx_phases_display_id`、`idx_phases_match_ref`、`idx_sites_cod_id`。
- `cod_atomic_sites(cod_id, site_idx, label, element, x, y, z, occupancy)`，PK(cod_id, site_idx)；COD-Inorg **不含 u_iso**。

### 4.3 PolyXRD 侧 — COD-Full 用 `cod_entries` 表

```sql
cod_entries(cod_id INTEGER PK, file TEXT, mineral_name, formula, formula_red,
            elements TEXT, space_group, space_group_number INT,
            a,b,c,alpha,beta,gamma,volume REAL, z_value INT,
            last_updated INT, parse_ok INT, cif_gz BLOB)
```

- `parse_ok=1` 是有效行标记（XinMatch 全库构建即以 `WHERE parse_ok=1` 取数）。
- **索引**：`idx_formula_red`、`idx_elements`、`idx_sg_number`、`idx_sg_name`、`idx_volume`、`idx_parse_ok`、`idx_name_fts`、`idx_cif_file`、`idx_sites_cod_id`。
- `cod_atomic_sites` 全库版**含 `u_iso` 列**。

### 4.4 `meta` 表（两项目都读，缺失时 PolyXRD 会自动补默认值，但建议显式写入）

| key | COD-Inorg | COD-Full |
|---|---|---|
| `schema_version` | `2` | `1` |
| `entry_count` | 实际 phases 行数 | 实际 cod_entries 行数 |
| `build_time` | ISO 时间戳 | Unix 时间戳（`last_build_time`） |
| `cif_source` / `tar_source` | CIF 归档路径 | 源 tar/归档路径 |
| `cif_embedded` / `cif_missing` | 内嵌/缺失条数（不内嵌则 0 / 全部） | 同 |
| `atomic_sites_rows` | 实际行数 | — |

---

## 5. 峰计算法则（最关键的一致性口径）

| 参数 | XinMatch 现行口径 | PolyXRD 现行口径（实测） | **打包建议** |
|---|---|---|---|
| 波长 | Cu Kα1 **1.5406 Å** | **1.5406 Å** | 1.5406（两边本就一致） |
| 反射枚举 | gemmi `ReciprocalAsu`（不对称单元去重） | pymatgen 自动展开对称操作 | gemmi ASU（打包机只需 gemmi） |
| 强度 | `StructureFactorCalculatorX` 的 \|F\|² | pymatgen XRDCalculator | gemmi \|F\|² |
| LP 因子 | 未极化 `(1+cos²2θ)/(sin²θ·cosθ)` | pymatgen 内置（同式） | 未极化式，显式写进脚本 |
| 截断 | d ≥ **1.0 Å** | 2θ ∈ **[5°, 90°]**（≈d≥0.99 Å） | **统一 d ≥ 1.0 Å**（差异 <1%，避免跨库行为不一致） |
| 条数 | 最强 **100** 条/条目 | 全量（实测最多 500+）+ top-64 预截断列 | XinMatch 表存 top-100；PolyXRD 表存全量 CSV + top-64 BLOB |
| **强度归一化** | 随包无机库实测 **max=1000**（继承 PolyXRD 数据）；CIF 直构的 cod_full 为**原始 \|F\|²·LP** | **max=1000**（实测三张卡全为 1000.00） | **统一归一到 max=1000**。XinMatch 的 `FoM=exp(−Rwp/σ)` 虽对标量不变，但统一口径可保证跨库阈值/对比行为一致 |
| 排序 | peaks 行按**强度降序**插入 | CSV 按 **d 降序**；top-64 按强度降序 | 按上表分表各自排序 |
| hkl | `peaks.h/k/l`（当前随包库未填；`compute_peaks_from_cif(return_hkl=True)` 可回填） | phases 表不存 hkl | **建议回填 3-index hkl**（XinMatch 新的 March-Dollase 择优取向拟合依赖 `peaks.h/k/l`，见 HANDOVER §5.2）；六方晶系存 3-index（schema 仅三列） |

> **核心结论**：双 schema 分表存放后，**同一份 gemmi 计算结果可同时双写两边**（序列化成 CSV/BLOB 给 PolyXRD、展开成行给 XinMatch），打包机无需安装 pymatgen，也不必强行统一两家的历史算法。

---

## 6. 构建流程（推荐步骤）

1. **扫描 CIF 归档** → 逐条 `gemmi.read_small_structure`；`cell`/`spacegroup` 缺失 → 记入跳过名单（不致命）。
2. **峰计算**（§5 口径）→ `(d, I, hkl)`，I 归一到 max=1000，取 top-100。
3. **双写**（建议单事务域批量提交，batch 200–5000）：
   - XinMatch 四表（`insert_entries` + `build_element_index` 语义）；
   - PolyXRD `phases`/`cod_entries` + `cod_atomic_sites`（从 CIF 原子位点展开，`occupancy` 缺失填 1.0）。
4. **建索引 + `ANALYZE`**（生成 `sqlite_stat1`，两项目的查询计划都依赖它）。
5. **外挂友好化**：`PRAGMA journal_mode=DELETE;` → `VACUUM;`
   （⚠️ 实测 `cod_index.sqlite` 现为 **WAL** 模式且带活动的 `-shm`；只读外挂目录下 WAL 库可能无法打开，**必须转为 DELETE 模式或删除 -wal/-shm 后再分发**。XinMatch 三个库均为 delete 模式。）
6. **落位 + 验收**（§7、§8）。

辅助能力（可选）：`build_progress` 水位表支持断点续跑（全量约 2 小时级，务必可 `--resume`）。

---

## 7. 挂载方式（两项目，零代码改动）

| 项目 | 库 | 放置路径 | 生效方式 |
|---|---|---|---|
| XinMatch | COD-Inorg | `<repo>/data/cod_inorganics.db` | 默认随包库，启动即挂载 |
| XinMatch | COD-Full | `<repo>/data/cod_full.db` | `cod_full` 注册库（GUI「设置→参考数据库」或默认配置） |
| PolyXRD | COD-Inorg | `<repo>/cod_data/COD_inorganics.sqlite` | 默认路径（`config.cod_db_path`） |
| PolyXRD | COD-Full | `<repo>/cod_data/cod_index.sqlite` | 默认路径（GUI 可改用户库路径） |

- 也可以用**符号链接/同一文件**指向同一份双 schema 产物，避免双份磁盘。
- 只读外挂：目录无写权限时 DELETE 模式可直接 `mode=ro` 打开（XinMatch 即以 `mode=ro + query_only` 打开）。
- PolyXRD 读取源库期间**确认无进程占用**（本次实测 `cod_index.sqlite-shm` 23:28 仍被 touched，说明有进程在线）。

---

## 8. 验收清单（Checklist）

- [ ] **条目数对齐**：Inorg phases ≈ 71,199 / entries ≈ 71,206（以随包库实测为基线）；Full cod_entries = 113,223 / entries ≈ 112,734；`element_combo` 组数万级。
- [ ] **峰行数**：Inorg peaks ≈ 6.21 M 行（100 条/条目）；Full peaks = entries×≤100。
- [ ] **ID 三方一致**：抽 20 条，`entry_id == ref_id == display_id == "96-"+cod_id`。
- [ ] **峰位抽检**：石英（SiO₂）最强线 ≈ 3.34 Å、方解石 ≈ 3.04 Å、刚玉 ≈ 2.55 Å；另抽 5 条与 CIF 重算值逐一对照（d 偏差 < 0.001 Å）。
- [ ] **强度口径**：每卡 `MAX(intensity)=1000.0`（或明确记录为原始口径）。
- [ ] **元素索引**：抽 10 条，`elements` 行集合 == formula 解析集合；`element_combo` 哈希可复现（sha1 前 16 位）。
- [ ] **top-64 BLOB**：`len(peaks_top_d)=512` 字节 = 64×float64；与全量 CSV 的最强 64 条一致。
- [ ] **两项目实开**：XinMatch 检索冒烟（`search_match` 对石英谱 Top-1 命中）；PolyXRD 打开库后按 formula/元素过滤有结果。
- [ ] **性能**：`ANALYZE` 已执行；XinMatch 71k 库单次峰列表检索秒级（~8.7s 为已知基线）。
- [ ] **外挂稳健**：文件为 DELETE journal 模式、无残留 `-wal/-shm`、UTF-8、page_size 4096。

---

## 9. 体积与性能建议

| 决策 | 建议 | 理由 |
|---|---|---|
| `cif_gz` 内嵌 | **不内嵌**（默认） | 内嵌会使 Inorg 库从 ~0.8 GB 涨到 ~1.3 GB；两项目均可回落外部 CIF 归档（XinMatch `cod/cif/`，PolyXRD `cod_data/cif_db`）。若目标部署无归档，再内嵌 |
| page_size | 4096（默认） | 与现有两项目库一致 |
| 预截断列 | 保留 `peaks_top_*` | PolyXRD 检索在 `max_ref_peaks ≤ 64` 时只读这两列，省约 85% 解析（其代码注释实测结论） |
| 原子位点 | Inorg 全量保留（311k 行） | PolyXRD 结构视图/PO 判据需要 |
| hkl 回填 | **做** | XinMatch  March-Dollase 择优取向（`march_po`）要求 `peaks.h/k/l` 非空；一次性回填，后续检索直接受益 |

---

## 10. 合规与许可

- COD CIF 数据遵循 COD 公开许可，随库分发时保留来源说明（`meta.cif_source`）。
- **PDF-2 2004 不在本规范内**：ICDD 商业授权数据，禁止随包再分发；如需挂载走 XinMatch 侧车索引机制（`docs/COD多库挂载说明.md` §4）。
- 两项目均为**双许可（学术 + 商业）**，数据库产物按同一授权分发。

---

## 附：关键常量速查

```
波长            λ = 1.5406 Å (Cu Kα1)
LP(未极化)      (1 + cos²2θ) / (sin²2θ · cos2θ)
d 截断          d ≥ 1.0 Å
条数            XinMatch top-100；PolyXRD 全量 + top-64
强度归一化      max = 1000
entry_id        96-XXX-XXXX  (cod_id zfill(7)，前3-后4)
combo 哈希      sha1(",".join(sorted(elements)))[:16]
top-64 BLOB     np.asarray(v, dtype='<f8').tobytes()  # 小端裸字节
CIF 布局        {d}/{XX}/{XX}/{id:07d}.cif
journal         DELETE（外挂强制）
```
