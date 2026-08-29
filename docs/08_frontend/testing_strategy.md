# pinkdooHub 前端测试策略

> **Document Version:** v0.9
> **Status:** Draft
> **Last Updated:** 2026-08-29
> **Applies To:** 正式 `miniapp/` 与其 FastAPI 集成边界

本文档定义测试层级、Mock 边界、四端矩阵、CI 与发布门槛。Spike 已固定：Jest 29.7.0 + `jest-environment-jsdom` 29.7.0 + `@tarojs/test-utils-react` 0.1.1（详见 [ADR-001](adr/ADR-001-use-taro-react-typescript.md) 与架构文档 §4.1）。

## 0. 工具链已知结论（Spike 2026-08-15）

- `@tarojs/test-utils-react@0.1.1` 的 peerDependencies 仍声明 `@tarojs/* ^3.6.0`，与 Taro 4.2.1 冲突；npm 安装必须 `--legacy-peer-deps`（Spike 工程 `.npmrc` 已固化，正式工程沿用）。
- 官方 Jest transformer 未启用私有方法/属性插件，全量转译会失败；需要自定义 transformer 补齐（见 Spike 工程 `jest.transformer.js`）。
- `@tarojs/router` 与 `@tarojs/components`（Stencil bundle）在 Jest 中形成循环依赖，组件测试需工厂 mock `@tarojs/router`；`html()` 序列化 shadow DOM 会爆栈，断言使用 `queries.querySelector*`。
- React 18.3 下 test-utils 内部使用已废弃的 `ReactDOMTestUtils.act`，产生告警但不阻断；升级测试工具时消除。
- `openapi-typescript@7.13.0` 通过 `--immutable --alphabetize` 生成类型，`npm run api:types:check` 直接检查生成物漂移。
- 2026-08-20 正式工程依赖复核后，`npm ls --depth=0` 无错误；官方 registry 审计仍有 10 项生产依赖风险来自 Taro 4.2.1 H5 上游链，强制修复会破坏性降级 Taro，列为公开发布门槛。
- 当前完整 Jest 为 60 套件 / 375 项。Auth/Product/Cart/Order/Inventory Endpoint 与 Feature 使用 fake transport、upload transport、image picker、storage、clock 等平台边界；账号注册覆盖请求投影、User Runtime Guard、字段校验、白名单 redirect、登录页入口、成功不自动登录、唯一性错误、未知结果和同步防双击。Order 创建纵向集成保留真实 CartStore → SubmissionStore → OrderApi → ApiClient，用户查询/取消及 ADMIN 列表→Paid→Completed 纵向集成都保留真实 OrderApi → ApiClient，只替换网络、Storage 与 Auth 平台边界。
- 2026-08-20 微信开发者工具已连接本地 FastAPI + SQLite + Redis 完成账号密码认证 Functional：错误/正确/禁用账号、`user/admin/super_admin` 展示、Storage 写入、重启 `/users/me` 恢复、登出清理、`expiresAt` 主动 refresh、服务端 `1006` 被动 refresh，以及 access/refresh 同时无效后的 Session 清理全部通过；未记录或传播真实 Token。该结果不替代真机、H5、弱网、HTTPS/合法域名及正式微信登录门槛。

---

## 1. 测试原则

1. 优先验证用户可观察行为和稳定契约，不绑定组件内部实现。
2. 纯业务算法、请求层、认证与幂等逻辑必须可脱离开发者工具运行。
3. Mock 平台、网络、时间和 Storage 等不稳定边界，不 Mock 被测 Feature 本身。
4. 构建成功不等于功能可用；Build、Smoke、Functional 分层验收。
5. 微信通过不代表支付宝、抖音或 H5 通过。
6. 不为固定覆盖率制造低价值测试；关键风险必须完整覆盖正常和失败分支。
7. 测试夹具不得包含真实密码、Token、手机号或 AppSecret。

---

## 2. 测试金字塔

