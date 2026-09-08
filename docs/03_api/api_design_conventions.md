# API Design Conventions

> **Document Version:** v2.5
> **Status:** Active
> **Scope:** 项目级 — Product / Order / User / Inventory 等全部模块必须遵守
>
> 本文档定义 pinkdooHub 所有 API 的强制性设计规范。新增或修改接口时，必须对照本文档逐项检查。
>
> **业务模块 API 文档：** [User API](user_api.md) · [Product API](product_api.md) · [Order API](order_api.md) · [Inventory API](inventory_api.md) · [Wallet API](wallet_api.md) · [Reservation API](reservation_api.md)
>
> **快速检查清单见 [§18](#18-快速检查清单)。**

---

## 0. Data Flow（数据流向）

核心原则：**数据库存原始值，API Mapper 负责展示转换，Response 面向前端。**

```
Database                  API Mapper                  Response
────────                  ──────────                  ────────
duration_minutes = 60  →  转换  →  { "value": 60, "label": "1小时" }
day_type = "weekday"   →  转换  →  { "value": "weekday", "label": "工作日" }
status = "online"      →  转换  →  { "value": "online", "label": "已上架" }
```

| 层 | 职责 | 禁止 |
|----|------|------|
| Database | 保存原始值，便于计算和索引 | 保存展示文案（"1小时"） |
| Service | 返回领域值或已加载聚合 | 依赖 API Out Schema 或生成展示文案 |
| API Mapper | 转换原始值 → `{value, label}` DTO | 查询数据库或把内部字段透传给响应 |
| Response | 返回 `{value, label}`，前端直接展示 | 返回数据库原始字段名（`duration_minutes`） |
| Request | 前端提交 `value` | 提交 `label`（"1小时"） |

---

## 1. Base URL

```
/api/v1
```

所有接口路径均以此为前缀。

---

## 2. URI 命名规范

### 2.1 基本规则

| 规则 | 说明 |
|------|------|
| 小写 | 全部使用小写字母 |
| 资源名用复数 | `/users`、`/products`、`/orders` |
| 单词分隔用短横线 | `/order-items`、`/product-experiences` |
| 路径参数用 `{id}` | `/users/{id}`、`/orders/{id}` |
| 层级不超过 3 层 | `/users/{id}/orders` ✅ `/users/{id}/orders/{oid}/items` ❌ |
| 动词用 HTTP Method 表达 | `/users/create` ❌ → `POST /users` ✅ |

### 2.2 示例

```
# 用户端（public）
GET    /products                          # 商品列表
GET    /products/experience/{id}          # 拼豆体验详情
GET    /products/kit/{id}                 # 拼豆套装详情

GET    /users/me                          # 当前用户信息
PATCH  /users/me                          # 当前用户修改资料

# 管理端（admin）
GET    /admin/products                    # 管理端商品列表
POST   /admin/products/experience         # 创建体验商品
POST   /admin/products/kit                # 创建套装商品
PATCH  /admin/products/{id}               # 编辑商品基本信息
DELETE /admin/products/{id}               # 逻辑删除
PATCH  /admin/products/{id}/online        # 上架
PATCH  /admin/products/{id}/offline       # 下架
POST   /admin/products/experience/{id}/options # 新增 Option
PATCH  /admin/options/{option_id}         # 修改 Option
DELETE /admin/options/{option_id}         # 删除 Option

GET    /admin/users                       # 管理端用户列表
PUT    /admin/users/{id}/disable          # 管理端禁用用户
```

### 2.3 命名优先级

```
资源集合 → 资源标识 → 子资源 → 动作
/admin/users/{id}/disable
  ↑      ↑     ↑      ↑
 范围   集合   标识    动作
```

---

## 3. HTTP Method

| Method | 语义 | 幂等 | 示例 |
|--------|------|------|------|
| GET | 查询资源 | ✅ | `GET /products` |
| POST | 创建资源 | ❌ | `POST /auth/register` |
| PUT | 整体替换 | ✅ | `PUT /users/me` |
| PATCH | 部分更新 | ❌ | `PATCH /products/{id}/status` |
| DELETE | 删除资源 | ✅ | `DELETE /products/{id}` |

> **本项目约定**：全量更新用 `PUT`，状态变更用 `PATCH`（如 online/offline），创建用 `POST`。

---

## 4. 认证与授权

### 4.1 认证方式

JWT Bearer Token

```
Authorization: Bearer <access_token>
```

认证依赖统一使用 `HTTPBearer(auto_error=False)`，由共享异常中间件输出项目错误信封：缺失 Bearer 凭据返回 HTTP 401 / code `401` / `Authentication required`，不得暴露 FastAPI 默认 `{"detail": ...}`。当前无效或过期 Token 仍沿用 User 模块既有 `TokenExpired` 契约（code `1006`、HTTP 400）；若后续迁移为 401，必须作为公共认证契约变更同步所有 API 文档和测试。

### 4.2 Token 机制

| 概念 | 说明 |
|------|------|
| access_token | 访问令牌，有效期 2 小时 |
| refresh_token | 刷新令牌，用于获取新的 access_token |

每次登录创建独立 refresh family。刷新必须原子轮换 access/refresh 双 Token；旧 refresh 重放时撤销该 family。密码修改、外部身份解绑、用户禁用/注销通过 `auth_version` 和 Redis family 撤销使旧会话失效。身份限流使用 Redis 原子计数并 fail closed，客户端不得依据 429/1002/1003 等响应枚举有效账号。

### 4.3 接口角色标注

每篇 API 文档的端点列表中必须标注"认证"和"角色"两列：

| Method | URI | 描述 | 认证 | 角色 |
|--------|-----|------|------|------|
| GET | /products | 商品列表 | ❌ | 游客 |
| POST | /products | 创建商品 | ✅ | 管理员 |

### 4.4 角色定义

| 角色 | 说明 |
|------|------|
| 游客 | 未登录，可浏览公开内容 |
| user（普通用户） | 已登录，可操作个人数据 |
| admin（管理员） | 已登录，可管理所有资源 |

---

## 5. 请求规范

### 5.1 Content-Type

| 场景 | Content-Type |
|------|-------------|
| JSON 请求体 | `application/json` |
| 文件上传 | `multipart/form-data` |

### 5.2 参数位置

| 参数类型 | 位置 | 示例 |
|----------|------|------|
| 路径参数 | URL Path | `/users/{id}` |
| 查询参数 | Query String | `?page=1&page_size=20` |
| 请求体 | Request Body (JSON) | `{"username":"alice"}` |
| 文件 | Form Data | `file=@avatar.jpg` |

### 5.3 查询参数命名

使用 snake_case：

```
?page=1&page_size=20&sort_by=created_at&sort_order=desc
```

---

## 6. 响应规范

### 6.1 统一信封

所有接口返回统一结构：

```json
{
    "code": 0,
    "message": "success",
    "data": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | int | 是 | 业务状态码，`0` 表示成功 |
| message | string | 是 | 可读的状态描述 |
| data | any | 否 | 返回数据，无数据时为 `null` |

实现层使用 `success()` 构造运行时成功信封，异常中间件构造错误信封；OpenAPI 必须分别通过泛型 `SuccessResponse[T]` 和 `ErrorResponse` 精确声明响应结构，不能保留无约束的 `object`。如果 API Mapper 已经完成严格 Out Schema 校验并把 `Decimal` 等领域值序列化为契约字符串，路由应通过 `responses` 声明 OpenAPI 模型并保持 `response_model=None`，避免 FastAPI 对已序列化数据进行第二次、语义不同的校验。

### 6.2 成功响应

```json
// 单个对象
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "username": "alice"
    }
}

