# Phase 9.4 Gate A 代表性数据与二次隔离恢复报告

> **Result:** PASS（受控代表性数据、非空备份与独立恢复范围）
> **Backup ID:** `20260902t014211z`（UTC）
> **Runtime Candidate:** `51ad3152c8960bc133c25a600418f5f850d69199`
> **Operations Revision:** `351149184e244cf118fef60257156279bffef572`
> **Implementation CI:** [GitHub Actions Run 33576453364](https://github.com/EVEBios/pinkdooHub/actions/runs/33576453364)，8/8 Job success
> **Executed At:** 2026-09-02 09:41:03–09:43:25（Asia/Shanghai）
> **Executor / Reviewer:** Yijie Shen

本报告证明真实腾讯云 Gate A 主机通过当前 loopback 正式 API 写入最小代表性数据，
随后生成权威 MySQL 与三张商品图片的一致备份，并在不引用来源卷、不发布宿主端口的
独立 Compose project 中完成恢复、数据比较和 Restore App readiness。执行人管理员
身份、密码、Token、合成用户密码、手机号和连接 Secret 均未进入仓库、命令参数、
日志或成功 Record。

本次关闭 Phase 9.4 的“代表性数据非空备份与隔离恢复”子门槛。同机备份仍不能覆盖
主机、系统盘、账号或区域级故障；DNS、HTTPS、微信合法域名、真实 RC 和真机仍未
完成，因此 Gate A 继续保持 **No-Go / Not Authorized**。

## 1. 执行边界

- 主机继续使用 Runtime candidate `51ad315...` 与既有 App image；本次没有重建或
  替换业务镜像、修改 API、Schema/Aerich、依赖或应用版本。
- Operations 先在 Run 33576453364 的 8 个 Job 全绿后切换到 `3511491...`；该修订
  只增加代表性数据编排、测试和文档。
- 管理员当前密码只经真实 TTY 隐藏双输入并保留在进程内存，不接受参数、环境变量或
  文件；合成用户密码由 `secrets` 随机生成且只存在于同一进程内存。
- 所有业务写入均经过 `127.0.0.1:18080` Nginx 和既有正式 API；SQL 只用于写入前后
  的只读摘要与业务断言，没有直接写 Model、数据库或图片卷。
- 工具要求 Bootstrap 后精确空业务基线、三项持久卷、迁移/Bootstrap Record、四项
  服务健康和唯一 loopback publisher 全部匹配；成功 Record 已存在时拒绝重跑。

## 2. 代表性数据结果

代表性数据操作从 `2026-09-02T01:41:03Z` 到 `01:41:19Z`，共完成 26 个受控 API
请求。流程在成功前注销并验证撤销合成用户与本次管理员 Refresh 会话，禁用合成用户
并确认其再次登录被拒绝。

| 指标 | Bootstrap 后基线 | 写入后 | 结果 |
|------|------------------|--------|------|
| Users | 1 | 2 | PASS；唯一管理员保持正常，合成 USER 最终禁用 |
| Products / Experience options | 0 / 0 | 2 / 1 | PASS；Experience 与 Kit 均为 Online |
| Product images / Kits / Kit stock | 0 / 0 / 0 | 3 / 1 / 10 | PASS |
| Orders / Items / Order total | 0 / 0 / `0.00` | 2 / 3 / `248.00` | PASS |
| Inventory transactions / net change | 0 / 0 | 3 / 10 | PASS；`+10/-2/+2` |
| Audit logs | 3 | 21 | PASS |

两笔订单分别为一笔 Cancelled 混合订单和一笔 Completed Experience 订单；三条库存
流水分别为管理员调整、订单扣减和取消恢复，各恰好一条。代表性数据 Record 位于
`records/representative-data/gatea-representative-data.json`：

| 属性 | 结果 |
|------|------|
| Owner / mode / size | `root:root 0644` / 1,791 bytes |
| SHA-256 | `0ca882b40e13851225fc7266b5c74daa32cc80f402a49777dcef4f8b622b49d7` |
| 图片 / 请求 | 3 files / 26 requests |
| 会话与账号清理 | 两类 Refresh 均撤销；合成 USER 已禁用 |
| PII / Secret | `pii_recorded=false`、`secret_values_recorded=false` |
| 总结论 | `passed=true` |

## 3. 非空一致性备份

Backup `20260902t014211z` 从 `01:42:32Z` 到 `01:42:51Z`。工具先停止 Nginx/App
形成约 20 秒停写窗口，MySQL/Redis 保持运行；完成 MySQL 单事务逻辑备份和图片卷
归档后自动恢复 App/Nginx，并重新通过 liveness/readiness。

| Artifact | 权限 | 大小 | SHA-256 |
|----------|------|------|---------|
| MySQL 逻辑备份 | `root:root 0600` | 154,702 bytes | `370801ee1789974e6bb12ac9d66d37fb436d46a746b468d9cbea0d5076f4b5a8` |
| 商品图片 Tar | `root:root 0600` | 10,240 bytes | `66fbc941c3f9c021fb4b79f5690814c248a4529f0fb9148644c2e6b573a18443` |
| Backup Record | `root:root 0644` | 1,622 bytes | `15f03919ff82b3bcc37c26f95d9f8b5943fe85bb5718f83f7b84a0a2429acce2` |

独立复核重新读取 Artifact 并计算 SHA-256、大小和图片 manifest，全部与 Backup Record
一致；数据库摘要与代表性数据写入后完全相同，包括 10 表、90 列、26 个约束、63 项
statistics、2 个用户、2 个 Product、3 张图片、2 个订单和 3 条库存流水。

## 4. 独立恢复结果

恢复 project 为 `pinkdoohub-gatea-restore-20260902t014211z`，从 `01:42:59Z` 到
`01:43:25Z`。它只使用独立 internal network、临时 MySQL/图片 named volumes、空
Redis、image-init 和 Restore App；不加入来源 project、不挂载来源卷，也不发布任何
宿主端口。

| 检查 | 结果 |
|------|------|
| Artifact 路径、大小、SHA-256 | PASS |
| 数据库 Schema 与完整业务摘要 | PASS；`database_matches=true` |
| 三张图片内容 manifest | PASS；`images_match=true` |
| Restore App readiness | PASS |
| Redis 恢复策略 | PASS；空实例启动，旧 refresh 会话失效 |
| 宿主端口 | PASS；`host_ports_published=false` |
| 临时资源清理 | PASS；container / volume / network 独立复核均为 0 |

Restore Record 为 `root:root 0644`、508 bytes，SHA-256 为
`d76371e1ab2721b633635eb7260396c2403abdd6555babcfcc9d97743a3dda45`；其
`temporary_resources_removed=true`、`refresh_sessions_invalidated=true` 和
`passed=true`。

## 5. 来源环境、清理与剩余门槛

- 来源 MySQL、Redis、App、Nginx 最终全部 Healthy；Readiness 为 HTTP 200 / `ready`，
  database/redis 均为 `up`，唯一业务 listener 仍为 `127.0.0.1:18080`。
- 当前 Operations 软链接为版本化 Release `351149184e244cf118fef60257156279bffef572`；
  一次性投放启动器、上传归档和本地临时文件均已删除。
- 有意保留本次两个 `0600` Artifact、三个脱敏 Record、代表性 Gate A 数据、来源三个
  持久 named volumes、四个健康常驻服务、版本化 Release，以及此前空数据备份
  `20260901t232740z` 作为流程历史证据。
- Redis 不作为权威备份资产；灾难恢复固定启动空 Redis，从而使备份点之前的 refresh
  会话失效并要求重新登录。
- 仍需冻结备份保留期、删除审批、加密、独立故障域副本、恢复授权和周期演练频率。
- DNS/证书、80/443、微信 request/upload/download 合法域名、真实 HTTPS Origin RC、
  iOS/Android 真机、弱网/前后台矩阵和体验版上传仍未执行。

本次不授权体验版上传、分发、提审或公开发布。
