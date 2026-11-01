# TCOD / PCOD polyDB 构建与验收报告（20261020 期）

> 日期：2026-10-31　构建器：`tools/build_polydb.py`（`--lib` 泛化版）
> 格式：`docs/外挂库格式规范-polyDB-v4.md`（schema_version = 1，未改任何段字节布局）
> 源数据：`D:/Project/XRD/sync-COD`（清单 `inorg_manifest.sqlite` built_at 2026-10-20 01:52:04）

## 1. 结论

三个库全部构建完成并通过**三重验收**（结构 32 项 / 精度抽样 200 相 / 消费侧真实 reader），
无 FAIL、无 WARN。产物在 `polydb/`，已打 zip 并发布到 Release `20261020`。

| 库 | 相数 | 峰数 | 位点数 | 体积 | manifest | 跳过 | 耗时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `TCOD-Inorg-20261020.polyDB` | 46,541 | 3,767,731 | 754,606 | 52.6 MiB | 46,943 | 402（0.86%） | 247 s |
| `TCOD-Full-20261020.polyDB` | 359,307 | 35,039,291 | 22,178,424 | 681.6 MiB | 362,293 | 2,986（0.83%） | 6,259 s |
| `PCOD-Inorg-20261020.polyDB` | 1,061,817 | 106,160,732 | 32,522,180 | 1,413.0 MiB | 1,061,962 | 145（0.014%） | 8,208 s |

### 1.1 发布资产（Release `20261020`）

| 资产 | 字节数 | SHA-256 |
|---|---:|---|
| `TCOD-Inorg-20261020.polyDB.zip` | 33,054,486（31.5 MiB） | `783bc4f68e59c317a14a75b9dd99d27111a5fa27aba30d149479d7ffdccc4ead` |
| `TCOD-Full-20261020.polyDB.zip` | 489,220,264（466.6 MiB） | `81ae572ffff3547f2248395e2613b7aa6c31e284329fa75e11f86664fb56ab47` |
| `PCOD-Inorg-20261020.polyDB.zip` | 982,429,739（936.9 MiB） | `898dc822da90d54f8d7f1e4d4e1a04db8f809f926777b36047b2e153dd89310f` |
| `SHA256SUMS.txt` | — | 上述三条汇总 |

打包用 7-Zip 26.03（`-tzip -mx=5 -mmt=4`），zip 内条目用**正斜杠**路径、
顶层为同名 `.polyDB` 目录（已用 Python `zipfile` 逐个核对 9 个条目，无反斜杠）。
压缩率 60%~68%（`peaks_d.f32` 是 float32，可压缩性有限；`index.sqlite` 与位图段压缩明显）。

**解压回环验收**：把 `TCOD-Inorg-20261020.polyDB.zip` 解到临时目录后重跑 `verify_polydb.py`
→ 32/32 PASS，证明 zip 载荷与构建产物逐字节一致、解压即可挂载。

**没有 `PCOD-Full`**：清单里 PCOD 的 1,061,962 条 `is_inorg` 全为 1（GRINSP 预测集本身
不含有机相），建出来会与 `PCOD-Inorg` 逐字节相同，按确认只出 `PCOD-Inorg` 一份。

## 2. 峰口径（三库与 COD 完全一致，未改）

λ = 1.5406 Å（Cu Kα1）、d ≥ 1.0 Å、2θ 5.0–100.76°、等价反射按 2θ 合并、强度归一到 1000、
**无 Debye-Waller**、每相按强度取前 K = 100 条、`bins_top_m` = 40、`quant_i = u16/65535*1000`。

三库 `meta.json.peak_convention` 逐字段核对一致；`variant` 分别为
`tcod-inorg` / `tcod-full` / `pcod-inorg`（命名规则见规范 §5.1）。

## 3. 验收明细

### 3.1 结构层 `tools/verify_polydb.py`（32 项硬判据）

