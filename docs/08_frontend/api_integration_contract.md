# pinkdooHub 前端 API 集成契约

> **Document Version:** v0.6
> **Status:** Draft
> **Last Updated:** 2026-08-24
> **Source of Truth:** 实际 FastAPI OpenAPI、路由/Schema/测试及对应业务/API 文档

本文档是 Taro 客户端与现有 FastAPI 后端之间的适配契约。它不复制各模块完整 API 文档，而是冻结所有前端模块必须共同遵守的解析、认证、类型、错误、上传和幂等规则。

## 0. 当前实现状态

基础集成层、账号密码登录、公开 Product、用户侧 Order 与 ADMIN Order 人工状态纵向链路已落地：

- `scripts/export_openapi.py`：隔离导出当前 FastAPI OpenAPI；
- `miniapp/openapi/openapi.json`：45 条路径、108 个 Schema 的生成输入；
- `miniapp/src/api/generated/schema.d.ts`：`openapi-typescript@7.13.0` 生成的只读、字母序类型；
- `miniapp/src/api/client.ts`：统一信封、Query、Bearer、错误与 refresh 边界；
- `miniapp/src/api/taro_transport.ts`：`Taro.request` Transport 与取消/网络/超时分类；
- `miniapp/src/api/factory.ts`：消费严格校验后的 `TARO_APP_API_ORIGIN`；
- `miniapp/src/api/endpoints/auth.ts`：login/refresh/logout/getMe 薄 Endpoint，以及认证数据 Runtime Guard + 白名单投影；
- `miniapp/src/auth/`：Session Manager、启动恢复、Context 与运行时组合；`miniapp/src/platform/storage.ts` 提供 Taro Storage Adapter；
- `miniapp/src/pages/login/`：现有账号密码受控登录表单；公开首页按认证状态显示登录、当前用户或登出，但游客浏览不依赖认证；
- `miniapp/src/api/endpoints/products.ts`：公开列表 Query/响应生成类型、运行时 Guard 与白名单投影；
- `miniapp/src/features/product/`：第一页、下一页、四态、重复加载保护与迟到响应隔离；`miniapp/src/utils/asset_url.ts` 是相对图片 URL 的唯一解析点；
- `miniapp/src/api/endpoints/orders.ts`：用户创建/列表/详情/取消与 ADMIN 列表/详情/paid/complete 的最小请求投影，以及 Detail/Page/Status Runtime Guard；
- `miniapp/src/features/order/`：本地 Cart、一次提交状态机、用户/管理列表竞态隔离、详情命令 unknown/40921 状态收敛；`miniapp/src/auth/login_route.ts` 只允许登录返回已注册的固定确认页、用户列表或管理列表；
- `miniapp/src/pages/order-confirm/`、`pages/orders/`、`pages/order-detail/`：用户创建、核对、查询与 Pending 取消；`miniapp/src/admin/pages/`：ADMIN+ 完整筛选、详情、Pending → Paid 和 Paid → Completed。完整前端为 31 套件 / 213 项；OpenAPI 类型漂移检查与四端 production build 通过，Order API 后端回归 107 项及完整后端 1445 项通过（9 项 MySQL-only 跳过）。

认证、Product 浏览、Cart 与 Order 创建已在微信开发者工具连接本地 FastAPI + SQLite + Redis 完成既定 Functional。Order 查询/详情/取消由用户确认除 40921 双端竞态外均通过；该竞态仍待补测。ADMIN Order 工程实现、自动化和四端构建已完成，微信 Functional 待验证。H5 真实跨域联调仍受后端尚未注册 CORS allowlist 限制。微信登录、真实支付、前端上传和其他管理业务页面仍未交付。

---

## 1. 权威来源与漂移规则

按以下优先级判断“当前可调用能力”：

1. 实际代码、自动化测试和运行时 OpenAPI；
2. `docs/03_api/` 对应契约；
3. `docs/01_requirements/` 业务规则；
4. 未来计划和目录示意。

发现冲突时不得静默选择或由前端补造接口，应记录到 API Gap Matrix 并回到后端契约修复。

当前已验证 FastAPI 可生成 OpenAPI，并包含 HTTP Bearer Security Scheme。正式工程使用 `openapi-typescript` 只生成类型，不生成依赖 Fetch/Axios 的 transport。

生成规则：

- FastAPI 是类型源；
- 生成文件禁止手工编辑；
- Endpoint API 手工保持薄且语义化；
- CI 重新导出/生成并检查 Git diff；
- OpenAPI 不能替代运行时 Guard；
- API 变更必须和后端文档、测试、前端类型同一逻辑改动。

---

## 2. Base URL 与环境

API 路径前缀：

```text
/api/v1
```

Endpoint 只接收相对路径。HTTP Client 按 `APP_ENV` 选择 Origin：

