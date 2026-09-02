# 微信 Gate A 隔离发布演练 Runbook

> **Status:** Phase 9.3 Executed — DR-01～DR-07、DR-09 服务端部分通过
> **Last Updated:** 2026-08-31
> **Scope:** 微信小程序内部测试版（Gate A）

本文定义 Phase 9.3 的安全执行顺序、证据和失败处置。它不是生产操作授权，也不包含任何真实连接信息。首次实际演练必须在专用、可销毁、与共享环境隔离的 MySQL 8+、Redis 和图片存储中执行。

## 1. 安全边界

- 演练不得连接默认 `3306` 共享实例、生产资源、开发 SQLite 或来源不明的数据库；fixture 和人工预检都必须拒绝这些目标。
- 不使用 Aerich `--fake`，不依赖应用启动自动建表，不用手工 SQL 补版本或业务状态。
- 数据只使用合成数据；日志、截图和报告不得包含密码、Token、JWT、Redis URL、AppSecret 或连接串。
- 迁移前必须生成备份并在独立实例验证可恢复。仅“命令返回 0”不算备份验证。
- 每个进程、容器、端口、临时目录、快照和 artifact 都记录所有者及用途，成功、失败或放弃时走同一清理路径。
- MySQL DDL 可能隐式提交。不得假设迁移失败会整体事务回滚；发生部分失败时先停写并调查真实 Schema 状态。
- downgrade、恢复、覆盖数据、删除 Schema、切换 DNS、上传体验版等外部或破坏性操作均需当次明确授权。

## 2. 演练角色与输入

| 角色 | 责任人 | 责任 |
|------|--------|------|
| 演练负责人 | Yijie Shen | 冻结范围、窗口、目标、停止条件和最终结论 |
| 数据库执行人 | Yijie Shen | 预检、备份、迁移、Schema/数据核验和恢复 |
| 应用执行人 | Yijie Shen | 后端、Redis、图片、管理员初始化和 API Smoke |
| 微信验证人 | Yijie Shen | 构建来源、体验版、合法域名和真机 Smoke |
| 观察/复核人 | Yijie Shen | 分步骤复核目标、证据、失败决策和资源清理 |

当前项目由同一人承担所有角色，因此演练记录必须把“执行”和“复核”写成两个独立步骤，分别保存时间和检查结果；不得用一次笼统签字代替复核。

演练开始前必须冻结：

- Git SHA、后端版本、前端版本、OpenAPI 摘要和 CI run；
- 与该 SHA 绑定的后端/微信构建 artifact 及校验和；
- 专用 MySQL、Redis、HTTPS Origin、图片存储和合成账号清单；
- MySQL 当前版本、目标 Aerich 版本、备份目标和预计恢复时间；
- 演练负责人、执行人、Go/No-Go 决策人、回滚/恢复授权人；
- 维护或停写窗口、最长允许中断、终止阈值和沟通渠道。

缺少任一项时不得进入写操作。

## 3. 演练场景

| ID | 场景 | 核心断言 | 状态 |
|----|------|----------|------|
| DR-01 | 全新空库 0→当前 | 迁移 0→1→2 完成；表、约束、索引、Aerich 版本正确 | PASS（9.3 Report） |
| DR-02 | 迁移 0 代表性数据升级 | 用户、Product、Audit 等数据保持；新增结构正确 | PASS（9.3 Report） |
| DR-03 | 迁移 1 代表性数据升级 | Order、库存余额、opening balance 和历史快照不漂移 | PASS（9.3 Report） |
| DR-04 | 备份并恢复到新实例 | Schema、关键行数、抽样聚合、登录和启动均通过 | PASS（9.3 Report） |
| DR-05 | 可控迁移失败 | 识别实际部分提交状态；按批准方案前滚或从已验证备份恢复 | PASS（9.3 Report） |
| DR-06 | 应用与依赖 | FastAPI/Uvicorn、MySQL、Redis、图片、liveness/readiness、优雅重启通过 | PASS（9.3 Report） |
| DR-07 | 管理员初始化 | 一次性、幂等、可审计地建立首个 SUPER_ADMIN；重复执行无第二账号 | PASS（9.3 Report） |
| DR-08 | 微信真机网络 | request/upload/download、证书、Token、图片和错误信封通过 | 待 9.4 |
| DR-09 | Gate A 纵向 Smoke | Guest、用户、ADMIN、SUPER_ADMIN、禁用用户最小链路通过 | 服务端 HTTPS 32 请求 PASS；真机扩展待 9.4 |

