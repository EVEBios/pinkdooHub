# Phase 9 环境矩阵与 Secret 清单

> **Status:** 9.1–9.3 Complete; 9.4 Gate A pre-ICP server and governance controls passed
> **Last Updated:** 2026-09-02
> **Values Policy:** 本文只记录键名和责任，不记录真实值

## 1. 环境矩阵

| 层级 | 前端环境 | 后端环境 | 数据库 | Redis | 网络 | 数据性质 |
|------|----------|----------|--------|-------|------|----------|
| Local | `TARO_APP_APP_ENV=development` | `APP_ENV=development` | SQLite | 本地 Redis | HTTP localhost/局域网；开发工具可临时关闭域名校验 | 可丢弃开发数据，不产生发布证据 |
| CI | `testing` | `testing` | 临时 SQLite + 专用 MySQL 8+ Job | CI 隔离实例 | Job 内部网络 | 每次重建，禁止访问共享资源 |
| Release Rehearsal | `production` 构建模式 | `production` 配置语义 | 生产相似、可销毁 MySQL 8+ | 生产相似隔离 Redis | 真实 HTTPS 测试域名；开启微信域名校验 | 合成/脱敏数据，可完整备份恢复 |
| Gate A Experience | `production` 构建模式 | `production` 配置语义 | 独立持久 MySQL 8+ | 独立持久 Redis | 微信体验版 + 测试 HTTPS 域名 | 仅受邀测试数据，有保留和清理期限 |
| Production | `production` | `production` | 持久 MySQL 8+ | 持久 Redis | 正式 HTTPS 域名 | 仅 Gate B 授权后启用 |

发布演练和 Gate A 都必须走与生产相同的安全配置语义，才能发现 debug、SQLite、弱 Secret 等配置差异；“staging/experience”属于部署层级和数据分类，不应靠放宽 `APP_ENV` 表示。若需要在监控或运维界面区分层级，应使用独立、非安全开关的部署元数据，不能把测试数据环境误当作正式商业生产。

9.2.4 的 CI MySQL 密码是仓库内明确标识的 disposable test credential，只用于每次新建的 service container，不是 Gate A/生产 Secret。安全脚本要求 Aerich 的 `DB_*` 与 pytest 的 `INVENTORY_MYSQL_TEST_*` 完全相同，并固定 `127.0.0.1:13306` 和精确专用 Schema；任何远端地址、3306、目标漂移或未显式启用都会在连接前失败。真实 Gate A 数据库凭据仍必须由受保护 Secret 系统注入，不能沿用该测试值。

## 2. 当前已有配置键

### 2.1 后端

| 键 | Secret | 当前能力 | Gate A 要求 | 责任角色 |
|----|--------|----------|------------|----------|
| `APP_NAME` | 否 | 已有 | 固定展示值 | Yijie Shen |
| `APP_VERSION` | 否 | 已有，默认 0.6.0 | 与 Release Record 对齐 | Yijie Shen |
| `APP_ENV` | 否 | development/testing/production 校验 | 明确环境，不靠默认值 | Yijie Shen |
| `APP_DEBUG` | 否 | production 启动强制 `false` | Gate A/生产必须显式 `false` | Yijie Shen |
| `DB_ENGINE` | 否 | sqlite/mysql；production 强制 mysql | Gate A/生产必须显式 mysql | Yijie Shen |
| `DB_HOST`/`DB_PORT`/`DB_NAME` | 部分敏感 | 已有 | 从部署配置注入，不进入日志/前端 | Yijie Shen |
| `DB_USER`/`DB_PASSWORD` | 是 | 已有 | 最小权限账号；专用 Secret 注入 | Yijie Shen |
| `REDIS_URL` | 是 | production 强制 redis/rediss、有效且非本机 host；连接日志仅输出安全目标摘要 | 专用实例、认证/网络边界；CI 复核日志脱敏 | Yijie Shen |
| `PRODUCT_IMAGE_UPLOAD_DIR` | 否 | 已有 | Gate A 指向持久卷或隔离对象存储适配 | Yijie Shen |
| `PRODUCT_IMAGE_BASE_URL` | 否 | production 强制无凭据的绝对 HTTPS URL | 真实 HTTPS 可访问地址 | Yijie Shen |
| `JWT_SECRET_KEY` | 是 | production 拒绝弱值并要求 trim 后至少 32 字符 | 每环境独立随机值；保管和轮换记录 | Yijie Shen |
| `JWT_ALGORITHM` | 否 | production 固定 HS256 | 变更需安全 Review | Yijie Shen |
| `JWT_ACCESS_TOKEN_EXPIRE` | 否 | 已有 | 与测试/运营策略一致 | Yijie Shen |
| `JWT_REFRESH_TOKEN_EXPIRE` | 否 | 已有 | Gate A 可沿用；Gate B 与轮换设计一起冻结 | Yijie Shen |
| `PINKDOOHUB_BOOTSTRAP_PASSWORD` | 是 | 9.3.2 管理命令的非交互 Secret 输入；不进入应用常驻配置、参数或日志 | 只在首次初始化/严格重放命令进程短期注入，完成后撤销 | Yijie Shen |
| Phase 9.3 rotated bootstrap password | 是 | 仅由主机侧 HTTPS Smoke 读取，用于完成初始凭据轮换并验证独立 Restore App 登录 | 不进入 Compose 参数、应用常驻环境、日志或报告；随演练工作区清理 | Yijie Shen |