```text
development → 本地/开发 API
testing     → 隔离集成 API
production  → HTTPS 生产 API
```

页面、组件和 Feature 禁止硬编码 Origin。

---

## 3. 统一响应信封

成功：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

失败：

```json
{
  "code": 40921,
  "message": "...",
  "data": null
}
```

HTTP Client 的最低运行时 Guard：

- 响应是非 null object；
- `code` 是 number；
- `message` 是 string；
- 存在 `data` 字段（允许 null）；
- code `0` 才返回 typed data。

不能因为 `Taro.request` 进入成功回调就判定业务成功。必须同时检查 HTTP status、信封和业务 code。

---

## 4. 认证与 Token

### 4.1 登录响应

```text
access_token
refresh_token
token_type = Bearer
expires_in = 7200
user
```

客户端保存安全必要字段，并计算 `expiresAt`。密码永不持久化。

当前实现把 Token 只保存在 `SessionManager` 内存和 Taro Storage 中；React Context 只接收不含 Token 的 User/Session Snapshot。Storage 恢复输入仍按 `unknown` 校验，版本或字段损坏时主动删除。Taro Storage 不是硬件安全区，H5 环境尤其必须以 XSS 防护、短期 access token、后端撤销和未来 refresh 轮换共同降低风险。

启动恢复顺序固定为：读取并校验 Storage → access token 临近过期时 refresh → `/users/me` 服务端验证 → 标记 authenticated。缓存中的 User 只改善恢复体验，不是授权证据。

### 4.2 Header

受保护请求：

```text
Authorization: Bearer <access_token>
```

`Idempotency-Key` 只在对应 Inventory 请求中添加，不作为通用请求 Header 泄漏给所有端点。

### 4.3 当前特殊错误

| 情况 | 当前契约 | 前端行为 |
|------|----------|----------|
| 缺少 Bearer | HTTP 401 / code 401 | 未登录；必要时转登录 |
| 权限不足 | HTTP 403 / code 403 | 显示无权限；不刷新 Token |
| 无效/过期 Token | HTTP 400 / code 1006 | 触发一次 refresh 流程 |
| refresh 失败 | 业务/认证错误 | 清理会话并要求重新登录 |

不得只监听 HTTP 401，否则无法处理当前 `1006` 契约。

### 4.4 Single-flight Refresh

多个并发请求同时遇到 `1006` 时：

1. 第一项创建共享 refresh Promise；
2. 后续等待同一 Promise；
3. 成功后各自仅重放一次原请求；
4. 失败时只清理一次会话；
5. refresh 请求本身不进入 refresh 循环；
6. 重放后仍 `1006` 直接失败。

写请求只有在明确知道首次未被业务执行时才允许由该流程重放。正式实现前必须测试 Taro transport 在认证失败返回点的行为。

---

## 5. 错误适配

| 类别 | 识别 | 公开信息 |
|------|------|----------|
| Network | 未收到 HTTP | 可重试提示，不含底层敏感配置 |
| Timeout | 明确超时 | 标记结果可能未知，写请求不自动重试 |
| HTTP | 非预期 status/非信封 | status + 安全 endpoint operation |
| Business | 非 0 code | code/message/允许公开 data |
| Validation | HTTP 422 `data.errors` | 字段 location/message/type |
| Product readiness | code `42201` | 完整 `data.issues`，一次展示 |
| Auth | 401/1006/refresh 失败 | 清理或刷新流程 |
| Authorization | 403 | 无权限，不伪装资源不存在 |
| Contract | 最低形状错误 | 通用错误 + 内部安全诊断 |

HTTP 状态由后端异常类型决定，前端禁止按 code 数字段推断 404/409/422。

---

## 6. 数据类型

### 6.1 Money

Product 与 Order 金额是普通十进制字符串，响应固定两位：

```json
"599.00"
```

规则：

- 不转 float 做权威计算；
- 请求价格保持后端接受的普通十进制字符串；
- 不提交指数形式；
- 不静默四舍五入；
- Order 总额只显示服务端快照。

### 6.2 Datetime

响应使用 ISO 8601 UTC。客户端显示时可转换到用户本地时区；管理筛选发送给后端时必须显式转换为 UTC。

### 6.3 Enum

响应常用：

```json
{
  "value": "pending",
  "label": "待支付"
}
```

- 判断、筛选和请求使用 `value`；
- 默认展示后端 `label`；
- 不提交 `label`；
- 未知 value 不用危险的强制断言掩盖，应进入兼容或 ContractError。

### 6.4 IDs

路由、Storage 和输入框得到的 ID 先视为字符串/unknown，再验证为正整数。禁止用 `Number(value) || 0` 把非法值静默转成 0。

### 6.5 Null 与缺失