// 列表（分页）
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [...],
        "total": 100,
        "page": 1,
        "page_size": 20
    }
}

// 无数据返回
{
    "code": 0,
    "message": "User disabled"
}
```

### 6.3 错误响应

```json
// 业务错误
{
    "code": 1001,
    "message": "Username already exists"
}

// 参数或业务语义校验失败（422）
{
    "code": 422,
    "message": "Validation failed",
    "data": {
        "errors": [
            {
                "location": ["body", "username"],
                "message": "String should have at least 3 characters",
                "type": "string_too_short"
            }
        ]
    }
}
```

FastAPI 请求参数错误由全局 `RequestValidationError` handler 转换为上述信封。每项只包含 `location`、`message` 和 `type`，不得回显原始输入值，避免密码、Token 或其他敏感内容进入响应与日志。业务聚合状态的 HTTP 422（例如 Product `42201`）继续使用对应命名异常规定的数据结构，不套用 `data.errors`。

### 6.4 传输压缩

客户端发送 `Accept-Encoding: gzip` 时，直连 Uvicorn 和受管 Nginx 均对不小于 1024 bytes 的 JSON/文本响应启用 gzip level 6，并返回 `Content-Encoding: gzip` 及 `Vary: Accept-Encoding`。不声明 gzip 或显式请求 `identity` 的客户端仍获得未压缩的相同 JSON 契约；响应体的业务字段、状态码和签名语义不变。

`/uploads/products/` 与 Nginx 的 PNG/JPEG/WebP 等已压缩图片 MIME 明确绕过 gzip，避免无效 CPU 开销和可能的体积增长。Brotli 当前未引入：固定 `nginx:1.27.5-alpine` 不包含 Brotli 模块，只有在真实链路测量证明进一步收益且新模块/镜像通过供应链 Review 后才能增加。

### 6.5 字段排除规则

以下字段**不得**在 API 响应中返回：

| 字段 | 原因 |
|------|------|
| password | 安全，密码哈希不可泄露 |

---

## 7. HTTP 状态码

| 状态码 | 含义 | 使用场景 |
|--------|------|----------|
| 200 | OK | 请求成功 |
| 201 | Created | 创建资源成功 |
| 400 | Bad Request | 请求格式错误 |
| 401 | Unauthorized | 未认证或 Token 无效 |
| 403 | Forbidden | 已认证但无权限 |
| 404 | Not Found | 资源不存在 |
| 409 | Conflict | 资源冲突（如用户名已存在） |
| 413 | Payload Too Large | 上传文件超过大小限制 |
| 422 | Unprocessable Entity | 参数校验失败，或请求语法正确但当前业务聚合不满足处理条件 |
| 500 | Internal Server Error | 服务器内部错误 |
| 503 | Service Unavailable | 实例存活，但关键依赖暂不可用，或受控业务能力/支付 Provider 尚未开放 |

> 业务状态以响应体中的 `code` 字段为准，HTTP 状态码用于表达请求层面的结果。

业务异常通过异常类型映射 HTTP 状态，不根据业务错误码的数字范围推断：

| 异常类型 | HTTP status | 语义 |
|----------|-------------|------|
| `BusinessException` | 400 | 一般业务规则不满足 |
| `UnprocessableEntityException` | 422 | 请求语法正确，但当前业务数据或聚合状态不满足处理条件 |
| `ServiceUnavailableException` | 503 | 关键基础设施不可用，或受控资金能力 fail closed；失败路径不得产生业务写入 |

`UnprocessableEntityException` 是通用异常类型并继承 `BusinessException`；全局异常中间件必须为它注册更具体的 HTTP 422 映射，同时保持普通 `BusinessException` 为 HTTP 400。模块命名异常可以继承该通用类型，例如 Product 的 `ProductNotReadyForOnline`。禁止使用 `if 42200 <= code < 42300` 一类号段判断 HTTP 状态。

> **实现状态：** 上述 HTTP 422 业务异常类型和中间件映射已实现；Product Validator、Service 和 21 个 API 端点也已完成，并由异常契约、业务规则、事务回滚、权限、OpenAPI 与真实 HTTP 集成测试覆盖。Product 原库存直设端点已在 Phase 4.3.10 移除，库存写入统一由 Inventory API 承担。

### 7.1 Liveness 与 Readiness

运行时探针不需要认证，并按职责拆分：

| Method | URI | 外部依赖 | 成功 | 失败语义 |
|--------|-----|----------|------|----------|
| GET | `/api/v1/health` | 无 | HTTP 200；保留既有 `app/env/status=ok` 响应 | 仅作兼容入口，不代表依赖可用 |
| GET | `/api/v1/health/live` | 无 | HTTP 200；`status=alive` | 进程无法响应时由运行平台判定失败 |
| GET | `/api/v1/health/ready` | MySQL/SQLite 默认连接、Redis | 两项均为 `up` 时 HTTP 200；`status=ready` | 任一失败或超过单项 1 秒时 HTTP 503 / code `503`；`status=not_ready` |

Readiness 并行执行最小只读数据库查询与 Redis `PING`，单项失败不得跳过另一项。HTTP 只公开 `database` / `redis` 的 `up` / `down`，日志只记录依赖类别和异常类型；响应与日志禁止包含 host、port、数据库名、用户名、密码、URL、驱动异常文本或查询参数。Liveness 不得查询数据库或 Redis，避免依赖故障触发错误的进程重启循环。

---

## 8. 错误码体系

### 8.1 编码规则

| 范围 | 含义 |
|------|------|
| 0 | 成功 |
| 1xxx | 用户模块业务错误 |
| 4041x / 4092x / 4223x | 订单模块 — 资源不存在 / 状态与阶段冲突 / 聚合不可用 |
| 4093x | 库存模块 — 余额与幂等冲突 |
| 4044x / 4094x / 4224x | Wallet/Payment/Refund — 资源不存在 / 余额、结算、退款与幂等冲突 / 充值范围 |
| 4045x / 4095x / 4225x | Reservation — 预约/店休资源不存在 / 状态与时间冲突 / Product、Option、排期、手机号和店休日期不可用 |
| 40xxx | 商品模块 — 资源不存在 / 类型错误 |
| 409xx | 商品模块 — 状态冲突 |
| 422xx | 商品模块 — 业务校验 |
| 5xxx | 服务器错误 |

### 8.2 全局错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 请求参数校验失败 |
| 42901 | 认证请求超过限流阈值（HTTP 429） |
| 500 | 服务器内部错误 |
| 503 | 关键依赖暂不可用，或受控资金/支付能力尚未开放 |

### 8.3 用户模块错误码（1xxx）

| code | 说明 |
|------|------|
| 1001 | 用户名已存在 |
| 1002 | 用户不存在 |
| 1003 | 密码错误 |
| 1004 | 旧密码不正确 |
| 1005 | 用户已被禁用 |
| 1006 | Token 已过期 |
| 1007 | 手机号已被注册 |
| 1008 | 当前账号没有密码登录能力 |
| 1009 | 账号已注销 |
| 1010 | 密码注册已关闭 |
| 1011 | 外部身份无效 |
| 1012 | 外部身份绑定冲突 |
| 1013 | 外部身份未绑定 |
| 1014 | 解绑会移除唯一登录方式 |
| 1015 | 活跃订单、未来活跃预约、处理中资金、可退款钱包结算敞口或非零钱包余额阻止账号注销 |

### 8.4 商品模块错误码（40xxx / 409xx / 422xx）

**资源不存在（404xx）—— HTTP 404**

`NotFoundException` 必须支持由命名子类传入稳定业务 code，同时保持无参数时现有通用 `404` 行为向后兼容；例如 `ProductNotFound` 使用 `40401`，而不是退化为通用 code `404`。

| code | 说明 |
|------|------|
| 40401 | 商品不存在 |
| 40402 | Option 不存在 |
| 40403 | 图片不存在 |
| 40404 | 套装配置不存在 |
| 40405 | 全局拼豆颜色不存在 |
| 40406 | 商品颜色关联不存在或不再可见 |

**类型错误（400xx）—— HTTP 400**

| code | 说明 |
|------|------|
| 40001 | 商品类型与此操作不匹配 |
| 40021 | Option 图片不能设为封面 |

**状态冲突（409xx）—— HTTP 409**

状态冲突由 `ConflictException` 及其模块命名子类表达，全局异常中间件按异常类型映射 HTTP 409；禁止根据 `409xx` 错误码号段推断 HTTP 状态。Product Service 首个命名子类为 `ProductIsDeleted` 和 `ProductAlreadyOnline`。

模块异常按 HTTP 语义类型直接继承，不要求建立覆盖全部状态码的模块基类。现有 `ProductException` 继承自 `UnprocessableEntityException`，实际只能表示 HTTP 422；进入 Product Service 异常实现时将移除该伪通用基类，让 `ProductNotReadyForOnline` 直接继承 `UnprocessableEntityException`、`ProductNotFound` 直接继承 `NotFoundException`，冲突异常直接继承 `ConflictException`。这不改变任何对外错误契约。

| code | 说明 |
|------|------|
| 40901 | 商品已上架 |
| 40902 | 商品已下架 |
| 40903 | 商品已删除 |
| 40904 | online 商品需先下架才能删除 |
| 40905 | online 商品不可修改 |
| 40911 | Option 配置已存在 |
| 40912 | Option 已删除 |
| 40913 | 非空全局颜色业务编码重复 |
| 40914 | 全局颜色未配置/未激活，不能激活或启用销售 |
| 40915 | Online 商品正在使用全局颜色，禁止修改 |

**业务校验（422xx）—— HTTP 422**

| code | 说明 |
|------|------|
| 42201 | 商品未满足上架条件；message 固定为 `Product is not ready to go online`，`data.issues` 为非空字符串数组 |
| 42221 | 图片文件无效；message 固定为 `Invalid image file`，`data.reason` 提供稳定失败原因 |

> Product 写接口收到的价格、库存、时长、人数、日期类型和请求形状由 Pydantic/FastAPI 静态校验，使用全局 HTTP 422 参数校验响应。上架时对已加载聚合快照执行的价格、库存与关联完整性校验使用 `42201`；其精确 message、issues 清单与顺序见 [Product Business Rules §8.5](../01_requirements/product_business_rules.md#85-online-validation上架校验)。上传文件内容、MIME 和大小校验使用 `42221`。

### 8.5 订单模块错误码（4041x / 4092x / 4223x）

Order 与 Product 一样使用 HTTP 语义化的稳定业务 code；异常必须按语义直接继承 `NotFoundException`、`ConflictException` 或 `UnprocessableEntityException`。HTTP 状态由异常类型映射，不按 code 数字段推断。

| code | HTTP | 命名异常 | 说明 |
|------|------|----------|------|
| 40411 | 404 | `OrderNotFound` | 订单不存在；用户访问他人订单也统一使用该错误，避免资源枚举 |
| 40921 | 409 | `OrderStatusConflict` | 当前订单状态不允许指定状态变迁 |
| 42231 | 422 | `OrderProductUnavailable` | Product 不存在、已删除、未上架，或所需 Kit 扩展不可用 |
| 42232 | 422 | `OrderOptionUnavailable` | Experience Option 缺失/无效/归属错误，或 Kit 错误携带 Option |
| 42233 | 422 | `OrderKitColorUnavailable` | 商品颜色缺失、未启用、全局未激活/未配置、归属错误，或非颜色商品错误携带颜色；data 返回 product_id/kit_color_id |
| 42234 | 422 | `OrderAmountExceeded` | 服务端权威累计总额超过 `99999999.99`；data 只返回 maximum，不回显内部中间金额 |

`items` 为空/分类项数超限、重复 `(product_id, experience_option_id, kit_color_id)`、数量范围、备注长度和未知字段属于请求形状校验，使用全局参数错误 code `422`。M6 限制为颜色行最多 20、非颜色行最多 10、总行最多 30，每色数量最多 99；旧 fixed/Experience 客户端仍受原非颜色 10 行边界保护。

> **实现状态：** Order 的 `IntEnum`、API value/label Registry、Schema/应用层及 Phase 4.2 最终 Review 均已完成。Phase 4.3.7–4.3.8 已接入 Kit/混合创建扣减与 Pending 取消恢复；当前会使用 `40931` 库存不足、`40932` 恢复越界和 `40933` restore 幂等矛盾，阶段门禁 `40922` 已移除。

### 8.6 库存模块错误码（40031 / 4093x）

以下命名异常及三个 Inventory 管理路由均已实现；Wallet/Payment/Refund M4 另在 PAID Kit 全额退款中复用 `40932`/`40933`：

| code | HTTP | 命名异常 | 说明 |
|------|------|----------|------|
| 40031 | 400 | `InventoryKitKindMismatch` | message 固定为 `Kit kind does not match this inventory operation`；data 返回 `expected/actual` KitKind value |
| 40931 | 409 | `InsufficientStock` | 下单库存不足；用户数据不披露精确可用量 |
| 40932 | 409 | `InventoryBalanceExceeded` | 调整后余额超出 `0..999999`；颜色余额场景的 data 另含 `kit_color_id` |
| 40933 | 409 | `InventoryTransactionConflict` | 幂等键已绑定到不同请求 |

Inventory 资源身份继续复用 Product 的 `40401`、`40404`、`40406`、`40001`、`40903`。fixed 端点和颜色端点必须明确拒绝错误 KitKind；请求体、`Idempotency-Key`、分页和筛选形状错误使用全局 HTTP 422 / code `422`。HTTP 状态仍由异常类型映射，不按数字段判断。

### 8.7 Wallet / Payment / Refund 错误码（4044x / 4094x / 4224x）

| code | HTTP | 命名异常 | 说明 |
|------|------|----------|------|
| 40441 | 404 | `WalletNotFound` | 钱包不存在或不可见；历史 NORMAL/DISABLED USER 尚未 backfill 也使用该错误 |
| 40442 | 404 | `RechargeOrderNotFound` | 充值单不存在或不可见 |
| 40443 | 404 | `PaymentNotFound` | 支付或成功结算不存在/不可见 |
| 40444 | 404 | `RefundNotFound` | 退款不存在 |
| 40941 | 409 | `WalletBalanceExceeded` | 变化后余额超出 `0.00..1000.00` |
| 40942 | 409 | `InsufficientWalletBalance` | 钱包余额不足；响应不披露当前余额 |
| 40943 | 409 | `WalletTransactionConflict` | 幂等键绑定到不同资金意图 |
| 40944 | 409 | `PaymentStatusConflict` | Payment 状态不允许操作或重放事实不完整 |
| 40945 | 409 | `PaymentSettlementConflict` | Order/Payment 已有冲突结算 |
| 40946 | 409 | `RefundStatusConflict` | 订单/Refund 状态不允许退款或已退款 |
| 40947 | 409 | `WalletRefundCapacityExceeded` | 正向入账会侵占尚可全额退款的钱包支付预留空间 |
| 40948 | 409 | `RefundWindowExpired` | Completed 订单超过 30 天退款窗口 |
| 42241 | 422 | `RechargeAmountOutOfRange` | 单笔充值额超出 `1.00..1000.00` |

钱包余额硬上限为 `1000.00`。ADMIN 正向调账还必须满足 `调整后余额 + 尚可退款的钱包支付敞口 ≤ 1000.00`；PAID 钱包订单和完成未满 30 天的钱包订单在 Refund succeeded 前占用敞口。未来真实充值成功也必须复用该预留校验。真实微信 Provider 当前关闭，充值、微信订单支付及微信退款使用 HTTP 503 / code `503`，且必须在任何数据库写入前失败。完整端点与字段见 [Wallet API](wallet_api.md)。

### 8.8 Reservation 错误码（4045x / 4095x / 4225x）

| code | HTTP | 命名异常 | 说明 |
|------|------|----------|------|
| 40451 | 404 | `ReservationNotFound` | 预约不存在；用户访问他人预约也使用该错误 |
| 40452 | 404 | `StoreClosureNotFound` | 目标日期当前没有可恢复的自定义店休 |
| 40951 | 409 | `ReservationStatusConflict` | 当前状态不允许 confirm/reject/cancel；data 返回稳定 operation、current_status、allowed_statuses |
| 40952 | 409 | `ReservationCancellationWindowClosed` | 已晚于开始前 3 小时的顾客取消截止时间 |
| 40953 | 409 | `ReservationOperationExpired` | 预约已开始，门店不能再确认或拒绝 |
| 42251 | 422 | `ReservationProductUnavailable` | Product 已删除、非 Experience 或不处于 Online |
| 42252 | 422 | `ReservationOptionUnavailable` | ExperienceOption 不存在、已删除或归属不可用 |
| 42253 | 422 | `ReservationScheduleUnavailable` | 日期/时段不可用；data.reason 为稳定机器原因 |
| 42254 | 422 | `ReservationPhoneRequired` | 当前普通用户没有手机号，不能创建预约 |
| 42255 | 422 | `StoreClosureDateUnavailable` | 自定义店休日期是过去日期或周一 |

`42253.data.reason` 只允许 `minimum_lead_time`、`outside_booking_window`、`invalid_slot_increment`、`outside_business_hours`、`weekly_closed`、`store_closed`、`option_day_type_mismatch`。`42255.data.reason` 只允许 `past_date`、`weekly_closed`。完整契约见 [Reservation API](reservation_api.md)。请求形状错误继续使用通用 HTTP 422 / code `422`。

---

## 9. 数据类型与格式

### 9.1 时间

所有 datetime 字段使用 ISO 8601 格式，UTC 时区：

```
"2026-07-23T10:30:00Z"
```

字段命名示例：`created_at`、`updated_at`、`scheduled_start_at`、`scheduled_end_at`。

Reservation 是明确例外的“双表示”输入/输出边界：创建请求使用 `Asia/Shanghai` 当地严格日期 `YYYY-MM-DD` 与开始时间 `HH:00` / `HH:30`；服务端转换后以 UTC datetime 保存并输出，同时返回上海当地的 `reservation_date/start_time/end_time` 便于页面显示。所有提前量、周一、营业时间和第 0–30 日窗口判断使用服务端时钟与上海时区，不能使用客户端设备时区作为权威。

### 9.2 金额

所有金额以“元”为单位，后端必须使用 `Decimal` / `DecimalField(10,2)`，禁止 float。Product、Order 与资金响应使用普通十进制字符串，以避免浮点精度和尾随零歧义：

```json
"price": "199.00",
"total_amount": "497.00"
```

金额字符串不得使用指数形式，服务端不得静默四舍五入。Wallet 调账与充值等资金写请求进一步要求固定两位小数字符串，例如 `"-20.00"`；拒绝 JSON number、正负零、科学计数、NaN、Infinity 和三位以上小数。单笔充值冻结为 `1.00..1000.00`，Wallet 余额冻结为 `0.00..1000.00`；这些是领域常量，不由客户端能力提示或普通环境配置放宽。

### 9.3 布尔值

使用 JSON `true` / `false`，不使用 `0` / `1`：

```json
"is_active": true
```

### 9.4 枚举值 — {value, label} 模式

任何需要展示给用户的枚举字段，统一使用 `{value, label}` 格式：

```json
{
    "value": "weekday",
    "label": "工作日"
}
```

**Response：**

```json
{
    "status": { "value": "online", "label": "已上架" },
    "options": [
        {
            "duration": { "value": 60, "label": "1小时" },
            "participants": { "value": 2, "label": "2人" },
            "day_type": { "value": "holiday", "label": "节假日" }
        }
    ]
}
```

**Request（前端提交时只传 value）：**

```json
{ "duration": 60, "day_type": "weekday" }        // ✅
{ "duration": "1小时", "day_type": "工作日" }      // ❌
```

**请求和查询中的枚举值**只提交原始 value，不提交 label：

```json
{ "product_type": "experience" }
```

判断标准：响应中用于展示的枚举使用 `{value, label}`；请求、查询和仅供后端判断的值使用原始 value。Product 列表响应的 `product_type` 既用于前端路由也用于展示，因此仍使用 `{value, label}`。

具体映射关系见 [§14 Enum Registry](#14-enum-registry枚举注册表)。

### 9.6 NULL 处理

- 值为空时返回 `null`，不省略字段
- 列表为空时返回 `[]`，不返回 `null`

```json
// ✅ 正确
"phone": null,
"avatar": null

