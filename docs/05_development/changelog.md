# Development Changelog

> 每个独立功能模块完成后更新。记录做了什么、为什么这样做、有什么限制。

---

## Frontend Phase 6 — 公开 Product 列表纵向链路（2026-08-20）

### Summary

完成前端 Product 浏览纵向链路：游客可通过公开首页读取 Online Product，按服务端分页、类型和 keyword 浏览 Experience 与 Kit，并进入类型专属详情选择真实 Option；Product 数据状态与 AuthContext 解耦。Endpoint、运行时契约、图片地址、分页/搜索 Feature、四态 UI、详情、自动化、四端构建和微信开发者工具 Functional 均已完成。

### Implemented

- 新增严格限定为本地开发环境的 `python -m app.tasks.product_functional_seed`：要求 development、仓库内 SQLite/图片目录、`--apply` + `--confirm-local-only` 双确认和启用的 ADMIN/SUPER_ADMIN 操作者。脚本复用 Product Service、Validator、AuditLog 与 LocalImageStorage，生成 7 Experience、6 Kit、13 条 Online Product 和 21 张相对图片；其中专用多配置 Experience 有两个不同组合、价格和配色图片的 Option。完整同名数据可幂等跳过，冲突数据安全停止，图片登记失败执行文件补偿。
- 修复 Seed PNG 夹具只有文件签名、无法真实解码的问题：改为生成带 IHDR、zlib IDAT、IEND 和逐 chunk CRC 的 2×2 RGB PNG；重复执行只原子修复 Seed Product 引用的旧错误内容或缺失文件，不覆盖其他图片。2026-08-21 首次修复当时 12 条目录的结果为 `created=0 / skipped=12 / repaired_images=18`。
- 新增 `ProductApi.listProducts()`，直接复用 OpenAPI 生成的 Product Query/Page/Item 类型；HTTP Client 结果保持 `unknown`，Endpoint 校验并白名单投影 ID、名称、Product Enum、两位小数金额、图片地址和分页字段。公开请求固定 `auth: none`，不会因本地存在 Session 而附带 Token。
- 新增唯一 `resolveAssetUrl()`：HTTP(S) 绝对 URL 原样使用，`/uploads/...` 相对已校验 API Origin 补全，其他路径拒绝；ProductCard 使用懒加载和图片失败占位。
- 新增 `useProductList` Feature，首屏固定 `page=1&page_size=10`，按服务端 `page/pages/total` 加载下一页；防止同页重复点击，并以请求 sequence 隔离迟到旧响应，不依赖所有小程序运行时未必提供的 `AbortController`。
- 首页改为公开 Product 页面，互斥展示 Loading/Empty/Error/Content；首屏失败可重试，下一页失败保留已有内容。Experience 按 `product_type.value` 显示“起”，Kit 显示固定价格；guest/authenticated/error 状态只影响账号操作，不阻断公开浏览。
- Jest setup 集中 mock Taro 4.2.1 router 循环依赖，并为 jsdom 提供 `IntersectionObserver`，支持 `Image lazyLoad` 组件测试且不隐藏现有上游 `act` 弃用告警。
- 新增 Phase 6 学习笔记，解释生成类型与 Runtime Guard、金额字符串、Enum、判别四态、服务端分页、请求竞态、相对图片和公开数据/认证状态边界。
- 首页新增“全部 / 拼豆体验 / 材料套装”类型筛选和最长 100 字符的受控 keyword 搜索；类型立即生效，keyword 在 300ms 静默期后去除首尾空白并查询。筛选变化重置第 1 页，加载更多保留查询上下文，迟到响应继续由 sequence token 隔离。
- 新增公开 Product 详情纵向链路：列表卡片根据服务端 ProductType 跳转单一详情页，严格解析正整数 ID 与 experience/kit 类型；Endpoint 分别调用两条无认证详情 API 并对 unknown JSON 执行白名单 Runtime Guard。详情 Hook 提供 Loading/Error/Content 与重试、迟到响应隔离；Experience 只允许选择服务端真实 Option 完整组合并同步价格/专属图片，Kit 展示价格、库存和 available 且明确下单仍需服务端校验。

### Verification

- 本地 Product seed 17 项隔离测试通过，覆盖环境/引擎/路径/双确认门槛、13 条两类型目录、重复执行、保留名称冲突、图片补偿、PNG chunk/CRC/像素解压、旧夹具精准修复、缺失文件恢复、旧默认 Option 配色迁移，以及一次性 SQLite + 临时图片目录中的真实 13 Product / 21 图片纵向创建；集成断言会从 Online 详情重读两个 Option 的完整组合、价格、图片关系和不同像素内容。
- 完整 Jest 11 套件 / 70 项通过，覆盖公开 Product Query/无认证头、坏契约拒绝、动态详情路由、Experience/Kit Runtime Guard、图片 URL、列表/详情四态、分页追加、完整 Option 选择及旧响应隔离。只有 Taro Test Utils 间接旧 `act` 的已知上游警告。
- `npm run typecheck`、ESLint `--max-warnings=0`、Stylelint 与 OpenAPI 类型漂移检查均以退出码 0 通过；后端完整套件为 1442 项通过、9 项显式隔离 MySQL 门槛跳过。
- weapp/alipay/tt/h5 四端生产构建均通过；为避免用户微信 watcher 竞态，weapp 在复用同一依赖的系统临时副本中隔离构建并核对详情产物。冷启动支付宝 25.11 分钟，预热后抖音 39.45 秒、微信 2.97 秒，H5 2.72 分钟。H5 入口保持 327 KiB、app JS 245 KiB，仍有 Webpack 244 KiB 性能建议和 `[hash]` 上游弃用警告。
- 未修改 FastAPI Web 运行链、数据库 Schema 或依赖；不需要迁移。2026-08-22 列表 Content、相对图片、第二页、类型筛选、keyword 防抖/组合搜索、Empty，以及详情/多配置 Option 切换微信 Functional 均已通过。本地开发库增量 Seed 先得到 `created=1 / skipped=12 / repaired_images=0`，再把多配置 Experience 第二张旧默认测试图精准迁移为备用配色，结果为 `created=0 / skipped=13 / repaired_images=1`；当前共有 13 条 Online Product 和 21 张图片，全部由 Windows `System.Drawing` 解码为 2×2 PNG。

### Next

Phase 6 自动化与微信 Functional 已收口。下一步进入 Phase 7 购物车、确认页和 Order 创建。

---

## Frontend Phase 5 — 账号密码登录纵向链路（2026-08-20）

### Summary

完成首条可运行的前端业务纵向链路：现有账号密码登录、Token 会话持久化、启动恢复、access token 刷新、`/users/me` 验证、页面守卫和登出。同步修复认证/用户成功响应在 OpenAPI 中为 `unknown`、以及 User `IntEnum` 数据库存储与 HTTP 字符串输出不一致的 Schema 描述；接口运行行为和数据库结构均未改变。

### Implemented

- 为 auth register/login/refresh/logout 和 users me/update/password 声明精确 `SuccessResponse[T]` / `ErrorResponse` OpenAPI 信封；User 输出 Schema 现在正确描述 `role=user|admin|super_admin` 与 `status=normal|disabled`，生成结果更新为 45 paths / 108 schemas。
- 新增薄 `AuthApi` Endpoint，登录请求直接使用生成类型，登录/刷新/用户响应在运行时逐字段校验并重新构造白名单对象；坏 JSON 或意外额外敏感字段不会因 TypeScript 类型断言而进入应用状态/Storage。
- 新增 Taro Storage Port/Adapter 与可注入 storage/clock/refresh 的 `SessionManager`；仅持久化 access token、refresh token、expiresAt 和公开 User，不保存密码。损坏缓存会删除，并发 refresh 共享一次 Promise。
- 新增 React `AuthProvider`/`useAuth`：启动时恢复缓存，临近过期先 refresh，再用 `/users/me` 验证当前身份；缓存身份在服务端验证前不会被视为已认证。Session 失效清理会话，网络初始化失败保留为可重试 error 状态。
- 新增受控登录表单、登录错误映射、提交中防重复、首页登录守卫、当前用户展示和登出。用户不存在与密码错误在 UI 统一为同一提示；密码提交失败后清空且永不写 Storage。
- 新增阶段学习笔记，解释生成类型/Runtime Guard、受控表单、Context、Effect、Port/Adapter、Token 生命周期、判别状态与测试边界。

### Verification

- 后端完整 SQLite 套件 1425 项通过、9 项可选 MySQL 门槛跳过；其中认证/用户相关 33 项通过，OpenAPI 测试固定成功响应引用、密码排除及输出字符串 Enum。
- 前端 `typecheck`、ESLint、Stylelint 和 OpenAPI 类型漂移检查通过；Jest 7 套件 / 29 项通过。Taro Test Utils 仍只有已记录的上游 `ReactDOMTestUtils.act` 弃用警告。
- weapp/alipay/tt/h5 四端生产构建通过；加入认证链后 H5 入口为 327 KiB，仍超过 244 KiB 建议线，比 281 KiB 空应用基线增加 46 KiB。
- 未新增 npm/Python 依赖、数据库迁移或配置密钥；尚未完成微信开发者工具/H5 对真实后端的人工 Functional，H5 仍受待实现的严格 CORS allowlist 阻挡。

### Next

先在微信开发者工具用隔离开发账号完成真实后端登录/刷新/重启恢复/登出 Functional；随后实现公开 Product 列表与详情纵向链路。微信登录仍是正式公开发布前门槛，不在本次账号密码 MVP 中伪实现。

---

## Frontend Phase 5 — 依赖复核与 API 基础层（2026-08-20）

### Summary

复核正式 `miniapp/` 的安装结果并完成下一步 OpenAPI 类型生成与 HTTP Client 基础层。依赖树已从 Spike `node_modules` 镜像残留状态收敛为 `package.json`/`package-lock.json` 可复现状态；当前尚未实现 auth Endpoint、Session Storage 或登录页面。

### Implemented

- 用官方 npm registry 确认 Taro 4.2.1 仍为最新版；清理 16 个 extraneous NutUI/React Spring 包，显式补齐 `solid-js@1.9.15` peer，并移除非目标平台插件、Taro Generator 与未启用的 Husky/Commitlint/Lint Staged，共减少 113 个未使用包。
- 新增 `scripts/export_openapi.py`，以 `TESTING=1` 从真实 FastAPI `app.openapi()` 原子导出稳定 JSON；导出结果包含 45 条路径和 99 个组件 Schema。
- 引入 `openapi-typescript@7.13.0`，使用 `--immutable --alphabetize` 生成 `miniapp/src/api/generated/schema.d.ts`，并通过 `api:types:check` 检查漂移。
- 实现可注入 Transport/AuthSession 的 HTTP Client、Taro Request Transport、统一响应信封 Runtime Guard，以及 Network/Timeout/HTTP/Business/Contract/Session/Cancel 错误模型。
- code `1006` 使用 single-flight refresh，多个并发请求共享一次刷新并各自最多重放一次；403 不刷新，普通超时和写请求不自动重试，empty-body PATCH 不添加 data/Content-Type。
- 环境 Origin 现在要求无路径、无凭据的 HTTP(S) Origin；生产环境必须 HTTPS，并拒绝 localhost、127.0.0.1、0.0.0.0 与 `[::1]`。

### Verification

- `npm ls --depth=0` 与 `npm ls --all --omit=dev` 通过，无 missing/extraneous dependency。
- `npm run typecheck`、`npm run lint`、`npm run lint:styles`、`npm run api:types:check` 全部通过。
- Jest 4 套件 / 19 用例通过，其中 14 项覆盖 API Client 与环境配置；Taro Test Utils 仍输出上游 `ReactDOMTestUtils.act` 弃用警告。
- weapp/alipay/tt/h5 四端生产构建通过；H5 空应用入口 281 KiB，超过 Webpack 244 KiB 建议线，作为后续依赖体积基线。
- 官方 registry `npm audit --omit=dev` 仍报告 10 项 Taro 4.2.1 H5 上游风险（4 moderate、1 high、5 critical）；`audit fix --force` 会破坏性降级 Taro 组件/插件，因此未执行，正式发布前必须重审。
- 未运行后端完整 pytest：后端运行时代码未修改；OpenAPI 导出脚本已通过 `py_compile` 和真实导出验证。未做真机或真实后端网络联调。

### Next

使用生成类型实现 auth Endpoint、Session/Token Storage、账号密码登录/刷新/登出纵向链路；H5 真实联调前仍需后端严格 CORS allowlist。

---

## Frontend Phase 5 — 正式 miniapp 工程创建（2026-08-15）

### Summary

创建正式跨端前端工程 `miniapp/`（Taro 4.2.1 + React 18.3.1 + TypeScript 5.9.3 strict + Webpack 5.91.0 + Jest 29.7.0），包含四端构建命令、环境变量文件、测试与 lint 工具链；工程代码目前尚未提交（待用户确认）。工程不是从 Spike 复制，Spike 仅作为依赖版本与测试 workaround 的依据。

### Verified

- `npm run typecheck`（`tsc --noEmit`，strict + skipLibCheck）、`npm test`（2 套件 / 5 用例）、`npm run lint`（`--max-warnings=0`）全部通过。
- weapp/alipay/tt/h5 四端生产构建全部通过（weapp 3.7s），产物固定输出 `dist/<TARO_ENV>`；`project.config.json` 的 `miniprogramRoot` 指向 `dist/weapp`。
- 生产包无 localhost/HTTP 泄漏；`TARO_APP_APP_ENV`/Origin 按 Spike 结论仅对字面量引用注入，当前页面尚未消费 API Origin，将在 HTTP Client 步骤生效。
- `package-lock.json` 已生成（559 KB），锁定 Taro 4.2.1 / React 18.3.1 / Jest 29.7.0 / `@tarojs/test-utils-react` 0.1.1 等版本。

### Fixed / Recorded

- npmmirror 安装多次卡死（进程无网络/磁盘/CPU 活动、包半提取），清华源不支持 scoped 包（`@babel/core` 404）；最终以 Spike 同版本完整 `node_modules` 镜像（robocopy /MIR，53,377 文件 / 397.67 MB）兜底，再以 `npm install --package-lock-only` 生成 lockfile。
- Jest 链路沿用 Spike 结论：`.npmrc` 保留 `legacy-peer-deps`、自定义 transformer 补私有方法插件、mock `@tarojs/router` 打破循环依赖。
- 正式工程尚未引入 NutUI（ADR-005 按需引入要求留待组件开发步骤）；Spike 遗留的 NutUI 相关包已在 2026-08-20 依赖复核中清理。

### Verification

- 已运行：`npm run typecheck`、`npm test`、`npm run lint`、`npm run build:weapp|alipay|tt|h5`，全部通过。
- 未运行：后端完整 pytest（本次未修改后端代码）；未做真机/开发者工具预览（需微信开发者工具导入 `dist/weapp`）。

---

## Frontend Phase 5 — Taro 四端最小技术 Spike（2026-08-15）

### Summary

完成前端阶段 2（Taro 四端最小技术 Spike），验证 Taro 4 + React 18 + TypeScript strict + Webpack 5 + NutUI + Jest 组合在 weapp/alipay/tt/h5 的技术风险，并把结论回写架构文档与 ADR。没有创建正式 `miniapp/`、没有提交前端工程代码、没有修改后端。

### Verified