- 缺失字段和 `null` 不等价；
- PATCH 只提交用户真正修改的字段；
- 不把所有空输入自动转换为 `null`；
- Kit 的 `experience_option_id` 省略或 null，Experience 必须提供有效正整数。

---

## 7. 分页、筛选与竞态

分页统一：

```text
page >= 1
page_size 在后端允许范围
```

响应：

```text
items / total / page / page_size / pages
```

客户端要求：

- 修改筛选时重置 page 和 items；
- 防止同一页并发重复请求；
- 防止旧搜索响应覆盖新查询；
- total/pages 使用服务端值；
- 无下一页时不再请求；
- Query 只发送 Endpoint 明确允许的字段。

---

## 8. 文件与图片

图片上传使用 `Taro.uploadFile` 适配器，不能当普通 JSON POST。

当前 Product 上传限制：

- 最大 2 MiB；
- jpg/png/webp；
- 服务端验证内容、MIME 和路径；
- 客户端检查只用于提前反馈；
- 上传失败或业务失败不能展示伪成功。

当前开发图片地址可能为相对路径。唯一 `resolveAssetUrl()` 规则：

- `https://` 等绝对 URL 原样返回；
- 以 `/` 开头的路径相对 API Origin；
- 空值按调用方 Schema 语义处理；
- 禁止在各页面重复拼接。

---

## 9. 写请求与幂等

### 9.1 默认策略

- 禁止通用层自动重试 POST/PATCH/PUT/DELETE；
- UI 防连点不能替代服务端幂等；
- 网络超时意味着结果可能未知；
- 恢复后优先查询权威状态，而不是直接再提交。

### 9.2 Inventory 调整

```text
POST /admin/products/kit/{product_id}/inventory-adjustments
Idempotency-Key: <stable-client-key>
```

同一次用户操作：

- 首次生成 key；
- 网络重试复用同一 key；
- 首次可能 HTTP 201；
- 幂等重放 HTTP 200；
- 201/200 均解析成功 data；
- key 不记录到日志或 UI。

### 9.3 Order 创建

当前 `POST /orders` 没有客户端幂等键。客户端必须禁用重复提交，不在超时后自动重试。正式商业发布前应把 Order create idempotency 作为后端契约缺口处理。

当前实现进一步冻结：

- `OrderSubmissionStore` 在一次进行中的提交内复用同一个 Promise，页面按钮同时禁用；两层保护都不等于服务端幂等；
- 请求开始时复制 Cart 快照，后续用户修改不改变已发出的请求；Experience 必须携带 `experience_option_id`，Kit 省略该字段；
- 空白 remark 省略，非空 remark trim 后发送且最多 500 字符；请求只允许 `items` 与可选 `remark`；
- 明确业务、认证或非 5xx HTTP 拒绝进入 `failed`，可以修正后由用户重新提交；network/timeout/cancel、成功响应契约损坏或 HTTP 5xx 无法证明事务未提交，进入 `unknown` 且页面不提供立即重试；
- 成功结果只消费服务端 `OrderDetailOut` 快照。随后按已提交快照对账 Cart：当前数量相等则移除，大于提交量则扣除，小于提交量则保留并提示冲突；无关 Item 保留；
- Cart 对账或 Storage 失败不改变“服务端订单已创建”的事实，只显示本地清理警告，避免用户再次 POST；
- unknown 保留 Cart、不宣称失败、不自动重发，并提供“我的订单”入口读取服务端权威结果。

---

## 10. 特殊业务契约

### 10.1 Product

- 公开列表/详情只返回有效 Online Product；
- Experience 选择必须解析为实际 Option，不构造笛卡尔积中不存在的组合；
- Kit `stock/available` 只用于展示，下单时服务端重检；
- 管理上架 `42201` 一次返回全部 readiness issues；
- 金额保持字符串。

### 10.2 Order

