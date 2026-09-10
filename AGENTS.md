# pinkdooHub 项目指令

本文件是 Codex 在本仓库中的项目级开发规则。它补充 `~/.codex/AGENTS.md` 的全局规则，并以本项目的架构、当前阶段和文档体系为准。详细设计保存在 `docs/`；本文件只保留每次任务都需要知道的约束和导航。

## 项目概览

pinkdooHub 是拼豆店管理系统，后端技术栈为 FastAPI、Tortoise ORM、Pydantic、Redis，以及 MySQL（生产）/ SQLite（开发）。依赖版本以 `requirements.txt` 为准，测试配置以 `pyproject.toml` 为准。

主要技术组件：

- FastAPI 0.139.2 + Uvicorn 0.51.0
- Tortoise ORM 1.1.7 + Aerich 0.9.3
- asyncmy 0.2.14（MySQL 异步驱动）
- Pydantic 2.13.4 + pydantic-settings 2.14.2
- Redis 8.0.1
- pytest 9.1.1 + pytest-asyncio + httpx

## 当前 Phase 与范围

当前代码版本候选为 **v0.6.0（尚未发布）**；**Phase 4.1：Product Module**、**Phase 4.2：Order Module**、**Phase 4.3：Inventory Module**、**Reservation N1**、**M6 自选颜色 Kit**、**M7 可配置每周固定店休**、**M8 数字色块 HEX/文本压缩** 与 **M9 二维码开台/多时长计时** 均已完成仓库实现。

已完成：

- 项目基础设施、统一响应、全局异常处理、配置、日志、数据库和 Redis 接入。
- 用户注册、登录、Token 刷新/登出、个人资料和密码修改。
- RBAC 权限链、管理员用户列表与禁用操作。
- 敏感操作的顺序审计日志。
- Product 业务规则、数据模型和 API 设计。

当前实现状态：

