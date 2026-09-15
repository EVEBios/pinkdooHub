# Gate A M2→M7 升级、综合测试数据与数据后恢复报告

> **Result:** PASS（不依赖域名的 Gate A 服务端范围）  
> **Gate A Decision:** No-Go / Not Authorized  
> **Execution Date:** 2026-09-08  
> **Runtime Candidate:** `73dca350505d43775fb1ff1158ccf6aabc221998`  
> **Runtime Image ID:** `sha256:d508e9d9cba0abd3b12d6a6361be9242074785fbd397222f3fd6f38a4d027b53`  
> **Latest Operations Candidate:** `353455bbd05d658bc7b99753d790149d3ce48041`  
> **Latest CI:** [GitHub Actions Run 34178908663](https://github.com/EVEBios/pinkdooHub/actions/runs/34178908663)

本报告关闭持久 Gate A 的 M2→M7 升级、Wallet 历史补齐/对账、221 色与
持久图片、M7 综合合成测试数据、候选级韧性、数据后一致备份与独立
恢复范围。它不依赖备案/域名等待，也不替代真实 HTTPS Origin、微信合法
域名、`release_eligible=true` RC、体验版上传授权或 iOS/Android 真机矩阵。

## 1. 候选和 CI 证据

Runtime 保持为已经完成升级、重建和韧性验收的 `73dca350...`；本轮只安装
版本化 Operations Release，没有把 `/srv/pinkdoohub/gatea/current` 指向文档提交。
综合数据写入使用 Operations `c179ad8f...`，数据后备份最终使用包含
loopback 端口快速复用修复的 `353455bb...`。

Run 34178908663 于 `2026-09-08T02:06:28Z`–`02:10:50Z` 完成，PR head 为
`353455bbd05d658bc7b99753d790149d3ce48041`，干净 checkout 的 merge-ref 为
`92649bac7dc90aa3098c57d55aba05782e194e96`，8 个 Job 全部 `success`。

| Job | 结果 | 范围 |
|-----|------|------|
| `backend-sqlite` | success | 完整 SQLite 回归与 JUnit |
| `backend-mysql-release` | success | MySQL 8.0.46 M0–M7、三域门槛与 cleanup |
| `frontend-quality` | success | TypeScript、ESLint、Stylelint、Jest 与 CI policy |
| `openapi-contract` | success | OpenAPI 与生成类型阻断检查 |
| `weapp-build` | success | 微信非发布候选产物构建、扫描与留证 |
| `python-dependency-audit` | success | Python 依赖策略 |
| `npm-dependency-audit` | success | npm 可达性策略 |
| `repository-hygiene` | success | tracked 文件、Secret、diff 与干净树 |

Run 保留 7 组未过期 artifact；`openapi-contract` 按 workflow 只做阻断检查，
不上传 artifact，因此数量符合设计。

| Artifact | Bytes | GitHub digest |
|----------|------:|---------------|
| `backend-sqlite-92649bac7dc90aa3098c57d55aba05782e194e96-34178908663` | 36,279 | `sha256:bf50fa2bc4c155fac3b04c4276fa5b9057bbc79ee0c027be87f79ba5e37a83bc` |
| `backend-mysql-release-92649bac7dc90aa3098c57d55aba05782e194e96-34178908663` | 3,545 | `sha256:2f706aa46fc819181f4aecc134013a750c752e530aa30ea67529c5b8d3459f21` |
| `frontend-quality-92649bac7dc90aa3098c57d55aba05782e194e96-34178908663` | 32,507 | `sha256:a5849ed823e8a340476ede720d7e9d5b4dac8c59904af17c672ba06392187e3f` |
| `weapp-1.0.0-92649bac7dc9-34178908663` | 295,570 | `sha256:3d062dec0cc400cd4f48f9660e1dc496b71048015d97067044dc36a6a660a2f4` |
| `python-dependency-audit-92649bac7dc90aa3098c57d55aba05782e194e96-34178908663` | 1,206 | `sha256:8b36472d9e60429488bbf7ad0bbd2c706a8d0a89642f6ab150117bb56a2b5209` |
| `npm-dependency-audit-92649bac7dc90aa3098c57d55aba05782e194e96-34178908663` | 1,784 | `sha256:61233b6ff7200f5c848f8e4f4dd293ed661037e420d97ab964da4ee6420eb075` |
| `repository-hygiene-92649bac7dc90aa3098c57d55aba05782e194e96-34178908663` | 268 | `sha256:a59bd40af0910bcfe725ee618281a7804036cb19a2a1e574af78439929f68d20` |

`353455bb...` 的本地发布工具套件为 `169 passed`，本地完整后端套件为
`2039 passed, 31 skipped in 112.21s`。`31 skipped` 是需显式隔离 MySQL 环境的
已批准门槛，相应 MySQL 集合由远端 `backend-mysql-release` 覆盖。

## 2. 持久 M2→M7 升级

写入前只读采样确认持久 Gate A 的真实 Aerich 起点为 M0–M2，而不是沿用
2026-09-02 的历史推断。升级前 Backup `20260908t000731z` 已完成无宿主
端口的独立 Restore。受控升级随后逐步完成 M3→M4→M5→M6→M7，最终
结构为 22 表、217 列、83 约束和 173 索引统计行。

M4 后的历史准备按冻结上界执行：

- Wallet account preview/apply/二次 preview：`would_create=1` → `created=1` →
  `would_create=0`；
- legacy manual settlement preview/apply/二次 preview：`would_create=1` →
  `created=1` → `would_create=0`，`blocked=0`；
- 升级内对账：`scanned=1, mismatches=0, violations=0`。

M6 后使用冻结 manifest 向 Gate A MySQL 写入 221 个色槽，并向持久图片卷
原子发布 221 张确定性 PNG，总内容 128,325 bytes；manifest SHA-256 为
`45e37342ff77907556974bc78c501a3931fda9100afae4506a709ab8a11ad238`，图片集
SHA-256 为 `00b26503f2b896092bbfe9a2580d0b0d04a450ca2ca5edf56eb6f401b54f4418`。
M7 单例、默认周一固定店休和 CHECK/UNIQUE 均通过。候选升级 Record 为
`/srv/pinkdoohub/gatea/records/releases/73dca350505d43775fb1ff1158ccf6aabc221998.existing-database-upgrade.json`。

## 3. 候选韧性与综合合成数据

当前 Runtime 已重新完成 MySQL/Redis 依赖中断、App 重启、数据/图片不漂移、
四服务日志轮转和脱敏扫描。候选级 Record 为
`/srv/pinkdoohub/gatea/records/resilience/gatea-resilience-73dca350505d43775fb1ff1158ccf6aabc221998.json`。
当时数据库和 224 个图片文件前后完全一致。

综合数据写入前，Backup `20260908t004536z` 已经独立 Restore PASS。工具随后
经正式 loopback API 执行 82 个请求，创建 3 个合成 NORMAL USER、3 个 Wallet、
7 条 WalletTransaction、1 个 221 色自选 Kit（启用 3 色）、6 笔预留订单和 6 条
预约。主要分布为：

- 预留订单：Pending 1、Paid 3、Completed 2；Payment/Settlement 各 5，Refund 2；
- 预约：Pending 1、Confirmed 1、Rejected 1、顾客取消 1、`store_closed`
  取消 2；单日店休 1，当前每周店休为周一；
- 资金：三个合成 Wallet 合计余额 `160.00`，`recharge_orders=0`；
- 库存：启用色库存 148，覆盖订单扣减、取消恢复和 PAID 退款恢复。

最终数据库摘要为 5 User、3 Product、4 ProductImage 数据行、2 Kit，8 Order/
10 Item，订单总额 `492.00`，14 InventoryTransaction（净变化 155）和 68 AuditLog。
持久图片文件数从 224 增加到 225。

三个合成账号的随机密码只保存于
`/srv/pinkdoohub/gatea/records/representative-data/gatea-m7-synthetic-credentials.json`，
文件为 `root:root 0600`。成功 Record 为同目录的
`gatea-m7-representative-data-73dca350505d43775fb1ff1158ccf6aabc221998.json`，为
`root:root 0644`；它不记录 SUPER_ADMIN 凭据、Token、手机号或请求/响应正文。
三个合成会话与 SUPER_ADMIN 会话全部撤销，没有残留 `.pending` 文件。

写入后二次 `wallet_reconcile` 为
`scanned=4, mismatches=0, violations=0`。密码注册只在创建合成用户时临时开启，
成功后已恢复 `PASSWORD_REGISTRATION_ENABLED=false`并重建 App；新密码注册再次
按契约被拒绝。

## 4. 数据后备份、失败收敛与修复

首次数据后 Backup ID `20260908t020111z` 完成了 MySQL/图片导出，但在快速恢复
App/Nginx 时，旧 Operations 用未设 `SO_REUSEADDR` 的临时 `bind()` 将刚关闭的
`127.0.0.1:18080` TCP 回收窗口误判为真实监听占用。失败路径按契约：

- 删除未成功留证的 MySQL/图片导出，不写 Backup Record；
- 不修改权威数据，数据库摘要与 225 图片仍与 Seed Record 精确一致；
- 等待 TCP 回收窗口后恢复原 Runtime，四服务及 liveness/readiness 重新正常。

`353455bb...` 在探测的 `bind()` 前设置 `SO_REUSEADDR`，但仍依赖内核拒绝真实
活动监听者；同时新增调用顺序和真实活动端口回归。该提交在 Run 42
8/8 后才作为新 Operations Release 投放。

修复版从 `2026-09-08T02:12:31Z` 开始创建 Backup `20260908t021224z`，到
`02:12:51Z` 恢复长期 App/Nginx 健康。备份资产为：

| Artifact | 权限 | Bytes | SHA-256 |
|----------|------|------:|---------|
| MySQL SQL | `root:root 0600` | 819,133 | `6c73089242f2585b1f09bfd4e1515fd06f183345483b7e3a62a2a920230275c9` |
| Images Tar | `root:root 0600` | 348,160 | `477a5957a6638ab1b535b8a34f0801b9f6f6ad853cf4d17810c86eccc2a9d5c2` |

独立 Restore project `pinkdoohub-gatea-restore-20260908t021224z` 于
`02:12:57Z`–`02:13:25Z` 完成：数据库和 225 图片匹配，Restore App ready，Redis 从空
实例启动并使历史 refresh 会话失效，没有发布任何宿主端口。成功、失败和
临时 `migrate`/`image-init` 任务容器均已复核清除，Restore 的容器、网络和卷均为零。

当次 Backup 随后经受控 SSH 精确下载四个已验证成员，在管理电脑形成加密
异机副本并立即完成解密复核：

| 项目 | 结果 |
|------|------|
| 副本路径 | `$HOME/Backups/pinkdoohub/gatea/20260908t021224z.pdhb` |
| 算法 | AES-256-GCM；数据密钥由 RSA-3072 / OAEP-SHA256 封装 |
| key ID | `595d864b7c45c7cfa26a03184085e36bd6f304c929fe1a9c69d0b580f6bcfcae` |
| 副本 | `0400`；89,861 bytes；SHA-256 `c8cf3e0cabfa668f0feaa7ffcb90cf1ae7770046d8b868c7af7d5e805b17acfd` |
| 副本 Record | `0600`；`source_restore_passed=true`、`verified_after_export=true`、`passed=true` |
| 数据最小化 | `pii_recorded=false`、`secret_values_recorded=false` |

复核同时验证 AEAD、固定 Tar 成员、四个来源文件大小/SHA-256 及服务器
Backup/Restore PASS。私钥与副本分离，没有上传到服务器或写入仓库。

## 5. 最终运行与安全复核

最终 MySQL、Redis、App、Nginx 全部 Healthy，liveness/readiness 均为 HTTP 200，
唯一 publisher 仍为 `127.0.0.1:18080`。数据库摘要同时与综合数据成功
Record 及 Backup Record 精确一致，225 个图片 manifest 与 Backup 精确一致。

长期 App PID 1 的最终非 Secret 开关为：

```text
WALLET_ADMIN_WRITE_ENABLED=true
WALLET_ORDER_PAYMENT_ENABLED=true
WALLET_REFUND_ENABLED=true
WALLET_TOPUP_ENABLED=false
PAYMENT_PROVIDER=disabled
PASSWORD_REGISTRATION_ENABLED=false
```

前三项只用于 Gate A 无真实资金的内部人工验收；真实充值/微信支付继续
503 且零写入。最终 24 小时组合日志扫描 165 行，解析 8 条 Nginx 请求，
4xx/5xx 均为 0，精确 Secret 和高置信敏感模式匹配均为 0；成功结果不保存
原始日志。

## 6. 未关闭项与发布决定

截至本报告，除域名链路外没有另一个可在当前 loopback 服务器范围内继续关闭的
P0/P1 项。以下项直接依赖备案生效、DNS/证书和微信平台/真机，仍为
Gate A blocker：

1. 真实 API/图片 HTTPS Origin、DNS、TLS 证书和续期责任复核；
2. 微信后台 request/upload/download 合法域名；
3. 使用真实 Origin 重建同 SHA、`release_eligible=true` 的 RC；
4. 取得独立上传/分发授权后创建体验版；
5. iOS/Android 真机的全业务、权限、弱网、断网、前后台、锁屏、上传中断和
   unknown 结果收敛；
6. 所有必需真机项通过后的 Gate A Go/No-Go 签署。

因此当前决定仍是 **No-Go / Not Authorized**；没有修改 DNS、证书、微信后台、
体验版、审核或公开发布状态。

## 7. 资源与保留

- 有意保留：四个长期 Gate A 服务、三个持久卷、当前 Runtime Release、版本化
  Operations Release、升级/韧性/Seed/Backup/Restore Record、`0600` 合成凭据和已
  齐备的服务器备份资产、管理电脑加密副本与独立私钥；
- 已清理并复核：投放临时 archive、失败 Backup `20260908t020111z` 的导出物、
  独立 Restore 容器/网络/卷、一次性 `migrate`/`image-init` 容器和 `.pending` 凭据文件；
- 未接触：本地 `db.sqlite3`、共享/production 数据库、域名、证书、微信后台和体验版。
