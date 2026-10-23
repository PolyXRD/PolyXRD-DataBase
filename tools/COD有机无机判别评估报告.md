# 本地 COD / PCOD / TCOD 有机物—无机物判别能力评估

**评估对象**：`E:\rsync-COD\` 下已同步完成的三个本地库
**评估时间**：2026-10-11
**方法**：两阶段随机抽样（先随机抽叶子目录，再在目录内随机抽 CIF），解析 CIF 头部文本；样本量 COD 4520、PCOD 2988、TCOD 2450
**复现脚本**：`E:\rsync-COD\tools\scan_organic.py`
**原始数据**：`E:\rsync-COD\tools\organic_scan_result.csv`

---

## 一、结论摘要

1. **能分辨，但没有现成标签。** 三个库的 CIF 里**不存在**"有机物/无机物"这类分类标签字段，必须依据化学组成自行判定。
2. **判定基础字段可用性极高**：`_chemical_formula_sum`（化学式和，Hill 记法）在 COD 覆盖 **99.85%**、PCOD 与 TCOD **100%**。这是唯一可以批量、可靠使用的判别依据。
3. **名称类字段不能用作判别依据**：`_chemical_name_common` 覆盖率仅 0.27%~11.13%，`_chemical_compound_source` 仅 0.9%~6.04%，缺失太严重。
4. **三个库的化学构成差异极大**，不能一视同仁（详见第三节）。

---

## 二、判别依据实测覆盖率

| 库 | 抽样数 | `_chemical_formula_sum` | `_chemical_name_common` | `_chemical_name_systematic` | `_chemical_compound_source` |
|---|---|---|---|---|---|
| COD | 4520 | **99.85%** | 11.13% | 46.59% | 6.04% |
| PCOD | 2988 | **100.00%** | 0.27% | 0.00% | 0.00% |
| TCOD | 2450 | **100.00%** | 1.02% | 1.10% | 0.90% |

---

## 三、按化学式规则的有机/无机分布

**判定规则**（元素集合 E，非金属集合之外的元素视为金属）：

| 类别 | 判据 | 说明 |
|---|---|---|
| 有机物 organic | 含 C **且** 含 H，且不含金属元素 | C—H 键是有机物的核心特征 |
| 金属有机 / 有机盐 organometallic | 含 C **且** 含 H，且含金属元素 | 如醋酸锶、金属配合物 |
| 无机碳 carbon-inorganic | 含 C **但不含** H | 碳酸盐、CO₂、碳化物、氰化物等，按化学惯例归无机 |
| 含 H 无机物 | 含 H 但不含 C | 如氢氧化物、酸式盐 |
| 无机物 | 既不含 C | 氧化物、硫化物、金属间化合物等 |

**实测分布**（%，95% 置信区间约 ±1.4 个百分点，按二项分布标准误计）：

| 库 | 有机物 | 金属有机/有机盐 | 无机碳 | 含 H 无机物 | 无机物 | 无法判定 |
|---|---|---|---|---|---|---|
| COD | 33.52 | 50.02 | 0.88 | 3.50 | 11.92 | 0.15 |
| PCOD | **0.00** | 0.00 | 0.00 | 0.00 | **100.00** | 0.00 |
| TCOD | 49.55 | 18.16 | 3.31 | 2.61 | 26.37 | 0.00 |

**外推到全库的条目数估算**：

| 库 | 本地文件数 | 严格无机（不含 C）估算 | 宽口径无机（含无机碳、含 H 无机）估算 |
|---|---|---|---|
| COD | 535,181 | ≈ 82,500 | ≈ 87,200 |
| PCOD | 1,062,044 | ≈ 1,062,000 | ≈ 1,062,000 |
| TCOD | 57,478 | ≈ 15,200 | ≈ 17,100 |

> 注：外推基于抽样比例，存在 ±1.4% 的相对误差，仅作量级参考。

---

## 四、为什么可以这样判：权威依据

1. **数据库官方定位本身就包含四类物质，但只提供元素级检索、不提供有机/无机标签**
   - COD：*International Tables for Crystallography* Vol. H, ch. 3.7.8（Kaduk & Gražulis, 2019）原文："aims at collecting in a single open-access database **all organic, inorganic and organometallic structures**, except for the structures of biological macromolecules"。
   - TCOD 官网首页原文："Open-access collection of theoretically calculated or refined crystal structures of **organic, inorganic, metal-organic compounds and minerals**, excluding biopolymers."
   - COD 官方搜索界面提供的是"chemical formula (in Hill notation) 1 to 8 elements"与"**NOT these elements**"过滤，以及 SMILES 子结构检索（覆盖 258,635 个结构的子集），**没有** organic/inorganic 勾选框。这从官方工具设计上印证了"标签不存在、需按元素组成自行判定"。

2. **C—H 键判据符合化学分类惯例**：有机化合物通常指含碳化合物，但 CO、CO₂、碳酸盐、碳化物、氰化物等传统上归入无机，其共同特征正是"含 C 而无 C—H 键"。本规则与该惯例一致。

3. **氘代化合物必须特殊处理**：中子衍射结构中常见氘代样品，例如本地 COD `1/00/00/1000002.cif` 的式子为 `C3 D3 O7 Sr`（氘代草酸锶，`_chemical_name_common` 为 "Deuterated acid strontium oxalate"）。若把 D 忽略，会被误判为"无机碳"。本次脚本已把 D/T 并入 H 处理。

---

## 五、规则的已知边界（需要二次判定的情形）

基于"元素组成"只能粗判，以下情形建议改用**键连通性分析**（用 gemmi / pymatgen 计算是否存在 C—H 或 C—C 键）：

| 边界情形 | 元素规则结果 | 化学上更合理的归类 |
|---|---|---|
| 石墨、金刚石、富勒烯（纯 C） | 无机物 | 单质碳，通常归无机 |
| 碳酸盐（CaCO₃）、CO₂、SiC、CaC₂ | 无机碳 | 无机（规则已正确） |
| 草酸盐、氰酸盐等含 C 无 H 的有机酸盐 | 无机碳 | 视用途可归有机 |
| 金属有机框架（MOF）、有机金属配合物 | 金属有机 | 视检索需求决定是否保留 |
| 有机硅、有机硼化合物（含 Si/B + C + H） | 有机物 | 规则已按非金属处理，正确 |
| 有机盐（如醋酸钠） | 金属有机/有机盐 | 粉末衍射中常按"有机相"处理 |

---

## 六、对 XRD 物相检索的实操建议

- **做无机未知相检索时**，主力库应是 **PCOD（100% 无机，106 万条目）+ COD 的无机子集（约 8.2~8.7 万条目）**，TCOD 无机部分约 1.5 万条目可作补充。
- **不要直接用 COD 全库做无机检索**：有机物 + 金属有机合计约 83.5%，会显著增加假阳性匹配与检索耗时。
- **建立无机子集索引**：以 `_chemical_formula_sum` 为准，按"不含 C"或"含 C 但不含 H 且不含金属"筛出无机条目清单，再据此建检索库。这正是本次脚本可以扩展完成的工作。
- **PCOD 是纯无机预测结构库**，对未知无机相的假设结构匹配价值高，但要注意它是**计算预测**结构，与实测粉末谱可能存在偏差，匹配结果需人工复核。

---

## 七、复现方式

```bash
# 重新抽样扫描（结果写入 tools/organic_scan_result.csv）
"C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe" -u \
  "E:/rsync-COD/tools/scan_organic.py" "E:/rsync-COD"
```

脚本参数在 `main()` 的 `plan` 列表中：`(库名, 路径, 抽样目录数, 每目录抽样文件数, 目录层级深度)`，可按需调整样本量或改成全量遍历。