9.2.2 已实现上述 production fail-fast 规则，并让 Pydantic 配置错误隐藏原始输入；契约测试覆盖接受路径、每类拒绝路径和 Secret 不回显，后续干净 PR CI 与当前 Operations CI 均已重复通过。

### 2.2 微信前端

| 键/配置 | Secret | 当前能力 | Gate A 要求 | 责任角色 |
|---------|--------|----------|------------|----------|
| `TARO_APP_APP_ENV` | 否 | 已有三环境 | 微信 RC 使用 production 构建模式 | Yijie Shen |
| `TARO_APP_API_ORIGIN` | 否 | production 强制 HTTPS/非本机 | 替换 `.example.invalid`，只含 Origin、无路径/凭据 | Yijie Shen |
| `project.config.json` AppID | 否 | 已配置 | 确认属于目标小程序账号；不在日志重复传播 | Yijie Shen |
| `urlCheck` | 否 | 当前为 true | 保持 true；真机证据禁止关闭域名校验 | Yijie Shen |
| `miniprogramRoot` | 否 | 指向 `dist/weapp` | 与 CI artifact 一致 | Yijie Shen |
| `uploadWithSourceMap` | 否 | 当前为 false；9.2.3 本地 production artifact 扫描为 0 source map | Gate A 禁止上传 source map；远端 CI/真实 RC 重跑 | Yijie Shen |

所有 `TARO_APP_*` 都会进入客户端包，只能承载公开配置。任何 AppSecret、JWT、数据库、Redis、支付密钥或私钥都禁止使用该前缀。

2026-09-02 开发者工具检查发现被 Git 忽略的本机 `project.private.config.json` 曾把
权威 `urlCheck=true` 覆盖为 `false`；已只将该本机值恢复为 `true`。重新编译后工具
精确拒绝保留 `.test` Origin，证明合法域名校验 fail closed。该私有设置不进入候选或
manifest；真实 RC 仍以仓库配置、微信后台域名清单和真机结果三者共同为准。

## 3. 未来 Secret Inventory

| Secret | 首次需要 | 存放位置要求 | 读取主体 | 轮换/撤销要求 | 责任角色 |
|--------|----------|--------------|----------|---------------|----------|
| DB password | Gate A | CI/部署 Secret 系统 | 后端运行身份、迁移 Job | 人员变更/疑似泄漏/周期轮换 | Yijie Shen |
| Redis credential | Gate A | CI/部署 Secret 系统 | 后端运行身份 | 同上；连接日志必须脱敏 | Yijie Shen |
| JWT secret | Gate A | CI/部署 Secret 系统 | 后端运行身份 | 定义旧 Token 失效和轮换窗口 | Yijie Shen |
| Initial SUPER_ADMIN password | Gate A 首次初始化 | 部署 Secret 系统或人工 TTY 隐藏输入；不得放命令参数/仓库/报告 | 一次性 Bootstrap 命令 | 首次登录后按批准流程轮换并撤销初始 Secret | Yijie Shen |
| Backup encryption credential | Gate A | 与备份数据分离的 Secret 系统 | 备份/恢复 Job | 恢复演练验证；最小权限 | Yijie Shen |
| Image storage credential | Gate A 或 Gate B | CI/部署 Secret 系统 | 图片服务身份 | 权限限于目标 bucket/namespace | Yijie Shen |
| Monitoring ingest credential | Gate A 最低观察或 Gate B | CI/部署 Secret 系统 | 后端/前端上传 Job | 禁止进入客户端和公开日志 | Yijie Shen |
| WeChat AppSecret | Gate B 微信登录 | 后端 Secret 系统 | 微信身份交换服务 | 不下发客户端；泄漏立即重置 | Yijie Shen |
| WeChat Pay private key/API key/cert | Gate B 在线收款 | 专用 Secret/证书系统 | 支付后端 | 到期告警、轮换、吊销和审计 | Yijie Shen |
| WeChat upload private key | 自动上传被批准时 | CI Secret 系统 | 受保护上传 Job | 限制分支/环境；可立即撤销 | Yijie Shen |

