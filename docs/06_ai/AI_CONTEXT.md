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
| 库存业务规则 | [inventory_module.md](../01_requirements/inventory_module.md) |
| 库存 API 草案 | [inventory_api.md](../03_api/inventory_api.md) |
| 数据库设计 | [database_design.md](../02_database/database_design.md) |
| ER 图 | [er_diagram.dbml](../02_database/er_diagram.dbml) |
| Code Review 清单 | [code_review_checklist.md](../07_process/code_review_checklist.md) |
| 数据库迁移流程 | [database_migration_workflow.md](../07_process/database_migration_workflow.md) |
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

- 前端 **Phase 9.1 已 Complete；9.2.1–9.2.5 已于 2026-08-31 完成本地实现，下一步为 9.2.6 真实 PR CI**：仓库固定 Python 3.10.9、Node 24.13.0、npm 11.6.2/pip 26.2.1；GitHub Actions 当前包含 8 个 Job，在既有 SQLite/MySQL/前端/OpenAPI/微信构建/仓库卫生门槛之外增加 Python 与 npm 依赖审计。Python 将 asyncmy、cryptography、python-jose 升级到已修复版本后，`pip-audit==2.10.1` 只剩 ecdsa 的 1 条无修复公告；production 固定 HS256，例外截至 2026-11-30。npm 官方 registry 的 Gate A 生产树仍为 10 个包、5 个叶子公告（4 moderate/1 high/5 critical），已逐项记录 build-time/H5-only/当前微信源码与产物不可达证据及同日到期策略；新增、消失、版本/严重性/路径变化或到期都会失败。本地完整后端为 `1507 passed, 9 skipped`，前端 61 套件/387 项、CI Node policy 13 项、静态/OpenAPI 和微信 artifact 检查通过；升级后的 asyncmy 再次通过 MySQL 8.0.46 真实迁移与 9 项门槛并已完整清理。在真实 PR 的干净 checkout 取得 8 Job 结果前，这些仍只是本地证据，不是远端 CI 通过证据；真实 HTTPS/合法域名、备份恢复、readiness、图片持久化、SUPER_ADMIN bootstrap 和真机仍待 9.3–9.4 关闭，未授权持久迁移、微信后台变更、上传、提审或发布。
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
- Phase 7.1–7.4 已收口。H5 等后端 CORS allowlist 后验证。Order create 仍无客户端幂等键；微信登录/微信支付未实现、refresh 不轮换及登录/注册不限流均是明确集成/发布缺口。
- 当前代码版本候选为 **v0.6.0（尚未发布）**；**Phase 4.1 Product Module**、**Phase 4.2 Order Module** 与 **Phase 4.3 Inventory Module** 均已完成实现和最终 Review。Order v1.0 基线保持 release-ready，Phase 4.3.7–4.3.8 已在原 POST/cancel 上增加纯 Kit/混合创建扣减及 Pending 取消恢复。九个 Order 端点、查询、Mapper 和资源隐藏边界保持不变；Phase 4.3.11 真实 MySQL 库存竞争与 Phase 4.3.12 最终 Review 均已通过。
- Product 业务规则、数据库设计、API 契约和 Validator 对外契约均已完成；Product API 文档已通过 Phase 4.1 最终 Review，并收口为 v1.0 Implemented。
- 已实现 Product 字符串 Enum、字段常量、请求/查询 Schema、响应 Schema 及其契约测试。
- `app/schemas/product.py` 负责请求体和查询参数；`app/schemas/product_response.py` 负责响应白名单。
- Product、ExperienceOption、ProductKit 与 ProductImage 的全部 Model、`ProductRepository`、Product Validator、Service、API Mapper 与 21 个 FastAPI 端点均已实现。其中 19 个 JSON 端点负责公开/管理查询、Product/Option/Kit mutation、图片元数据 PATCH/DELETE 和 Product 操作历史；两个 ADMIN+ multipart 端点负责 Product 公共图和 Option 专属图创建。旧 stock 写端点已在 Phase 4.3.10 移除。上传已接入严格表单、文件校验/本地存储、Service 失败幂等补偿、开发环境静态 URL 和真实 SQLite HTTP 一致性测试。Product 操作历史通过共享 AuditLog Repository/Service、Out Schema 和 Mapper 分页查询，支持逻辑删除后的追溯。逻辑删除图片的本地文件由带显式截止时间的可重试批处理清理。
- MySQL 8+ 权威首迁移、Order 增量迁移及 Inventory 增量迁移已离线生成并通过契约测试；完整链已在一次性 MySQL 8.0.46 实例真实执行并在验证后销毁，未应用任何持久、共享或生产数据库，也未使用 `--fake`。SQLite 开发库未被本次演练修改。
- Phase 4.3.1–4.3.12 Inventory 契约、领域/Schema、Model/数据库设计、MySQL 增量迁移、Repository、管理员调整、Kit/混合订单创建扣减、Pending 取消恢复、查询 Service/Mapper、三个 ADMIN+ API、发布门槛和最终 Review 均已完成。Order 创建和取消分别拥有 deduction/restore 的稳定集合锁、批量余额/流水、Order/Audit/重载外层事务；状态机与 restore UNIQUE 共同防止重复恢复。指定 Kit 查询验证资源聚合，全局查询把 Product ID 仅作为筛选；Mapper 对预加载展示字段显式投影并保持零 SQL/零修改。调整 API 首次返回 201、幂等重放返回 200。真实 MySQL 回填、Repository smoke、竞争/1205/EXPLAIN、MySQL HTTP smoke 与完整 HTTP 矩阵均已通过；旧直接设置库存端点和 Kit 创建 stock 输入已移除。Product Kit 详情响应的库存上限已与 Inventory `999999` 契约一致，数据库文档的旧 Kit 规划描述已清理。
- 2026-08-14 的 MySQL smoke 曾发现 Order 阻断：`OrderStatus` 直接写普通 `SmallIntField` 会被 asyncmy 编码成 `OrderStatus.*` 字符串并报 1366。现已将 Model Pending 默认值、Repository 状态更新和状态筛选统一转换为原生整数，并在全新 MySQL 8.0.46 上通过默认创建、Pending/Paid 筛选及状态更新回归；物理 Schema 和 API 语义未变化，无需迁移。
- ExperienceOption 配置组合在全历史范围内唯一；再次创建相同已删除组合时恢复原 Option ID、更新当前价格并保留图片关联，不创建第二条版本记录。

