#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PolyXRD / XinMatch 双项目「实开冒烟」验收（规范 §8 第 8 项）。

用法（本机已装 PolyXRD 源码 E:\\TEMP\\PolyXRD\\src）:
    QT_QPA_PLATFORM=offscreen /e/GSASII/python.exe tools/smoke_two_projects.py

被测对象（只读打开，**不改用户配置、不覆盖随包库**）：
  PolyXRD 侧 Inorg：CIFDatabase._cod_conn 直接注入只读连接
  PolyXRD 侧 Full ：CODLocalDatabase(cod_root=..., db_path=<产物>)
  XinMatch 侧     ：XinMatch 仓库不在本机 → 用其 schema.sql / db_index_build.py
                    复刻同样的 SQL 检索路径（见 --xinmatch-proxy）

为什么要注入连接而不是 set_cod_db_path()：后者会把路径**持久化进用户配置**，
冒烟会污染用户的 PolyXRD 设置。直接给 _cod_conn 赋值是等价的只读注入。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 三个参考物相的实测峰（Cu Kα1，ICDD 卡口径，d/I）──────────────────
REFS = {
    "α-石英 SiO2": {
        "d": [4.2553, 3.3435, 2.4573, 2.2817, 2.2371, 2.1274, 1.9790, 1.8178,
              1.6708, 1.5418],
        "i": [22.0, 100.0, 4.0, 9.0, 4.0, 6.0, 2.0, 14.0, 3.0, 8.0],
        "expect_formula": "O2 Si",
    },
    "方解石 CaCO3": {
        "d": [3.0350, 2.8450, 2.4950, 2.2850, 2.0950, 1.9130, 1.8750, 1.6250],
        "i": [100.0, 14.0, 14.0, 18.0, 18.0, 17.0, 17.0, 8.0],
        "expect_formula": "C Ca O3",
    },
    "刚玉 Al2O3": {
        "d": [2.0850, 2.5510, 1.6014, 3.4795, 2.3790, 1.5470, 2.5488, 1.4027],
        "i": [100.0, 97.0, 82.0, 45.0, 40.0, 80.0, 74.0, 30.0],
        "expect_formula": "Al2 O3",
    },
}

RESULTS: list[tuple] = []

_RE_EL = __import__("re").compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")


def norm_formula(s: str) -> str:
    """把分子式归一到最简整数比，用于跨写法比较。

    例：'C Ca O3' 与 'C6 Ca6 O18'（Z=6 的整胞写法）都归一到 'CCaO3'；
        'Al2 O3' → 'Al2O3'；'O2 Si' → 'O2Si'。
    实测必需：方解石 Top-1 返回的是 'C6 Ca6 O18'，按字面比会误判为 FAIL。
    """
    if not s:
        return ""
    cnt: dict[str, float] = {}
    for sym, n in _RE_EL.findall(s):
        if not sym:
            continue
        try:
            v = float(n) if n else 1.0
        except ValueError:
            v = 1.0
        cnt[sym] = cnt.get(sym, 0.0) + v
    if not cnt:
        return ""
    base = min(cnt.values())
    if base <= 0:
        return ""
    ratio = {k: v / base for k, v in cnt.items()}
    mult = 1
    for m in range(1, 13):
        if all(abs(r * m - round(r * m)) < 1e-3 for r in ratio.values()):
            mult = m
            break
    out = []
    for k in sorted(cnt):
        n = int(round(ratio[k] * mult))
        out.append(k + ("" if n == 1 else str(n)))
    return "".join(out)


def rec(item, ok, detail):
    RESULTS.append((item, ok, detail))
    print("  [%s] %-52s %s" % ("PASS" if ok else "FAIL", item, detail), flush=True)