Secret Inventory 的 Release Record 只记录 Secret ID/版本/更新时间，不记录值。

### 3.1 Gate A 实际保管映射

Phase 9.4 已在 `deploy/gatea/` 建立文件型 Secret 边界，并于 2026-09-02 在 Gate A
主机创建以下 Root 文件。本文及 Release Record 只记录路径、权限和读取主体，不记录
或导出真实值：

| Secret | 计划路径 | 宿主权限 | 读取主体 |
|--------|----------|----------|----------|
| DB app password | `/etc/pinkdoohub/gatea/secrets/mysql_app_password` | `root:10001 0440` | MySQL 初始化、App、迁移/Bootstrap Job |
| DB root password | `/etc/pinkdoohub/gatea/secrets/mysql_root_password` | `root:root 0400` | MySQL 初始化及后续受控备份/恢复；App 禁止读取 |
| Redis password | `/etc/pinkdoohub/gatea/secrets/redis_password` | `root:10001 0440` | Redis、App、迁移/Bootstrap Job |
| JWT secret | `/etc/pinkdoohub/gatea/secrets/jwt_secret` | `root:10001 0440` | App、迁移/Bootstrap Job |
| Initial SUPER_ADMIN password | `/run/pinkdoohub-gatea/bootstrap_password.pending` | `root:10001 0440` | 只在明确 Bootstrap override 中短期挂载，轮换后删除；`/run` 重启不保留 |

Secret 目录固定为 `root:root 0700`，宿主普通用户无法遍历。Compose 对本地文件型
Secret 使用 bind mount 并保留宿主元数据，因此三个 App Runtime Secret 使用宿主
未分配的数值 GID 10001 与 `0440`，供容器内固定 UID/GID 10001 只读；Root Secret
继续为 `root:root 0400` 且不挂载给 App。非 Secret 配置固定为
`/etc/pinkdoohub/gatea/config.env`、`root:root 0640`。只读预检会检查类型、所有者、
权限和非空大小，但不会读取或输出 Secret 值。该文件系统映射满足 Gate A 单机测试
环境的最小保管基线，不自动满足 Gate B 的集中 Secret Manager、审计或高可用要求。

Gate A 持久 Bootstrap 只允许 `gatea_bootstrap.py` 从人工 TTY 隐藏读取初始/最终
密码。初始值短暂落在上述 `/run` tmpfs 文件，最终值不落文件；两个值都不进入
命令参数、宿主/常驻应用环境、仓库、日志或 Record。初始值只由 Compose Secret
提供给一次性 Bootstrap 容器入口，并在该进程内转换为既有管理命令要求的短期
环境变量。工具在成功和失败路径删除初始 Secret，成功后同时撤销验证期间产生的
两个 Refresh 会话。脱敏 Bootstrap Record 只包含候选、用户 ID、唯一性/重放/
登录/轮换/清理布尔值和 UTC 时间，不保存身份字段。

2026-09-02 真实 Gate A 已完成该流程：唯一 SUPER_ADMIN 首次创建与严格重放、初始
登录、正式密码轮换、旧密码拒绝、正式密码登录和两个 Refresh 会话撤销均通过；临时
Secret、一次性容器和投放文件已清理。脱敏证据见
[`reports/phase94_gatea_bootstrap_2026-09-02.md`](reports/phase94_gatea_bootstrap_2026-09-02.md)。

