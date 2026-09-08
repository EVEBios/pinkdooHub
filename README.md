# pinkdooHub

pinkdooHub 是一个面向拼豆门店的后端管理系统，基于 FastAPI、Tortoise ORM、Pydantic 和 Redis 构建。开发环境使用 SQLite，生产数据库设计面向 MySQL 8+。

当前代码版本候选为 **v0.6.0（尚未发布）**。Phase 4.1 Product、Phase 4.2 Order、Phase 4.3 Inventory、Wallet/Payment/Refund v1、Reservation N1、M6 自选颜色 Kit、M7 可配置每周固定店休与 M8 数字色块 HEX 均已完成仓库实现。持久 Gate A 已受控应用 M3–M7、Wallet 历史准备和 MARD 221 色/兼容 PNG，当前权威检查点为 M7；M8 尚未应用 Gate A，生产资金能力仍关闭。开发 SQLite 可能由 `generate_schemas` 自动补建缺失表；这种状态不会产生 Aerich 版本记录，不能作为发布迁移证据。

## 当前能力

- 用户注册、登录、Token 刷新与登出，以及个人资料和密码修改。
- 微信小程序 `code2Session` 登录、显式绑定/安全解绑、外部身份 HMAC 最小化、refresh family 轮换/重放撤销、Redis 认证限流和账号匿名化注销；正式微信与 Gate B 外部资源尚未启用。
- RBAC 权限链、管理员用户列表和禁用操作。
- 敏感操作顺序审计，以及 Product 操作历史分页查询。
- Product、ExperienceOption、ProductKit、ProductImage，以及 M6 全局 221 槽 BeadColor/商品级 ProductKitColor 的完整业务、持久化与 API 链路。
- Product API 包括公开查询、ADMIN+ 管理、图片上传、审计历史、全局颜色目录与商品颜色启停；库存写入仍由 Inventory API 独立承担。
- M8 将 MARD 221 标准色卡的规范大写 `swatch_hex` 纳入数据库、管理/公开 API 与销售就绪校验；小程序优先用 `backgroundColor` 直绘，只有 HEX 缺失时才回退可选 `swatch_image_url`。
- 来源页本身使用 CSS 色块而非独立图片；已存在的 221 张确定性 256×256 sRGB PNG 只在迁移期兼容，不转 WebP、不删除。商品照片和未来实拍校色色样使用 WebP，生产对象存储发布仍待 Gate B。
- Product 图片大小、格式、MIME 和安全路径校验，以及上传失败补偿和延迟物理清理。
- Order 的 Experience、固定 Kit、自选颜色 Kit 与混合下单、不可变 Product/Option/颜色/10g 单位/价格快照、用户/管理查询、取消、人工确认支付、完成和审计历史。
- Pending 创建时的稳定多 Kit 行锁、库存扣减、不可变 Order 来源流水和全写集原子回滚。
- Order 状态与审计原子事务、订单号冲突重试、分页组合筛选、用户资源隐藏和完整 HTTP 错误/边界矩阵。
- 独立于订单和支付的体验预约：顾客使用当前手机号选择服务端生成的上海营业日/半小时时段，预约先进入待确认；顾客可查询历史并在开始前至少三小时取消。
- ADMIN+ 可查看预约与当前联系电话、确认或以唯一原因 `no_capacity` 拒绝；可配置单日店休，并在同一事务内将当天尚未开始的 Pending/Confirmed 预约批量取消为独立原因 `store_closed`，恢复营业不会复活历史预约。
- 预约营业时间为上海时间 11:00–20:00，每周固定店休默认周一并可由 ADMIN+ 更换；最早提前三小时，最远当地今日起第 30 天（含）。首版由店员人工判断容量，不自动防超额。
- 普通会员的钱包摘要与不可变流水、ADMIN+ 调账和代客钱包订单、订单余额支付与资金事实查询，以及 PAID/COMPLETED 一次全额退款；PAID Kit 退款恢复库存，COMPLETED 不恢复。
- 钱包余额和单笔充值上限均为 `1000.00`（充值下限 `1.00`）；真实微信充值、支付和退款 Provider 当前关闭并返回 503 零写入。
- 微信小程序客户与 ADMIN+ 共 31 个已注册页面已完成 “Ribbon Ledger” 视觉统一：保留全部既有功能，以紧凑排版、邻近莓色渐变、受控透明层和 44 px H5 触控基线覆盖认证、Product、Cart、Order、Inventory、Wallet/Payment、Reservation/店休与 User 管理流程。
- 统一成功/错误响应、全局异常处理和精确 OpenAPI 响应契约；直连 App 与 Gate A/Rehearsal Nginx 对客户端协商的 ≥1 KiB 文本响应启用 gzip level 6，图片路径/MIME 不重复压缩。