如果未来出现需要接管的既有数据库，必须先新增只读审计场景，确认 Schema、Aerich 版本、数据质量和备份；未审计的库不自动成为“受支持升级起点”。

本次执行的 SHA、CI、结果、耗时、修复项和资源清理记录见 [Phase 9.3 隔离发布演练报告](reports/phase93_rehearsal_2026-08-31.md)。

## 4. 执行顺序

### 4.0 本仓库自动化入口

9.3.3–9.3.4 已把本 Runbook 固化为以下入口。`<run-id>` 必须使用 `YYYYMMDDtHHMMSS`；准备命令会先要求工作树 clean、记录 HEAD/Compose digest、确认四个回环端口空闲且同名 project 不存在，未通过时不会创建 Secret、证书或 Docker 资源。以下命令不包含 Secret 值，所有原始证据只写入 `/tmp/pinkdoohub-phase93/<run-id>/evidence`：

```bash
python -m scripts.release.phase93_rehearsal prepare --run-id <run-id>

python -m scripts.release.phase93_operations pull-images --run-id <run-id>
python -m scripts.release.phase93_operations build-app --run-id <run-id>
python -m scripts.release.phase93_operations start-data --run-id <run-id>

python -m scripts.release.phase93_operations migrate --run-id <run-id>
python -m scripts.release.phase93_operations verify-current --run-id <run-id>
python -m scripts.release.phase93_operations legacy-m0 --run-id <run-id>
python -m scripts.release.phase93_operations legacy-m1 --run-id <run-id>

python -m scripts.release.phase93_operations bootstrap --run-id <run-id>
python -m scripts.release.phase93_operations bootstrap-replay --run-id <run-id>
python -m scripts.release.phase93_operations verify-bootstrap --run-id <run-id>
python -m scripts.release.phase93_operations runtime-seed --run-id <run-id>
python -m scripts.release.phase93_operations start-app --run-id <run-id>
python -m scripts.release.phase93_operations live-smoke --run-id <run-id>

python -m scripts.release.phase93_operations backup-db --run-id <run-id>
python -m scripts.release.phase93_operations backup-images --run-id <run-id>
```

以下步骤会执行恢复、依赖停止、受控失败或资源删除，必须在执行时把 `<project>` 替换为 manifest 中的精确 project，并取得当次授权：

```bash
python -m scripts.release.phase93_operations restore-db \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-database pinkdoohub_phase93_restore
python -m scripts.release.phase93_operations restore-images \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations verify-restore \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-database pinkdoohub_phase93_restore
python -m scripts.release.phase93_operations dependency-drill \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations restart-app \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations failure-drill \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-database pinkdoohub_phase93_failure

python -m scripts.release.phase93_report --run-id <run-id>
python -m scripts.release.phase93_operations stop \
  --run-id <run-id> \
  --confirm-project <project>
python -m scripts.release.phase93_operations cleanup \
  --run-id <run-id> \
  --confirm-project <project> \
  --confirm-workspace /tmp/pinkdoohub-phase93/<run-id>
```

`phase93_report` 只有在 DR-01～DR-07 与 DR-09 服务端必需报告全部 `passed=true` 时才生成仓库外脱敏摘要；DR-08 明确写为 9.4 deferred。清理前先保存该摘要，清理后再把端口释放、project label 归零和临时目录删除结果人工回写最终报告。工具不会自动 commit、push、连接微信后台或执行任何持久/生产资源操作。

