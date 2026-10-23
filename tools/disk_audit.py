#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""E 盘内容清点（清理后的容量审计）

用途：在一次单流顺序扫描中，给出 E:\ 各顶层目录 / rsync-COD 各子项的
真实占用字节数，与卷级 GetDiskFreeSpaceEx 的 used 值对账，确认清理
（删除 .db 副本 78 GiB、分片目录 42 GB）是否已真正回收、以及是否有
未释放的块。

机械盘上 1.8M 个小文件的枚举瓶颈在寻道，因此：
  - 只做 os.scandir + stat（不做 is_file 二次调用）
  - 单线程顺序跑，不与其它重 I/O 任务并行
  - 逐目录 flush 打印，便于用 tail 观察进度

用法：
  E:/GSASII/python.exe -u tools/disk_audit.py
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

GiB = 1024.0 ** 3


def free_space(drive: str = "E:/"):
    fn = ctypes.windll.kernel32.GetDiskFreeSpaceExW
    free = ctypes.c_ulonglong()
    tot = ctypes.c_ulonglong()
    avail = ctypes.c_ulonglong()
    fn(drive, ctypes.byref(avail), ctypes.byref(tot), ctypes.byref(free))
    return tot.value, free.value


def walk_size(path: str):
    """返回 (文件数, 字节数)。不跟随符号链接/联接点，避免重复计数。"""
    n = 0
    total = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_file_attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                    continue
                if st.st_size and not (st.st_mode & 0o040000):  # 普通文件
                    total += st.st_size
                    n += 1
                elif st.st_mode & 0o040000:
                    stack.append(e.path)
    return n, total


def report(label: str, path: str):
    t0 = time.time()
    if os.path.isdir(path):
        n, b = walk_size(path)
    elif os.path.exists(path):
        n, b = 1, os.path.getsize(path)
    else:
        print("%-28s %s" % (label, "（不存在）"), flush=True)
        return 0
    print("%-28s %9d 文件  %9.2f GiB  (%.1f min)"
          % (label, n, b / GiB, (time.time() - t0) / 60.0), flush=True)
    return b


def main():
    root = "E:/rsync-COD"
    tot_b = 0
    print("=== rsync-COD 子项 ===", flush=True)
    for name in ("COD", "PCOD", "TCOD", "inorg_cif", "sync-COD-pack",
                 "sync_logs", "tools", ".workbuddy"):
        tot_b += report(name, os.path.join(root, name))
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            tot_b += report(name, p)
    print("%-28s %28.2f GiB" % ("rsync-COD 合计", tot_b / GiB), flush=True)

    print("\n=== E 盘其它顶层目录 ===", flush=True)
    other = 0
    for name in sorted(os.listdir("E:/")):
        p = os.path.join("E:/", name)
        if name == "rsync-COD" or not os.path.isdir(p):
            continue
        if name in ("System Volume Information", "$RECYCLE.BIN"):
            n, b = 0, 0
            try:
                n, b = walk_size(p)
            except OSError:
                pass
            print("%-28s %9d 文件  %9.2f GiB  (可能无权限，仅供参考)"
                  % (name, n, b / GiB), flush=True)
            other += b
            continue
        other += report(name, p)
    print("%-28s %28.2f GiB" % ("其它目录合计", other / GiB), flush=True)

    tot, free = free_space()
    used = tot - free
    print("\n=== 对账 ===", flush=True)
    print("卷总量        %8.2f GiB" % (tot / GiB), flush=True)
    print("卷已用(系统)  %8.2f GiB" % (used / GiB), flush=True)
    print("卷可用        %8.2f GiB" % (free / GiB), flush=True)
    print("已清点内容    %8.2f GiB" % ((tot_b + other) / GiB), flush=True)
    print("差额(未清点)  %8.2f GiB  ← 应为 NTFS 元数据/$MFT/无权限项/其它"
          % ((used - tot_b - other) / GiB), flush=True)


if __name__ == "__main__":
    sys.exit(main())
