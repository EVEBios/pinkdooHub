# AI Context — pinkdooHub

> 强制开发规则已内置在项目根目录的 `AGENTS.md` 中（每次会话自动加载）。
> 本文档是 AI 的"项目守则"——定义开发流程、文档维护规则和全局上下文。
> 完成任何代码修改后，按本文档检查是否需要同步更新。
> 遇到不确定的领域时，按索引去读对应文档，不要凭记忆猜测。

---

## 1. 文档索引

| 需要了解 | 读这个 |
|----------|--------|
| 代码怎么写 | [coding_standards.md](../05_development/coding_standards.md) |
| 项目怎么分层 | [architecture.md](../04_architecture/architecture.md) |
| 开发历史 | [changelog.md](../05_development/changelog.md) |
| API 设计规范（全局） | [api_design_conventions.md](../03_api/api_design_conventions.md) |
| 用户 API | [user_api.md](../03_api/user_api.md) |
| 商品 API | [product_api.md](../03_api/product_api.md) |
| 商品业务规则 | [product_business_rules.md](../01_requirements/product_business_rules.md) |
| 订单 API | [order_api.md](../03_api/order_api.md) |
| 会员钱包/支付/退款业务规则 | [wallet_module.md](../01_requirements/wallet_module.md) |
| 会员钱包/支付/退款 API | [wallet_api.md](../03_api/wallet_api.md) |
| 库存业务规则 | [inventory_module.md](../01_requirements/inventory_module.md) |
| 库存 API（已实现） | [inventory_api.md](../03_api/inventory_api.md) |
| 预约业务规则（N1 权威） | [reservation_module.md](../01_requirements/reservation_module.md) |
| 预约 API（N1 权威） | [reservation_api.md](../03_api/reservation_api.md) |
| 预约微信店休通知（N2 Deferred） | [reservation_wechat_notification_plan.md](../01_requirements/reservation_wechat_notification_plan.md) |
| 二维码开台业务规则（M9 已实现） | [table_session_module.md](../01_requirements/table_session_module.md) |
| 二维码开台 API（M9 已实现） | [table_session_api.md](../03_api/table_session_api.md) |
| 数据库设计 | [database_design.md](../02_database/database_design.md) |
| ER 图 | [er_diagram.dbml](../02_database/er_diagram.dbml) |
| Code Review 清单 | [code_review_checklist.md](../07_process/code_review_checklist.md) |
| 数据库迁移流程 | [database_migration_workflow.md](../07_process/database_migration_workflow.md) |
| 容量与性能压测规范 | [capacity_load_test_runbook.md](../09_release/capacity_load_test_runbook.md) |
| 稳定产品与顾客四根页边界 | [PRODUCT.md](../../PRODUCT.md) |
| Ribbon Ledger 与瓷白丝带托盘规则 | [DESIGN.md](../../DESIGN.md) |
| 四根页 Surface Brief | [miniapp-customer-root-tabs.md](../../.impeccable/surfaces/miniapp-customer-root-tabs.md) |
| 前端总体架构（Draft） | [frontend_architecture.md](../08_frontend/frontend_architecture.md) |
| 前端多端策略 | [multi_platform_strategy.md](../08_frontend/multi_platform_strategy.md) |
| 前端 API 集成契约 | [api_integration_contract.md](../08_frontend/api_integration_contract.md) |
| 前端测试策略 | [testing_strategy.md](../08_frontend/testing_strategy.md) |
| 前端学习路线 | [learning_roadmap.md](../08_frontend/learning_roadmap.md) |
| Phase 9 微信发布规划 | [phase9_wechat_release_plan.md](../08_frontend/phase9_wechat_release_plan.md) |
| Phase 9 发布审计与清单 | [Release Documents](../09_release/README.md) |
| 前端 ADR | [ADR Index](../08_frontend/adr/README.md) |
| 需求文档 | [../01_requirements/](../01_requirements/) |

---

## 2. 技术栈速查

| 层级 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.139 |
| ORM | Tortoise ORM | 1.1.7 |
| 数据校验 | Pydantic | 2.13 |
| 配置管理 | pydantic-settings | 2.14 |
| 密码加密 | passlib[bcrypt] | 1.7.4 |
| JWT | python-jose + cryptography | 3.5.0 + 50.0.1 |
| 数据库 | MySQL（生产）/ SQLite（开发） | — |
| MySQL 异步驱动 | asyncmy | 0.2.14 |
| 缓存 | Redis | — |
| 迁移 | Aerich | 0.9.3 |
| 服务器 | Uvicorn | 0.51 |
| 测试 | pytest + pytest-asyncio + httpx | 9.1 / 1.4 / — |
| 时区 | tzdata | —（Windows 必需） |

跨端前端技术基线如下。四端技术 Spike 已于 2026-08-15 通过并锁定精确版本（临时工程 `spikes/taro-four-end-spike/`，已 gitignore）；正式工程 `miniapp/` 已于 2026-08-15 创建。2026-08-20 已完成并提交依赖/API 基础、账号密码登录代码链及微信开发者工具认证 Functional；2026-08-22 已完成公开 Product 列表、筛选与详情 Phase 6：

| 层级 | 技术 | 状态 |
|------|------|------|
| 跨端框架 | Taro 4.2.1（所有 `@tarojs/*` 同一版本） | Accepted |
| UI 框架 | React 18.3.1 | Accepted |
| 语言 | TypeScript 5.9.3 strict（`skipLibCheck`） | Accepted |
| 编译器 | Webpack 5.91.0 | Accepted（Spike 四端通过） |
| 基础组件 | `@tarojs/components` | Accepted |
| 增强组件 | NutUI React Taro 2.7.15（候选） | Deferred（Spike 通过但正式工程未安装；真实需要时按 ADR-005 受控引入） |
| API 类型 | FastAPI OpenAPI + `openapi-typescript` 7.13.0 | Accepted（正式生成链已落地） |
| 测试 | Jest 29.7.0 + `@tarojs/test-utils-react` 0.1.1 | Accepted（含 `legacy-peer-deps` 等已知 workaround） |

### 2.1 当前 Phase 与实现边界