| 层级 | 目标 | 工具候选 | 频率 |
|------|------|----------|------|
| Typecheck | 静态 DTO、null、联合类型、调用边界 | `tsc --noEmit` | 每次提交 |
| Lint/Format | 规则与格式 | ESLint/Prettier | 每次提交 |
| Unit | 纯函数、Feature 算法、Error、Session | Jest | 每次提交 |
| Component | Props、事件、四态、生命周期外观 | Taro React Test Utils + Jest | 每次提交 |
| API Client | transport、信封、Token、上传、幂等 | Jest + fake transport/storage/clock | 每次提交 |
| Contract | OpenAPI 类型和关键 Operation | OpenAPI 导出 + 生成 + diff | 每个 PR |
| Build | 四端可编译 | Taro CLI | 每个 PR |
| Smoke | 启动、导航、网络、Storage | 各端工具/H5 浏览器 | 阶段候选 |
| E2E | 用户/管理员纵向链路 | 平台自动化/H5 E2E | PR 或发布候选 |
| Real device | 真机、弱网、前后台、上传 | 人工/平台能力 | 发布候选 |

---

## 3. 静态门槛

预期命令：

```text
npm run typecheck
npm run lint
npm run format:check
```

规则：

- production source 禁止无说明 `any`；
- 禁止业务层直接引用 `wx`、`my`、`tt`；
- 禁止 Page 直接引用低层 HTTP transport；
- Generated 目录排除人工格式化修改，但参与 typecheck；
- 未使用变量、浮动 Promise 和危险类型断言按工具能力收紧。

---

## 4. 单元测试重点

### 4.1 Shared

- Money 原样/显示格式；
- UTC 转本地与本地筛选转 UTC；
- `{value,label}` 未知值；
- 相对/绝对图片 URL；
- 正整数路由参数；
- Page 响应与下一页判断；
- Runtime Envelope Guard。

### 4.2 Product

- 公开列表 Query 只发送 `page/page_size/product_type/keyword`，且不附带 Token；
- Page/Product Runtime Guard 拒绝非法 ID、金额、Enum、图片 URL 和分页字段；
- Loading/Empty/Error/Content 四态互斥且可观察；
- 下一页追加而不是替换，重复点击不重复请求；
- 较早请求迟到时不能覆盖较新结果；
- 相对/绝对图片 URL 与图片失败占位；
- Experience 有效组合筛选；
- 每一步选择后的可用值；
- 最终唯一 Option；
- 无匹配/多个异常匹配；
- Kit available 只用于 UI，不生成权威订单金额。

### 4.3 Order

- Experience/Kit Item 构造；
- 重复 Product/Option 合并或拒绝策略；
- 数量与 Item 边界；
- 空白 remark；
- 状态对应按钮；
- empty-body PATCH；
- 本地购物车持久化与坏数据恢复。

Phase 7.1 已落地的 Cart 自动化额外固定：Storage 白名单重写、Experience/Kit 跨字段一致性、重复组合串行合并、不同 Option 隔离、10 Item/99 quantity 边界、写失败不发布伪成功、Order Item 最小字段投影，以及 Cart 页四态和数量操作。当前 3 个新增套件 / 17 项通过；微信开发者工具的重启恢复、登录/退出保留、坏缓存恢复、无库存禁用及“有库存 Kit 可加入且无 Experience 配置”均已通过。local-only Seed 已通过正式 Inventory 调整为 Product ID 7 建立库存 8。

Phase 7.2 自动化固定以下高风险边界：Experience 请求携带真实 Option、Kit 省略 Option、请求/响应白名单、登录 redirect 白名单、受控 remark、重复点击单 POST、明确失败与 network/timeout/cancel/contract/5xx unknown 分流、unknown 不自动重试、成功只展示服务端快照，以及按提交快照删除/扣减/保留 Cart。Cart 持久化失败必须保持订单成功并给出本地警告。真实前端链路测试只 Mock transport/storage/auth 平台边界；后端另以真实 FastAPI + SQLite 34 项覆盖 Experience/Kit/混合创建、库存与事务失败。