### 4.1 预检（只读）

1. 两名人员核对目标主机、端口、数据库名、环境标识和资源所有者。
2. 确认目标不是生产、共享 `3306`、开发 SQLite 或其他任务资源。
3. 记录 MySQL/Redis/Python/Node/Taro 版本、Git SHA、artifact checksum 和当前 Aerich 状态。
4. 确认应用写入尚未开启；已有数据场景进入明确停写窗口。
5. 检查磁盘/配额、备份目标、证书有效期、HTTPS Origin 和微信后台合法域名。
6. 检查 Secret 仅由受控环境注入，命令行历史、日志和 artifact 中无 Secret。
7. 确认当前版本已经通过 9.2 所有 CI 门槛；任何必需 Job 缺失即停止。

### 4.2 备份与恢复预验证

1. 对有数据场景创建一致性备份或快照，记录不可变 ID、开始/结束时间、工具版本和校验和。
2. 在新的隔离实例恢复该备份。
3. 比较 Schema 摘要、关键表行数和预先冻结的业务抽样；启动只读应用 Smoke。
4. 记录恢复耗时和恢复点。恢复验证失败时不得继续迁移。

### 4.3 数据库迁移

1. 再次核对连接身份、目标 Schema、当前版本和备份 ID。
2. 按项目数据库迁移流程执行 Aerich 0→1→2 或已冻结的受支持升级路径。
3. 每一步记录开始/结束时间、退出码和无敏感信息的日志摘要。
4. 核验 Aerich 版本、表、外键、唯一约束、索引、库存余额和期初流水。
5. 对 Product、Order、Inventory、Audit 和 User 做关键行数与抽样聚合对比。

迁移失败后立即停止应用写入和后续步骤。先记录真实 Schema/Aerich 状态，再由授权人选择前滚修复或从已验证备份恢复；不得盲目重跑、fake 版本或直接 downgrade。

### 4.4 应用部署与运行时验证

1. 注入已冻结的非 Secret 配置和受控 Secret；验证 `APP_ENV=production` 语义、`APP_DEBUG=false`、MySQL、Redis 和图片持久化。
2. 启动后端，先验证 liveness，再验证包含 MySQL/Redis 的 readiness。
3. 验证启动失败不会泄漏连接串或凭据；Redis 不可用时实例不接收业务流量。
4. 执行管理员幂等 bootstrap，保存审计证据并按流程处置初始凭据。
5. 执行 API Smoke、图片上传/读取、日志检索和优雅停止/再次启动。

当前仓库已实现 dependency-free liveness 与 DB/Redis dependency-aware readiness，并有本地 SQLite/fakeredis、失败、超时和脱敏契约；它仍需在本场景使用隔离 MySQL/Redis 验证故障摘流量与恢复。受控 SUPER_ADMIN bootstrap 也已实现本地事务、并发、重放、回滚与 Secret 契约；仍需在本场景使用隔离 MySQL 执行首次创建、重复运行、登录、Audit 与初始凭据处置，才能关闭对应风险。

#### 4.4.1 SUPER_ADMIN Bootstrap 安全执行

人工执行时优先使用 TTY 隐藏双输入，命令行不出现密码：

```bash
python -m app.tasks.super_admin_bootstrap \
  --username <synthetic-username> \
  --nickname <synthetic-nickname> \
  --phone <synthetic-phone> \
  --apply
```

