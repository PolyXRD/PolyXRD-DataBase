# sync-COD 打包工具包（COD CIF → 双项目可用 SQLite）

本文件夹是**自包含**的打包参考包，随 COD 官方 CIF 集合一起同步到干净电脑。
目标：在这台没有 PolyXRD / XinMatch 源码的机器上，一个 agent 依据本包
即可写出构建脚本，产出**两个项目都能直接外挂**的数据库：

- `COD-Inorg.sqlite`（双 schema：XinMatch `entries/peaks/elements/element_combo`
  + PolyXRD `phases/cod_atomic_sites/meta`）
- `COD-Full.sqlite`（双 schema：XinMatch 四表 + PolyXRD `cod_entries/cod_atomic_sites/meta`）

## 目录结构

```
sync-COD/
├── README.md                        ← 本文件（导航 + 执行路径）
├── COD打包规范_CIF到SQLite.md        ← ★ 规范正文（唯一权威，先读它）
└── reference/                       ← 参考代码（只读材料，原样拷贝，勿改）
    ├── xinmatch/
    │   ├── schema.sql               ← XinMatch 四表权威 DDL（xinmatch/core/db/schema.sql）
    │   ├── schema.py                ← create_tables / enable_wal / table_exists
    │   ├── db___init__.py           ← 包导出（build_element_index/create_tables/insert_entries）
    │   ├── db_build_cod.py          ← insert_entries + _entry_row：entries/peaks/elements 写入语义
    │   ├── db_index_build.py        ← build_element_index + element_combo 哈希算法（sha1 前 16 位）
    │   ├── model_entry.py           ← Entry / CellParams 数据模型（xinmatch/core/model/entry.py）
    │   ├── cif_store.py             ← cod_cif_path：CIF 四级目录布局 {d}/{XX}/{XX}/{id:07d}.cif
    │   └── build_cod_full_xinmatch.py ← ★ CIF→峰全算法（gemmi）+ entry_id 约定 + 批量/断点续跑
    └── polyxrd/
        ├── phases_schema.sql        ← PolyXRD COD-Inorg 侧 DDL（实测自线上库，含 4 个索引）
        ├── cod_full_schema.sql      ← PolyXRD COD-Full 侧 DDL（cod_local.py _SCHEMA_SQL 逐字）
        ├── runtime_contract_摘录.md  ← 运行时契约摘录（加载优先级/has_cif/top-64 BLOB/回退链）
        └── regenerate_reference_db_peaks.py ← PolyXRD 峰口径参照脚本（pymatgen；六方 4-index）
```

## 执行路径（写构建脚本的顺序）

**前置**：Python ≥3.10 + `gemmi` + `numpy`（**不需要 pymatgen、不需要两个项目的源码**）。

1. **读规范** `COD打包规范_CIF到SQLite.md`（§0 结论 → §3 输入约定 → §4 schema → §5 峰口径 → §6 流程 → §8 验收）。
2. **峰计算**：照抄 `reference/xinmatch/build_cod_full_xinmatch.py` 的
   `compute_peaks_from_cif()`（gemmi `ReciprocalAsu` + `StructureFactorCalculatorX`，
   LP 未极化 `(1+cos²2θ)/(sin²θ·cosθ)`，λ=1.5406，d≥1.0 Å，top-100，
   强度归一到 max=1000）。加 `return_hkl=True` 拿 hkl（填 XinMatch `peaks.h/k/l`）。
3. **entry_id**：`_entry_id_for_cod()` 同款——`96-{cod_id前3位}-{后4位}`（cod_id zfill(7)）。
4. **XinMatch 侧写入**：`reference/xinmatch/schema.sql` 建表 →
   按 `db_build_cod.py::insert_entries` 的列序写 `entries/peaks/elements` →
   `db_index_build.py::build_element_index` 建 `elements/element_combo`。
5. **PolyXRD 侧写入**：`reference/polyxrd/phases_schema.sql`（Inorg）/
   `cod_full_schema.sql`（Full）建表；同一份峰数据序列化两次——
   CSV 文本（d 降序）填 `peaks_d/peaks_i`，top-64 float64 小端裸字节填
   `peaks_top_d/peaks_top_i`（见 `runtime_contract_摘录.md` §3）；
   `cif_gz` **恒 NULL**；原子位点写 `cod_atomic_sites`（ occupancy 缺失填 1.0）。
6. **meta**：按规范 §4.4 写键；**不内嵌 cif_gz 时必须写
   `variant`（值以 `slim-index` 开头）+ `cif_embedded='0'`**，
   否则 PolyXRD 检索被 has_cif 过滤清空（摘录 §2）。
7. **收尾**：建索引 → `ANALYZE` → `PRAGMA journal_mode=DELETE` → `VACUUM`
   → `integrity_check`（规范 §6 第 4-5 步）。
8. **验收**：按规范 §8 清单逐项过（条目数/峰行数/ID 一致/峰位抽检/强度口径/
   两项目实开冒烟/体积/journal 模式）。
9. **落位**（规范 §7）：产物改名/软链到
   - XinMatch：`data/cod_inorganics.db` + `data/cod_full.db`
   - PolyXRD：`cod_data/COD_inorganics.sqlite` + `cod_data/cod_index.sqlite`

## 注意

- `reference/` 是**只读参考**，不要修改；它是两项目源码的原样拷贝/摘录，
  在干净环境里**不可直接运行**（import 路径已断），只用于照抄算法与 DDL。
- 构建脚本写在 `sync-COD/` 本地（新文件，不动任何现有代码）。
- 规范与参考代码冲突时**以规范正文为准**，并在规范里记录差异。
- PDF-2 2004 不在范围内（ICDD 商业授权，禁止随包再分发）。