Phase 7.3 自动化固定以下高风险边界：列表 Query/响应白名单、分页公式、状态 value/label、服务端 page/pages/total、筛选和迟到响应隔离、owner-only 40411 统一提示、路由正安全整数、历史 Item 快照、仅 Pending 显示取消、empty-body PATCH、重复点击单 cancel、成功后 GET、刷新失败不推翻成功、network/timeout/contract/5xx unknown 不自动重发，以及 40921 后按服务端状态收敛。定向 Jest 8 套件 / 61 项，完整前端 25 套件 / 172 项；后端真实 FastAPI + SQLite Order HTTP 53 项及完整 1445 项通过（9 项 MySQL-only 跳过）。

Phase 7.4 自动化固定以下高风险边界：ADMIN Query/响应白名单、精确订单号/历史商品名称快照/用户 ID/UTC 日期范围、包含结束日到排他上界转换、商品改名后的历史检索、多 Item 同时命中的订单去重与 `item_count/total/pages`、管理安全用户字段、普通用户在挂载 Hook 前拦截、固定登录回跳、`admin` 分包路由、Pending 仅 paid、Paid 仅 complete、两个终态无命令、两个 PATCH empty body、重复命令单请求、成功后 GET、权威 GET 完成前保持 submitting、刷新失败不推翻成功、unknown 不重发、40921 后重读，以及真实 `OrderApi → ApiClient` 的列表→详情→Paid→详情→Completed→详情链路。初始阶段完整前端 31 套件 / 213 项、后端 Order API 107 项及完整 1445 项通过（9 项 MySQL-only 跳过）；2026-08-28 的商品名筛选增量结果见本页工程门槛与 changelog。

Phase 8.1 自动化固定以下高风险边界：ADMIN Product 六字段 Query 白名单与 Bearer、草稿空封面/空价格/空图片/空 Option、逻辑删除标记、Experience/Kit 类型专属详情、正安全整数动态路由、服务端分页、筛选换页与迟到响应隔离、普通用户挂载 Hook 前拦截、固定管理列表登录回跳，以及页面不提前出现任何 mutation。微信 Functional 需覆盖 ADMIN 与普通用户边界、四类筛选组合、Draft/Online/Offline/已删除记录、两类详情和空配置提示。

Phase 8.2 自动化固定以下高风险边界：Experience/Kit 创建请求严格分型、Kit 不发送 stock、响应 Runtime Guard、创建/编辑路由参数、PATCH 只发送真实差异、`description: null` 清空、空 PATCH 前端阻止、DELETE 无 body、进行中 Promise 合并、明确失败与 unknown 分流、unknown 不自动重发、普通用户不挂载写 Hook、Online/已删除操作禁用、删除二次确认和成功后以服务端 ID/类型导航。定向 7 套件/56 项，完整前端 41 套件/288 项；2026-08-26 用户确认业务 Functional 全部通过。当时延期的管理页白色图案和登录 `_` 闪烁已于 2026-08-29 关闭：白色图案最终定位为带白色卡片视觉样式的原生 `Form` 渲染异常，改由外层 `View` 绘制卡片、内层透明 `Form` 只保留提交语义；无提交语义的表单容器直接改为 `View`。用户在库存流水、管理商品、Kit 管理库存、管理订单及预防性调整页面完成微信复测并确认通过。登录 `_` 闪烁后续无法再复现，用户确认已消失，按验收结论标记为已解决；不把此前无效的 `alwaysEmbed` 尝试单独视为因果证明。

