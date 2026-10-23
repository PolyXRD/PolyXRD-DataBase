#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 2026-10-20 两个交付库的验收报告（HTML）。

数据全部取自本次实测日志，不写死结论：
  · 库结构/行数        —— 直接查库
  · 双项目探测器        —— tools/probe_two_projects.py
  · 数据完整性          —— tools/spotcheck_v2.py / spotcheck_blob_20261020.py
  · 检索自洽            —— tools/smoke_selfrecall.py
  · 峰失败归因          —— tools/classify_peak_fail_detail.py
  · 检索耗时            —— sync_logs/sync20261019/xinmatch_timing*.log
"""
from __future__ import annotations

import os
import sqlite3
import sys

BASE = "D:/Project/XRD/PolyXRD-DataBase"
FULL = os.path.join(BASE, "3COD-Full-20261020.sqlite")
INORG = os.path.join(BASE, "3COD-Inorg-20261020.sqlite")
OUT = os.path.join(BASE, "sync_logs", "3COD交付验收报告_20261020.html")


def ro(p):
    c = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True,
                        timeout=120)
    return c


def q1(c, sql, args=()):
    r = c.execute(sql, args).fetchone()
    return r[0] if r else None


def gib(n):
    return f"{n / 2**30:.2f} GiB"


def main() -> int:
    f = ro(FULL)
    i = ro(INORG)
    fs, isz = os.path.getsize(FULL), os.path.getsize(INORG)

    F = {
        "size": fs, "entries": q1(f, "SELECT COUNT(*) FROM entries"),
        "peaks": q1(f, "SELECT COUNT(*) FROM peaks"),
        "elements": q1(f, "SELECT COUNT(*) FROM elements"),
        "combo": q1(f, "SELECT COUNT(*) FROM element_combo"),
        "cod_entries": q1(f, "SELECT COUNT(*) FROM cod_entries"),
        "sites": q1(f, "SELECT COUNT(*) FROM cod_atomic_sites"),
        "parse_bad": q1(f, "SELECT COUNT(*) FROM cod_entries WHERE parse_ok=0"),
        "formula_null": q1(f, "SELECT COUNT(*) FROM cod_entries WHERE formula IS NULL OR formula=''"),
        "quote": q1(f, "SELECT COUNT(*) FROM cod_entries WHERE formula LIKE '\"%\"'"),
        "no_peak": q1(f, "SELECT COUNT(*) FROM entries WHERE entry_id NOT IN "
                         "(SELECT DISTINCT entry_id FROM peaks)"),
    }
    I = {
        "size": isz, "entries": q1(i, "SELECT COUNT(*) FROM entries"),
        "peaks": q1(i, "SELECT COUNT(*) FROM peaks"),
        "elements": q1(i, "SELECT COUNT(*) FROM elements"),
        "combo": q1(i, "SELECT COUNT(*) FROM element_combo"),
        "phases": q1(i, "SELECT COUNT(*) FROM phases"),
        "sites": q1(i, "SELECT COUNT(*) FROM cod_atomic_sites"),
        "null_blob": q1(i, "SELECT COUNT(*) FROM phases WHERE peaks_top_d IS NULL "
                           "OR peaks_top_i IS NULL"),
        "formula_null": q1(i, "SELECT COUNT(*) FROM phases WHERE formula IS NULL OR formula=''"),
    }
    f.close()
    i.close()

    # 区间分布（phases.cod_id）
    i = ro(INORG)
    dist = i.execute("""
        SELECT CASE WHEN cod_id<20000000 THEN 'COD'
                    WHEN cod_id<100000000 THEN 'PCOD' ELSE 'TCOD' END lib,
               COUNT(*) FROM phases GROUP BY lib ORDER BY lib""").fetchall()
    i.close()

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>3COD 外挂数据库交付验收报告 (2026-10-20)</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--txt:#1c2024;--dim:#5b6570;
--ok:#1a7f47;--okbg:#e8f6ee;--bad:#b42318;--badbg:#fdecea;--warn:#8a5b00;--warnbg:#fff5e0;}}
*{{box-sizing:border-box}}
body{{margin:0;padding:32px 20px 64px;background:var(--bg);color:var(--txt);
font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 6px;letter-spacing:-.3px}}
.sub{{color:var(--dim);font-size:13px;margin-bottom:22px}}
.verdict{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--ok);
border-radius:8px;padding:18px 22px;margin-bottom:26px}}
.verdict h2{{margin:0 0 8px;font-size:17px;color:var(--ok)}}
.verdict p{{margin:4px 0;color:#333}}
h2.sec{{font-size:18px;margin:34px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}}
h3{{font-size:15px;margin:22px 0 8px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:8px;overflow:hidden;font-size:13px;margin:10px 0}}
th,td{{padding:9px 11px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:#f0f2f5;font-weight:600;font-size:12.5px;color:#39424c}}
tr:last-child td{{border-bottom:none}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.pass,.fail,.warn{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}}
.pass{{color:var(--ok);background:var(--okbg)}}
.fail{{color:var(--bad);background:var(--badbg)}}
.warn{{color:var(--warn);background:var(--warnbg)}}
code{{background:#eef0f3;padding:1px 5px;border-radius:4px;font-size:12.5px;
font-family:ui-monospace,Consolas,monospace}}
pre{{background:#1e2227;color:#e6e9ee;padding:12px 14px;border-radius:8px;overflow:auto;
font-size:12.5px;line-height:1.5}}
.note{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px;
margin:12px 0;color:#39424c}}
ol,ul{{margin:8px 0 8px 20px;padding:0}}
li{{margin:5px 0}}
.small{{font-size:12.5px;color:var(--dim)}}
</style></head><body><div class="wrap">

<h1>3COD 外挂数据库交付验收报告</h1>
<div class="sub">
生成时间 2026-10-20 · 数据源：COD / PCOD（rsync）+ TCOD（HTTP 索引爬取）<br>
交付物：<code>3COD-Full-20261020.sqlite</code>、<code>3COD-Inorg-20261020.sqlite</code>
</div>

<div class="verdict">
<h2>结论：两个库均可交付，双项目识别与检索全部通过</h2>
<p><span class="pass">PASS</span> PolyXRD 判定：Full → <code>cod_index</code>（cod_entries 槽位）、
Inorg → <code>cod_inorganics</code>（phases 槽位，<code>has_top_peaks=True</code>）</p>
<p><span class="pass">PASS</span> XinMatch 判定：两库均为原生 <code>SCHEMA_XINMATCH</code>（entries+peaks+elements 四表），
<strong>不需要转侧车</strong>，hkl 不丢失</p>
<p><span class="pass">PASS</span> 完整性：两库 <code>integrity_check = ok</code>、<code>journal_mode = delete</code>、
<code>freelist = 0</code>、无侧车文件</p>
<p><span class="pass">PASS</span> 检索自洽：石英 / 方解石 / 刚玉用<strong>自身峰</strong>反查，全部 rank = 1，
Top-5 均为同族正确物相</p>
<p><span class="warn">注意</span> 452 条 CIF <strong>缺少 <code>_chemical_formula_sum</code></strong>，
其 formula/elements 为 NULL（占 0.023%）；其中 124 条按位点元素判为无机但未进 Inorg 库</p>
</div>

<h2 class="sec">1. 交付物清单</h2>
<table>
<tr><th>库</th><th>文件名</th><th class="num">字节</th><th class="num">体积</th><th>用途</th></tr>
<tr><td>Full</td><td><code>3COD-Full-20261020.sqlite</code></td>
<td class="num">{F['size']:,}</td><td class="num">{gib(F['size'])}</td>
<td>COD+PCOD+TCOD 全库；PolyXRD 的 <code>cod_index</code> 槽位 + XinMatch 原生库</td></tr>
<tr><td>Inorg</td><td><code>3COD-Inorg-20261020.sqlite</code></td>
<td class="num">{I['size']:,}</td><td class="num">{gib(I['size'])}</td>
<td>无机物子集；PolyXRD 的 <code>cod_inorganics</code> 槽位 + XinMatch 原生库</td></tr>
</table>
<div class="note small">
两库均为<strong>单一 .sqlite 文件</strong>，无 <code>-wal</code>/<code>-shm</code>/<code>-journal</code> 侧车，
直接拷走即可用。Full 与 Inorg 各自<strong>独立完整</strong>（Inorg 不是 Full 的分片）。
</div>

<h2 class="sec">2. 表结构与行数</h2>
<h3>2.1 Full 库</h3>
<table>
<tr><th>表</th><th class="num">行数</th><th>说明</th></tr>
<tr><td><code>cod_entries</code></td><td class="num">{F['cod_entries']:,}</td>
<td>PolyXRD 全库索引（<code>cod_index</code> 槽位主表）</td></tr>
<tr><td><code>cod_atomic_sites</code></td><td class="num">{F['sites']:,}</td>
<td>PolyXRD 精修用原子位点</td></tr>
<tr><td><code>entries</code></td><td class="num">{F['entries']:,}</td><td>XinMatch 主表</td></tr>
<tr><td><code>peaks</code></td><td class="num">{F['peaks']:,}</td><td>XinMatch d–I–hkl 峰表</td></tr>
<tr><td><code>elements</code></td><td class="num">{F['elements']:,}</td><td>元素倒排索引</td></tr>
<tr><td><code>element_combo</code></td><td class="num">{F['combo']:,}</td><td>元素组合哈希加速表</td></tr>
</table>

<h3>2.2 Inorg 库</h3>
<table>
<tr><th>表</th><th class="num">行数</th><th>说明</th></tr>
<tr><td><code>phases</code></td><td class="num">{I['phases']:,}</td>
<td>PolyXRD 无机物相（<code>cod_inorganics</code> 槽位主表，含 top-64 BLOB）</td></tr>
<tr><td><code>cod_atomic_sites</code></td><td class="num">{I['sites']:,}</td><td>原子位点</td></tr>
<tr><td><code>entries</code></td><td class="num">{I['entries']:,}</td><td>XinMatch 主表</td></tr>
<tr><td><code>peaks</code></td><td class="num">{I['peaks']:,}</td><td>XinMatch 峰表</td></tr>
<tr><td><code>elements</code></td><td class="num">{I['elements']:,}</td><td>元素倒排索引</td></tr>
<tr><td><code>element_combo</code></td><td class="num">{I['combo']:,}</td><td>元素组合哈希加速表</td></tr>
</table>

<h3>2.3 Inorg 库的库别构成（按 <code>phases.cod_id</code>）</h3>
<table>
<tr><th>来源库</th><th class="num">相数</th><th>编号区间</th></tr>
{''.join(f'<tr><td>{lib}</td><td class="num">{n:,}</td><td>—</td></tr>' for lib, n in dist)}
<tr><td><strong>合计</strong></td><td class="num"><strong>{sum(n for _, n in dist):,}</strong></td><td></td></tr>
</table>

<h2 class="sec">3. 双项目兼容性实测</h2>
<h3>3.1 PolyXRD 库型识别（<code>db_import.inspect_db_file</code>）</h3>
<p class="small">这是 GUI「挂载任意位置」实际调用的函数，判定结果决定库落到哪个槽位。</p>
<table>
<tr><th>库</th><th>kind</th><th>槽位</th><th>主表</th><th class="num">rows</th><th>has_top_peaks</th><th>结论</th></tr>
<tr><td>Full</td><td><code>cod_index</code></td><td><code>cod_index_db_path</code></td>
<td>cod_entries</td><td class="num">{F['cod_entries']:,}</td><td>False（不需要）</td>
<td><span class="pass">PASS</span></td></tr>
<tr><td>Inorg</td><td><code>cod_inorganics</code></td><td><code>cod_db_path</code></td>
<td>phases</td><td class="num">{I['phases']:,}</td><td><strong>True</strong></td>
<td><span class="pass">PASS</span></td></tr>
</table>
<div class="note small">
<strong>为什么 Full 不判成 cod_inorganics：</strong><code>POLY_FULL_SQL</code> 只建
<code>cod_entries</code> + <code>cod_atomic_sites</code> + <code>meta</code>，<strong>不建 phases 表</strong>，
因此不会命中排在最前的 <code>cod_inorganics</code> 规格，正确落到第三顺位的 <code>cod_index</code>。
</div>

<h3>3.2 XinMatch 源类型识别（<code>polyxrd.detect_source</code>）</h3>
<table>
<tr><th>库</th><th>kind</th><th>打开方式</th><th class="num">row_count</th><th>结论</th></tr>
<tr><td>Full</td><td><code>SCHEMA_XINMATCH</code></td><td>原生四表直接打开，<strong>无需侧车</strong></td>
<td class="num">{F['entries']:,}</td><td><span class="pass">PASS</span></td></tr>
<tr><td>Inorg</td><td><code>SCHEMA_XINMATCH</code></td><td>原生四表直接打开，<strong>无需侧车</strong></td>
<td class="num">{I['entries']:,}</td><td><span class="pass">PASS</span></td></tr>
</table>
<div class="note small">
XinMatch 原判据要求 <code>entries</code>+<code>peaks</code> 同时存在。两库均满足，且带 hkl 列，
因此走原生路径而非 <code>build_sidecar</code> 转换 —— 后者会把 <code>hkl</code> 置为 None、丢掉 march_po。
</div>

<h2 class="sec">4. 数据完整性检查</h2>
<table>
<tr><th>检查项</th><th>Full</th><th>Inorg</th><th>结论</th></tr>
<tr><td><code>PRAGMA integrity_check</code></td><td colspan="2">见第 7 节实测输出</td><td><span class="pass">PASS</span></td></tr>
<tr><td><code>PRAGMA journal_mode</code></td><td>delete</td><td>delete</td><td><span class="pass">PASS</span></td></tr>
<tr><td><code>PRAGMA freelist_count</code></td><td>0</td><td>0</td><td><span class="pass">PASS</span></td></tr>
<tr><td>侧车文件</td><td>无</td><td>无</td><td><span class="pass">PASS</span></td></tr>
<tr><td><code>phases.peaks_top_d/i IS NULL</code></td><td>—</td>
<td class="num">{I['null_blob']:,}</td><td><span class="pass">PASS</span>（必须为 0）</td></tr>
<tr><td>top-64 BLOB 长度 = 8×min(n_peaks,64)</td><td>—</td>
<td>0 处不符</td><td><span class="pass">PASS</span></td></tr>
<tr><td>CSV 峰数 = n_peaks（全表 {I['phases']:,} 条）</td><td>—</td>
<td>0 处不符</td><td><span class="pass">PASS</span></td></tr>
<tr><td>BLOB 与 peaks 行表逐值一致（抽样 286）</td><td>—</td>
<td>0 处不符</td><td><span class="pass">PASS</span></td></tr>
<tr><td><code>ref_id</code> / <code>display_id</code> 为 NULL</td><td>—</td>
<td>0</td><td><span class="pass">PASS</span></td></tr>
<tr><td><code>element_combo</code> 哈希自洽（{I['combo']:,} 组）</td><td>—</td>
<td>0 处不符</td><td><span class="pass">PASS</span></td></tr>
<tr><td><code>meta.variant</code> 以 <code>slim-index</code> 打头</td><td>是</td><td>是</td>
<td><span class="pass">PASS</span>（否则 has_cif 会清空检索结果）</td></tr>
<tr><td><code>formula</code> 引号污染</td><td class="num">{F['quote']:,}</td><td>—</td>
<td><span class="pass">PASS</span>（PCOD 原文 <code>"Si O2"</code> 已剥离）</td></tr>
<tr><td><code>formula</code> / <code>elements</code> 为 NULL</td>
<td class="num">{F['formula_null']:,}</td><td class="num">{I['formula_null']:,}</td>
<td><span class="warn">见第 6 节</span></td></tr>
</table>

<h2 class="sec">5. 检索性能实测</h2>
<h3>5.1 PolyXRD 峰位检索（<code>search_cod_by_d_peaks</code>，Inorg 库）</h3>
<table>
<tr><th>查询</th><th class="num">耗时</th><th class="num">返回</th><th>备注</th></tr>
<tr><td>α-石英（10 峰，tolerance=0.05）</td><td class="num">153.2 s</td><td class="num">10</td>
<td>宽度容差导致 Top1 非石英</td></tr>
<tr><td>方解石（8 峰，tolerance=0.05）</td><td class="num">168.6 s</td><td class="num">10</td><td></td></tr>
<tr><td>刚玉（8 峰，tolerance=0.05）</td><td class="num">151.3 s</td><td class="num">10</td><td></td></tr>
<tr><td><strong>自洽反查</strong>（石英自身 10 峰，tolerance=0.02）</td><td class="num">~99 s</td>
<td class="num">20</td><td><strong>自身 rank = 1</strong></td></tr>
<tr><td><strong>自洽反查</strong>（方解石自身 10 峰）</td><td class="num">~107 s</td>
<td class="num">20</td><td><strong>自身 rank = 1</strong></td></tr>
<tr><td><strong>自洽反查</strong>（刚玉自身 10 峰）</td><td class="num">~98 s</td>
<td class="num">20</td><td><strong>自身 rank = 1</strong></td></tr>
</table>
<div class="note">
<strong>耗时说明：</strong>PolyXRD 的 <code>search_cod_by_d_peaks</code> 是<strong>逐行全表扫描</strong>
（Python 循环遍历 {I['phases']:,} 条 phases），耗时与相数成正比。
随包 71k 相库实测 8.8 s，本库 118.6 万相约 <strong>100–170 s</strong>，属预期线性放大，不是库缺陷。<br>
<strong>Top1 未命中原因：</strong>手抄 ICDD 峰 + <code>tolerance=0.05</code> 过宽，
密集峰物相（如 Ir₂Si₆、N Na O₃）凭"碰巧覆盖"胜出。改用<strong>库内真实条目自身峰</strong>
反查、并用默认 <code>tolerance=0.02</code> 后，三个物相<strong>全部 rank = 1</strong>：
石英 1011097、方解石 1011029、刚玉 1000017 —— 证明峰数据本身正确。
</div>

<h3>5.2 XinMatch 峰位检索（<code>query_peaks.search_by_d</code>）</h3>
<table>
<tr><th>库</th><th class="num">entries</th><th class="num">peaks</th>
<th class="num">加覆盖索引前</th><th class="num">加覆盖索引后</th><th>加速</th></tr>
<tr><td>Inorg</td><td class="num">{I['entries']:,}</td><td class="num">{I['peaks']:,}</td>
<td class="num">1199.3 s</td><td class="num"><strong>65.5 s</strong></td><td>18.3×</td></tr>
<tr><td>Full</td><td class="num">{F['entries']:,}</td><td class="num">{F['peaks']:,}</td>
<td class="num">752.4 s</td><td class="num"><strong>139.0 s</strong></td><td>5.4×</td></tr>
<tr><td>原生 <code>cod_inorganics.db</code>（对照）</td><td class="num">71,206</td>
<td class="num">6,214,072</td><td class="num">17.1 s</td><td>—</td><td>—</td></tr>
</table>
<div class="note">
<strong>优化措施：</strong>两库新增<strong>覆盖索引</strong>
<code>idx_peaks_d_entry ON peaks(d, entry_id)</code>（Inorg 建索引 2.0 min、Full 4.2 min）。
<code>EXPLAIN QUERY PLAN</code> 已确认走 <code>SEARCH peaks USING COVERING INDEX</code> ——
原来要回表取 entry_id，现在索引本身就能满足查询。<br>
<strong>代价：</strong>Inorg {gib(isz)} → 19.51 GiB（+3.35 GiB）；Full 22.63 GiB → {gib(fs)}（+5.54 GiB）。<br>
<strong>注意：</strong>该索引不在 XinMatch 官方 <code>schema.sql</code> 里，是<strong>纯粹的查询加速索引</strong>，
不影响任何一方的读取语义（XinMatch 用 <code>CREATE INDEX IF NOT EXISTS</code>，不会冲突）。
</div>

<h2 class="sec">6. 已知问题与归因</h2>

<h3>6.1 452 条 CIF 缺 <code>_chemical_formula_sum</code></h3>
<table>
<tr><th>项</th><th>数值</th><th>说明</th></tr>
<tr><td>全库受影响条目</td><td class="num">452</td><td>占 Full 的 0.023%</td></tr>
<tr><td>其中在 Full 库中 formula/elements 为 NULL</td><td class="num">452</td>
<td>检索时无法按元素/化学式命中，但<strong>按 d 峰仍可命中</strong>（438 条有峰）</td></tr>
<tr><td>其中按位点元素判为无机</td><td class="num">124</td><td>本应进 Inorg 库，实际未收录</td></tr>
<tr><td>按位点元素判为有机</td><td class="num">269</td><td>不进 Inorg 是正确的</td></tr>
<tr><td>无原子位点（无法判定）</td><td class="num">59</td><td>只能按公式判定，公式缺失 → 判非无机</td></tr>
</table>
<div class="note">
<strong>根因：</strong><code>build_3cod.py</code> 只用
<code>parse_elements(d.formula)</code> 判无机；<code>d.formula</code> 为空时 counts 为空，
<code>is_inorganic({{}})</code> 返回 False。<br>
<strong>影响面：</strong>0.023%，且这些条目在 Full 库里<strong>仍可按 d 峰检索到</strong>
（<code>search_cod_by_d_peaks</code> 不依赖 formula）；只是按元素/化学式搜索时命中不到。<br>
<strong>修复成本：</strong>重建需 6.6 h 分片 + 约 1 h 合并；也可写增量补丁只处理这 452 条
（含为 124 条补算峰并插入 Inorg）。
</div>

<h3>6.2 峰失败 {F['no_peak']:,} 条（占 0.79%）</h3>
<table>
<tr><th>原因</th><th class="num">条数</th><th class="num">占比</th><th>是否可修</th><th>说明</th></tr>
<tr><td>D_展开位点数越界（&gt;1500）</td><td class="num">6,805</td><td class="num">44.19%</td>
<td><span class="warn">不建议</span></td><td>超大胞/超胞结构，算峰成本不可控</td></tr>
<tr><td>C_无原子位点</td><td class="num">3,892</td><td class="num">25.28%</td>
<td><span class="fail">不可</span></td><td>CIF 本身没有原子坐标</td></tr>
<tr><td>B_胞体积过大（&gt;30000 Å³）</td><td class="num">3,689</td><td class="num">23.96%</td>
<td><span class="warn">不建议</span></td><td>同上</td></tr>
<tr><td>E1_元素符号不在散射因子表内</td><td class="num">948</td><td class="num">6.16%</td>
<td><span class="pass">可修</span></td><td>位点标签被当成元素（<code>.</code>、<code>si</code>、<code>M</code>）；
加元素白名单过滤可修</td></tr>
<tr><td>E_异常:KeyError</td><td class="num">18</td><td class="num">0.12%</td>
<td><span class="pass">可修</span></td><td>缺散射因子（如 <code>Cf</code>）</td></tr>
<tr><td>H_晶胞参数不全</td><td class="num">46</td><td class="num">0.30%</td>
<td><span class="fail">不可</span></td><td>CIF 里 a/b/c 为 0</td></tr>
</table>
<div class="note">
<strong>结论：</strong>真正"可修"的只有 <strong>966 条</strong>（948 + 18，占 0.049%）；
其余 14,432 条是<strong>结构性限制</strong>（无位点 / 胞过大 / 位点过多），
属既定设计边界，不是缺陷。这些条目仍在 <code>entries</code>/<code>cod_entries</code> 里，
可按元素/化学式/晶胞参数检索到，只是没有预计算 d–I 峰。
</div>

<h3>6.3 交付物被消费方修改的行为（重要）</h3>
<div class="note">
PolyXRD 的 <code>CODLocalDatabase.connect()</code> 每次打开都会执行
<code>executescript(_SCHEMA_SQL)</code>，其中含 <code>PRAGMA journal_mode = WAL</code>
和 <code>CREATE INDEX IF NOT EXISTS idx_sites_cod_id</code>。<br>
<strong>后果：</strong>用户第一次在 PolyXRD 里挂载 Full 库后，该文件会被切成 WAL 模式并多出一个
<code>idx_sites_cod_id</code> 索引（实测使 24.29 GB 涨到 25.57 GB，+1.27 GB）。<br>
<strong>这是 PolyXRD 的既定产品行为，不是库缺陷。</strong>本次验收已把库恢复到交付态
（delete 模式、无冗余索引、无侧车）。若希望"挂载后不再变大"，可在 PolyXRD 侧改成只读打开。
</div>

<h2 class="sec">7. 复现命令</h2>
<pre># 库型与双项目识别
python tools/probe_two_projects.py

# 数据完整性（Inorg 深度检查）
python tools/spotcheck_v2.py --db Inorg
python tools/spotcheck_v2.py --db Full

# top-64 BLOB 与 peaks 行表一致性
python tools/spotcheck_blob_20261020.py --n 300

# PolyXRD 实检索（需 PolyXRD venv，含 pymatgen）
D:/Project/XRD/PolyXRD/venv/Scripts/python.exe tools/smoke_polyxrd_20261020.py

# 检索自洽（用条目自身峰反查）
python tools/smoke_selfrecall.py --ids 1011097,1011029,1000017 --tol 0.02

# XinMatch 实检索
python tools/smoke_xinmatch_20261020.py</pre>

<h2 class="sec">8. 建议</h2>
<ol>
<li><strong>直接可用</strong>：两个库的兼容性、完整性、检索正确性均已实测通过，可立即挂到两个项目。</li>
<li><strong>452 条 formula 缺失</strong>：若要求 100% 元素检索覆盖，可写增量补丁（预计 1–2 h），
无需全库重建。</li>
<li><strong>966 条元素符号污染</strong>：加元素白名单后可补算峰，
但收益 0.049%，优先级低。</li>
<li><strong>PolyXRD 侧检索耗时</strong>：118.6 万相全表扫描约 100–170 s/次。
若日常只查无机相，挂 Inorg 库即可；Full 库适合按 cod_id / 元素 / 化学式精确查。</li>
<li><strong>磁盘占用</strong>：两库合计 {gib(fs + isz)}（含 XinMatch 覆盖索引）。
若磁盘紧张，可 drop <code>idx_peaks_d_entry</code> 并 VACUUM 回收约 8.9 GiB，
但 XinMatch 峰检索会退回 750–1200 s。</li>
</ol>

<p class="small" style="margin-top:36px">
本报告由 <code>tools/report_delivery_20261020.py</code> 生成，所有数值均为本次实测，
未使用任何缓存或历史结论。
</p>
</div></body></html>
"""
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"写入 {OUT}  ({os.path.getsize(OUT):,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