---

## 3. 枚举速查

| 数据库 | API (string) | Python Enum |
|--------|--------------|-------------|
| `users.role` 1/2/3 | `"user"` / `"admin"` / `"super_admin"` | `UserRole` |
| `users.status` 1/2 | `"normal"` / `"disabled"` | `UserStatus` |
| `products.product_type` VARCHAR | `"experience"` / `"kit"` | `ProductType(str, Enum)` |
| `products.status` VARCHAR | `"draft"` / `"online"` / `"offline"` | `ProductStatus(str, Enum)` |
| `experience_options.day_type` VARCHAR | `"weekday"` / `"holiday"` | `DayType(str, Enum)` |
| `orders.status` 0/1/2/3 | `"pending"` / `"paid"` / `"cancelled"` / `"completed"` | `OrderStatus` |
| `inventory_transactions.transaction_type` VARCHAR(40)（Model/迁移已实现；一次性 MySQL 演练通过，未应用持久环境） | `"opening_balance"` / `"admin_adjustment"` / `"order_deduction"` / `"order_cancellation_restore"` | `InventoryTransactionType(str, Enum)` |
| `inventory_transactions.source_type` VARCHAR(30)（Model/迁移已实现；一次性 MySQL 演练通过，未应用持久环境） | `"migration"` / `"admin"` / `"order"` | `InventorySourceType(str, Enum)` |

> `duration_minutes` 和 `participants` 是开放正整数，不是 Enum。当前常用值不构成允许值白名单。

