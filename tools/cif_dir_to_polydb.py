#!/usr/bin/env python3
"""
cif_dir_to_polydb.py — 任意 CIF 目录 → polyDB（复用 build_polydb 的全流程）
=========================================================================

用途：把**不是 COD** 来源的 CIF 集合（ICSD / FindIt 导出、厂商 CIF、自建 CIF）
做成 PolyXRD 可直接挂载的 polyDB v4 库。

做法上不重写任何格式逻辑：只是把来源整理成 ``build_polydb.py`` 期望的
``DATA_ROOT`` 目录树，然后调用它 + ``verify_polydb.py``。这样峰口径、
位点打包、位图索引、校验和全部与官方构建器逐字节一致。

期望的目录树::

    <root>/COD/<...>/<name>.cif      ← 归一化后的 CIF
    <root>/inorg_manifest.sqlite      ← files(cod_id, lib, rel, ..., is_inorg)

支持两种输入：
  1. ``--cif-dir``   扫描目录下所有 CIF（递归），自动按 ``data_`` 块**拆分**
     一个文件里含多张卡的情况。
  2. ``--cif-file``  单个文件或明确的后缀列表。

ID 规则（决定 eid，需稳定且唯一）：
  优先 ``_database_code_ICSD``（ICSD 卡片号，如 98-000-1234 → 980001234）→
  其次文件名里的数字 → 最后按读取顺序编号。重复 ID 会被改写并告警。

用法：
    # 1) 只整理目录树（不建库）
    python tools/cif_dir_to_polydb.py --cif-dir D:/icsd_cif --root D:/Project/XRD/icsd_polydb --prepare

    # 2) 整理 + 建库 + 校验
    python tools/cif_dir_to_polydb.py --cif-dir D:/icsd_cif --root D:/Project/XRD/icsd_polydb \
        --out D:/Project/XRD/icsd_polydb/ICSD.polyDB --build --verify

红线：ICSD 数据是 NIST 版权库，产物只留本机，不入库、不随安装包分发。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / "build_polydb.py"
VERIFIER = HERE / "verify_polydb.py"

CIF_SUFFIXES = {".cif", ".cif.txt", ".txt"}

#: 从 CIF 里取稳定 ID 的候选标签，按优先级
ID_TAGS = (
    "_database_code_ICSD",
    "_database_code_depnum_ccdc_archive",
    "_journal_paper_doi",
)

BLOCK_SPLIT = re.compile(r"^data_", re.M)


def split_cif_blocks(text: str) -> list[tuple[str, str]]:
    """把一个 CIF 文件拆成若干 (data_name, block_text)。"""
    marks = list(BLOCK_SPLIT.finditer(text))
    if not marks:
        return [("", text)]
    out: list[tuple[str, str]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        head = text[m.start():text.find("\n", m.start()) if "\n" in text[m.start():end] else end]
        name = head[len("data_"):].strip()
        out.append((name, text[m.start():end]))
    return out


def tag_value(block: str, tag: str) -> str | None:
    """取 CIF 单值标签（``_tag   value`` 形式）。"""
    m = re.search(r"^" + re.escape(tag) + r"\s+(\S+)", block, re.M)
    if not m:
        m = re.search(r"^" + re.escape(tag) + r"\s*\n\s*(\S+)", block, re.M)
    return m.group(1).strip("'\"") if m else None


def make_id(block: str, data_name: str, stem: str, seq: int) -> int:
    """稳定 ID：纯数字文件名优先 → CIF 内的库编号 → 文件名数字 → 兜底序号。

    纯数字文件名优先，是为了让 COD 这类「文件名即 ID」的集合保持原号不变。
    """
    for cand in (stem, data_name):
        if cand and cand.isdigit() and len(cand) <= 15:
            return int(cand)
    for tag in ID_TAGS:
        v = tag_value(block, tag)
        if v:
            digits = re.sub(r"\D", "", v)
            if digits:
                n = int(digits)
                if n < 10**17:
                    return n
    for cand in (data_name, stem):
        digits = re.sub(r"\D", "", cand or "")
        if digits and len(digits) <= 15:
            return int(digits)
    return 900_000_000 + seq          # 兜底号段，避免与 COD(1e6 起) 撞


def prepare(cif_dir: Path | None, cif_files: list[Path], root: Path,
            id_prefix: str = "") -> dict:
    """扫描并归一化 CIF → ``<root>/COD/`` + manifest。"""
    files: list[Path] = []
    if cif_dir:
        for p in sorted(cif_dir.rglob("*")):
            if p.is_file() and (p.suffix.lower() in CIF_SUFFIXES
                                or p.name.lower().endswith(".cif.txt")):
                files.append(p)
    files.extend(cif_files)
    if not files:
        raise SystemExit(f"[!] 在 {cif_dir} 下没找到 CIF")

    cod_dir = root / "COD" / ("ICSD" if "icsd" in str(root).lower() or id_prefix else "import")
    cod_dir.mkdir(parents=True, exist_ok=True)

    con_path = root / "inorg_manifest.sqlite"
    if con_path.exists():
        con_path.unlink()
    con = sqlite3.connect(con_path)
    con.execute("""CREATE TABLE files (
        cod_id INTEGER PRIMARY KEY, lib TEXT NOT NULL, rel TEXT NOT NULL,
        formula TEXT, formula_red TEXT, elements TEXT,
        is_inorg INTEGER NOT NULL, size INTEGER, mtime INTEGER)""")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    seen: dict[int, str] = {}
    rows: list[tuple] = []
    n_blocks = n_split = n_dup = 0
    next_free = 900_000_000
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  ! 读失败 {p.name}: {e}")
            continue
        blocks = split_cif_blocks(text)
        if len(blocks) > 1:
            n_split += 1
        for k, (name, block) in enumerate(blocks):
            if "loop_" not in block and "_cell_length_a" not in block:
                continue                      # 不是结构块，跳过
            n_blocks += 1
            eid = make_id(block, name, p.stem, n_blocks)
            if eid in seen:
                n_dup += 1
                while next_free in seen:
                    next_free += 1
                eid = next_free
                next_free += 1
            fname = f"{eid:012d}.cif" if len(blocks) == 1 else f"{eid:012d}_{k}.cif"
            dst = cod_dir / fname
            dst.write_text(block if block.endswith("\n") else block + "\n",
                           encoding="utf-8")
            rel = dst.relative_to(root / "COD").as_posix()
            formula = tag_value(block, "_chemical_formula_sum") or ""
            seen[eid] = rel
            # lib 必须是 'COD'：build_polydb 的查询是 lib='COD' AND is_inorg=1
            rows.append((eid, "COD", rel, formula, "", "", 1,
                         dst.stat().st_size, int(dst.stat().st_mtime)))

    con.executemany("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO meta VALUES (?,?)", [
        ("source", str(cif_dir or cif_files[0])),
        ("n_blocks", str(n_blocks)),
        ("note", "cif_dir_to_polydb import"),
    ])
    con.commit()
    con.close()
    print(f"准备完成：{len(files)} 个文件 → {n_blocks} 个结构块"
          f"（多块文件 {n_split} 个，ID 冲突改写 {n_dup} 个）")
    print(f"  CIF 目录 : {cod_dir}  ({len(rows)} 个)")
    print(f"  清单     : {con_path}")
    return {"root": str(root), "cod_dir": str(cod_dir),
            "n_blocks": n_blocks, "n_dup": n_dup}


def run_build(root: Path, out: Path, workers: int) -> int:
    env = dict(os.environ)
    env["XRD_DATA_ROOT"] = str(root)
    env.setdefault("TEMP", r"D:\px_tmp")
    env.setdefault("TMP", env["TEMP"])
    os.makedirs(env["TEMP"], exist_ok=True)
    cmd = [sys.executable, str(BUILDER), "--scope", "inorg",
           "--out", str(out), "--workers", str(workers), "--force"]
    print("\n$ " + " ".join(cmd))
    r = subprocess.run(cmd, env=env, cwd=str(HERE))
    return r.returncode


def run_verify(out: Path) -> int:
    cmd = [sys.executable, str(VERIFIER), str(out), "--no-hash"]
    print("\n$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(HERE)).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cif-dir", type=Path, help="CIF 目录（递归扫描）")
    ap.add_argument("--cif-file", type=Path, action="append", default=[],
                    help="单个 CIF（可重复）")
    ap.add_argument("--root", type=Path, required=True,
                    help="生成的 DATA_ROOT（内含 COD/ 与 manifest）")
    ap.add_argument("--out", type=Path, help="目标 .polyDB 目录")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    ap.add_argument("--prepare", action="store_true", help="只整理目录树")
    ap.add_argument("--build", action="store_true", help="整理后调用 build_polydb")
    ap.add_argument("--verify", action="store_true", help="建完后跑 verify_polydb")
    args = ap.parse_args(argv)

    if not args.cif_dir and not args.cif_file:
        ap.error("需要 --cif-dir 或 --cif-file")
    args.root.mkdir(parents=True, exist_ok=True)

    info = prepare(args.cif_dir, args.cif_file, args.root)
    if args.prepare and not args.build:
        return 0
    if not args.out:
        ap.error("--build 需要 --out")

    rc = run_build(args.root, args.out, args.workers)
    if rc != 0:
        print(f"[!] build_polydb 退出码 {rc}")
        return rc
    if args.verify:
        rv = run_verify(args.out)
        if rv != 0:
            print(f"[!] verify_polydb 退出码 {rv}")
            return rv
    print("\n完成 →", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
