# TCOD / PCOD 三库验收报告（20261020 期）

> 验收日期：**2026-11-01**（本地时）　验收人：独立复验（不采信构建期自述）
> 对象：`polydb/TCOD-Inorg-20261020.polyDB`、`polydb/TCOD-Full-20261020.polyDB`、
> `polydb/PCOD-Inorg-20261020.polyDB`
> 依据：`docs/外挂库格式规范-polyDB-v4.md`（§1–§6）、`docs/polyDB重建方案-20261021.md`（S6–S13 判据）、
> `docs/polyDB-TCOD-PCOD构建报告-20261020.md`（构建自述）、`tools/README.md`、`README.md §1.3`
> 证据：`docs/bench/polydb_tcod_pcod_accept.json`（本次全部原始判定与数字）

## 1. 结论

**PASS —— 三库均通过独立复验，可以直接进入打包/发布流程，无需重建。**

- 结构层 `tools/verify_polydb.py`：三库各 **32 PASS / 0 FAIL / 0 WARN**（含 7 段 sha256 重算）。
- 精度层 `PolyXRD/scripts/polydb_verify.py --sample 200`：三库 **ok / failures=[] / warnings=[]**，
  L1 结构+hash、L2 位图（bins/elem）按 d 矩阵与 `elements` 全库重算**逐字节相等**、L3 源 CIF 回算 200 相。
- 消费侧真实 reader：`probe / is_ready / stats / get_phase / get_atomic_sites /
  search_by_d_peaks / search_entries / elements_allowed / row↔eid` 全通。
- 外挂挂载识别：三库均被 `db_mounts.detect_kind` 自动识别为 `polydb`，
  `add_mount + probe` 的 `variant / rows / size_mb` 全部正确（隔离 `USERPROFILE`，未写用户配置）。
- 构建报告与 README 的公开数字基本一致（36 项中 33 项精确一致，3 项差异均属文档四舍五入/抽样口径，见 §4）；另发现 10 条不影响验收的观察/文档项（§5）。

| 库 | 相数 | 峰数（非零 d） | 位点 | 体积 | 结构 32 项 | L3 max\|Δd\| / max\|ΔI\|（200 相） | reader | 挂载 |
|---|---:|---:|---:|---:|---|---|---|---|
| TCOD-Inorg-20261020 | 46,541 | 3,767,731 | 754,606 | 52.6 MiB | 32/32 PASS | 7.94e-7 Å / 0.00762 | PASS | PASS |
| TCOD-Full-20261020 | 359,307 | 35,039,291 | 22,178,424 | 681.6 MiB | 32/32 PASS | 9.49e-7 Å / 0.00761 | PASS | PASS |
| PCOD-Inorg-20261020 | 1,061,817 | 106,160,732 | 32,522,180 | 1,413.0 MiB | 32/32 PASS | 9.08e-7 Å / 0.00763 | PASS | PASS |

> 判据（规范 §4.1/§4.2）：d ≤ 1e-4 Å、I ≤ 0.05（1000 标度）。实测三项均 ≤ 9.5e-7 / 0.00763，比判据小 2 个数量级；脚本闸门本身写的是 5×0.05，本次连更严的 0.05 也远未触及。

## 2. 逐条对照要求