Phase 8.3 自动化固定以下高风险边界：Option POST/PATCH/DELETE 与 Kit price PATCH 的路径、Bearer、请求白名单和 Runtime Guard；Option POST 完整四维组合、PATCH 只发送差异、空差异前端阻止、DELETE 无 body；Kit 改价绝不发送 stock；恢复结果保留服务端 Option ID；40911/40912/40905 提示；进行中 Promise 合并；unknown 不自动重发；普通用户不挂载详情或 mutation Hook；Online/已删除只读；删除确认明确历史订单快照和恢复原 ID；成功后重新读取权威管理详情。定向 5 套件/48 项、完整前端 43 套件/306 项、静态检查、OpenAPI 漂移和四端 build 通过；Product API 52 项与完整后端 1446 项通过，9 项 MySQL-only 跳过。2026-08-26 用户确认微信 Functional 除改价前后订单快照外均已通过；该项现已具备 Phase 8.5 上下架界面并纳入 8.4–8.5 合并 Functional。

Phase 8.4–8.5 自动化固定以下高风险边界：`Taro.chooseImage`/`Taro.uploadFile` 平台适配、multipart form 字段与平台生成 boundary、Bearer、字符串响应信封、code `1006` single-flight refresh 和一次上传重放；Product/Option 图片归属、响应联合 Runtime Guard、2 MiB/MIME 预检、`42221` 原因；排序、设封面、逻辑删除；online/offline empty-body PATCH、`42201.data.issues` 完整有序保留和未知 issue；进行中 Promise 合并、不同命令同步互斥、unknown 不自动重发、成功或核对后重新 GET；Guest/普通用户/Online/逻辑删除权限与只读边界。定向 8 套件/66 项、完整前端 47 套件/328 项、静态检查、OpenAPI 漂移、四端 build、Product API 52 项和完整后端 1446 项均通过，9 项 MySQL-only 跳过；2026-08-28 用户确认微信 Functional 和 Phase 8.3 延期的旧/新订单价格快照联动全部通过。

Phase 8.6 自动化固定以下高风险边界：调整 path/header/body 白名单；Idempotency-Key 的可打印 ASCII/长度边界；首次 201 与重放 200；refresh 后保留最终重放 status；非法 2xx、库存算术与 transaction/source/operator/order 元数据 Runtime Guard；四类流水及额外字段丢弃；指定 Kit/全局 Query 白名单、UTC 半开日期、source ID 依赖、服务端分页与筛选换页；新业务意图新 key、unknown 不自动重发、用户安全重试复用完全相同的 payload/key、双击 Promise 合并、明确失败清除意图；Guest 固定回跳、普通用户零管理 Hook、已删除 Kit 阻断、Online Kit 可调整及导航回归。定向 9 套件/42 项，另有共享 Client metadata 回归；完整前端 60 套件/375 项、TypeScript、ESLint、Stylelint、OpenAPI 漂移、四端 build 和完整后端 1465 项均通过，9 项 MySQL-only 跳过。2026-08-28 用户确认微信开发者工具 Functional 全部通过。

Phase 8.8–8.9 自动化固定以下高风险边界：Product Audit 动态路由正安全整数/类型、目标类型与 Product ID 绑定、响应白名单、逻辑删除历史和分页；ADMIN User 严格 `status/role` Query、额外参数 422、安全列表字段、稳定分页、Guest/普通用户在 Hook 前拦截、固定登录 redirect；禁用无 body、自己/角色层级、行锁下状态与审计同事务、重复调用幂等、审计失败回滚、旧 access/refresh 立即失效；客户端 code `1005` 清理 Session、不 refresh，network/timeout/contract/5xx unknown 不自动禁用重发。该阶段当时完整前端 54 套件/350 项、完整后端 1465 项通过（9 项 MySQL-only 跳过），并由用户确认微信 Functional 全部通过；随后 Phase 8.6 作为独立增量实施，其门槛见上一段。

2026-08-29 管理筛选交互增量增加页面级契约：按钮型筛选点击后立即调用 `applyFilters`；调用参数必须保留上一次已提交的文字条件，不得混入尚未点击“查询”的草稿；草稿规范化值与已提交快照不同时必须显示待应用提示，校验失败不得更新快照；商品删除记录必须渲染“不含删除记录 / 包含删除记录”两个互斥按钮；库存来源离开 `order` 时必须从已提交筛选移除 `sourceId`；管理用户原有状态/角色即时筛选保持不变。定向 6 套件/29 项、完整前端 60 套件/381 项通过，TypeScript、ESLint 与 Stylelint 通过。用户随后完成微信端 Functional，确认上述交互、组合查询与清空行为全部通过。