---

## 4. 错误码号段速查

| 模块 | 号段 | 已用 |
|------|------|------|
| 用户 | 1xxx | 1001-1007 |
| 商品 | 40xxx / 409xx / 422xx | 40001, 40021 / 40401-40404 / 40901-40905, 40911-40912 / 42201, 42221 |
| 订单 | 4041x / 4092x / 4223x | 40411 / 40921 / 42231-42232（命名异常与 HTTP 映射已实现；40922 已移除） |
| 库存 | 4093x | 40931-40933（命名异常、HTTP 映射与三个 ADMIN+ Inventory API 均已实现） |

Inventory Phase 4.3.1 契约速查：

- `product_kits.stock` 继续作为唯一权威可售余额；每次变化写不可变流水，余额/流水必须同事务。
- 新建 Pending Kit/混合订单立即扣减；Pending 取消幂等恢复；支付和完成不再改变库存。
- 支持纯 Experience、纯 Kit 和混合订单；多 Kit 按 Product ID 升序加行锁，Order 创建/取消 Service 拥有外层事务并协调 Inventory Repository。
- 管理员调整为 ADMIN+ 的 `change + reason + Idempotency-Key`，允许未删除 Online Kit；余额范围 `0..999999`，reason trim 后 `1..256`。
- 旧 `PATCH .../stock` 与 Kit 创建 `stock` 输入已在 Phase 4.3.10 移除；当前库存写入统一经过 Inventory 流水语义。
- 流水类型冻结为 `opening_balance`、`admin_adjustment`、`order_deduction`、`order_cancellation_restore`；现有正库存生成期初流水，零库存不生成零变化流水。
- 用户库存不足不披露精确 available；自动事件和管理员重试均由 UNIQUE 幂等身份保护。
- MySQL 8+ 真实并发验证是 v0.6.0 发布硬门槛；Phase 4.3.11 已在隔离实例通过，但未执行持久环境迁移或版本发布。

Inventory Phase 4.3.2 实现速查：

- `app/common/enums/inventory.py` 定义四种流水类型和三种 source 类型，均为稳定字符串 Enum；常量集中在 `app/common/constants/inventory.py`。
- `InsufficientStock(40931)` 不包含 available；`InventoryBalanceExceeded(40932)` 只接受确实越界的调整上下文；`InventoryTransactionConflict(40933)` 不输出 data。三者均继承 `ConflictException` 并由全局中间件映射 HTTP 409。
- `app/schemas/inventory.py` 实现 `InventoryIdempotencyKey`、`InventoryAdjustmentCreate`、`InventoryProductTransactionQuery` 与 `InventoryTransactionQuery`。写整数 strict；HTTP Query ID 接受十进制字符串；时间只接受 UTC；`source_id` 要求 `source_type=order`。
- `app/schemas/inventory_response.py` 实现余额、流水列表/详情和调整响应白名单，拒绝内部幂等键与隐私字段，并校验 before/change/after、流水方向和 source/operator 元数据一致性。

Inventory Phase 4.3.3 实现速查：

- `app/models/inventory_transaction.py` 关联 `products.id` 与可空 `users.id`，两者 `RESTRICT`；通用可空 `source_id` 不建多态 FK。`source_type`、稳定 `reason` 与内部 256 字符幂等身份均非空。
- 幂等键使用 `uidx_inventory_idempotency_key` 命名 UNIQUE；另有 Product、source、transaction type 与全局 `created_at DESC, id DESC` 分页查询索引。数据库设计与 DBML 已同步，MySQL 迁移留在 4.3.4。
- Model 校验变化量非零及库存闭区间，但 before/change/after 等式与类型/source 组合仍由未来 Service 保证；当前不新增跨方言 `CHECK`。流水继承 BaseModel 的 `updated_at` 技术字段，但没有业务更新/删除入口且 API 不输出。

Inventory Phase 4.3.4 迁移速查：

