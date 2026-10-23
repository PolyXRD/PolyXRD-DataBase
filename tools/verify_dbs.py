#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 PolyXRD 自己的导入探测逻辑验证生成的两个库是否可挂载，并做完整性对账。

验证项:
  1) db_import.inspect_db_file —— 软件实际使用的判别逻辑（必需列/特征列/排除列）
  2) 条目数 vs 源 CIF 文件数（不漏条目）
  3) 抽样抽查字段内容（晶胞/原子坐标/峰表/内嵌 CIF 可否解压）
"""
from __future__ import annotations

import gzip
import os
import sqlite3
import sys

sys.path.insert(0, "E:/TEMP/PolyXRD/src")
from polyxrd.services.db_import import inspect_db_file, DB_KINDS  # noqa: E402

FULL_DB = "E:/rsync-COD/COD-PCOD-TCOD-full-20261010.sqlite"
INORG_DB = "E:/rsync-COD/COD-PCOD-TCOD-Inorg-20261010.sqlite"

LIBS = [("COD", "E:/rsync-COD/COD"), ("PCOD", "E:/rsync-COD/PCOD"),
        ("TCOD", "E:/rsync-COD/TCOD")]


def count_cifs(root):
    n = 0
    for _d, _s, fs in os.walk(root):
        n += sum(1 for f in fs if f.lower().endswith(".cif"))
    return n


def main():
    print("=" * 78)
    print("1) PolyXRD 导入探测（软件实际使用的判别逻辑）")
    for db in (FULL_DB, INORG_DB):
        if not os.path.exists(db):
            print("  %s 不存在" % db)
            continue
        ins = inspect_db_file(db)
        print("  %s" % os.path.basename(db))
        print("    识别结果 : ok=%s kind=%s table=%s rows=%d has_top_peaks=%s"
              % (ins.ok, ins.kind, ins.table, ins.rows, ins.has_top_peaks))
        if not ins.ok:
            print("    !! error=%s hint=%s" % (ins.error, ins.hint))
        print("    体积     : %.2f GB" % (os.path.getsize(db) / 1024 ** 3))

    print("\n2) 条目数对账（源 CIF 文件数 vs 库内条目数）")
    total_files = 0
    for lib, root in LIBS:
        if not os.path.isdir(root):
            continue
        n = count_cifs(root)
        total_files += n
        print("  %-5s 源 CIF 文件数: %d" % (lib, n))
    print("  合计: %d" % total_files)

    if os.path.exists(FULL_DB):
        c = sqlite3.connect("file:%s?mode=ro" % FULL_DB.replace("\\", "/"), uri=True)
        n_ent = c.execute("SELECT COUNT(*) FROM cod_entries").fetchone()[0]
        n_site = c.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
        n_gz = c.execute("SELECT COUNT(*) FROM cod_entries WHERE cif_gz IS NOT NULL").fetchone()[0]
        n_dup = c.execute("SELECT COUNT(*) FROM (SELECT cod_id FROM cod_entries "
                          "GROUP BY cod_id HAVING COUNT(*)>1)").fetchone()[0]
        print("  full 库: cod_entries=%d (源 %d, 差 %d), 原子位点=%d, 内嵌CIF=%d, 重复ID=%d"
              % (n_ent, total_files, n_ent - total_files, n_site, n_gz, n_dup))
        rows = c.execute("SELECT cod_id,file,formula,elements,space_group,a,b,c,"
                         "alpha,beta,gamma,length(cif_gz) FROM cod_entries "
                         "LIMIT 3").fetchall()
        for r in rows:
            print("     样例:", r)
        c.close()

    if os.path.exists(INORG_DB):
        c = sqlite3.connect("file:%s?mode=ro" % INORG_DB.replace("\\", "/"), uri=True)
        n_ph = c.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
        n_pk0 = c.execute("SELECT COUNT(*) FROM phases WHERE n_peaks>0").fetchone()[0]
        n_err = c.execute("SELECT COUNT(*) FROM parse_errors").fetchone()[0]
        n_sp = c.execute("SELECT COUNT(*) FROM cod_atomic_sites").fetchone()[0]
        print("  inorg 库: phases=%d (有峰 %d), 原子位点=%d, parse_errors=%d"
              % (n_ph, n_pk0, n_sp, n_err))
        # 预截断强峰列（检索快路径依赖它）
        try:
            n_top = c.execute(
                "SELECT COUNT(*) FROM phases WHERE peaks_top_d IS NOT NULL").fetchone()[0]
            r = c.execute(
                "SELECT cod_id, n_peaks, length(peaks_top_d), length(peaks_top_i), "
                "peaks_top_i FROM phases WHERE peaks_top_d IS NOT NULL "
                "LIMIT 1").fetchone()
            import struct
            ti = struct.unpack("<64d", r[4][:512]) if r and r[3] >= 512 else ()
            print("    预截断强峰列: %d/%d 相, 样例 cod_id=%s n_peaks=%d "
                  "top_d=%d B top_i=%d B, I降序=%s, I[0]=%.1f"
                  % (n_top, n_ph, r[0] if r else "-", r[1] if r else 0,
                     r[2] if r else 0, r[3] if r else 0,
                     all(ti[i] >= ti[i + 1] - 1e-9 for i in range(len(ti) - 1)),
                     ti[0] if ti else -1))
        except sqlite3.Error as e:
            print("    预截断强峰列检查失败: %s" % e)
        rows = c.execute("SELECT cod_id,formula,space_group,cell_a,cell_b,cell_c,"
                         "n_peaks,substr(peaks_d,1,40),substr(peaks_i,1,40),"
                         "ref_id,display_id,length(cif_gz) FROM phases "
                         "WHERE n_peaks>0 LIMIT 3").fetchall()
        for r in rows:
            print("     样例:", r)
        # 内嵌 CIF 可否解压
        r = c.execute("SELECT cod_id, cif_gz FROM phases WHERE cif_gz IS NOT NULL "
                      "LIMIT 1").fetchone()
        if r:
            txt = gzip.decompress(r[1]).decode("utf-8", "replace")
            print("     内嵌CIF解压 (cod_id=%s): %d 字节, 首行 %r"
                  % (r[0], len(txt), txt.splitlines()[0] if txt else ""))
        errs = c.execute("SELECT reason, COUNT(*) FROM parse_errors GROUP BY reason "
                         "ORDER BY 2 DESC LIMIT 5").fetchall()
        if errs:
            print("     parse_errors 归类:", errs)
        c.close()


if __name__ == "__main__":
    main()