### 4.4 Inventory

- Idempotency-Key 生命周期；
- 同一次重试复用；
- 新操作使用新 key；
- 201/200 成功分支；
- key 不进入日志/error。

---

## 5. API Client 测试矩阵

必须覆盖：

- HTTP 2xx + code 0；
- HTTP 2xx + 非 0 code；
- HTTP 401 缺少凭据；
- HTTP 403 不触发 refresh；
- HTTP 400 + code 1006；
- 三个并发 1006 只有一次 refresh；
- refresh 成功后每项最多重放一次；
- refresh 失败清理会话；
- refresh 自身 1006 不递归；
- HTTP 422 `data.errors`；
- Product 42201 `data.issues`；
- 404/409 结构化业务错误；
- 非 JSON、坏信封和错误 content-type；
- network fail、timeout、abort；
- JSON Query 编码；
- 无 body PATCH 完全不设置 data；
- upload Header、formData、成功与失败；
- 日志和错误不含 Token、密码、幂等键。

写请求超时测试必须断言“未自动重试”。

---

## 6. React 组件测试

组件测试关注：

- 用户看到什么；
- 用户点击/输入后发出什么事件；
- Loading/Empty/Error/Content 是否互斥；
- disabled/submitting 是否阻止重复事件；
- 长文本、null 和未知状态的安全表现；
- Props 变化后的渲染；
- 页面生命周期触发的外部行为。

避免：

- 断言私有 state；
- 调用组件内部非公开函数；
- 把整页做成巨大、难 Review 的 snapshot；
- 仅测试 NutUI 自己已经保证的内部行为。

快照只用于小而稳定的展示结构，并配合语义断言。

---

## 7. OpenAPI 契约测试

CI 流程：

```text
FastAPI app.openapi()
  → export openapi.json
  → openapi-typescript
  → generated/schema.d.ts
  → typecheck
  → git diff --exit-code（生成物策略批准后）
```

额外断言关键 Operation 存在：

- auth login/refresh/logout；
- public Product list/detail；
- user Order create/list/detail/cancel；
- admin Product/Inventory/Order；
- HTTP Bearer scheme；
- 成功/错误信封 Schema。

如果文档计划接口不存在，测试不得伪造类型让前端继续开发。

---

## 8. 四端构建与 Smoke

### 8.1 Build

每个 PR：

```text
npm run build:weapp
npm run build:alipay
npm run build:tt
npm run build:h5
```

检查：

- exit code；
- 编译 warning 白名单；
- secret 扫描；
- 包体积；
- 目标配置文件；
- 没有 development Origin 进入 production 产物。

### 8.2 Smoke

至少覆盖：

- 启动与首页；
- 健康检查；
- 登录输入与提交；
- Storage；
- 页面导航/返回；
- 一项 Dialog/Toast；
- 一次图片或上传验证；
- 网络失败提示。

---

## 9. 纵向 E2E

### 9.1 用户路径

1. 游客浏览 Product；
2. 注册/登录；
3. Experience 选择有效 Option 并下单；
4. Kit 下单与库存不足；
5. 查看订单；
6. 取消 Pending；
7. Token 过期刷新；
8. 登出并清理会话。

### 9.2 管理路径

1. 普通用户进入管理入口失败；
2. ADMIN 创建 Product 草稿；
3. 配置 Option/价格/图片；
4. 上架失败完整展示 issues；
5. 上架成功；
6. Kit Inventory 调整首次/重放；
7. 管理订单 Pending → Paid → Completed；
8. 查看审计历史。

E2E 使用隔离测试账号和可重复种子。不得依赖开发者个人数据库中的手工数据。

---

## 10. 真机与非功能测试

发布候选覆盖：