- `migrations/models/2_20260814104655_add_inventory_transactions.py` 使用 `AERICH_MYSQL_VERSION=8.0` 离线生成，人工移除 `IF NOT EXISTS` 并声明 `RUN_IN_TRANSACTION=False`；已在一次性 MySQL 8.0.46 完成真实升级/降级/带数据再升级，未 fake，未应用持久环境。
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

- `OrderItemCreate.experience_option_id` 现为可省略/null；Service 对 Experience 要求有效 Option，对 Kit 要求 null。`OrderItemOut` 只接受完整 Option 快照或四项全 null Kit 快照，既有 POST 路由已可创建纯 Kit/混合订单。
- ProductRepository 批量读取 Product、非空 Option ID 和 Kit 候选价格；事务内先创建 Pending Order，再由 InventoryRepository 一次按 Product ID 升序锁定全部 Kit，并用同一连接重读 Product 状态。
- 锁后按请求顺序检查 Kit 扩展和余额；多 Kit 余额用一次 `bulk_update`、流水用一次 `bulk_create`。流水固定为 `order_deduction` / Order source / 下单用户 operator / `Order stock deduction`，key 为 `inventory:order:{order_id}:deduct:product:{product_id}`。
- Order、库存、流水、Items、`CREATE_ORDER` Audit 和详情重载原子提交；库存不足、审计或重载失败全部回滚。`40931` 不包含 available。纯 Experience 创建零 Inventory Repository 调用。
- 订单号 UNIQUE 冲突在任何库存锁/写之前发生并沿用新编号事务重试；MySQL 1205/1213 对完整写事务以同一候选快照/编号和全新事务最多尝试 3 次。`IntegrityError` 必须先于其父类 OperationalError 处理。
- 取消先锁 owner 可见 Order 并重检 Pending，再读取最小 Item 快照、稳定锁定 Kit、批量检查 `inventory:order:{order_id}:restore:product:{product_id}`，批量恢复余额/`order_cancellation_restore` 流水后提交 Cancelled/Audit/重载。
- 重复取消由状态机返回 `40921`；Pending 与已存在 restore 身份矛盾返回 `40933`，恢复越界返回 `40932`。MySQL 1205/1213 对完整取消事务最多尝试 3 次；支付和完成零库存调用。
- 阶段门禁 `40922 KitOrderingRequiresInventory` 已从常量、异常、导出、测试和当前文档注册表移除。真实 MySQL 竞争已由 4.3.11 验证。

Inventory Phase 4.3.9–4.3.11 查询、API 与发布门槛速查：

- 指定 Kit 查询先验证 Product/Kit 聚合身份；全局 Product ID 只筛选。Mapper 显式投影严格 Out Schema，只消费预加载 operator 与批量 Order 编号，零 SQL、零修改且不泄漏幂等键或用户隐私。
- `get_inventory_service()` 与三个 ADMIN+ 路由已注册；调整要求严格 body/`Idempotency-Key`，首次 201、重放 200，两个 GET 输出统一 Page。旧 Product stock 路由和创建 stock 输入已移除。
- Phase 4.3.11 在隔离 MySQL 8.0.46、真实 Aerich 0→1→2 上通过 9 项门槛：同/异 key、最后一件、反向多 Kit、同单取消、调整/下单真实等待、真实 1205 全事务重试、三类 EXPLAIN 和 MySQL HTTP 并发重放/查询。
- 完整 HTTP 矩阵另有 41 项，覆盖三端点 401/1006/403、资源/业务异常、严格 422、分页/筛选/Order source/UTC 与隐私。测试 fixture 强制回环、非 3306 和专用 Schema 前缀；实例销毁且未修改持久数据库。

Order v1.0 契约速查：