- M6 自选颜色 Kit 已完成仓库实现与本地回归：全局 221 个 BeadColor 槽、商品级 ProductKitColor 启用/10g 库存、统一每 10g 价格、每单最多 20 个颜色且每色最多 990g、颜色订单快照、扣减/取消/PAID 退款恢复、管理 API 与小程序页面均已接入；既有 fixed Kit 保持兼容。2026-09-07 已冻结 MARD A1–M15 共 221 色 manifest，并在本地 SQLite 导入 code/name/URL、确定性 PNG；2026-09-08 持久 Gate A 又在 M6 阶段发布 221 色元数据/PNG、建立三启用色测试商品和库存，随后完成 M7 数据后 Backup/Restore。M8 再把 `swatch_hex` 纳入正式字段；当前 Gate A 仍为 M7，现有 PNG 只作兼容回退，不转 WebP、不删除。
- Reservation N1 已完成独立预约、服务端上海营业日历、Pending→Confirmed/Rejected 审核、顾客提前三小时取消、ADMIN+ 单日店休及原子批量 `store_closed` 取消、当前手机号隐私投影、预约历史阻止注销、M5 和六个小程序页面。M7 又将每周固定店休从硬编码周一收口为 `ReservationSettings` 单例：默认周一，ADMIN+ 可更换星期，并原子取消新店休日上未开始的活跃预约。首版不绑定 Order/Payment、不自动计算容量、不快照手机号、不处理法定节假日/调休；拒绝原因仅 `no_capacity`，恢复营业不恢复历史预约。M5/M7 已应用当前持久 Gate A 并有综合数据/恢复证据；共享、预发布和生产环境不因该证据自动迁移。N2 微信主动通知尚未实现，详细冻结方案见 `docs/01_requirements/reservation_wechat_notification_plan.md`。
- Wallet/Payment/Refund v1 已完成仓库实现：新建普通 `USER` 创建 `0.00..1000.00` WalletAccount；历史 backfill 只补 NORMAL/DISABLED 普通 USER，历史 DELETED 不补，ADMIN/SUPER_ADMIN 始终不建钱包。六个用户侧 wallet/payment 端点强制 NORMAL USER；调账、代客扣款和退款资金写入只操作普通客户。已实现会员/流水查询、ADMIN+ 调账与代客钱包订单、余额支付、manual 结算、订单资金只读查询和一次全额退款；PAID Kit 恢复、COMPLETED 不恢复。一次性 MySQL Wallet `9 passed` 与三域联合 `30 passed`、远端 workflow 及 Gate A M4/backfill/reconcile 均已完成；Gate A 只允许无真实资金的合成验收。真实微信充值/支付/退款仍保持 503 零写入，共享/预发布/生产迁移和生产资金开关仍需单独授权。`wallet_reconcile` 全程只读，任一 mismatch/violation 非零退出且不自动修账。
- Phase 4.2 Order v1.0 已完成契约冻结、4.2.2–4.2.11 实现与 4.2.12 最终 Review：领域语言、Schema、Model/离线迁移、Repository、标准库 OD+ULID 生成器、查询/Experience 创建/三个状态变迁 Service、API Mapper、组合根，以及用户 4 个/管理 5 个 FastAPI 端点均已实现并有契约测试。创建用例批量校验 Product/Option，在单事务内写 Order、快照 Items、`CREATE_ORDER` 审计并重载聚合；编号冲突通过全新事务最多重试 3 次。状态用例在事务内执行 `SELECT ... FOR UPDATE`、锁后重检并原子提交状态/审计/重载。Mapper 对用户/管理列表、详情和状态响应执行显式字段投影与严格 Out Schema 校验，真实聚合测试固定零 SQL、零修改。路由统一通过认证或 ADMIN+ 依赖、`get_order_service()` 组合根、Mapper 和 `success()` 工作；缺失 Bearer 凭据已统一为 401 错误信封，既有无效 Token `1006` 仍按 User 契约返回 HTTP 400。完整真实 HTTP 矩阵覆盖创建防伪与边界、Product/Option/Kit 拒绝、权限和资源隐藏、组合筛选、全部非法状态前置条件、审计顺序、事务故障回滚及订单号冲突重试；三个无请求体状态 PATCH 会主动拒绝任意 body。最终安全复核同时将共享审计 IP 输入收紧为合法 IPv4/IPv6 字面量，非法、超长或带 scope 的代理头回退到直连地址。MySQL 8+ Order 增量迁移已离线生成并通过最终静态 Review；它作为 M1 已存在于当前 Gate A 的 M0–M7 链中，M8 不改变其结构，其他共享、预发布或生产数据库仍须分别核验和授权。
- Product 的业务、数据库、API 和 Schema 契约已完成；`app/common/` 中的 Product Enum/常量、`app/schemas/product*.py`、四个 Product Model，以及 `app/repositories/product_repo.py` 已实现并有契约测试。Product Validator、Service 和 API Mapper 均已完成，跨表写入和审计有真实事务回滚测试，Mapper 有零 SQL、零修改和字段隔离测试。Phase 4.3.10 移除旧 stock 写入口后保留 21 个 Product FastAPI 端点，包括 19 个用户/管理 JSON 查询与 mutation（含共享 AuditLog 分页操作历史），以及 Product 公共图/Option 专属图两个 ADMIN+ multipart 上传端点。上传链路已实现 2 MiB、jpg/png/webp、内容/MIME 一致、安全 UUID 路径、原子写入、Service 失败的幂等文件补偿、开发环境静态 URL 和真实 SQLite HTTP 流程测试；逻辑删除图片的本地文件由显式截止时间、命名空间校验、有效引用保护和失败重试语义的独立批处理清理。
- MySQL 8+ 权威迁移链现为 M0–M9，均已离线生成并通过静态契约测试；M9 新增固定桌台、会话、计时器与占用四表。持久 Gate A 已于 2026-09-08 从经只读确认的 M2 受控应用 M3–M7，本文更新时权威状态仍为 M7；M8/M9 只有在当次 CI、备份恢复、停写迁移与现场验收全部通过后才可记为已应用。共享、预发布和生产数据库不因 Gate A 证据自动迁移，仍须分别核验和授权。
- 本地持久 `db.sqlite3` 曾因 `generate_schemas()` 只补表不 ALTER 而缺少 `refunds.inventory_restored` 及 `UNIQUE(order_id)`。提交 `35e8630` 的精确修复脚本已应用，写前备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-refunds-repair-20260907-105304-874045.bak`；备份权限 `0600`，应用后完整性和外键核验通过。该脚本不写 Aerich，不是 MySQL/发布迁移证据，数据库设计与 API 契约本就已是目标形状。
- 综合本地演示数据已应用并通过专用 verifier：新增 9 个合成用户；本地表中共 19 个 Product（活跃 8 Experience/10 Kit，另 1 条逻辑删除）、8 笔四状态 Order、6 笔 Payment/Settlement、2 笔 Refund，及 6 条 seed Reservation（实际表含旧数据共 7 条）；自选颜色 Kit 启用三色，每周固定店休收敛为周三。写前备份 `backups/local-demo-data/db.sqlite3.pre-local-demo-20260907-105320-455438.bak` 与忽略的凭据文件 `backups/local-demo-data/synthetic-credentials.json` 均为 `0600`，不得记录或提交凭据值。`wallet_reconcile` 结果为 `scanned=11 mismatches=0 violations=0`；该检查点后端完整回归为 `2000 passed, 30 skipped`，三类 MySQL-only 门槛另以真实联合 `30 passed` 覆盖。
- ExperienceOption 配置组合在全历史范围内唯一；再次创建相同已删除组合时恢复原 Option ID、更新当前价格并保留图片关联，不创建第二条版本记录。
- Phase 4.1 曾让 Kit 库存采用直接设置最终值模式；Phase 4.3.10 已完成破坏性切换，当前所有业务库存写入统一经过 Inventory 流水语义。
- Phase 4.3.1 Inventory 现状审计与业务契约冻结已完成：`product_kits.stock` 保持唯一权威余额；创建 Pending Kit/混合订单时扣减、Pending 取消时幂等恢复、支付/完成不改库存；管理员调整采用 `change + reason + Idempotency-Key` 并允许 Online Kit；多 Kit 按 Product ID 升序加锁，MySQL 真实并发测试是发布硬门槛。运行时实现状态以以下分阶段条目及实际代码为准。
- Phase 4.3.2 Inventory 领域语言与 Schema 已实现：`app/common/` 中已有流水/source 字符串 Enum、库存/原因/幂等/重试常量和 `40931`–`40933` 命名异常；`app/schemas/inventory*.py` 已实现严格调整/查询输入及响应白名单。
- Phase 4.3.3 Inventory Model/数据库设计已实现：`InventoryTransaction` 已注册 ORM，关联 Product 与可空 User 的 `RESTRICT` 外键，使用命名幂等 UNIQUE 和 Product/source/type/全局分页索引；`source_id` 保持无 FK 的通用来源标识，Model 不承载跨字段业务判断。
- Phase 4.3.4 Inventory MySQL 8+ 增量迁移已离线生成并通过静态 Review，新增流水表并为 `stock > 0` 的现有 Kit 写幂等 `opening_balance`；零库存不写，余额不修改。完整链、正/零库存回填和 Phase 4.3.5 Repository smoke 已在一次性 MySQL 8.0.46 通过；该 M2 已存在于当前持久 Gate A 的 M0–M7 链中，其他持久环境仍未因此自动应用。DDL 与数据回填因 MySQL 隐式提交不具备整体原子性，任何新目标环境执行前仍必须停写、扫描库存范围和备份。
- Phase 4.3.5 `InventoryRepository` 已实现：单/多 Kit `select_for_update()`、按 Product ID 升序的一次集合锁、余额保存、单条/批量流水写入、同连接幂等读取/详情重载，以及 Product/type/source/UTC 时间组合分页；operator 预加载和 Order 编号批量补齐保持 Mapper 零 SQL。Repository 不拥有事务/重试、不判断库存业务规则或抛业务异常。
- Phase 4.3.6 `InventoryService.adjust_stock()` 已实现管理员调整：Service 自有事务内锁定 Kit，校验 Product 与余额，按 Product/change/规范化 reason/operator 处理严格幂等，并原子提交余额、`admin_adjustment` 流水和 `ADJUST_INVENTORY` Audit；并发 UNIQUE 在退出失败事务后解析。仅 MySQL 1205/1213 对整个用例用全新事务最多尝试 3 次，其他数据库错误不重试；日志不输出 reason/key。不可变结果的 `is_replay` 已由 Phase 4.3.10 Router 用于选择首次 201/重放 200。
- Phase 4.3.7 Kit/混合订单创建扣减已实现：Order Item 对 Experience 要求有效 Option，对 Kit 接受省略/null 并输出全 null Option 快照；OrderService 直接协调 InventoryRepository，在同一外层事务中先写 Pending Order，再稳定集合锁、锁后重检、批量余额/`order_deduction` 流水、Items、`CREATE_ORDER` Audit 和详情重载。库存不足只返回 Product/requested，不暴露 available；订单号冲突发生在库存写前，MySQL 1205/1213 对完整写事务最多尝试 3 次。阶段门禁 `40922` 已移除，现有 POST 路由可创建纯 Kit/混合订单。
- Phase 4.3.8 Pending 取消恢复已实现：取消事务先锁用户可见 Order 并重检 Pending，再读取最小 Item 快照、按 Product ID 升序锁定全部 Kit、批量检查服务端 restore 幂等键、恢复余额并写 `order_cancellation_restore` 流水，最后更新 Cancelled、写 `CANCEL_ORDER` Audit 和重载响应。Order 状态机与流水 UNIQUE 形成双层幂等保护；Pending 与已存在 restore 身份矛盾时抛 `40933`，余额越界抛 `40932`，任一步失败完整回滚。MySQL 1205/1213 对完整取消用例使用全新事务最多尝试 3 次；支付与完成不触碰库存。
- Phase 4.3.9 Inventory 查询 Service/Mapper 已实现：指定 Kit 查询按 Product 不存在、删除、类型、Kit 扩展的稳定优先级校验；全局 Product ID 只作为筛选，未知 ID 返回空 Page。两类查询复用 Repository 组合过滤和稳定分页。Mapper 显式投影流水/分页/调整响应，只消费预加载 operator 与批量 Order 编号，严格 Out Schema 校验，执行期间零 SQL、零 ORM 修改且不输出幂等键或用户隐私字段。
- Phase 4.3.10 Inventory API 已实现：`get_inventory_service()` 组合根和三个 ADMIN+ 路由已注册；调整要求严格 body 与 `Idempotency-Key`，首次 201、重放 200；指定 Kit/全局流水使用严格 Query、Mapper 和统一 Page 信封。旧 Product `PATCH .../stock`、对应 Schema/Mapper/Service 已移除，Kit 创建不再接受 stock 并固定从 0 开始。
- Phase 4.3.11 真实发布门槛已通过：隔离 MySQL 8.0.46 真实执行 Aerich 0→1→2 后，9 项测试覆盖同/异 key 调整、最后一件、反向多 Kit、同单取消、调整/下单阻塞、真实 1205 全事务重试、EXPLAIN 和 FastAPI 并发重放；`performance_schema.data_lock_waits` 证实行锁等待，三个关键查询命中预期索引。另有 41 项完整 HTTP 矩阵覆盖三端点认证、权限、资源/业务错误、严格 422、分页/筛选/Order source/UTC 和隐私。测试 fixture 拒绝 3306 与非专用 Schema；临时实例验证后销毁，未接触持久数据库。
- Phase 4.3.12 最终 Review 已完成：分层、事务所有权、稳定锁序、MySQL 瞬态重试、幂等/隐私、Schema/OpenAPI、Mapper、Model/迁移/索引及文档联动均已复核；Product 用户/管理 Kit 详情响应补齐 `stock <= 999999`，数据库设计与 DBML 的旧“未来 Kit”描述已更新为当前 Kit/混合订单语义。全新隔离 MySQL 8.0.46 再次真实迁移并通过 9 项门禁，SQLite/MySQL 同进程完整套件 1431 项通过。该阶段的隔离复核本身未写持久库；其 M2 后续已随 Gate A M0–M7 链应用。代码候选仍未 tag/release，其他持久环境须单独授权。
- 2026-08-14 真实 MySQL smoke 曾发现 Order `IntEnum` 发布阻断：`OrderStatus` 直接通过普通 `SmallIntField` 会被 asyncmy 编码成 Enum 字符串并报 1366。现已将 Model 默认值及 Repository 更新/筛选边界统一为原生整数，并在 MySQL 8.0.46 通过创建、Pending/Paid 筛选和状态更新回归；物理 Schema 未变化、无需迁移。后续仍不得把 SQLite 通过当作 MySQL 类型兼容证据。
- 架构文档中出现的 Product、Order、Inventory、Wallet/Payment/Refund 文件可能同时包含已实现与未来结构，不得仅凭目录图判断能力或持久库状态；开始任务前必须检查实际文件树、测试和迁移边界。
- Product API 文档已完成 Phase 4.1 Review，并标记为 v1.0 Implemented。后续维护仍以 `product_business_rules.md` 和 `product_api.md` 为契约；遇到缺口或冲突先指出，不自行发明业务规则。

后续阶段：

- Phase 4.3：Inventory；4.3.1–4.3.12 已完成并通过最终 Review。
- Wallet/Payment/Refund v1 已完成仓库实现、扩展 MySQL/远端门槛及 Gate A M4/历史补齐/对账；真实 Provider、生产环境迁移和生产开关仍属于发布前工作。
- Reservation N1 已完成；N2 微信主动通知、可逆加密投递地址、durable outbox、worker、重试与监控仍是明确后续范围，不能把页面状态展示误报为主动通知。
- M9 二维码开台已于 2026-09-10 完成仓库实现：精确 30 桌、15 分钟待支付、按 Experience 时长快照分组并各加 10 分钟、`quantity` 不乘时长、Kit 不参与计时、最长 Timer 到期只释放桌台；Reservation 独立，内部验收只用钱包/人工结算，真实微信支付另行立项。后端四表/迁移、API、跨域事务、小程序顾客和管理页面、受控 bootstrap/reconcile/sweep 及普通占位二维码均已接入；占位码内容为 `PINKDOOHUB_TABLE:v1:<token>`，微信官方小程序码保持 Deferred。
- M9 当前本地门槛为后端完整 `2384 passed, 39 skipped`、前端 `102 suites / 719 tests`，TypeScript/ESLint/Stylelint/CI policy/OpenAPI 类型均通过；一次性 MySQL 8.0.46 的 M0→M9 迁移和 M9 发布门槛为 `39 passed`。Gate A/容量 Runtime 已关闭未经脱敏的 Uvicorn access log，Nginx 与异常日志对桌台 Token 路径统一脱敏；reconcile 同时核验打开和已关闭会话的付款/计时历史。微信 CI 使用独立 `.env.ci`，避免生产占位 Origin 覆盖 CI 注入值；页头纹理由全局 CSS 变量只内联一次，当前不可发布微信产物主包约 0.86 MiB、总包约 1.42 MiB。
- M9 是 M8 之后的当前仓库候选增量；环境状态必须以该环境的 Release Record 为准。未经明确授权，不接入真实微信支付、不生成或上传正式微信小程序码，也不把仓库实现误报为持久环境已经迁移。

2026-09-09 已新增可复用的本机容量工具，并在 MySQL 8/M8、共享双 CPU、五个稳态容器内存上限合计 4096MiB、唯一 5Mbps TBF 出口下完整执行 A/B/C/D、5/10 VU 的 12/12 Profile 探索轮。`73,027` 个请求均成功，gzip 色板、认证浏览、C v3 的 221 PNG 冷/热完整页面和 150 个订单/库存/钱包写旅程均通过，最终对账、日志/statement 与资源清理通过；唯一失败是 10 VU 持续请求 51,063-byte 未压缩色板，产生 428 个 qdisc drops、P95/P99 1,510/2,442ms，所以整轮严格为 `FAIL`。gzip 后为 10,023 bytes、减少 80.371%，同一 10 VU 为 271/290ms 且零 drops。该 dirty-tree、单轮 ARM64 Docker **服务容器包络**不包含宿主内核/daemon/Runner，不是独立 2C/4GiB 主机、candidate-pre、TLS/公网或真机证据；报告见 `docs/09_release/reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md`。新增完整 updater disposable CI 候选后，本地回归为后端 `2348 passed, 33 skipped`、Release `259 passed`、Performance `190 passed`，前端为 `84 suites / 573 tests`，TypeScript/ESLint/Stylelint/CI policy/OpenAPI 类型均通过。没有新增直接依赖；为消除两条新公开的 Low 原型污染公告，`@tarojs/service@4.2.1` 允许范围内的传递依赖 Joi 已从 `17.13.4` lockfile-only 提升至 `17.13.7`，既有 npm 审计例外集合不变。CI 当前有 9 个 required Job；第九个 `gatea-m7-m8-updater` 已在 GitHub-hosted disposable Linux 上真实完成完整 M7→M8 编排。

当前仍为 **No-Go**：持久 Gate A 的权威成功点仍是 2026-09-08 的 M7 Runtime `73dca350...` 与数据后 Backup `20260908t021224z`；M8/M9 尚未应用。M9 仓库候选已把受控升级器扩展为 M7→M8→M9，并加入 30 桌 bootstrap/replay、M9 结构/约束、table reconcile/sweep、常驻 sweeper 与 Runtime API 验收；只有当前候选自身完成干净远端 required Jobs 后，才允许执行当次真实 Backup/独立 Restore、停写 apply、紧邻 plan replay、app-up 和数据后 Backup/Restore。历史 Run 34288613644 只证明 M8 updater 基线。真实 Origin/`release_eligible=true` RC、iOS/Android 真机、微信官方小程序码、upload/gray/release 与真实微信支付仍未完成或未授权；共享、预发布和生产环境未触碰。

## 文档导航与事实来源

遇到细节时先读对应文档，不凭记忆猜测。`docs/` 中既有已实现说明，也有未来设计；必须结合“当前 Phase”和实际代码判断实现状态。

### 开发与架构

| 需要了解 | 文档 |
|----------|------|
| AI/开发全局上下文、文档联动和流程 | [`docs/06_ai/AI_CONTEXT.md`](docs/06_ai/AI_CONTEXT.md) |
| 分层、目录、依赖方向、请求流程、基础组件 | [`docs/04_architecture/architecture.md`](docs/04_architecture/architecture.md) |
| 代码、类型、各层、性能、测试和 Git 规范 | [`docs/05_development/coding_standards.md`](docs/05_development/coding_standards.md) |
| 已完成能力、重要决策和已知限制 | [`docs/05_development/changelog.md`](docs/05_development/changelog.md) |
| 完成功能后的检查项目 | [`docs/07_process/code_review_checklist.md`](docs/07_process/code_review_checklist.md) |
| 数据库迁移生成、Review、执行与既有库基线 | [`docs/07_process/database_migration_workflow.md`](docs/07_process/database_migration_workflow.md) |
| 容量压测设计、执行、证据与资源清理 | [`docs/09_release/capacity_load_test_runbook.md`](docs/09_release/capacity_load_test_runbook.md) |
| 用户模块历史摘要 | [`docs/06_ai/User_Module_Summary.md`](docs/06_ai/User_Module_Summary.md) |

### 需求与业务规则

| 模块 | 文档 |
|------|------|
| 用户需求 | [`docs/01_requirements/user_module.md`](docs/01_requirements/user_module.md) |
| Product 需求概要 | [`docs/01_requirements/product_module.md`](docs/01_requirements/product_module.md) |
| Product 权威业务规则 | [`docs/01_requirements/product_business_rules.md`](docs/01_requirements/product_business_rules.md) |
| Order 需求 | [`docs/01_requirements/order_module.md`](docs/01_requirements/order_module.md) |
| Inventory 权威需求 | [`docs/01_requirements/inventory_module.md`](docs/01_requirements/inventory_module.md) |
| Wallet/Payment/Refund 权威需求 | [`docs/01_requirements/wallet_module.md`](docs/01_requirements/wallet_module.md) |
| Reservation N1 权威需求 | [`docs/01_requirements/reservation_module.md`](docs/01_requirements/reservation_module.md) |
| Reservation N2 微信通知规划 | [`docs/01_requirements/reservation_wechat_notification_plan.md`](docs/01_requirements/reservation_wechat_notification_plan.md) |
| M9 二维码开台权威需求（已实现） | [`docs/01_requirements/table_session_module.md`](docs/01_requirements/table_session_module.md) |

### API 与数据

| 需要了解 | 文档 |
|----------|------|
| 通用响应、分页、错误码和 Enum 约定 | [`docs/03_api/api_design_conventions.md`](docs/03_api/api_design_conventions.md) |
| 用户 API | [`docs/03_api/user_api.md`](docs/03_api/user_api.md) |
| Product API | [`docs/03_api/product_api.md`](docs/03_api/product_api.md) |
| Order API | [`docs/03_api/order_api.md`](docs/03_api/order_api.md) |
| Inventory API | [`docs/03_api/inventory_api.md`](docs/03_api/inventory_api.md) |
| Wallet/Payment/Refund API | [`docs/03_api/wallet_api.md`](docs/03_api/wallet_api.md) |
| Reservation API | [`docs/03_api/reservation_api.md`](docs/03_api/reservation_api.md) |
| M9 二维码开台 API（已实现） | [`docs/03_api/table_session_api.md`](docs/03_api/table_session_api.md) |
| 表、字段、约束和索引 | [`docs/02_database/database_design.md`](docs/02_database/database_design.md) |
| 可维护的 ER 源文件 | [`docs/02_database/er_diagram.dbml`](docs/02_database/er_diagram.dbml) |

按主题确定事实来源：

- 业务行为以对应的 `docs/01_requirements/` 文档为准。
- HTTP 契约以对应的 `docs/03_api/` 文档为准。
- 表结构和索引以 `database_design.md` 与 `er_diagram.dbml` 为准，两者必须保持一致。
- 当前是否已经实现，以实际代码、测试和 changelog 共同判断；规划目录或 Draft 文档不能当成实现证据。
- 架构边界和编码方式以本文件、`architecture.md` 和 `coding_standards.md` 为准。
- 文档相互冲突时不要静默选择其中一份：检查代码、测试、文档版本和当前 Phase，明确报告差异后再按任务范围处理。

## 项目架构

核心调用链为：

```text
API → Service → Repository → Model → MySQL/SQLite
          │
          ├─→ Validator（关键状态变迁前的纯业务校验）
          └─→ core/Redis/共享基础设施
