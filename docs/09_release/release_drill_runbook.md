# 微信 Gate A 隔离发布演练 Runbook

> **Status:** Historical M2 drill passed — M2→M7 tooling ready；persistent execution/RC blocked
> **Last Updated:** 2026-09-07
> **Scope:** 微信小程序内部测试版（Gate A）

本文定义 Phase 9.3 的安全执行顺序、证据和失败处置。它不是生产操作授权，也不包含任何真实连接信息。首次实际演练必须在专用、可销毁、与共享环境隔离的 MySQL 8+、Redis 和图片存储中执行。

2026-08-31 的已执行报告只证明当时 M0–M2 候选。当前迁移链已经扩展到 M7，功能面
增加 M4 Wallet/Payment/Refund、M5 Reservation N1、M6 自选颜色 Kit 和 M7 可配置
固定店休。旧报告、旧工具输出和旧候选迁移 Record 不得重命名或复用为当前结果。
Gate A 在 2026-09-02 的最后记录是非空 M2；这不是当前数据库事实，任何写操作前仍须
以只读查询确认真实状态。

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
| DR-01 | 全新空库 0→当前 | 历史要求为 0→2；当前要求为精确 0→7，并核验 M3–M7 表/约束/索引/默认数据 | 历史 M2 PASS；本地 dirty-tree M7 PASS；远端/Gate A 待证据 |
| DR-02 | 迁移 0 代表性数据升级 | 用户、Product、Audit 等数据保持；当前必须继续到 M7 | 历史 M2 PASS；本地 dirty-tree M0→M7 PASS；Gate A 待证据 |
| DR-03 | 历史版本代表性数据升级 | 历史 M1 Order/库存样本；当前增加 1/2/3/4/5/6→7 与各领域不漂移 | 本地 dirty-tree M0–M6→M7 矩阵 PASS；远端/Gate A 待证据 |
| DR-04 | 备份并恢复到新实例 | Schema、关键行数、抽样聚合、登录和启动均通过 | 历史 M2 PASS（9.3 Report）；当前候选待重演 |
| DR-05 | 可控迁移失败 | 识别实际部分提交状态；按批准方案前滚或从已验证备份恢复 | 历史 M2 PASS（9.3 Report）；当前既有库路径待实现/重演 |
| DR-06 | 应用与依赖 | FastAPI/Uvicorn、MySQL、Redis、图片、liveness/readiness、优雅重启通过 | 历史 M2 PASS（9.3 Report）；当前镜像待重演 |
| DR-07 | 管理员初始化 | 一次性、幂等、可审计地建立首个 SUPER_ADMIN；重复执行无第二账号 | 历史 M2 PASS（9.3 Report）；当前环境待复核 |
| DR-08 | 微信真机网络 | request/upload/download、证书、Token、图片和错误信封通过 | BLOCKED：备案/Origin/RC |
| DR-09 | Gate A 纵向 Smoke | 旧最小链路加 Wallet、颜色 Kit、Reservation、M7 和最新界面 | 历史 M2 服务端 32 请求 PASS；当前候选待重演 |
| DR-10 | M4 钱包补齐与对账 | wallet/legacy preview 与冻结上界 apply、二次 preview、只读 reconcile 全零差异 | NOT RUN（Gate A） |
| DR-11 | M5 Reservation | 预约四状态、单日店休、隐私、并发/1205/1213/索引与历史数据 | 一次性 M5 MySQL 历史 PASS；Gate A NOT RUN |
| DR-12 | M6 颜色目录与库存 | M5 fixed 重放到 M6/M7；221 槽/列/FK/索引；持久图、商品启用色/库存与 HTTPS | 一次性 M6 snapshot PASS；SQLite 色板仅开发证据；Gate A NOT RUN |
| DR-13 | M7 固定店休 | 单例/默认周一/唯一约束，历史预约/单日店休不漂移，更换的事务/锁序/批量取消 | 本地 dirty-tree 一次性 MySQL/21 项联合门槛 PASS；远端/Gate A 待证据 |

对最后留证为非空 M2 的当前 Gate A，以及未来任何需要接管的既有数据库，都必须先执行
只读审计，确认 Schema、Aerich 版本、数据质量和备份；未审计的库不自动成为“受支持
升级起点”。