非交互部署只允许 Secret 系统短期注入 `PINKDOOHUB_BOOTSTRAP_PASSWORD`；不得在 shell 命令、`.env`、日志、截图、报告或 CI artifact 中填写真实值。命令必须在已迁移数据库上运行，不会自动建表。演练依次验证：首次结果 `created=true`；数据库只有一个正常 SUPER_ADMIN 和一条自指向 `BOOTSTRAP_SUPER_ADMIN` Audit；相同四项身份/密码重放为 `created=false/replay=true` 且 `updated_at`、密码哈希和 Audit 数量不变；不同输入、普通用户占用、禁用状态和审计矛盾均拒绝。最后完成真实登录、初始凭据轮换/撤销记录，再移除命令进程 Secret。

### 4.5 微信体验版与真机验证

1. 仅取同一 CI run、同一 Git SHA 的 `weapp` artifact；不得在开发者电脑二次修改。
2. 核对 API Origin、AppID、主包/分包大小、source map 策略和产物 Secret 扫描。
3. 取得外部上传授权后才上传体验版，并记录微信版本号、备注、上传人和时间。
4. 在 iOS/Android 真机验证 request/upload/download、登录、图片、弱网、断网和 unknown 结果。
5. 按验收矩阵执行最小纵向链路，记录设备、基础库、网络、环境和结果。

## 5. Smoke 最小集合

- Guest：冷启动、Product 列表/详情、登录入口；
- 普通用户：登录、Cart、创建 Experience/Kit/混合订单、订单详情、Pending 取消；
- ADMIN：订单 Paid/Completed、Product 管理、图片、Inventory 调整/流水、Audit、用户列表；
- SUPER_ADMIN：初始化后登录、角色边界、用户禁用；
- 安全边界：普通用户调用管理 API 为 403，被禁用用户旧 Token 失效；
- 运行边界：Token 刷新、弱网、断网、请求结果未知、重复点击、图片上传中断；
- 数据断言：订单快照、库存扣减/恢复、幂等重放和审计顺序一致。

完整场景及证据等级以 [wechat_acceptance_matrix.md](wechat_acceptance_matrix.md) 为准。

## 6. 前滚、恢复与停止条件

优先停止并进入 No-Go 的条件包括：

- 目标身份不清、疑似连接共享/生产资源或备份未验证；
- 迁移、Schema、库存、订单或审计发生无法解释的漂移；
- readiness、Redis、图片持久化或管理员初始化失败；
- 越权、凭据泄漏、数据破坏、重复订单/扣库存或无法恢复；
- artifact 与已测试 SHA 不一致；
- 微信真机无法通过 HTTPS 或合法域名访问。

Inventory downgrade 会删除流水结构并可能丢失新版本运行后的历史，不是常规无损回滚。一旦新版本开始写数据，首选停写、保全证据和前滚修复；从备份恢复只由授权人决定，并明确恢复点之后数据的处置。

## 7. 演练记录模板

```text
演练 ID：
日期/窗口：
Git SHA / artifact checksum：
环境与资源所有者：
执行人 / 复核人 / 决策人：Yijie Shen（实际执行时分别确认时间）
场景：DR-01 ... DR-09
迁移前/后 Aerich 版本：
备份/快照 ID 与恢复验证：
步骤、开始/结束、退出码、证据链接：
Smoke 结果：
发现的问题与风险 ID：
决策：Go / No-Go / 前滚修复 / 批准恢复
清理与复核：
```

证据只引用受控日志、报告、截图、checksum 和 CI run，不粘贴 Secret 或个人信息。

## 8. 资源回收清单

无论成功、失败、取消或超时，执行人都必须：

- 优雅停止本次启动的 Uvicorn、测试进程、代理、隧道和 watcher，并按 PID/进程树复核；
- 停止本次专用容器/数据库/Redis，检查端口已释放；
- 删除仅属于本次演练且已批准删除的临时目录、合成数据和短期 artifact；
- 保留受控证据和已批准快照，不删除共享缓存、用户文件或来源不明资源；
- 对故意保留的环境记录资源 ID、用途、所有者、到期时间和停止方法；
- 把不能安全清理的残留、原因、风险和精确处置方式写入演练报告。