三库均 **32 PASS / 0 FAIL / 0 WARN**。覆盖：8 段齐全、段字节数与 sha256 与 meta 记录一致、
`peaks_d = N*K*4`、`peaks_i = N*K*2`、`bins = 501*ceil(N/8)`、`elem = 118*ceil(N/8)`、
`sites_off = (N+1)*8` 且单调、`sites.bin` 被 17 整除、`integrity_check = ok`、
`entries` 行数 == N、`row_idx` 是 0..N-1 的完整唯一排列（§3 铁律：≠ eid-1）、
抽样 64 相行内 I 降序且空槽在尾部。

### 3.2 精度层 `PolyXRD/scripts/polydb_verify.py`（L1+L2+L3，抽样 200 相）

| 库 | 抽样回算相数 | max ǀΔdǀ（容差 1e-4 Å） | max ǀΔIǀ（容差 0.05） |
|---|---:|---:|---:|
| `TCOD-Inorg` | 200 | 7.94e-7 | 0.00762 |
| `TCOD-Full` | 200 | 9.49e-7 | 0.00761 |
| `PCOD-Inorg` | 200 | 9.08e-7 | 0.00763 |

均远在容差内，说明 `peaks_d.f32` / `peaks_i.u16` 的量化误差就是全部误差来源，
峰计算与源 CIF 完全一致。L2 层（`bins.u8` / `elem.u8` 由 d 矩阵与 `elements` 字段重算复现）
三库比对全等。

> 该脚本原先在 L3 层把源目录写死为 `<数据根>/COD`，已改为按 `meta.source.lib` 解析
> （缺字段回退 COD，对既有 COD 库仍然兼容）。否则 PCOD/TCOD 库会一律报"CIF 缺失"。

### 3.3 消费侧 `PolyXRD.services.polydb.PolyDatabase`（真实 reader）

每库都用项目里的真实 reader 打开，检查 `available/is_ready`、`stats()`、
`get_phase()`、`get_atomic_sites()`、`search_by_d_peaks()`、`search_entries()`（FTS5）、
`elements_allowed` 元素过滤，全部正常。

自召回（把库内相自己的峰当作测量峰检索，`limit=10`）：

| 库 | hit@1 | hit@5 | 单次检索耗时 |
|---|---:|---:|---:|
| `TCOD-Inorg` | 3/5 | 4/5 | 0.35 s |
| `TCOD-Full` | 3/5 | 4/5 | 1.3 s |
| `PCOD-Inorg` | 5/5 | 5/5 | 3.4 s |
| 对照：`COD-Inorg-20261021`（已发布） | 3/5 | 4/5 | 0.36 s |

TCOD 两库与已发布 COD-Inorg 的自召回率**完全相同**，说明未命中案例来自打分口径
（用全部 100 条库内峰当测量峰时的 Hanawalt 主峰匹配特性），不是数据缺陷。
PCOD 更高是因为 GRINSP 预测集同构相极多、峰位几乎重合，自检索必然先命中自己。

检索耗时随相数线性增长：77k → 0.36 s、359k → 1.3 s、1.06M → 3.4 s，与规范 §6 的预期一致。

## 4. 数据构成

| 项 | TCOD-Inorg | TCOD-Full | PCOD-Inorg |
|---|---:|---:|---:|
| 元素种类 | 91 | 91 | **19** |
| eid 范围 | 110,000,001–140,354,736 | 110,000,001–140,354,755 | 21,000,000–29,585,139 |
| 每相峰数 min/avg/max | 2 / 81.0 / 100 | 2 / 97.5 / 100 | 12 / 100.0 / 100 |
| 元素前三（相数） | O 25,372 / N 6,977 / S 6,809 | C 319,380 / H 317,258 / O 263,412 | O 1,042,665 / Si 954,474 / P 44,267 |

- PCOD 只有 **19 种元素**、O 与 Si 压倒性占比，是 GRINSP 预测集（硅酸盐/磷酸盐为主）
  的客观构成，与 xinDB 侧 PCOD 统计（同为 19 种）吻合，不是丢数据。