- Item 1–10，quantity 1–99，以实际 OpenAPI 常量为准；
- 同一 Product/Option 组合不能重复；
- Experience 必须有有效 Option；Kit 必须无 Option；
- 本地 Cart 使用同一组合身份；重复加入在发送前合并 quantity，不同 Experience Option 保持不同 Item；
- Cart 名称、配置、图片和价格是非权威预览字段；创建请求必须白名单投影，禁止把这些字段发给后端；
- 当前 Cart Storage 是设备级游客缓存，版本为 `pinkdoohub.cart.v1`；坏数据清除，登录/退出不自动清空；
- 我的订单固定由服务端按 `created_at DESC, id DESC` 排序；前端使用 `page/pages/total` 分页事实和可选 status 筛选，不根据本页长度推断总页数；
- `item_count` 表示订单 Item 行数而非 quantity 总和；列表、详情和状态响应均按 unknown 做 Runtime Guard 与白名单投影；
- 详情只渲染 Order Item 历史快照，不用当前 Product 名称、价格或 Option 覆盖；不存在与他人订单的 `40411` 使用同一不可访问提示；
- 状态只允许 `pending → cancelled`、`pending → paid`、`paid → completed`；
- cancel/paid/complete 三个 PATCH 不发送任何 body，连 `{}` 也不能发送；
- 用户取消只在服务端详情为 Pending 时提供；进行中 Promise 合并不替代后端状态机。network/timeout/cancel、5xx 或成功响应契约损坏进入 unknown，不自动 PATCH；
- cancel 成功后重新 GET 详情；刷新失败不改变已确认的 cancelled 事实。`40921` 后也重拉服务端状态，以收敛跨端竞态；
- ADMIN 列表只发送 page/page_size/status/order_no/user_id/created_from/created_to；日期界面若按“包含结束日”表达，必须转成次日 UTC 零点作为 API 排他 `created_to`；
- ADMIN 列表/详情只接收安全的 `user_id/user_nickname`。客户端角色守卫在挂载 Hook 前阻止普通用户请求，但后端 ADMIN+ dependency 仍是唯一授权边界；
- ADMIN 详情只从服务端当前状态派生唯一命令：Pending → Paid，Paid → Completed，Cancelled/Completed 无命令。paid/complete 与 cancel 共用结果未知和成功后 GET 的收敛规则；
- 用户不存在/他人订单统一 40411；
- MVP Paid 只由 ADMIN+ 人工确认。

### 10.3 Inventory

- 调整要求 ADMIN+、change、reason、Idempotency-Key；
- 首次 201、重放 200；
- `40931` 库存不足不包含精确 available；
- 流水不输出内部幂等键；
- UTC 筛选和分页严格遵循后端 Query。

---

## 11. 当前 API Gap Matrix

| 需求 | 当前实际状态 | 前端决策 |
|------|--------------|----------|
| 用户名密码 | 已实现 | MVP 使用 |
| 微信登录 | 未实现 | 正式公开发布前新增后端契约 |
| 微信支付 | 未实现 | MVP 显示待商家确认；商业发布前新增 |
| 头像上传 | 实际 OpenAPI 未提供 | 不创建入口 |
| 管理员启用用户 | 未实现 | 不创建伪功能 |
| 管理员用户详情 | 实际 OpenAPI 未提供 | 列表只用现有字段 |
| Order 创建幂等 | 未提供客户端 key | 禁止自动重试；发布前补齐 |
| 生产图片 | 当前开发本地/相对 URL | 开发 resolver；生产对象存储/CDN |
| H5 CORS | FastAPI 当前未注册 | H5 联调前实现严格 allowlist |
| Refresh rotation | 未实现 | MVP 接受已知限制；公开发布前安全 Review |
| 登录/注册限流 | 未实现 | 公开发布前后端门槛 |

---

## 12. 页面—API 矩阵

| 页面/用例 | 主要 API | 认证/角色 |
|-----------|----------|-----------|
| 注册 | `POST /auth/register` | Guest |
| 登录 | `POST /auth/login` | Guest |
| 恢复会话 | `POST /auth/refresh`、`GET /users/me` | Refresh/User |
| 商品列表 | `GET /products` | Guest |
| 本地购物车 | 无网络请求；Taro Storage | Guest/User |
| Experience 详情 | `GET /products/experience/{id}` | Guest |
| Kit 详情 | `GET /products/kit/{id}` | Guest |
| 创建订单 | `POST /orders` | USER+ |
| 我的订单 | `GET /orders` | USER+ |
| 订单详情 | `GET /orders/{id}` | USER+ |
| 取消订单 | `PATCH /orders/{id}/cancel` | USER+；empty body |
| 管理商品 | `/admin/products...` | ADMIN+ |
| 管理库存 | `/admin/.../inventory-adjustments`、流水 GET | ADMIN+ |
| 管理订单列表/详情 | `GET /admin/orders`、`GET /admin/orders/{id}` | ADMIN+ |
| 人工支付/完成 | `PATCH /admin/orders/{id}/paid`、`PATCH /admin/orders/{id}/complete` | ADMIN+；empty body |
| 用户列表/禁用 | `/admin/users...` | ADMIN+ |

完整字段和错误以对应模块 API 文档及 OpenAPI 为准。

---

## 13. 契约变更流程

1. 后端先更新业务/API Schema、实现和测试；
2. 导出 OpenAPI；
3. 重新生成 TypeScript 类型；
4. 更新 Endpoint、Runtime Guard 和前端测试；
5. 更新本文件的公共集成规则或 Gap Matrix；
6. 运行后端完整回归与前端四端构建；
7. Git diff 确认无手改生成文件和意外输出。
