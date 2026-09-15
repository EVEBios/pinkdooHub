# Phase 9.4 Gate A 持久备份与隔离恢复报告

> **Result:** PASS（同机备份与独立恢复流程范围）  
> **Backup ID:** `20260901t232740z`（UTC）  
> **Runtime Candidate:** `51ad3152c8960bc133c25a600418f5f850d69199`  
> **Operations Revision:** `d1f3379a9a359de8026eb49ec871db561363f2ca`  
> **CI:** [GitHub Actions Run 33570862787](https://github.com/EVEBios/pinkdooHub/actions/runs/33570862787)，8/8 Job success  
> **Executed At:** 2026-09-02（Asia/Shanghai）  
> **Executor / Reviewer:** Yijie Shen

本报告证明真实 Gate A 主机完成权威 MySQL 与商品图片备份，并在无宿主端口、
不引用来源卷的独立 Compose project 中恢复和启动 Restore App。当前备份仍位于
同一服务器，未形成加密异机副本，因此不能覆盖服务器或系统盘故障，也不改变
Gate A 的 **No-Go / Not Authorized** 结论。报告不包含密码、Token、私钥、连接串、
SQL 内容或 Secret 值。

## 1. 备份边界与 Artifact

备份工具先验证 Root 配置/Secret、Runtime image、首次迁移 Record，以及
MySQL/Redis/App/Nginx 四项健康；随后停止 Nginx/App 形成停写窗口，MySQL/Redis
保持运行。备份和 App/Nginx 自动恢复共约 20 秒，恢复后 Liveness/Readiness 均通过。

| Artifact | 权限 | 大小 | SHA-256 |
|----------|------|------|---------|
| MySQL 逻辑备份 | `root:root 0600` | 148,782 bytes | `70e8729f80bf50faf55e8d3fea976a65e7c05d1e34afd6d160eb22860981047a` |
| 商品图片 Tar | `root:root 0600` | 10,240 bytes | `ac155f4edb930dea6bb511f1d3e42dc6c265b7d51859595ffd042e460a9a1103` |
| Backup Record | `root:root 0644` | 1,301 bytes | 脱敏摘要；不保存 Artifact 内容或 Secret |

MySQL 使用 `--single-transaction`、routines、triggers、hex blob 和关闭 GTID 注入的
逻辑备份；图片在同一停写窗口从固定 named volume 归档。当前图片卷为空，Tar 仍是
合法且可验证的空归档。

## 2. 来源数据库摘要

| 指标 | 值 |
|------|----|
| Aerich | `0_20260810101218_init.py,1_20260813130455_add_order_tables.py,2_20260814104655_add_inventory_transactions.py` |
| Tables / Columns | 10 / 90 |
| Constraints / Statistics | 26 / 63 |
| Users / Products / Images | 0 / 0 / 0 |
| Orders / Items / Inventory transactions | 0 / 0 / 0 |
| Kit stock / Inventory change / Order total | 0 / 0 / `0.00` |
| Audit logs | 0 |

该摘要反映 Bootstrap 和业务测试数据尚未写入。它足以证明 Schema 与空数据恢复，
但不替代后续含代表性 Gate A 测试数据的周期恢复演练。

## 3. 独立恢复结果

恢复 project 固定为
`pinkdoohub-gatea-restore-20260901t232740z`，只包含独立 MySQL 8.0.46、空 Redis、
临时图片卷、image-init 和 Restore App；所有服务只加入 internal network，没有任何
宿主 publisher，也没有引用 `pinkdoohub-gatea-*` 来源 volumes。

| 检查 | 结果 |
|------|------|
| Artifact 路径、大小和 SHA-256 重检 | PASS |
| MySQL 备份导入独立临时卷 | PASS |
| 10 表/90 列/26 约束/63 statistics 与业务摘要比较 | PASS |
| 图片 manifest 比较 | PASS（0 files） |
| Restore App readiness | PASS |
| Redis 恢复策略 | PASS；空实例 `DBSIZE=0`，旧 refresh 会话失效 |
| 宿主端口 | PASS；无 publisher |
| 来源 Gate A | PASS；恢复期间未停止或修改来源 volumes |
| 临时资源清理 | PASS；恢复 containers、network、MySQL/images volumes 均为 0 |

恢复验证从 `2026-09-01T23:28:23Z` 到 `23:28:48Z`，约 26 秒。成功 Record 明确记录
`database_matches=true`、`images_match=true`、`restore_app_ready=true`、
`refresh_sessions_invalidated=true` 和 `temporary_resources_removed=true`。

## 4. Redis 策略

Redis 当前只保存 refresh-token 会话，不保存 Product、Order、Inventory 或图片
权威数据。恢复旧 AOF/RDB 可能重新激活备份时仍存在、但灾难发生前已撤销的 Token；
因此恢复固定使用空 Redis，要求所有用户重新登录。来源 Redis named volume 仍用于
正常重启持久化，本次没有停止、导出或删除它。

## 5. 保留、清理与剩余门槛

- 有意保留两个 `0600` Artifact、Backup/Restore Record、来源 4 个健康容器、3 个
  持久 named volumes、版本化 Release 和回滚配置。
- 已清理备份 helper、所有 restore containers、internal network、两个临时 volumes、
  上传归档和命令会话；来源唯一 listener 仍为 `127.0.0.1:18080`。
- 同机备份不能覆盖主机、系统盘、账号或区域级故障。Gate A 决策前仍需冻结保留期、
  删除审批、加密、独立故障域副本和周期演练。
- Bootstrap 后需要再执行一次包含受控用户、Audit 与代表性业务/图片数据的备份恢复，
  当前空数据结果不能替代该证据。
- DNS/HTTPS、微信合法域名、真实 RC、iOS/Android 真机和体验版上传仍未执行。

本次关闭 Phase 9.4 的“空数据持久 Gate A 同机备份与独立恢复机制”子门槛；不授权
体验版上传、分发、提审或公开发布。
