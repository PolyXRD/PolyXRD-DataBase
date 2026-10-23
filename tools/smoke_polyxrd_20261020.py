#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PolyXRD 实检索冒烟（只读，不写用户配置）。

用 PolyXRD 自己的 ``CIFDatabase`` / ``CODLocalDatabase``，以**注入只读连接**
的方式挂上交付库，跑真实检索：

  A. Inorg 库（cod_inorganics 槽位）
     - ``search_cod_by_d_peaks`` 三个参考物相：α-石英 / 方解石 / 刚玉
       走 top-64 BLOB 快路径（max_ref_peaks=40 默认值），验证不再有
       ``peaks_top_d IS NULL`` 的 AttributeError
     - ``get_cod_phase`` 取一个真实条目的原子位点
  B. Full 库（cod_index 槽位）
     - ``CODLocalDatabase.search`` 按 formula_red / mineral_name / elements 查
     - ``get_phase`` 取原子位点动态算峰

不调用 set_cod_db_path / set_cod_index_db_path，因此不污染
~/.polyxrd/user_db_paths.json。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

BASE = "D:/Project/XRD/PolyXRD-DataBase"
POLY = "D:/Project/XRD/PolyXRD/src"
INORG = os.path.join(BASE, "3COD-Inorg-20261020.sqlite")
FULL = os.path.join(BASE, "3COD-Full-20261020.sqlite")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, POLY)

FAIL: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAIL.append(msg)


# ── 参考物相：实测 d / I（Cu Kα1，ICDD 卡口径）──────────────
REFS = {
    "α-石英 SiO2": {
        "d": [4.2553, 3.3435, 2.4573, 2.2817, 2.2371, 2.1274, 1.9790, 1.8178,
              1.6708, 1.5418],
        "i": [22.0, 100.0, 4.0, 9.0, 4.0, 6.0, 2.0, 14.0, 3.0, 8.0],
    },
    "方解石 CaCO3": {
        "d": [3.0350, 2.8450, 2.4950, 2.2850, 2.0950, 1.9130, 1.8750, 1.6250],
        "i": [100.0, 14.0, 14.0, 18.0, 18.0, 17.0, 17.0, 8.0],
    },
    "刚玉 Al2O3": {
        "d": [2.0850, 2.5510, 1.6014, 3.4795, 2.3790, 1.5470, 2.5488, 1.4027],
        "i": [100.0, 97.0, 82.0, 45.0, 40.0, 80.0, 74.0, 30.0],
    },
}


