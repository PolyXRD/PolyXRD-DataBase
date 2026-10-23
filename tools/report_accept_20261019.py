#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 3COD 综合验收报告（HTML，自包含，无外链）。"""
import os, time

OUT = "D:/Project/XRD/PolyXRD-DataBase/sync_logs/3COD综合验收报告_20261019.html"

INORG_INTEG = """
<span class="fail">损坏</span> 22.7 min 后返回 20+ 条：b-tree 行序错乱（rowid 97376698 / 7248175）、
孤儿页 2545165、<code>NUMERIC value in phases.formula</code>、
大量 <code>row ... missing from index</code>"""
FULL_INTEG = """
<span class="fail">损坏</span> 10.6 min 后抛 <code>database disk image is malformed</code>，
完整性检查提前中止（存在不可读/结构非法的页面）"""
ORG_INTEG = """
<span class="pass">通过</span> 16.1 min，返回 <code>ok</code>"""

INORG_J = '<span class="fail">损坏</span>'
FULL_J = '<span class="fail">损坏</span>'
ORG_J = '<span class="pass">完好</span>'

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--txt:#1c2024;--dim:#5b6570;
--ok:#1a7f47;--okbg:#e8f6ee;--bad:#b42318;--badbg:#fdecea;--warn:#8a5b00;--warnbg:#fff5e0;}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--bg);color:var(--txt);
font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.3px}
.sub{color:var(--dim);font-size:13px;margin-bottom:22px}
.verdict{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--bad);
border-radius:8px;padding:18px 22px;margin-bottom:26px}
.verdict h2{margin:0 0 8px;font-size:17px;color:var(--bad)}
.verdict p{margin:4px 0;color:#333}
h2.sec{font-size:18px;margin:34px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:22px 0 8px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:8px;overflow:hidden;font-size:13px}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f0f2f5;font-weight:600;font-size:12.5px;color:#39424c}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.pass,.fail,.warn{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}
.pass{color:var(--ok);background:var(--okbg)}
.fail{color:var(--bad);background:var(--badbg)}
.warn{color:var(--warn);background:var(--warnbg)}
code{background:#eef0f3;padding:1px 5px;border-radius:4px;font-size:12.5px;
font-family:ui-monospace,Consolas,monospace}
pre{background:#1e2227;color:#e6e9ee;padding:12px 14px;border-radius:8px;overflow:auto;
font-size:12.5px;line-height:1.5}
.note{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px;
margin:12px 0;color:#39424c}
.bar{height:9px;background:#e9ecf0;border-radius:5px;overflow:hidden;margin-top:4px}
.bar>i{display:block;height:100%;background:#4b6b8a}
ol,ul{margin:8px 0 8px 20px;padding:0}
li{margin:5px 0}
.small{font-size:12.5px;color:var(--dim)}
"""

def row(*cells):
    return "<tr>" + "".join(cells) + "</tr>"

judge = {
    "pass": '<span class="pass">通过</span>',
    "fail": '<span class="fail">不通过</span>',
    "warn": '<span class="warn">有缺陷</span>',
}

checks = [
    ("文件级格式", "pass", "三库 magic=SQLite format 3、page_size=4096、UTF-8、journal_mode=delete、无 -wal/-shm 残留"),
    ("表结构与索引", "pass", "PolyXRD 侧 phases/cod_entries/cod_atomic_sites/meta、XinMatch 侧 entries/peaks/elements/element_combo 及全部规范索引齐备"),
    ("PolyXRD 库型识别", "pass", "官方 <code>db_import.inspect_db_file()</code>：Full→<code>cod_index</code>（1,838,364 行）、Inorg→<code>cod_inorganics</code>（1,172,223 行）"),
    ("Org 库在 PolyXRD 的落位", "fail", "被识别成 <code>cod_inorganics</code>：PolyXRD 只有 4 个槽位（cod_inorganics / pdf2 / cod_index / xinmatch），<b>没有有机物槽位</b>，挂载 Org 会顶掉无机库"),
    ("XinMatch 库型识别", "pass", "三库均被 <code>polyxrd.detect_source()</code> 判为原生 <code>xinmatch</code>（entries+peaks 齐备），直接打开、无需转换"),
    ("条目数守恒", "pass", "Inorg 1,172,223 + Org 651,514 = 1,823,737 phases；entries 1,173,999 + 664,365 = 1,838,364 = Full 条目数"),
    ("峰行数守恒", "pass", "Inorg 114,824,098 + Org 65,128,244 = 179,952,342 = Full peaks 行数"),
    ("ID 映射", "pass", "抽检 4,000 条：<code>ref_id == display_id == 96-XXX-XXXX</code>，不符 0 条"),
    ("峰三方一致", "pass", "抽检 3 条：<code>peaks_d/peaks_i</code> CSV、<code>peaks_top_d/i</code> BLOB、<code>peaks</code> 行表逐值相等（Δd、Δi 均为 0）"),
    ("hkl 填充", "pass", "<code>peaks.h/k/l</code> 全量非空（XinMatch <code>march_po</code> 择优取向可用）"),
    ("原子位点覆盖", "pass", "Inorg 99.90% / Org 99.58% / Full 99.79%（平均 29.1 / 78.4 / 46.9 位点每相）"),
    ("CIF 可定位", "pass", "<code>cod_entries.file</code> 存相对路径（<code>COD/1\\00\\00/1000000.cif</code>），<code>cod_root</code> 指到数据根目录即可命中"),
    ("<b>Inorg 物理完整性</b>", "fail", "<code>PRAGMA integrity_check</code> 报 b-tree 行序错乱、孤儿页、93 行数值型 formula、多条记录缺索引"),
    ("<b>Full 物理完整性</b>", "fail", "<code>PRAGMA integrity_check</code> 10.6 分钟后抛 <code>database disk image is malformed</code>，提前中止"),
    ("Org 物理完整性", "pass", "<code>PRAGMA integrity_check</code> 16.1 分钟返回 <code>ok</code>（三库中唯一结构完好的）"),
    ("<b>PolyXRD 默认检索</b>", "fail", "默认 <code>max_ref_peaks=40</code>（走 BLOB 快路径）在 Inorg 上直接 <code>AttributeError: 'NoneType' has no attribute 'split'</code>"),
    ("<b>PolyXRD 检索性能</b>", "fail", "1.17M 相全表扫描 <b>348.7 s</b>/次；随包 71k 相库 8.8 s。Org 651k 相 193.8 s"),
    ("formula 规范", "fail", "1,061,845 条（57.8%）formula 带字面双引号，如 <code>\"Si O2\"</code>；<code>formula_red</code>/<code>elements</code> 未被污染"),
    ("XinMatch 元数据完整度", "fail", "<code>crystal_system</code> 100% 为 NULL；<code>density/year/author/journal</code> 0 填充；<code>mineral_name</code> 仅 4.3%"),
    ("meta 准确性", "fail", "<code>tar_source</code> 仍指向已不存在的 <code>E:/rsync-COD/{COD,PCOD,TCOD}</code>；缺数据快照与许可信息"),
    ("外挂稳健性", "pass", "DELETE journal、无侧车、page_size 4096、表内 <code>meta.variant=slim-index-*</code>（PolyXRD 的 <code>has_cif</code> 过滤因此放行）"),
]

checks_html = "".join(
    row(f"<td>{i+1}</td>", f"<td>{name}</td>", f"<td>{judge[st]}</td>", f"<td>{desc}</td>")
    for i, (name, st, desc) in enumerate(checks)
)

sizes = [
    ("peaks（XinMatch 行表）+ 两个索引", 7617.18 + 3767.99 + 3098.04, 33.8),
    ("cod_atomic_sites + PK + idx_sites_cod_id", 4416.99 + 1277.74 + 1107.05, 30.2),
    ("cod_entries", 237.38, 1.1),
    ("entries / elements / element_combo 等", 189.56 + 132.93 + 134.73 + 134.71, 2.6),
    ("其余索引与统计表", 22559.64 - (7617.18 + 3767.99 + 3098.04 + 4416.99 + 1277.74 + 1107.05 + 237.38 + 189.56 + 132.93 + 134.73 + 134.71), 100 - 33.8 - 30.2 - 1.1 - 2.6),
]
size_rows = "".join(
    row(f"<td>{n}</td>", f'<td class="num">{b:,.0f}</td>', f'<td class="num">{p:.1f}%</td><td><div class="bar"><i style="width:{p}%"></i></div></td>')
    for n, b, p in sizes
)

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>3COD 外挂数据库综合验收报告</title><style>{CSS}</style></head><body><div class="wrap">

<h1>3COD 外挂数据库综合验收报告</h1>
<div class="sub">验收时间 2026-10-19　·　被测物：3COD-Full-20261015 / 3COD-Inorg-20261016 / 3COD-Org-20261016　·　
基准：PolyXRD v3.1.0（eed0466）、XinMatch v2.0.0（c0b1a56）的最新源码，而非 10-13 的旧打包规范</div>

<div class="verdict">
<h2>结论：不予通过 —— 三个库建议整体重建（其中两个已经损坏）</h2>
<p><b>直接原因有四个：</b></p>
<ol>
<li><b>3COD-Full 与 3COD-Inorg 物理损坏</b>：<code>PRAGMA integrity_check</code> 一个直接中止（<i>malformed</i>），
一个报 b-tree 行序错乱 + 孤儿页 + 93 行数据错位。<b>三个库只有 Org 是完好的</b>。这不是"查询慢"，是文件本身不合法。</li>
<li><b>PolyXRD 默认检索在 Inorg 上崩溃</b>：那 93 行的 <code>peaks_top_d</code> 为 NULL，PolyXRD 的 top-64 快路径不做空值保护，
第一次检索就抛 <code>AttributeError</code>。</li>
<li><b>检索耗时不可接受</b>：1.17M 相每次 348.7 s（随包 71k 相库 8.8 s）。PolyXRD 的物相检索是逐行全表扫描，库越大越慢。</li>
<li><b>Org 在 PolyXRD 侧无处安放</b>：PolyXRD 只有 4 个槽位，没有有机库槽位，Org 会被误判成无机库并顶掉真正的无机槽位。</li>
</ol>
<p class="small">Full / Org 之外的结构与数据一致性抽检（ID 映射、峰三方一致、位点覆盖、hkl 填充）全部通过，
说明<b>数据本身是对的、构建与交付环节有问题</b>——这正是重建能一次解决的原因。</p>
</div>

<h2 class="sec">一、逐项判定</h2>
<table>
<thead><tr><th style="width:36px">#</th><th style="width:190px">检查项</th><th style="width:74px">结论</th><th>证据 / 说明</th></tr></thead>
<tbody>{checks_html}</tbody></table>

<h2 class="sec">二、三个阻断项的复现与根因</h2>

<h3>2.1 Inorg 库结构损坏</h3>
<pre>$ python -c "import sqlite3;c=sqlite3.connect('file:3COD-Inorg-20261016.sqlite?mode=ro',uri=True);
print(c.execute('PRAGMA integrity_check(50)').fetchall()[:6])"

*** in database main ***
On tree page 2545167 cell 92: Rowid 97376698 out of order
On tree page 2545166 cell 0: Rowid 7248175 out of order
Page 2545165 is never used
NUMERIC value in phases.formula
row 56713 missing from index idx_phases_match_ref
row 56713 missing from index idx_phases_display_id</pre>
<p>受影响的 93 行 <code>rowid</code> 落在 97,376,606–97,376,698，而三库真实 ID 区间是
COD 1,000,000–9,017,926 / PCOD 21,000,000–29,585,139 / TCOD 110,000,001–140,233,698 ——
这段 97.3M 是<b>不存在的编号空洞</b>，且这些行 <code>formula</code> 存的是浮点数（如 1.4370539）、
<code>ref_id</code> 为 NULL，属典型<b>列错位写入</b>。它们对 PK 查找不可见（
<code>WHERE cod_id=97376606</code> 返回空），只对全表扫描可见 —— 这正是行序错乱的直接后果。</p>
<p class="small">根因指向 v2 补丁分片的合并环节：<code>build_3cod.merge()</code> 用
<code>journal_mode=OFF + INSERT OR REPLACE ... SELECT *</code> 合并 25 个分片，
一旦中途异常/中断，b-tree 会停在半提交状态，而构建脚本没有任何完整性门禁。</p>

<h3>2.2 PolyXRD 默认检索崩溃</h3>
<pre>>>> db.search_cod_by_d_peaks(d, i, limit=5, conn=inorg_conn)      # 默认 max_ref_peaks=40
AttributeError: 'NoneType' object has no attribute 'split'
  File "polyxrd/services/cif_database.py", line 838, in _parse_float_csv</pre>
<p><code>cif_database.py:1892</code> 只要 <code>max_ref_peaks ≤ 64</code> 就走 <code>peaks_top_d/peaks_top_i</code>，
而该分支<b>没有 <code>IS NOT NULL</code> 保护</b>。GUI 预筛的默认值正是
<code>prefilter_max_ref_peaks=40</code>（<code>phase_identifier.py</code>），所以这是<b>默认路径必崩</b>，不是边角情况。</p>
<p class="small">双重修法：数据侧保证 <code>peaks_top_*</code> 永不为 NULL（峰失败就写 0 长 BLOB 或不写该行）；
代码侧给 <code>_parse_float_csv</code> 加 None 兜底。两边都做才稳。</p>

<h3>2.3 检索性能</h3>
<table><thead><tr><th>库</th><th class="num">相数</th><th class="num">phases 表</th><th class="num">单次检索</th><th>说明</th></tr></thead><tbody>
<tr><td>PolyXRD 随包 COD_inorganics_index</td><td class="num">71,199</td><td class="num">380 MB</td><td class="num">8.8 s</td><td>基线</td></tr>
<tr><td>3COD-Inorg</td><td class="num">1,172,223</td><td class="num">8.6 GB</td><td class="num">348.7 s</td><td>16.5× 相数 → 39× 耗时</td></tr>
<tr><td>3COD-Org</td><td class="num">651,514</td><td class="num">5.1 GB</td><td class="num">193.8 s</td><td>无有机槽位，实际挂不上</td></tr>
</tbody></table>
<p>PolyXRD 的检索是 <code>for row in cur</code> 逐行 Python 循环（元素过滤也在循环内），
耗时与 <code>phases</code> 表字节数近似成正比。当前每行 ~7.4 KB，其中 <code>peaks_d/peaks_i</code>
CSV 就占 ~4 KB（500 条峰、d 保留 7 位有效数字）。<b>把入表峰数压到 120、d 取 4 位小数</b>，
单行可降到 ~1.6 KB，检索预计回到 60–90 s。</p>

<h2 class="sec">三、非阻断缺陷</h2>
<table><thead><tr><th style="width:210px">问题</th><th style="width:120px">规模</th><th>影响与建议</th></tr></thead><tbody>
<tr><td>formula 带字面引号</td><td>1,061,845 条（57.8%）</td><td>PCOD 原始 <code>_chemical_formula_sum</code> 写成 <code>"Si O2"</code>，打包时未去引号。界面显示与 formula LIKE 检索受影响；<code>formula_red</code>/<code>elements</code> 已正确。重建时 strip 掉即可。</td></tr>
<tr><td>XinMatch 元数据大面积空</td><td>crystal_system 100% · density/year/author/journal 100% · mineral_name 95.7%</td><td>XinMatch 的晶系/密度/年份/作者/期刊筛选条件实际全部失效。晶系可由空间群推导，密度可由 formula+cell+Z 计算，年/作者/期刊在 CIF 的 <code>_journal_*</code>、<code>_publ_author_name</code> 里现成。</td></tr>
<tr><td>Org 库在 PolyXRD 侧无槽位</td><td>1 个库</td><td>PolyXRD <code>DB_KINDS</code> 只有 cod_inorganics/pdf2/cod_index/xinmatch。Org 若保留 <code>phases</code> 表会被判成无机库并顶掉无机槽位；建议 Org 只出 XinMatch 四表（PolyXRD 会按 <code>xinmatch</code> 类型挂载，仅用于检索）。</td></tr>
<tr><td>meta 与实际不符</td><td>3 个库</td><td><code>tar_source</code> 指向已消失的 E 盘；<code>cif_missing</code> 与 <code>entry_count</code> 口径不一（Org 差 138）。建议补 <code>source_root</code>、<code>source_snapshot</code>（各库条目数与抓取时间）、<code>license</code>、<code>builder_version</code>。</td></tr>
<tr><td>冗余索引</td><td>2.2 GB 合计</td><td><code>idx_sites_cod_id(cod_id)</code> 被主键 <code>(cod_id, site_idx)</code> 完全覆盖，属纯冗余：Full 1.1 GB / Inorg 0.45 GB / Org 0.65 GB。</td></tr>
<tr><td>峰数据双存</td><td>33.8% / 44.2% / 35.6% 的体积</td><td>同一批峰既存 <code>phases.peaks_d/i</code>（给 PolyXRD）又存 <code>peaks</code> 行表（给 XinMatch）。这是双 schema 的固有代价，见第五节方案 B。</td></tr>
</tbody></table>

<h2 class="sec">四、体积构成（dbstat 实测）</h2>
<p class="small">3COD-Full-20261015.sqlite，总计 22.03 GiB。Inorg 20.46 GiB、Org 14.26 GiB 构成类似（peaks 占比更高）。</p>
<table><thead><tr><th>对象</th><th class="num">MiB</th><th class="num">占比</th><th style="width:34%"></th></tr></thead><tbody>{size_rows}</tbody></table>

<h2 class="sec">五、三个可选方案</h2>
<table><thead><tr><th style="width:70px">方案</th><th>内容</th><th class="num" style="width:90px">总体积</th><th class="num" style="width:110px">检索耗时</th><th style="width:180px">代价</th></tr></thead><tbody>
<tr>
<td><b>A 修复+轻量</b><br><span class="small">推荐</span></td>
<td>保留双 schema；修损坏与空值；<code>phases</code> 峰数 500→120、d 取 4 位；Org 去掉 PolyXRD 侧表；补全 XinMatch 元数据；formula 去引号；删冗余索引；meta 修正</td>
<td class="num">~40 GiB</td><td class="num">60–90 s</td>
<td>峰数从 500 降到 120，极弱线（I&lt;0.5%）会丢，但 PolyXRD 预筛本来只用 top-64</td>
</tr>
<tr>
<td><b>B 激进瘦身</b></td>
<td>在 A 基础上再去掉 XinMatch 的 <code>peaks</code> 行表，XinMatch 首次挂载时用 <code>build_sidecar()</code> 从 <code>phases</code> 自动生成侧车</td>
<td class="num">~16 GiB</td><td class="num">首次挂载需转换</td>
<td><b>丢 hkl</b>（<code>march_po</code> 择优取向不可用）；侧车要占额外磁盘（≈重新造一份 peaks）；大库转换耗时未测</td>
</tr>
<tr>
<td><b>C 仅修复</b></td>
<td>保持现有格式与体积，只重跑构建修掉损坏与 NULL</td>
<td class="num">~57 GiB</td><td class="num">348 s</td>
<td>检索性能问题原样保留；Org 仍挂不上 PolyXRD</td>
</tr>
</tbody></table>

<div class="note">
<b>我的建议是 A。</b>B 省的空间最多，但要用 hkl 和首次挂载转换去换，而 hkl 正是 XinMatch 今年新加的择优取向功能的前提；
C 只是把"崩溃"修掉，用户第一次检索就要等 6 分钟，等于没解决。
A 把 57 GiB 压到 40 GiB，检索进到 1 分钟内，两边能力都不丢。
</div>

<h2 class="sec">六、重建的前置条件</h2>
<ol>
<li><b>上游同步</b>：本机已无 rsync / wget（<code>C:\\msys64</code> 与本机不符，只剩 curl）。COD/PCOD 要走 rsync 增量需先装便携版 rsync；
否则只能走 HTTP 索引爬取（TCOD 现有脚本可复用，但 160 万文件会很慢）。TCOD 本来就只有 HTTP 一条路。</li>
<li><b>构建门禁</b>：合并后必须跑 <code>PRAGMA integrity_check</code>，且
<code>SELECT COUNT(*) FROM phases WHERE peaks_top_d IS NULL</code> 必须为 0，否则不予交付 —— 这次就是缺这道门禁。</li>
<li><b>验收回归</b>：重建后重跑本次的 19 项 + 双项目实开冒烟（石英/方解石/刚玉 Top-1 命中）。</li>
</ol>

<h2 class="sec">七、三个库的完整性一览</h2>
<table><thead><tr><th style="width:250px">库</th><th style="width:80px">结论</th><th>PRAGMA integrity_check 结果</th></tr></thead><tbody>
<tr><td>3COD-Inorg-20261016.sqlite</td><td>{INORG_J}</td><td>{INORG_INTEG}</td></tr>
<tr><td>3COD-Full-20261015.sqlite</td><td>{FULL_J}</td><td>{FULL_INTEG}</td></tr>
<tr><td>3COD-Org-20261016.sqlite</td><td>{ORG_J}</td><td>{ORG_INTEG}</td></tr>
</tbody></table>
<p class="small">三个库由同一套脚本（<code>build_3cod.py</code> / <code>build_3cod_org.py</code>）分两批构建，
合并阶段统一使用 <code>journal_mode=OFF + synchronous=OFF</code> 且<b>收尾不校验</b>。
Org 是唯一幸存的，说明问题出在构建过程（中断/半提交），而不是数据源。</p>

<p class="small" style="margin-top:36px">原始输出：<code>sync_logs/integrity_inorg_20261019.log</code>、
<code>sync_logs/dbstat_20261019.csv</code>　·　生成于 {time.strftime('%Y-%m-%d %H:%M')}</p>
</div></body></html>
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("written", OUT, len(html))