- 四端生产构建全部通过（weapp/alipay/tt/h5，Webpack 5.91.0），产物固定 `dist/<TARO_ENV>`，微信项目根指向 `dist/weapp`。
- 环境变量注入：Taro 只替换字面量 `process.env.TARO_APP_*`/`TARO_ENV`；修正后四端生产包均含生产 Origin 且无 localhost。
- HTTP Client（`Taro.request`/`uploadFile` 适配层 + 统一错误模型）、Storage 封装与 NutUI Button/Toast/Dialog/Input 受控用法；13 项 Jest 测试通过，`tsc --noEmit`（strict + skipLibCheck）与 ESLint 通过。
- H5 CORS 风险：实测 FastAPI 无 CORS 头，确认缺口。

### Fixed / Recorded

- `@tarojs/test-utils-react@0.1.1` 与 Taro 4.2.1 peer 冲突（需 `--legacy-peer-deps`）、官方 transformer 缺私有方法插件、`@tarojs/router` 循环依赖与 `html()` 爆栈问题均已在 Spike 工程记录 workaround。
- NutUI 2.7.15 无按组件 JS 入口，桶导入 + 全量主题使 h5 入口 485 KiB；ADR-005 要求正式工程按需引入并纳入构建门槛。
- TypeScript strict 需 `skipLibCheck`（Taro 声明文件本身不干净）；模板 `config/index.ts` 未用解构已修正。

### Verification

- `npm run typecheck`、`npm test`（13 项）、`npm run lint` 通过；四端 `taro build` 退出码 0。
- 后端完整 pytest 未运行（本次未修改后端代码）；CORS 检查使用与测试夹具相同的 fakeredis + 临时 SQLite 隔离环境。

---

## v0.6.0 (Unreleased) — Inventory Module Final Review (Phase 4.3.12)

**Date:** 2026-08-14

### Summary

Completed the final architecture, security, transaction, concurrency, migration, API, test, and documentation review for Inventory v0.6. Phase 4.3 is code-complete and the local application candidate is now v0.6.0; this is not a Git tag, release, deployment, or persistent-database migration.

### Reviewed

- Confirmed API → Service → Repository → Model dependency direction, explicit transaction ownership, stable Product-ID lock ordering, post-lock validation, whole-use-case MySQL 1205/1213 retries, and no InventoryService call from OrderService.
- Confirmed administrator adjustment, Order deduction, and Pending cancellation keep balance, immutable ledger, Order/Audit writes, and response reloads on the owning transaction connection.
- Confirmed the idempotency UNIQUE, state-machine defense in depth, privacy-safe insufficient-stock payload, ADMIN+ ledger access, internal-key/log exclusions, strict request/query schemas, explicit response projections, and zero-SQL Mapper invariants.
- Reconciled Model, MySQL migration, named foreign keys/indexes, database design, DBML, OpenAPI, Product/Order integration contracts, and current implementation status.

### Fixed

- Added the frozen `stock <= 999999` upper bound to both public and administrator Product Kit detail Out Schemas. Added two regression cases so abnormal data cannot escape through Product responses even though ordinary Model writes already enforce the same bound.
- Replaced stale database-design, DBML, exception, and test descriptions that still called Kit OrderItem fields a future Phase 4.2 extension; they now describe the implemented pure Kit and mixed-order lifecycle.
- Corrected the AI context's stale Experience-only Order input summary and advanced the code default, `.env.example`, version contract, README, architecture example, project context, Inventory requirement, and API status to the v0.6.0 unreleased candidate.

### Verification

- Product/Order/Inventory plus version regressions pass 1358 tests without the optional MySQL directory.
- A new disposable MySQL Community Server 8.0.46 instance on `127.0.0.1:13306` applied the real Aerich 0 → 1 → 2 chain and passed all 9 Inventory MySQL concurrency, lock-wait, EXPLAIN, and HTTP gates.
- The complete suite passes 1431 tests with SQLite and MySQL gates in the same pytest process. `compileall`, `pip check`, secret/log pattern scans, and `git diff --check` pass. Ruff is not installed and was not claimed as executed.
- The temporary MySQL directory and schema were removed after a graceful shutdown. The existing 3306 `MySQL80` service remained running and was not connected or modified.

### Release and Database Boundary

- No new dependency or migration was added by the final Review. The reviewed Inventory migration remains required before any persistent environment can use the module.
- No push, tag, GitHub Release, deployment, development-database rebuild, Aerich fake, or persistent/shared/production migration was performed.

## Unreleased — Inventory MySQL Concurrency and HTTP Gate (Phase 4.3.11)

**Date:** 2026-08-14

### Summary

Completed the Inventory release gate with reproducible real-MySQL concurrency, driver-level lock-timeout retry, query-plan verification, a real MySQL FastAPI smoke, and the complete three-endpoint HTTP permission/error/boundary matrix. No Inventory business implementation, physical schema, migration, dependency, or application version changed.

### Verified

- Added a guarded MySQL test fixture that only permits explicit enablement, `127.0.0.1`, a non-3306 port, and the disposable `pinkdoohub_inventory_4311` schema prefix; it preserves Aerich versions and clears only business tables between tests. It also clears Tortoise 1.1.7's backend-agnostic global Executor SQL cache before and after MySQL tests, allowing SQLite and asyncmy suites to coexist without placeholder leakage.
- Ran the real Aerich 0 → 1 → 2 chain on an isolated MySQL Community Server 8.0.46 instance before testing, without `--fake` or `generate_schemas()`.
- Verified concurrent distinct adjustments accumulate without lost updates, while identical concurrent idempotency keys create one balance change, ledger, and Audit and return one committed result plus one replay.
- Verified exactly one of two last-item orders commits; reversed two-Kit request orders both complete through stable Product-ID locking; and concurrent cancellation of one Pending Order restores stock exactly once.
- Held an administrator adjustment row lock and observed the competing order in `performance_schema.data_lock_waits`; after release, the order read the committed balance. Induced a real MySQL 1205 with `innodb_lock_wait_timeout=1` and verified the Service succeeds in its second fresh transaction without duplicate writes.
- Seeded representative selective data and 5,000 valid ledger rows, refreshed statistics, and verified `EXPLAIN` selects ProductKit `product_id`, `idx_inventory_product_created_id`, and `idx_inventory_created_id` for the frozen lock/Product/global pagination queries.
- Added a real MySQL FastAPI concurrent replay/query smoke and 41 SQLite-backed HTTP matrix cases covering every Inventory route's authentication, authorization, resource errors, balance/idempotency conflicts, strict validation, filters, pagination, UTC bounds, Order source metadata, and privacy exclusions.

### Verification

- The isolated MySQL gate passes 9 tests; the new complete HTTP matrix passes 41 tests; all Inventory tests pass together with 241 tests. The complete project suite, with MySQL gates explicitly enabled in the same pytest process as SQLite regressions, passes 1429 tests. `compileall`, dependency integrity, documentation contracts, and diff whitespace checks also pass.
- The temporary server and schema are destroyed after verification; the existing `MySQL80` service and all persistent/shared/production databases remain untouched.

## Unreleased — Inventory Management API (Phase 4.3.10)

**Date:** 2026-08-14

### Summary

Exposed Inventory adjustment and ledger queries through three ADMIN+ FastAPI endpoints, with strict Header/Body/Query adaptation, exact success/error envelopes, explicit Mapper serialization, and first-create versus replay status handling. Completed the frozen v0.6 breaking switch by removing Product's direct stock overwrite route and Kit creation stock input.

### Implemented

- Added `get_inventory_service()` as the sole composition root for InventoryRepository, ProductRepository, and shared AuditLogService.
- Registered POST adjustment, Product-scoped ledger GET, and global ledger GET routes under `/api/v1/admin`, all protected by the existing JWT ADMIN+ dependency.
- Required and normalized `Idempotency-Key`; mapped first commits to HTTP 201 and exact committed replays to HTTP 200 without moving transport semantics into Service.
- Adapted all validated filters explicitly and serialized every successful result through Inventory Mapper, strict Out Schema, and the shared success envelope. OpenAPI declares precise generic success models and 400/401/403/404/409/422 error envelopes.
- Removed the legacy `PATCH .../stock` route, `KitStockUpdate`, `KitStockOut`, Product stock Mapper, and `ProductService.update_kit_stock()` so application business code has one stock-write path.
- Removed `stock` from `KitProductCreate`; ProductService now creates ProductKit with the Repository's fixed zero default, and any initial stock must be added through Inventory adjustment.

### Verification

- Added composition, layering, registration, OpenAPI, permission, strict validation, query adaptation, privacy, real SQLite adjustment/replay/query, zero-opening Kit, and legacy-request rejection tests.
- Product and Inventory regression suites pass together with 909 tests; the complete project suite passes 1379 tests. `compileall`, dependency integrity, documentation contracts, and diff whitespace checks also pass.

## Unreleased — Inventory Query Service and API Mapper (Phase 4.3.9)

**Date:** 2026-08-14

### Summary

Implemented the two Inventory ledger query use cases and the synchronous API mapping boundary. Product-scoped reads now validate the complete Kit resource identity, global reads preserve filter-only semantics, and ledger/adjustment responses are explicitly projected without SQL, ORM mutation, internal idempotency data, or user privacy fields. Inventory composition and HTTP routes remain Phase 4.3.10.

### Implemented

- Added `InventoryService.list_product_transactions()` with the stable Product missing/deleted/type/Kit-extension error priority before delegating all frozen filters and pagination to InventoryRepository.
- Added `InventoryService.list_transactions()` for global filtering; an unknown Product ID is not treated as a resource lookup and returns an ordinary empty `Page`.
- Kept both reads transaction-free and lock-free, with no duplicated ORM filtering or ordering in Service.
- Added synchronous Inventory transaction, list-item, page, and adjustment Mappers. Every output is built from an explicit field whitelist and validated by its strict Out Schema.
- Consumed only Repository-preloaded operator nicknames and batched Order numbers. Mapping performs zero SQL and zero ORM mutation, and excludes `idempotency_key`, technical `updated_at`, username, phone, password, Token, and order remark.
- Kept the adjustment Mapper independent from `InventoryAdjustmentResult`; the future Router supplies its domain values and retains ownership of first-create 201 versus replay 200.

### Verification

- Added 18 focused Service/Mapper tests covering exact filter forwarding, resource error priority, global empty results, all four ledger metadata shapes, pagination, adjustment consistency, field isolation, layer direction, real SQLite data, zero SQL, and zero ORM mutation.
- All 172 Inventory tests and the complete 1382-test project suite pass. `compileall` and diff whitespace checks also pass.

## Unreleased — Pending Order Inventory Restoration (Phase 4.3.8)

**Date:** 2026-08-14

### Summary

Extended the existing owner cancellation endpoint so Pending Kit and mixed orders restore every Kit balance exactly once. Restoration, immutable ledgers, Cancelled status, audit, and response reload now form one transaction; payment and completion remain inventory-neutral.

### Implemented

- Added server-owned restore identities and reason: `inventory:order:{order_id}:restore:product:{product_id}` and `Order cancellation stock restore`.
- Added a minimal immutable Order cancellation projection containing only Product ID, nullable Option ID, and quantity, loaded on the caller's transaction connection in stable Item order.
- Added one Inventory Repository batch lookup for restore identities; empty sets execute no SQL, and Repository remains free of transaction ownership and business exceptions.
- Split owner cancellation from the generic payment/completion transition helper. Cancellation now locks the owner-visible Order first, rechecks Pending, loads Items, aggregates Kit quantities, locks all Kit rows in ascending Product ID order, and checks every restore identity before writes.
- Restored balances with one bulk update and wrote all `order_cancellation_restore` rows with one bulk insert before committing Cancelled, `CANCEL_ORDER` audit, and response reload.
- Preserved catalog independence: restoration uses immutable OrderItem quantities and does not require the Product to remain Online or reuse its current price. Missing Kit rows and Pending/restore-identity contradictions fail as consistency conflicts instead of silently skipping stock.
- Enforced the `0..999999` balance range during restoration. Any inventory, ledger, status, audit, or reload failure rolls back the complete use case.
- Kept duplicate cancellation safe through two layers: the locked Order state rejects ordinary repeats, while the restore UNIQUE identity protects transaction replay and future automatic cancellation paths.
- Added whole-use-case retries only for MySQL 1205/1213, using a fresh transaction and at most three attempts; other database errors are not retried.

### Verification

- Added Repository, Service orchestration, real SQLite transaction, real HTTP, rollback, idempotency-conflict, balance-boundary, duplicate-cancel, and transient-retry tests. The complete project suite passes 1364 tests.

## Unreleased — Kit and Mixed Order Deduction (Phase 4.3.7)

**Date:** 2026-08-14

### Summary

Enabled pure Kit and Experience/Kit mixed creation through the existing Order endpoint. Pending Order creation now owns stable Kit locking, post-lock sellability and sufficiency checks, bulk balance/ledger persistence, and atomic Order/Items/Audit response creation. Pending cancellation restoration remains Phase 4.3.8.

### Implemented

- Made `experience_option_id` optional at the request/domain boundary: Experience requires a valid owned Option, while Kit requires omission/null. Order responses accept either a complete Experience Option snapshot or an all-null Kit Option snapshot.
- Added one batched ProductKit candidate-price loader to ProductRepository and one `bulk_update_stocks()` primitive to InventoryRepository; empty collections execute no SQL and multi-Kit writes do not loop over awaited saves.
- Injected InventoryRepository directly into OrderService and the API composition root without calling InventoryService. Pure Experience creation short-circuits before any InventoryRepository operation.
- Preserved the frozen transaction order: build authoritative candidate snapshots outside the transaction, create Pending Order first, acquire all ProductKit locks in ascending Product ID order, re-read Product state on the same connection, then bulk-write balances and `order_deduction` rows before Items, Audit, and detail reload.
- Generated one stable Order-source ledger identity per Kit: `inventory:order:{order_id}:deduct:product:{product_id}`, with the requesting user as operator and `Order stock deduction` as the server-owned reason.
- Returned the first insufficient Kit in request order through privacy-safe `40931` data containing only Product ID and requested quantity. Any unavailable/insufficient Kit or downstream failure rolls back the complete Order, stock, ledger, Item, and Audit write set.
- Kept order-number collision attribution ahead of all inventory locks/writes. Added whole-write-transaction retries only for MySQL 1205/1213, with a fresh transaction and at most three attempts; IntegrityError remains reserved for order-number attribution.
- Removed the obsolete `40922 KitOrderingRequiresInventory` constant, exception, exports, tests, and current API registration.
- Moved shared database error-code extraction into a stateless utility used by InventoryService and OrderService while preserving Python 3.10 compatibility through `timezone.utc`.

### Verification

- Added unit, architecture, real SQLite Service, and real HTTP tests for pure Kit and mixed orders, null Option snapshots, server prices, stable ledger metadata, multi-Kit rollback, audit rollback, order-number collision before deduction, insufficient-stock privacy, and transient retry limits.
- The complete project suite passes 1350 tests; `compileall`, dependency integrity, and diff whitespace checks also pass.

## Unreleased — Inventory Admin Adjustment Service (Phase 4.3.6)

**Date:** 2026-08-14

### Summary

Implemented the administrator stock-adjustment use case with row-locked balance arithmetic, immutable ledger and shared-audit atomicity, exact idempotent replay, and bounded MySQL transient-error retries. No Inventory Mapper, composition dependency, or HTTP route is registered yet.

### Implemented

