# M7 一次性 MySQL 发布门槛报告

> **Result:** PASS（本地一次性 MySQL 范围；远端后续结果见第 7 节）
> **Release Decision:** BLOCKED / No-Go
> **Executed At:** 2026-09-07（Asia/Shanghai）
> **Branch:** `feature/phase9-ci`
> **Execution Base:** `c6778e79cccd7940928431ab17b958ea19993915`
> **Post-run Local Commit:** `58d8435d76022db41e625e3cdb7704a37943c94d`

本报告记录 M7 CI 修复在专用、可销毁 MySQL 上的本地证据。测试运行时对象是基础
HEAD `c6778e7...` 加尚未提交的 CI/MySQL 测试改动，不是干净 commit，也不是远端
Runner；当时工作树还包含 sibling agent 的未提交发布文档/本地 seed 改动，它们不属于
本门槛范围。运行后，相同的 10 个 tracked CI/测试文件被记录为本地提交 `58d8435...`；
这 10 个文件相对执行基础 HEAD 的 binary diff SHA-256 为
`3e973dd9a0f7d43f16a32f301981a1b58dfce407db2c7fbcb4d8eda3bfda625c`，复核命令为
`git diff --no-ext-diff --binary <Execution Base> <Post-run Local Commit> | shasum -a 256`。
执行者确认最终三组测试后没有再修改这些文件。
本节保留报告编写时的历史事实：当时 `origin/feature/phase9-ci` 仍指向执行基础
`c6778e7...`，尚无本地提交 `58d8435...` 的 GitHub Actions 结果。2026-09-07 后续已将
包含该修复的候选 head `4d6430c...` 推送，并由 Run 34129910349 取得 8/8；精确远端
证据见第 7 节。该后续结果仍不能关闭 Gate A 持久迁移、真实 RC 或真机门槛。

报告不包含密码、Token、私钥、带凭据连接串或真实用户数据。

## 1. 隔离边界

| 项目 | 本次值 |
|------|--------|
| MySQL | 官方 arm64 `mysql:8.0.46` |
| 容器 | `pinkdoohub-m7-gate-0907`；完整 ID `856bea0539292afd60fff52f99ee823a8153b117df572fe5d814446522d95016` |
| 端口 | `127.0.0.1:13306 → 3306`；未使用默认 `3306` |
| Schema | `pinkdoohub_inventory_4311_ci` |
| 临时目录 | `/tmp/pinkdoohub-m7-gate.DGOEgT` |
| 持久资源 | Gate A、共享、预发布、生产 MySQL 及本地 `db.sqlite3` 均未触碰 |

既有 `pinkdoohub-dev-redis` 和 PID `39691` 不属于本次任务，未复用、停止或修改。

## 2. 主迁移链与 Snapshot

本轮真实执行以下顺序，全程未使用 `--fake`：

1. 从空专用 Schema 执行 Aerich M0→M7；
2. 真实 downgrade M7→M6，在 M6 可表达结构中写入 2 条 Reservation 与 2 条
   StoreBusinessDay 非敏感历史；
3. 再真实 downgrade M6→M5，在 M5 结构中写入非零库存 fixed Kit 历史；
4. 正向执行 M5→M6→M7；
5. 再执行一次 upgrade，结果为 `No upgrade items found`；
6. 最终 snapshot 状态为 `release-gate-ready`，Aerich 版本链精确包含 M0–M7 八条记录。

| Snapshot | 结果 | 关键断言 |
|----------|------|----------|
| M6 | PASS | 221 个 placeholder 槽及 shape 正确；fixed Kit 历史兼容；19 个关键列、4 个命名外键、7 个命名索引正确 |
| M7 | PASS | `reservation_settings` 恰好 1 行；默认 `monday`；`singleton_key = 1` CHECK 有效；命名单列 UNIQUE 索引恰好 1 个 |
| M5/M6 历史 | PASS | 2 条 Reservation、2 条 StoreBusinessDay 及其状态、原因、时间、Product/Option 快照逐字段不漂移；fixed Kit 保持兼容 |

## 3. 历史基线矩阵

Aerich 0.9.3 没有定向 target-upgrade 参数。每个场景因此都先独立重建专用 Schema 并
完整升级，再用已 Review 的 downgrade 精确回到目标 Mx；脚本先断言 Aerich 版本前缀，
写入该版本能够表达的非敏感历史，最后通过正式 upgrade 正向到 M7，并核验通用历史与
版本特有历史不漂移。

| 起点 | 终点 | 结果 |
|------|------|------|
| M0 | M7 | PASS |
| M1 | M7 | PASS |
| M2 | M7 | PASS |
| M3 | M7 | PASS |
| M4 | M7 | PASS |
| M5 | M7 | PASS |
| M6 | M7 | PASS |

