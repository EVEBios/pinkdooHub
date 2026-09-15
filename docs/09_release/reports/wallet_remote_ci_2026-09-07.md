# Wallet 扩展门槛远端 CI 报告

> **Result:** PASS（GitHub Actions 8/8）
> **Release Decision:** BLOCKED / No-Go
> **Executed At:** 2026-09-07 22:41–22:46（Asia/Shanghai）
> **Branch:** `feature/phase9-ci`
> **PR:** [#2 `feature/phase9-ci` → `develop`](https://github.com/EVEBios/pinkdooHub/pull/2)
> **Run:** [GitHub Actions 34134341829](https://github.com/EVEBios/pinkdooHub/actions/runs/34134341829)

## 1. 受测身份

| 项目 | 值 |
|------|----|
| PR head SHA | `62f807ac2fc6c249149b261758403e1e70650685` |
| PR merge-ref SHA | `6675b4f5f4ba163441d625ef3da2274b387a0ebd` |
| Base | `develop@35d28bb4393350b7621072f113301c32b91fb513` |
| Workflow / attempt | `.github/workflows/ci.yml` / `1` |
| Event | `pull_request` / `synchronize` |
| Run window | `2026-09-07T14:41:35Z`–`2026-09-07T14:46:05Z` |

Run 元数据绑定 PR head；GitHub checkout/artifact 名称绑定本次 merge-ref。本文记录在
后续提交中，不属于受测 head。其后的 Gate A 运维和 MARD 发布实现也不在本 Run 内，
必须由新的远端 Run 重新验证，不能沿用本报告。

## 2. Job 与 Wallet 门槛

| Job | 结果 | 开始（UTC） | 完成（UTC） | 证据边界 |
|-----|------|-------------|-------------|----------|
| `backend-mysql-release` | success | 14:41:40 | 14:42:58 | 迁移演练、Inventory + Reservation + Wallet 联合测试、专用 Schema/service cleanup 和 artifact 上传步骤全部 success |
| `backend-sqlite` | success | 14:41:38 | 14:46:04 | 完整 SQLite 套件命令显式忽略三类 MySQL-only 目录并保存 JUnit |
| `frontend-quality` | success | 14:41:39 | 14:44:11 | typecheck、ESLint、Stylelint、Jest、CI policy 与 artifact success |
| `openapi-contract` | success | 14:41:39 | 14:43:44 | OpenAPI 与生成类型阻断检查 success |
| `weapp-build` | success | 14:41:39 | 14:43:08 | 非 release-eligible 微信产物构建、扫描和 artifact success |
| `python-dependency-audit` | success | 14:41:39 | 14:42:48 | 固定 Python 审计策略与 artifact success |
| `npm-dependency-audit` | success | 14:41:39 | 14:43:24 | npm reachability 策略与 artifact success |
| `repository-hygiene` | success | 14:41:39 | 14:41:52 | tracked file、Secret、diff、clean tree 与 artifact success |

受测 workflow 明确运行 `tests/inventory/mysql tests/reservation/mysql tests/wallet/mysql`；
在同一 head 的本地候选中该集合为 30 项，其中 Wallet 9 项覆盖并发不同/相同 key
调账、余额支付、退款、真实 1205、首轮写入后 1213 整事务重试、跨资金/库存锁等待和
五类关键 `EXPLAIN`。GitHub 公共 API 不开放无认证 Job 日志下载，因此本文只把远端
步骤结论记录为直接证据；精确断言与本地时长继续引用
[Wallet 扩展 MySQL 报告](wallet_mysql_release_gate_2026-09-07.md)，不伪造远端日志正文。

## 3. Artifact 清单

7 组 artifact 均未过期，保留至 2026-09-21。8 个 Job 中 `openapi-contract` 按 workflow
只做阻断检查、不上传 artifact，因此数量符合设计。

| Artifact | Bytes | GitHub digest |
|----------|------:|---------------|
| `backend-sqlite-6675b4f5f4ba163441d625ef3da2274b387a0ebd-34134341829` | 35,817 | `sha256:95ed91c14eebb04c25d805faeed2aa9f100bc4723a20f7f5e6c08fab9a92aae3` |
| `backend-mysql-release-6675b4f5f4ba163441d625ef3da2274b387a0ebd-34134341829` | 3,506 | `sha256:81947a50b44dd3a38edbc8169c363ed86ee5f2023ebe5d27a0d8a45a490dd47d` |
| `frontend-quality-6675b4f5f4ba163441d625ef3da2274b387a0ebd-34134341829` | 32,559 | `sha256:b00b8bd3df3b921624368ee8d0ed0546048a094511f39cfbd7abf5bf7fd4fb83` |
| `weapp-1.0.0-6675b4f5f4ba-34134341829` | 295,506 | `sha256:192b16f744c6c4ee31f90f8e287fb0d4c563ee58f5386cdd10593e0ab57f6366` |
| `python-dependency-audit-6675b4f5f4ba163441d625ef3da2274b387a0ebd-34134341829` | 1,206 | `sha256:c19752dddfeb39b9e2d6f606aaba9537c8cd2d9d1d75ae39648f17ff908348cb` |
| `npm-dependency-audit-6675b4f5f4ba163441d625ef3da2274b387a0ebd-34134341829` | 1,787 | `sha256:07da07de630b567c345fc15a90caadf56484909dbaaf063ef3b467e018eb3165` |
| `repository-hygiene-6675b4f5f4ba163441d625ef3da2274b387a0ebd-34134341829` | 268 | `sha256:282725f01b1112f763c704f7a06f4ad402d68d506daac61cc7e12077448ac47f` |

## 4. 结论与边界

R-029 的本地仓库门槛和远端干净 Runner 复现均已关闭。远端 MySQL Job 的 cleanup
步骤明确 success；该 service container 属于 GitHub 临时 Runner，没有接触 Gate A、
本地 `db.sqlite3`、共享、预发布或生产数据库。

发布仍为 **No-Go**：持久 Gate A 真实版本/Schema 尚未只读复核，非空升级编排、当次
Backup/Restore、M4 backfill/reconcile、M6 色卡与测试商品配置均未应用；真实 HTTPS
Origin、微信合法域名、release-eligible RC 和 iOS/Android 真机也未完成。体验版上传、
分发、提审或公开发布未获本文授权。