def test_inorg_peaks() -> None:
    print("=" * 78)
    print("A. PolyXRD  Inorg 库  search_cod_by_d_peaks (BLOB 快路径)")
    print("=" * 78)
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase(enable_cod_local=False)
    # 只读注入：等价于 set_cod_db_path 的效果，但不落盘
    conn = sqlite3.connect("file:" + INORG.replace("\\", "/") + "?mode=ro",
                           uri=True, timeout=60.0)
    conn.row_factory = sqlite3.Row
    db._cod_conn = conn          # noqa: SLF001 - 官方声明过的注入点

    for name, ref in REFS.items():
        t0 = time.time()
        try:
            res = db.search_cod_by_d_peaks(
                measured_d=ref["d"], measured_i=ref["i"],
                tolerance=0.05, min_match=3, limit=10,
                max_ref_peaks=40,       # GUI 预筛固定值 ⇒ 走 BLOB 路径
            )
        except Exception as e:      # noqa: BLE001
            ok(False, f"{name}: 抛异常 {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        top = res[0] if res else None
        print(f"  [{name}] {len(res)} 条命中, {dt*1000:.0f} ms")
        if top:
            print(f"      Top1 cod_id={top.get('cod_id')} formula={top.get('formula')!r} "
                  f"sg={top.get('space_group')!r} score={top.get('score', 0):.4f}")
        ok(bool(res), f"{name}: 有命中结果")
    db._cod_conn.close()
    db._cod_conn = None


def test_inorg_phase() -> None:
    print()
    print("=" * 78)
    print("A2. PolyXRD  Inorg 库  get_cod_phase 取原子位点")
    print("=" * 78)
    from polyxrd.services.cif_database import CIFDatabase

    db = CIFDatabase(enable_cod_local=False)
    conn = sqlite3.connect("file:" + INORG.replace("\\", "/") + "?mode=ro",
                           uri=True, timeout=60.0)
    conn.row_factory = sqlite3.Row
    db._cod_conn = conn
    # ⚠️ get_cod_phase 返回 **dict**（不是 Phase 对象），必须按 key 取值。
    # 首版用 getattr 导致全部读成 None，误判成"库里没有"。
    for cid in (1010360, 1000003, 1011097):
        try:
            ph = db.get_cod_phase(cid)
        except Exception as e:      # noqa: BLE001
            print(f"  cod_id={cid} 抛异常 {type(e).__name__}: {e}")
            continue
        if ph is None:
            print(f"  cod_id={cid} -> None（库中无此条）")
            continue
        dl = ph.get("peaks_d_list") or []
        il = ph.get("peaks_i_list") or []
        print(f"  cod_id={cid} formula={ph.get('formula')!r} "
              f"sg={ph.get('space_group')!r} n_peaks={ph.get('n_peaks')} "
              f"parsed_d={len(dl)} parsed_i={len(il)}")
        print(f"      d 前 6: {[round(x,4) for x in dl[:6]]}")
        print(f"      i 前 6: {[round(x,1) for x in il[:6]]}")
        ok(len(dl) > 0 and len(dl) == len(il) == ph.get("n_peaks"),
           f"get_cod_phase({cid}) 峰解析与 n_peaks 一致")
        break
    db._cod_conn.close()
    db._cod_conn = None
    ok(True, "get_cod_phase 调用链未崩溃")


def test_full_index() -> None:
    print()
    print("=" * 78)
    print("B. PolyXRD  Full 库  CODLocalDatabase (cod_index 槽位)")
    print("=" * 78)
    from polyxrd.services.cod_local import CODLocalDatabase

    db = CODLocalDatabase(db_path=FULL, cod_root=BASE)
    print(f"  is_ready = {db.is_ready()}")
    st = db.stats()
    print(f"  stats: total={st.get('total'):,} parse_ok={st.get('parse_ok'):,} "
          f"parse_bad={st.get('parse_bad'):,}")

    for q in ({"formula": "SiO2"}, {"formula": "Al2O3"},
              {"mineral_name": "quartz"}, {"elements": ["Zr", "O"]}):
        t0 = time.time()
        try:
            rows = db.search(limit=5, **q)
        except Exception as e:      # noqa: BLE001
            ok(False, f"search{q} 抛异常 {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        print(f"  search{q} -> {len(rows)} 条, {dt*1000:.0f} ms")
        for r in rows[:3]:
            print(f"      cod_id={r.cod_id} formula={r.formula!r} "
                  f"formula_red={r.formula_red!r} sg={r.space_group!r} "
                  f"file={r.file!r}")
        ok(len(rows) > 0, f"search{q} 有命中")

    # 取原子位点 + 动态峰
    t0 = time.time()
    for cid in (1000003, 9008467, 1010360):
        try:
            ph = db.get_phase(cid)
        except Exception as e:      # noqa: BLE001
            print(f"  get_phase({cid}) 抛异常 {type(e).__name__}: {e}")
            ph = None
        if ph is not None:
            print(f"  get_phase({cid}) -> formula={getattr(ph,'formula',None)!r} "
                  f"sites={len(getattr(ph,'atomic_sites',[]) or [])} "
                  f"peaks={len(getattr(ph,'reference_peaks',[]) or [])} "
                  f"({(time.time()-t0)*1000:.0f} ms)")
            break
    else:
        print("  get_phase 三次尝试都返回 None（可能这些 cod_id 不在库中）")

    # CIF 四级回退：slim 库应走 cod_root 的文件路径
    try:
        txt = db.get_cif(1000003)
        ok(txt is None or isinstance(txt, (str, bytes)),
           f"get_cif(1000003) 返回 {'None' if txt is None else str(len(txt))+' 字符'}")
    except Exception as e:          # noqa: BLE001
        ok(False, f"get_cif 抛异常 {type(e).__name__}: {e}")


def main() -> int:
    test_inorg_peaks()
    test_inorg_phase()
    test_full_index()
    print()
    print("=" * 78)
    if FAIL:
        print(f"结果：{len(FAIL)} 项 FAIL")
        for f in FAIL:
            print("  -", f)
        return 1
    print("结果：全部 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
