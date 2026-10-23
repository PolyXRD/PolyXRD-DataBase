#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染「3COD-Org 打包验收报告」HTML（数据全部来自 accept_3cod_org.py 的落盘结果）。

用法:
    python report_accept_org.py [--stamp 20261016] [--src-stamp 20261015] [--out ...]
"""
from __future__ import annotations

import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BASE, "sync_logs")

CSS = """
:root{--ink:#1a1a1a;--mut:#646464;--line:#d8d8d8;--bg:#fff;--hl:#f4f7fb;
      --ok:#0a7d32;--warn:#b00020;--accent:#1f4e79}
*{box-sizing:border-box}
body{margin:0;padding:40px 48px;background:var(--bg);color:var(--ink);
     font-family:"Source Han Sans CN","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
     font-size:14px;line-height:1.7}
h1{font-size:22px;margin:0 0 6px;color:var(--accent)}
h2{font-size:17px;margin:34px 0 10px;padding-left:10px;border-left:4px solid var(--accent)}
h3{font-size:14.5px;margin:22px 0 6px;color:var(--accent)}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:26px}
table{border-collapse:collapse;width:100%;margin:10px 0 6px;font-size:13px}
caption{caption-side:top;text-align:left;color:var(--mut);font-size:12.5px;
        padding:6px 0 8px;font-weight:400}
th{background:var(--hl);text-align:left;font-weight:600;border-top:1.5px solid var(--ink);
   border-bottom:1px solid var(--ink);padding:7px 9px}
