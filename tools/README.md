# tools/ 索引

历史上所有构建/同步/验收脚本都留在这里（约 100 个，纯 Python + numpy），
以免"能跑但找不到"。**日常只需关心第一组**，其余是数据同步、旧格式打包与一次性诊断。

## A. polyDB 构建主线（现行，对应 Release 20261021）

| 脚本 | 作用 |
|---|---|
| `build_polydb.py` | **主入口**。两阶段构建 `*.polyDB` 目录容器（并行 unit → 串行合并） |
| `fastcif.py` | 快速 CIF 解析 + 对称操作展开（不依赖 gemmi/pymatgen） |
| `fastxrd.py` | 峰位 d / 强度 I 计算（Cromer-Mann + LP + 多重性，无温度因子） |
| `build_dbs.py` | 化学式解析（`parse_elements` / `is_inorganic`）、晶胞体积、旧 3COD 打包器 |
| `scan_inorg.py` | 三库无机分类扫描 + 生成 `inorg_manifest.sqlite` 清单 |
| `verify_polydb.py` | 结构/校验和校验器（32 项硬判据，纯标准库） |
| `bench_polydb_pilot.py` | 小样本试产：单条耗时、峰数分布、与旧库峰位 parity |

```bash
python tools/scan_inorg.py --workers 6
python tools/build_polydb.py --scope inorg --workers 8
python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB
```

## B. 数据同步与清单核对

| 脚本 | 作用 |
|---|---|
| `fetch_remote_inv.py` / `make_local_inv.py` / `cmp_inv.py` | 远端/本地清单生成与逐条比对 |
| `crawl_tcod_http.py` / `fetch_tcod_http.py` / `fetch_missing_tcod.py` | TCOD 只能走 Apache 索引爬取（无 rsync），含补齐与退避 |
| `audit_tcod_inv.py` / `diff_tcod_inv.py` / `fix_tcod_offset.py` | TCOD 清单审计、差集、错层路径修正 |
| `verify_coverage.py` / `verify_sync_tcod.py` | 覆盖率与同步完整性核验 |
| `disk_audit.py` / `recycle_audit.py` | 容量盘点（含回收站真实占用） |
| `probe_remote.sh` | 到 COD 站点的连通性/并发探测 |

## C. 旧格式（3COD sqlite）—— **已废弃，仅存档**

`build_3cod.py`（全量+无机）、`build_3cod_org.py`（有机物差集）、`split_3cod.py`（分片）、
`accept_3cod.py` / `accept_3cod_org.py`（成品质检）、`report_pack_accept.py` /
`report_accept_formal.py`（验收报告）、`probe_two_projects.py`（PolyXRD / XinMatch 双向探测）。

> 这套产出的是 `.sqlite` 单体库（Full 28 GiB / Inorg 19 GiB），与 polyDB 口径不同
> （旧库 500 峰、按 d 降序、无 d 截止）。**2026-10-23 起格式只保留 polyDB 与 xinDB**，
> 本组脚本不再维护、不再使用，对应的打包规范与参考实现（原 `sync-COD-pack/`）已从仓库移除；
> 留在这里只为读懂历史产物的来路。

## D. 一次性诊断/复核（可读性差，按需参考）

`debug_*.py`、`diag_quartz_strongest.py`、`check_*.py`、`analyze_*.py`、`classify_*.py`、
`spotcheck_*.py`、`diff_*.py`、`inspect_*.py`、`bench_*.py`、`smoke_*.py`、`verify_*.py`、`report_*.py`。

其中值钱的是三份"结论性"脚本，出问题先看它们：

| 脚本 | 结论 |
|---|---|
| `arbiter_direct.py` | 定义级峰位/强度仲裁：与 `fastxrd` 逐峰 0.00% 偏差 → F/多重性/LP/归一化全对 |
| `verify_tth_range.py` / `verify_peak_params.py` | 峰口径（2θ 范围、λ、截断）回归 |
| `compare_cif.py` / `validate_against_reference.py` | CIF 解析正确性对照 |