- Added `InventoryService.adjust_stock()` with constructor-injected Inventory/Product repositories and shared AuditLogService; the Service owns only the administrator-adjustment transaction and does not call ProductService or access Models directly.
- Locked ProductKit before revalidating Product existence, deletion state, Kit type, extension presence, and the post-change `0..999999` balance boundary.
- Persisted balance, `admin_adjustment` ledger row, compact `ADJUST_INVENTORY` Product audit, and response detail reload on the same transaction connection so any failure rolls back the complete write set.
- Namespaced client keys as `inventory:admin:adjust:{key}` and bound an existing identity to the exact Product/change/normalized reason/operator tuple. Identical retries return the originally committed transaction and its original after-balance; mismatches raise `40933`.
- Resolved concurrent unique-key races only after the failed transaction exits: a matching committed row becomes a replay, an absent row preserves the original IntegrityError, and a different payload becomes a business conflict.
- Retried only MySQL 1205/1213 for the whole use case with a fresh transaction, at most three attempts. Logs include operator/product/error/attempt context but never the reason or idempotency key.
- Added frozen `InventoryAdjustmentResult.is_replay` so a future Router can select HTTP 201 for first creation and 200 for replay without introducing transport concepts into the Service.

### Verification

- Added real SQLite transaction tests for Draft/Online/Offline Kits, closed balance boundaries, rollback at every write/reload failure, missing/deleted/wrong-type resources, exact replay after later adjustments, conflict dimensions, maximum client-key capacity, ledger/audit privacy, and atomicity.
- Added isolated retry/error-chain tests for 1205, 1213, retry exhaustion, non-retryable errors, concurrent unique resolution, and preservation of unrelated database exceptions.
- Added architecture contracts for dependency direction, transaction ownership, frozen results, no direct ORM persistence, and sensitive logging exclusions.
- Inventory passes 150 tests, Order passes 375 regression tests, and the complete project suite passes 1331 tests.

## Unreleased — Fix OrderStatus MySQL Persistence

**Date:** 2026-08-14

### Fixed

- Fixed MySQL 1366 failures caused by passing `OrderStatus(IntEnum)` objects through Tortoise `SmallIntField` to asyncmy: the Model Pending default, Repository status updates, and Repository status filters now cross the persistence boundary as native integers.
- Kept the public Order enum/API contract and physical `orders.status SMALLINT DEFAULT 0` Schema unchanged; no database migration or dependency change is required.
- Added connection-parameter regression tests that reject `OrderStatus` objects and require exact `int` values for creation, updates, and filters.
- Re-ran the complete 0 → 1 → 2 migration chain on an isolated MySQL 8.0.46 instance and verified default creation (`0`), Pending filtering, update to Paid (`1`), and Paid filtering through the real `OrderRepository` and asyncmy driver.

## Unreleased — Real MySQL Migration and Repository Smoke

**Date:** 2026-08-14

### Verification

- Ran the complete Aerich 0 → 1 → 2 chain against an isolated MySQL Community Server 8.0.46 instance and verified InnoDB/utf8mb4 table metadata, columns, named indexes, the idempotency UNIQUE, foreign keys, and Aerich version rows.
- Downgraded only Inventory version 2 in the disposable schema, seeded stock=7 and stock=0 Kit fixtures, and re-upgraded: the positive Kit received exactly one `0 → 7` opening row, the zero Kit received none, and the mismatch query returned zero.
- Ran a real asyncmy/MySQL `InventoryRepository` smoke covering ordered multi-Kit locks, atomic balance/ledger commit, forced rollback, unique-key propagation, bulk rows, same-connection reads, detail hydration, and Order-source pagination.
- Did not apply migrations to any persistent/shared/production database and did not use `--fake`; the temporary instance and test Schema were destroyed after verification.
- Found a pre-existing release blocker outside InventoryRepository: plain `IntField` writes of `OrderStatus` were encoded as Enum strings by asyncmy, so `OrderRepository.create_order()` defaults and `update_status()` failed with MySQL 1366. The subsequent OrderStatus persistence fix above resolves this blocker and has its own real-MySQL regression.

## Unreleased — Inventory Repository (Phase 4.3.5)

**Date:** 2026-08-14

### Summary

Implemented the Inventory data-access primitives for stable row locking, balance persistence, immutable ledger writes, idempotency reads, detail hydration, and filtered pagination without adding business decisions or runtime endpoints.

### Implemented

- Added `InventoryRepository.get_kit_for_update()` and a deduplicated, single-query `get_kits_for_update()` using the caller connection, `ORDER BY product_id`, and `SELECT ... FOR UPDATE`.
- Added final-balance persistence that updates only `stock`/`updated_at` and leaves sufficiency/range decisions to the owning Service.
- Added an immutable `InventoryTransactionCreateData` DTO, single-row creation for admin adjustments, and one-statement bulk creation for multi-Kit automatic events; empty collections execute no SQL.
- Added lightweight same-connection idempotency lookup and same-connection detail reload for uncommitted adjustment responses.
- Added Product/type/source/UTC-range filters, `created_at DESC, id DESC` pagination, operator preloading, and one batched Order lookup for safe `source_order_no` hydration. Order-source pages remain a constant three SELECTs regardless of row count.
- Kept the Repository free of FastAPI, Schema, Service, Validator, business exceptions, Redis, transaction ownership, retry loops, Product status checks, inventory arithmetic, and error translation.

### Verification

- Added 24 Inventory Repository contracts covering architecture, static lock/bulk guarantees, empty-set SQL avoidance, deterministic lock order, balance/ledger rollback, bulk rollback, uniqueness propagation, uncommitted visibility, metadata hydration, every filter, stable pagination, time boundaries, empty pages, and constant query count.
- The complete project suite passes with 1297 tests; `compileall`, `pip check`, and `git diff --check` also pass.

## Unreleased — Inventory Offline MySQL Migration (Phase 4.3.4)

**Date:** 2026-08-14

### Summary

Generated and statically reviewed the MySQL 8+ Inventory incremental migration, including deterministic opening-balance ledger rows for existing positive Kit stock, without connecting to or changing any database.

### Implemented

- Generated `2_20260814104655_add_inventory_transactions.py` with `AERICH_MYSQL_VERSION=8.0` and Aerich offline mode, preserving the generated model state for future diffs.
- Reviewed the table DDL for exact fields, nullable generic source/operator columns, two `RESTRICT` foreign keys, the named idempotency UNIQUE, and four stable-pagination indexes.
- Removed `CREATE TABLE IF NOT EXISTS` so Schema drift cannot be silently treated as success, and declared `RUN_IN_TRANSACTION=False` because MySQL DDL implicitly commits.
- Added one ordered `INSERT ... SELECT` that writes `opening_balance` only for `product_kits.stock > 0`, with UTC microsecond timestamps, stable reason/idempotency identity, null source/operator, and no balance mutation.
- Kept zero stock as an implicit baseline and rejected silent recovery constructs such as `INSERT IGNORE` or `ON DUPLICATE KEY UPDATE`.
- Documented the required stock-range preflight, write-quiescence window, backup, temporary-MySQL rehearsal, post-migration one-to-one verification, partial-failure forward-recovery process, and destructive downgrade semantics.
- Kept all runtime boundaries unchanged: the migration is not applied, Kit ordering remains blocked, and Inventory Repository/Service/Mapper/routes remain unimplemented.

### Verification

- Added five static migration contracts covering scope, fields/FKs/indexes, positive-only backfill, destructive downgrade boundary, and compressed model state.
- The complete project suite passes with 1273 tests; `compileall`, `pip check`, and `git diff --check` also pass.

## Unreleased — Inventory Model and Database Design (Phase 4.3.3)

**Date:** 2026-08-14

### Summary

Implemented the Inventory ledger persistence shape and synchronized its authoritative database design without generating or executing a migration.

### Implemented

- Added and registered `InventoryTransaction` with Product and nullable operator `RESTRICT` foreign keys, stable string Enum fields, non-zero/range Model validators, required source/reason, nullable generic `source_id`, and a 256-character internal idempotency identity.
- Added the named unique idempotency index plus Product, source, transaction-type, and global stable-pagination indexes. The generic source ID deliberately has no polymorphic foreign key.
- Kept `product_kits.stock` as the authoritative balance and aligned its Model plus transitional Product request boundary to `0..999999`.
- Added a reusable non-zero integer Model validator and documented that cross-field arithmetic/type-source rules remain Service responsibilities rather than Model business behavior.
- Updated the database design and DBML with the ledger table, relations, index rationale, BaseModel `updated_at` boundary, and the current no-`CHECK` cross-dialect strategy.
- Kept runtime behavior unchanged: Kit ordering is still blocked, the old direct stock endpoint still exists, and no Inventory migration, Repository, Service, Mapper, route, or database operation was added.

### Verification

- Added Inventory Model metadata, field boundary, round-trip, nullable migration actor/source, idempotency uniqueness, FK deletion protection, reverse relation, and real SQLite DDL tests; expanded Product stock upper-bound regressions.
- The complete project suite passes with 1268 tests; `compileall`, `pip check`, and `git diff --check` also pass.

## Unreleased — Inventory Domain Language and Schema (Phase 4.3.2)

**Date:** 2026-08-14

### Summary

Implemented the frozen Inventory domain vocabulary and strict Pydantic boundaries without introducing persistence or runtime endpoints.

### Implemented

- Added stable string Enums for four transaction types and three source types, plus named constants for stock/change limits, reason and idempotency-key lengths, audit identity, and bounded transaction retry attempts.
- Added `InsufficientStock`, `InventoryBalanceExceeded`, and `InventoryTransactionConflict` as HTTP-semantic `ConflictException` subclasses and exported them through the common exception package.
- Added strict adjustment input, standalone idempotency-header type, Product/global transaction queries, and UTC/time/source cross-field validation.
- Added balance, transaction/list item, and adjustment response schemas with explicit field projection, internal-key/privacy isolation, UTC datetime enforcement, arithmetic consistency, transaction-direction/source metadata validation, and adjustment-result consistency.
- Kept Order and Product runtime boundaries unchanged: Kit ordering remains blocked, direct stock setting remains available, and no Inventory table, migration, Repository, Service, Mapper, route, or database operation was added.

### Verification

- Added Inventory domain, exception middleware, request/query, response privacy, and cross-field contract tests.
- The complete project suite passes with 1249 tests; `compileall` and `git diff --check` also pass.

## Unreleased — Inventory Contract Freeze (Phase 4.3.1)

**Date:** 2026-08-13

### Summary

Completed the Phase 4.3.1 current-state audit and froze the authoritative Inventory business/API contracts without implementing runtime Inventory code.

### Important Decisions

1. `product_kits.stock` remains the single authoritative sellable balance and will be paired with immutable same-transaction ledger entries.
2. Pending Kit/mixed order creation deducts immediately; Pending cancellation restores idempotently; payment and completion do not change stock.
3. Pure Experience, pure Kit, and mixed orders are supported by the target contract. Multi-Kit writes lock ProductKit rows in ascending Product ID order and remain atomic with Order/Items/Audit.
4. ADMIN+ adjustments use strict `change`, a trimmed 1–256 character reason, and mandatory `Idempotency-Key`; Online Kit adjustment is allowed. Balance is bounded to `0..999999`.
5. The v0.6.0 Inventory cutover will remove direct `PATCH .../stock` and non-zero stock from Kit creation instead of retaining a semantically ambiguous compatibility wrapper.
6. Ledger types are `opening_balance`, `admin_adjustment`, `order_deduction`, and `order_cancellation_restore`. Existing positive balances receive migration baseline entries; zero balances do not create zero-change entries.
7. User-facing insufficient-stock errors do not expose exact availability. Database unique identities, Order state validation, stable lock ordering, and bounded whole-transaction deadlock retries provide layered protection.
8. Real MySQL 8+ concurrency tests are a release gate for v0.6.0. This step does not change the application version, schema, migration, dependencies, development database, or current runtime endpoints.

### Documentation and Verification

- Added authoritative Inventory requirement and API contract documents.
- Synchronized Product, Order, API conventions, AI context, README, and project instructions while preserving clear implemented-versus-frozen boundaries.
- Added documentation contract tests for the frozen decisions and current runtime boundary.

## Unreleased — Test Suite Domain and Layer Layout

**Date:** 2026-08-13

### Summary

Reorganized the previously flat 98-file test suite by business domain and application layer without changing test names or behavior. The root now contains only global fixtures, shared data factories, and a navigation document; Product and Order tests can be run independently or narrowed to API, Schema, Model, Repository, Service, Mapper, Validator, or storage boundaries.

### Important Decisions

1. Tests are grouped by domain first because this matches production ownership and makes Phase-focused verification discoverable.
2. Product and Order are grouped by their principal tested layer instead of a rigid unit/integration split; many existing contracts deliberately combine boundary assertions with real SQLite behavior.
3. Global fixtures remain in `tests/conftest.py`, and reusable response factories remain in `tests/support/`, so no duplicate fixture trees or nested override rules were introduced.
4. Pytest configuration remains unchanged: recursive discovery under `tests/` collects the same suite, while paths such as `tests/order/` and `tests/product/services/` provide focused runs.

### Verification

- Pytest collection finds the unchanged total of 1178 tests after all moves.
- The repository-root lookup in the relocated version contract was updated to remain location-correct.

---

## v0.5.0 (Unreleased) — Order Module Final Review (Phase 4.2.12)

**Date:** 2026-08-13

### Summary

Completed the final architecture, security, transaction, query-performance, migration, test, and documentation review for Order v1.0. Phase 4.2 is code-complete and release-ready as the unreleased v0.5.0 candidate; Phase 4.3 Inventory is the next business stage.

### Reviewed and Changed

- Reviewed all nine HTTP operations against the frozen Order requirements/API contracts and verified API → Service → Repository → Model dependency direction, authenticated identity ownership, unified envelopes, and explicit user/admin response projection.
- Reviewed creation and state-change transaction boundaries, post-lock state validation, sequential audit writes, rollback injection, order-number collision attribution/retry, stable pagination ordering, batch Product/Option loading, database item counts, and preloaded detail relations.
- Reviewed `1_20260813130455_add_order_tables.py` as a MySQL 8+ additive migration: it creates only `orders` and `order_items`, preserves four historical `RESTRICT` foreign keys and five query indexes, declares the non-transactional DDL boundary, and contains no upgrade-side destructive SQL.
- Added a cross-module amount-capacity invariant proving the maximum legal request (`10 × 99 × 99999.00`) remains below `DECIMAL(10,2)` Order capacity. This documents why no additional total-overflow business error is necessary while the existing Product price and Order item bounds remain unchanged.
- Hardened shared audit IP extraction: only valid, length-safe IPv4/IPv6 literals are persisted; malformed, overlong, or IPv6 scope-bearing `X-Forwarded-For` values fall back to the direct peer, and an invalid/missing peer becomes `unknown`. A real Order HTTP test proves hostile proxy text cannot turn an otherwise valid audited mutation into a 500 or partial write.
- Advanced the unreleased application candidate from v0.4.0 to v0.5.0 in code defaults, example environment, version contracts, README, project instructions, architecture context, and Order requirement/API status. Advanced the database design document to v1.4 for the Order table addition.

### Important Decisions

1. **Release candidate, not a release:** v0.5.0 identifies the completed local code candidate. No Git tag, GitHub Release, commit, push, MySQL migration execution, Aerich fake, or development-database rebuild is implied.
2. **Aggregate constraints are reviewed together:** individual price, item-count, and quantity limits form a safe maximum total. A regression invariant now alerts future maintainers if any one bound changes enough to exceed storage capacity.
3. **Proxy input remains a trust boundary:** syntax and storage safety are enforced in the application, while deployment must still configure the ingress proxy to overwrite untrusted forwarding headers.
4. **Inventory remains out of scope:** Order continues to reject every Kit item before writes and never reads, deducts, or restores `ProductKit.stock`; those concurrency semantics belong to Phase 4.3.
5. **Migration execution is separately authorized:** the reviewed Order migration remains offline and unapplied. Production rollout still requires target-schema audit, backup/snapshot, staging verification, explicit authorization, and a tested rollback plan.