```

各层职责：

- `app/api/`：路由、请求参数、Pydantic 校验、认证/权限依赖、调用 Service、构造统一成功响应；不得写业务逻辑或数据库查询。
- `app/services/`：业务规则和编排、权限判断、事务边界、Repository 协调、Validator 调用、外部基础设施调用。
- `app/validators/`：关键状态变迁前的完整性判断；数据由 Service 准备，只判断并抛业务异常，不查库、不写库、不返回 bool。
- `app/repositories/`：Tortoise ORM 查询和原子 CRUD；不得包含状态判断、权限判断或业务异常。
- `app/models/`：表结构、关系、字段约束和索引声明；不得包含应用层业务行为。
- `app/schemas/`：请求和响应数据形状；可依赖 `common/`，不得依赖 Model、Repository 或 Service。
- `app/common/`：跨领域 Enum、常量、分页和响应类型，不反向依赖应用层。
- `app/core/`：配置、安全、Redis 和基础异常，不反向依赖业务层。
- `app/middleware/`：HTTP 横切能力和统一异常处理。
- `app/utils/`：无状态纯工具，不依赖应用层。

依赖规则：

- 禁止 API 直接调用 Repository 或 Model。
- 禁止 Service 直接操作 Model；所有持久化经过 Repository。
- 禁止普通业务 Service 调用另一个业务 Service；跨领域数据通过对应 Repository 获取。
- `AuditLogService` 是当前明确的共享基础设施 Service 例外，可以被业务 Service 调用。新增例外必须先在架构文档中说明共享属性和依赖方向。
- 禁止 Repository 调用 Service、Validator 或 Redis。
- 禁止 Validator 调用 Service 或 Repository。
- 每增加一个 import，都检查是否发生反向依赖或跳层调用。

## 强制开发规则

### 异常与响应

- 业务错误由 Service 或 Validator 抛出，禁止使用 FastAPI `HTTPException` 表达业务规则。
- 已有模块命名异常时优先使用，例如 `UsernameAlreadyExists()`、`UserNotFound()`；稳定的新业务错误应在模块异常文件中定义命名异常并继承 `BusinessException`。一次性且没有命名类型的错误才直接构造 `BusinessException(code=..., message=...)`。
- 异常由 `app/middleware/exception.py` 统一转换；API 不用 `try/except` 手写错误响应。
- 成功响应统一使用 `success(data=..., message=...)`，禁止手写 `{"code": 0, ...}`、返回其他信封或返回裸列表。
- API 输出必须先经 Pydantic Out Schema 验证/序列化，例如 `UserOut.model_validate(obj).model_dump()`，再传给 `success()`；禁止直接返回 ORM Model。
- 任何响应、日志和调试信息都不得包含 `password`、Token、密钥等敏感字段。

### 命名、类型与数据模型

- 类名使用 PascalCase；函数、变量和文件使用 snake_case；常量使用 SNAKE_CASE。
- Schema 使用明确后缀，如 `XxxCreate`、`XxxUpdate`、`XxxOut`、`XxxListItem`、`XxxRequest`。
- 公开函数和各层方法必须标注参数及返回类型；Out Schema 配置 `from_attributes = True`。
- 禁止 Magic Number；稳定业务值放入 `app/common/constants/`，枚举放入 `app/common/enums/`。
- Enum 的数据库表示按模块权威设计执行：User 当前使用 `SmallIntField` + `IntEnum`；Product 的 `ProductType`/`ProductStatus` 设计为字符串 Enum。不要把一种存储方式机械套到所有模块。
- 金额使用 `Decimal`/`DecimalField(max_digits=10, decimal_places=2)`，禁止使用 float。
- 列表和分页接口使用 `Page[T]`，不得用裸 tuple 表达分页结果，也不得无限制全表加载。

### 数据、事务与性能

- 跨表写入或必须保持原子性的操作使用 `in_transaction()`。
- 禁止在 `for` 循环中逐条 `await` 查询；按关系使用 `select_related()` 或 `prefetch_related()`。
- 批量写入或更新优先使用 `bulk_create()`、`bulk_update()` 或集合更新，避免循环单条保存。
- 列表查询必须包含分页 `limit`/`offset`；只读取需要的字段。
- 索引根据实际查询模式设计，通过 Model `Meta.indexes` 集中声明，并同步数据库文档和 ER 图。
- Product 上架等关键状态变迁必须调用对应 Validator；Validator 失败时直接抛异常。

### 日志

- 每个模块使用 `logging.getLogger(__name__)`，禁止 `print()` 和遗留调试输出。
- 关键业务操作记录必要上下文；异常记录应支持定位问题，适用时使用 `exc_info=True`。
- 不在日志中记录密码、Token 或完整敏感个人信息。

## 开发流程

开始任务时：

1. 确认任务所属模块、当前 Phase 和明确范围。
2. 先读该模块的需求文档与 API 文档；Product 任务必须同时读 `product_business_rules.md` 和 `product_api.md`。
3. 涉及表结构时再读 `database_design.md` 和 `er_diagram.dbml`；涉及分层或新增目录时读 `architecture.md`；涉及具体写法时读 `coding_standards.md`。
4. 检查实际代码和测试，不根据规划文档假设文件、端点或能力已经存在。

实现与验证时：

1. 按当前架构做完成任务所需的最小改动。
2. 同步新增或更新正常、异常、权限和关键边界测试。
3. 运行与改动直接相关的测试，再运行完整测试：`pytest tests/ -q`。
4. 检查分层、依赖方向、事务、安全、性能和敏感数据处理。
5. 按下方联动表检查并更新文档；文档与代码属于同一逻辑改动。
6. 完成一个独立功能模块时更新 `docs/05_development/changelog.md`。
7. 使用 `git diff` 和仓库状态复核变更范围，确认没有无关文件、调试输出、敏感信息或意外生成物。
8. 只有用户明确要求时才 commit、push、发布、打 tag 或执行数据库迁移；完成实现不自动扩大为远端或环境变更授权。

无法运行测试或检查时，明确列出未验证项和原因，不得声称已经通过。

## 文档更新联动

| 代码或设计变化 | 必须检查/更新 |
|----------------|---------------|
| Model、表、字段、约束或索引 | `docs/02_database/database_design.md` + `docs/02_database/er_diagram.dbml` |
| API 端点、请求、响应或错误 | `docs/03_api/<module>_api.md` |
| Enum 或映射方式 | `docs/03_api/api_design_conventions.md` 对应章节 + `docs/06_ai/AI_CONTEXT.md` 速查表 |
| 业务规则、状态流或权限 | `docs/01_requirements/<module>.md`；Product 还要检查 `product_business_rules.md` |
| 目录、分层或依赖方向 | `docs/04_architecture/architecture.md` |
| 依赖或技术栈 | `requirements.txt` + `architecture.md` 技术栈章节 |
| 通用编码或流程规范 | `docs/05_development/coding_standards.md`；必要时同步本文件 |
| 新错误码 | 模块 API 文档 + `api_design_conventions.md` + `AI_CONTEXT.md` 错误码速查 |
| 独立功能模块完成 | `docs/05_development/changelog.md` |

更新文档时说明设计原因和取舍，保持示例与实际代码一致，并沿用同目录现有格式。不要只写“详见代码”，也不要在多个文档复制一份可能失同步的规则。

## 完成与 Review

完成较大任务或独立功能模块后，对照 `docs/07_process/code_review_checklist.md` 检查：

- Architecture：分层、依赖方向、文件归属。
- Security：密码、密钥、Token、权限、输入和 SQL 安全。
- Naming & Types：命名、类型标注、Schema、Enum、常量。
- Exception & Response：命名业务异常、统一中间件、`success()` 和 Pydantic 输出。
- Database & Performance：字段、约束、索引、事务、分页和 N+1。
- Testing & Logging：新增测试、异常/边界覆盖、日志和调试输出。
- Documentation：API、需求、数据库、架构、AI context 和 changelog 联动。

最终交付说明至少包含：修改内容、运行过的测试及结果、文档影响、是否需要数据库迁移/版本升级/新增依赖，以及仍未完成或未验证的事项。
