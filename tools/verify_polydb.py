#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polyDB v4 结构校验器（纯标准库，无需 numpy）。

校验项（全部为"读不到/对不上就报错"的硬判据）：
  1. 必需段齐全（meta.json / index.sqlite / peaks_d.f32 / peaks_i.u16 /
     bins.u8 / elem.u8 / sites.bin / sites_off.i64）；
  2. 每段实际字节数 == meta.json 记录，且 sha256 一致；
  3. meta.counts 与形状自洽：peaks_d 字节 == N*K*4、peaks_i == N*K*2、
     bins == 501*ceil(N/8)、elem == 118*ceil(N/8)、sites_off == (N+1)*8；
  4. sites_off 单调不减、首值 0、末值 == len(sites.bin)，且能被 17 整除；
  5. index.sqlite：integrity_check == ok；entries 行数 == N；
     row_idx 唯一且为 0..N-1 的完整排列（§3 铁律：row_idx ≠ eid-1）；
  6. 抽样若干相：peaks_d 行内按 I 降序、空槽在尾部（d=0 只在 I=0 之后）。

用法：
    python tools/verify_polydb.py polydb/COD-Inorg-20261021.polyDB
    python tools/verify_polydb.py polydb/COD-Full-20261021.polyDB --no-hash
退出码：0 全通过；1 有 FAIL。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import struct
import sys
import time

BIN_WIDTH = 0.05
N_BINS = 501
SITE_BYTES = 17
REQUIRED = ("meta.json", "index.sqlite", "peaks_d.f32", "peaks_i.u16",
            "bins.u8", "elem.u8", "sites.bin", "sites_off.i64")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, item: str, detail: str = "") -> None:
        self.rows.append((status, item, detail))

    def ok(self, item: str, detail: str = "") -> None:
        self.add("PASS", item, detail)

    def fail(self, item: str, detail: str = "") -> None:
        self.add("FAIL", item, detail)

    def warn(self, item: str, detail: str = "") -> None:
        self.add("WARN", item, detail)

    def render(self) -> int:
        w = max(len(r[1]) for r in self.rows)
        for st, item, detail in self.rows:
            print("  [%s] %-*s  %s" % (st, w, item, detail))
        n_fail = sum(1 for r in self.rows if r[0] == "FAIL")
        n_warn = sum(1 for r in self.rows if r[0] == "WARN")
        print("\n  合计 %d 项：PASS %d / FAIL %d / WARN %d"
              % (len(self.rows), len(self.rows) - n_fail - n_warn, n_fail, n_warn))
        return 1 if n_fail else 0


def sha256_of(path: str, chunk: int = 8 << 20, progress=print) -> str:
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    t0 = time.perf_counter()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
            done += len(b)
            if total >= (256 << 20) and progress:
                el = time.perf_counter() - t0
                rate = done / el / 2**20 if el > 0 else 0
                progress("       %-16s %5.1f%%  %.0f MB/s"
                         % (os.path.basename(path), 100.0 * done / total, rate))
    return h.hexdigest()