### Verification

- All 392 Order-related tests pass, including contracts, Models, migration DDL, Repository, Service, Mapper, routes, real JWT/SQLite HTTP flows, transaction rollback, and amount-capacity invariants.
- Six focused request-IP tests pass, plus the real Order audit integration regression.
- The complete project suite passes with 1178 tests.
- `compileall`, dependency integrity (`pip check`), and whitespace/error-marker review (`git diff --check`) pass.
- Ruff was not run because it is not installed in the project environment or declared in `requirements.txt`.

### Release Notes

- No dependency was added.
- The MySQL initial migration and Order incremental migration remain unapplied; the local development database was not rebuilt or mutated.
- `docs/02_database/er_diagram.png` remains an untracked user-owned artifact and was not modified.

---

## Unreleased — Order HTTP Error and Boundary Matrix (Phase 4.2.11)

**Date:** 2026-08-13

### Summary

Completed the full real-JWT/SQLite HTTP error and boundary matrix for all nine Order endpoints. The matrix now verifies authoritative Experience snapshots and Decimal totals, request-shape anti-forgery, Product/Option/Kit rejection, visibility and ADMIN+ permissions, pagination and combined filters, every illegal state precondition, ordered audit history, transactional failure rollback, and order-number collision retry behavior.

### Added

- Real HTTP creation coverage for multiple distinct Options, exact Decimal arithmetic, immutable historical snapshots, 1/99 quantity bounds, 500-character remarks, empty-remark normalization, duplicate/empty/oversized item collections, strict scalar types, and all server-owned field forgery attempts.
- Product and Option availability cases for missing, draft/offline/deleted, missing/deleted/mismatched Option, plus explicit Kit rejection with unchanged `ProductKit.stock` and no partial Order/audit writes.
- Full authentication and ADMIN+ route matrices, uniform missing-order/resource-hiding 404 behavior, user/admin list visibility, pagination, exact lookup, status/user/time combined filters, UTC/range validation, and reverse-chronological audit pagination.
- All nine illegal status-operation preconditions across cancel, mark-paid, and complete, with stable `40921` payloads and proof that neither status nor audit changes.
- HTTP-level fault injection after audit writes and at post-write reloads, proving atomic rollback of Order/Items/status/audit, plus collision retry success and third-collision exhaustion without partial artifacts.
- A shared transport dependency that rejects any non-empty request body on cancel/paid/complete while preserving body-free OpenAPI operations.

### Important Decisions

1. **Negative-space contracts are enforced:** omitting `requestBody` from OpenAPI is documentation, not runtime validation. The three fixed state-use-case PATCH routes now explicitly reject `{}`, `null`, or any other non-empty body with the unified HTTP 422 envelope before mutation.
2. **HTTP tests exercise real boundaries:** business-error and rollback cases use real JWT authentication, SQLite, repositories, services, mappers, and exception middleware. Dependency overrides are limited to deterministic generators and deliberate failure injection.
3. **Server authority is tested end to end:** authenticated identity, order status, Product/Option snapshots, unit prices, subtotals, and totals cannot be supplied by clients and remain frozen after source catalog changes.
4. **Failure responses disclose no internals:** injected runtime and database-integrity failures are logged server-side, return only the shared generic 500 envelope, and leave no partial aggregate or audit state.

### Verification

- 79 new focused HTTP matrix test instances pass across creation boundaries, query/permission/state behavior, and transaction/collision failure injection.
- Existing route architecture and mocked adaptation tests continue to pass with strict no-body enforcement and unchanged OpenAPI request-body declarations.
- 104 focused Order HTTP/route/architecture tests pass together; all 390 Order-related tests pass.
- The complete project suite passes with 1170 tests.

### Release Notes

- No dependency, database schema, migration, or application-version change was made in this step.
- The existing offline MySQL Order migration remains unapplied; no development database was rebuilt.
- Phase 4.2.12 final checklist, migration review, and version decision remain pending before declaring the Order module release-ready.

---

## Unreleased — Order FastAPI Routes (Phase 4.2.10)

**Date:** 2026-08-13

### Summary

Exposed the implemented Order domain through four authenticated user endpoints and five ADMIN+ endpoints. Added the Order composition root, strict request-to-domain adaptation, Mapper serialization, unified success/error envelopes, exact OpenAPI contracts, and core real JWT/SQLite HTTP lifecycle coverage. The exhaustive Phase 4.2.11 HTTP error/boundary matrix and Phase 4.2.12 final review remain pending.

### Added

- `get_order_service()` composition root wiring OrderRepository, ProductRepository, and the shared AuditLogService/AuditLogRepository.
- User routes for Experience creation, paginated own-order listing, owner-scoped detail, and Pending cancellation.
- ADMIN+ routes for filtered listing, unrestricted detail, manual payment confirmation, completion, and paginated Order audit history.
- Explicit OrderCreate-item to `OrderItemInput` adaptation so Service remains independent of transport Schemas.
- Authenticated identity as the sole source of `user_id`/`operator_id`, plus shared client-IP extraction for every audited HTTP mutation.
- Precise `SuccessResponse[T]` and shared `ErrorResponse` declarations, HTTP 201 creation, HTTP 200 queries/mutations, PATCH operations without request bodies, and one-time router registration tests.
- Real JWT/SQLite flows covering creation, Decimal snapshot response, user list, resource hiding, ADMIN+ access, paid/completed transitions, owner cancellation, ordered audits, source IPs, and audit privacy.
- Unified missing-Bearer handling through `AuthenticationException` by setting HTTPBearer `auto_error=False`; all routes using the existing authentication dependency now return the project error envelope for missing credentials.

### Important Decisions

1. **Composition root:** concrete repositories and shared infrastructure are assembled only in `app/api/deps.py`. Route modules import Service/Mapper/Schemas but never business repositories or Order/Product persistence models.
2. **Identity is server-owned:** create and owner-scoped routes use `current_user.id`; admin mutations use `current_admin.id`. Extra `user_id`, price, amount, or snapshot fields are rejected by strict request Schemas before Service execution.
3. **Authentication versus authorization:** missing credentials return HTTP 401 with the unified envelope, while an authenticated normal user accessing ADMIN+ routes returns HTTP 403. The pre-existing invalid/expired Token exception remains code `1006`/HTTP 400 pending a separate User-contract migration, so Order OpenAPI documents both 400 and 401.
4. **Single serialization pass:** routes call the dedicated Mapper and `model_dump(mode="json")`, then pass the validated data to `success()` with `response_model=None`; OpenAPI uses explicit generic response declarations without runtime Decimal revalidation.
5. **No body for state PATCH:** cancel, paid, and complete select fixed Service use cases entirely through the path and authenticated identity; clients cannot submit an arbitrary target state.

### Verification

- 25 focused Order route/architecture/integration test instances were added and pass after the unified-auth additions.
- 84 combined Order/User/Product route regressions pass after changing the shared HTTPBearer behavior.
- All 311 Order-related contracts pass together.
- Python compilation and dependency integrity checks pass; the complete suite passes with 1091 tests.

### Release Notes

- The nine documented Order endpoints are now registered and callable.
- No new dependency, database schema change, migration, or application-version change was made.
- The existing offline MySQL Order migration remains unapplied; no development database was rebuilt.
- Phase 4.2.11 must still expand the complete HTTP business-error/input-boundary matrix. Phase 4.2.12 must perform final checklist/migration/version review before declaring the Order module release-ready.

---

## Unreleased — Order API Mapper (Phase 4.2.9)

**Date:** 2026-08-13

### Summary

Implemented the synchronous Order API mapping boundary for user/admin lists, user/admin details, OrderItem snapshots, and lightweight status-transition responses. The Mapper performs explicit field projection and strict Out Schema validation without querying or mutating ORM aggregates. Dependency wiring and HTTP routes remain outside this slice.

### Added

- Authoritative OrderStatus and DayType `{value, label}` mapping using the existing common registries.
- Explicit OrderItem snapshot mapping with Decimal price/subtotal preservation and no live Product/Option reads.
- Separate user/admin list and detail projections; user responses never read User relations, while admin responses add only `user_id` and `user_nickname`.
- User/admin Page mapping that preserves total, page, page size, and pages while consuming Repository `item_count` annotations.
- Lightweight status-response mapping from a relation-free Order returned by the status transaction reload.
- Aggregate-integrity checks that reject an OrderItem attached to a different Order before serialization.
- Architecture, atomic conversion, projection, strict validation, real Repository zero-SQL, and non-mutation tests.

### Important Decisions

1. **Explicit projection:** each endpoint class has a dedicated mapper and Out Schema. Fields are assembled from a whitelist rather than passing ORM models directly to Pydantic, making user/admin isolation visible in code.
2. **Zero-SQL mapping:** lists consume the Repository's `item_count` annotation, details consume preloaded Items/User, and status responses consume a lightweight Order. Mapper functions contain no async code, Repository/Service imports, or ORM query calls.
3. **Snapshot-only items:** historical Item output uses the stored name, Option dimensions, day type, unit price, quantity, and subtotal. It never follows Product or ExperienceOption relationships that may have changed since purchase.
4. **Schema owns wire formatting:** Mapper preserves domain `Decimal` and Enum values; strict response Schemas validate arithmetic and serialize amounts as two-decimal strings. This avoids duplicating formatting rules in two layers.
5. **Non-mutating composition:** Mapper builds new dictionaries and Schema objects. Real aggregate snapshots prove the source Order, User, Items, relationship lists, and annotated fields are unchanged.

### Verification

- 23 focused Order Mapper tests pass.
- All 286 Order-related contracts pass together.
- The complete suite passes with 1066 tests after the Mapper and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until dependency composition and user/admin routes are implemented.

---

## Unreleased — Order Status Transition Service (Phase 4.2.8)

**Date:** 2026-08-13

### Summary

Implemented the three frozen Order state-transition use cases: owner cancellation, ADMIN+ manual payment confirmation, and ADMIN+ completion. Each use case locks the visible Order inside its transaction, validates the latest state, and atomically persists the status, audit, and lightweight response reload. Mapping, dependency wiring, and HTTP routes remain outside this slice.

### Added

- `OrderService.cancel_order()` for owner-scoped `pending → cancelled` with SQL-level visibility hiding.
- `OrderService.mark_order_paid()` for the temporary ADMIN+ `pending → paid` operational entry point.
- `OrderService.complete_order()` for ADMIN+ `paid → completed`.
- Stable `cancel`, `mark_paid`, and `complete` operation constants for `OrderStatusConflict` payloads.
- A private transition template that performs transaction-bound row locking, post-lock state validation, status persistence, sequential audit, and response reload without exposing a generic public status mutator.
- Unit and real SQLite tests for all success paths, status conflicts, missing/hidden resources, audit summaries, repeated-transition serial results, and audit/reload rollback.
- A static Repository contract proving `get_order_for_update()` retains `select_for_update()` for MySQL pessimistic locking semantics.

### Important Decisions

1. **Lock then decide:** state validity is checked only after `SELECT ... FOR UPDATE` returns the latest visible row. A pre-transaction read cannot authorize a mutation because another transaction may change the state before the write.
2. **Visibility in the lock query:** owner cancellation applies `(order_id, user_id)` before locking. Missing and foreign Orders therefore produce the same `40411 OrderNotFound`, without loading and revealing another user's row.
3. **No generic transition API:** callers select one of three named use cases and cannot supply an arbitrary target status. The private template receives only constants fixed by those public methods.
4. **Atomic status event:** status update, compact `before_status`/`after_status` audit, and response reload share one connection. Audit or reload failure restores the original status and leaves no audit row.
5. **SQLite verification boundary:** real SQLite tests prove equivalent serial outcomes and rollback behavior; a static `select_for_update()` contract preserves the intended MySQL row-lock implementation because SQLite itself cannot demonstrate MySQL row-level locking.
6. State transitions do not read or restore ProductKit stock. Inventory effects remain Phase 4.3 work.

### Verification

- 18 new status-transition test instances were added; the focused status-Service and architecture command passes with 20 tests including existing architecture guards.
- All 262 Order-related contracts pass together.
- The complete suite passes with 1043 tests after the status-Service and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until Mapper, dependency composition, and routes are implemented.

---

## Unreleased — Order Creation Service (Phase 4.2.7)

**Date:** 2026-08-13

### Summary

Implemented the Experience-only Order creation orchestration layer. The Service now validates Product/Option aggregates in batches, creates database-authoritative Decimal snapshots, and atomically persists the Order aggregate plus its non-sensitive audit record. Status transitions, mapping, dependency wiring, and HTTP routes remain outside this slice.

### Added

- `OrderItemInput` as a Service-domain input containing only Product ID, ExperienceOption ID, and quantity; no client-controlled snapshot fields enter the use case.
- Batch Product/Option resolution with stable request-order errors, Kit-before-Option behavior, and unified unavailable semantics for missing, deleted, offline, or mismatched aggregates.
- Database-authoritative Product name, Option configuration, price, subtotal, and total snapshots using `Decimal` arithmetic.
- One transaction for Order creation, one-shot Item bulk insertion, sequential `CREATE_ORDER` audit, and complete aggregate reload on the same connection.
- `OrderRepository.order_number_exists()` for post-rollback collision attribution and whole-transaction retry with a fresh order number, capped at three attempts.
- Unit and real SQLite tests for validation priority, batch access, snapshot immutability, audit privacy, complete rollback, collision success, retry exhaustion, and non-collision `IntegrityError` preservation.

### Important Decisions

1. **Database source of truth:** clients cannot submit names, configuration, prices, subtotals, totals, status, user ID, or order number. Every persisted and returned snapshot is reconstructed from the current valid Product/Option rows.
2. **Stable error priority:** bulk loading reduces query count without changing observable validation order. Items are checked in request order; each Item checks the known Kit boundary before Product availability and Option validity/ownership.
3. **Atomic aggregate:** Order, Items, audit, and response reload use one transaction connection. Even an exception after the audit INSERT rolls back every write, and validation failures occur before a transaction or audit begins.
4. **Fresh-transaction retry:** an `IntegrityError` leaves a transaction unusable. Collision attribution therefore occurs only after leaving the transaction context; a confirmed order-number collision opens a new transaction, while unrelated integrity errors retain their original cause.
5. Phase 4.2 creation performs no ProductKit stock read or write. Kit remains an explicit `40922` boundary until the Inventory concurrency model is designed in Phase 4.3.

### Verification

- 16 focused creation-Service unit and real SQLite integration tests pass.
- All 245 Order-related contracts pass together.
- The complete suite passes with 1025 tests after the creation-Service and documentation updates.

### Release Notes

- No new dependency, database schema change, migration, endpoint, or application-version change is required by this slice.
- The existing offline Order migration remains unapplied; no development database was rebuilt.
- Order HTTP APIs remain unavailable until Mapper, dependency composition, and routes are implemented. State-transition Services also remain unimplemented.

---

## Unreleased — Order Query Service (Phase 4.2.6)

**Date:** 2026-08-13

### Summary

Implemented the read-only Order business orchestration layer: user/admin lists, user/admin details, and administrator Order audit-history queries. This slice adds visibility and error semantics without introducing creation, status transitions, response mapping, dependency wiring, or routes.

### Added