- Android/iOS；
- 常见屏幕、小屏和大字体；
- Wi-Fi、移动网络、弱网和断网；
- 前后台切换、锁屏、请求中断；
- Token 即将/已经过期；
- 上传中断；
- 重复点击和结果未知；
- 图片 HTTPS、失败占位和预览；
- 小程序冷启动和分包首次加载；
- H5 移动浏览器、刷新、后退和直接链接；
- 合法域名、证书、CORS 和 CSP；
- 无障碍基础：点击区域、对比度、非纯颜色提示。

性能以测量为准：首屏时间、列表滚动、请求数、包体积和图片体积。没有测量证据不做预优化。

---

## 11. Mock 边界

应该 Mock：

- Taro transport；
- Taro Storage；
- 当前时间/随机 key；
- Platform login/payment/share；
- 外部图片选择和上传；
- 不稳定网络和超时。

不应该 Mock：

- 被测 Feature 本身；
- 简单纯格式化函数的真实行为；
- OpenAPI DTO 到 Endpoint 的关键映射；
- 集成测试中的 FastAPI 业务服务。

后端真实 HTTP 集成使用现有 pytest/httpx 体系；前端 E2E 通过隔离环境调用真实 API。

---

## 12. CI 路径

建议任务：

| 变更路径 | 后端测试 | 前端静态/单测 | OpenAPI | 四端构建 |
|----------|----------|---------------|---------|----------|
| `app/`、`tests/` | 是 | 契约相关时 | 是 | 是 |
| `docs/` only | 文档契约相关时 | 否 | 否 | 否 |
| `miniapp/src/` | 相关 smoke | 是 | 是 | 是 |
| OpenAPI Schema/路由 | 是 | 是 | 是 | 是 |
| 前端构建配置/依赖 | 否 | 是 | 否 | 是 |

先保证正确性，再根据真实 CI 时长做安全缓存和路径优化。

---

## 13. 阶段门槛

### 架构 Draft → Approved