// ❌ 错误（省略字段）
// phone 字段直接不出现
```

---

## 10. 分页

### 10.1 请求参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | int | 1 | 页码，从 1 开始 |
| page_size | int | 20 | 每页数量，最大 100 |

### 10.2 响应格式

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [...],
        "total": 100,
        "page": 1,
        "page_size": 20
    }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| items | array | 当前页数据 |
| total | int | 总记录数 |
| page | int | 当前页码 |
| page_size | int | 每页数量 |

### 10.3 排序（可选）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| sort_by | string | created_at | 排序字段 |
| sort_order | string | desc | `asc` / `desc` |

---

## 11. 字段校验

### 11.1 通用规则

| 字段类型 | 规则 |
|----------|------|
| 必填字符串 | 非空，去除首尾空格 |
| 可选字符串 | 允许 `null` 或空字符串，统一存为 `null` |
| 手机号 | 11 位中国大陆手机号（1[3-9] 开头） |
| 密码 | 8-64 字符 |

### 11.2 校验失败响应

```json
{
    "code": 422,
    "message": "Validation failed",
    "data": {
        "<field>": "<error description>"
    }
}
```

`data` 中 key 为校验失败的字段名，value 为中文或英文错误描述。

---

## 12. 文件上传

### 12.1 请求

```
POST /api/v1/users/me/avatar
Content-Type: multipart/form-data
```

### 12.2 限制

| 限制项 | 值 |
|--------|-----|
| 最大体积 | 2MB |
| 允许格式 | jpg, png, webp |

上述约束适用于现有 Product/Option 单图上传；每个请求只接受一个文件。M6 的 221 色色板图属于全局 BeadColor，而非 ProductImage，不通过逐个 multipart 请求做首批导入。实物图推荐 192×192 或 256×256、sRGB、WebP；指定 MARD 页面只有 CSS HEX/RGB 色块，项目已通过版本化 manifest 和默认 dry-run、显式本地 apply 的离线工具生成 256×256 sRGB PNG，完成槽号、来源顺序、HEX/RGB、确定性文件名、URL、冲突和 Online 引用校验。`swatch_image_url` 可为空，缺图不阻止颜色配置或商品上架；生产对象存储/CDN 发布仍属于 Gate B，而不是该本地工具的能力。

### 12.3 响应

上传成功返回文件的访问 URL：

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "avatar": "https://cdn.example.com/avatars/1.jpg"
    }
}
```