- 小程序顾客一级信息架构保持“商城 / 预约 / 订单 / 会员中心”四个固定根 Tab；M9 后 `app.config.ts` 共注册 16 个主包页面和 20 个 `admin` 分包页面，即 36 条路由。商品浏览只在商城，普通 USER 的账户与退出在会员中心，ADMIN+ 的身份与退出在独立“店铺工作台”；详情、购物车、下单确认、认证、钱包、工作台和管理页不显示底栏。微信通过 `custom-tab-bar/` 使用“瓷白丝带托盘”并设置 `custom: true`，支付宝/抖音/H5 使用同路径、文案与本地图标的原生 `custom: false` 降级。根页跳转必须用 `switchTab`，`navigation/root_tabs.ts` 统一配置和选中同步；微信每个根页的自定义栏实例需在页面显示时同步自身索引。
- 微信、抖音和 H5 默认由无底栏 `pages/entry` 等 `/users/me` 确认身份后分流：Guest/普通 USER `switchTab` 商城，ADMIN+ `reLaunch` 到 `admin/pages/workbench`；支付宝因首个 Tab 必须是首页而保留商城为 `pages[0]`，由商城相同角色守卫分流。四个顾客根页及商品详情、购物车、下单确认、顾客订单/预约详情和钱包页都在对应业务 Hook 挂载前把 ADMIN+ 送回工作台。工作台按“今日处理 / 商品与库存 / 门店与权限”展示预约审核、订单处理、商品管理、库存流水、营业日历、用户与权限及 M9 桌台工作台七个入口，自身不请求列表/汇总、不伪造数字；本期不做管理员底栏、商城预览或摘要 API。订单、预约和会员中心对普通 USER 再显示时读取新鲜服务端事实并与首次挂载去重，商城保留筛选与浏览上下文。M9 又在该壳层新增桌台入口，但不改变既有六项权限和业务边界；自动化、构建与视觉结论以本次真实执行证据和 changelog 为准。
- M8 **数字色块 HEX 的 Model/迁移/API/销售校验、小程序直绘和发布工具均已完成仓库实现，并已应用当前本地持久 SQLite；Gate A 仍为 M7，M8 尚未应用**：`BeadColor.swatch_hex` 为 nullable `VARCHAR(7)`，非空写入规范化为大写 `#RRGGBB`；code/name/有效 HEX 三者完整才算 configured，激活、商品颜色启用、上架、公共输出与下单均 fail closed。公开颜色响应要求非空 HEX，管理响应保留 nullable 诊断态。小程序以共享组件用 `backgroundColor` 直绘，并只在迁移期 HEX 缺失时回退可选 `swatch_image_url`；该 URL 只用于既有兼容 PNG 或未来实拍校色 WebP，不回退商品封面。现有 221 张 PNG 不转 WebP、不删除；纯数字色块不再生成新图片格式。
- M9 **二维码开台已于 2026-09-10 完成仓库实现**：精确建立 `T01`–`T30` 与环境专属随机 QR Token；NORMAL USER 将本人含 Experience 的 Pending 订单绑定桌台后占用 15 分钟。付款以 `Payment.succeeded_at` 为统一起点，Experience 按 `option_duration_minutes` 精确分组，同分钟合并、不同分钟分别计时，每组增加 10 分钟；`quantity` 不乘时长，Kit 可同单购买但不参与计时，纯 Kit 不可开台。最长 Timer 到期只释放桌台；取消、完成、退款和管理员释放在原事务内关闭会话。四表、M9 迁移、API/Mapper、严格幂等与限流、sweeper/reconcile、顾客扫码/付款/计时页和 ADMIN 桌台页均已实现。备案前普通占位码使用 `PINKDOOHUB_TABLE:v1:<token>`，目标微信版本为 `develop`；微信官方小程序码和真实微信支付分别 Deferred。本文更新时 Gate A 仍为 M7，仓库实现不等于已部署。
- M9 当前本地门槛为后端等价完整 `2856 passed, 39 skipped`（沙箱 `2852 passed`，四项 loopback bind 在允许环境另为 `4 passed`）、Release 等价完整 `734 passed`（沙箱 `732 passed`，其中两项 loopback bind 在允许环境另为 `2 passed`）、前端完整 `102 suites / 719 tests`，TypeScript/ESLint/Stylelint/CI policy/OpenAPI 类型通过；一次性 MySQL 8.0.46 的 M0→M9 迁移与 M9 真实门槛为 `39 passed`。Runtime 关闭未经脱敏的 Uvicorn access log，Nginx 与应用异常日志对桌台 Token 路径统一脱敏；table reconcile 同时校验打开与已关闭会话的历史付款/计时快照。微信 CI 通过独立 `.env.ci` 隔离生产占位 Origin，页头纹理只在全局样式中内联一次，当前不可发布产物主包约 0.86 MiB、总包约 1.42 MiB。当前结论仍只属于仓库/一次性环境，等待本候选自己的远端 CI。
- Gate A Backup 的常驻服务恢复按精确 Schema 分流：M7/M8 不启动 M9 `table-sweeper`；M9 在备份前必须要求 sweeper 健康，并与 App/Nginx 一起停写和恢复。该分流只由备份器从批准的 Aerich 链内部选择，未知链或停写窗口内版本变化均拒绝；普通 `app-up` 仍默认严格要求 M9 sweeper。
- M9 持久发布候选现采用 `stage` → `activate-config` → upgrade/replay → `app-up` → acceptance → resilience → 数据后 Backup/Restore → `finalize` 的可恢复状态机。唯一 operation lock 防并发，另以全局 inventory 扫描所有候选 SHA 的四类 candidate pending，以及所有候选的 acceptance pending/complete；candidate、Backup/Restore、upgrade、Bootstrap、两类代表数据、`initial-migrate`、`app-up`、acceptance 与 resilience 都必须在数据库快照、TTY、业务 API 或资源启停前 fail closed。只有原动作严格绑定 candidate/kind/path/checkpoint 的 own recovery 可获结构化 allowance，任一第二 blocker、畸形项或非普通路径仍失败；不同 Backup ID 不因此全局互斥。
- `finalize` 的 acceptance/resilience Record 父目录必须分别等于对应 canonical 默认或显式 guarded directory；入口先扫描全候选 acceptance sidecar。resilience final 还必须是 `root:root 0644`、`nlink=1`、稳定且没有 `.tmp-*`/未知 alias/sidecar 的已收口普通文件，candidate 不替 resilience 清理残留。
- Run 34520442209 的 8 个非 updater required Job 均通过，但 updater 在 source Backup 后因新增必填 `release_record_dir` 未从 disposable 编排器透传到 Restore 而失败。当前调用已显式复用受保护 Release Record 目录，并由接线回归同时断言 Backup/Restore；该 Run 只保留为诊断证据，后续当前 SHA 仍须取得全新 9/9。
- 发布证据采用 durable no-clobber 语义：不可变 Record/artifact 先在同目录随机临时文件完整写入并 file `fsync`，再 hard-link 发布并同步目录；candidate/config/current journal、Backup/Restore、Upgrade evidence/success、acceptance `.complete`/final 和 resilience final 都按各自提交点恢复。acceptance 使用 schema v3 pending 与独立的 schema v1 success，Payment ID/No 哈希/成功时间跨两者绑定；resilience final 已可见时只做两次完整现场一致性复验并清理最多一个同 inode writer temp，孤儿/额外 alias 阻断且不会重跑依赖故障。所有持久变更入口在 CLI work 前统一安装 SIGHUP/SIGTERM/SIGINT guard，SIGINT 保持 `KeyboardInterrupt`；强制恢复/清理子进程使用新 session/独立进程组。服务 stop、Restore project 与 candidate 临时镜像分别以 Compose `ps`、容器/两个临时卷/internal network inventory、精确 image reference inventory 判定完成，后两类最多重试两轮；不能以 Docker 命令退出码代替复核。错误传播固定为 recovery/cleanup failure > original work/control error > deferred signal。SIGKILL/断电后只能严格恢复 journal/已提交 Record，不能猜测完成。M9 resilience 必须显式传入 acceptance Record 与确认 SHA-256，并在前后直连验证 candidate/Image、Operations/CI、upgrade/replay、代表数据/凭据、五服务、attempt digest 与完成时间；M9 Record 为 schema v2，M2/M7/M8 legacy Record 保持 schema v1。该实现仍未改变 Gate A M7/No-Go 的环境事实。
- MySQL/Aerich 权威链现为 M0–M9；M8 负责 221 色 HEX 回填与 MARD 精确核验，M9 新增固定桌台、会话、计时器和当前占用四表，并在迁移后执行 30 桌 bootstrap/replay。M8 的一次性 MySQL、历史 CI 与 M7→M8 updater 证据继续作为基线；当前 M9 候选必须用自身干净 SHA 的 CI 与目标环境 Release Record 证明。持久 Gate A 在本文更新时仍为 M7，M8/M9 尚未应用。
- HTTP 传输已为直连 App 增加 ≥1 KiB、level 6 的协商 gzip，并在 Gate A/Rehearsal Nginx 启用相同文本 MIME 策略；本地上传图片路径和 PNG/JPEG/WebP MIME 不重复压缩。标准 Nginx 镜像没有 Brotli 模块，本次不更换镜像、不引入第三方压缩依赖。
- M6 **自选颜色 Kit 仓库实现、客户端、本地 SQLite/MARD、MySQL 门槛及 Gate A 持久发布均已完成**：`KitKind=fixed|color_selectable`，省略保持 fixed；全局 BeadColor 固定 221 槽，每个 color-selectable Product 独立维护 `is_enabled/stock_units`。价格按 10g，每色一条 OrderItem，Order 快照 code/name/slot/10g，InventoryTransaction 可空关联 kit color；fixed 历史语义保持兼容。Gate A 已按冻结 manifest 发布 221 色 code/name/URL 与 221 张确定性 PNG，综合商品启用三色并有库存，数据后 225 图片 Backup/Restore 通过。M8 只新增 HEX 权威字段，不重建/转换这些 PNG；Gate B 对象存储/CDN和实体拼豆校色仍待完成。
- M6/M8 细节契约：每色数量≤99、颜色行≤20、非颜色行≤10、总行≤30；Product 上架与颜色启停共用 Product 行锁，全局色板修改按引用 Product ID 升序→BeadColor→启用关联锁序并锁后复验；管理输出保留 enabled + inactive/unconfigured 诊断态，公共输出只接受 code/name/规范 HEX 全部完整。BeadColor.sort 范围为 `0..32767`，最长元数据审计使用有效 JSON 的 len/SHA-256 有界摘要；miniapp 与 OpenAPI 生成物同步。
- Reservation N1/M7 **契约、仓库实现、MySQL 门槛和 Gate A 持久验收已完成**：独立预约不创建 Order/Payment；正常普通 USER 以 `experience_option_id + reservation_date + start_time` 创建 pending，必须有当前手机号。服务端按上海时区执行未来 0–30 日、11:00–20:00、至少提前 3 小时和可配置固定店休。单日/固定店休原子取消尚未开始的活跃预约为 `store_closed`，恢复不复活历史。M5/M7 已应用当前 Gate A M7并有综合数据/恢复证据；共享、预发布、生产及真机不因该结果自动通过。N2 微信订阅消息、Outbox、Worker 与主动通知保持 Deferred。
- Wallet/Payment/Refund v1 **仓库实现、扩展 MySQL/远端门槛及 Gate A M4/backfill/reconcile 已完成**：普通 USER 钱包、ADMIN+ 调账/代客订单、余额支付、manual settlement、资金查询和一次全额退款均已实现；历史 DELETED 与 ADMIN/SUPER_ADMIN 不建钱包，所有资金写入只操作普通客户，主动消费与代客订单还要求 NORMAL，disabled 只允许 ADMIN+ 人工纠错和法定义务退款。一次性 MySQL Wallet `9 passed`、三域联合 `30 passed` 和远端 Run 均通过；Gate A 综合数据后 reconcile 为 `4/0/0`。Gate A 只允许无现金价值合成余额验收；真实微信 Provider/充值/支付/退款保持 503 零写入，生产迁移和开关仍需单独授权。
- 本地持久 SQLite 于 2026-09-07 完成一次精确结构修复：提交 `35e8630` 的工具补齐 `refunds.inventory_restored` 和 `UNIQUE(order_id)`，写前 `0600` 备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-refunds-repair-20260907-105304-874045.bak`，完整性/外键与重放核验均通过。该工具不写 Aerich，不表示 M4 已在本地或发布环境按 Aerich 应用；数据库设计/API 已是目标形状，无需修改契约。
- 本地综合 demo seed 已实际应用并通过专用 verifier：写前备份 `backups/local-demo-data/db.sqlite3.pre-local-demo-20260907-105320-455438.bak` 与被 Git 忽略的 `backups/local-demo-data/synthetic-credentials.json` 均为 `0600`，不记录凭据值。新增 9 个合成用户；当前表为 users 13、products 19、product images 24、orders 8/items 10、payments 6/settlements 6/refunds 2、inventory transactions 238、reservations 7、wallet accounts 11/transactions 9、audit logs 584、external identities 0。订单覆盖四状态，预约 seed 覆盖四状态及 `customer_request/store_closed`，自选颜色 Kit 启用三色，每周固定店休为周三。`wallet_reconcile` 为 `scanned=11 mismatches=0 violations=0`；真实微信外部身份和 Provider 成功事实不伪造。
- M8 基线完整回归为后端 `2069 passed, 31 skipped`（122.64s），skip 为显式隔离的 MySQL-only 门槛；M8 另在一次性 MySQL 8.0.46 真实 0→8 后通过精确 HEX 与 publish/replay `2 passed`。前端 Node 24.13.0 / npm 11.6.2 为 `84 suites / 573 tests`，TypeScript、ESLint、Stylelint 全绿；OpenAPI 已重新生成。本地 M8 应用后又通过后端定向 `46 passed`、小程序 11 套件 `146 passed`、钱包对账、真实 API 221 项逐槽核验和微信开发者工具 HEX 直绘/零色样 PNG 请求。基线 head `4e745848...` / Run 34242753255 远端 8/8并保留 7 组 artifact；后续 M7→M8/Online no-op、内容保护和性能工具的 `tests/release` 为 `229 passed`、完整后端为 `2317 passed, 33 skipped in 125.31s`、`tests/performance` 为 `190 passed`，MARD 一次性 MySQL 并发/锁序为 `3 passed`。这些改动已由 `fa6fce05...` / Run 34281512196 在干净远端完成 8/8并保存 7 组 artifact。新增 disposable 完整 updater Job 与安全/清理测试后，本地 `tests/release` 为 `259 passed`、完整后端为 `2348 passed, 33 skipped in 126.83s`；Run 34288613644 已把真实 Job、其他八个现有 Job 和 artifact/cleanup 门槛完整跑成 9/9。没有新增直接依赖；`@tarojs/service@4.2.1` 的传递 Joi 已在兼容范围内由 lockfile `17.13.4` 提升至 `17.13.7`，消除两条新公开的 Low 公告且不扩大既有 npm 审计例外。
- 2026-09-08 已完成本地探索性 `2 核 / 4GiB / 聚合 5Mbps` 容量探测：当前工作区原生 ARM64 临时镜像运行于隔离 SQLite M8/Redis、单 Uvicorn worker 和 Nginx/TBF 栈，三个服务共享 CPU `0-1`、内存上限合计 4GiB。5/10 个每次间隔 0.4–0.6s 的快速浏览用户分别为 `9.55/19.12 req/s`、P95 `30.42/33.98ms`、0 错误，10 人只用 `0.549Mbps` 与约 10.73% 的两核容量；5/10 个持续 221 色详情请求均约 `57.2 req/s`，出口稳定 `5.000–5.001Mbps`，P95 `104.50/191.22ms`，0 错误/丢包/OOM/重启，瓶颈明确为出口而非 CPU/内存。当前图片仅 77–583 bytes，SQLite 只读、本机 ARM64 和单轮 30 秒结果不得外推生产 MySQL、真实 WebP、HTTPS/公网 RTT 或云主机发布容量；后续复用按 `docs/09_release/capacity_load_test_runbook.md` 执行，当次证据见 `docs/09_release/reports/local_2c4g_5mbps_load_test_2026-09-08.md`。
- 2026-09-09 又按新版工具在 MySQL 8.0.46/M8 上执行 A/B/C/D、5/10 VU 共 12/12 个 Profile，五个稳态容器共享 `cpuset=0-1`、禁用 swap 的上限合计 4096MiB，唯一出口为 5Mbps TBF。`73,027` 个请求均成功，150 个真实本地写旅程与最终订单/库存/钱包/Audit 对账通过；gzip 色板、认证浏览、C v3 的 221 PNG 冷/热页和 D 写链路在 5/10 VU 均通过。唯一失败是 10 VU 持续请求 51,063-byte 未压缩色板：出口 4.992Mbps、428 drops、P95/P99 1,510/2,442ms，故完整探索轮严格为 `FAIL`；gzip 后 10,023 bytes、减少 80.371%，同一 10 VU 为 271/290ms 且零 drops。结论是正常 5–10 人 gzip/API 路径有余量，未压缩大 JSON 的连续突发会先耗尽 5Mbps；该 dirty-tree、单轮 ARM64 Docker 包络不等同于完整 4GiB 主机或 candidate-pre/公网/真机证据。详见 `docs/09_release/reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md`。
- 当前仍为 **No-Go**：Gate A 权威成功点仍为 M7 Runtime `73dca350...` / Backup `20260908t021224z`；M8/M9 尚未应用。当前仓库已把受控升级器扩展到 M7→M8→M9，并加入 30 桌 bootstrap/replay、M9 Schema/约束、table reconcile/sweep、常驻 sweeper 和 Runtime API 核验；但只有当前候选自身 CI 全绿后才能开始当次持久 Backup/独立 Restore、停写、apply、紧邻 plan replay、app-up 与数据后 Backup/Restore。历史 Run 34288613644 只证明 M8 updater 基线，不能替代 M9 候选或持久状态。真实 Origin、`release_eligible=true` RC、iOS/Android 真机、微信官方小程序码、upload/gray/release 和真实微信支付仍未完成或未授权；共享、预发布和生产环境未触碰。
- Phase 9.5 **不依赖备案的仓库实现已于 2026-09-02 完成**：后端已实现服务端微信 code2Session、微信首次普通用户创建、既有账号显式绑定/冲突/解绑、外部标识独立 Pepper HMAC、Refresh family 原子轮换与重放撤销、认证限流 fail-closed、账号注销匿名化和脱敏安全事件；密码/微信既有身份登录及微信首次注册唯一冲突收敛均锁定并复验 User，`last_login_at` 与登录 Audit 同事务，签发后再锁定确认 `auth_version/status`，不一致时只撤销本次新 family。注销以数据库 commit 为权威成功点，commit 后 Redis family 清理为 best-effort；失败仍返回成功，`status/auth_version` 保持会话失效，并记录不含 Token/JTI 的高优先级安全事件供运维重试清理。Order 创建也先锁后复验 NORMAL 普通 USER，封闭注销竞态。小程序新增显式 password/wechat 模式和 refresh 双 Token 替换。MySQL 迁移 3 已离线生成、在可销毁 MySQL 验证，并已随当前持久 Gate A 的 M3→M7 受控升级应用；共享、预发布和生产环境不因该证据自动迁移。`ImageStorage` 与 Secret 文件注入只完成供应商无关边界；真实 AppID 真机、集中 Secret Manager、告警送达、对象存储和微信隐私材料仍是 Gate B 阻断，未连接微信后台或创建云资源。权威边界见 `docs/09_release/phase95_public_security_baseline.md`。
- 前端 **Phase 9.1–9.3 已于 2026-08-31 Complete；下一步为 Phase 9.4 微信内部测试版**：Phase 9.3 最终候选 `136a8bd...` 的 GitHub Actions Run 33408135841 为 8/8 success，53 项发布工具契约通过。Run ID `20260831t221625` 在唯一、可销毁的双 MySQL 8.0.46、认证 Redis 8.0.1、短期 CA/Nginx、非 root App 和独立 Source/Restore 图片卷中完成 DR-01～DR-07、DR-09 服务端部分：空库/旧数据迁移、opening balance、数据库与图片独立恢复、MySQL DDL 部分失败恢复、MySQL/Redis Readiness 故障与恢复、Bootstrap 首次/重放/唯一 Audit/凭据轮换、32 请求真实 HTTPS 纵向 Smoke 和优雅重启均通过。演练促成 Python 基础镜像标签、Compose `--env`、合成 Order No、internal/edge 网络四项修复及回归测试；R-004/R-006/R-011 已关闭。Compose containers/networks/volumes、端口、短期 Secret/CA/证据目录和任务 App 镜像已删除，既有开发 Redis 未接管。报告见 `docs/09_release/reports/phase93_rehearsal_2026-08-31.md`。微信合法域名、真实 Origin/证书、iOS/Android 真机 DR-08 与 Gate A 决策仍属于 9.4；未授权上传、分发、提审或发布。
- 前端完成**阶段 2：四端 Taro Spike**（2026-08-15）：Taro 4.2.1 + React 18.3.1 + TS 5.9.3 strict + Webpack 5.91.0 + NutUI 2.7.15 + Jest 29.7.0 在 weapp/alipay/tt/h5 四端生产构建全部通过；`Taro.request`/Storage/上传适配层与 Jest + Taro Test Utils 链路已验证（13 项测试）。产物固定输出 `dist/<TARO_ENV>`，生产包注入 `TARO_APP_APP_ENV`/Origin 且无 localhost 泄漏。关键发现：Taro 只替换字面量 `process.env.TARO_APP_*`；测试工具需 `legacy-peer-deps` 并 mock `@tarojs/router`；NutUI 桶导入会把整库打入包（h5 入口 485 KiB），正式工程必须按需引入；H5 CORS 实测确认后端未配置白名单。Spike 结果已回写架构文档 §4.1、ADR-003/ADR-005、多端与测试策略；ADR-003/ADR-005 已 Accepted。总体架构仍为 Draft（正式工程已落地，待批准），不得把 Spike 与文档规划误报为已交付业务能力。
- 前端完成**阶段 3：正式 `miniapp/` 工程创建与依赖复核**（2026-08-15 创建，2026-08-20 复核）：Taro 4.2.1 + React 18.3.1 + TS 5.9.3 strict 正式工程已落地，包含四端构建、环境配置、Jest/ESLint/Stylelint 与金额格式化测试。官方 npm registry 复核确认 Taro 4.2.1 仍为最新版；16 个 Spike 遗留 extraneous 包已清理，`solid-js@1.9.15` 显式补齐 H5 peer，非目标平台插件、Generator 和未启用 Git Hook 依赖已移除；`npm ls` 零错误。生产 Origin 必须是无路径/凭据的 HTTPS，并拒绝本机地址。正式工程尚未引入 NutUI；基线与认证链路均已提交。
- 前端完成**阶段 4 基础：OpenAPI 类型 + HTTP Client**（2026-08-20）：`scripts/export_openapi.py` 从真实 FastAPI 导出 45 paths / 99 schemas，`openapi-typescript@7.13.0` 生成 immutable/alphabetized 类型并支持 `--check` 漂移门槛；`miniapp/src/api/` 已实现 Taro JSON Transport、统一信封 Runtime Guard、Query/Bearer、取消、Network/Timeout/HTTP/Business/Contract/Session 错误、code `1006` single-flight refresh 与一次受控重放。普通写请求/超时不自动重试，empty-body PATCH 不添加 data。前端共 4 套件 / 19 用例通过，其中 14 项覆盖 API/环境；四端生产构建通过，H5 空应用入口 281 KiB 超过 244 KiB 建议线。官方审计仍有 10 项生产风险来自 Taro 4.2.1 H5 上游链，强制修复会破坏性降级，公开发布前必须跟踪重审。
- 前端完成**阶段 5 主链：账号密码登录纵向链路**（2026-08-20）：auth/users 成功响应已补齐精确 `SuccessResponse[T]` OpenAPI，User `IntEnum` 内部表示与字符串 HTTP 输出的 Schema 已对齐；当前导出为 45 paths / 108 schemas。`AuthApi` Endpoint、逐字段 Runtime Guard、Taro Storage Port/Adapter、可注入 Session Manager、`initializing/guest/authenticated/error` AuthContext、启动 refresh + `/users/me` 验证、受控登录表单、首页守卫和登出均已实现。Context 不暴露 Token，Storage 不保存密码，损坏缓存删除，并发 refresh single-flight。前端共 7 套件 / 29 项、后端完整 SQLite 套件 1425 项（另 9 项可选 MySQL 跳过）、静态检查与四端生产构建通过；H5 入口为 327 KiB。微信开发者工具连接本地 FastAPI + SQLite + Redis 的真实账号密码 Functional 已通过：错误/正确/禁用账号、`user/admin/super_admin` 展示、Storage、重启 `/users/me` 恢复、登出、`expiresAt` 主动 refresh、code `1006` 被动 refresh 与无效 refresh 清理均成功；未记录完整 Token。该结果不等于真机、H5、正式 HTTPS/合法域名或微信登录通过。
- 前端完成**阶段 6：公开 Product 列表、筛选与详情**（2026-08-22）：`ProductApi.listProducts()` 使用生成 Query/Page/Item 类型并对 `unknown` 响应运行时校验/白名单投影，公开请求不附带 Token；唯一 Asset Resolver 补全 `/uploads/...`；列表 Feature 负责 `page_size=10`、类型/keyword、防抖、下一页、四态和 sequence 迟到响应隔离。卡片按服务端类型进入单一详情页；Experience 只选择真实完整 Option 并同步价格/专属图片，Kit 只展示价格与库存快照。完整 Jest 11 套件/70 项、typecheck、ESLint、Stylelint、OpenAPI 漂移和四端生产构建均通过；后端完整 SQLite 套件 1442 项通过，9 项显式隔离 MySQL 门槛跳过。H5 入口保持 327 KiB、app JS 245 KiB，保留 244 KiB 性能建议与 `[hash]` 上游警告。2026-08-22 微信开发者工具已通过游客、Content、相对图片、第二页、筛选/组合搜索、Empty、Error 恢复、登录/退出后继续浏览、Experience/Kit 详情及多配置 Option 切换。`python -m app.tasks.product_functional_seed` 严格限定 development + 仓库内 SQLite/图片目录 + 双显式确认 + 启用 ADMIN 以上操作者，通过正式 Product Service/Validator/审计/图片存储生成 7 Experience、6 Kit、13 条 Online Product 和 21 张相对图片；专用多配置 Experience 有两个不同组合、价格与像素配色的带图 Option。17 项隔离测试通过；当前开发库最后两次执行分别为 `created=1 / skipped=12 / repaired_images=0` 与 `created=0 / skipped=13 / repaired_images=1`，21 个文件均由 Windows `System.Drawing` 独立解码成功。
- 前端 Phase 6 已加入 Product type 筛选与 keyword 防抖搜索：`all | experience | kit` UI 字面量联合类型中，all 省略 Query，其余映射 `product_type`；类型立即查询，受控 keyword 在 300ms 后 trim，纯空白省略。筛选变化重置第 1 页，下一页保留组合条件，sequence token 继续隔离旧查询迟到响应。
- 2026-08-22 Phase 6 最终门禁已通过：typecheck、11 套件/70 项 Jest、ESLint、Stylelint、OpenAPI 漂移、weapp/alipay/tt/h5 生产构建与 1442 项后端 SQLite 测试均为退出码 0；9 项可选 MySQL 门槛按显式配置跳过。首次 Node 包加载受 Windows 文件扫描影响异常缓慢，最小 TypeScript 冷加载 86.7 秒、热加载 0.7 秒；结论均来自真实退出码，不能因长时间无输出提前判断。
- 前端 **Phase 7.1 本地购物车代码与自动化已完成，微信 Functional 待验证**（2026-08-22）：`CartItem` 为 Experience/Kit 判别联合，真实 Option/null 在编译期固定；`CartStore` 使用 `pinkdoohub.cart.v1`、unknown Runtime Guard、白名单重写、坏数据清理、10 Item/99 quantity 边界、相同组合合并和 Promise 队列串行 mutation。Storage 成功后才发布 Context 状态；设备级游客 Cart 不随登录/退出清除，且不保存身份或个人资料。详情页已接入加入/查看入口，Cart 页实现初始化/错误/空/内容、数量和移除；本地价格只预览，`buildOrderItems()` 只映射 Product/真实 Option/quantity。新增 3 套件/17 项，完整前端为 14 套件/87 项；typecheck、ESLint、Stylelint、OpenAPI 漂移和四端编译均通过，后端完整 SQLite 1442 项通过、9 项隔离 MySQL 门槛跳过。H5 入口 334 KiB、主 JS 251 KiB，保留 244 KiB 建议与 `[hash]` 警告。
- 前端 **Phase 7.2 确认页与 Order 创建已完成**（2026-08-24）：`OrderApi.createOrder()` 以认证 POST `/api/v1/orders`，请求仅投影 items/可选 remark，Experience 必须带真实 Option，Kit 省略 Option；响应逐字段 Runtime Guard 后只返回 `OrderDetailOut` 白名单快照。`OrderSubmissionStore` 冻结一次提交的 Cart/request、合并重复点击，并用 `idle/submitting/succeeded/failed/unknown` 区分明确失败和网络结果未知；network/timeout/cancel/contract/5xx 都不自动重试。Guest 登录 redirect 仅允许确认页，成功后 `reLaunch` 返回。结果页只显示后端订单号、状态、金额与 Option 快照；成功后按提交快照保守对账 Cart，Storage/冲突只提示本地警告，不把服务端成功降级。完整前端 19 套件/130 项、typecheck、ESLint、Stylelint、OpenAPI 漂移和四端 production build 均通过；真实 FastAPI + SQLite Order 创建/边界/事务失败 34 项及完整后端 1445 项通过，9 项 MySQL-only 门槛按配置跳过。2026-08-24 用户确认 Phase 7.1 剩余有库存 Kit UI 复测及 Phase 7.2 微信 Functional 全部通过；该结论不代表真机/H5。H5 入口 343 KiB、主 JS 259 KiB，保留体积与 `[hash]` 上游警告。
- 前端 **Phase 7.3 我的订单、详情与 Pending 取消工程实现及微信 Functional 均已完成**（2026-08-24）：`OrderApi` 新增认证列表/详情/cancel、Query/响应白名单和 Page/ListItem/Status Runtime Guard；cancel 不设置 body 且只接受 cancelled 结果。列表固定 `page_size=20`，支持四状态筛选、四态、下一页、重复加载保护和 sequence 迟到响应隔离；详情路由只接受正安全整数，只展示服务端 Order Item 历史快照，40411 不区分不存在/他人资源。取消使用 `idle/submitting/failed/unknown/succeeded`，进行中 Promise 合并，network/timeout/cancel/contract/5xx unknown 不自动重发，成功后 GET 详情，刷新失败不推翻成功，40921 后按服务端状态收敛。7.2 创建成功与 unknown、首页均可进入“我的订单”；登录 redirect 白名单只增加固定订单列表。Phase 7.3 定向 Jest 8 套件/61 项、当时完整前端 25 套件/172 项、Order HTTP 53 项及完整后端 1445 项通过；2026-08-24 用户确认人工清单第 1–9 项通过，2026-08-25 又确认旧用户详情 cancel 在竞争客户端先变 Paid 后收到 40921、重新 GET 收敛且不重发，第 10 项竞态通过。
- 前端 **Phase 7.4 ADMIN 订单查询与人工 Paid/Completed 工程实现及微信 Functional 均已完成**（2026-08-24；商品名称筛选于 2026-08-28 增补并通过 Functional）：`OrderApi` 提供 ADMIN 列表/详情/paid/complete，8 个 Query 严格投影；`product_name` 按 `order_items.product_name` 下单快照部分匹配，Order ID 子查询确保多 Item 命中时仍是一单一行、完整 `item_count` 和正确 `total/pages`，不关联当前 Product。管理响应只增加 `user_id/user_nickname`，两个 PATCH 无 body 且校验目标状态。`admin` 分包提供状态/订单号/历史商品名/用户/UTC 日期筛选与服务端分页；结束日转次日 UTC 排他上界。首页只为 ADMIN+ 显示入口，列表/详情在角色确认后才挂载 Hook；后端 ADMIN+ 仍是授权事实。详情只派生 Pending → Paid、Paid → Completed，终态无按钮；命令 Promise 合并，unknown 不重发，成功/40921 后 GET 权威详情且 GET 完成前保持 submitting，paid/complete 不改库存。H5 保留体积、React Test Utils act 与 `[hash]` 上游告警。商品名增量改变 OpenAPI Query/生成类型，但不改变路径、响应、数据库 Schema、迁移或依赖。
- 前端 **Phase 8 已冻结分阶段规划，Phase 8.1 ADMIN Product 只读管理已完成**（2026-08-25）：`AdminProductApi` 使用认证 Client 与独立管理 Runtime Guard，列表支持 type/status/keyword/include_deleted、服务端分页和迟到响应隔离；Experience/Kit 管理详情允许 Draft 空封面/图片/Option/dimensions、null description 及逻辑删除记录，同时严格校验 Enum、金额、UTC、库存和聚合维度。首页只为 ADMIN+ 显示入口，普通用户在 Hook 挂载前拦截，登录只返回固定管理列表，动态详情校验正安全整数 ID + 类型。页面只读，不提前实现创建、编辑、删除、Option、图片、状态、库存或审计。定向前端 8 套件/39 项、完整前端 37 套件/240 项、typecheck、ESLint、Stylelint、OpenAPI 漂移、四端 production build、Product API 52 项及完整后端 1445 项均通过（9 项 MySQL-only 跳过）。`[LOCAL-ADMIN-FE]` 正式 Service Seed 补齐 Draft/逻辑删除样本后，用户确认全部微信 Functional 通过。首页账号操作区按真实截图调整为账号信息和可换行按钮组，按钮文字保持单行。后续按 8.2–8.9 逐步开放 Product 基本写入、Option/Kit 价格、图片、readiness/状态、Inventory、既有 Order 整合、Audit/User 和最终 Review。
- 前端 **Phase 8.2 ADMIN Product 基本写入工程、自动化与微信业务 Functional 均已完成**（2026-08-26）：`AdminProductApi` 新增 Experience/Kit 分型创建、基本信息 PATCH、无 body DELETE 与严格 Runtime Guard；创建表单不混淆 Experience Option 价格和 Kit 价格，Kit 不发送 stock。编辑从管理详情计算真实 diff，区分字段缺失与 `description: null`；Online/已删除禁用只作即时反馈，40903/40904/40905 仍由后端裁决。统一 mutation Hook 合并进行中 Promise，以 `failed/unknown` 区分明确拒绝和无法证明未提交的结果，unknown 不自动重发。管理列表、详情、创建、编辑页面均在 ADMIN+ 守卫后挂载 Hook；Guest 仍只回固定管理列表。定向 7 套件/56 项、完整前端 41 套件/288 项与 TypeScript strict 已通过。用户确认业务 Functional 全部通过。管理页白色图案和登录 `_` 闪烁在该阶段结束时仍为延期项，后于 2026-08-29 完成专项复测并关闭。没有后端 API、数据库、OpenAPI Schema、依赖或版本变化。
- 前端 **Phase 8.3 ADMIN Experience Option 与 Kit 价格管理工程和自动化已完成，可验收微信 Functional 已通过**（2026-08-26）：管理详情新增分型“价格与配置”入口；Experience 支持 Option 新增/恢复、真实差异 PATCH 与无 body 逻辑删除，Kit 只修改 price 且库存只读。Endpoint 从 unknown 严格校验 Option Base/完整响应、删除结果和 KitPriceOut；POST 恢复只信任服务端返回的原 Option ID。独立 mutation Hook 合并进行中 Promise，network/timeout/cancel/contract/5xx unknown 不自动重发，成功或核对均重新读取类型专属管理详情。Online/已删除页面禁用不替代 40001/404xx/40903/40905/40911/40912 后端裁决；历史订单继续展示 Order Item 价格与 Option 快照。定向 5 套件/48 项、完整前端 43 套件/306 项、静态检查、OpenAPI 漂移、四端 production build、Product API 52 项和完整后端 1446 项均通过（9 项 MySQL-only 跳过）；用户确认除改价前后订单快照外的微信 Functional 全部通过，该联动场景现已具备 Phase 8.5 上下架界面并纳入 8.4–8.5 合并 Functional。H5 主 JS 278 KiB、入口 362 KiB，保留既有体积与 `[hash]` 告警。未改变后端、数据库、OpenAPI 生成物、依赖或版本。
- 前端 **Phase 8.4–8.5 ADMIN Product 图片与上下架/readiness 工程、自动化、四端构建及微信 Functional 均已完成**（2026-08-26 实现，2026-08-28 验收）：`ApiClient.uploadFile()`、`TaroFileUploadTransport` 与 `ImagePickerPort` 隔离 multipart/选图平台边界，上传复用 Bearer、统一字符串信封、code `1006` single-flight refresh 和一次重放且不手工设置 boundary。管理端开放 Product 公共图、Option 专属图的上传/排序/封面/逻辑删除，以及 online/offline empty-body PATCH；前端 2 MiB/MIME 预检不替代后端签名、内容、归属和封面唯一校验。独立 lifecycle mutation Hook 合并进行中 Promise，unknown 不自动重发并重新 GET 核对；详情同步门闩防不同命令交叉提交。上架完整、有序展示 `42201.data.issues` 并保留未知原文，不复制 ProductValidator；下架不修改配置、图片、库存或历史订单。微信 Functional 包含 Phase 8.3 延期的旧/新订单价格快照，用户确认全部通过。Phase 8.2 管理页白色图案与登录 `_` 闪烁在本阶段结束时仍为延期项，后于 2026-08-29 完成专项复测并关闭。
- 前端 **Phase 8.8 Product Audit、ADMIN User 与 8.9 当时管理端范围 Review 工程、自动化及微信 Functional 全部完成**（2026-08-28）：Product Audit 复用既有 ADMIN+ 分页端点，支持逻辑删除历史并用目标 ID 绑定的 Runtime Guard 重建白名单；ADMIN User 后端先收口严格 `status/role` Query、typed Page、稳定倒序、Mapper 与组合根，禁用改为行锁下状态/审计同事务且幂等。禁用后旧 access 立即返回 `1005`，旧 refresh 首次 `1005` 并撤销，客户端受保护 JSON/上传遇到 `1005` 清理 Session 且不 refresh。前端新增固定 `/admin/pages/users/index`、动态 Product Audit 页、首页/详情入口、筛选/分页/禁用 unknown 状态；Guest/普通用户在 Hook 挂载前拦截，User 列表不含 phone/avatar/password，不提供不存在的详情/启用/头像按钮。OpenAPI 为 45 paths/109 schemas；当时完整前端 54 套件/350 项、完整后端 1465 项通过（9 项 MySQL-only 跳过），TypeScript/ESLint/Stylelint/类型漂移及四端生产构建均通过。用户进一步用 Swagger 独立 ADMIN Session 验证禁用账号旧 refresh 首次 `1005`、重放 `1006`，旧 access 请求触发本地 Session 清理。管理页白色图案和登录 `_` 闪烁在本阶段结束时继续延期，后于 2026-08-29 完成专项复测并关闭。
- 前端 **Phase 8.6 Kit Inventory 管理工程、自动化、四端构建与微信 Functional 全部完成**（2026-08-28）：`InventoryApi` 消费既有三个 ADMIN+ Endpoint，严格投影 adjustment/header/query，并以 Runtime Guard 校验库存算术、四类 transaction、三类 source、operator/order 元数据、UTC 与分页，响应不输出内部 key。`ApiClient.requestWithMeta()` 向后兼容保留最终 HTTP status，明确 201 首次/200 重放。调整 Hook 以冻结的 product/payload/key 为业务意图，双击合并；network/timeout/cancel/contract/5xx unknown 不自动重发，用户安全重试复用完全相同的 key/request，明确失败或成功后新意图生成新 key。新增动态 Kit 库存页与固定全局流水页，支持 Product/source/type/UTC 筛选和服务端分页；Guest/普通用户在 Hook 前拦截，动态页登录返回固定管理商品列表，Draft/Offline/Online Kit 可调整，逻辑删除不挂载 Inventory Hook。完整前端 60 套件/375 项、完整后端 1465 项通过（9 项 MySQL-only 跳过），静态检查、类型漂移和四端构建通过；三端 admin 分包约 167 KiB，H5 主 JS 283 KiB/入口 370 KiB，保留既有告警。用户确认 Phase 8.6 微信开发者工具 Functional 全部验证完成并通过。没有后端、OpenAPI、数据库、迁移、依赖或版本变化。
- 前端 **Phase 8 延期视觉兼容问题已关闭**（2026-08-29）：管理页白色图案最终定位为白色卡片样式直接挂在原生 `Form` 上引发的微信渲染异常。库存流水、管理商品、Kit 管理库存和管理订单改为外层 `View` 绘制卡片、内层透明 `Form` 只处理提交；无提交语义的商品创建、编辑、Experience Option 与 Kit 价格配置容器直接使用 `View`。全项目审计确认登录/注册卡片原本已由外层 `View` 绘制，其余管理页没有同类结构风险。登录 `_` 闪烁后续无法复现并由用户确认消失，不把早期 `alwaysEmbed` 尝试单独表述为确定根因。Taro 微信 development build、局域网 API 产物检查及用户微信/真机复测通过；没有后端/API/OpenAPI、数据库、迁移、依赖或版本变化。
- **Product JPEG 导出尾部兼容已实现**（2026-08-27）：真实微信导出 JPEG 在标准 `FF D9` 后统一附加 `17 4D A1 01 00 00 00 00 + JPEG 本体 16-byte MD5`，旧存储层强制 `endswith(FF D9)` 导致 19/19 可解码样本误报 `42221 invalid_image_content`。`LocalImageStorage` 现仅在 JPEG 头尾、固定前缀和摘要全部匹配时剥离 24 字节并保存规范化 JPEG；任意尾随、错误摘要、伪造前缀和 MIME 不匹配继续拒绝，原始文件仍受 2 MiB 限制。MD5 只识别导出格式，不作为安全摘要。存储与真实 multipart API 定向 28 项、`D:\pinkdooPics` 真实样本 19/19 和完整后端 1450 项均通过，9 项 MySQL-only 跳过；临时输出已清理。无 API Schema、错误码、数据库、迁移、依赖或版本候选变化。
- 前端 **账号密码注册补漏工程与微信 Functional 已完成**（2026-08-25）：`AuthApi/AuthContext` 接入现有无认证 `POST /auth/register`，注册页实现 username/password/confirm/nickname/phone 受控校验、同步 ref 防双击、1001/1007 提示、POST unknown 不重试及成功后主动登录；登录/注册双向保留固定白名单 redirect，密码不进入 URL/Storage，注册成功不伪造 Session。完整前端现为 38 套件/255 项；用户已确认普通注册、字段/唯一性、快速连点、结果未知、密码隔离及订单列表 redirect 全链路通过。审阅发现 username 字符集旧文档与实际 Pydantic/OpenAPI 不一致，API 文档已同步当前无 pattern 的事实，客户端不额外限制。
- Phase 7.1–7.4 已收口。H5 等后端 CORS allowlist 后验证。Order create 仍无客户端幂等键；真实微信支付 Provider 仍未实现，是明确集成/发布缺口。微信登录、refresh 轮换及登录/注册限流已由 Phase 9.5 仓库实现，但真实 AppID/域名/真机与持久环境启用仍受 Gate B 控制。
- 当前代码版本候选仍为 **v0.6.0（尚未发布）**；Phase 4.1/4.2/4.3、Wallet/Payment/Refund v1、Reservation N1、M6/M7/M8 与 M9 二维码开台均已完成仓库实现。M9 当前等待自身 CI 与持久 Gate A M7→M8→M9 受控验收；Gate A 在本文更新时仍为 M7。
- Product 业务规则、数据库设计、API 契约和 Validator 对外契约均已完成；Product API 文档已通过 Phase 4.1 最终 Review，并收口为 v1.0 Implemented。
- 既有 Product 字符串 Enum、字段常量、Schema 与测试已实现；M6 新增 KitKind/颜色库存结构，M8 新增 `swatch_hex` 正式颜色字段，具体实现和测试状态必须以实际代码与 changelog 为准。
- `app/schemas/product.py` 负责请求体和查询参数；`app/schemas/product_response.py` 负责响应白名单。
- Product、ExperienceOption、ProductKit 与 ProductImage 的既有链路及 21 个端点保持 Implemented。M6 新增 BeadColor/ProductKitColor，并扩展同一 Product Repository/Service/Validator/Mapper 与路由；M8 又把 HEX 纳入同一层级和可售性边界，颜色库存不回流 Product stock 写端点。现有单图链只服务 Product/Option 图片；BeadColor 的可选全局 URL 只作实拍/迁移回退，数字色块以 `swatch_hex` 为权威。
- MySQL 8+ M0–M9 迁移链已离线生成；M9 新增四张桌台表、四维当前占用 UNIQUE、RESTRICT 历史外键及 30 桌受控 bootstrap。M8 历史 MySQL/CI/updater 证据继续有效，但不能替代 M9 当前候选的 CI 或任何持久环境迁移。Gate A 在本文更新时仍为 M7；M8/M9 均未应用 Gate A、共享、预发布或生产数据库。
- Phase 4.3.1–4.3.12 Inventory 契约、领域/Schema、Model/数据库设计、MySQL 增量迁移、Repository、管理员调整、Kit/混合订单创建扣减、Pending 取消恢复、查询 Service/Mapper、三个 ADMIN+ API、发布门槛和最终 Review 均已完成。Order 创建和取消分别拥有 deduction/restore 的稳定集合锁、批量余额/流水、Order/Audit/重载外层事务；状态机与 restore UNIQUE 共同防止重复恢复。指定 Kit 查询验证资源聚合，全局查询把 Product ID 仅作为筛选；Mapper 对预加载展示字段显式投影并保持零 SQL/零修改。调整 API 首次返回 201、幂等重放返回 200。真实 MySQL 回填、Repository smoke、竞争/1205/EXPLAIN、MySQL HTTP smoke 与完整 HTTP 矩阵均已通过；旧直接设置库存端点和 Kit 创建 stock 输入已移除。Product Kit 详情响应的库存上限已与 Inventory `999999` 契约一致，数据库文档的旧 Kit 规划描述已清理。
- 2026-08-14 的 MySQL smoke 曾发现 Order 阻断：`OrderStatus` 直接写普通 `SmallIntField` 会被 asyncmy 编码成 `OrderStatus.*` 字符串并报 1366。现已将 Model Pending 默认值、Repository 状态更新和状态筛选统一转换为原生整数，并在全新 MySQL 8.0.46 上通过默认创建、Pending/Paid 筛选及状态更新回归；物理 Schema 和 API 语义未变化，无需迁移。
- ExperienceOption 配置组合在全历史范围内唯一；再次创建相同已删除组合时恢复原 Option ID、更新当前价格并保留图片关联，不创建第二条版本记录。

---

## 3. 枚举速查

| 数据库 | API (string) | Python Enum |
|--------|--------------|-------------|
| `users.role` 1/2/3 | `"user"` / `"admin"` / `"super_admin"` | `UserRole` |
| `users.status` 1/2/3 | `"normal"` / `"disabled"` / `"deleted"` | `UserStatus` |
| `products.product_type` VARCHAR | `"experience"` / `"kit"` | `ProductType(str, Enum)` |
| `products.status` VARCHAR | `"draft"` / `"online"` / `"offline"` | `ProductStatus(str, Enum)` |
| `product_kits.kit_kind` VARCHAR(20)（本地 SQLite 与当前 Gate A M7 已应用） | `"fixed"` / `"color_selectable"` | `KitKind(str, Enum)` |
| `experience_options.day_type` VARCHAR | `"weekday"` / `"holiday"` | `DayType(str, Enum)` |
| `orders.status` 0/1/2/3 | `"pending"` / `"paid"` / `"cancelled"` / `"completed"` | `OrderStatus` |
| `inventory_transactions.transaction_type` VARCHAR(40)（M4 增加退款恢复；当前 Gate A M7 已应用） | `"opening_balance"` / `"admin_adjustment"` / `"order_deduction"` / `"order_cancellation_restore"` / `"order_refund_restore"` | `InventoryTransactionType(str, Enum)` |
| `inventory_transactions.source_type` VARCHAR(30)（当前 Gate A M7 已应用） | `"migration"` / `"admin"` / `"order"` | `InventorySourceType(str, Enum)` |
| `wallet_accounts.status` VARCHAR(32)（当前 Gate A M7 已应用） | `"active"` / `"closed"` | `WalletStatus(str, Enum)` |
| `wallet_transactions.transaction_type` VARCHAR(32)（当前 Gate A M7 已应用） | `"recharge"` / `"order_payment"` / `"admin_adjustment"` / `"refund"` | `WalletTransactionType(str, Enum)` |
| `payments.purpose` VARCHAR(32)（当前 Gate A M7 已应用） | `"order"` / `"recharge"` | `PaymentPurpose(str, Enum)` |
| `payments.method` VARCHAR(32)（当前 Gate A M7 已应用） | `"wallet"` / `"wechat"` / `"manual"` | `PaymentMethod(str, Enum)` |
| `payments.status` VARCHAR(32)（当前 Gate A M7 已应用） | `"pending"` / `"succeeded"` / `"failed"` / `"closed"` | `PaymentStatus(str, Enum)` |
| `refunds.status` VARCHAR(32)（当前 Gate A M7 已应用） | `"pending"` / `"succeeded"` / `"failed"` | `RefundStatus(str, Enum)` |
| `reservations.status` VARCHAR(32)（当前 Gate A M7 已应用） | `"pending"` / `"confirmed"` / `"rejected"` / `"cancelled"` | `ReservationStatus(str, Enum)` |
| `reservations.rejection_reason` VARCHAR(32)（当前 Gate A M7 已应用） | null / `"no_capacity"` | `ReservationRejectionReason(str, Enum)` |
| `reservations.cancellation_reason` VARCHAR(32)（当前 Gate A M7 已应用） | null / `"customer_request"` / `"store_closed"` | `ReservationCancellationReason(str, Enum)` |
| `table_sessions.status` VARCHAR(32)（M9 已实现） | `"awaiting_payment"` / `"active"` / `"closed"` | `TableSessionStatus(str, Enum)` |
| `table_sessions.close_reason` VARCHAR(32)（M9 已实现） | null / `"payment_timeout"` / `"time_expired"` / `"order_cancelled"` / `"order_completed"` / `"refunded"` / `"admin_released"` | `TableSessionCloseReason(str, Enum)` |
| Table Timer API phase（M9 已实现） | `"experience"` / `"grace"` / `"ended"` | `TableTimerPhase(str, Enum)`（API-only） |

> `duration_minutes` 和 `participants` 是开放正整数，不是 Enum。当前常用值不构成允许值白名单。

---

## 4. 错误码号段速查

| 模块 | 号段 | 已用 |
|------|------|------|
| 用户 | 1xxx | 1001-1015；认证限流另用 42901 |
| 商品 | 40xxx / 409xx / 422xx | 40001, 40021 / 40401-40406 / 40901-40905, 40911-40915 / 42201, 42221（M6 新增 40405-40406/40913-40915） |
| 订单 | 4041x / 4092x / 4223x | 40411 / 40921 / 42231-42234（M6 新增颜色不可用 42233、总额上限 42234；40922 已移除） |
| 库存 | 40031 / 4093x | 40031 / 40931-40933（M6 以 40031 区分 fixed/颜色库存端点） |
| Wallet/Payment/Refund | 4044x / 4094x / 4224x | 40441-40444 / 40941-40948 / 42241（40947 退款预留容量、40948 超退款窗口；M4 已进入当前 Gate A M7） |
| Reservation | 4045x / 4095x / 4225x | 40451-40452 / 40951-40953 / 42251-42255（N1 已实现；M5 已进入当前 Gate A M7） |
| QR Table Session | 4046x / 4096x / 4226x / 4296x | 40461-40463 / 40961-40966 / 42261 / 42961（M9 已实现） |

Reservation N1 速查：

- POST 只接受 `experience_option_id + reservation_date(YYYY-MM-DD) + start_time(HH:00/HH:30)`；手机号来自锁后的当前 User，缺失为 42254，且不快照。
- 上海当地今天至第 30 日、至少提前 3 小时、11:00–20:00、完整体验；每周固定店休默认周一并可由 ADMIN+ 更换，周一至周五仍按 weekday、周末按 holiday，不处理法定节假日/调休。`booking-options` 返回当前固定店休日及全部合法日期/时段，不表达空位。
- 同一用户/Option/开始时段可创建多条 Reservation；没有容量表、占座或同槽 UNIQUE，店员逐条人工确认/拒绝。POST 结果未知时先查列表，不自动重发。
- 四状态 pending/confirmed/rejected/cancelled；拒绝只允许 no_capacity，取消只允许 customer_request/store_closed。管理员在开始时刻及之后不能确认/拒绝，顾客 `now == start-3h` 仍可取消。
- 单日店休只允许今天或未来且不能是当前固定店休日；首次 PUT 201、重放 200。固定店休更换与命中新星期的未来活跃预约取消原子提交，旧星期立即恢复、单日店休不变、历史不复活。单日 DELETE 不恢复预约，无店休时 40452。
- 管理列表只返回服务端掩码当前手机号，详情才返回当前完整手机号；User 注销时未来 pending/confirmed 且 `scheduled_end_at > now` 使用现有 1015 阻断。
- M5 两表为 `store_business_days` 与 `reservations`；四个历史 FK 全 RESTRICT，排期存 UTC，完整 Option 值存快照。N2 主动通知保持 Deferred。

QR Table Session M9 速查（已实现）：

- 精确 30 桌 `T01`–`T30`；二维码为公开随机定位符，扫码解析不等于占台授权。
- 开台要求本人 Pending 订单至少一个 Experience；15 分钟内占台，超时只关 Session、不取消 Order，允许同一 Pending Order 后续重新绑定。
- 付款以 `Payment.succeeded_at` 同时启动全部 Timer；按 Experience 分钟精确分组，每组 `+10` 分钟。`quantity > 1` 不乘时长；Kit 不参与 Timer，纯 Kit 不开台。
- 最长 Timer 到期释放 Occupancy，Order 继续 Paid；取消/完成/全额退款/管理员释放在原事务内关闭整张桌台。
- 四张目标表为 `store_tables`、`table_sessions`、`table_session_timers`、`table_occupancies`。Occupancy 对 table/session/user/order 分别 UNIQUE，历史 Session 保留。
- 用户 API 已实现二维码解析、可选订单、创建、当前会话和订单最新会话；管理员已实现 30 桌、会话列表/详情、启停和应急释放。钱包 Table 页面通过可选 `Table-Session-No` Header 绑定精确付款意图。
- M9 必须在 M8 之后单独迁移/验收；运行时开关、迁移、页面和普通占位二维码工具均已实现。当前占位载荷为 `PINKDOOHUB_TABLE:v1:<token>`；微信官方小程序码、真实微信支付与 Reservation 绑定均不在 M9 首版。

Inventory Phase 4.3 + M6 契约速查：

- fixed 使用 `product_kits.stock`；color_selectable 使用各 `product_kit_colors.stock_units`，同一全局颜色在不同商品间不共享。每次变化写不可变流水，余额/流水必须同事务。
- 新建 Pending Kit/混合订单立即扣减；Pending 取消幂等恢复；支付和完成不再改变库存。
- 支持 Experience、fixed Kit、color_selectable Kit 混合订单；颜色每色一行，稳定锁序扩展到 Product/商品颜色，Order 创建/取消 Service 拥有外层事务并协调 Inventory Repository。
- 管理员调整为 ADMIN+ 的 `change + reason + Idempotency-Key`，允许未删除 Online Kit；余额范围 `0..999999`，reason trim 后 `1..256`。
- 旧 `PATCH .../stock` 与 Kit 创建库存输入已移除；fixed 与颜色库存分别使用明确的 Inventory 路径，路径和 KitKind 不匹配返回 40031。
- 流水类型冻结为 `opening_balance`、`admin_adjustment`、`order_deduction`、`order_cancellation_restore`、`order_refund_restore`；现有正库存生成期初流水，零库存不生成零变化流水。
- 用户库存不足不披露精确 available；自动事件和管理员重试均由 UNIQUE 幂等身份保护。
- MySQL 8+ 真实并发验证是 v0.6.0 发布硬门槛；Phase 4.3.11 的隔离实例门槛已通过且该次验证本身未写持久库，Inventory M2 后续已进入当前 Gate A M7；版本发布及其他持久环境迁移仍未自动发生。

Inventory Phase 4.3.2 实现速查：

- `app/common/enums/inventory.py` 现定义五种流水类型（含 `order_refund_restore`）和三种 source 类型，均为稳定字符串 Enum；常量集中在 `app/common/constants/inventory.py`。
- `InsufficientStock(40931)` 不包含 available；`InventoryBalanceExceeded(40932)` 只接受确实越界的调整上下文，颜色余额场景的 data 另含 `kit_color_id`，fixed 场景保持原形状；`InventoryTransactionConflict(40933)` 不输出 data。三者均继承 `ConflictException` 并由全局中间件映射 HTTP 409。
- `app/schemas/inventory.py` 实现 `InventoryIdempotencyKey`、`InventoryAdjustmentCreate`、`InventoryProductTransactionQuery` 与 `InventoryTransactionQuery`。写整数 strict；HTTP Query ID 接受十进制字符串；时间只接受 UTC；`source_id` 要求 `source_type=order`。
- `app/schemas/inventory_response.py` 实现余额、流水列表/详情和调整响应白名单，拒绝内部幂等键与隐私字段，并校验 before/change/after、流水方向和 source/operator 元数据一致性。

Inventory Phase 4.3.3 实现速查：

- `app/models/inventory_transaction.py` 关联 `products.id` 与可空 `users.id`，两者 `RESTRICT`；通用可空 `source_id` 不建多态 FK。`source_type`、稳定 `reason` 与内部 256 字符幂等身份均非空。
- 幂等键使用 `uidx_inventory_idempotency_key` 命名 UNIQUE；另有 Product、source、transaction type 与全局 `created_at DESC, id DESC` 分页查询索引。数据库设计与 DBML 已同步，对应 MySQL 迁移已在 Phase 4.3.4 完成。
- Model 校验变化量非零及库存闭区间；before/change/after 等式与类型/source 组合由已实现的 Service 保证，当前不新增跨方言 `CHECK`。流水继承 BaseModel 的 `updated_at` 技术字段，但没有业务更新/删除入口且 API 不输出。

Inventory Phase 4.3.4 迁移速查：

- `migrations/models/2_20260814104655_add_inventory_transactions.py` 使用 `AERICH_MYSQL_VERSION=8.0` 离线生成，人工移除 `IF NOT EXISTS` 并声明 `RUN_IN_TRANSACTION=False`；已在一次性 MySQL 8.0.46 完成真实升级/降级/带数据再升级，未 fake，并已作为 M2 存在于当前 Gate A M7。其他持久环境仍须各自受控执行。
- 升级先建表，再按 Product ID 升序为 `stock > 0` 写 `opening_balance`；使用 UTC 微秒时间、稳定原因和 `inventory:opening:product:{product_id}`，不修改余额、不为零库存写流水、不静默忽略冲突。
- MySQL DDL 隐式提交使建表与回填非原子；执行必须停写、扫描 `0..999999`、备份、预演并核验。downgrade 删除全部流水但不重算余额，是需单独授权的数据破坏操作。

Inventory Phase 4.3.5 Repository 速查：

- `get_kit_for_update()` 与 `get_kits_for_update()` 必须使用调用方连接和 `select_for_update()`；集合锁去重后通过单条 SQL 按 `product_id` 排序，不循环查询。
- `update_stock()` 只保存 Service 给定最终余额；`create_transaction()` 服务单条管理调整，`bulk_create_transactions()` 服务多 Kit 自动事件。Repository 不计算 after、不判断不足、不捕获幂等唯一冲突。
- 幂等读取和详情重载支持同一未提交连接；分页支持 Product/type/source/UTC 时间范围，稳定倒序，并预加载 operator、一次批量补齐 Order 编号。含 Order source 的分页固定最多三条 SELECT，不随流水数增长。

Inventory Phase 4.3.6 管理调整 Service 速查：

- `InventoryService.adjust_stock()` 依赖 `InventoryRepository`、`ProductRepository` 和共享 `AuditLogService`；它拥有管理员调整事务，不调用 ProductService，也不直接操作 Model。
- 用例先锁 ProductKit，锁后区分 Product 不存在/删除/非 Kit/扩展缺失并计算闭区间余额；余额、`admin_adjustment` 流水、`ADJUST_INVENTORY` Audit 和详情重载共享连接，任一步失败全部回滚。
- 内部身份为 `inventory:admin:adjust:{client_key}`。同 Product/change/规范化 reason/operator 返回首次已提交的原始流水与 after；任一维不同返回 40933；失败回滚不占 key。并发 UNIQUE 在退出失败事务后解析。
- 只重试 MySQL 1205/1213，整个用例每次使用全新事务、最多 3 次；其他 OperationalError/IntegrityError 保留原始根因。日志不输出原因或幂等键。
- `InventoryAdjustmentResult.is_replay` 已由 Inventory Router 用于区分首次 201/重放 200；Inventory 流水/分页/调整 Mapper 不依赖该 Service DTO。Order 创建扣减已由 4.3.7 直接协调 Repository 接入，不调用该 Service。

Inventory Phase 4.3.7–4.3.8 Order 库存生命周期速查：

- `OrderItemCreate.experience_option_id` 可省略/null；M6 增加 nullable `kit_color_id`。Service 强制 Experience(option 有/color 无)、fixed Kit(二者空)、color_selectable Kit(option 空/color 有)三态；响应颜色行保存 code/name/slot/10g 快照并派生总克重，其他行颜色字段全 null。
- ProductRepository 批量读取 Product、非空 Option ID 和 Kit 候选价格；事务内先锁定 User 并复验仍为 NORMAL 普通 USER，再创建 Pending Order，随后由 InventoryRepository 一次按 Product ID 升序锁定全部 Kit，并用同一连接重读 Product 状态。
- 锁后按请求顺序检查 Kit 扩展和余额；多 Kit 余额用一次 `bulk_update`、流水用一次 `bulk_create`。流水固定为 `order_deduction` / Order source / 下单用户 operator / `Order stock deduction`，key 为 `inventory:order:{order_id}:deduct:product:{product_id}`。
- Order、库存、流水、Items、`CREATE_ORDER` Audit 和详情重载原子提交；库存不足、审计或重载失败全部回滚。`40931` 不包含 available。纯 Experience 创建零 Inventory Repository 调用。
- 订单号 UNIQUE 冲突在任何库存锁/写之前发生并沿用新编号事务重试；MySQL 1205/1213 对完整写事务以同一候选快照/编号和全新事务最多尝试 3 次。`IntegrityError` 必须先于其父类 OperationalError 处理。
- 取消先锁 owner 可见 Order 并重检 Pending，再读取最小 Item 快照、稳定锁定 Kit、批量检查 `inventory:order:{order_id}:restore:product:{product_id}`，批量恢复余额/`order_cancellation_restore` 流水后提交 Cancelled/Audit/重载。
- 重复取消由状态机返回 `40921`；Pending 与已存在 restore 身份矛盾返回 `40933`，恢复越界返回 `40932`。MySQL 1205/1213 对完整取消事务最多尝试 3 次；支付和完成零库存调用。
- 阶段门禁 `40922 KitOrderingRequiresInventory` 已从常量、异常、导出、测试和当前文档注册表移除。真实 MySQL 竞争已由 4.3.11 验证。

Inventory Phase 4.3.9–4.3.11 查询、API 与发布门槛速查：

- 指定 Kit 查询先验证 Product/Kit 聚合身份；全局 Product ID 只筛选。Mapper 显式投影严格 Out Schema，只消费预加载 operator 与批量 Order 编号，零 SQL、零修改且不泄漏幂等键或用户隐私。
- `get_inventory_service()` 与三个既有 ADMIN+ fixed/全局路由已注册；M6 另增两个颜色子资源端点并扩展全局 kit_color_id 筛选。两类调整都要求严格 body/`Idempotency-Key`，首次 201、重放 200；旧 Product stock 路由和创建库存输入不恢复。
- Phase 4.3.11 在隔离 MySQL 8.0.46、真实 Aerich 0→1→2 上通过 9 项门槛：同/异 key、最后一件、反向多 Kit、同单取消、调整/下单真实等待、真实 1205 全事务重试、三类 EXPLAIN 和 MySQL HTTP 并发重放/查询。
- 完整 HTTP 矩阵另有 41 项，覆盖三端点 401/1006/403、资源/业务异常、严格 422、分页/筛选/Order source/UTC 与隐私。测试 fixture 强制回环、非 3306 和专用 Schema 前缀；实例销毁且未修改持久数据库。

Wallet/Payment/Refund v1 速查：

- 金额：单笔充值 `1.00..1000.00`，钱包余额 `0.00..1000.00`；资金写入只接受固定两位小数字符串，所有余额由 `WalletAccount.balance` 权威保存并配套不可变 WalletTransaction。ADMIN 正向调账必须保持 `调整后余额 + 尚可退款的钱包 Payment 敞口 ≤ 1000.00`；PAID 和完成未满 30 天的 wallet Payment 在 Refund succeeded 前占用敞口，未来真实充值也必须复用该校验。相同敞口也阻断账号注销，即使当前余额为零。
- 身份：新建普通 USER 建钱包；历史 backfill 仅补 NORMAL/DISABLED 普通 USER，历史 DELETED 可无钱包且不得补建。ADMIN/SUPER_ADMIN 不建钱包，调账、代客扣款和退款资金写入只能操作普通客户。六个用户侧 wallet/payment 端点共享 `get_current_customer`，在实时状态与 `auth_version` 校验后强制 `role=user`，staff 统一 403；管理端订单资金事实只读查询仍可查看任意管理端可见订单。disabled USER 禁止主动充值/消费，但 ADMIN+ 人工纠错和法定义务退款仍允许；deleted USER 禁止资金写入。
- 支付：余额支付以 `User → Order → Payment/Settlement → Wallet` 锁序把扣款、流水、成功 Payment、唯一 Settlement、Order Paid 与 Audit 原子提交。ADMIN+ 代客钱包订单为正常普通 USER 原子创建真实 Order/Items、扣 Kit/钱包、创建 Payment/Settlement、直接 Paid 并写 `CREATE_ORDER` + `PAY_ORDER`；disabled 目标因属于消费而拒绝。人工 Paid 先只读定位 owner，再按 `User → Order` 锁序复验；只有 NORMAL 普通 USER 订单可同事务创建 `method=manual` Settlement，staff/disabled/deleted owner 均零写入拒绝。
- 退款：仅 ADMIN+、仅普通 USER 的 PAID/COMPLETED 已结算订单、一次全额；Completed 窗口 30 天。退款前验证 Settlement 与成功 order-purpose Payment 的用户、订单、金额及空充值关联一致性，矛盾事实零写入拒绝。PAID Kit 按 OrderItem 快照恢复并写 `order_refund_restore`，COMPLETED 不恢复；退款不改 OrderStatus。
- 幂等：ADMIN 调账、代客钱包订单、余额支付、充值/微信支付意图和退款要求 `Idempotency-Key`；四个持久 key 列在 MySQL 使用 ASCII / `ascii_bin`，按大小写敏感逐字节语义比较。首次 201、完全一致重放 200、不同意图 409；调账复验完整流水身份与余额算术，余额/代客支付复验 Order、Payment、Settlement 和扣款流水，退款复验 Settlement、Payment、Refund 及钱包渠道入账流水，任一缺失或矛盾都拒绝重放。只在退出失败事务后解析 UNIQUE；MySQL 1205/1213 可对完整内部事务最多尝试 3 次。
- 开关：development/testing 默认允许调账、余额支付和内部退款演练；production 分别显式开启。真实充值/微信订单支付/微信退款固定 503 且零写入；当前配置拒绝非 disabled Provider 与 topup enabled。
- 数据：迁移 `4_20260905162243_add_wallet_payment_refund.py` 已离线生成；一次性 MySQL 8.0.46 已完成 Wallet `9 passed` 与 Inventory + Reservation + Wallet 联合 `30 passed`，扩展并发/1205/1213/锁序/EXPLAIN 门槛及对应远端 workflow 均已关闭。M4 已随当前持久 Gate A 的 M3→M7 升级应用，Wallet account/legacy settlement backfill 与只读 reconcile 也已完成；共享、预发布和生产环境仍未因此自动迁移。本地 development SQLite 的 `generate_schemas` 可能补建缺失表，但不会 ALTER 既有表或写入 Aerich 版本，不能作为发布迁移证据。新注册/首次微信 USER 同事务建钱包；历史 NORMAL/DISABLED 普通 USER 的 `wallet_account_backfill` 默认 preview 输出 `through_user_id=N`，apply 必须显式复用 `--through-user-id N --apply`。写批次按 User ID 升序锁定，事务内复验 USER + NORMAL/DISABLED 并重查钱包存在性，DELETED/staff/已有钱包均跳过且不造零流水。随后用各自固定预览上界运行 wallet 复查和 `legacy_manual_settlement_backfill`，最后执行只读 `wallet_reconcile`，核验余额净额、非零变化、单行算术/范围、余额链、末条余额和无流水零余额规则；任一差异或 blocker 均非零退出且不自动改账。完整发布顺序是 M4 → wallet backfill → legacy settlement backfill → reconcile/发布门槛 → 启用。
- API：用户 `/wallet`、`/wallet/transactions`、`/wallet/recharges`、`/orders/{id}/financials`、余额/微信支付六个端点统一要求 customer 身份；管理端 `/admin/users/{id}/wallet*`（含 `POST /admin/users/{id}/wallet-orders`）、`/admin/orders/{id}/financials` 与全额退款。资金 Mapper 后的严格 Out Schema 校验 finite Decimal/UTC，Payment 用途的 Order/Recharge 互斥关联、Payment/Refund 成功时间，以及 OrderFinancial/WalletPayment/AssistedWalletOrder 中 Order、Payment、Refund 的订单、渠道、金额与成功状态；矛盾事实不序列化为成功响应。完整契约见 `wallet_api.md`。

Order v1.0 契约速查：

- `app/common/enums/order.py` 使用 `OrderStatus(IntEnum)` 保存 0/1/2/3；`app/common/constants/order.py` 显式注册 API value/label，禁止把 IntEnum 整数直接输出为 API status。
- 已实现 Item 1–10、quantity 1–99、remark 500、订单号长度/正则/重试次数、Phase 4.3 边界和四个审计 action 常量；五个命名异常通过 `app/common/exceptions/__init__.py` 导出。
- `app/schemas/order.py` 固定创建请求、重复 Product/Option 拒绝、用户/管理分页筛选和 UTC 时间范围；`app/schemas/order_response.py` 固定金额 Decimal→两位字符串、status/day_type 配对、快照金额一致性以及用户/管理字段隔离。详情不返回列表派生 `item_count`。
- `app/models/order.py` 已实现 `Order` / `OrderItem`、`SmallIntField` 状态、订单号唯一约束、Decimal 快照、四条 `RESTRICT` 历史外键和五组稳定查询索引；MySQL 8+ 增量迁移已离线生成并静态 Review，且作为 M1 已存在于当前 Gate A M7，其他持久环境须分别核验。
- `app/common/order_number.py` 只用标准库生成 OD+ULID；`app/repositories/order_repo.py` 已实现 Order/Item 事务写入、详情、用户可见限定、行锁、状态持久化和用户/管理分页，列表使用数据库 `COUNT(items)` 生成 `item_count`。ProductRepository 已提供包含逻辑删除记录的 Product/Option 集合读取，供创建 Service 一次批量校验。
- `app/services/order_service.py` 已实现 Experience/Kit/混合创建、ADMIN+ 代客钱包订单、三个独立状态变迁及五个只读用例。普通创建批量读取 Product/Option/Kit 候选快照；事务内先锁定 User 并复验仍为 NORMAL 普通 USER，再写 Pending Order、稳定锁定并扣减 Kit，批量写余额/流水/Items，最后写 `CREATE_ORDER` Audit 和重载聚合。代客钱包订单锁目标 USER、新 Order、Wallet 与稳定 Kit 集合，把真实 Items、库存/钱包扣减、Payment/Settlement、直接 Paid 和双审计原子提交。取消使用独立库存感知事务，在 Order 锁后读取最小 Item 快照、稳定锁定并恢复 Kit，再提交 Cancelled/Audit/重载；Wallet/Payment M4 接入后，人工 Paid 先定位 owner，再按 `User → Order` 锁序复验，仅允许 NORMAL 普通 USER 并同事务创建 manual Payment/Settlement，staff/disabled/deleted 拒绝且零写入；complete 会检查 Refund 冲突。创建和取消的 MySQL 1205/1213 都重试完整用例最多 3 次。用户查询与取消使用 `(order_id, user_id)` 可见限定统一隐藏不存在/他人资源；管理端审计先确认 Order 存在再委托共享 AuditLogService。`OrderStatusValue` 定义在 common Enum 模块，Service 使用完整 `ORDER_STATUS_BY_VALUE` Registry 将 API 字符串翻译为数据库 IntEnum。
- `app/api/mappers/order.py` 已实现 OrderStatus/DayType、OrderItem 快照、用户/管理列表与分页、用户/管理详情和轻量状态响应。Mapper 只消费 Repository 已注解或预加载的数据，用户端不读取 User 关系，管理端只输出 `user_id/user_nickname`；严格 Schema 负责 Decimal 两位小数与聚合金额一致性。真实 SQLite 聚合测试固定零 SQL、零 ORM 对象/关系列表修改。
- `app/api/deps.py:get_order_service()` 组装 OrderRepository、ProductRepository 和共享 AuditLogService；`app/api/v1/orders.py` 已注册创建、我的列表、我的详情和取消，`app/api/v1/admin_orders.py` 已注册管理列表/详情、确认支付、完成和审计历史。九个端点均使用精确 `SuccessResponse[T]` / `ErrorResponse` OpenAPI、统一 `success()` 与全局异常中间件；真实 JWT + SQLite 测试已贯通核心生命周期。缺失 Token 为统一 401，现有无效 Token `1006` 仍为 User 契约的 HTTP 400。
- 创建 Item 必须提供 `product_id + quantity`；Experience 还必须提供有效且属于该 Product 的 `experience_option_id`，Kit 则必须省略或提交 `null`。同一 Product/Option 组合不得重复。
- 金额由当前 Option 价格用 `Decimal` 计算，API 固定输出两位小数字符串；OrderItem 保存名称、Option 配置和价格快照。
- 订单号使用 `OD` + 26 位大写 Crockford Base32 ULID（总长 28），数据库 UNIQUE 兜底；列表权威排序为 `created_at DESC, id DESC`。
- 状态流仍仅为 `pending → cancelled`、`pending → paid`、`paid → completed`；ADMIN+ `/paid` 登记 manual Payment/Settlement，USER 余额支付也驱动 `pending → paid`。Refund 独立，不回退 OrderStatus。
- 创建、取消、确认支付和完成分别写 `CREATE_ORDER`、`CANCEL_ORDER`、`MARK_ORDER_PAID`、`COMPLETE_ORDER`，与业务写入同事务；`target_type=order`。
- 用户访问不存在或他人订单统一返回 `40411 OrderNotFound`；用户端不返回 user 字段，管理端仅增加 `user_id` 与 `user_nickname`。

Product Validator 契约速查：

- `42201` 固定映射 HTTP 422，message 精确为 `Product is not ready to go online`，`data.issues` 是非空英文字符串数组；精确 issue 清单与顺序见 [Product Business Rules §8.5](../01_requirements/product_business_rules.md#85-online-validation上架校验)。
- `ProductNotReadyForOnline` 当前通过 `UnprocessableEntityException` 映射 HTTP 422；进入 Service 异常实现时将移除只能表示 422 的伪通用 `ProductException`，让 Product 的 404/409/422 命名异常分别直接继承 `NotFoundException`、`ConflictException`、`UnprocessableEntityException`。HTTP 状态按异常类型映射，禁止按错误码号段推断，普通 `BusinessException` 仍为 HTTP 400。
- `ProductValidator.validate_before_online(product) -> None` 是同步纯计算接口。Service 必须传入 `ProductRepository.get_product_detail(product_id, include_deleted=True)` 预加载的聚合；Validator 不执行 I/O、不修改对象，也不把未预加载关系造成的编程错误转换为 `42201`。
- Product 上架 Service 与 ADMIN+ JSON 路由已实现：`online_product(product_id, *, operator_id, ip_address) -> Product` 依次处理 `40401 ProductNotFound`、`40903 ProductIsDeleted`、`40901 ProductAlreadyOnline`，再同步调用 Validator。校验通过后状态与审计原子提交，Router 经 `ProductOnlineOut` 返回统一信封。
- Product 下架 Service 与 ADMIN+ JSON 路由已实现：仅允许 Online → Offline；Draft/Offline 统一返回 `40902 ProductAlreadyOffline`，逻辑删除优先返回 `40903`。成功状态与审计同事务提交，下架不调用 Validator，Router 经 `ProductOfflineOut` 返回统一信封。
- Product 查询、响应映射与 FastAPI 路由已实现：管理端/用户端采用独立 Service、Mapper 和路由；Mapper 从已预加载关系派生展示字段，执行期间零 SQL且不修改 ORM。用户端固定 Online 且未删除；管理端使用 ADMIN+ 权限并支持显式 include_deleted。查询端点当前可调用。
- Product 创建 Service 与 ADMIN+ HTTP 201 路由已实现：Experience 原子写 Product+审计；Kit 原子写 Product+ProductKit+审计。Service 保持领域边界，Router 负责 Request Schema、Mapper 和统一响应。
- Product 基础信息修改与逻辑删除 Service/ADMIN+ 路由均已实现；PATCH 使用 `model_dump(exclude_unset=True)` 保留缺失/null 语义，DELETE 只设置 Product 删除标记并保持 status/关联记录，Router 经专用 Mapper 返回统一信封。
- ExperienceOption 新增/恢复 Service 与 ADMIN+ 路由已实现：Service 返回 `ExperienceOptionCreationResult(option, restored)`，Router 新建返回 201、恢复返回 200；全历史唯一、原图片关系和事务审计契约保持不变。
- ExperienceOption 修改 Service 与 ADMIN+ JSON PATCH 路由已实现；Router 保留显式字段语义并返回不含图片的 `ExperienceOptionBaseOut`，全历史唯一与顺序审计契约不变。
- ExperienceOption 删除 Service 与 ADMIN+ JSON DELETE 路由已实现；只设置 Option.is_deleted，保持 Product 状态与图片记录/外键，并经 `DeletedResourceOut` 返回。
- Kit 价格修改 Service 与 ADMIN+ JSON PATCH 路由已实现；响应 ID 使用 ProductKit.product_id。旧 Product 库存最终值写入口已移除，库存调整统一使用 Inventory API 的变化量、流水和幂等语义。
- ProductImage 生命周期已实现：公共图/Option 图创建、排序/封面修改和逻辑删除使用 40401/40402/40403、40903/40905/40912、40021 与 42221 契约；封面批量清理、图片写入及一至两条审计同事务回滚。Service 只接收 image_url。API multipart 边界使用 `python-multipart==0.0.32`，严格表单模型拒绝未知字段；`LocalImageStorage` 完成 2 MiB、jpg/png/webp 签名/MIME、UUID 路径与原子写入；上传编排在 Service 失败时以 storage key 幂等删除文件。逻辑删除后的物理清理使用 `app.tasks.product_image_cleanup` 运维命令，显式截止时间、ID 游标分页、存储命名空间校验、有效引用保护、幂等缺失处理和失败退出码均有真实测试；不会由 Web 进程自动执行。

---

## 5. 文档更新联动

```
修改 Model           → er_diagram.dbml + database_design.md
修改 API 端点        → docs/03_api/<module>_api.md
修改 Enum            → api_design_conventions.md §14 + 本文 §3
修改业务规则         → docs/01_requirements/<module>.md
修改目录结构         → architecture.md §2
修改通用规范         → coding_standards.md
完成功能模块         → changelog.md
修改前端架构/依赖     → docs/08_frontend/frontend_architecture.md + 对应 ADR
修改跨端行为          → multi_platform_strategy.md + 四端测试矩阵
修改前后端集成契约     → api_integration_contract.md + OpenAPI 生成类型
```

---

## 6. Documentation Maintenance Rules

### Core Principle

**Documentation is part of the codebase.** Any code change that affects
architecture, API, database schema, business logic, or developer workflow
must update related documents before commit.

### When to Update

| Change Type | Update |
|-------------|--------|
| New/changed API endpoint | `docs/03_api/<module>_api.md` |
| New/changed database table/field | `database_design.md` + `er_diagram.dbml` |
| New/changed Enum | `api_design_conventions.md` §14 + `AI_CONTEXT.md` §3 |
| New/changed project structure | `architecture.md` §2 |
| New/changed dependency | `architecture.md` §1 + requirements.txt |
| New/changed coding rule | `coding_standards.md` + `AGENTS.md`（如影响优先级） |
| Feature completion | `changelog.md` |
| New error code | `api_design_conventions.md` §8 + `AI_CONTEXT.md` §4 |
| New/changed frontend architecture/dependency | `docs/08_frontend/frontend_architecture.md` + corresponding ADR |
| New/changed platform behavior | `multi_platform_strategy.md` + `testing_strategy.md` |
| New/changed frontend API integration rule | `api_integration_contract.md` + generated OpenAPI types（工程创建后） |

### Workflow After Code Changes

```
Code Change
  │
  ├─ Run tests                ← pytest tests/ -v
  ├─ Check architecture impact  ← new layer? new dependency direction?
  ├─ Check documentation impact  ← which docs are affected? (see table above)
  ├─ Update docs               ← keep in same commit as code
  ├─ Update changelog          ← if completing a feature
  ├─ git diff --stat review    ← sanity check
  └─ commit + push（仅用户明确要求时）