| 要求 | 判据 | 实测 | 结论 |
|---|---|---|---|
| S6 构建器 | `--lib COD\|PCOD\|TCOD`（缺省 COD）、`--stamp`、`--max-skip-ratio`、parts 按 variant 隔离、条数守恒 | `--help` 四参数齐；parts 单元数 24/182/531 == `ceil(attempted/2000)`；三库均 `清单 = 入库 + skip` | ✅ |
| S7/S11 构建 | 跳过率 <5% 且原因分类齐全 | 0.856% / 0.824% / 0.0137%；四类原因（no_volume / volume_too_large / no_sites / no_pattern）计数之和 == skipped | ✅ |
| S8/S12 校验 | 结构 32 项 + 位图重算 + 精度抽样 | 见 §1；`integrity_check=ok`、`entries=N`、`row_idx=0..N-1` 完整唯一 | ✅ |
| S12 复本率/tier | 入档（COD 两库判据） | 精确峰型重复行 TCOD-Inorg 0.77% / TCOD-Full 0.56% / PCOD 0.0001%，无须去重；tier/dup_group 全 0（与 COD 两库一致，见 F5/F6） | ✅（附观察项） |
| 规范 §1 容器 | 8 段齐全、little-endian、目录名 `<LIB>-<scope>-<stamp>.polyDB` | 三库各 8 文件，段字节数与 meta 逐一相等 | ✅ |
| 规范 §2 口径 | λ=1.5406、2θ 5–100.76、d≥1.0、intensity_top、K=100、M=40 | `peak_convention` 与 COD-Inorg/COD-Full `meta.json` **逐字段相等**；实测 d∈[1.0000, 17.6596]（理论上界 17.659579）、每相最大 I 恰为 65535（归一 1000） | ✅ |
| 规范 §3 寻址 | `i == entries.row_idx`（**不是** eid-1） | `row_idx` 为 0..N-1 完整唯一排列；`eid-1==row_idx` 行数为 0 | ✅ |
| 规范 §4.3/4.4 | bins=501×ceil(N/8) 且只索引最强 40 峰；elem=118×ceil(N/8) | 形状自洽；L2 全库重算逐字节相等；无 d≥25 峰 → overflow 箱（500）为空，最高用箱 353 | ✅ |
| 规范 §4.5 位点 | 17 B/点、`sites_off` 单调、末值==sites.bin | 全库校验通过；15 相/库抽样与源 CIF 非对称单位逐点一致（0 差异）。坐标越胞问题见 F4 | ✅ |
| 规范 §5/5.1 | `variant` 逐库唯一；PCOD 无 Full | `tcod-inorg` / `tcod-full` / `pcod-inorg`；全仓库 6 个 polyDB 的 variant 互不相同；无 `PCOD-Full` 目录 | ✅ |
| ID 段 | COD +0 / PCOD +2e7 / TCOD +1e8，与清单一致 | TCOD 110,000,001–140,354,755；PCOD 21,000,000–29,585,139；全库 eid ∈ 清单，40 相/库抽样 `eid/formula/cif_rel` 与清单完全一致 | ✅ |
| 数据来源 | 清单条数 == attempted == 入库+skip | 46,943 / 362,293 / 1,061,962 与 `inorg_manifest.sqlite` 分布完全一致 | ✅ |
| 消费侧 | 真实 reader 可用 | 见 §1；PCOD 元素过滤 3.5 s（允许元素池 ⊆ 相元素集，结果全部满足） | ✅ |
| 外挂挂载 | `.polyDB` 任意目录可挂 | 三库 `detect_kind → polydb`、`probe ok`、相数/体积与 meta 一致、variant 正确 | ✅ |
| COD 回归 | 新增 `--lib` 不改 COD 行为 | `--lib COD` 与省略 `--lib` 各建 20 相迷你库：`variant=cod-inorg`、`source.lib=COD`、`peaks_d` sha256 相同；改后的 `polydb_verify.py` 跑 COD-Inorg `--sample 50` PASS；COD 两库文件 mtime 仍为 2026-10-21 | ✅ |

## 3. 复验方法（与构建期脚本分离）

1. **结构门禁**：`tools/verify_polydb.py`（纯标准库，含 sha256）。
2. **精度门禁**：`PolyXRD/scripts/polydb_verify.py --sample 200`（L1 + L2 位图全量重算 + L3 源 CIF 回算）。
3. **独立审计**（一次性只读脚本，判据不依赖前两者）：
   - 峰矩阵**全量逐行**检查（3 库共 1,467,665 相 × 100 槽 = 1.47 亿个峰槽）：I 降序、`I[0]==65535`、
     `d=0 ⟺ i=0`、空槽只在尾部、`n_peaks == 非零峰数`、`d≥1.0`、无非有限值；
   - 元素位图 **118 行全量** vs `entries.elements` vs `meta.element_phase_counts` 三方一致；
   - 抽样 40 相/库对 `inorg_manifest.sqlite` 核 `eid/formula/rel` 并确认 CIF 存在；
   - 抽样 15 相/库由 `sites_off` 取 `sites.bin`，与源 CIF 非对称单位逐点比对；
   - 全量检查 eid 覆盖清单、无机口径（无机库不得出现同时含 C+H 的相）；
   - TCOD-Inorg ⊂ TCOD-Full：公共 eid 抽样 50 相，峰矩阵逐字节相同。