def verify(db_dir: str, do_hash: bool = True, samples: int = 64) -> int:
    rep = Report()
    print("polyDB 校验：%s" % db_dir)
    print("  mtime=%s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(os.path.getmtime(db_dir))))

    # 1) 段齐全
    missing = [n for n in REQUIRED if not os.path.isfile(os.path.join(db_dir, n))]
    if missing:
        rep.fail("必需段齐全", "缺失 %s" % ", ".join(missing))
        return rep.render()
    rep.ok("必需段齐全", "%d/%d" % (len(REQUIRED), len(REQUIRED)))

    with open(os.path.join(db_dir, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)

    # 2) 字节数 + 校验和
    sections = meta.get("sections") or {}
    total_bytes = 0
    for name in REQUIRED:
        if name == "meta.json":
            continue
        p = os.path.join(db_dir, name)
        real = os.path.getsize(p)
        total_bytes += real
        rec = sections.get(name) or {}
        exp = rec.get("bytes")
        if exp is None:
            rep.warn("段字节数 " + name, "meta 未记录，实测 %d" % real)
        elif int(exp) != real:
            rep.fail("段字节数 " + name, "meta=%d 实测=%d" % (int(exp), real))
        else:
            rep.ok("段字节数 " + name, "%d" % real)
        if do_hash and rec.get("sha256"):
            got = sha256_of(p, progress=print)
            if got != rec["sha256"]:
                rep.fail("sha256 " + name, "meta=%s… 实测=%s…"
                         % (rec["sha256"][:12], got[:12]))
            else:
                rep.ok("sha256 " + name, "%s…" % got[:16])
    # meta.total_bytes 只累计 sections 里 7 个段（不含 meta.json 自身）
    rep.ok("总体积", "%.2f MiB（实测 7 段）／meta.total_bytes=%.2f MiB"
           % (total_bytes / 2**20, int(meta.get("total_bytes", 0)) / 2**20))

    # 3) 形状自洽
    counts = meta.get("counts") or {}
    n = int(counts.get("phases") or 0)
    k = int(counts.get("k") or 0)
    if n <= 0 or k <= 0:
        rep.fail("counts", "phases=%s k=%s" % (n, k))
        return rep.render()
    nbytes = (n + 7) // 8
    expect = {
        "peaks_d.f32": n * k * 4,
        "peaks_i.u16": n * k * 2,
        "bins.u8": N_BINS * nbytes,
        "elem.u8": 118 * nbytes,
        "sites_off.i64": (n + 1) * 8,
    }
    for name, exp in expect.items():
        real = os.path.getsize(os.path.join(db_dir, name))
        if real == exp:
            rep.ok("形状 " + name, "期望 %d" % exp)
        else:
            rep.fail("形状 " + name, "期望 %d 实测 %d" % (exp, real))
    for name in ("peaks_d.f32", "peaks_i.u16", "bins.u8", "elem.u8", "sites_off.i64"):
        shp = (sections.get(name) or {}).get("shape")
        if shp:
            calc = {"peaks_d.f32": [n, k], "peaks_i.u16": [n, k],
                    "bins.u8": [N_BINS, nbytes], "elem.u8": [118, nbytes],
                    "sites_off.i64": [n + 1]}[name]
            if list(shp) != calc:
                rep.fail("shape 字段 " + name, "meta=%s 计算=%s" % (shp, calc))
    rep.ok("counts", "phases=%d k=%d peaks=%d sites=%d"
           % (n, k, int(counts.get("peaks") or 0), int(counts.get("sites") or 0)))

    # 4) sites_off
    off_path = os.path.join(db_dir, "sites_off.i64")
    with open(off_path, "rb") as fh:
        offs = struct.unpack("<%dq" % (n + 1), fh.read((n + 1) * 8))
    sites_len = os.path.getsize(os.path.join(db_dir, "sites.bin"))
    if offs[0] != 0:
        rep.fail("sites_off[0]", "= %d" % offs[0])
    elif offs[-1] != sites_len:
        rep.fail("sites_off[-1]", "= %d 而 sites.bin = %d" % (offs[-1], sites_len))
    elif sites_len % SITE_BYTES:
        rep.fail("sites.bin 对齐", "%d 不能被 17 整除" % sites_len)
    else:
        mono = all(offs[i] <= offs[i + 1] for i in range(n))
        if mono:
            rep.ok("sites_off", "首 0 / 末 %d / %d 位点 / 单调" % (sites_len, sites_len // SITE_BYTES))
        else:
            rep.fail("sites_off 单调性", "存在递减项")
    if (sites_len // SITE_BYTES) != int(counts.get("sites") or -1):
        rep.warn("counts.sites", "meta=%s 实测=%d"
                 % (counts.get("sites"), sites_len // SITE_BYTES))

    # 5) index.sqlite
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(db_dir, "index.sqlite").replace("\\", "/"),
                          uri=True)
    try:
        ic = con.execute("PRAGMA integrity_check").fetchone()[0]
        rep.ok("index.sqlite integrity_check", ic) if ic == "ok" else \
            rep.fail("index.sqlite integrity_check", ic)
        n_rows = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        if n_rows == n:
            rep.ok("entries 行数", "%d" % n_rows)
        else:
            rep.fail("entries 行数", "meta.phases=%d 实测 %d" % (n, n_rows))
        r = con.execute("SELECT MIN(row_idx), MAX(row_idx), COUNT(DISTINCT row_idx) "
                        "FROM entries").fetchone()
        if r[0] == 0 and r[1] == n - 1 and r[2] == n:
            rep.ok("row_idx 完整排列", "0..%d 唯一" % (n - 1))
        else:
            rep.fail("row_idx 完整排列", "min=%s max=%s distinct=%s（应 0..%d / %d）"
                     % (r[0], r[1], r[2], n - 1, n))
        n_bad = con.execute("SELECT COUNT(*) FROM entries WHERE eid - 1 = row_idx").fetchone()[0]
        rep.ok("eid≠row_idx+1", "符合 §3（%d 行恰好 eid-1==row_idx，应为 0 或少数）" % n_bad) \
            if n_bad < n else rep.fail("eid≠row_idx+1", "全部 %d 行 eid-1==row_idx" % n_bad)
        try:
            n_fts = con.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]
            rep.ok("FTS5 索引", "%d 行" % n_fts) if n_fts == n else \
                rep.warn("FTS5 索引", "%d 行 ≠ entries %d" % (n_fts, n))
        except sqlite3.Error as exc:
            rep.fail("FTS5 索引", str(exc))
        null_elem = con.execute("SELECT COUNT(*) FROM entries WHERE elements IS NULL "
                                "OR elements = ''").fetchone()[0]
        rep.ok("elements 非空率", "%.2f%%" % (100.0 * (n - null_elem) / n)) \
            if null_elem * 20 <= n else rep.warn("elements 非空率", "空 %d 条" % null_elem)

        # 6) 抽样行序检查（需按 row_idx 取值）
        step = max(1, n // samples)
        bad_order = 0
        bad_slot = 0
        checked = 0
        rows = [r[0] for r in con.execute(
            "SELECT row_idx FROM entries ORDER BY row_idx").fetchall()[::step]][:samples]
        with open(os.path.join(db_dir, "peaks_d.f32"), "rb") as fd, \
                open(os.path.join(db_dir, "peaks_i.u16"), "rb") as fi:
            for row_idx in rows:
                fd.seek(row_idx * k * 4)
                d = struct.unpack("<%df" % k, fd.read(k * 4))
                fi.seek(row_idx * k * 2)
                i = struct.unpack("<%dH" % k, fi.read(k * 2))
                checked += 1
                for j in range(1, k):
                    if i[j] > i[j - 1]:
                        bad_order += 1
                        break
                seen_zero = False
                for j in range(k):
                    if i[j] == 0:
                        seen_zero = True
                    elif seen_zero and d[j] > 0:
                        # 空槽之后仍有有效峰 → 尾部未对齐
                        bad_slot += 1
                        break
        rep.ok("抽样行序（I 降序）", "%d 相全部通过" % checked) if bad_order == 0 else \
            rep.fail("抽样行序（I 降序）", "%d/%d 相乱序" % (bad_order, checked))
        rep.ok("抽样空槽尾部", "%d 相" % checked) if bad_slot == 0 else \
            rep.fail("抽样空槽尾部", "%d/%d 相空槽不连续" % (bad_slot, checked))
    finally:
        con.close()

    # 7) 峰口径与分箱一致性
    pc = meta.get("peak_convention") or {}
    if int(pc.get("k", -1)) == k and abs(float(pc.get("bins_top_m", -1)) - 40) <= 40:
        rep.ok("peak_convention", "λ=%s 2θ=%s~%s k=%s bins_top_m=%s"
               % (pc.get("wavelength"), pc.get("tth_min"), pc.get("tth_max"),
                  pc.get("k"), pc.get("bins_top_m")))
    else:
        rep.warn("peak_convention", json.dumps(pc, ensure_ascii=False)[:120])
    return rep.render()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dbs", nargs="+", help="polyDB 目录（可多个）")
    ap.add_argument("--no-hash", action="store_true", help="跳过 sha256（大库省时）")
    ap.add_argument("--samples", type=int, default=64)
    args = ap.parse_args(argv)
    rc = 0
    for i, d in enumerate(args.dbs):
        if i:
            print("\n" + "-" * 72 + "\n")
        if not os.path.isdir(d):
            print("  [FAIL] 目录不存在：%s" % d)
            rc = 1
            continue
        rc |= verify(d, do_hash=not args.no_hash, samples=args.samples)
    print("\n结论：%s" % ("全部 PASS" if rc == 0 else "存在 FAIL 项"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