- [x] Taro 四端空应用构建（Spike：weapp/alipay/tt/h5 生产构建通过，产物 `dist/<TARO_ENV>`）；
- [x] 测试工具可运行（Jest 29.7.0 + test-utils，13 项测试通过）；
- [x] Request/Upload 最小验证（HTTP Client 单测覆盖成功/业务/HTTP/网络/契约错误与上传信封解析）；
- [x] 候选组件矩阵（Button/Toast/Dialog/Input 四端编译通过，见 ADR-005）；
- [x] H5 CORS Spike（确认后端未配置 CORS，缺口已记录）；
- [x] Proposed ADR 更新状态（ADR-003/ADR-005 已 Accepted）。
- [x] 正式工程依赖树可复现且无 extraneous/missing dependency；
- [x] OpenAPI 导出与生成类型漂移检查（45 paths / 108 schemas，认证响应不再是 unknown）；
- [x] HTTP Client 风险矩阵基础测试（14 项 API/环境测试；全项合计 19 项）；
- [x] 正式工程四端 Build；H5 281 KiB 基线告警已记录。
- [x] 账号登录代码链：Endpoint/Runtime Guard/Session/Storage/Context/受控表单/守卫/登出，Jest 7 套件 / 29 项；四端 Build 通过，H5 当前 327 KiB。
- [x] 账号密码注册补漏工程链：UserCreate 请求投影、User Runtime Guard、AuthContext、受控五字段表单、确认密码、登录/注册白名单回跳、同步防双击与 POST unknown；完整 Jest 38 套件 / 255 项、静态检查与 OpenAPI 漂移通过，注册页微信隔离构建生成完整产物。四端 production build 沿用注册补漏前的 Phase 8.1 基线；微信注册 Functional 已通过。
- [x] 公开 Product 列表代码链：Endpoint/Runtime Guard/分页/迟到响应隔离/图片 Resolver/四态，针对性 Jest 4 套件 / 16 项、完整 Jest 10 套件 / 44 项、Product 后端 API 52 项及四端 Build 通过。
- [x] 公开 Product 列表基础 Functional：游客、Empty、错误恢复、登录/退出后继续浏览。
- [x] 公开 Product 列表/详情数据 Functional：Content、相对图片、第二页、筛选/搜索、Experience/Kit 详情与真实多配置 Option（2026-08-22）。
- [x] 微信开发者工具连接本地隔离后端的账号密码认证 Functional：错误/正确/禁用账号、三种角色、Storage、重启 `/users/me` 恢复、登出、主动/被动 refresh 与无效 refresh 清理全部通过（2026-08-20；本地 SQLite + Redis，非真机/非 H5/非微信登录）。
- [x] Phase 7.1 Cart：代码、自动化及微信 Functional 全部通过，含有库存 Kit 加入且无 Experience 配置（2026-08-24 用户确认）。
- [x] Phase 7.2 Order 创建工程门槛：Endpoint/Runtime Guard、确认页、登录白名单返回、提交状态机、unknown、服务端结果与 Cart 对账；完整 Jest 19 套件 / 130 项、静态检查、OpenAPI 漂移、FastAPI + SQLite Order 34 项、完整后端 1445 项（9 项 MySQL-only 跳过）和四端 build 通过。
- [x] Phase 7.2 微信 Functional：真实登录返回、Experience/Kit/混合创建、库存不足、快速连点、弱网 unknown 与成功 Cart 对账全部通过（2026-08-24 用户确认；非真机/非 H5）。
- [x] Phase 7.3 Order 查询/取消工程门槛：列表/筛选/分页、owner-only 详情、历史快照、empty-body cancel、unknown/40921 收敛；完整 Jest 25 套件 / 172 项、静态检查、OpenAPI 漂移、Order HTTP 53 项、完整后端 1445 项（9 项 MySQL-only 跳过）和四端 build 通过。
- [x] Phase 7.3 微信 Functional（除竞态）：登录回跳、筛选/分页、创建 unknown 核对、详情快照、Pending 取消与库存恢复、终态无按钮、弱网 unknown 均由用户确认通过（2026-08-24）。
- [x] Phase 7.3 40921 双端竞态：2026-08-25 用户使用独立客户端先把 Pending 变为 Paid，旧用户详情 cancel 收到 40921 后重新 GET 并收敛到 Paid，未重复发送 cancel PATCH。
- [x] Phase 7.4 ADMIN Order 工程门槛：完整筛选、管理详情、权限边界、empty-body paid/complete、unknown/40921 收敛与 `admin` 分包；完整 Jest 31 套件 / 213 项、静态检查、OpenAPI 漂移、Order API 107 项、完整后端 1445 项（9 项 MySQL-only 跳过）和四端 build 通过。
- [x] Phase 7.4 微信 Functional：2026-08-25 用户确认普通用户边界、ADMIN 登录回跳/筛选/详情、Pending → Paid、Paid → Completed、终态无按钮、库存不变、弱网 unknown、40921 竞态及普通用户直调 ADMIN API 403/不 refresh 全部通过。断网分支显示“结果待确认”且未自动再次 PATCH；Slow 3G 约 310 ms 返回而未触发 timeout，严格 timeout 只保留为非阻断补测。
- [x] 2026-08-28 ADMIN Order 商品名称筛选工程与微信 Functional：历史 `product_name` 快照包含匹配、当前 Product 改名隔离、多 Item 命中去重、组合筛选、完整 `item_count/total/pages`、Query 白名单、翻页保持和页面入口均已覆盖；后端定向 128 项、Order 411 项、完整 1457 项（9 项 MySQL-only 跳过）、前端 47 套件/330 项、静态检查、OpenAPI 漂移与四端 build 通过，用户确认微信验证全部通过。
- [x] Phase 8.1 ADMIN Product 只读管理工程实现：列表/筛选/分页、两类详情、草稿/删除形状、权限与路由边界均已落地；定向前端 8 套件/39 项、完整前端 37 套件/240 项、Product API 52 项、完整后端 1445 项（9 项 MySQL-only 跳过）、静态检查、OpenAPI 漂移和四端 Build 全部通过。
- [x] Phase 8.1 微信 Functional：2026-08-25 用户确认 Guest 固定入口登录跳转、普通用户边界、ADMIN 登录回跳、筛选/分页、Experience/Kit 详情、断网重试、无 mutation 按钮、Draft 空配置与逻辑删除标记全部通过。
- [x] Phase 8.2 微信业务 Functional：2026-08-26 用户确认 Experience/Kit 创建、零库存、基本信息 diff/描述清空、Draft/Offline 删除、删除记录查回、Online/已删除边界、快速连点、unknown 核对和普通用户权限全部通过。
- [x] Phase 8.2 延期视觉问题已关闭（2026-08-29）：原生 `Form` 不再直接承担白色卡片背景/边框/圆角，管理页改为 `View` 视觉外壳后用户复测白色图案全部消失；登录输入 `_` 闪烁后续无法复现并由用户确认已消失。
- [x] Phase 8.3 工程门槛：Option/Kit price Endpoint、Runtime Guard、状态机、分型配置页、权限/路由/表单自动化；完整前端、静态检查、OpenAPI、四端 build、Product API 与后端全量回归均通过。
- [x] Phase 8.3 微信 Functional（已可验收范围）：2026-08-26 用户确认 Option 新增/恢复/修改/删除、Kit 改价、权限、重复点击、unknown 核对与 Online/删除边界全部通过。
- [x] Phase 8.3 延期联动验收：为存在历史订单的 Online 商品下架改价，确认旧订单保持旧快照、新订单使用新价格；2026-08-28 已随 8.4–8.5 微信 Functional 通过。
- [x] Phase 8.4–8.5 工程门槛：图片选择/上传适配、multipart/refresh、图片生命周期、readiness/上下架状态机、权限/路由/页面自动化；完整前端、静态检查、OpenAPI、四端 build 与 Product API 回归均通过。
- [x] Phase 8.4–8.5 微信 Functional：2026-08-28 用户确认真实相册/相机与三种格式、大小/内容拒绝、封面/排序/删除、Option 图片归属、完整 readiness、Kit 零库存上架、下架不改库存/历史、unknown 核对，以及 8.3 订单快照联动全部通过。
- [x] Phase 8.8–8.9 Product Audit/ADMIN User/当前范围 Review 微信 Functional：2026-08-28 用户确认全部通过，包括 Swagger 独立 ADMIN Session 禁用后旧 refresh/access 阻断与前端 Session 清理。
- [x] Phase 8.6 工程门槛：Inventory Endpoint/Runtime Guard、201/200 metadata、业务意图幂等、指定 Kit/全局流水、权限/路由/筛选/分页；定向 9 套件/42 项并补充共享 Client metadata 回归，完整前端 60 套件/375 项、静态检查、OpenAPI 漂移、四端 build 与完整后端 1465 项（9 项 MySQL-only 跳过）全部通过。
- [x] Phase 8.6 微信 Functional：2026-08-28 用户确认 Guest/普通用户/ADMIN 边界、Draft/Offline/Online 与逻辑删除 Kit、正负调整/40932、快速连点、unknown 安全重试 201/200、两类流水与组合筛选/分页/订单跳转/隐私字段全部验证完成并通过。

### MVP 功能完成

- [ ] 微信/H5 用户纵向 E2E；
- [ ] 支付宝/抖音 Build + Smoke；
- [ ] API Client 与真实后端集成矩阵；
- [ ] 后端完整测试；
- [ ] 文档与类型无漂移。

### 正式公开发布

- [ ] 微信登录；
- [ ] 商业需要时的微信支付闭环；
- [ ] Order create 幂等；
- [ ] 生产对象存储/CDN；
- [ ] 登录/注册限流和认证安全 Review；
- [ ] 持久 MySQL 迁移按流程执行；
- [ ] 真机、隐私、HTTPS、合法域名、回滚全部通过。