Gate A 代表性备份数据工具不创建新的持久 Secret。执行人当前 SUPER_ADMIN 密码只经
TTY 隐藏读取并保留在宿主进程内存；合成 USER 密码由进程使用 `secrets` 随机生成，
只保留在同一进程内存。完成正式 API 数据链后，两个会话均注销并验证 Refresh 撤销，
合成 USER 固定禁用；成功 Record 不保存任何身份字段、密码、Token 或 hash。

2026-09-02 真实 Gate A 已完成该流程及后续非空备份/隔离恢复：2 个受控用户、2 个
Product、3 张图片、2 笔终态订单和 3 条库存流水均通过只读摘要；Backup
`20260902t014211z` 的 MySQL/图片 Artifact 为 `root:root 0600`，独立 Restore 使用
空 Redis、无宿主端口并在验证后删除全部临时资源。脱敏证据见
[`reports/phase94_gatea_representative_restore_2026-09-02.md`](reports/phase94_gatea_representative_restore_2026-09-02.md)。

### 3.2 Gate A 备份保管与 Redis 恢复策略

Gate A 权威备份资产是 MySQL 逻辑备份与商品图片归档。两者固定写入
`/srv/pinkdoohub/gatea/backups/{mysql,images}/`，文件为 `root:root 0600`；脱敏
Record 写入 `records/{backups,restores}/`。MySQL Root Secret 只在容器内通过
`/run/secrets` 供 `mysqldump/mysql` 读取，不进入命令参数、备份 Record 或日志。

Redis 当前只保存 refresh-token 会话，不保存 Product、Order、Inventory 或图片
权威数据。灾难恢复固定启动空 Redis，不恢复 AOF/RDB，使所有旧 refresh 会话失效
并要求用户重新登录；这比恢复可能包含已撤销 Token 的旧 Redis 快照更安全。该策略
不改变正常重启时现有 Redis named volume 的持久化行为。

同机 `0600` 备份不能覆盖主机或系统盘故障。Gate A 采用以下冻结策略：

- 每次迁移、配置/Secret 轮换、外部入口切换、体验版上传前，以及测试期内最长每
  24 小时生成一次一致备份；每个批准 Backup 必须完成隔离 Restore 和客户端加密副本。
- 来源主机和管理电脑至少保留最近 7 个成功 Backup，且任何体验版停用后至少保留
  30 日；脱敏审计 Record 至少保留到 Gate A 决策结束后 90 日。两者取较长者。
- 不自动删除。删除要求精确 Backup ID、存在更新且已恢复/异机验证的 Backup、项目
  负责人当次批准和删除后清单；当前工具故意不提供 delete 命令。
- Gate A 测试期 RPO 目标为 24 小时；计划变更的停写窗口 RPO 为 0；从已验证备份
  恢复到健康应用的 RTO 目标为 30 分钟。每个 RC 前及活跃测试期每月执行一次恢复。
- 恢复到来源卷、覆盖数据或删除 Schema 仍需单独破坏性操作授权；默认先恢复到隔离
  project 比较，再决定前滚或来源恢复。

客户端副本使用 AES-256-GCM，数据密钥使用 RSA-OAEP-SHA256 封装。管理电脑私钥位于
`$HOME/.config/pinkdoohub/gatea-backup/private.pem`（`0600`），公钥同目录 `0644`；
加密副本位于 `$HOME/Backups/pinkdoohub/gatea/`（目录 `0700`、copy `0400`、Record
`0600`），均在仓库外。私钥不上传服务器、不进入副本目录、仓库、日志或 Record；
年度轮换、疑似泄漏或管理电脑更换时生成新 key ID，旧私钥在其加密副本全部超过保留
期前不得删除。

2026-09-02 已对非空 Backup `20260902t014211z` 实际生成首个加密异机副本并立即完成
解密、AEAD、Tar 白名单、来源文件 checksum 和 Restore PASS 复核。副本为 `0400`、
Record 为 `0600`、私钥为 `0600`，密钥目录与副本目录分别为 `0700`；管理电脑
FileVault 已开启。脱敏 Record 只保存 key ID、算法、大小/checksum、来源文件摘要和
验证布尔值，不保存私钥、Secret 或 PII。详细证据见
[`reports/phase94_pre_icp_completion_2026-09-02.md`](reports/phase94_pre_icp_completion_2026-09-02.md)。

