# tools/ 索引

2026-10-23 大幅收敛：**只保留 polyDB 最新格式链路**。旧 3COD `.sqlite` 单体库的构建、
验收、一次性诊断与报告生成脚本已成批删除（git 历史里仍可找回）；与 COD 官方同步相关
的脚本移入 [`sync/`](sync/README.md)，当前**停用**。

现在 `tools/` 一共 9 个 Python 脚本 + 2 份文档。

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

## B. 验收门禁

| 脚本 | 判据 |
|---|---|
| `verify_polydb.py` | polyDB 结构 32 项硬判据（段齐全/字节数/sha256/shape 自洽/sites_off 单调/`integrity_check`/`row_idx` 完整排列/抽样行序）—— **发布前必过** |
| `verify_data_root.py` | 数据根完整性：清单行数基线 + 每库抽样 250 个归档与副本，比对字节数 |
| `verify_inorg_copy.py` | `inorg_cif` 副本 vs 清单逐条一致（缺/多/尺寸不符三项须全 0） |
| `verify_coverage.py` | 源库 CIF / 无机副本 / 清单 三方对照（"有没有漏条目"） |

```bash
python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB
python tools/verify_data_root.py
```

## C. sync/ —— 与 COD 官方同步（停用）

见 [`sync/README.md`](sync/README.md)。10 个脚本，含清单抓取、补齐、对账。
**当前不参与构建**，也不会被任何构建脚本导入。

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