- `OrderService.list_user_orders()` / `get_user_order_detail()` with SQL-scoped user visibility and uniform `OrderNotFound` behavior for missing and foreign resources.
- `OrderService.list_admin_orders()` / `get_admin_order_detail()` forwarding the frozen paging, exact order-number, user, status, and UTC time-range contract.
- `OrderService.list_order_audit_logs()` with a lightweight Order existence check before delegation to the shared `AuditLogService` and `target_type="order"` pagination.
- `OrderRepository.get_order_by_id()` as a relation-free existence lookup with optional caller connection.
- A common `OrderStatusValue` API type plus complete `ORDER_STATUS_BY_VALUE` reverse registry for explicit API-string-to-database-Enum translation.
- Mock orchestration, architecture, real SQLite visibility, aggregation, relation-preloading, audit isolation, orphan-audit, and named-exception tests.

### Important Decisions

1. **Resource-enumeration protection:** user detail always queries by `(order_id, user_id)`. Both a missing ID and another user's ID produce Repository `None` and the same `40411 OrderNotFound`; Service never loads a foreign Order and exposes a different ownership error.
2. **Boundary translation:** Query Schema and Service accept stable API values (`pending`, `paid`, `cancelled`, `completed`), while Repository accepts `OrderStatus`. The explicit reverse registry is the only translation boundary, preventing HTTP strings from leaking into persistence code and IntEnum integers from leaking into the API.
3. **Existence before history:** an Order audit query first proves the Order row exists. A stale or orphan `audit_logs` row cannot make a nonexistent Order appear queryable.
4. Query Service performs no direct ORM operation, opens no transaction for pure reads, does not call ProductService, and delegates audit access only through the documented shared-service exception.

### Verification

- 59 focused Enum/Query Schema/Service/Repository tests pass after boundary translation.
- All 212 `test_order_*.py` contracts pass together.
- The complete suite passes with 1009 tests after the query-Service and documentation updates.

### Release Notes

- No database schema, migration, dependency, endpoint, or application-version change is required.
- The Order API remains unavailable until Mapper and routes are implemented.
- Order creation transaction, order-number collision retry, state-transition/audit transactions, Mapper, and routes remain unimplemented.

---

## Unreleased — Order Repository and Number Generator (Phase 4.2.5)

**Date:** 2026-08-13

### Summary

Implemented the Order data-access boundary and dependency-free order-number generator. This slice provides the transaction-aware primitives required by the later query, creation, and state-transition Services without introducing business exceptions, service orchestration, mapping, or HTTP routes.

### Added

- Standard-library `OD` + 26-character Crockford Base32 ULID generation using UTC Unix milliseconds and `secrets.token_bytes()`; no Redis, database sequence, third-party ULID package, or mutable generator state.
- `OrderRepository` creation, one-shot OrderItem `bulk_create()`, ID/number detail loading, optional SQL-level user visibility, transaction-bound `SELECT ... FOR UPDATE`, status persistence, and user/admin pagination.
- Database `COUNT(items)` list summaries, stable `created_at DESC, id DESC` pagination, exact admin order-number/user/status filters, inclusive `created_from`, exclusive `created_to`, and admin User preloading.
- Product/ExperienceOption set loaders in `ProductRepository`; each executes one query, includes logically deleted rows for Service-level availability decisions, and accepts the caller's transaction connection.
- Architecture, source-selection, real SQLite transaction, rollback, query-count, visibility, filtering, paging, snapshot, and order-number tests.

### Important Decisions

1. Repository methods do not raise Order business exceptions or decide ownership, availability, Kit policy, snapshot arithmetic, retry policy, or state transitions. User visibility is expressed as an optional SQL predicate so the query Service can hide missing and foreign resources uniformly.
2. List queries aggregate Item row count and do not preload Item collections. Detail queries preload stable Item order and the User relation in constant query count; the later Mapper must perform zero SQL.
3. `update_status()` persists only a status already approved by Service. Every state-transition Service must lock and recheck the row in the same transaction before calling it.
4. The generator provides approximate time ordering only. `created_at DESC, id DESC` remains authoritative; the database unique constraint and later Service transaction retry remain the collision boundary.

### Verification

- 28 focused generator, Repository, Product batch-loader, architecture, transaction, and performance tests pass, including uncommitted aggregate reload on the caller's transaction connection.
- All 195 `test_order_*.py` domain, Schema, Model, migration, generator, and Repository tests pass together; including the three Product batch-loader contracts, the combined slice has 198 passing tests.
- The complete suite passes with 992 tests after the Repository and documentation updates.

### Release Notes

- No database schema, migration, dependency, endpoint, or application-version change is required.
- The existing Order MySQL migration remains offline and unapplied. No development database was rebuilt or modified outside disposable test schemas.
- Order query Service, creation transaction, status/audit Service, Mapper, and routes remain unimplemented.

---

## Unreleased — Order Models and MySQL Migration (Phase 4.2.4)

**Date:** 2026-08-13

### Summary

Implemented the Order persistence contract: registered `Order` / `OrderItem` Tortoise Models, verified their real SQLite schema and behavior, and generated a reviewed MySQL 8+ incremental migration without connecting to or changing any database.

### Added

- `Order` with unique `OD` + ULID order number, User `RESTRICT` relation, exact Decimal total, `SmallIntField` status with ORM/database default `0`, nullable remark, and four named stable-pagination indexes.
- `OrderItem` with Order/Product/ExperienceOption `RESTRICT` relations, nullable future-Kit Option fields, immutable product/configuration/price snapshots, strict quantities and amounts, and the named `(order_id, id)` index.
- Real temporary-SQLite contracts for Model metadata, default values, Decimal/Enum round trips, reverse relations, field boundaries, unique order numbers, physical-delete protection, exact index columns, nullable extension fields, and DDL foreign keys.
- Offline MySQL migration `1_20260813130455_add_order_tables.py` plus static contracts for its exact table scope, field types, defaults, four foreign keys, five indexes, non-transactional MySQL DDL semantics, safe child-before-parent downgrade order, and Aerich model state.

### Important Decisions

1. Order status uses the project's actual Tortoise/MySQL integer-enum mapping, `SmallIntField` / `SMALLINT`, rather than the stale `TINYINT` wording in the frozen draft. Database design and DBML were corrected together.
2. Cross-field Option completeness, duplicate Item combinations, Product availability, snapshot arithmetic, Kit rejection, and state transitions remain Schema/Service responsibilities; Models contain no business workflow or database queries.
3. Nullable Option fields remain in the physical table for Phase 4.3 Kit compatibility, while Phase 4.2 Service must reject every Kit Item.
4. Aerich's generated MySQL migration was reviewed to remove `IF NOT EXISTS`, declare `RUN_IN_TRANSACTION = False`, and drop `order_items` before `orders` on an explicitly authorized downgrade.

### Verification

- 22 focused Order Model tests pass.
- 29 combined Order Model, Order migration, and initial MySQL migration tests pass.
- The complete suite passes with 964 tests after the persistence and documentation updates.

### Release Notes

- The incremental migration was generated with `AERICH_MYSQL_VERSION=8.0` and `aerich --app models migrate --offline`; no `upgrade`, `downgrade`, `--fake`, development-database rebuild, or live database connection was performed.
- Applying the migration later requires a separately authorized target, schema audit, backup, and execution plan. Its downgrade deletes all Order data and must never be treated as routine rollback.
- No dependency, endpoint, or application-version change is required. Order Repository, Service, Mapper, routes, and order-number generator remain unimplemented.

---

## Unreleased — Order Schema Contracts (Phase 4.2.3)

**Date:** 2026-08-13

### Summary

Implemented strict Order creation, list-query, and user/admin response Schema contracts without introducing database Models, business Services, Mappers, or routes.

### Added

- `OrderItemCreate` and `OrderCreate` with strict IDs/quantity, 1–10 Items, duplicate Product/Option rejection, remark normalization, unknown-field rejection, and server-owned field isolation.
- `OrderListQuery` and `AdminOrderListQuery` with API-string status values, exact order-number filtering, safe query-ID parsing, UTC-aware date ranges, and strict range ordering.
- `OrderItemOut`, user/admin list and detail outputs, and lightweight status output with explicit field whitelists.
- Decimal-only response amounts serialized as fixed two-place strings, Product-price upper bounds, status/day-type value-label consistency, Item subtotal validation, and Order total validation.
- User/admin isolation contracts: user responses omit all user data; admin responses add only `user_id` and `user_nickname`; detail responses do not repeat the list-derived `item_count`.

### Important Decisions

1. Query status accepts only API values (`pending`, `paid`, `cancelled`, `completed`) and never database IntEnum integers.
2. Query datetimes and response datetimes must be explicitly UTC; naive and non-UTC-offset values are rejected.
3. Out Schema accepts internal monetary values only as `Decimal`; strings and floats are rejected before fixed two-place serialization.
4. The response layer validates snapshot arithmetic but does not query or mutate any ORM object.

### Verification

- 116 focused Order Schema tests pass; all 144 Order domain and Schema tests pass together.
- The complete suite passes with 938 tests after all implementation and documentation updates.

### Release Notes

- No database migration, dependency, endpoint, or application-version change is required.
- Order Model, Repository, Service, Mapper, routes, and migration remain unimplemented.

---

## Unreleased — Order Domain Contracts (Phase 4.2.2)

**Date:** 2026-08-13

### Summary

Implemented the first Order code slice after the v1.0 contract freeze: database status Enum, fixed business boundaries, API display registries, audit constants, and HTTP-semantic named exceptions. No database, Schema, Service, or route behavior is introduced by this slice.

### Added

- `OrderStatus(IntEnum)` with stable database values 0–3.
- Explicit OrderStatus API value and Chinese label registries, preventing IntEnum database integers from leaking into API status output.
- Frozen constants for Item count, quantity, remark length, ULID order-number shape and retry limit, Phase 4.3 Kit boundary, and four audit actions.
- `OrderNotFound`, `OrderStatusConflict`, `KitOrderingRequiresInventory`, `OrderProductUnavailable`, and `OrderOptionUnavailable`, exported through the common exception package.
- Enum/constant and exception contracts covering inheritance, payloads, invalid construction, JSON behavior, and global HTTP 404/409/422 mappings.

### Important Decisions

1. OrderStatus remains an `IntEnum` for the database; API values are obtained only through an explicit registry.
2. Named exceptions validate their structured payload at construction so invalid IDs or status types cannot produce unstable public error data.
3. Request-shape errors remain the responsibility of the next Schema stage and are not duplicated as business exceptions.

### Verification

- 27 focused Order domain contract tests pass.
- The complete suite passes with 821 tests after all implementation and documentation updates.

### Release Notes

- No database migration, dependency, endpoint, or application-version change is required.
- Order Schema, Model, Repository, Service, Mapper, routes, and migration remain unimplemented.

---

## v0.4.0 — Product Module Implementation (Unreleased)

**Date:** 2026-08-13

### Summary

Completed the Product module implementation and its final architecture, OpenAPI, documentation, and release-readiness review. The Product API contract is now v1.0 Implemented. This section is the v0.4.0 release-candidate summary; the following Unreleased Phase 4.1 sections retain the detailed implementation history.

### Changed

- Added precise generic OpenAPI success and error envelopes for all 22 Product operations while preserving the Mapper as the single runtime serialization boundary.
- Verified that all 19 admin Product operations require Bearer authentication, all 3 public Product operations remain anonymous, and every application operation ID is unique.
- Removed the obsolete Phase 3 demo `GET /api/v1/admin/users` registration; the formal admin-users router remains the only owner of that path.
- Synchronized Product business rules, API conventions, architecture, AI context, and project instructions with the implemented Phase 4.1 state.

### Important Decisions

1. Product routes declare precise OpenAPI models through `responses` with `response_model=None`; this avoids revalidating Mapper-produced decimal strings while retaining strict one-pass Out Schema validation.
2. The Product API document advances from Draft v0.9 to Implemented v1.0. This is a contract-document version, not an application release or Git tag.
3. The code/default configuration advances from v0.3.0 to the unreleased v0.4.0 candidate because this release adds the complete Product feature set rather than a backward-compatible bug fix. No Git tag or release is created by this change.

### Verification

- 51 focused Product API route, OpenAPI, and real SQLite HTTP tests pass.
- The complete suite passes with 794 tests, including two application-version consistency contracts.
- Python compilation, dependency integrity, OpenAPI warning/operation/security checks, whitespace, debug-output, and unfinished-marker checks pass.

### Release Notes

- No new database migration is introduced by this review. The existing MySQL 8+ initial migration remains unapplied and still requires an explicitly authorized deployment procedure.
- No cleanup command was run against the development database or upload directory.

---

## Unreleased — Product Image Delayed Cleanup (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented a retryable operational batch that removes local files only after ProductImage logical deletion is durably committed, without coupling irreversible file I/O to the DELETE request transaction.

### Added

- Repository ID-cursor scan for deleted images at or before an explicit cutoff.
- `ProductImageCleanupService` with managed-URL validation, active-reference protection, idempotent deletion, per-item failure isolation, and batch statistics.
- `python -m app.tasks.product_image_cleanup --before <timezone-aware ISO 8601>` operational command with bounded batches and failure exit status.
- Real SQLite and temporary-filesystem tests for cutoff selection, cursor pagination, managed/external URLs, active URL references, missing objects, failures, and unsafe parameters.

### Important Decisions

1. Cleanup does not run inside ProductService, FastAPI BackgroundTasks, application startup, or the logical-delete transaction.
2. Existing `is_deleted`, `updated_at`, and `image_url` fields are the durable retry source; ProductImage and AuditLog records remain intact, so no cleanup-status table or migration is needed.
3. The cutoff is mandatory and timezone-aware. Retention policy remains an explicit deployment choice rather than an application magic number; the command defaults to preview and requires `--apply` for deletion.
4. A failed object remains discoverable on the next run. A missing object is treated as idempotent success, while unmanaged/external URLs are never passed to local storage deletion.

### Verification

- 39 focused storage, Repository, cleanup Service, task orchestration, architecture, real SQLite, filesystem, batch-query, and preview-safety tests pass.

### Operational Note

- The command is implemented but was not executed against the workspace development database or upload directory. Production scheduling remains a deployment responsibility.
- No database migration, dependency, API endpoint, or application version change is required.

---

## Unreleased — Product Audit History API (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented the shared AuditLog read path and exposed Product operation history as an ADMIN+ paginated endpoint without embedding audit data in Product detail or duplicating its Schema in the Product module.

### Added

- Shared `AuditLogRepository.list_logs()` and `AuditLogService.list_logs()` target-scoped pagination.
- Shared `AuditLogOut`, strict pagination query Schema, and Audit API Mapper field whitelist.
- `GET /api/v1/admin/products/{product_id}/audit-logs`, including logically deleted Product records.
- Repository, Service, Mapper, permission, validation, route-contract, and real SQLite HTTP tests.

### Important Decisions

1. ProductService checks Product existence with `include_deleted=true`, then delegates the actual query to the shared AuditLogService.
2. Logs are ordered by `created_at DESC, id DESC` so pagination remains deterministic when timestamps collide.
3. The public audit shape omits `updated_at`; audit entries are immutable event records for this read contract.
4. Audit logs remain an independent paginated resource and are not loaded into Product list or detail queries.

### Verification

- 54 focused Audit/Product route, Service, Mapper, architecture, permission, validation, and real SQLite tests pass.

### Known Limitations

- ProductImage delayed physical cleanup was completed by the later stage above.
- No database migration, dependency, or application version change is required.

---