## 4. 微信网络与域名清单

Gate A 前由发布负责人 Yijie Shen 填写实际值并附微信后台截图/导出证据：

| 用途 | 计划域名 | 微信后台类型 | 当前状态 |
|------|----------|--------------|----------|
| JSON API | 待选 | request 合法域名 | `blocked` |
| 图片上传 | 待选；可与 API 同 Origin | uploadFile 合法域名 | `blocked` |
| 商品图片读取 | 待选 | downloadFile 合法域名；是否必需按实际 Image 行为复核 | `blocked` |
| WebSocket | 当前未使用 | socket 合法域名 | `N/A` |

域名验收：

- [ ] HTTPS 证书链和主机名在 iOS/Android 真机通过；
- [ ] 域名不是 IP、localhost 或内网临时地址；
- [ ] 域名满足微信当前备案与服务器域名规则；
- [ ] request/upload/download 分别按真实调用配置；
- [ ] 不把 `api.weixin.qq.com` 配成客户端服务器域名；
- [ ] 测试和正式 Origin 不混入同一个 RC；
- [ ] 证书到期负责人、提前告警和续期流程明确；
- [ ] 微信后台变更有操作者、时间和回滚记录。

## 5. 日志与敏感信息

Gate A 最低规则：

- 不记录密码、Token、JWT payload、AppSecret、session_key、支付密钥、完整 Redis URL 或数据库连接串；
- Inventory reason/idempotency key 沿用现有不输出规则；
- 登录、注册、上传、订单和管理员操作只记录定位所需的内部 ID/结果，不记录完整个人资料；
- 异常响应不回显原始敏感输入；
- 日志采集凭据不进入小程序；
- 保存期限、访问角色、删除方式和事故导出范围在 Gate A 前冻结。

当前 Gate A 使用 Docker `json-file`，每个长期容器固定 `max-size=10m`、`max-file=5`，
即单容器最多约 50 MiB 的本机轮转窗口；不把大小上限误报为固定天数。活跃测试会话
前后及事故时用精确 Compose project 查询 App/Nginx/MySQL/Redis 日志。成功的韧性演练
Record 只保留 24 小时总行数、Nginx 请求数、4xx/5xx、median/p95/max request time、
轮转配置和零敏感命中，不保存原始日志、IP、User-Agent、URI、身份或 Secret。

普通事故导出只允许上述聚合或人工脱敏片段；原始日志只由服务器 Root 在事件处理中
短期读取。测试负责人和事故联系人均为 Yijie Shen，具体响应、反馈、停用和数据清理
规则见 [`gatea_test_operations.md`](gatea_test_operations.md)。Gate B 再评估集中采集、
长期保留和主动告警，不把 Gate A 的单机观察描述为高可用监控。

2026-09-02 真实持久主机已验证四个长期容器的上述轮转契约，分别中断 MySQL/Redis
时 readiness 为 503、liveness 为 200，恢复后 readiness 为 200；App 重启后数据与
三图片保持。24 小时日志扫描验证四项真实 Secret 精确命中和高置信敏感模式命中均为
0，并可生成请求数、4xx/5xx 与 median/p95/max request time 聚合。原始日志未写入
Record；该证据只证明 Gate A 单机查询和响应办法，不替代 Gate B 集中监控与主动告警。

9.2.2 已将 `app/core/redis.py` 连接成功日志改为 `scheme/host/port/db` 安全目标摘要，不再输出 username、password 或 query，并有专门脱敏测试；干净 CI 与 2026-09-02 持久日志扫描均已通过，R-012 已关闭。

## 6. 配置冻结记录模板

```text
Release candidate:
Git SHA:
Environment:
API Origin:
Request domain configured:
Upload domain configured:
Download domain configured:
MySQL target ID (no credential):
Redis target ID (no credential):
Image namespace/base URL:
Secret versions (IDs only):
Certificate expiry:
Configured by: Yijie Shen（实际配置后填写时间）
Reviewed by: Yijie Shen（独立复核步骤完成后填写时间）
Timestamp:
Responsible owner: Yijie Shen
```