- `app/common/enums/order.py` 使用 `OrderStatus(IntEnum)` 保存 0/1/2/3；`app/common/constants/order.py` 显式注册 API value/label，禁止把 IntEnum 整数直接输出为 API status。
- 已实现 Item 1–10、quantity 1–99、remark 500、订单号长度/正则/重试次数、Phase 4.3 边界和四个审计 action 常量；五个命名异常通过 `app/common/exceptions/__init__.py` 导出。
- `app/schemas/order.py` 固定创建请求、重复 Product/Option 拒绝、用户/管理分页筛选和 UTC 时间范围；`app/schemas/order_response.py` 固定金额 Decimal→两位字符串、status/day_type 配对、快照金额一致性以及用户/管理字段隔离。详情不返回列表派生 `item_count`。
- `app/models/order.py` 已实现 `Order` / `OrderItem`、`SmallIntField` 状态、订单号唯一约束、Decimal 快照、四条 `RESTRICT` 历史外键和五组稳定查询索引；MySQL 8+ 增量迁移已离线生成并静态 Review，尚未应用。
- `app/common/order_number.py` 只用标准库生成 OD+ULID；`app/repositories/order_repo.py` 已实现 Order/Item 事务写入、详情、用户可见限定、行锁、状态持久化和用户/管理分页，列表使用数据库 `COUNT(items)` 生成 `item_count`。ProductRepository 已提供包含逻辑删除记录的 Product/Option 集合读取，供创建 Service 一次批量校验。
- `app/services/order_service.py` 已实现 Experience/Kit/混合创建、三个独立状态变迁及五个只读用例。创建批量读取 Product/Option/Kit 候选快照；事务内先写 Pending Order，再稳定锁定并扣减 Kit，批量写余额/流水/Items，最后写 `CREATE_ORDER` Audit 和重载聚合。取消使用独立库存感知事务，在 Order 锁后读取最小 Item 快照、稳定锁定并恢复 Kit，再提交 Cancelled/Audit/重载；支付和完成仍是纯状态事务。创建和取消的 MySQL 1205/1213 都重试完整用例最多 3 次。用户查询与取消使用 `(order_id, user_id)` 可见限定统一隐藏不存在/他人资源；管理端审计先确认 Order 存在再委托共享 AuditLogService。`OrderStatusValue` 定义在 common Enum 模块，Service 使用完整 `ORDER_STATUS_BY_VALUE` Registry 将 API 字符串翻译为数据库 IntEnum。
- `app/api/mappers/order.py` 已实现 OrderStatus/DayType、OrderItem 快照、用户/管理列表与分页、用户/管理详情和轻量状态响应。Mapper 只消费 Repository 已注解或预加载的数据，用户端不读取 User 关系，管理端只输出 `user_id/user_nickname`；严格 Schema 负责 Decimal 两位小数与聚合金额一致性。真实 SQLite 聚合测试固定零 SQL、零 ORM 对象/关系列表修改。
- `app/api/deps.py:get_order_service()` 组装 OrderRepository、ProductRepository 和共享 AuditLogService；`app/api/v1/orders.py` 已注册创建、我的列表、我的详情和取消，`app/api/v1/admin_orders.py` 已注册管理列表/详情、确认支付、完成和审计历史。九个端点均使用精确 `SuccessResponse[T]` / `ErrorResponse` OpenAPI、统一 `success()` 与全局异常中间件；真实 JWT + SQLite 测试已贯通核心生命周期。缺失 Token 为统一 401，现有无效 Token `1006` 仍为 User 契约的 HTTP 400。
- 创建 Item 必须提供 `product_id + quantity`；Experience 还必须提供有效且属于该 Product 的 `experience_option_id`，Kit 则必须省略或提交 `null`。同一 Product/Option 组合不得重复。
- 金额由当前 Option 价格用 `Decimal` 计算，API 固定输出两位小数字符串；OrderItem 保存名称、Option 配置和价格快照。
- 订单号使用 `OD` + 26 位大写 Crockford Base32 ULID（总长 28），数据库 UNIQUE 兜底；列表权威排序为 `created_at DESC, id DESC`。
- 状态流仅为 `pending → cancelled`、`pending → paid`、`paid → completed`；ADMIN+ `/paid` 是支付集成前临时人工入口。
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