def open_ro(path):
    con = sqlite3.connect("file:%s?mode=ro" % path.replace(os.sep, "/"),
                          uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    return con


def polyxrd_inorg(path, max_ref_peaks, refs="", skip_open=False,
                  skip_peaks=False):
    sys.path.insert(0, "E:/TEMP/PolyXRD/src")
    from polyxrd.services.cif_database import CIFDatabase
    print("\n=== PolyXRD 实开：3COD-Inorg（CIFDatabase 注入只读连接）===")
    db = CIFDatabase(enable_cod_local=False)
    db._cod_conn = open_ro(path)

    if not skip_open:
        t0 = time.time()
        n = db.cod_phase_count()
        dt = time.time() - t0
        rec("PolyXRD 打开库 / cod_phase_count()", n == 1172085,
            "返回 %s 条（构建值 1,172,085），%.2f s" % (f"{n:,}", dt))

    if not skip_peaks:
        want = [s.strip() for s in refs.split(",") if s.strip()]
        for name, r in REFS.items():
            if want and not any(w in name for w in want):
                continue
            t0 = time.time()
            hits = db.search_cod_by_d_peaks(r["d"], r["i"], tolerance=0.02,
                                            min_match=3, limit=10,
                                            max_ref_peaks=max_ref_peaks)
            dt = time.time() - t0
            if not hits:
                rec("峰匹配 %s（max_ref_peaks=%d）" % (name, max_ref_peaks), False,
                    "无命中；%.2f s" % dt)
                continue
            top = hits[0]
            f = (top.get("formula") or "")
            # 按最简整数比归一后比较，兼容整胞写法（如方解石 'C6 Ca6 O18'）
            want = norm_formula(r["expect_formula"])
            got = norm_formula(f)
            hit = bool(want) and want == got
            rec("峰匹配 %s → Top-1" % name, hit,
                "Top-1 formula=%r（归一 %s，期望 %s）display_id=%s score=%s；%.2f s"
                % (f, got, want,
                   top.get("display_id") or top.get("cod_id"),
                   (top.get("score") if "score" in top else
                    top.get("meas_ratio", "?")), dt))

    # 注意：search_by_formula 只查 PolyXRD 内置矿物词典，不碰外挂库，
    # 不能用来验证库；库里查分子式要用 search_cod_phases（会自动按元素排序规范化）。
    for q in ("O2 Si", "C Ca O3", "Al2 O3"):
        t0 = time.time()
        hits = db.search_cod_phases(q, limit=20)
        dt = time.time() - t0
        rec("search_cod_phases(%r)" % q, bool(hits),
            "%d 条；%.2f s" % (len(hits), dt))

    t0 = time.time()
    hits = db.search_cod_phases("96-101-1097", limit=20)
    dt = time.time() - t0
    rec("search_cod_phases('96-101-1097')", bool(hits),
        "%d 条；%.2f s" % (len(hits), dt))


def polyxrd_full(path):
    print("\n=== PolyXRD 实开：3COD-Full（CODLocalDatabase → cod_entries）===")
    from polyxrd.services.cod_local import CODLocalDatabase
    dbo = CODLocalDatabase(cod_root=os.path.join(BASE, "COD"), db_path=path)
    rec("CODLocalDatabase 初始化", dbo.is_ready(), "is_ready()=%s" % dbo.is_ready())

    for kw, label in ((dict(formula="SiO2"), "formula='SiO2'"),
                      (dict(elements=["Si", "O"]), "elements=['Si','O']"),
                      (dict(space_group="P 63/m"), "space_group='P 63/m'"),
                      (dict(cod_id=2102703), "cod_id=2102703")):
        t0 = time.time()
        try:
            rows = dbo.search(limit=10, **kw)
            dt = time.time() - t0
            rec("CODLocalDatabase.search(%s)" % label, bool(rows),
                "%d 条；%.2f s" % (len(rows), dt))
        except Exception as e:
            rec("CODLocalDatabase.search(%s)" % label, False,
                "%s: %s" % (type(e).__name__, e))

    t0 = time.time()
    try:
        rows = dbo.search_structures("SiO2", limit=10)
        rec("CODLocalDatabase.search_structures('SiO2')", bool(rows),
            "%d 条；%.2f s" % (len(rows), time.time() - t0))
    except Exception as e:
        rec("CODLocalDatabase.search_structures('SiO2')", False,
            "%s: %s" % (type(e).__name__, e))


def xinmatch_proxy(inorg, full):
    """XinMatch 仓库不在本机：按其 schema.sql 复刻同一批检索 SQL 作为代理。"""
    print("\n=== XinMatch 侧（仓库不在本机，按 schema.sql 复刻检索 SQL）===")
    for tag, path in (("Inorg", inorg), ("Full", full)):
        con = open_ro(path)
        for sql, args, label in (
            ("SELECT entry_id, formula, elements FROM entries "
             "WHERE formula=? LIMIT 20", ("O2 Si",), "entries WHERE formula='O2 Si'"),
            ("SELECT e.entry_id, p.d, p.intensity FROM entries e "
             "JOIN peaks p ON p.entry_id=e.entry_id "
             "WHERE e.formula=? ORDER BY p.d DESC LIMIT 20",
             ("O2 Si",), "entries⋈peaks ON formula"),
            ("SELECT entry_id FROM elements WHERE element=? LIMIT 20",
             ("Si",), "elements WHERE element='Si'"),
            ("SELECT COUNT(*) FROM element_combo", (), "element_combo 行数"),
        ):
            t0 = time.time()
            try:
                rows = con.execute(sql, args).fetchall()
                dt = time.time() - t0
                rec("XinMatch-Proxy %s: %s" % (tag, label), True,
                    "%d 行；%.2f s" % (len(rows), dt))
            except sqlite3.Error as e:
                rec("XinMatch-Proxy %s: %s" % (tag, label), False, str(e))
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="20261015")
    ap.add_argument("--max-ref-peaks", type=int, default=40,
                    help="PolyXRD 默认 40；≤64 才会走 peaks_top_* BLOB 预截断路径")
    ap.add_argument("--xinmatch-proxy", action="store_true")
    ap.add_argument("--refs", default="",
                    help="只跑指定参考物相的峰匹配（逗号分隔子串）；空=全部")
    ap.add_argument("--skip-open", action="store_true",
                    help="跳过开库计数（已单独验过）")
    ap.add_argument("--skip-peaks", action="store_true",
                    help="跳过 d-I 峰匹配（单项 10~40 min，机械盘上很慢）")
    args = ap.parse_args()

    inorg = os.path.join(BASE, "3COD-Inorg-%s.sqlite" % args.stamp)
    full = os.path.join(BASE, "3COD-Full-%s.sqlite" % args.stamp)
    for p in (inorg, full):
        if not os.path.exists(p):
            print("! 缺失 %s" % p)
            return 2

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    polyxrd_inorg(inorg, args.max_ref_peaks, refs=args.refs,
                  skip_open=args.skip_open, skip_peaks=args.skip_peaks)
    polyxrd_full(full)
    if args.xinmatch_proxy:
        xinmatch_proxy(inorg, full)

    print("\n" + "=" * 72)
    bad = [r for r in RESULTS if not r[1]]
    print("合计 %d 项，通过 %d，失败 %d" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    for item, _, detail in bad:
        print("   - %s : %s" % (item, detail))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