- TCOD-Full 的 C/H 各约 32 万相，正是"Full 比 Inorg 多出来的部分"（有机/金属有机）。
- `eid` 已按库偏移：COD +0 / PCOD +2e7 / TCOD +1e8，与清单、xinDB 完全一致，
  三库可共存于同一配置而不撞号。

## 5. 跳过原因（全部可分类，守恒已核）

守恒检查三库均通过：`manifest == 入库 + 跳过`。

| 库 | no_volume | volume_too_large | no_sites | no_pattern | 合计 |
|---|---:|---:|---:|---:|---:|
| TCOD-Inorg | 272 | 81 | 48 | 1 | 402 |
| TCOD-Full | 717 | 893 | 150 | 1,226 | 2,986 |
| PCOD-Inorg | 110 | 1 | 1 | 33 | 145 |

- `no_volume`：CIF 里没有可解析的晶胞（TCOD 有大量只有粉末数据、无结构的条目）。
- `volume_too_large`：晶胞体积 > 30,000 Å³，峰计算代价不可控，与 COD 建库同一阈值。
- `no_pattern`：展开位点后仍算不出峰（空位点/超胞失败）。

## 6. 构建侧改动（本次为建三库新增，COD 行为不变）

| 文件 | 改动 |
|---|---|
| `tools/build_polydb.py` | 新增 `--lib COD\|PCOD\|TCOD`（缺省 COD，行为逐字节不变）、`--stamp`、`--max-skip-ratio`（默认 0.20，超限拒绝出库）；源目录按 `<数据根>/<LIB>/` 取；`variant = <lib>-<scope>`；parts 目录按 variant 隔离；worker 用 `initargs` 传源目录（Windows spawn 不继承父进程全局变量） |
| `PolyXRD/scripts/polydb_verify.py` | L3 精度层源目录改为按 `meta.source.lib` 解析（缺字段回退 COD） |
| `docs/外挂库格式规范-polyDB-v4.md` | 新增 §5.1 `variant` 命名与"必须逐库唯一"的约束 |
| `tools/README.md` | 补 `--lib` / `--stamp` / `--max-skip-ratio` 用法表 |

`--max-skip-ratio` 这道闸不是形式主义：散射因子表（`_atomic_scattering_params.json`）缺失时，
worker 会把每个文件的异常吞掉，流程照常跑完、写出一个 0 相的空壳库。超限即拒绝出库，
比事后发现"库是空的"便宜得多。

## 7. 复现命令

```bash
cd D:/Project/XRD/PolyXRD-DataBase/tools
python build_polydb.py --lib TCOD --scope inorg --stamp 20261020 --workers 4
python build_polydb.py --lib TCOD --scope full  --stamp 20261020 --workers 4
python build_polydb.py --lib PCOD --scope inorg --stamp 20261020 --workers 4

# 验收
python verify_polydb.py ../polydb/TCOD-Inorg-20261020.polyDB
python D:/Project/XRD/PolyXRD/scripts/polydb_verify.py ../polydb/TCOD-Inorg-20261020.polyDB --sample 200
```

parts 缓存保留在 `_polydb_parts/{tcod-inorg,tcod-full,pcod-inorg}`（共 2.2 GiB），
改 `bins_top_m` 或重跑 merge 时可直接复用；确认无误后可整体删除。

## 8. 在 PolyXRD 里挂载

PolyXRD v4.x 的内置槽位只登记 `cod-inorg` / `cod-full`，本次**未改软件侧代码**
（按确认走自定义挂载）。在「数据库挂载」面板按目录添加，`kind` 会自动识别为 `polydb`：

```
D:/Project/XRD/PolyXRD-DataBase/polydb/TCOD-Inorg-20261020.polyDB
D:/Project/XRD/PolyXRD-DataBase/polydb/TCOD-Full-20261020.polyDB
D:/Project/XRD/PolyXRD-DataBase/polydb/PCOD-Inorg-20261020.polyDB
```

三库 `variant` 互不相同，不会被自动发现逻辑误当成默认 COD-Inorg 顶上。
