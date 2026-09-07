# Wallet 扩展 MySQL 发布门槛报告（2026-09-07）

> **结论：** 仓库候选 PASS；Wallet-expanded workflow 尚未远端复现；Gate A 继续 No-Go
>
> **执行基线：** `feature/phase9-ci`，执行前 HEAD `b321225f55c53b52fe7ab700b1e03d3e4e32e199`
>
> **数据库：** 一次性 `mysql:8.0.46`，回环 `127.0.0.1:13316`
>
> **执行时间：** 2026-09-07 22:20–22:27 +08:00

## 1. 范围与停止边界

本轮只关闭 Wallet/Payment/Refund 的扩展 MySQL 仓库门槛：并发、瞬态错误整事务重试、跨资金/库存锁序和关键查询计划，并把该目录接入统一 CI Job。没有连接 3306，没有读取或修改本地持久 `db.sqlite3`、Gate A、共享、预发布或生产数据库，也没有执行 backfill、reconcile、资金开关、微信 Provider、tag 或 release。

本轮执行时新增测试与 workflow 尚未 commit/push，因此这里记录的是本地候选证据，不能冒充远端干净 checkout 或 GitHub Actions artifact。

## 2. 隔离与迁移

- 运行前仅存在用户已有 `pinkdoohub-dev-redis`（6379）；保持不动。
- 创建任务专属容器 `codex-pinkdoohub-wallet-gate-20260907`，只绑定 `127.0.0.1:13316`，使用 disposable root credential。
- 在 `pinkdoohub_wallet_release_gate` 完整执行 Aerich M0→M7，用于 Wallet 专项。
- 在同一临时实例另建 CI 冻结 Schema `pinkdoohub_inventory_4311_ci`，完整执行 Aerich M0→M7，用统一 `INVENTORY_MYSQL_TEST_*` 环境变量运行三域联合门槛，验证 Wallet fixture 与 CI 配置一致。
- 未使用 `--fake`、`init-db`、应用自动建表或任何持久数据副本。

## 3. 验证结果

| 门槛 | 结果 | 关键证据 |
|------|------|----------|
| Wallet 专项 | `9 passed in 4.35s` | 原 2 项资金/库存闭环与 `ascii_bin`；新增 7 项扩展门槛 |
| 三域联合 | 初跑 `30 passed in 13.33s`；夹具收口后复跑 `30 passed in 13.21s` | Inventory + Reservation 原 21 项与 Wallet 9 项同一 M0→M7 Schema 全绿；最终夹具保留 Aerich/M6 色槽/M7 单例证据 |
| Wallet/CI 契约专项 | `164 passed in 4.38s` | Wallet 非 MySQL 全模块与 workflow 契约 |
| 完整后端 | `2000 passed, 30 skipped in 113.05s` | 30 项为三类 MySQL-only 门槛，真实联合结果如上 |
| 并发调账 | PASS | 不同 key 两笔均提交且无丢失更新；同 key 仅一笔流水/Audit，另一请求严格重放 |
| 并发余额支付 | PASS | 同 Order/key 只扣款一次，只生成一个 Payment、Settlement、流水与 Audit |
| 并发退款 | PASS | 只生成一个 Refund/退款流水/库存恢复/Audit，钱包和 Kit 各恢复一次 |
| 真实 1205 | PASS | 阻塞 User 行并将 session 超时降为 1 秒；首次 1205 后释放锁，第二个全新事务提交，零残留首轮写 |
| 1213 整事务重试 | PASS | 首轮 Refund、钱包入账、库存恢复与状态写完后注入 1213；整笔回滚，第二轮只留下唯一成功事实 |
| 跨域锁序 | PASS | Inventory 调账先持有 Kit 行锁，Refund 按资金链走到 ProductKit 后在 `performance_schema.data_lock_waits` 可观察；释放后双方完成，无锁反转或重复事实 |
| `EXPLAIN` | PASS | 2,000 WalletTransaction + 2,000 Payment 样本；owner 唯一锁、两类幂等和两类稳定分页均命中冻结索引 |

命中的索引为：`wallet_accounts.user_id`、`uidx_wallet_transaction_idempotency`、`idx_wallet_transaction_wallet_created_id`、`uidx_payment_idempotency`、`idx_payment_user_created_id`。没有发现需要新增索引、Schema 修复或迁移的实现缺陷。

## 4. CI 变更

- `backend-sqlite` 显式忽略 `tests/wallet/mysql`，避免普通 SQLite Job 依赖外部 MySQL。
- `backend-mysql-release` 联合命令增加 `tests/wallet/mysql`，继续复用固定 MySQL 8.0.46、回环非 3306、冻结 Schema、M0→M7 迁移与 `always()` cleanup。
- Wallet fixture 可显式使用独立 `WALLET_MYSQL_TEST_*`，也可在统一 Job 中复用受保护的 `INVENTORY_MYSQL_TEST_*`；两种路径都拒绝远端 host、3306 和非专用 Schema 前缀。
- CI workflow 契约测试和测试运行说明同步更新。

## 5. 清理与剩余门槛

初跑容器 `codex-pinkdoohub-wallet-gate-20260907` 与最终复跑容器 `codex-pinkdoohub-wallet-gate-20260907-rerun` 均已通过精确名称停止，并因 `--rm` 删除；`docker ps -a` 无这两个名称，13316 无监听，复跑临时迁移日志也已删除。只保留任务开始前已有的 `pinkdoohub-dev-redis`；没有遗留 Schema、容器、端口、PTY 或后台测试进程。

R-029 的仓库缺口已关闭，但以下项目不在本报告内，发布仍为 No-Go：

- 新提交/PR merge-ref 的远端 GitHub Actions 8/8 与 Wallet-expanded JUnit/cleanup artifact；
- Gate A 当前版本只读盘点及非空 M2→M7 升级入口；
- M4 持久迁移、wallet backfill、legacy manual settlement backfill、只读 reconcile；
- MARD 持久 MySQL/对象存储发布；
- release-eligible RC、真实 HTTPS Origin、微信合法域名和 iOS/Android 真机验收。
