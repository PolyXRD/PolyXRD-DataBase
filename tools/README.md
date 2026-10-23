# tools/ 索引

2026-10-23 大幅收敛：**只保留 polyDB 最新格式链路**。旧 3COD `.sqlite` 单体库的构建、
验收、一次性诊断与报告生成脚本已成批删除（git 历史里仍可找回）；同步与数据验收脚本
移出本仓库，落到数据根 `<数据根>/tools/`（同步部分当前**停用**）。

现在 `tools/` 一共 **6 个 Python 脚本 + 2 份文档**：构建链 5 个 + 产物验收 1 个。

## 数据根（重要）

源数据**不在本仓库**，统一在 `/D:/Project/XRD/sync-COD`（PolyXRD / XinMatch 两库共用）：

```
D:/Project/XRD/sync-COD/
├── COD/                    535,166 个 CIF（3 级布局 1/00/00/1000003.cif）
├── PCOD/                 1,061,962 个（2 级布局）
├── TCOD/                   362,293 个（3 级布局）
├── inorg_cif/{COD,PCOD,TCOD}/   无机子集副本，共 1,188,103 个
└── inorg_manifest.sqlite    逐条清单，1,959,421 行 / 289 MB
```

所有脚本用环境变量 `XRD_DATA_ROOT` 覆盖，缺省即上面这个路径。

## A. 构建主链

| 脚本 | 作用 |
|---|---|
| `scan_inorg.py` | ① 三库无机分类扫描 → 复制 `inorg_cif/` 副本 + 生成 `inorg_manifest.sqlite` |
| `build_polydb.py` | ② **主入口**。两阶段构建 `*.polyDB`（并行 unit → 串行合并），产物写到仓库内 `polydb/` |
| `cif_common.py` | 共用纯函数：`parse_elements` / `is_inorganic` / `cell_volume` / `list_dirs` / `formula_mass` |
| `fastcif.py` | 快速 CIF 解析 + 对称操作展开（不依赖 gemmi/pymatgen） |
| `fastxrd.py` | 峰位 d / 强度 I 计算（Cromer-Mann + LP + 多重性，无温度因子） |
| `_atomic_scattering_params.json`（仓库根） | `fastxrd.py` 读取的 Cromer-Mann 系数表，缺失时建库直接失败 |

```bash
python tools/scan_inorg.py --workers 6                # ① 仅在需要重建清单/副本时跑
python tools/build_polydb.py --scope inorg --workers 8
python tools/build_polydb.py --scope full  --workers 8
```

## B. 产物验收门禁

| 脚本 | 判据 |
|---|---|
| `verify_polydb.py` | polyDB 结构 32 项硬判据（段齐全/字节数/sha256/shape 自洽/sites_off 单调/`integrity_check`/`row_idx` 完整排列/抽样行序）—— **发布前必过** |

```bash
python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB
```

> **数据侧的验收不在这里**：清单行数基线、`inorg_cif` 副本一致性、三方覆盖度
> 三个脚本（`verify_data_root.py` / `verify_inorg_copy.py` / `verify_coverage.py`）
> 已随同步脚本一起迁到数据根 `<数据根>/tools/`，见
> [`sync-COD/tools/README.md`](../../sync-COD/tools/README.md)。
> 分界理由：它们验的是"数据本身"（会被两个仓库共用），
> 而 `verify_polydb.py` 验的是"本仓库的构建产物"。

## C. 同步与数据验收（已迁到数据根）

2026-10-23 把 13 个脚本移出本仓库，落到 `<数据根>/tools/`：

- 同步 10 个（`fetch_remote_inv` / `crawl_tcod_http` / `make_local_inv` / `cmp_inv` /
  `fetch_tcod_http` / `fetch_missing_tcod` / `audit_tcod_inv` / `diff_tcod_inv` /
  `verify_sync_tcod` / `probe_remote.sh`）—— **当前停用**
- 数据验收 3 个（`verify_data_root` / `verify_inorg_copy` / `verify_coverage`）

理由：这些脚本只操作数据（清单 / 副本 / 归档），不碰 polyDB；数据由两个仓库共用，
脚本跟着数据走才不会出现"两份代码各自漂移"。索引见该目录的 README。

## 已删除的东西（2026-10-23）

| 删掉的内容 | 原因 |
|---|---|
| `build_dbs.py` / `build_3cod.py` / `build_3cod_org.py` / `split_3cod.py` | 旧 3COD 单体 sqlite 构建机，格式已废弃 |
| `accept_3cod*.py` / `verify_complete.py` / `verify_dbs.py` / `dbstat_report.py` | 旧格式验收 |
| `report_*.py`（6 个） | 旧格式验收报告生成器 |
| `debug_* / bench_* / smoke_* / spotcheck_* / diff_* / classify_* / analyze_*` | 一次性诊断，结论已落在文档里 |
| `disk_audit.py` / `recycle_audit.py` | 硬编码已不存在的 E: 盘 |

有价值的**结论**保留在仓库文档里，不需要靠脚本重跑：
`docs/` 下的格式规范与 `COD有机无机判别评估报告.md`。

## 口径备忘（别搞错）

- polyDB：λ 1.5406、d ≥ 1.0、2θ 5–100.76°、**无** Debye-Waller、每相取强度前 100 条。
- xinDB（姊妹仓库）：d 0.7703–30 Å、**含** Debye-Waller、最多 150 条反射。
  **两个库强度体系不同，不能互校。**