历史 M2 执行的 SHA、CI、结果、耗时、修复项和资源清理记录见
[Phase 9.3 隔离发布演练报告](reports/phase93_rehearsal_2026-08-31.md)。该报告不修改，
当前候选的每次新执行必须另建独立报告并列出 DR-01～DR-13 的适用/不适用项。

当前 M7 的本地可销毁迁移与联合门槛见
[M7 一次性 MySQL 报告](reports/m7_mysql_release_gate_2026-09-07.md)。该报告运行于提交前
dirty 工作树；同内容随后成为提交 `58d8435...`，并随 head `4d6430c...` 在
[Run 34129910349](https://github.com/EVEBios/pinkdooHub/actions/runs/34129910349) 取得远端
8/8。远端证据见 [M7 当前候选远端 CI 报告](reports/m7_remote_ci_2026-09-07.md)，但仍不包含
持久部署、备份恢复、应用/图片/Redis Smoke 或微信真机，因此不能把 DR-01～DR-13
整体标成当前候选 PASS。

### 3.1 当前 M4–M7 证据分层

| 版本 | 仓库/历史事实 | 当前候选一次性 MySQL | 持久 Gate A 必需动作 |
|------|---------------|----------------------|----------------------|
| M3 | 外部身份与认证安全仓库实现完成；旧一次性 0→3 通过 | 本地 M0–M6→M7 历史矩阵已纳入 M3；当前 workflow 远端 8/8 | 只读扫描后先应用 M3；Gate A 仍保持 password 模式 |
| M4 | 钱包/支付/退款代码完成；旧关键闭环 `2 passed` | 一次性 MySQL 8.0.46 已完成 Wallet `9 passed` 与三域联合 `30 passed`；head `62f807a...` 的 Run 34134341829 远端 8/8，三域联合/cleanup/artifact 步骤成功 | 应用 M4 后执行两个 backfill 与 reconcile，零差异前禁止启用资金入口 |
| M5 | 一次性 MySQL 0→5 与 Inventory + Reservation `16 passed` | 本地历史矩阵与远端 M5 fixed→M6→M7 workflow 均通过 | 核验两张预约表、外键/六个索引、既有数据和注销边界 |
| M6 | 本地 SQLite/221 色 manifest/确定性 PNG 已完成 | 本地 M6 snapshot/颜色锁等待及远端联合 21 项通过 | 使用专门的 MySQL/持久存储导入发布入口；本地 SQLite-only 工具不得复用 |
| M7 | 离线迁移与本地业务测试已完成 | 本地单例/默认/约束/历史不漂移/事务并发通过；远端 workflow 8/8 | 核验现有预约/单日店休不漂移并配置目标固定店休日 |

任何“一次性 MySQL PASS”只关闭候选迁移实现风险，不等于已应用 Gate A。任何本地
SQLite 数据也只属于开发环境，不是 Gate A 的数据或图片发布证据。

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

#### 4.0.1 当前工具适用边界与停止条件

历史演练入口仍不能直接承担最后留证 M2→M7 的持久升级，但专用入口已经实现：

- `scripts.release.phase93_operations` 的迁移版本、Schema 断言和 legacy 场景硬编码为
  M0–M2，只能复核历史 9.3 报告；在更新并重新测试前不得称为“0→当前”。
- `scripts.release.gatea_operations initial-migrate` 仍只接受 0 张表的首次数据库，不得
  对非空 Gate A 使用；`app-up` 现同时接受精确匹配的 initial migration Record 或
  `gatea_upgrade` 成功生成的 existing-database upgrade Record。
- `scripts.release.gatea_operations database-status` 已可对健康 MySQL 只读输出精确
  Aerich 链、Schema 数量/指纹和 M2 关键业务聚合，但不会迁移或批准未知起点。
- `scripts/local/import_mard_bead_colors.py` 仍只操作项目内 SQLite；Gate A 的
  `app.tasks.gatea_mard_publish` 已由专用升级入口在 M6 后编排，不能把本地开发图片
  复制为持久发布证据。

`scripts.release.gatea_upgrade` 已实现并在本地单测与一次性 MySQL 8.0.46 验证以下能力：

1. 先用 `database-status` 保存不含 Secret/PII 的只读起点证据；非空库升级入口再验证
   Root/Secret/镜像、停写状态、新 Backup/Restore Record、候选 SHA/Image ID 和该份
   Aerich/Schema 证据；受支持起点清单必须单独 Review，不能由
   一次性 MySQL 的 M0–M6 矩阵自动推导；
2. 入口按真实 Aerich 版本逐步升级，保存每步 Schema/数据摘要，失败时保留现场，并在
   全部核验通过后生成新的 candidate upgrade Record 供 `app-up` 使用；
3. 已实现的 Gate A 221 色发布原语须接入非空升级入口：默认 preview、显式 checksum
   apply、MySQL 事务、持久图片原子发布/补偿、幂等重放和 HTTPS URL 核验均由编排留证；
4. 失败保留脱敏 evidence 和停止状态，成功 Record 可重放；输出不含 Secret、PII 或
   幂等键，`app-up` 只在 Record 与当前 target SHA/Image ID 完全一致时放行。

默认 plan 只读；apply 必须同时确认 source SHA、target SHA、Backup ID 与 MARD manifest
SHA-256。当前实现只批准精确 M2 起点，不批准 M0/M1/M3–M6 持久升级。入口通过测试不等于
已取得持久写入授权；Gate A 当前真实版本、当次新 Backup/Restore 与执行仍须在恢复 SSH
公钥访问后重新取得证据。不得用临时 SQL、删除旧 Record、伪造 Record 或绕过保护逻辑。

候选镜像已提供 `app.tasks.gatea_migrate_step` 与 `app.tasks.gatea_wallet_prepare` 两个
内部执行原语：前者将 Aerich 限制为 M3–M7 单步前进，后者完成 M4 后双 preview、冻结
上界 apply、重放与 reconcile。它们不拥有主机/备份/停写/Record 验证，只能由
`gatea_upgrade` 调用，不得直接用于持久 Gate A。

M6 色卡原语 `app.tasks.gatea_mard_publish` 也已完成：它固定 production MySQL、
`/data/images`、HTTPS URL、manifest SHA-256 和 `0644` 图片，事务失败补偿本轮文件，
精确重放零写入。它同样不拥有停写/Backup/Restore 授权，必须由升级编排调用。

### 4.1 预检（只读）

1. 两名人员核对目标主机、端口、数据库名、环境标识和资源所有者。
2. 确认目标不是生产、共享 `3306`、开发 SQLite 或其他任务资源。
3. 记录 MySQL/Redis/Python/Node/Taro 版本、Git SHA、artifact checksum 和当前 Runtime
   image；对持久 Gate A 通过受控只读查询同时记录精确 Aerich 版本链、表/列/约束/索引
   摘要和关键领域行数。若与 2026-09-02 的 M2 记录不一致，停止并调查。
4. 确认应用写入尚未开启；已有数据场景进入明确停写窗口。
5. 检查磁盘/配额、备份目标、证书有效期、HTTPS Origin 和微信后台合法域名。
6. 检查 Secret 仅由受控环境注入，命令行历史、日志和 artifact 中无 Secret。
7. 确认当前版本已经通过 9.2 所有 CI 门槛；任何必需 Job 缺失即停止。
8. 验证 4.0.1 所述非空升级和颜色发布入口已经实现并通过当前 SHA 的自动化；缺失即停止。

### 4.2 备份与恢复预验证

1. 对有数据场景创建一致性备份或快照，记录不可变 ID、开始/结束时间、工具版本和校验和。
2. 在新的隔离实例恢复该备份。
3. 比较 Schema 摘要、关键表行数和预先冻结的业务抽样；启动只读应用 Smoke。
4. 记录恢复耗时和恢复点。恢复验证失败时不得继续迁移。

### 4.3 数据库迁移

本节由 `scripts.release.gatea_upgrade` 固化；只有该入口在当前干净 SHA 的 CI 通过、当前
Gate A 起点只读确认为 M2、新 Backup/Restore 通过并取得当次持久写入授权后才可执行。
不能把以下内部步骤拆成现场命令单独运行。

1. 再次核对连接身份、目标 Schema、当前版本和备份 ID。
2. 停止 App/Nginx 的业务写入并证明无活跃写请求；MySQL/Redis 保持受控可用。
3. 当前真实 Aerich 版本必须等于经 Review 的受支持起点；未知、缺口、重复、Schema 与
   版本不一致或尚未批准该起点时停止。最后历史记录为 M2，不能在未查询时假设；CI 的
   M0–M6→M7 矩阵也不构成持久起点批准。
4. 若只读结果仍为 M2 且 M2→M7 路径已经批准，先依次应用 M3、M4；其他起点严格使用
   对应批准路径。每一步记录开始/结束时间、退出码、真实 Aerich/Schema 状态和无敏感
   信息的摘要。不得 `--fake`、直接改 Aerich 表或把 downgrade 当回滚。
5. M4 后保持资金入口关闭，按预览输出冻结 `through_user_id`，执行：

   ```bash
   python -m app.tasks.wallet_account_backfill
   python -m app.tasks.wallet_account_backfill --through-user-id <preview-id> --apply
   python -m app.tasks.wallet_account_backfill --through-user-id <same-preview-id>
   ```

   二次 preview 必须 `would_create=0`。随后按同样原则冻结 `through_order_id`：

   ```bash
   python -m app.tasks.legacy_manual_settlement_backfill
   python -m app.tasks.legacy_manual_settlement_backfill --through-order-id <preview-id> --apply
   python -m app.tasks.legacy_manual_settlement_backfill --through-order-id <same-preview-id>
   python -m app.tasks.wallet_reconcile
   ```

   二次 preview 必须没有待补订单；任一 `blocked`、mismatch、violation 或非零退出都
   停止。任务不会自动修账。
6. 再按顺序应用 M5、M6、M7。M6 后先保持颜色商品不可销售，使用批准的 Gate A
   发布入口导入/核验 221 色与持久图片，再为测试商品配置启用色和库存。M7 后核验
   `reservation_settings` 只有一个 `singleton_key=1`，默认/当前 weekday 合法，
   `ck_reservation_settings_singleton` 与 `uidx_reservation_settings_singleton` 存在。
7. 核验最终 Aerich 精确为 M0–M7，并对 User、ExternalIdentity、Product、Order、
   Inventory、Wallet、Payment、Settlement、Refund、Reservation、StoreBusinessDay、
   ReservationSettings 和 Audit 做前后行数/业务聚合；已有预约、单日店休、历史取消、
   fixed Kit 库存和订单快照不得漂移。
8. 只在全部检查通过后写入绑定 candidate SHA、Image ID、迁移前/后版本、Backup ID、
   backfill/reconcile、颜色 manifest 和复核时间的新 upgrade Record；随后才允许启动候选。

迁移失败后立即停止应用写入和后续步骤。先记录真实 Schema/Aerich 状态，再由授权人选择前滚修复或从已验证备份恢复；不得盲目重跑、fake 版本或直接 downgrade。

### 4.4 应用部署与运行时验证

1. 注入已冻结的非 Secret 配置和受控 Secret；验证 `APP_ENV=production` 语义、`APP_DEBUG=false`、MySQL、Redis 和图片持久化。
2. 启动后端，先验证 liveness，再验证包含 MySQL/Redis 的 readiness。
3. 验证启动失败不会泄漏连接串或凭据；Redis 不可用时实例不接收业务流量。
4. 执行管理员幂等 bootstrap，保存审计证据并按流程处置初始凭据。
5. 执行 API Smoke、图片上传/读取、日志检索和优雅停止/再次启动。

#### 4.4.2 M7 综合代表性测试数据

M2 历史代表数据只证明 User/Product/Order/Inventory 的旧链路；M7 持久升级通过后，
仍需为 Wallet/Payment/Refund、自选颜色 Kit 和 Reservation 建立可供 Gate A 人工验收的
合成数据。先保持微信 Provider 与充值开关关闭；仅在 M4 backfill、legacy settlement
backfill、`wallet_reconcile`、扩展 MySQL 门槛和当前候选升级 Record 全部通过后，显式
开启以下内部 Gate A 能力并重建 App：

```dotenv
WALLET_ADMIN_WRITE_ENABLED=true
WALLET_ORDER_PAYMENT_ENABLED=true
WALLET_REFUND_ENABLED=true
WALLET_TOPUP_ENABLED=false
PAYMENT_PROVIDER=disabled
PASSWORD_REGISTRATION_ENABLED=true
```

开关切换必须先备份 `config.env`，重建后复核 production Settings、四项 Healthy、唯一
`127.0.0.1` publisher、liveness/readiness、六个开关的 PID 1 实际值，以及微信充值/支付
仍为 503。`PASSWORD_REGISTRATION_ENABLED` 只为创建合成账号临时开启；成功保存随机凭据
并确认所有合成会话撤销后必须恢复为 `false`、重建 App 并再次核验注册被拒绝，其他三个
内部钱包开关按 Gate A 人工验收计划保留。随后对当前 M7 候选创建新的 Backup 并完成独立
无端口 Restore；不得复用升级前 M2 Backup。把已经通过当前远端 CI 的 Operations commit
安装为单独版本化 Release 并保留 `.source-sha` 与 `.ci-run-id` sidecar，再从该目录执行：

```bash
sudo python3 -m scripts.release.gatea_m7_representative_data \
  --super-admin-username '<current-super-admin>' \
  --confirm-super-admin-username '<current-super-admin>' \
  --backup-id '<current-m7-backup-id>' \
  --confirm-backup-id '<current-m7-backup-id>' \
  --apply
```

当前 SUPER_ADMIN 密码只经 TTY 隐藏双输入，不放入参数、环境、文件或 Record。工具会创建
三个合成账号和覆盖 M3–M7 的聚合场景；其随机密码只保存在
`/srv/pinkdoohub/gatea/records/representative-data/gatea-m7-synthetic-credentials.json`
（`root:root 0600`）。成功后必须再次执行 `wallet_reconcile`、新 Backup/独立 Restore、
数据库/图片摘要和日志 Secret 扫描。工具由多次正式 API 请求组成，不是跨请求单事务：
任何中断或失败都保留 `.pending` 凭据与现场，立即停止后续写入并从该次已验证 Backup
恢复；禁止删除失败现场、手工补行或直接重跑。

历史 M2 环境已验证 dependency-free liveness、DB/Redis dependency-aware readiness、
故障摘流量/恢复、Bootstrap 和凭据处置。当前 M7 镜像必须在升级后的持久环境重新验证；
旧结果只用于说明流程，不允许直接关闭当前候选项目。

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
- 普通用户：登录、Cart、创建 Experience/fixed/color/mixed Order、订单详情、Pending
  取消、会员余额/流水、合成余额支付、预约创建/列表/详情/取消；
- ADMIN：订单 Paid/Completed、Product/221 色/图片、fixed/颜色 Inventory、Wallet 客户
  查询/调账/多颜色代客订单/退款、预约确认/拒绝、单日与固定店休、Audit、用户列表；
- SUPER_ADMIN：初始化后登录、角色边界、用户禁用；
- 安全边界：普通用户调用管理 API 为 403，被禁用用户旧 Token 失效；
- 运行边界：Token 刷新、弱网、断网、请求结果未知、重复点击、图片上传中断；
- 数据断言：订单金额/颜色/重量快照，fixed/颜色库存扣减/取消/PAID 退款恢复，钱包
  余额链与 Payment/Settlement/Refund，预约状态/店休历史，幂等重放和审计顺序一致；
- 诚实能力边界：真实微信充值/支付/退款仍返回 503 零写入，Reservation N1 不显示
  主动通知或自动容量已实现；
- 视觉回归：会员缺省头像小屏/大字体居中，代客多颜色手机六列/宽屏十列可操作。

完整场景及证据等级以 [wechat_acceptance_matrix.md](wechat_acceptance_matrix.md) 为准。

## 6. 前滚、恢复与停止条件

优先停止并进入 No-Go 的条件包括：

- 目标身份不清、疑似连接共享/生产资源或备份未验证；
- 迁移、Schema、库存、订单或审计发生无法解释的漂移；
- readiness、Redis、图片持久化或管理员初始化失败；
- 越权、凭据泄漏、数据破坏、重复订单/扣库存或无法恢复；
- artifact 与已测试 SHA 不一致；
- 当前远端 CI 未达 8/8，或 MySQL snapshot 未精确覆盖 M0–M7（当前 Run 34129910349 已满足，后续 SHA 必须重验）；
- 非空升级入口尚未通过当前 SHA 的 CI、候选 upgrade Record 缺失，或试图对 Gate A
  使用空库 `initial-migrate`；
- wallet backfill/reconcile 非零差异，或 Gate A 221 色/图片/商品库存未完成；
- 微信真机无法通过 HTTPS 或合法域名访问。

Inventory downgrade 会删除流水结构并可能丢失新版本运行后的历史，不是常规无损回滚。一旦新版本开始写数据，首选停写、保全证据和前滚修复；从备份恢复只由授权人决定，并明确恢复点之后数据的处置。

## 7. 演练记录模板

```text
演练 ID：
日期/窗口：
Git SHA / artifact checksum：
环境与资源所有者：
执行人 / 复核人 / 决策人：Yijie Shen（实际执行时分别确认时间）
场景：DR-01 ... DR-13
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