## Unreleased — Product Multipart Image Routes (Phase 4.1)

**Date:** 2026-08-13

### Summary

Connected Product and ExperienceOption image uploads to ADMIN+ multipart FastAPI routes, the completed local storage adapter, ProductService, API mappers, and development static-file serving.

### Added

- HTTP 201 `POST /api/v1/admin/products/{product_id}/images` and `POST /api/v1/admin/options/{option_id}/images`.
- Strict multipart Pydantic forms: public images accept only file/is_cover/sort; Option images accept only file/sort and reject `is_cover`.
- API upload orchestration that runs synchronous storage off the event loop, closes spooled upload files, and compensates a stored file when ProductService fails without masking the original exception.
- Deferred-directory local static serving for generated `/uploads/products/{uuid}.{ext}` URLs.
- Real SQLite multipart tests covering file persistence, Product/Option ownership, audit ordering, safe filenames, response mapping, and static retrieval.

### Important Decisions

1. ProductService remains unaware of UploadFile and storage. The API boundary passes only the generated image URL.
2. Multipart validation errors use the existing unified request-validation envelope; invalid content/MIME/size uses named `42221 InvalidImageFile`.
3. Compensation failures are logged with the opaque storage key and do not replace the original Service exception.
4. Local static serving is a development adapter. A non-path external base URL is not mounted and can be supplied by a future object-storage deployment adapter.

### Verification

- 57 focused multipart route, real SQLite, storage, security, and architecture tests pass.

### Known Limitations

- ProductImage delayed physical cleanup was completed by the later stage above.
- Product audit-history listing was completed by the later stage above.
- No database migration or application version change is required. Runtime dependency `python-multipart==0.0.32` was added.

---

## Unreleased — Product Image Storage Adapter (Phase 4.1)

**Date:** 2026-08-13

### Summary

Implemented the Product image validation and local-storage boundary without coupling ProductService to FastAPI or file I/O. Multipart routes remain a separate next step.

### Added

- `LocalImageStorage` with a 2 MiB bounded read, jpg/png/webp signature detection, declared-MIME consistency checks, server-generated UUID keys, non-overwriting atomic publication, URL generation, and idempotent compensation deletion.
- Named `42221 InvalidImageFile` with a stable `data.reason` contract.
- Environment-configurable local upload directory/base URL, plus repository ignore rules for runtime uploads.
- Unit, security, architecture, and global exception-mapping tests.

### Important Decisions

1. Client filenames never enter the storage key or filesystem path; only adapter-generated lowercase UUID keys and allowlisted extensions are accepted.
2. Validation happens before the destination directory or final object is created. Temporary files are cleaned on any publication failure, and an existing target is never overwritten.
3. The adapter returns both a public URL for ProductService and an opaque key for route-level compensation. It does not import FastAPI, Models, Repositories, or Services.
4. Multipart parsing, calling ProductService, compensating a stored file when Service fails, static-file serving, and delayed cleanup after logical deletion remain in the next API integration step.

### Verification

- 23 focused storage, security, architecture, exception-contract, and HTTP exception-mapping tests pass.

### Known Limitations

- Resolved by the later Product Multipart Image Routes stage above: both image-create endpoints are now registered and callable.
- No database schema, migration, dependency, or application version change is required.

---

## Unreleased — Product JSON FastAPI Routes (Phase 4.1)

**Date:** 2026-08-13

### Summary

Connected the completed Product Service and API Mapper layers to 19 callable FastAPI endpoints for public/admin queries and ordinary JSON mutations. Multipart image creation and audit-history listing were separate follow-up stages at that point and are now complete above.

### Added

- Public Product list plus Experience/Kit detail routes.
- ADMIN+ Product list/detail, create/update/delete, online/offline, Option lifecycle, Kit price/stock, and ProductImage metadata/delete routes.
- `get_product_service()` API composition dependency for ProductRepository + shared AuditLogService + ProductService.
- Global `RequestValidationError` conversion to the project response envelope without echoing original input values.
- Route contract, architecture, permission, validation, status-code, response isolation, and real SQLite HTTP lifecycle tests.

### Important Decisions

1. Routes depend on ProductService, never Product Model/Repository; they only validate transport input, invoke Service, map the result, and call `success()`.
2. Product creates return HTTP 201. ExperienceOption creates return 201 for a new record and 200 when restoring its historical ID.
3. Query parameter models use FastAPI `Query()` so `extra="forbid"` rejects unknown query parameters at the HTTP boundary.
4. PATCH routes pass `model_dump(exclude_unset=True)` to preserve missing versus explicit null semantics.
5. ProductImage JSON PATCH/DELETE were included in this stage because they required no file content; the later Product Multipart Image Routes stage above registered both image POST routes.
6. Request validation errors expose only location, message, and type. Raw request values are not included in the response or warning log.

### Verification

- 31 focused Product API route, architecture, and real SQLite integration tests pass.
- All 629 Product tests pass.
- Real HTTP flows cover Experience/Kit creation, queries, state transitions, mutations, response IDs, availability, and persisted ordered audits.

### Known Limitations

- Product/Option multipart creation, validation/storage, Service-failure compensation, delayed cleanup, and Product audit-history listing were completed by the later stages above.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product API Mapper (Phase 4.1)

**Date:** 2026-08-13

### Summary

Completed the Product API response adaptation boundary. Product Service ORM/Page results can now be converted synchronously and without SQL into strict user/admin Out Schemas. FastAPI routes and image file storage remain separate pending work.

### Added

- `app/api/mappers/product.py` mappings for user/admin pages, Experience/Kit details, Product/Option/Image/Kit mutation responses, image ownership, dimensions, availability, covers, prices, and value labels.
- Authoritative Product type/status/day-type label registries and open duration/participant label rules in Product constants.
- Architecture tests prohibiting async/await, ORM query/mutation calls, and Service/Repository/FastAPI/Redis dependencies.
- Unit and real SQLite tests for response whitelists, user/admin isolation, aggregate completeness, ID semantics, stable dimensions, zero SQL, and zero ORM mutation.

### Important Decisions

1. Mapper functions construct explicit whitelisted dictionaries and immediately validate them with the corresponding Product Out Schema; prices remain `Decimal` until Schema serialization fixes them to two decimal places.
2. User mappers fail fast for non-Online/deleted/incomplete aggregates instead of fabricating empty covers, zero prices, or missing Kit extensions. Admin mappers permit documented Draft emptiness.
3. Mapper consumes Repository-established relation ordering and never reloads or expands the data scope. Unprefetched relationships remain programming errors.
4. Kit price/stock mutation response IDs use `ProductKit.product_id`, never the ProductKit table primary key.
5. Existing Service return values and Repository preloads already satisfy response mapping, so no Service/Repository compatibility changes were needed.

### Verification

- 32 focused Mapper unit and architecture tests pass.
- 3 real SQLite Mapper integration tests pass with SQL execution disabled after Repository loading.
- All 597 Product tests pass.

### Known Limitations

- Ordinary Product JSON FastAPI routes, ADMIN+ dependencies, and `success()` integration are complete. Multipart parsing, image validation/storage, and external-file compensation remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ProductImage Lifecycle Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed ProductImage database lifecycle orchestration: public and Option image creation, atomic cover switching, partial metadata updates, and logical deletion. Multipart validation, external storage, and API routing remain separate pending integration work.

### Added

- `ProductImageNotFound` (`40403`) and `OptionImageCannotBeCover` (`40021`) with stable HTTP mappings.
- Product and Option image creation Services with fixed ownership, Option non-cover enforcement, cover clearing, and Product-targeted audits.
- Image sort/cover update and logical-delete Services with hidden deleted parents, ordered one/two-audit flows, and compact snapshots.
- Repository Product-row lock and cover lookup on the caller transaction, with mock/real SQLite tests for cover invariants and rollback.

### Important Decisions

1. Service accepts a storage-generated image URL; FastAPI UploadFile, 2MB/type/content checks, external storage, and `42221` remain API/infrastructure responsibilities.
2. If storage succeeds before a database Service failure, the future caller must delete the object or enqueue delayed cleanup because the database transaction cannot roll back external storage.
3. Cover creation/switching locks the Product row so concurrent cover requests for one aggregate are serialized before bulk cover clearing.
4. Deleted Image/Product/Option ownership is hidden behind `40403`; an Option image cover attempt uses the registered `40021` contract.
5. Delete audit omits the potentially 2048-character URL to fit the existing 256-character AuditLog description. The logical-deleted ProductImage remains the authoritative URL record addressable by image ID.

### Verification

- 71 focused Image Service, Repository, exception, and architecture tests pass.
- All 559 Product tests pass.
- Full regression: 666 tests pass.
- Real SQLite tests prove one effective public cover and rollback of cover creation, second cover audit, and deletion failures.

### Known Limitations

- Multipart routes, image validation, storage adapter, compensation/delayed cleanup, and response mapping were completed by the later stages above.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ProductKit Mutation Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic Kit price changes and direct final-stock settings, completing the ProductKit mutation Service boundary. The HTTP endpoints remain unavailable until API integration.

### Added

- `ProductService.update_kit_price()` and `update_kit_stock()` with shared ordered Product/Kit aggregate checks.
- Named `ProductKitNotFound` using the existing `40404` API allocation when a valid Kit Product lacks its required extension record.
- Compact `UPDATE_PRICE` and `UPDATE_STOCK` before/after snapshots in the existing AuditLog description field.
- Mock and real SQLite tests for error precedence, Draft/Offline writes, zero stock, field preservation, Validator isolation, write failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. Checks run in the stable order missing Product, deleted Product, type mismatch, Online state, and missing ProductKit extension.
2. Price and stock remain separate use cases and each changes exactly one ProductKit field.
3. Phase 4.1 stock mutation sets the final value; stock movements, reasons, automatic deduction/restoration, and concurrency control remain Phase 4.3 Inventory work.
4. ProductKit mutation and its Product-targeted audit share one transaction. Service returns ProductKit; the future API Mapper uses `product_id` as the response ID.

### Verification

- 51 focused Kit mutation, exception, and architecture tests pass.
- All 530 Product tests pass.
- Full regression: 637 tests pass.
- Real SQLite tests prove field preservation and audit-failure rollback for both mutations.

### Known Limitations

- Kit price/stock API routes and response mappings remain pending.
- Product image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Delete Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed the ExperienceOption lifecycle Service by implementing status-safe logical deletion with atomic snapshot auditing. The HTTP endpoint remains unavailable until API integration.

### Added

- `ProductService.delete_experience_option()` with ordered missing/deleted/Product-state checks and Draft/Offline logical deletion.
- Compact `DELETE_OPTION` snapshots containing Option identity, dimensions, day type, and two-decimal price in the existing AuditLog description field.
- Mock and real SQLite tests for conflict precedence, deleting the final active Option, Product status preservation, image record/foreign-key preservation, Validator isolation, write failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. A deleted parent Product hides its Option behind `40402`; an already-deleted Option retains `40912` precedence over Product Online status.
2. Deletion changes only `ExperienceOption.is_deleted`. Product status and ProductImage records are not modified, and no physical delete occurs.
3. Draft/Offline may reach zero active Options. The delete workflow does not count siblings or invoke ProductValidator; a later online request owns aggregate completeness enforcement.
4. Option mutation and `DELETE_OPTION` audit share one transaction and target the Product for unified product-history lookup.

### Verification

- 39 focused Option delete, exception, and architecture tests pass.
- All 506 Product tests pass.
- Full regression: 613 tests pass.
- Real SQLite tests prove final-Option deletion, unchanged Product/image state, and audit-failure rollback.

### Known Limitations

- The ExperienceOption delete API route and response mapping remain pending.
- Kit mutation and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Update Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented partial ExperienceOption mutation with merged all-history uniqueness checks and atomic configuration/price auditing. The HTTP endpoint remains unavailable until API integration.

### Added

- `ExperienceOptionNotFound` (`40402`) and `ExperienceOptionAlreadyDeleted` (`40912`) with fixed HTTP contracts.
- `ProductService.update_experience_option()` with non-empty field allowlisting, API-to-Model duration mapping, Product state protection, merged final-combination validation, and race-time unique conflict translation.
- Separate `UPDATE_OPTION` dimension snapshots and `UPDATE_PRICE` price snapshots; one PATCH can atomically write both actions in deterministic order.
- Mock and real SQLite tests for omitted-field preservation, current-ID exclusion, active/deleted history collisions, deleted Product hiding, Online protection, image preservation, Validator isolation, and rollback on first/second audit or response reload failure.

### Important Decisions

1. Service receives `model_dump(exclude_unset=True)` output rather than a Pydantic Schema and rejects empty or internal-field mappings before any lookup.
2. Uniqueness is evaluated against the merged final dimensions. The current Option row is allowed; any other historical row is a `40911`, including deleted rows.
3. Configuration and price use their authoritative separate audit actions. Both audit rows target the Product so the existing product-history endpoint can return them.
4. Update, all audits, and response aggregate reload use the same transaction connection. Option images are neither modified nor included by the future `ExperienceOptionBaseOut` response.

### Verification

- 58 focused Option update, exception, Repository, and architecture tests pass.
- 512 Product/Option/audit tests and the complete 600-test suite pass.
- Real SQLite tests prove field persistence, image preservation, deterministic dual audits, and complete rollback when either audit or response reload fails.

### Known Limitations

- The ExperienceOption update API route and response mapping remain pending.
- Option delete, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — ExperienceOption Create and Restore Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic ExperienceOption creation and historical-record restoration while preserving the all-history combination identity contract. The HTTP endpoint remains unavailable until API integration.

### Added

- `ProductTypeMismatch` (`40001`) and `ExperienceOptionAlreadyExists` (`40911`) with frozen response data.
- `ProductService.create_experience_option()` with Product preconditions, all-history combination lookup, INSERT/restore branching, and shared transaction audit persistence.
- `ExperienceOptionCreationResult(option, restored)` so the API can select HTTP 201 for creation and HTTP 200 for restoration without introducing transport concerns into Service.
- Repository Option detail loading with parent Product and sorted active images, including caller-owned transaction support.
- Mock and real SQLite tests for Draft/Offline creation, Product conflicts, active duplicates, concurrent unique-index translation, original ID/image preservation, price snapshot auditing, Validator isolation, and audit-failure rollback.

### Important Decisions

1. A deleted matching combination is restored in place with its original Option ID and image foreign keys; only current price and `is_deleted` change.
2. The Service lookup gives an early `40911`, while the database all-history unique index remains the concurrency authority. A race-time `IntegrityError` is translated to the same business conflict.
3. Creation/restoration, audit, and response aggregate reload use one transaction connection. `CREATE_OPTION` and `RESTORE_OPTION` target the Product so the existing product-history endpoint can return them.
4. AuditLog has no metadata column; restoration stores compact JSON with Option ID and before/after price strings in the existing `description` field. No migration is introduced.

### Verification

- 47 focused Option create/restore, exception, Repository, and architecture tests pass.
- 484 Product/Option/audit tests and the complete 572-test suite pass.
- Real SQLite tests prove new-record persistence, restoration identity/image preservation, and rollback of both paths when audit fails.

### Known Limitations

- The ExperienceOption create/restore API route and response mapping remain pending.
- Option update/delete, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Update and Delete Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented Product basic-information PATCH orchestration and Product logical deletion with stable conflicts and atomic audit persistence. The HTTP endpoints remain unavailable until API integration.

### Added