4. **消费侧**：用 PolyXRD 的 `PolyDatabase` 打开三库（+ COD-Inorg 对照），
   自检索（库内相自己的 100 峰当测量峰，`limit=10`）、元素过滤、文本检索、`row↔eid` 往返。
5. **挂载侧**：`db_mounts.detect_kind/add_mount/probe`，把 `USERPROFILE` 指到临时目录，确保不写用户配置。

> **预筛召回（G2）的前提已复核**：`bins.u8` 由 `peaks_d` 前 40 峰**全库**重算逐字节相等（L2），
> 且 `M=40 ≥ max_ref_peaks=40`，因此规范 §6「位图资格集 ⊇ 精确打分结果」成立；
> 13 试样 top-100 A/B 是 COD 专用探针，本次不重复（见 §6）。

> 结论不依赖构建报告：报告只用于事后比对数字（§4）。

## 4. 与构建报告 / README 数字的比对

构建报告/README 的 36 项公开数字中 **33 项精确一致**（相数、峰数、位点数、体积、耗时、eid 段、
元素种类、逐相峰数 min/avg/max、跳过原因分布等）；另 3 项差异均已解释（下表）。
`PCOD 无 Full`、`variant` 命名、三库 variant 互不相同等非数字项也逐条核对通过。

| 项 | 报告值 | 实测 | 说明 |
|---|---|---|---|
| TCOD-Full 跳过率 | 0.83% | 0.8242% | 文档四舍五入应为 **0.82%**（见 F9） |
| TCOD-Inorg 自召回 hit@1 | 3/5 | 4/5 | 抽样相位与构建期不同（本次取每库 `n_peaks≥90` 的等距 5 相）；同轮 COD-Inorg 对照亦为 4/5，**相对结论不变** |
| TCOD-Full 自召回 hit@1 | 3/5 | 3/5（hit@5 5/5） | 同上；5 相样本量不足以判定系统性差异 |

构建报告未覆盖、本次补做的检查：`row_idx` 全排列、`n_peaks` 与实际非零峰数全量一致、
元素位图与 `elements` 字段全量一致、位点与 CIF 逐点一致、eid 与清单全量覆盖、
COD 默认路径 A/B 冒烟、挂载识别。

## 5. 观察项（不影响本次 PASS）