---

## 13. 数据库映射约定

API 字段名与数据库字段名保持直接映射。枚举字段的转换规则见 [Enum Mapping](#14-enum-mapping枚举映射)。

| 数据库字段 | API 字段 | 类型转换 |
|-----------|----------|----------|
| `id` (bigint) | `id` | → int |
| `username` (varchar) | `username` | → string |
| `created_at` (datetime) | `created_at` | → ISO 8601 string |
| `updated_at` (datetime) | `updated_at` | → ISO 8601 string |
| `total_amount` (decimal) | `total_amount` | → 两位小数 string |
| `is_cover` (boolean) | `is_cover` | → boolean |
| `scheduled_start_at` (datetime) | `scheduled_start_at` | → UTC ISO 8601 string |
| `option_price` (decimal) | `price` | → Reservation 创建快照的两位小数 string |

> - 所有 ID 类型在 API 中统一为 `int` / `bigint`
> - 所有时间字段统一为 ISO 8601 字符串
> - 枚举字段通过 Enum 类在 DB `SMALLINT` 或 `VARCHAR` 与 API value 之间转换；具体表示按模块注册表执行

---

## 14. Enum Registry（枚举注册表）

项目中所有枚举字段的完整映射。新增模块时在此表追加。Duration 和 Participants 是开放正整数展示值，不属于 Enum。

**开放展示值（非 Enum）**

| 字段 | DB 存储 | 常用值 | 规则 |
|------|---------|--------|------|
| `duration_minutes` | INT | 60 → “1小时”、120 → “2小时”、540 → “全天” | 任意正整数；API Mapper 根据分钟数生成 label |
| `participants` | INT | 1 → “1人”、2 → “2人” | 任意正整数；API Mapper 根据人数生成 label |

**固定 Enum**

| 枚举类型 | DB 存储 | value | label |
|----------|---------|-------|-------|
| `DayType` | VARCHAR | `"weekday"` | "工作日" |
| | | `"holiday"` | "节假日" |
| `ProductStatus` | VARCHAR | `"draft"` | "草稿" |
| | | `"online"` | "已上架" |
| | | `"offline"` | "已下架" |
| `ProductType` | VARCHAR | `"experience"` | "拼豆体验" |
| | | `"kit"` | "拼豆套装" |
| `KitKind` | VARCHAR | `"fixed"` | "固定套装" |
| | | `"color_selectable"` | "自选颜色" |
| `UserRole` | SMALLINT | 1 → `"user"` | "普通用户" |
| | | 2 → `"admin"` | "管理员" |
| | | 3 → `"super_admin"` | "超级管理员" |
| `UserStatus` | SMALLINT | 1 → `"normal"` | "正常" |
| | | 2 → `"disabled"` | "已禁用" |
| | | 3 → `"deleted"` | "已注销" |
| `OrderStatus` | SMALLINT | 0 → `"pending"` | "待支付" |
| | | 1 → `"paid"` | "已支付" |
| | | 2 → `"cancelled"` | "已取消" |
| | | 3 → `"completed"` | "已完成" |
| `WalletStatus` | VARCHAR | `"active"` | 活跃钱包 |
| | | `"closed"` | 已注销关闭 |
| `WalletTransactionType` | VARCHAR | `"recharge"` / `"order_payment"` / `"admin_adjustment"` / `"refund"` | 充值 / 订单消费 / 管理调账 / 退款 |
| `WalletTransactionSourceType` | VARCHAR | `"recharge_order"` / `"order"` / `"admin"` / `"refund"` | 流水业务来源 |
| `PaymentPurpose` | VARCHAR | `"order"` / `"recharge"` | 订单支付 / 钱包充值 |
| `PaymentMethod` | VARCHAR | `"wallet"` / `"wechat"` / `"manual"` | 钱包 / 微信 / 人工线下 |
| `PaymentStatus` | VARCHAR | `"pending"` / `"succeeded"` / `"failed"` / `"closed"` | 支付状态 |
| `RechargeOrderStatus` | VARCHAR | `"pending"` / `"paid"` / `"failed"` / `"closed"` | 充值单状态 |
| `RefundStatus` | VARCHAR | `"pending"` / `"succeeded"` / `"failed"` | 退款状态 |
| `ReservationStatus` | VARCHAR | `"pending"` / `"confirmed"` / `"rejected"` / `"cancelled"` | 待门店确认 / 已确认 / 未能确认 / 已取消 |
| `ReservationRejectionReason` | VARCHAR | `"no_capacity"` | 当前时段无空位 |
| `ReservationCancellationReason` | VARCHAR | `"customer_request"` / `"store_closed"` | 顾客取消 / 门店店休 |
| `ReservationScheduleUnavailableReason` | API-only | `"minimum_lead_time"` / `"outside_booking_window"` / `"invalid_slot_increment"` / `"outside_business_hours"` / `"weekly_closed"` / `"store_closed"` / `"option_day_type_mismatch"` | 排期不可用机器原因，不持久化 |
| `StoreClosureDateUnavailableReason` | API-only | `"past_date"` / `"weekly_closed"` | 自定义店休日期不可操作机器原因，不持久化 |

> Order/DayType/KitKind/Reservation 状态与持久化原因等面向页面展示的字段通过 Mapper 输出 `{value, label}`；请求中的 `kit_kind` 使用原始字符串 value，省略时默认 `fixed`。Reservation 的 `42253/42255 data.reason` 是机器原因原始 value。Wallet/Payment/Refund 的机器状态当前直接输出稳定字符串 Enum。退款状态独立于 OrderStatus，成功退款不会把 Order 改成 Cancelled。

### 使用示例

```python
def duration_to_dto(value: int) -> dict:
    hours, minutes = divmod(value, 60)
    if minutes == 0:
        label = f"{hours}小时"
    else:
        label = f"{value}分钟"
    return {"value": value, "label": label}
```

### 新增枚举检查清单

添加新的枚举字段时：

- [ ] 在本文档 §14 注册表中新增一行
- [ ] 数据库使用项目 ORM 映射的 `SMALLINT`（数值型）或 `VARCHAR`（字符串型），在 ER 图 note 中标注
- [ ] Python 定义对应的 `Enum` 类（`app/common/enums/`）
- [ ] API Mapper 实现 `{value, label}` 转换
- [ ] 更新 `er_diagram.dbml` 和 `database_design.md`

---

## 15. 文档编写规范

### 14.1 每篇 API 文档必须包含

1. **概述**：模块职责、Base URL、认证方式
2. **数据对象定义**：该模块核心对象的字段说明
3. **错误码**：该模块特有的业务错误码
4. **端点列表**：概览表格（Method / URI / 描述 / 认证 / 角色）
5. **接口详情**：每个接口的请求参数、请求示例、成功响应、失败响应
6. **附录**（可选）：分页、排序等通用参数说明

### 14.2 接口详情模板

```markdown
### x.x 接口名称

`METHOD /api/v1/path`

功能描述。

**Header**

（如有认证要求）

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|

**请求示例**

```json
{}
```

**成功响应**

```json
{}
```

**失败响应**

错误场景描述：

```json
{}
```
```

### 14.3 JSON 示例格式

- 缩进使用 4 个空格
- key 不加引号内的空格：`"key": value`
- 适当添加注释说明字段含义

---

## 16. 版本策略

### 15.1 URL 前缀版本

```
/api/v1/...
/api/v2/...
```

### 15.2 兼容性承诺

| 版本阶段 | 兼容策略 |
|----------|----------|
| v0.x | 不保证兼容，可随时调整 |
| v1.0+ | 向后兼容，新增字段不影响旧客户端 |

### 15.3 废弃流程

1. 新版接口上线
2. 文档标注旧接口为 `@deprecated`
3. 保留至少一个大版本的过渡期
4. 过渡期后移除旧接口

---

## 17. 安全规范

| 规范 | 说明 |
|------|------|
| 密码不入响应 | 任何接口不得返回 `password` 字段 |
| 敏感接口限流 | 登录、注册接口需限流（如 5次/分钟/IP） |
| 输入校验 | 所有用户输入在后端进行二次校验 |
| SQL 注入防护 | 使用 ORM 参数化查询，禁止拼接 SQL |
| CORS | 仅允许白名单域名跨域访问 |

---

## 18. 快速检查清单

新接口上线前逐项确认：

- [ ] URI 全小写、资源名复数、kebab-case
- [ ] HTTP Method 语义正确
- [ ] 路径参数使用 `{id}` 占位符
- [ ] 响应使用统一信封 `{code, message, data}`
- [ ] 正确返回 HTTP 状态码
- [ ] 错误码在模块范围内不冲突
- [ ] 时间格式为 ISO 8601 UTC
- [ ] 金额以元为单位
- [ ] `password` 不出现在响应中
- [ ] 空值字段返回 `null`，不省略
- [ ] 请求参数有校验规则说明
- [ ] 至少提供成功 + 一种失败响应示例
- [ ] 需要认证的接口标注 Header
- [ ] 分页接口统一使用 `page` / `page_size`
- [ ] 枚举字段的 DB 表示与 Enum Registry 一致（Product 字符串 Enum 使用 VARCHAR；User / Order 数值 Enum 使用 SMALLINT）