七个场景均逐一真实执行；没有通过直接修改 Aerich 表、伪造版本或复用上一个场景的
残留 Schema 制造结果。该矩阵只证明一次性 CI 环境中的实现兼容性，不自动把 M0–M6
批准为持久 Gate A 的既有库升级起点。

## 4. 测试结果

| 范围 | 结果 |
|------|------|
| CI workflow、checker、M5/M7 静态迁移契约 | `20 passed in 0.64s` |
| Reservation 非 MySQL 回归 | `83 passed in 1.78s` |
| `tests/inventory/mysql tests/reservation/mysql` 联合 JUnit | `tests=21, failures=0, errors=0, skipped=0`；`21 passed in 8.69s` |

联合 MySQL 门槛包括：settings 单例行锁串行化、真实
`performance_schema.data_lock_waits`、Reservation ID 稳定锁序、settings/批量取消/
Audit 整体回滚，以及首次事务注入 1213 后退出失败事务、以全新事务完整重试。冻结的
MySQL 瞬态重试集合仍精确为 `{1205, 1213}`。

矩阵完成后的第一次联合门槛曾发现测试污染：M6 历史矩阵为色槽 1 写入了已配置样本，
而 fixture 有意保留 M6 palette 证据，导致 placeholder 断言失败。测试没有被放宽；随后
从空专用 Schema 重新建立完整 CI 主链与 placeholder snapshot，再取得上表最终无污染的
21/21 JUnit。该中间失败不能改写成第一次即通过。

## 5. Cleanup 结果与已知证据异常

实质清理结果为：

- 专用 Schema DROP 成功；
- 容器 stop 成功，并因 `--rm` 立即自动删除；
- `container_running=false`；
- 13306 端口关闭；
- 临时 matrix runner、字节码和报告目录已移出工作区，原临时路径不存在；
- 按完整容器 ID、精确名称、`docker inspect`、`lsof` 与 TCP connect 复核，容器不存在、
  端口无监听。

通用 cleanup checker 的本地 JSON 必须如实解释为
`rc=1 / status=cleanup-failed`：`--rm` 容器在 stop 后已不存在，checker 因而得到
`container_inspected=false`；其余字段为 `schema_dropped=true`、
`container_stopped=true`、`container_running=false`、`port_closed=true`。后续精确
复核证明资源已清理，但不能把 checker 自身写成全绿，也不能把本地复核冒充尚不存在的
远端 cleanup artifact。

## 6. 结论与未关闭门槛

本报告足以说明当前 M7 CI/MySQL 改动在一次性 MySQL 8.0.46 上完成了 0→7、M0–M6
历史基线升级、M6/M7 snapshot 和 21 项联合门槛；它只关闭本地可销毁环境的实现风险。

以下事项在本地执行当时仍为 **BLOCKED / NOT RUN**：

- 本地提交 `58d8435...` 当时尚未 push，未取得同一干净 SHA 的远端 8/8 GitHub
  Actions 和远端 cleanup artifact；既有 Run 34104680282 保留为 7/8 失败记录；该项
  后续已由第 7 节的 Run 34129910349 关闭；
- Gate A 最后证据为非空 M2，但当前真实 Aerich 状态尚未重新只读查询；仓库没有获批的
  既有库升级入口，且现有 `gatea_operations initial-migrate` 只接受空库。若实际仍为
  M2，M2→M7 的停写、备份/独立恢复、逐步迁移和候选 Record 路径尚不存在；
- Wallet 的扩展并发、1205/1213、锁序、`EXPLAIN` 与资金/库存联合 MySQL 门槛未由
  本报告覆盖，Gate A wallet/legacy backfill 与只读 reconcile 也尚未执行；
- SQLite-only MARD 导入器不能承担 Gate A MySQL、持久图片/对象存储和商品颜色库存发布；
- 未连接 Gate A、共享、预发布或生产 MySQL，未构建 release-eligible RC，未修改微信
  后台，也未执行 iOS/Android 真机矩阵。

因此 Gate A/Gate B 的最终结论继续为 **No-Go / Not Authorized**。

## 7. 远端后续证据（2026-09-07）

包含本地修复提交及其后续文档/测试数据收口的 PR head
`4d6430c1bf9532d644bd7039ed7603fe9ee2c2bf` 已推送。GitHub Actions
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349) 在 PR
merge-ref `ccbbe9dcb675a99369867814386051befc5922f2` 的干净 checkout 上 8/8 success：
远端 SQLite 为 `2000 passed, 2 skipped`，MySQL 联合门槛为 `21 passed`，MySQL cleanup
步骤成功，并保存 7 组带 merge-ref、Run ID 和 GitHub SHA-256 digest 的 artifact。

精确 Job 时间、artifact 名称、大小、digest 与仍未关闭的 Gate A 边界见
[M7 当前候选远端 CI 报告](m7_remote_ci_2026-09-07.md)。远端 CI 已关闭，但整体发布
结论仍为 **No-Go / Not Authorized**。