M8 基线的完整本地回归为后端 **2069 passed、31 skipped**（122.64s），skip 为显式隔离的 MySQL-only 门槛；一次性 MySQL 8.0.46 已真实完成 Aerich 0→8、M8 精确 HEX 与 Gate A publish/replay **2 passed**。前端为 **84 套件、573 项 Jest**，TypeScript、ESLint、Stylelint 全绿。M8 基线 head `4e745848...` 的 Run 34242753255 已在干净 checkout 完成 8/8；其后 head `fa6fce05...` / [Run 34281512196](https://github.com/EVEBios/pinkdooHub/actions/runs/34281512196) 又以 8/8 关闭 M7→M8 入口、21 表内容摘要、Online no-op 与性能工具的历史加固门槛。完整 updater 的受测实现 head `62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、真实 CI checkout/merge-ref `a9ff3d246c61a4aeede062596c32817a69834d7a` 已由 GitHub Actions [Run 34288613644](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) 最终 attempt 2 完成现行 **9/9 required Job**。新增第九个 `gatea-m7-m8-updater` 在一次性 Ubuntu/Linux root 环境真实完成完整 M7→M8 updater 的 14/14 阶段、两侧 Backup/Restore、221 HEX、gzip/PNG Runtime、artifact 安全扫描和零残留清理；它没有读取生产 Secret，也未获得或使用任何持久环境授权。首 attempt 的 OpenAPI Job 仅在安装阶段遇到 pip truststore 瞬态异常，相同提交重跑通过，非 Schema 漂移。持久 Gate A M8、candidate-pre 三轮、正式 RC 和真机仍未完成。此前 8/8 的不可变记录见 [M8 发布加固远端 CI 报告](docs/09_release/reports/m8_hardening_remote_ci_2026-09-09.md)，当前状态见 [Development Changelog](docs/05_development/changelog.md)。

2026-09-09 的新版本地容量工具在 MySQL 8/M8、共享 2 CPU、五容器 4096MiB 上限和唯一
5Mbps TBF 出口下完整采集 A/B/C/D、5/10 VU 共 12 个 Profile：gzip 色板、认证浏览、221
PNG 冷/热页与 150 个订单/库存/钱包写旅程均通过；10 VU 持续拉取未压缩 51,063-byte
色板出现 428 个 qdisc drops、P95 1.51s，故整轮严格为 **FAIL**。gzip 后线传 10,023 bytes、
减少 80.371%，同一 10 VU P95 271ms 且零 drops；这说明正常 5–10 人路径有余量，但 5Mbps
不适合未压缩大 JSON 的连续突发。该单轮 ARM64 Docker 服务包络不是独立 2C/4GiB 主机或
发布证据，详见 [M8 本地容量报告](docs/09_release/reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md)。

Phase 4.3.1–4.3.12 已完成 Inventory 契约、领域/Schema、Model/数据库设计、MySQL 8+ 增量迁移、Repository、管理员库存调整、Kit/混合订单创建扣减、Pending 取消幂等恢复、查询 Service/Mapper、三个 ADMIN+ Inventory API、真实 MySQL/完整 HTTP 发布门槛和最终 Review。最后一件库存、反向多 Kit、同单取消、同/异 key 调整、管理员调整与下单阻塞、真实 1205 全事务重试和 EXPLAIN 均已在隔离 MySQL 8.0.46 通过；三端点完整权限/错误/边界矩阵与真实 MySQL HTTP 并发重放也已通过。最终 Review 进一步统一了 Product Kit 详情的库存上限响应校验，并清理了数据库文档中的旧 Kit 规划描述。该轮隔离门槛的临时实例验证后已销毁；Inventory M2 后续已存在于当前 Gate A 的 M0–M7 链中，其他持久环境不因该结果自动迁移。

## 技术栈

| 领域 | 组件 |
|---|---|
| Web | FastAPI 0.139.2、Uvicorn 0.51.0 |
| ORM / Migration | Tortoise ORM 1.1.7、Aerich 0.9.3 |
| Database | SQLite（开发/测试）、MySQL 8+（生产设计） |
| Schema / Config | Pydantic 2.13.4、pydantic-settings 2.14.2 |
| Cache / Token State | Redis 8.0.1 |
| Testing | pytest 9.1.1、pytest-asyncio、HTTPX、fakeredis |
| Build Toolchain | Python 3.10.9、Node 24.13.0、npm 11.6.2 |

精确依赖版本以 [requirements.txt](requirements.txt) 为准，测试配置以 [pyproject.toml](pyproject.toml) 为准。
运行时版本分别由 [`.python-version`](.python-version)、
[`miniapp/.node-version`](miniapp/.node-version) 和 `miniapp/package.json#packageManager`
冻结，干净构建不得使用未经验证的其他版本。

## 快速开始

### 1. 创建虚拟环境并安装依赖

Windows PowerShell：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

项目当前将 Python 3.10.9 冻结为干净构建基线。创建环境后应先执行
`python --version` 确认精确版本；不要提交 `.venv`、缓存目录或本地运行文件。

### 2. 创建本地配置

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

开发环境默认使用 SQLite。启动前至少检查：

- `APP_ENV=development`
- `DB_ENGINE=sqlite`
- `REDIS_URL` 指向可用 Redis
- `JWT_SECRET_KEY` 仅可在本地开发使用示例值；生产必须设置安全随机密钥
- `PRODUCT_IMAGE_UPLOAD_DIR` 和 `PRODUCT_IMAGE_BASE_URL` 符合本地存储规划

`.env` 已被 Git 忽略，不得将密码、Token、私钥或真实连接串提交到仓库。

### 3. 启动基础设施和应用

先确保 Redis 可访问，再启动开发服务：

```bash
uvicorn app.main:app --reload
```

默认入口：

- API 根地址：`http://127.0.0.1:8000/`
- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

所有业务 API 使用 `/api/v1` 前缀。`v1` 只属于 HTTP 传输层版本，不需要复制到 Schema、Service、Repository 或 Model 目录。

### 4. 本地 MARD 221 色板导入

仓库冻结来源清单 `app/tasks/manifests/mard_221.json`，并提供默认只读的本地工具。来源抓取只接受 `https://peiseka.com/pindouseka.html`；MARD 导入只接受当前项目内已完成 M8 的 SQLite、清单、图片和备份路径：

```bash
# 抓取/校验来源页；默认不覆盖清单
python scripts/local/fetch_mard_bead_colors.py

# 预览 M8 swatch_hex 列与 221 项回填；不会写数据库或创建备份
python scripts/local/upgrade_sqlite_m8_swatch_hex.py

# 停止本地写入并复核 preview 后才显式升级；写前自动创建 0600 备份
python scripts/local/upgrade_sqlite_m8_swatch_hex.py --apply

# 预览数据库和 221 张确定性 PNG 的变化
python scripts/local/import_mard_bead_colors.py

# 复核预览后显式应用本地开发数据；写库前自动备份
python scripts/local/import_mard_bead_colors.py --apply --confirm-local-only
```

SQLite M8 工具不会写 Aerich，也不能应用到 MySQL。当前持久 `db.sqlite3` 已于 2026-09-08 在停止本地写入后执行 M8；写前 `0600` 备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-m8-swatch-hex-20260908-130013-906106.bak`。升级后 221 槽均有唯一、规范且与冻结清单逐项相等的 HEX，完整性/外键核验与幂等 preview 均通过。该结果只代表当前本地 SQLite；其他旧库在使用包含 M8 Model 的后端前仍必须先完成 preview/apply，且不能把本地脚本结果当作 Aerich 或 MySQL 发布证据。MARD 导入不会创建商品、启用商品颜色或写入库存；已有 PNG 只作迁移回退，不转换或删除。生产环境必须按 M3→M4→Wallet 准备→M5→M6→M7→M8→MARD 的受控顺序，并在 Gate B 接入对象存储/CDN。

### 5. 本地综合演示数据

当前 M7 开发库可通过一个显式、可重放的命令准备跨模块演示数据。执行前应停止其他
本地业务写入，并使用现有 ADMIN 或 SUPER_ADMIN 用户作为审计操作者：

```bash
# 仅接受 development + 仓库内 SQLite/图片目录；写入前自动建立并校验备份
python -m app.tasks.local_demo_seed \
  --apply \
  --confirm-local-only \
  --operator-username local_admin

# 后续只读核验数据库、钱包对账、图片文件和跨域场景
python -m app.tasks.local_demo_seed --verify
```

命令使用 `localdemo_v1_*` 保留用户名以及稳定的 remark / idempotency key，覆盖正常和
禁用会员、Product 全生命周期、Experience/fixed Kit/自选颜色 Kit、订单四种状态、
库存扣减与两种恢复、钱包调账/支付、人工结算、代客扣款、退款、预约四种状态、单日
店休/恢复和 M7 固定店休更换。真实微信充值/支付/退款仍按生产边界保持 503 零写入，
不会伪造成功数据。

每次 apply 都先在 `backups/local-demo-data/` 创建权限为 `0600` 的 SQLite Backup API
快照；新合成账号的随机密码只写入同目录下权限为 `0600` 的
`synthetic-credentials.json`，两者均被 Git 忽略，日志不会输出密码。命令不会覆盖已有
非 seed 固定店休：只接受从未调整过的默认周一，或已经由同一 seed 完整收敛出的周三；
任何冲突都会停止并保留精确备份路径。该流程是可恢复、可重放的本地开发工具，不是
Gate A/MySQL 迁移、发布数据或正式验收证据。

2026-09-07 已实际应用本地综合演示数据：写前备份为
`backups/local-demo-data/db.sqlite3.pre-local-demo-20260907-105320-455438.bak`，合成账号凭据仅保存于被 Git 忽略的
`backups/local-demo-data/synthetic-credentials.json`，两者权限均为 `0600`，文档与日志不记录凭据值。专用 verifier 已通过，
`wallet_reconcile` 输出 `scanned=11 mismatches=0 violations=0`。本地新增 9 个合成用户；Product 表共 19 条（非删除口径为
online 14 / offline 1 / draft 3，活跃类型为 Experience 8 / Kit 10，另 1 条逻辑删除）；8 笔 Order 覆盖
pending 1 / cancelled 1 / paid 4 / completed 2；6 笔 Payment 为 wallet 4 / manual 2，对应 6 条 Settlement 和 2 条 Refund。
6 条 seed Reservation 覆盖 pending 1 / confirmed 1 / rejected 1 / cancelled 3（`customer_request` 1 / `store_closed` 2），加旧数据实际表共 7 条；
Inventory seed 包含 `order_deduction` 8、`order_cancellation_restore` 2 和 `order_refund_restore` 2，自选颜色 Kit 启用三色，当前每周固定店休为周三。

## 测试与检查

运行完整测试：

```bash
python -m pytest tests/ -q
```

提交前至少执行：

```bash
python -m pytest tests/ -q
python -m compileall -q app tests
python -m pip check
git diff --check
```

Product、Order 或持久化相关改动还应运行对应专项测试，并对照 [Code Review Checklist](docs/07_process/code_review_checklist.md) 检查架构、安全、事务、性能、测试和文档联动。

测试已按领域和应用层归类，可以缩小反馈范围：

```bash
python -m pytest tests/order/ -q
python -m pytest tests/product/services/ -q
python -m pytest tests/product/repositories/ -q
```

完整目录说明和更多专项命令见 [测试目录导航](tests/README.md)。

## 架构边界

核心调用链：

```text
API → Service → Repository → Model → MySQL / SQLite
          │
          ├─→ Validator
          └─→ Redis / shared infrastructure
```

- API：协议适配、输入校验、认证/权限依赖、Mapper 和统一成功响应。
- Service：业务规则、事务边界、Repository 协调和审计编排。
- Validator：关键状态变迁前的同步纯业务校验，不查库、不写库。
- Repository：Tortoise ORM 查询和原子 CRUD，不包含业务判断。
- Model：表结构、关系、约束和索引声明。
- Schema：请求与响应数据形状，不依赖 Model、Repository 或 Service。

禁止 API 直接访问 Repository/Model，禁止 Service 直接操作 Model，禁止 Repository 反向依赖 Service。完整约束见 [Architecture](docs/04_architecture/architecture.md) 和 [Coding Standards](docs/05_development/coding_standards.md)。

## Product 图片清理

ProductImage 的 HTTP 删除是逻辑删除，物理文件由独立运维命令延迟清理。命令默认仅预览候选：

```bash
python -m app.tasks.product_image_cleanup \
  --before 2026-08-01T00:00:00+08:00 \
  --batch-size 100
```

确认截止时间、候选对象和存储目录后，才可使用相同参数增加 `--apply`：

```bash
python -m app.tasks.product_image_cleanup \
  --before 2026-08-01T00:00:00+08:00 \
  --batch-size 100 \
  --apply
```

不要在 Web 启动流程、数据库事务或未确认保留策略时自动执行物理清理。命令只处理当前存储命名空间中的安全 UUID 文件，并保护仍被有效记录引用的 URL。

## 数据库迁移

MySQL 是生产迁移的权威方言，SQLite 只用于本地开发与自动化测试。当前 MySQL 8+ M0–M8 迁移均已离线生成并通过静态契约测试；2026-09-08 又在一次性 MySQL 8.0.46 真实完成 Aerich 0→8、M8 列形状、221 项冻结 HEX 与 Gate A MARD publish/replay，随后删除容器并释放 13308。M8 基线 Run 34242753255 已 8/8。持久 Gate A 已完成 M3–M7、Wallet backfill/reconcile 和 M6 色卡发布，只有 M8 仍待受控应用；共享、预发布和生产环境不因这些 Gate A 证据自动迁移。仓库候选现以显式 `--source-version 7` 支持精确 M7→M8：只运行 M8，并以 `m7-preserved-business-v1` 对 20 个非色卡表和 `bead_colors` M7 投影（共 21 个业务表）做内容级摘要，另保持完整图片 manifest；停写后先用 raw M7 字段精确预检无 `swatch_hex`、221 条目录和 221 张 `0644` PNG，再要求 MARD preview/apply/replay 全部为严格 no-op。旧调用仍默认 M2，防止误把当前 M7 当成历史起点。成功后、`app-up` 前还必须在同一停写窗口重放 upgrade plan，实时复核数据库、图片、内容摘要和 MARD preview；`app-up` 自身不做这些 live 检查。独立只读代码审查发现并修复的停服复验缺口已由历史 head `fa6fce05...` / Run 34281512196 覆盖；完整 updater 的受测实现 head `62b1b15...` / merge-ref `a9ff3d2...` 又由 Run 34288613644 的第九个 required Job 在一次性 Linux/MySQL 8.0.46 上完成完整 updater 14/14 阶段。正式持久执行前仍须重新只读盘点、绑定目标 SHA/Image、建立当次新 Backup/独立 Restore、停写并取得明确写授权；CI 不授予持久写入权限。

本地持久 `db.sqlite3` 曾缺失目标设计已定义的 `refunds.inventory_restored` 与 `UNIQUE(order_id)`。提交 `35e8630` 提供默认预览、双显式确认、精确基线拒绝和 SQLite Backup API 的本地修复工具：

```bash
python scripts/local/repair_sqlite_refunds_schema.py
python scripts/local/repair_sqlite_refunds_schema.py --apply --confirm-local-only
```

2026-09-07 已对本地库应用，写前备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-refunds-repair-20260907-105304-874045.bak`，权限 `0600`，完整性/外键与结构重放核验均通过。该工具不写 Aerich、不能用于 MySQL，也不是发布迁移证据；数据库设计与 API 文档已是目标形状，无需因这次本地修复改契约。

生产环境禁止通过应用启动自动建表。执行 `aerich upgrade` 前必须：

1. 明确目标环境、MySQL 实例和版本；
2. 完成只读 Schema 审计；
3. 创建可验证备份或快照；
4. 先在临时或预发布 MySQL 执行并验证；
5. 获得明确执行授权并准备回滚方案。

禁止为了对齐版本记录而未经审计使用 `--fake`。完整流程见 [Database Migration Workflow](docs/07_process/database_migration_workflow.md)。

## 文档导航

| 主题 | 文档 |
|---|---|
| Product 权威业务规则 | [Product Business Rules](docs/01_requirements/product_business_rules.md) |
| Product API v1.0 | [Product API](docs/03_api/product_api.md) |
| Order 业务规则 | [Order Module](docs/01_requirements/order_module.md) |
| Order API v1.0 | [Order API](docs/03_api/order_api.md) |
| Inventory 权威业务规则 | [Inventory Module](docs/01_requirements/inventory_module.md) |
| Inventory API v0.6 | [Inventory API](docs/03_api/inventory_api.md) |
| Reservation N1 业务规则 | [Reservation Module](docs/01_requirements/reservation_module.md) |
| Reservation N1 API | [Reservation API](docs/03_api/reservation_api.md) |
| Reservation N2 微信主动通知规划 | [Reservation WeChat Notification Plan](docs/01_requirements/reservation_wechat_notification_plan.md) |
| 通用 API 约定 | [API Design Conventions](docs/03_api/api_design_conventions.md) |
| 数据库设计 | [Database Design](docs/02_database/database_design.md) |
| 分层与目录 | [Architecture](docs/04_architecture/architecture.md) |
| 前端架构（Draft） | [Frontend Architecture](docs/08_frontend/frontend_architecture.md) |
| 稳定产品与视觉边界 | [Product Context](PRODUCT.md) |
| 已实现设计系统 | [Design System](DESIGN.md) |
| UI 视觉与交互验收 | [Design QA](design-qa.md) |
| 前端多端/API/测试/学习策略 | [Frontend Documents](docs/08_frontend/) |
| Phase 9 微信发布规划 | [WeChat Release Plan](docs/08_frontend/phase9_wechat_release_plan.md) |
| Phase 9 发布审计与清单 | [Release Audit & Checklists](docs/09_release/README.md) |
| 前端架构决策 | [Frontend ADR](docs/08_frontend/adr/README.md) |
| 编码与 Git 规范 | [Coding Standards](docs/05_development/coding_standards.md) |
| AI/开发上下文 | [AI Context](docs/06_ai/AI_CONTEXT.md) |
| 迁移流程 | [Database Migration Workflow](docs/07_process/database_migration_workflow.md) |
| 容量与性能压测规范 | [Capacity Load Test Runbook](docs/09_release/capacity_load_test_runbook.md) |
| 最新 2C/4GiB/5Mbps 本地压测 | [M8 A/B/C/D 探索矩阵报告](docs/09_release/reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md) |
| 最新远端 CI 证据 | [Run 34288613644：完整 updater + 现行 9/9 required Job](https://github.com/EVEBios/pinkdooHub/actions/runs/34288613644) |

业务行为以 `docs/01_requirements/` 为准，HTTP 契约以 `docs/03_api/` 为准，表结构与索引以数据库设计和 DBML 为准；当前是否已实现必须结合代码、测试与 changelog 判断。

## Git 工作流

- `main`：生产就绪代码，只接受 Pull Request，禁止直接 push。
- `develop`：开发集成分支，是 feature/fix 分支的合入目标。
- `feature/<name>`：从 `develop` 创建的新功能分支。
- `fix/<name>`：Bug 修复分支。

提交信息使用 Conventional Commits：

```text
<type>(<scope>): <English imperative subject>
```

示例：

```text
feat(product): add product audit history
fix(auth): reject revoked refresh token
docs(readme): document local development workflow
```

一个提交只包含一个逻辑单元。未经明确授权不得执行数据库迁移、创建 tag、发布 Release、force push 或直接向受保护分支推送。

## 当前限制与后续工作

- v0.6.0 仍是未发布候选版本，尚未创建 Git tag 或 GitHub Release。
- Gate A 持久环境当前权威成功点为 M7；每次操作前仍须重新只读确认。`initial-migrate` 只支持空库；仓库候选的 `gatea_upgrade --source-version 7` 已收口 M7→M8，并让已有 Online 自选色商品只在数据库/221 图片完全匹配时通过事务内严格 no-op 复验。head `62b1b15...` / merge-ref `a9ff3d2...` 已由 Run 34288613644 在一次性 GitHub-hosted Linux 上完成完整 updater 14/14 阶段和现行 9/9 required Job；这关闭了 disposable 编排证据，不改变持久 Gate A 状态。下一步必须重新只读确认真实 M7，再绑定目标 SHA/Image、创建当次 `m7-preserved-business-v1` Backup/同 ID 独立 Restore、安排停写窗口并取得明确写授权。成功升级后必须保持 App/Nginx 停止并紧邻重放 upgrade plan，只有实时数据库、图片、21 表摘要与 MARD preview 全部匹配才可 `app-up`；后者自身不会重做这些检查。整个保护依赖维护窗口不存在直接 SQL 或宿主图片旁路写入，不是跨数据库/文件系统的绝对原子事务。不得使用默认 M2 路径、拆跑内部迁移任务、直接改表或为通过核验临时改变商品状态。远端 disposable CI 与本地 SQLite 都不构成 M8 已应用持久环境的证据。
- 真实 MySQL 演练曾发现 `OrderStatus` 通过普通 `SmallIntField` 被 asyncmy 编码为 Enum 字符串并触发 1366；现已在 Model 默认值及 Repository 更新/筛选边界统一转换为原生整数，并通过 MySQL 8.0.46 创建、筛选和状态更新回归，不再是发布阻断项。
- 邮件验证、OAuth、管理员启用用户和头像上传尚未实现。
- Phase 9.1–9.3 已完成；9.4 中不依赖备案的 M7 持久部署、MARD/Wallet 数据、备份恢复与运维治理已完成，真实 HTTPS/合法 Origin、正式 RC、体验版上传和 iOS/Android 真机仍等待外部条件与单独授权。M7→M8/Online no-op 保护和完整 updater 已由 Run 34288613644 在一次性 Linux 环境验证；持久目标 Runtime/HEX/gzip 现场验收、M8 数据后恢复和加密异机副本仍未关闭。Gate A 继续使用单主机持久图片卷；Gate B 的对象存储/CDN、真实微信 AppID、集中 Secret Manager、监控告警和隐私平台材料仍是后续阻断项。CI 通过也不授权数据库写入、微信 upload/gray/release、提审或公开发布。
- Phase 4.3.1–4.3.12 已完成并通过最终 Review；当前 Gate A 已包含 Inventory M2，但其他持久环境迁移、M8、发布与下一业务 Phase 仍需单独规划和授权。
- Wallet/Payment/Refund v1 已完成仓库实现、扩展 MySQL 门槛和 Gate A M4/backfill/reconcile；Gate A 只允许无真实资金的内部合成余额验收，真实充值/支付/退款 Provider 与生产开关仍关闭。历史 DELETED USER 与 ADMIN/SUPER_ADMIN 不补建钱包。
- Reservation N1 与 M7 可配置每周固定店休已完成仓库实现并已应用当前 Gate A M7，但尚未执行真实微信小程序真机验收；N2 微信订阅消息主动通知、可逆加密投递地址、durable outbox、worker、重试与监控均未实现，当前仅通过“我的预约/详情”展示状态和文案，并由管理端当前手机号提供人工联系兜底。