- `OnlineProductCannotBeModified` (`40905`) and `ProductMustBeOfflineBeforeDelete` (`40904`) with fixed messages and HTTP 409 mapping.
- `ProductService.update_product()` with non-empty `name` / `description` field allowlisting, PATCH missing/null preservation, ordered preconditions, and atomic `UPDATE_PRODUCT` audit persistence.
- `ProductService.delete_product()` with Draft/Offline support, status-preserving logical deletion, and atomic `DELETE_PRODUCT` audit persistence.
- Mock and real SQLite tests for missing/deleted/Online conflicts, deletion precedence, forbidden internal fields, Validator isolation, child-record preservation, shared transaction connections, failure short-circuiting, and audit-failure rollback.

### Important Decisions

1. API passes `ProductUpdate.model_dump(exclude_unset=True)` as a normalized field mapping; Service remains independent of Pydantic while preserving omitted fields versus explicit `description=None`.
2. Service allowlists only `name` and `description`, so type, status, and deletion state remain owned by their dedicated use cases.
3. Logical deletion changes only `Product.is_deleted`; status and Product child records remain untouched for traceability.
4. Neither workflow loads the aggregate or invokes ProductValidator because no online-readiness transition occurs.

### Verification

- 39 focused update/delete, exception, and architecture tests pass.
- 447 Product/audit transaction tests and the complete 549-test suite pass.
- Real SQLite tests prove successful field/deletion persistence and audit-failure rollback.

### Known Limitations

- Product update/delete API routes and response mapping remain pending.
- Option, Kit mutation, and image Service workflows remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Creation Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented atomic Experience and Kit Draft creation workflows with mandatory Product audit logging. Product HTTP creation endpoints remain unavailable until API integration.

### Added

- `create_experience_product()` with fixed Experience type and atomic Product plus `CREATE_PRODUCT` audit persistence.
- `create_kit_product()` with fixed Kit type and atomic Product, ProductKit, and audit persistence.
- Mock orchestration tests and real SQLite tests for shared transaction connections, fixed types/defaults, zero-stock Kit creation, failure short-circuiting, and full rollback on audit failure.

### Important Decisions

1. Service accepts normalized domain fields rather than Pydantic request objects and returns the created Product Model.
2. ProductType is selected by the Service method; Draft and non-deleted defaults remain Model-owned and cannot be overridden by callers.
3. Draft creation does not invoke ProductValidator and permits incomplete descriptions, images, and Experience Options.

### Verification

- 44 focused Product creation/query/status/architecture tests pass.
- The complete suite passes with 524 tests.

### Known Limitations

- Product creation API routes and response mapping remain pending.
- Product update/delete, Option, Kit mutation, and image Service workflows remain pending.

---

## Unreleased — Product Query Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented the Product query orchestration boundary for admin and public consumers while deliberately leaving presentation mapping to the future API layer.

### Added

- Admin Product list orchestration with pagination, type/status/keyword filters, and explicit logical-deletion scope.
- Public Product list orchestration that forces Online and non-deleted visibility and searches both name and description.
- Admin typed-detail lookup that includes deleted aggregates while hiding type mismatches as `40401`.
- Public typed-detail lookup that hides missing, deleted, non-Online, and type-mismatched resources behind the same `40401` contract.
- Mock contract tests and real SQLite tests for visibility, description search, type isolation, pagination delegation, and relation preloading.

### Important Decisions

1. Query Service returns `Product` or `Page[Product]`; it does not depend on API response Schemas.
2. `cover_image`, `display_price`, dimensions, availability, and value labels belong to an API Mapper built from preloaded aggregates.
3. Query operations do not open transactions, write audit logs, or invoke ProductValidator.

### Verification

- 35 focused Product query/status/architecture tests pass.
- The complete suite passes with 515 tests.

### Known Limitations

- Product API routes and presentation mapping are still unavailable.
- Product creation, update/delete, Option, Kit mutation, and image Service workflows remain pending.

---

## Unreleased — Product Offline Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Completed the Product status-transition Service pair by implementing atomic Online-to-Offline orchestration. The Product HTTP endpoint remains unavailable until the API layer is implemented.

### Added

- `ProductAlreadyOffline` (`40902`) as the stable conflict for both Draft and Offline Products receiving an offline request.
- `ProductService.offline_product(product_id, *, operator_id, ip_address) -> Product` using a lightweight Product lookup, ordered precondition checks, and atomic status plus `OFFLINE_PRODUCT` audit persistence.
- Tests for missing/deleted/non-Online Products, deletion precedence, absence of Validator calls, exact load/update/audit order, shared transaction connections, update failure, successful real persistence, and audit-failure rollback.

### Important Decisions

1. Draft and Offline share `40902` because both are already non-selling states; no additional Draft-specific code is introduced.
2. Offline uses `get_product_by_id(..., include_deleted=True)` because it needs no aggregate relations and never calls the online-readiness Validator.
3. Resource and status conflicts occur before the transaction; the status update and audit remain atomic within one caller-owned transaction.

### Verification

- 34 focused Product status-transition, exception, and architecture tests pass.
- The complete suite passes with 503 tests.
- Real SQLite tests prove successful persistence and audit-failure rollback to Online.

### Known Limitations

- No Product API routes are registered yet.
- Remaining Product query, creation, update/delete, Option, Kit, and image Service operations remain pending.

---

## Unreleased — Product Online Service (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented the first Product Service slice: precondition checks, Validator orchestration, and atomic online-status plus audit persistence. Product API routes remain unavailable; this milestone exposes no new HTTP endpoint.

### Added

- General `ConflictException` and HTTP 409 middleware mapping without error-code-range inference.
- Named `ProductNotFound`, `ProductIsDeleted`, and `ProductAlreadyOnline` exceptions with frozen 404/409 contracts.
- Caller-owned transaction support in `AuditLogRepository.create()` and `AuditLogService.log()` through optional `using_db` propagation.
- `ProductService.online_product(product_id, *, operator_id, ip_address) -> Product` with complete aggregate loading, ordered resource/state checks, synchronous Validator invocation, atomic status update, and `ONLINE_PRODUCT` audit.
- Service tests for exact orchestration order, Draft and Offline transitions, Experience and Kit aggregates, failure short-circuiting, shared transaction connections, update failure, audit failure rollback, and architecture boundaries.

### Important Decisions

1. Product named exceptions directly inherit the matching HTTP-semantic base; the former 422-only `ProductException` pseudo-base was removed.
2. Service returns the updated ORM Product. API remains responsible for ADMIN+ authorization and `ProductOnlineOut` serialization.
3. Validation and resource/state conflicts occur before the write transaction. Status persistence and audit persistence share one transaction connection and roll back together.
4. This slice does not add row locking, conditional status updates, or cross-request idempotency; concurrent online requests remain a documented future concurrency concern.

### Verification

- 72 Product online/exception/Validator/audit/architecture tests pass.
- The complete suite passes with 493 tests.
- Real SQLite tests prove both successful Experience/Kit persistence and audit-failure status rollback.

### Known Limitations

- No Product API route is registered yet, so the documented online endpoint remains unavailable.
- Remaining Product Service operations—query, create/update/delete, offline, Options, Kit edits, and images—remain pending.
- No database schema, migration, dependency, or version change is required.

---

## Unreleased — Product Validator (Phase 4.1)

**Date:** 2026-08-12

### Summary

Implemented and reviewed the Product pre-online aggregate-integrity Validator as a synchronous, pure business component. It reports all readiness issues in stable order through the frozen HTTP 422 / `42201` contract. Product Service and API routes remain unavailable and are intentionally outside this milestone.

### Added

- `UnprocessableEntityException` as the general HTTP 422 business-exception type while preserving HTTP 400 for ordinary `BusinessException` instances.
- `ProductException` and `ProductNotReadyForOnline`, fixing code `42201`, message `Product is not ready to go online`, and non-empty `data.issues` structure.
- `ProductValidator.validate_before_online(product) -> None` as a synchronous entry point that reads a Service-preloaded Product aggregate and either returns `None` or raises the named exception.
- Common online-readiness rules for non-blank Product name and description plus an active public cover.
- Experience rules for at least one public image, at least one active Option, positive Option prices, and at least one active image per Option.
- Kit rules for a required ProductKit extension, price in `(0, 99999]`, and non-negative stock, including support for online products with zero stock.
- Contract tests for exception mapping, every common and type-specific boundary, multi-issue aggregation, stable issue ordering, fail-closed ProductType dispatch, real Repository-loaded aggregates, zero validation-time SQL, no aggregate mutation, and unprefetched-relation programming errors.

### Important Decisions

1. **Validator is a separate component serving Service.** Service owns lookup, resource/state conflicts, transactions, persistence, and audit; Validator owns only aggregate-integrity decisions.
2. **Purity is expressed by a synchronous API.** Validator performs no database, Repository, Service, Redis, transaction, permission, audit, or state-mutation work.
3. **Input must be a complete aggregate.** Service must call `ProductRepository.get_product_detail(product_id, include_deleted=True)` before validation. Missing prefetches remain visible programming errors instead of becoming `42201`.
4. **All issues are returned together.** Stable English strings and ordering are part of the API contract; the Product business rules document is their authoritative list.
5. **Type dispatch fails closed.** Unknown Product types raise an internal programming error rather than passing only common checks or being mislabeled as incomplete business data.
6. **Option identity is not revalidated online.** The Option write flow and the all-history database unique index own configuration conflicts and their `40911` response.

### Verification

- Validator stage tests pass: 6 exception-contract, 11 common-rule, 10 Experience, 11 Kit, and 5 purity/integration tests.
- Product-related tests pass with 366 tests; the complete suite passes with 464 tests.
- Python compilation, dependency integrity, whitespace, forbidden dependency, debug-output, and unfinished-marker checks pass.

### Known Limitations

- Product Service, API routes, permissions, state-transition persistence, transactions, and Product audit-log writes remain pending.
- Product API documentation remains Draft until endpoint integration tests pass.
- Image file upload and MIME/size validation remain pending; `42221` is reserved for that later boundary.
- The committed MySQL initial migration remains unapplied. This Validator milestone changes no schema and requires no migration.

---

## Unreleased — Product Repository (Phase 4.1)

**Date:** 2026-08-11

### Summary

Implemented and reviewed the Product aggregate Repository as the data-access boundary for the upcoming Validator and Service slices. Product endpoints remain unavailable until Validator, Service, and API integration are complete.

### Added

- `ProductRepository` with Product create/update, logical-delete-aware lookup, filtered pagination, and aggregate detail loading.
- ExperienceOption lookup by ID and all-history configuration identity, plus transaction-aware create/update operations that support restoration orchestration without creating a second version row.
- ProductKit and ProductImage lookup/create/update operations, including one-statement public-cover clearing scoped by Product, logical deletion, and optional current-image exclusion.
- Use-case-specific relation loading: list summaries preload Kit, active Options, and active public images; details additionally preload active Option images; Option/Image ID lookups preload the parent records required by Service rules.
- Repository contract tests for normal paths, deletion scope, stable ordering, pagination metadata, transaction rollback, parent relations, and constant-query-count protection against N+1 behavior.

### Changed

- `Page[T]` now permits ORM Model item types so Repository code can return `Page[Product]` while API code continues using response-Schema pages.
- Consolidated the identical partial-update persistence mechanism behind a private bounded generic helper while retaining entity-specific public methods and return types.
- Rebuilt the active SQLite development database from current Tortoise Models after creating a recoverable backup. No MySQL migration was applied to SQLite and no Aerich version was faked.

### Important Decisions

1. **Repository returns Models, not API DTOs.** Service owns derived fields such as `cover_image` and `display_price`; API owns Out-Schema serialization.
2. **Transactions are Service-owned.** Repository writes accept an optional database client and join the caller's transaction without deciding transaction boundaries.
3. **Loading follows the use case.** Lists do not fetch Option images, details do, and child-resource lookups join only the parent records needed by Service checks.
4. **Logical deletion is explicit per query.** Ordinary lookups hide deleted rows, while the all-history Option identity query intentionally includes deleted records so Service can restore the stable Option ID.
5. **Cover switching is batch persistence, not a Repository business rule.** Repository provides one scoped UPDATE; Service must decide whether a cover change is valid and execute the full switch atomically.
6. **Reuse stays local until generalized behavior is proven.** Common update mechanics are private to the Product Repository module rather than imposed through a premature global BaseRepository.

### Verification

- 38 Product Repository tests pass, including bounded query-count and transaction rollback contracts.
- The complete test suite passes with 421 tests.
- Python compilation, dependency integrity, whitespace, forbidden dependency, and debug-output checks pass.

### Known Limitations

- Product Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until endpoint integration tests pass.
- The committed MySQL initial migration remains unapplied; deployment still requires explicit authorization, a reviewed target, and a backup/rollback plan.

---

## Unreleased — Product Schema and Model Foundation (Phase 4.1)

**Date:** 2026-08-10

### Summary

Implemented the complete Product request/query/response Schema layer plus the Product aggregate-root, ExperienceOption, ProductKit, and ProductImage Models as the first executable slices of Phase 4.1. This milestone freezes API data shapes and all four Product tables; it does **not** make Product endpoints available yet.

### Added

- `ProductType`, `ProductStatus`, and `DayType` as Python 3.10-compatible string Enums.
- Product validation constants for names, descriptions, prices, open positive experience dimensions, stock, image order, and search keywords.
- Strict JSON request Schemas for Product create/update, Experience Option CRUD input, image PATCH, Kit price/stock updates, and user/admin list queries.
- Response Schemas for user/admin lists, Experience/Kit details, create/update/status/delete actions, Options, images, dimensions, and Kit price/stock results.
- `LabeledValue[T]` for stable `{value, label}` response DTOs and `Page[T]` reuse for Product lists.
- Product Schema contract tests covering normal paths, invalid values, PATCH missing-vs-null semantics, field isolation, pagination nesting, and ORM/internal field filtering.
- Product aggregate-root Tortoise Model with string Enum fields, ORM validators, application and database defaults, a stable named status/deletion index, and real SQLite DDL tests.
- ExperienceOption Tortoise Model with a RESTRICT Product FK, open positive dimensions, DayType string Enum, strict Decimal price validation, logical deletion default, and a stable named all-history unique index.
- Reusable `UniqueIndex` and `StrictDecimalField` infrastructure for cross-database named uniqueness and pre-quantization Decimal precision validation.
- ExperienceOption Model contract tests covering ORM round trips, reverse relations, invalid boundaries, unknown Enums, logical-delete uniqueness, cross-Product scope, FK deletion protection, and real SQLite DDL.
- ProductKit Tortoise Model with a RESTRICT one-to-one Product relation, strict Decimal price, dual-layer stock default, non-negative stock validation, and parent-owned logical deletion.
- ProductKit Model contract tests covering reverse one-to-one access, price/stock boundaries, per-Product uniqueness, multiple independent Kit products, FK deletion protection, and real SQLite DDL.
- ProductImage Tortoise Model with Product RESTRICT and nullable ExperienceOption SET NULL relations, validated URL/sort fields, dual-layer defaults, logical deletion, and three stable named query indexes.
- ProductImage Model contract tests covering public/Option image relations, URL/sort boundaries, logical-delete preservation, Option physical-delete fallback, Product deletion protection, and real SQLite DDL.
- `asyncmy==0.2.11` as the required Tortoise ORM runtime driver for the production MySQL path.
- Integrated Product Model contract tests covering unified ORM registration, the complete forward/reverse relation graph, migration reconstruction of custom fields/indexes, exact SQLite named-index inventory, and offline MySQL DDL generation.
- Enterprise database migration runbook covering Aerich command boundaries, MySQL-authoritative SQL generation, review gates, existing-database baselines, backup/rollback requirements, and CHECK-constraint prerequisites.

