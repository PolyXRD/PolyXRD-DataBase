# 与 COD 官方同步 CIF 的脚本（**当前停用**）

> **状态：停用（2026-10-23）。** 用户明确"暂时不用同步了"。本目录只作能力留存，
> 不在日常建库流程里，也不会被任何构建脚本导入。
> 重新启用前先读下面的「环境前提」，两项前提现在都不满足。

## 数据落到哪

所有脚本的数据根统一走环境变量 `XRD_DATA_ROOT`，默认
`D:/Project/XRD/sync-COD`（与两个构库仓库共用，见仓库根 README）。

| 子项 | 位置 |
|---|---|
| COD 归档 | `<数据根>/COD`（3 级布局 `1/00/00/1000003.cif`） |
| PCOD 归档 | `<数据根>/PCOD`（2 级布局） |
| TCOD 归档 | `<数据根>/TCOD`（3 级布局） |
| 同步日志与清单 | `<数据根>/sync_logs/` |

## 脚本分工

| 脚本 | 作用 |
|---|---|
| `fetch_remote_inv.py` | 用 rsync `--list-only -r` 抓远端目录清单（COD/PCOD） |
| `crawl_tcod_http.py` | TCOD 没有 rsync，只能爬 Apache 索引拿清单 |
| `make_local_inv.py` | 生成本地逐条清单（`路径<TAB>字节`） |
| `cmp_inv.py` | 远端清单 vs 本地清单，输出缺失/多余 |
| `fetch_missing_tcod.py` | 按缺口清单补下载（顺序 + 退避 + 落盘尺寸校验） |
| `audit_tcod_inv.py` / `diff_tcod_inv.py` | TCOD 目录数与清单对账 |
| `verify_sync_tcod.py` | 解析 wget 日志，核对"日志声称下载"与"磁盘实际存在" |
| `probe_remote.sh` | 探查站点可达性与并发上限 |

## 环境前提（重新启用前必须满足）

1. **本机已无 rsync/wget**（2026-10-19 实测只剩 curl）。COD/PCOD 的 rsync 同步
   需先装便携 rsync；TCOD 只能走 HTTP 索引爬取。
2. **DNS 对国外域名整段失效**：固定 10.84 s 超时、curl exit 6。
   长任务必须"解析一次 → 按 IP 连接 + 显式 `Host:` 头"。
   TCOD 站点 `www.crystallography.net` 可通过 DoH 解析后直连。

## 血泪教训（照做，别重新踩）

- wget 的 `FINISHED` / `Downloaded: N files` **不是完整性证据**：子目录索引 403
  时会静默剪枝整棵子树。必须用独立逐条清单比对（`cmp_inv.py`）。
- `--tries` 不重试 403（只重试连接错误与 5xx），补齐要"顺序 + 指数退避 + 落盘尺寸校验"。
- 服务端并发上限约 4（`-P 12` 必 403，`-P 4` 实测 0 个 403）。
- TCOD 文件 mtime 是服务器时间戳，判断"本轮是否新下载"要看 Birth time。
- **`TaskStop` 只杀直接子进程**：`xargs -P4 → sh → wget` 的孙进程会残留并持续
  下载/污染目录。清理必须按 `Win32_Process.CommandLine` 关键字找全树。
- 并发不是越小越稳：到该站 4/16 并发只有 ~2.5 文件/s，32 并发 12.3 文件/s 且 0 个 403。
  但目录索引爬取要压速（2 并发 + 0.15 s 间隔），否则先 403 后直接丢包。

## rsync 源（供参考）

| 库 | 源 |
|---|---|
| COD | `rsync://www.crystallography.net/cif/` |
| PCOD | `rsync://www.crystallography.net/pcod-cif/` |
| TCOD | `http://www.crystallography.net/tcod/cif/`（**无 rsync，svn 3690 也不通**） |