```

### Documentation Style

- Explain **why** this design exists, not just what the code does
- Document important trade-offs and decisions
- Keep examples in sync with actual code
- Use the same format as existing documents in the same directory

---

## 7. 开发流程（AI 固定流程）

每完成一个任务，按以下顺序执行：

```
1. 修改代码
2. 运行测试        → 确保没有回归
3. 检查架构影响     → 新模块？新依赖方向？新层级？
4. 检查文档影响     → 对照 §6 的表格逐项确认
5. 更新相关文档     → 代码和文档同 commit
6. 更新 changelog   → 功能模块完成时
7. git diff review  → 最后确认变更范围
8. commit + push      → 仅用户明确要求时
```

**四件套原则：Code + Test + Documentation + Commit。缺一不可。**

---

## 8. AI Review 流程

每完成一个功能模块，AI 必须执行以下步骤：

### Step 1: 自动检查清单

对照 [Code Review Checklist](../07_process/code_review_checklist.md) 逐项检查：
- Architecture（分层、依赖方向）
- Security（密码哈希、密钥保护、SQL 注入）
- Naming & Types（命名规范、类型标注）
- Exception & Response（统一异常、统一响应格式）
- Database（字段设计、索引、nullable）
- Testing（新增测试、异常覆盖、边界覆盖）
- Logging（关键操作、无 print、无敏感信息）
- Documentation（API/DB/changelog 更新）

### Step 2: 生成 Review Report

```
## AI Code Review Report

### Changes
[本次修改的文件清单]

### Architecture Check
[通过 / 发现问题及说明]

### Security Check
[通过 / 发现问题及说明]

### Documentation Check
[通过 / 需更新：具体文件列表]

### Test Coverage
- 新增测试: N 条
- 通过: N/N

### Action Items
- [ ] [如需要] 升级版本号
- [ ] [如需要] 数据库迁移 (aerich migrate)
- [ ] [如需要] 新增依赖
- [ ] [如需要] 新增测试
```

### Step 3: 提醒开发者

完成 Review Report 后，主动提醒：
- 是否需要版本升级（semver）
- 是否需要数据库迁移
- 是否需要新增测试或补充边界用例