### Changed

- Split Product Schemas by trust boundary: `app/schemas/product.py` owns requests/queries; `app/schemas/product_response.py` owns response allowlists.
- Product monetary requests accept plain decimal strings and convert to `Decimal`; responses require `Decimal` internally and serialize fixed two-place strings.
- Retired Product-specific `42211`–`42215`; static field and request-shape failures use global HTTP 422 validation. `42201` remains for database-dependent online readiness and `42221` for image file validation.
- Admin list/detail contracts now always return `is_deleted`; user responses never expose it.
- Experience duration and participants remain open positive integers rather than fixed Enums.
- Normalized the pending Product Model contract across business rules, API, database design, DBML, and coding standards: online Option writes require prior offline status, Kit stock is a Phase 4.1 final-value field, and Product string Enums use the Python 3.10-compatible `str, Enum` form.
- Replaced deprecated `BigIntField(pk=True)` with `BigIntField(primary_key=True)` in `BaseModel` and all documentation examples.
- Corrected the stale Kit pricing sentence in the business rules: price lives in `product_kits.price`, and online Product writes require prior offline status, matching the database and API contracts.
- Pinned pytest-asyncio's fixture loop scope to `function`, preserving per-test database isolation and preventing a future default change from silently altering test behavior.
- Replaced the hand-built MySQL URL with structured Tortoise credentials so reserved characters in database passwords cannot be misparsed as URL syntax, and added configuration contract tests.
- Corrected the Product relation-loading example to use the implemented `kit`, `experience_options`, and `images` reverse relation names; synchronized the documented/example application version with the v0.3.0 baseline.
- Added the missing database-level unique constraint for `users.phone`, matching the existing registration/update conflict contract and closing the concurrent-write gap left by Service pre-checks alone.
- Restored the documented User admin-list and AuditLog tracing indexes in their Models so the initial migration matches established query plans instead of silently omitting them.

### Important Decisions

1. **Strict write boundary.** Unknown JSON fields are rejected; body integers reject booleans, floats, and numeric strings.
2. **PATCH preserves intent.** Empty PATCH bodies are rejected, missing fields mean “unchanged,” and explicit null follows field-specific rules. Services must use `model_dump(exclude_unset=True)`.
3. **User/Admin output separation.** Online user responses require complete sellable shapes, while admin Draft responses allow empty images, Options, and dimensions.
4. **Response allowlists.** Out Schemas ignore undeclared internal attributes so relation IDs, deletion flags, type-specific fields, and sensitive data cannot leak across endpoints.
5. **Option identity is stable.** The named unique index excludes `is_deleted`, so `(product_id, duration, participants, day_type)` remains unique across all rows. Reposting a logically deleted combination must restore the same Option ID and update its current price instead of creating or physically deleting historical rows.
6. **Defaults exist at both boundaries.** Product `status` and `is_deleted` declare both ORM `default` and database `db_default`, so ORM and direct SQL inserts share the same defaults.
7. **Money is validated before ORM quantization.** Product price fields use `StrictDecimalField` because native Tortoise Decimal conversion can round extra fractional digits before ordinary validators run.
8. **Kit extension is one-to-one.** `ProductKit.product` uses `OneToOneField`, so the database allows at most one Kit row per Product and ORM reverse access is a single `product.kit` object rather than a collection.
9. **Kit lifecycle belongs to Product.** ProductKit has no independent `is_deleted`; Product logical deletion controls visibility while the RESTRICT FK prevents accidental physical deletion of the parent.
10. **Phase 4.1 stock is a final value.** `product_kits.stock` is stored and validated now, but inventory ledgers, automatic deduction/restoration, and concurrency control remain Phase 4.3 concerns.
11. **Image ownership has two levels.** A null `experience_option_id` represents a Product public image; a non-null value represents an Option image while retaining the mandatory Product FK for direct Product queries.
12. **Option physical deletion is a fallback path.** ProductImage uses SET NULL for its nullable Option FK so an abnormal physical Option deletion preserves the image; normal business operations still logically delete Options.
13. **Cover consistency belongs to Service.** The three image indexes are non-unique query indexes. Service must enforce same-Product Option ownership, prevent Option covers, and switch the single Product cover inside a transaction.
14. **Both database paths are executable contracts.** SQLite integration tests exercise real tables, while offline MySQL schema generation verifies production DDL without requiring or mutating a live MySQL instance.
15. **Schema generation is environment-gated.** Application startup may auto-create tables only in local development. Tests own disposable schemas, while production must use reviewed migrations and cannot mutate schema as a startup side effect.
16. **Integrity has explicit enforcement layers.** Structural constraints live in the database, value ranges are currently enforced by Schema/Model validation, and cross-row/cross-table invariants belong to Service/Validator. Database CHECK constraints remain a migration-review decision rather than an implicit claim.
17. **Production migrations are MySQL-authoritative.** Aerich stores dialect-specific raw SQL, so MySQL generates and reviews deployable migrations; SQLite remains a development/test compatibility target and does not supply SQL for MySQL releases.
18. **The initial migration fails on schema drift.** Reviewed MySQL DDL omits `IF NOT EXISTS`, runs outside a claimed transaction, and has an intentionally non-destructive empty downgrade instead of dropping every user and business table.

### Database

All four Product Models now declare `products`, `experience_options`, `product_kits`, and `product_images`, including RESTRICT/SET NULL relations, Option uniqueness, Kit one-to-one uniqueness, dual defaults, and stable query indexes. Real SQLite DDL and offline MySQL DDL generation both pass their contracts. A MySQL 8+ initial migration has been generated and statically reviewed offline; it has not been applied to any database.

### Known Limitations

- Validator, Service, API routes, upload handling, and business exceptions remain pending.
- Product API documentation remains Draft until those layers are implemented and endpoint integration tests pass.
- FastAPI `RequestValidationError` still needs global envelope verification/handling during API integration; direct Schema tests do not prove the HTTP 422 response body contract.
- Shared audit-log listing (`AuditLogService.list_logs` / `AuditLogOut`) is not part of Product Schema and remains pending.
- The MySQL initial migration is committed but unapplied. Production startup does not auto-create tables; deployment still requires a separately authorized migration execution against a reviewed target and backup plan.
- Positive/range rules are not yet duplicated as physical database `CHECK` constraints; direct SQL can bypass Schema/Model validators and must remain a controlled operational path.

---

## v0.3.0 — RBAC + Audit Logging + Product Module Design

**Date:** 2026-07-30

### Summary

Added role-based access control (RBAC) with permission cascading, admin user
management with paginated listing and disable, sequential audit logging for
all sensitive operations, and completed Product module design (Phase 4.1).

### Added

- **RBAC Depends chain:** `get_current_user` → `get_current_admin` → `get_current_super_admin`
- **Admin API (`/api/v1/admin/`):** paginated user list (filterable by status/role),
  disable user endpoint (with role hierarchy protection)
- **Audit logging:** `AuditLog` model tracking operator_id, action, target_type,
  target_id, description, ip_address. Sequential (non-fire-and-forget) writes for
  register, login, disable_user. Failed operations produce no audit log.
- **Client IP detection:** `get_client_ip()` with X-Forwarded-For support for
  proxy environments.
- **Page[T] generic** for consistent paginated responses (items, total, page,
  page_size, pages)
- **Product Business Rules (`docs/01_requirements/product_business_rules.md`):**
  complete domain model (Product 1→N ExperienceOption), aggregate rules,
  lifecycle, constraints, and design decisions for Phase 4.1.
- **ER diagram redesign:** `product_experiences` → `experience_options` (1:N),
  price separation, `sort` field, `is_deleted`, `audit_logs` table,
  `ON DELETE RESTRICT` FK constraints.

### Changed

- PATCH semantics for `/users/me` (partial update) instead of PUT
- Phone field now required on `UserCreate` and User model

### Database

**New table:** `audit_logs`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| operator_id | BIGINT FK | Who performed the action |
| action | VARCHAR(50) | REGISTER, LOGIN, DISABLE_USER |
| target_type | VARCHAR(50) | user |
| target_id | BIGINT | Affected entity |
| description | VARCHAR(256) | nullable |
| ip_address | VARCHAR(45) | IPv4/IPv6 |
| created_at | DATETIME | auto |

### Important Decisions

1. **Sequential audit logging.** Audit writes are awaited inline, not
   fire-and-forget. If the audit log fails, the operation fails — no silent
   audit gaps.

2. **Guard before log.** Audit logs are only written after the business
   operation succeeds. Failed disables produce no audit entry.

3. **Depends chain for RBAC.** Each permission level wraps the previous one,
   reusing `get_current_user` → `get_current_admin` → `get_current_super_admin`.
   No repeated token parsing, clean extensibility.

### Known Limitations

- No refresh token rotation (Phase 4)
- No rate limiting on login/register
- Product module: design complete, implementation pending (Phase 4.1)
- No email verification
- No OAuth / third-party login
- Admin enable user endpoint deferred
- Avatar upload deferred

---

## v0.2.0 — User Authentication System

**Date:** 2026-07-25

### Summary

Implemented the complete user authentication system, covering the full
layered architecture from Model to API. Users can now register, login
with JWT, view their profile, and change their password.

### Added

**API Endpoints**

| Method | URI | Auth | Description |
|--------|-----|------|-------------|
| POST | `/api/v1/auth/register` | No | User registration |
| POST | `/api/v1/auth/login` | No | Login, returns access + refresh tokens |
| POST | `/api/v1/auth/refresh` | No | Exchange refresh for new access token |
| POST | `/api/v1/auth/logout` | Bearer | Revoke refresh token |
| GET | `/api/v1/users/me` | Bearer | Get current user |
| PATCH | `/api/v1/users/me` | Bearer | Update profile |
| PUT | `/api/v1/users/me/password` | Bearer | Change password |
| GET | `/api/v1/admin/users` | Bearer (ADMIN+) | List users (paginated, filtered) |
| PUT | `/api/v1/admin/users/{id}/disable` | Bearer (ADMIN+) | Disable user |
| GET | `/api/v1/admin/config` | Bearer (SUPER_ADMIN) | System config |

**Models**

| Model | Table | Fields |
|-------|-------|--------|
| `BaseModel` | (abstract) | id, created_at, updated_at |
| `User` | users | username, password (hashed), nickname, phone, avatar, role, status, last_login_at |

**Enums**

| Enum | Values |
|------|--------|
| `UserRole` | USER (1), ADMIN (2), SUPER_ADMIN (3) |
| `UserStatus` | NORMAL (1), DISABLED (2) |

**Schemas (schemas/user.py)**

| Schema | Purpose |
|--------|---------|
| `UserCreate` | Registration request |
| `UserUpdate` | Profile update (nickname, phone, avatar) |
| `PasswordChange` | Password change request |
| `UserOut` | Full user detail response |
| `UserListItem` | Lightweight list item |

**Schemas (schemas/auth.py)**

| Schema | Purpose |
|--------|---------|
| `LoginRequest` | Login request |
| `TokenOut` | Login response — access + refresh tokens + user |
| `RefreshRequest` | Refresh token exchange request |
| `RefreshOut` | Refresh response — new access token only |

**Exceptions (app/common/exceptions/user.py)**

7 named exception classes: `UsernameAlreadyExists` (1001), `UserNotFound` (1002),
`IncorrectPassword` (1003), `OldPasswordIncorrect` (1004), `UserDisabled` (1005),
`TokenExpired` (1006), `PhoneAlreadyExists` (1007).

**Infrastructure**

| Component | File |
|-----------|------|
| Configuration | `app/core/config.py` — 14 fields via pydantic-settings |
| Security | `app/core/security.py` — bcrypt + JWT (HS256, jti, type validation) |
| Redis | `app/core/redis.py` — Refresh token store (rt:{jti}) |
| Logging | `app/core/logging.py` — DEBUG/INFO env-aware |
| Database | `app/db/database.py` — register_tortoise (SQLite/MySQL) |
| DI | `app/api/deps.py` — get_current_user / admin / super_admin Depends chain |
| Pagination | `app/common/pagination.py` — PageParams + Page[T] |
| RBAC | `app/api/v1/admin_users.py` — paginated user list + disable |
| Audit | `app/models/audit_log.py` — operator_id, action, target_type, ip |
| Tests | `tests/` — 38 tests covering all endpoints |

### Changed

- **Exception handling:** Replaced single catch-all handler with per-type
  registration to fix Starlette re-raise issue.
- **Response format:** All endpoints now use `success()` envelope instead of
  `response_model` — ensures 100% consistent `{"code":0, "data":...}` format.
- **API layer:** Removed `response_model` decorators; `UserOut.model_validate()`
  handles serialization and password exclusion.

### Database

**New table:** `users`

| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT PK | |
| username | VARCHAR(32) UNIQUE | |
| password | VARCHAR(128) | bcrypt hashed |
| nickname | VARCHAR(32) | |
| phone | VARCHAR(11) | nullable |
| avatar | VARCHAR(256) | nullable |
| role | SMALLINT | default 1 |
| status | SMALLINT | default 1 |
| last_login_at | DATETIME | nullable |
| created_at | DATETIME | auto |
| updated_at | DATETIME | auto |

### Important Decisions

1. **JWT over sessions.** RESTful, no server-side state, suitable for
   separated frontend/backend. See architecture.md §6.3.

2. **Service layer owns business logic.** Repository is pure data access,
   all checks (dedup, password verification, status validation) live in
   `UserService`. This keeps the API layer thin and testable.

3. **Named exceptions over generic codes.** `raise UsernameAlreadyExists()`
   instead of `raise BusinessException(code=1001, ...)`. Self-documenting,
   impossible to get the wrong code number.

4. **pydantic-settings over os.getenv().** Automatic type coercion (bool,
   int from .env strings), field validation at startup, cleaner code.

5. **`success()` envelope over `response_model`.** The `{"code":0,
   "data":...}` format is enforced at the API layer, not delegated to
   FastAPI serialization. This prevents mixed response formats.

6. **`field_serializer` for IntEnum.** Stored as TINYINT in DB, exposed
   as lowercase string in API (`"user"` not `1`). This matches the
   API design conventions.

### Known Limitations

- No refresh token rotation (Phase 4)
- No login audit log
- No rate limiting on login/register
- No email verification
- No OAuth / third-party login
- Admin enable user endpoint deferred to Phase 3
- Avatar upload deferred to Phase 3

### Dependencies Added

| Package | Version | Purpose |
|---------|---------|---------|
| pydantic-settings | 2.14 | Configuration management |
| passlib[bcrypt] | 1.7.4 | Password hashing |
| python-jose[cryptography] | 3.3.0 | JWT signing/verification |
| tzdata | — | Timezone data (Windows) |
| pytest | 9.1 | Test framework |
| pytest-asyncio | 1.4 | Async test support |
| httpx | — | HTTP test client |

---

## v0.1.0 — Project Bootstrap

**Date:** 2026-07-24

### Summary

Project initialized with FastAPI skeleton, configuration system, logging,
exception handling, and database connection. No business logic.

### Added

- FastAPI application with lifespan (startup/shutdown lifecycle)
- pydantic-settings configuration with .env / .env.example
- Structured logging (DEBUG/INFO env-aware)
- AppException hierarchy with 4 HTTP-mapped types
- Tortoise ORM with SQLite/MySQL auto-switch
- BaseModel with id, created_at, updated_at
- Unified response envelope (`success()` / `error()`)
- Health check endpoint

### Known Limitations

- No business modules
- No authentication
- No tests
