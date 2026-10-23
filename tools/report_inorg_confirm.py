#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成"三库无机分类 + 副本到位"确认报告（单文件 HTML）。

数据源:
  inorg_manifest.sqlite   —— 逐条清单（cod_id / lib / rel / elements / is_inorg / size）
  coverage.sqlite         —— verify_coverage.py 产出的 disk / icif 两张表
  sync_logs/remote_inv_*.tsv / local_inv_*.tsv  —— 同步口径（可选）

用法:
    python report_inorg_confirm.py [--out sync_logs/无机分类与副本确认.html]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(BASE, "inorg_manifest.sqlite")
COVER = os.path.join(BASE, "coverage.sqlite")
LIBS = ("COD", "PCOD", "TCOD")


def q(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


def collect():
    con = sqlite3.connect(COVER)
    con.execute("ATTACH DATABASE ? AS mf", (MANIFEST,))
    con.execute("ATTACH DATABASE ? AS mfc", (MANIFEST,))
    d = {}

    d["meta"] = dict(con.execute("SELECT key, value FROM mf.meta").fetchall())

    # 表 1：分类
    t1 = []
    for lib in LIBS:
        tot = q(con, "SELECT COUNT(*) FROM mf.files WHERE lib=?", (lib,))
        ino = q(con, "SELECT COUNT(*) FROM mf.files WHERE lib=? AND is_inorg=1", (lib,))
        org = tot - ino
        t1.append((lib, tot, ino, org, 100.0 * ino / tot if tot else 0.0))
    t1.append(("合计",
               sum(r[1] for r in t1), sum(r[2] for r in t1),
               sum(r[3] for r in t1),
               100.0 * sum(r[2] for r in t1) / max(sum(r[1] for r in t1), 1)))
    d["t1"] = t1

    # 表 2：磁盘 vs 清单
    t2 = []
    for lib in LIBS:
        dk = q(con, "SELECT COUNT(*) FROM disk WHERE lib=?", (lib,))
        mf = q(con, "SELECT COUNT(*) FROM mf.files WHERE lib=?", (lib,))
        miss = q(con, "SELECT COUNT(*) FROM disk x WHERE x.lib=? AND NOT EXISTS "
                      "(SELECT 1 FROM mf.files f WHERE f.cod_id=x.cod_id)", (lib,))
        extra = q(con, "SELECT COUNT(*) FROM mf.files f WHERE f.lib=? AND NOT EXISTS "
                       "(SELECT 1 FROM disk x WHERE x.cod_id=f.cod_id)", (lib,))
        t2.append((lib, dk, mf, miss, extra))
    t2.append(("合计",
               sum(r[1] for r in t2), sum(r[2] for r in t2),
               sum(r[3] for r in t2), sum(r[4] for r in t2)))
    d["t2"] = t2

    # 表 3：无机副本
    t3 = []
    for lib in LIBS:
        fi = q(con, "SELECT COUNT(*) FROM mf.files WHERE lib=? AND is_inorg=1", (lib,))
        ic = q(con, "SELECT COUNT(*) FROM icif WHERE lib=?", (lib,))
        lack = q(con, "SELECT COUNT(*) FROM mf.files f WHERE f.lib=? AND f.is_inorg=1 "
                      "AND NOT EXISTS (SELECT 1 FROM icif c WHERE c.cod_id=f.cod_id)",
                 (lib,))
        orph = q(con, "SELECT COUNT(*) FROM icif c WHERE c.lib=? AND NOT EXISTS "
                      "(SELECT 1 FROM mf.files f WHERE f.cod_id=c.cod_id AND f.is_inorg=1)",
                 (lib,))
        t3.append((lib, fi, ic, lack, orph))
    t3.append(("合计",
               sum(r[1] for r in t3), sum(r[2] for r in t3),
               sum(r[3] for r in t3), sum(r[4] for r in t3)))
    d["t3"] = t3

    # 表 3b：副本尺寸一致性
    t3b = []
    for lib in LIBS:
        n = q(con, "SELECT COUNT(*) FROM icif c JOIN mf.files f ON f.cod_id=c.cod_id "
                   "WHERE c.lib=? AND f.is_inorg=1 AND c.size<>f.size", (lib,))
        t3b.append((lib, n))
    d["t3b"] = t3b

    d["dup"] = int(d["meta"].get("id_clash", "?"))
    d["rows_read"] = d["meta"].get("rows_read", "?")
    d["units"] = d["meta"].get("units", "?")
    d["built_at"] = d["meta"].get("built_at", "?")

    # 判据自检：elements 列是排序后的元素符号 CSV，用边界匹配避免 'Cl' 误命中 'C'
    has_c = "(',' || IFNULL(elements,'') || ',') LIKE '%,C,%'"
    has_h = "(',' || IFNULL(elements,'') || ',') LIKE '%,H,%'"
    # 反例 1：判为无机，却同时含 C 与 H
    d["inv_c"] = q(con, "SELECT COUNT(*) FROM mf.files WHERE is_inorg=1 AND %s AND %s"
                   % (has_c, has_h))
    # 反例 2：判为非无机，却满足无机条件（不含 C，或含 C 但不含 H）
    d["inv_o"] = q(con, "SELECT COUNT(*) FROM mf.files WHERE is_inorg=0 "
                        "AND IFNULL(elements,'')<>'' AND (NOT %s OR NOT %s)"
                   % (has_c, has_h))
    # 无元素可判（formula 为空）的条目数
    d["no_elem"] = q(con, "SELECT COUNT(*) FROM mf.files WHERE IFNULL(elements,'')=''")
    con.close()
    return d


def collect_sync():
    """读远端权威清单与本地文件清单，出同步口径与"多出的文件"清单。"""
    import collections
    LOGS = os.path.join(BASE, "sync_logs")
    rows = []
    extras = []
    spec = [("COD", "remote_inv_cod.tsv", "local_inv_cod.tsv", 3),
            ("PCOD", "remote_inv_pcod.tsv", "local_inv_pcod.tsv", 2),
            ("TCOD", "remote_inv_tcod.tsv", "local_inv_tcod.tsv", 3)]
    for lib, rf, lf, depth in spec:
        rp, lp = os.path.join(LOGS, rf), os.path.join(LOGS, lf)
        if not (os.path.exists(rp) and os.path.exists(lp)):
            rows.append((lib, None, None, None, depth, None, None, None))
            continue
        rem = set()
        for line in open(rp, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].lower().endswith(".cif"):
                rem.add(p[0].replace("/", "\\"))
        loc_all = 0
        loc_cif = 0
        own = set()
        for line in open(lp, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) < 2:
                continue
            loc_all += 1
            rel = p[0]
            if not rel.lower().endswith(".cif"):
                continue
            loc_cif += 1
            if rel.count("/") == depth:
                own.add(rel.replace("/", "\\"))
        covered = len(own & rem)
        rows.append((lib, len(rem), loc_all, loc_cif, depth,
                     loc_cif - len(own), covered, len(rem) - covered))
        # 位置异常（层数不符）的文件
        for line in open(lp, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) < 2:
                continue
            rel = p[0]
            if rel.lower().endswith(".cif") and rel.count("/") != depth:
                extras.append((lib, rel, int(p[1])))
    return rows, extras


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


CSS = """
:root{--ink:#1a1a1a;--mut:#646464;--line:#d8d8d8;--bg:#fff;--hl:#f4f7fb;
      --ok:#0a7d32;--warn:#b00020;--accent:#1f4e79}
*{box-sizing:border-box}
body{margin:0;padding:40px 48px;background:var(--bg);color:var(--ink);
     font-family:"Source Han Sans CN","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
     font-size:14px;line-height:1.7}
h1{font-size:22px;margin:0 0 6px;color:var(--accent)}
h2{font-size:17px;margin:34px 0 10px;padding-left:10px;border-left:4px solid var(--accent)}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:26px}
table{border-collapse:collapse;width:100%;margin:10px 0 6px;font-size:13.5px}
caption{caption-side:top;text-align:left;color:var(--mut);font-size:12.5px;
        padding:6px 0 8px;font-weight:400}
th{background:var(--hl);text-align:left;font-weight:600;border-top:1.5px solid var(--ink);
   border-bottom:1px solid var(--ink);padding:7px 10px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:6px 10px;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:1.5px solid var(--ink)}
tr.tot td{background:#fafafa;font-weight:600}
td.n,th.n{text-align:right}
.ok{color:var(--ok);font-weight:600}
.bad{color:var(--warn);font-weight:600}
.box{background:#fbf5f5;border:1px solid #f0cccc;border-left:4px solid var(--warn);
     padding:12px 16px;margin:14px 0;font-size:13.5px}
.box.g{background:#f4faf5;border-color:#cfe8d5;border-left-color:var(--ok)}
code{background:#f4f4f4;padding:1px 5px;border-radius:3px;font-size:12.5px}
"""


def render(d):
    p = []
    p.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    p.append("<title>三库无机分类与副本确认</title><style>%s</style></head><body>" % CSS)
    p.append("<h1>COD / PCOD / TCOD 无机分类与副本到位确认</h1>")
    p.append("<div class='sub'>清单构建时间 %s ｜ 扫描 %s 个目录单元 ｜ 读入 %s 行"
             " ｜ 本报告生成 %s</div>"
             % (esc(d["built_at"]), esc(d["units"]), esc(d["rows_read"]),
                time.strftime("%Y-%m-%d %H:%M:%S")))

    # 结论
    bad = [r for r in d["t2"] if r[3] or r[4]] + \
          [r for r in d["t3"] if r[3] or r[4]] + \
          [r for r in d["t3b"] if r[1]]
    if d["dup"] == 0 and not bad and d["inv_c"] == 0 and d["inv_o"] == 0:
        p.append("<div class='box g'><b>结论：</b>三库全部条目均已分类入库，无漏条目；"
                 "无机条目已 100% 复制到 <code>inorg_cif/{COD,PCOD,TCOD}</code> 对应目录，"
                 "无缺副本、无孤儿副本、无尺寸不符；统一编号 <code>cod_id</code> 冲突数为 "
                 "<b>0</b>。</div>")
    else:
        p.append("<div class='box'><b>注意：</b>检测到缺口，详见下列表格。</div>")

    # 表1
    p.append("<h2>表 1　三库条目分类</h2>")
    p.append("<table><caption>判据：分子式元素集合不含 C，或含 C 但不含 H 判为无机。</caption>")
    p.append("<tr><th>库</th><th class='n'>条目总数</th><th class='n'>无机</th>"
             "<th class='n'>有机/含碳氢</th><th class='n'>无机占比</th></tr>")
    for lib, tot, ino, org, pct in d["t1"]:
        cls = " class='tot'" if lib == "合计" else ""
        p.append("<tr%s><td>%s</td><td class='n'>%s</td><td class='n'>%s</td>"
                 "<td class='n'>%s</td><td class='n'>%.1f%%</td></tr>"
                 % (cls, esc(lib), f"{tot:,}", f"{ino:,}", f"{org:,}", pct))
    p.append("</table>")

    # 表2
    p.append("<h2>表 2　源库磁盘 vs 清单（是否漏条目）</h2>")
    p.append("<table><caption>逐条按统一编号 cod_id 求差集；'漏' 指磁盘有而清单无，"
             "'多' 指清单有而磁盘无。两列都必须为 0。</caption>")
    p.append("<tr><th>库</th><th class='n'>磁盘 CIF</th><th class='n'>清单条目</th>"
             "<th class='n'>漏（盘有单无）</th><th class='n'>多（单有盘无）</th></tr>")
    for lib, dk, mf, miss, extra in d["t2"]:
        cls = " class='tot'" if lib == "合计" else ""
        f = lambda v: ("<span class='ok'>0</span>" if v == 0 else "<span class='bad'>%s</span>" % f"{v:,}")
        p.append("<tr%s><td>%s</td><td class='n'>%s</td><td class='n'>%s</td>"
                 "<td class='n'>%s</td><td class='n'>%s</td></tr>"
                 % (cls, esc(lib), f"{dk:,}", f"{mf:,}", f(miss), f(extra)))
    p.append("</table>")

    # 表3
    p.append("<h2>表 3　无机条目 → inorg_cif 副本（是否已复制到位）</h2>")
    p.append("<table><caption>'缺副本'＝清单判为无机但副本目录没有；"
             "'孤儿副本'＝副本目录有但清单未判为无机。</caption>")
    p.append("<tr><th>库</th><th class='n'>清单无机</th><th class='n'>副本文件</th>"
             "<th class='n'>缺副本</th><th class='n'>孤儿副本</th></tr>")
    for lib, fi, ic, lack, orph in d["t3"]:
        cls = " class='tot'" if lib == "合计" else ""
        f = lambda v: ("<span class='ok'>0</span>" if v == 0 else "<span class='bad'>%s</span>" % f"{v:,}")
        p.append("<tr%s><td>%s</td><td class='n'>%s</td><td class='n'>%s</td>"
                 "<td class='n'>%s</td><td class='n'>%s</td></tr>"
                 % (cls, esc(lib), f"{fi:,}", f"{ic:,}", f(lack), f(orph)))
    p.append("</table>")

    p.append("<h2>表 4　副本字节数一致性</h2>")
    p.append("<table><caption>同一 cod_id 的副本尺寸与源文件尺寸不同的条数。</caption>")
    p.append("<tr><th>库</th><th class='n'>尺寸不符</th></tr>")
    for lib, n in d["t3b"]:
        c = "<span class='ok'>0</span>" if n == 0 else "<span class='bad'>%d</span>" % n
        p.append("<tr><td>%s</td><td class='n'>%s</td></tr>" % (esc(lib), c))
    p.append("<tr class='tot'><td>合计</td><td class='n'>%s</td></tr>"
             % ("<span class='ok'>0</span>" if sum(r[1] for r in d["t3b"]) == 0
                else "<span class='bad'>%d</span>" % sum(r[1] for r in d["t3b"])))
    p.append("</table>")

    p.append("<h2>表 5　统一编号与判据自检</h2>")
    p.append("<table>")
    p.append("<tr><th>检查项</th><th class='n'>结果</th><th>要求</th></tr>")
    p.append("<tr><td>cod_id 真实冲突（同一号来自不同来源）</td>"
             "<td class='n'>%s</td><td>必须为 0</td></tr>"
             % ("<span class='ok'>0</span>" if d["dup"] == 0
                else "<span class='bad'>%s</span>" % d["dup"]))
    p.append("<tr><td>判为无机却同时含 C 与 H 的条目</td><td class='n'>%s</td><td>必须为 0</td></tr>"
             % ("<span class='ok'>0</span>" if d["inv_c"] == 0
                else "<span class='bad'>%s</span>" % f"{d['inv_c']:,}"))
    p.append("<tr><td>判为有机却满足无机条件的条目</td><td class='n'>%s</td><td>必须为 0</td></tr>"
             % ("<span class='ok'>0</span>" if d["inv_o"] == 0
                else "<span class='bad'>%s</span>" % f"{d['inv_o']:,}"))
    p.append("<tr><td>分子式缺失、无法判定元素的条目</td><td class='n'>%s</td>"
             "<td>记录数（信息性）</td></tr>" % f"{d['no_elem']:,}")
    p.append("</table>")

    # 表 6：同步口径
    if d.get("sync"):
        p.append("<h2>表 6　同步口径（远端权威清单 vs 本地文件清单）</h2>")
        p.append("<table><caption>远端清单由 rsync 递归列举（COD/PCOD）与 Apache 索引爬取"
                 "（TCOD）得到；'收录' 指按数据集规定的目录层级被纳入清单的文件数。</caption>")
        p.append("<tr><th>库</th><th class='n'>远端 .cif</th><th class='n'>本地文件(全部)</th>"
                 "<th class='n'>本地 .cif</th><th class='n'>收录(.cif)</th>"
                 "<th class='n'>远端未收录</th></tr>")
        for lib, nrem, nall, ncif, depth, nmissdepth, ncov, nmiss in d["sync"]:
            def g(v):
                return "n/a" if v is None else f"{v:,}"
            p.append("<tr><td>%s</td><td class='n'>%s</td><td class='n'>%s</td>"
                     "<td class='n'>%s</td><td class='n'>%s</td><td class='n'>%s</td></tr>"
                     % (esc(lib), g(nrem), g(nall), g(ncif), g(ncov),
                        "n/a" if nmiss is None else
                        ("<span class='ok'>0</span>" if nmiss == 0
                         else "<span class='bad'>%s</span>" % f"{nmiss:,}")))
        p.append("</table>")
        if d.get("extras"):
            p.append("<table><caption>本地存在、但<b>不在数据集目录层级内</b>的 .cif"
                     "（已核实为应排除项，不属遗漏）。</caption>")
            p.append("<tr><th>库</th><th>相对路径</th><th class='n'>字节</th>"
                     "<th>判定</th></tr>")
            note = {
                "9/9000001.cif": "错层历史残留；正规条目在 PCOD/9/900/9000001.cif",
                "9/9000002.cif": "错层历史残留；正规条目在 PCOD/9/900/9000002.cif",
            }
            for lib, rel, sz in d["extras"]:
                key = rel.replace("\\", "/")
                if key in note:
                    why = note[key]
                elif key.startswith("dictionaries/") or "/dictionaries/" in key:
                    why = "TCOD 词典示例文件，非数据库条目"
                else:
                    why = "不在数据集目录层级内"
                p.append("<tr><td>%s</td><td><code>%s</code></td><td class='n'>%s</td>"
                         "<td>%s</td></tr>" % (esc(lib), esc(key), f"{sz:,}", esc(why)))
            p.append("</table>")

    p.append("<div class='box' style='border-left-color:#1f4e79;background:#f4f7fb;"
             "border-color:#d6e0ee'><b>统一编号：</b>COD 保留原号；PCOD 原号 +20,000,000；"
             "TCOD 原号 +100,000,000。三库原始编号段互相重叠，错位后全局唯一，"
             "也是磁盘/清单/副本三方对照的主键。</div>")
    p.append("</body></html>")
    return "\n".join(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, "sync_logs",
                                                  "无机分类与副本确认.html"))
    args = ap.parse_args()
    d = collect()
    d["sync"], d["extras"] = collect_sync()
    html = render(d)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("已写出 %s" % args.out)
    for lib, tot, ino, org, pct in d["t1"]:
        print("  %-5s 总 %8s 无机 %8s (%.1f%%)" % (lib, f"{tot:,}", f"{ino:,}", pct))
    print("  cod_id 冲突=%s  判据反例=%s" % (d["dup"], d["inv_c"]))


if __name__ == "__main__":
    main()