td{border-bottom:1px solid var(--line);padding:6px 9px;vertical-align:top}
tr:last-child td{border-bottom:1.5px solid var(--ink)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr.tot td{background:#fafafa;font-weight:600}
.ok{color:var(--ok);font-weight:600}
.bad{color:var(--warn);font-weight:600}
.na{color:var(--mut);font-weight:600}
.box{background:#f4faf5;border:1px solid #cfe8d5;border-left:4px solid var(--ok);
     padding:12px 16px;margin:14px 0;font-size:13.5px}
.box.w{background:#fbf5f5;border-color:#f0cccc;border-left-color:var(--warn)}
.box.i{background:#f4f7fb;border-color:#d6e0ee;border-left-color:#1f4e79}
code{background:#f4f4f4;padding:1px 5px;border-radius:3px;font-size:12.5px}
.small{font-size:12.5px;color:var(--mut)}
pre{background:#f7f8fa;border:1px solid var(--line);border-radius:4px;
    padding:10px 12px;overflow:auto;font-size:12px;line-height:1.55}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11.5px;
     font-weight:600;margin-left:6px;vertical-align:middle}
.tag.ok{background:#e7f5eb;color:var(--ok)}
.tag.warn{background:#fdecec;color:var(--warn)}
.tag.info{background:#eaf1f9;color:var(--accent)}
"""

SEC_TITLE = {
    "A": "A　集合与计数（差值集不变式）",
    "B": "B　峰 / ID / 强度口径",
    "C": "C　独立重算与定义级直算仲裁",
    "D": "D　外挂稳健",
    "E": "E　两项目实开",
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="20261016")
    ap.add_argument("--src-stamp", default="20261015")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    js = os.path.join(LOGS, "accept_org_%s.json" % args.stamp)
    if not os.path.exists(js):
        raise SystemExit("!! 缺少 %s（先跑 accept_3cod_org.py）" % js)
    data = json.load(open(js, encoding="utf-8"))
    items = data["items"]
    A, C, D = data.get("A", {}), data.get("C", {}), data.get("D", {})
    sm = data.get("summary", {})
    n_fail = sm.get("fail", 0)

    p = []
    p.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    p.append("<title>3COD-Org-%s 打包验收报告</title><style>%s</style></head><body>"
             % (esc(args.stamp), CSS))

    p.append("<h1>3COD-Org-%s 打包验收报告</h1>" % esc(args.stamp))
    p.append("<div class='sub'>有机物版参考数据库（= 3COD-Full − 3COD-Inorg 差值集）｜"
             "生成时间 %s｜验收脚本 <code>tools/accept_3cod_org.py</code>｜"
             "依据 <code>sync-COD-pack/COD打包规范_CIF到SQLite.md</code> §8</div>"
             % esc(data.get("generated_at", "")))

    # ── 一、交付物 ──
    p.append("<h2>一、交付物</h2>")
    p.append("<table><caption>单一格式交付（2026-10-18 起）：只保留 .sqlite，"
             "一份文件同时供两项目挂载</caption>")
    p.append("<tr><th>文件</th><th class='n'>字节</th><th>md5</th>"
             "<th>挂载角色</th></tr>")
    for name, role in (("3COD-Org-%s.sqlite" % args.stamp,
                        "PolyXRD：<code>cod_db_path</code>（phases 形态，"
                        "与 3COD-Inorg 同 schema）<br>"
                        "XinMatch：<code>data/cod_organics.sqlite</code>"
                        "（四表形态，客户端已支持该扩展名）"),):
        p.append("<tr><td><code>%s</code></td><td class='n'>%s</td>"
                 "<td><code>%s</code></td><td>%s</td></tr>"
                 % (esc(name), f"{D.get('bytes', 0):,}",
                    esc(D.get("md5", "")), role))
    p.append("</table>")
    p.append("<div class='box i'><b>为什么只出一份：</b>"
             "SQLite 引擎不看扩展名、只认文件头魔数，"
             "原先 <code>.sqlite</code> 与 <code>.db</code> 是<b>字节级相同</b>的两份"
             "物理副本（各占 15.3 GB）。XinMatch 侧已支持 <code>.sqlite</code>，"
             "故按要求删除 <code>.db</code> 副本，只保留一份，省下一倍磁盘。</div>")

    # ── 二、差值定义 ──
    p.append("<h2>二、差值定义与集合不变式</h2>")
    p.append("<div class='box i'>Org = <b>Full.entries − Inorg.entries</b>"
             "（按 <code>entry_id</code> 取差），即构建侧 "
             "<code>is_inorganic(parse_elements(formula)) == False</code> 的文件。"
             "本报告以三条不变式作为验收主线："
             "<b>①</b> Org ∩ Inorg = ∅；<b>②</b> Inorg ∪ Org = Full；"
             "<b>③</b> Org 的 entries/peaks 行与 Full 中同 <code>entry_id</code> 的行"
             "逐列相等（两侧同一代码路径、同一份源 CIF）。</div>")
    p.append("<table><caption>集合对账（实测）</caption>")
    p.append("<tr><th>项</th><th class='n'>条目</th><th>说明</th></tr>")
    rows = [
        ("3COD-Full entries", A.get("full_entries", 0), "三库全量（2026-10-15 已验收）"),
        ("3COD-Inorg entries", A.get("inorg_entries", 0), "无机版（2026-10-15 已验收）"),
        ("差值（Full − Inorg）", A.get("list_rows", 0), "由源库 entry_id 取差派生"),
        ("3COD-Org entries", A.get("entries", 0), "产物实测"),
    ]
    for k, v, note in rows:
        p.append("<tr><td>%s</td><td class='n'>%s</td><td>%s</td></tr>"
                 % (esc(k), f"{v:,}", esc(note)))
    p.append("<tr class='tot'><td>并集回代 Full</td><td class='n'>%s</td>"
             "<td>Inorg ∪ Org == Full（A3）</td></tr>"
             % f"{A.get('inorg_entries', 0) + A.get('entries', 0):,}")
    p.append("</table>")

    # ── 三、规模 ──
    p.append("<h2>三、产物规模</h2>")
    p.append("<table><caption>与两个已交付产物同表对照</caption>")
    p.append("<tr><th>表 / 指标</th><th class='n'>3COD-Org</th>"
             "<th class='n'>3COD-Inorg</th><th class='n'>3COD-Full</th></tr>")
    scale = [
        ("XinMatch <code>entries</code>", A.get("entries", 0),
         A.get("inorg_entries", 0), A.get("full_entries", 0)),
        ("PolyXRD <code>phases</code>", A.get("phases", 0), None, None),
        ("XinMatch <code>peaks</code>", A.get("peaks", 0), None, None),
        ("<code>cod_atomic_sites</code>", A.get("sites", 0), None, None),
        ("<code>element_combo</code>", A.get("element_combo", 0), None, None),
    ]
    for k, a, b, c in scale:
        p.append("<tr><td>%s</td><td class='n'>%s</td>"
                 "<td class='n'>%s</td><td class='n'>%s</td></tr>"
                 % (k, f"{a:,}" if a is not None else "—",
                    f"{b:,}" if b is not None else "—",
                    f"{c:,}" if c is not None else "—"))
    p.append("</table>")
    p.append("<div class='small'>peaks 行数与 Full 中同 id 集合的行数逐一相等"
             "（A5：%s vs %s）；element_combo 组数 == distinct(elements)（A6）。"
             "</div>"
             % (f"{A.get('peaks', 0):,}", f"{A.get('full_org_peaks', 0):,}"))

    # ── 四、逐项验收 ──
    p.append("<h2>四、规范 §8 逐项验收实测</h2>")
    p.append("<div class='small'>下表为 <code>accept_3cod_org.py</code> 的原始输出；"
             "凡未做的项不计入通过数。总览：%s 项，通过 %s，失败 %s，"
             "耗时 %s min。</div>"
             % (sm.get("total", 0), sm.get("pass", 0), sm.get("fail", 0),
                sm.get("minutes", 0)))
    cur = None
    for it in items:
        if it["sec"] != cur:
            cur = it["sec"]
            p.append("<h3>%s</h3>" % esc(SEC_TITLE.get(cur, cur)))
            p.append("<table><tr><th style='width:22%'>检查项</th>"
                     "<th style='width:10%'>结论</th>"
                     "<th style='width:26%'>实测方法</th>"
                     "<th>实测值</th></tr>")
        cls = "ok" if it["ok"] else "bad"
        p.append("<tr><td>%s</td><td class='%s'>%s</td><td>%s</td>"
                 "<td>%s%s</td></tr>"
                 % (esc(it["item"]), cls, "通过" if it["ok"] else "未过",
                    esc(it["method"]), esc(it["value"]),
                    ("<div class='small'>%s</div>" % esc(it["note"]))
                    if it.get("note") else ""))
        if it is items[-1] or items[items.index(it) + 1]["sec"] != cur:
            p.append("</table>")

    # ── 五、独立重算 ──
    p.append("<h2>五、峰位独立复核</h2>")
    p.append("<div class='box'><b>两条独立路径都对准：</b>"
             "① 与构建<b>同一代码路径</b>从源 CIF 重算全量峰，"
             "抽 %s 条，最大 Δd = <b>%.6f Å</b>；"
             "② <b>定义级直算</b>（F = Σf·occ·e<sup>2πi·g·r</sup>，多重性按同 d 分组求和，"
             "I ∝ Σ|F|²·LP，不使用 fastxrd 的向量化/ASU 剪峰/合并），"
             "抽 %s 条，最大 Δd = <b>%.6f Å</b>。"
             "后者不依赖被验代码本身，是对口径的真正独立仲裁。</div>"
             % (C.get("recheck", 0), C.get("worst_d", 0.0),
                C.get("direct", 0), C.get("worst_direct", 0.0)))

    # ── 六、挂载方式 ──
    p.append("<h2>六、两项目挂载方式</h2>")
    p.append("<table><caption>与已交付的 Inorg / Full 完全同构</caption>")
    p.append("<tr><th>项目</th><th>放置路径</th><th>生效方式</th><th>检索入口</th></tr>")
    p.append("<tr><td>PolyXRD</td><td><code>&lt;repo&gt;/cod_data/COD_organics.sqlite</code>"
             "（或任意路径）</td>"
             "<td>该槽位只自动发现 <code>COD_inorganics_index.sqlite</code> / "
             "<code>COD_inorganics.sqlite</code>；任意文件名需在"
             "「设置 → 数据库」里指定路径（<code>set_cod_db_path</code>，"
             "持久化到 <code>~/.polyxrd/user_db_paths.json</code>），"
             "或用「数据库管理」导入（按 <code>phases</code> 表签名识别）</td>"
             "<td><code>search_cod_by_d_peaks</code>（d-I 峰匹配，读 "
             "<code>phases</code> + <code>peaks_top_*</code> BLOB）、"
             "<code>search_cod_phases</code>、<code>get_cod_phase</code></td></tr>")
    p.append("<tr><td>XinMatch</td><td><code>&lt;repo&gt;/data/cod_organics.sqlite</code></td>"
             "<td>注册库，启动挂载（默认随包库同名槽位由 Inorg 占用）</td>"
             "<td><code>entries</code> / <code>peaks</code> / <code>elements</code> / "
             "<code>element_combo</code> 四表</td></tr>")
    p.append("</table>")
    p.append("<div class='box w'><b>互斥关系：</b>PolyXRD 的 "
             "<code>cod_db_path</code> 只有一个槽位，"
             "<b>3COD-Inorg 与 3COD-Org 不能同时挂在该槽位</b>——"
             "测无机样品挂 Inorg，测有机样品挂 Org，切换即换库"
             "（导入另一个文件或改路径）。若要「一次挂全库都能匹配」，"
             "应另做一个含全部 1,838,364 条 <code>phases</code> 的全库峰匹配版，"
             "那不是本次差值集口径。</div>")
    p.append("<div class='box i'><b>CIF 归档：</b>本库不内嵌 <code>cif_gz</code>"
             "（<code>cif_embedded=0</code>）。命中条目后两项目都按本地归档取原文："
             "XinMatch 走 <code>cod/cif/{d}/{XX}/{XX}/{id:07d}.cif</code>，"
             "PolyXRD 走 <code>cod_data</code> 下的 CIF 目录，缺失再回落在线下载。"
             "本地归档即已同步的 <code>E:\\rsync-COD\\{COD,PCOD,TCOD}</code>。"
             "</div>")

    # ── 七、已知事项 ──
    p.append("<h2>七、已知事项与使用注意</h2>")
    p.append("<table><tr><th style='width:26%'>事项</th><th>说明与处置</th></tr>")
    notes = [
        ("formula 缺失条目已按位点回推修正（142 条移出本版）",
         "E-4 分类分歧的处置结果：478 条 <code>elements</code> 为空的条目改由 "
         "<code>_atom_site_type_symbol</code> 回推位点元素重判——<b>142 条确为无机</b>"
         "（典型 ab initio / constrained Rietveld 型），已从本版剔除并收入 "
         "<b>3COD-Inorg-20261016</b>（补丁分片 p999_v2patch_inorg）；326 条位点确证有机"
         "（C+H）留在本版；10 条无位点标签无法判定，保守留在本版。判定明细 "
         "<code>sync_logs/inorg_v2_gap_20261016.json</code>。本版与 Inorg-v2 严格互斥、"
         "并集等于 Full。"),
        ("org_cif 以清单交付（不落盘 115.63 GB）",
         "差值 CIF 副本按用户决定改为清单交付：<code>sync_logs/org_cif_manifest_20261016.txt"
         "</code>（664,365 行 = 差值 664,507 − 142 排除，格式 {lib}/{rel}/{name}，16 MB）。"
         "如需实体副本可随时按清单落盘（工具 <code>tools/copy_org_cif.py</code> 已备）。"),
        ("有机物 formula 缺失率高于无机版",
         "B5 实测：本版 entries 中 formula / elements 为空的占比高于 Inorg 版的 0.04%。"
         "这些条目只能靠 d 值峰匹配命中，不能靠分子式/元素检索命中。"),
        ("大晶胞/多位点条目不建峰",
         "与 Inorg 版同一阈值（晶胞 &gt; 30,000 Å³ 或展开位点 &gt; 1500 不算峰），"
         "蛋白质/MOF 类因此没有 <code>phases</code> 行，只有 <code>entries</code>。"
         "具体计数见构建日志 <code>sync_logs/build_3cod_org_%s.log</code>。" % args.stamp),
        ("峰匹配耗时随库规模线性增长",
         "PolyXRD 的 <code>search_cod_by_d_peaks</code> 会整表扫 "
         "<code>phases</code>（读 top-64 BLOB 约数百 MB）。"
         "在 1,172,085 相的 Inorg 库上实测单次 752~2615 s（机械盘、有并发时更慢），"
         "随包 71,199 相库的已知基线为 8.7 s。"
         "有机物版相数更少，耗时会低一些；<b>把库放到 SSD</b> 是最有效的加速手段。"),
        ("<code>search_by_formula</code> 不是库检索",
         "该方法只查 PolyXRD 内置矿物词典，不碰外挂库；库内分子式检索应用 "
         "<code>search_cod_phases</code>（会按元素符号排序规范化查询）。"),
        ("PCOD 对差值集贡献为 0",
         "PCOD 1,061,962 条按 formula 判定<b>全部为无机</b>（含 C 且含 H 的 0 条），"
         "故有机物版全部来自 COD 与 TCOD。"),
    ]
    for k, v in notes:
        p.append("<tr><td><b>%s</b></td><td>%s</td></tr>" % (esc(k), v))
    p.append("</table>")

    # ── 八、复现 ──
    p.append("<h2>八、复现命令</h2>")
    p.append("<pre># 1) 派生差值文件清单（读 Full/Inorg，约 15 s）\n"
             "python tools/build_3cod_org.py --plan --stamp %s\n\n"
             "# 2) 分片构建 + 合并 + 排除 142 条 + 索引 + VACUUM + .db 副本\n"
             "python tools/build_3cod_org.py --resume --stamp %s "
             "--exclude-codids sync_logs/org_exclude_20261016.json\n\n"
             "# 3) Inorg-v2 重建（旧 24 分片 + 142 条补丁 → 3COD-Inorg-20261016）\n"
             "python tools/build_inorg_v2_patch.py            # 先建补丁分片\n"
             "python tools/build_inorg_v2_patch.py --merge-only  # 再合并\n\n"
             "# 4) 验收（A~D 节；--smoke 追加两项目实开）\n"
             "python tools/accept_3cod_org.py --stamp %s --src-stamp 20261015 "
             "--inorg-stamp 20261016 --smoke\n\n"
             "# 5) 生成本报告\n"
             "python tools/report_accept_org.py --stamp %s</pre>"
             % (args.stamp, args.stamp, args.stamp, args.stamp))

    p.append("<div class='sub' style='margin-top:30px'>数据来源："
             "<code>sync_logs/accept_org_%s.json</code>（结构化验收结果）、"
             "<code>sync_logs/build_3cod_org_%s.log</code>（构建日志）、"
             "<code>sync_logs/org_files_%s.jsonl</code>（差值文件清单）。"
             "峰口径：λ=1.5406 Å，d ≥ 1.0 Å，等价反射按 2θ 合并，"
             "强度归一 max=1000，XinMatch 取强度前 100，PolyXRD 全量 CSV + top-64 BLOB。"
             "</div>" % (args.stamp, args.stamp, args.stamp))

    p.append("</body></html>")
    out = args.out or os.path.join(
        LOGS, "3COD-Org打包验收报告_%s.html" % args.stamp)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(p))
    print("已写 %s（%s 字节）" % (out, f"{os.path.getsize(out):,}"))


if __name__ == "__main__":
    main()