| id | 级别 | 项 | 说明 / 建议 |
|---|---|---|---|
| F1 | 观察 | `search_entries("110000179")` 这类纯数字 eid 查询对 8/9 位 eid 不生效 | reader 的 `_parse_eid_query` 只认 7 位 / 96-97 前缀；`get_phase`、`row_of_eid` 正常。接入界面时补一条「任意位数按 eid 精确查」即可，与 polyDB 数据无关。 |
| F2 | 文档 | 构建报告 §3.3 写 `search_entries（FTS5）` | 实际 reader 走 SQL LIKE；`entries_fts` 表存在且行数一致，当前无调用方。改措辞即可。 |
| F3 | 文档 | README §1.3「构建于 2026-10-31」 | 按 `目录 mtime − elapsed_s` 反推实际构建区间：TCOD-Inorg 10-31 23:44→23:48、TCOD-Full 10-31 23:49→**11-01 01:33**、PCOD **11-01 01:34→03:51**。建议写「构建于 2026-10-31 ~ 11-01」（注意 F10：`started_at` 字段本身不可直接当开始时间用）。 |
| F4 | 规范 | 规范 §4.5 写位点坐标「0..1」 | 实测有 CIF 原样的越胞坐标（抽样比例：PCOD 15%、TCOD-Inorg 2.3%、TCOD-Full 1.7%、COD-Inorg 32%、COD-Full 87%）。存储/读取都按 CIF 原样（reader 文档已写明「非对称单位、CIF 原样」），下游按对称展开。建议规范改为「CIF 原样值，可越胞」，免第三方按 0..1 误判。 |
| F5 | 观察 | `tier` / `dup_group` 三库全 0 | 与 COD 两库一致（MP 库标了 tier=2）。TCOD/PCOD 的「理论/预测」属性若将来要参与 UI 区分，可在 build 里按 `--lib` 落 1/2。 |
| F6 | 观察 | 体积/去重 | 整行 600 B 哈希 + 逐字节复核：精确重复峰型 TCOD-Inorg 357/46,541、TCOD-Full 2,030/359,307、PCOD 1/1,061,817；**无需去重**。`formula+SG+volume` 聚类在 PCOD 达 38%，但多为同式同群不同构型，不是同相复本，勿当复本率。 |
| F7 | 待办 | 发布前剩 S13/S16/发版 | 未打 zip、未生成 `SHA256SUMS.txt`、未做外挂目录/GUI「自定义挂载」冒烟；README 已如实写「构建中，尚未发布」。三库 variant 唯一，可安全共存。 |
| F8 | 观察 | 检索耗时 | 本次自检索（100 峰）：TCOD-Inorg 0.40–0.53 s、TCOD-Full 1.6–2.0 s、PCOD 3.9–5.4 s（报告 0.35/1.3/3.4 s；本次有并发读盘）。同量级，未发现退化。 |
| F9 | 文档 | TCOD-Full 跳过率 0.83% | 2,986/362,293 = 0.8242% → 应写 0.82%。 |
| F10 | 缺陷（既有，非本次引入） | `meta.build.started_at` 语义错位 | `build_polydb.py` 在 worker 循环**结束后**才 `datetime.now()`，而 `elapsed_s` 也只量到这一刻（不含 merge/落盘）；实测三库 `started_at` 与目录 mtime 仅差 1–18 s（merge 时长），真实开始 = `started_at − elapsed_s`。COD 两库同样受影响（HEAD 版本即如此），MP 库用的是另一支构建器、不受影响。**数据不受影响**；建议改为用 `t0` 的 datetime 写 `started_at`，并另记 `finished_at` / 含 merge 的总耗时。 |

## 6. 本次验收不覆盖

- **13 试样 A/B 精度闸门（G1/G3）**：那套判据针对「COD 实验库 vs 旧 77k 库」；
  TCOD/PCOD 分别为理论计算与 GRINSP 预测集，无同口径旧库可比。本三期库沿用
  「与源 CIF 自洽（≤1e-6）+ 消费侧可用」判据，与构建报告口径一致。
- 打包/`SHA256SUMS.txt`/Release 附件、GUI 冒烟（S13/S16）——待用户确认后执行。
- `--max-skip-ratio` 的故意失败注入（缺散射因子表 → 拒绝出库）未演练；代码审阅通过，正常构建路径已生效。

## 7. 复现命令

```bash
# 结构门禁（发布前必过）
python tools/verify_polydb.py polydb/TCOD-Inorg-20261020.polyDB \
    polydb/TCOD-Full-20261020.polyDB polydb/PCOD-Inorg-20261020.polyDB

# 精度门禁（L1+L2+L3，抽样 200 相）
python D:/Project/XRD/PolyXRD/scripts/polydb_verify.py polydb/TCOD-Inorg-20261020.polyDB --sample 200
python D:/Project/XRD/PolyXRD/scripts/polydb_verify.py polydb/TCOD-Full-20261020.polyDB --sample 200
python D:/Project/XRD/PolyXRD/scripts/polydb_verify.py polydb/PCOD-Inorg-20261020.polyDB --sample 200

# COD 回归（默认 --lib）
python tools/build_polydb.py --lib COD --scope inorg --limit 20 --out <tmp> --force --workers 2
python tools/build_polydb.py        --scope inorg --limit 20 --out <tmp2> --force --workers 2
python D:/Project/XRD/PolyXRD/scripts/polydb_verify.py polydb/COD-Inorg-20261021.polyDB --sample 50
```

> 证据汇总：`docs/bench/polydb_tcod_pcod_accept.json`
> （结构/精度/独立审计/reader/挂载/跨库/文档比对/观察项，全部含原始数字与命令）。
