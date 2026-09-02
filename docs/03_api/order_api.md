# Order API

> **Document Version:** v1.2
>
> **Status:** Kit/Mixed Inventory Lifecycle Implemented（Phase 4.2 complete + Phase 4.3.8 complete）
>
> **Last Updated:** 2026-08-14
>
> 本文遵循 [API Design Conventions](api_design_conventions.md)，业务规则以 [Order Module](../01_requirements/order_module.md) 为准。

---

## 1. 概述与范围

Order API 提供 Experience、Kit 与混合订单创建，以及用户/管理员查询、取消、人工确认支付、完成和审计历史。Phase 4.3.7–4.3.8 已接入创建 Pending 时的 Kit 库存扣减及 owner cancel 时的幂等恢复；支付与完成不改变库存。

Base URL：`/api/v1`。除特别说明外，全部端点要求 JWT Bearer Token。

角色：

- 已认证用户：创建订单、访问和取消自己的订单；
- ADMIN+：`admin` 与 `super_admin`，访问管理端端点。

所有成功与错误响应都使用统一信封。创建返回 HTTP 201，其余成功返回 HTTP 200。业务异常由全局中间件转换，路由不得捕获后手写错误信封。

---

## 2. 数据契约

### 2.1 通用表示

- ID：JSON integer。
- 时间：UTC ISO 8601，例如 `"2026-08-13T10:30:00Z"`。
- 金额：固定两位小数的 JSON string，例如 `"99.00"`；后端计算使用 `Decimal`。
- 状态：展示对象 `{ "value": "pending", "label": "待支付" }`。
- 未填写备注时返回 `null`，不返回空字符串替代。
- Request Schema 均使用 `extra="forbid"`；Out Schema 使用字段白名单和 `from_attributes=True`。

### 2.2 Order Item 请求

| 字段 | 类型 | 必填 | 规则 |
|------|------|------|------|
| `product_id` | integer | 是 | 正整数；必须引用当前可售 Experience 或 Kit Product |
| `experience_option_id` | integer / null | 条件必填 | Experience 必须为当前有效 Option；Kit 必须省略或为 null |
| `quantity` | integer | 是 | 1 至 99 |

客户端不得提交名称、配置、价格、小计或库存字段。同一订单中 `(product_id, experience_option_id)` 不得重复；不自动合并重复行。

### 2.3 Order Item 响应

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | OrderItem ID |
| `product_id` | integer | 原 Product ID |
| `experience_option_id` | integer / null | Experience 的原 Option ID；Kit 为 null |
| `product_name` | string | Product 名称快照 |
| `option_duration_minutes` | integer / null | Experience 时长快照；Kit 为 null |
| `option_participants` | integer / null | Experience 人数快照；Kit 为 null |
| `option_day_type` | object / null | Experience 日期类型 `{value, label}`；Kit 为 null |
| `product_price` | string | 单价快照，两位小数 |
| `quantity` | integer | 数量 |
| `subtotal` | string | 小计，两位小数 |

`experience_option_id` 与三项 Option 快照必须同时完整或同时为 null：前者表示 Experience，后者表示 Kit；不接受部分 Option 快照。

### 2.4 用户端与管理端对象

用户端列表项：

| 字段 | 类型 |
|------|------|
| `id` | integer |
| `order_no` | string |
| `total_amount` | string |
| `status` | object |
| `item_count` | integer，OrderItem 明细行数（不是 quantity 求和） |
| `created_at` | datetime |
| `updated_at` | datetime |

用户端详情与列表项共享 `id`、`order_no`、`total_amount`、`status` 和时间字段，并额外返回 `remark` 与 `items`；列表派生字段 `item_count` 不进入详情。详情不返回 `user_id` 或任何用户资料。

管理端列表项额外返回：

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | integer | 下单用户 ID |
| `user_nickname` | string | 当前安全展示昵称，不属于订单快照 |

管理端详情与用户端详情相比只增加 `user_id` 和 `user_nickname`；它返回 `remark` 与 `items`，不返回列表派生字段 `item_count`。管理端也不得返回用户名、手机号、密码、Token 等字段。

### 2.5 状态变迁响应

取消、确认支付和完成均返回：

| 字段 | 类型 |
|------|------|
| `id` | integer |
| `order_no` | string |
| `status` | object |
| `updated_at` | datetime |

### 2.6 Schema 注册表

后续 Schema 阶段按以下名称和职责实现，不使用一个宽松 `OrderOut` 同时服务所有端点：

| Schema | 方向 | 用途 |
|--------|------|------|
| `OrderItemCreate` | Request | 单个 Experience 或 Kit Item |
| `OrderCreate` | Request | `items` + `remark`，负责非空、上限和重复组合校验 |
| `OrderListQuery` | Query | 用户端分页与状态筛选 |
| `AdminOrderListQuery` | Query | 管理端分页、状态、订单号、用户和时间范围筛选 |
| `OrderItemOut` | Response | 明细快照白名单 |
| `OrderListItemOut` | Response | 用户端列表项 |
| `AdminOrderListItemOut` | Response | 管理端列表项 |
| `OrderDetailOut` | Response | 用户端创建/详情 |
| `AdminOrderDetailOut` | Response | 管理端详情 |
| `OrderStatusOut` | Response | 三个状态变迁端点 |

运行时由 Mapper 生成并校验上述 Out Schema，再通过 `success()` 包装；OpenAPI 使用 `SuccessResponse[OrderDetailOut]`、`SuccessResponse[Page[OrderListItemOut]]` 等精确泛型和共享 `ErrorResponse` 声明。Mapper 完成序列化后路由保持 `response_model=None`，避免金额字符串被二次按 Decimal 输入规则校验。

---

## 3. 错误契约

HTTP 状态由异常类型决定，不能根据 code 的数字范围猜测。Order 命名异常按实际 HTTP 语义直接继承共享异常类型。

| 命名异常 | code | HTTP | message | data |
|----------|------|------|---------|------|
| `OrderNotFound` | `40411` | 404 | `Order not found` | `null` |
| `OrderStatusConflict` | `40921` | 409 | `Order status does not allow this operation` | `operation`, `current_status`, `required_status` |
| `OrderProductUnavailable` | `42231` | 422 | `Order product is unavailable` | `product_id` |
| `OrderOptionUnavailable` | `42232` | 422 | `Order experience option is unavailable` | `product_id`, `experience_option_id`（Experience 缺失时为 null） |
| `InsufficientStock` | `40931` | 409 | `Insufficient stock` | `product_id`, `requested_quantity`；不返回 available |
| `InventoryBalanceExceeded` | `40932` | 409 | `Inventory balance exceeds the allowed range` | 取消恢复越界时包含 Product、before/change 与上下限 |
| `InventoryTransactionConflict` | `40933` | 409 | `Inventory idempotency key conflicts with another request` | `null` |

请求形状错误使用全局 HTTP 422 / code `422` 参数校验信封，包括：`items` 为空或超过 10 项、ID 非正整数、数量不在 1 至 99、重复 `(product_id, experience_option_id)`、备注超过 500 字符、未知字段、分页/时间格式错误。`OrderItemsRequired` 属于 Schema 约束，不额外发明业务错误码。

用户查询或取消他人订单与订单确实不存在都返回 `40411`，不会对外提供 `OrderDoesNotBelongToUser`，避免资源枚举。管理员端才可按真实 ID 查询任意订单。

`OrderStatusConflict.data.operation` 对三条状态用例分别固定为 `cancel`、`mark_paid`、`complete`；它是稳定的业务操作标识，不等同于大写审计 action。

> **实现状态：** Phase 4.2 Order v1.0 全链及最终 Review 保持完成；Phase 4.3.7–4.3.8 已把既有创建/取消端点升级为完整 Kit 库存生命周期。创建和取消分别写 deduction/restore 流水，均使用稳定集合锁、同事务余额/Order/Audit/重载及 MySQL 1205/1213 有限重试；取消额外使用 Order 状态机和 restore UNIQUE 双层幂等保护。`40922` 阶段门禁已移除，Phase 4.3.11 真实 MySQL 最后一件、反向多 Kit、同单取消和管理调整竞争均已通过。

错误示例：

```json
{
    "code": 40921,
    "message": "Order status does not allow this operation",
    "data": {
        "operation": "complete",
        "current_status": "pending",
        "required_status": "paid"
    }
}
```

---

## 4. 端点列表

| Method | URI | 描述 | 认证 | 角色 |
|--------|-----|------|------|------|
| POST | `/orders` | 创建 Experience、Kit 或混合订单并扣减 Kit | 是 | 已认证用户 |
| GET | `/orders` | 我的订单 | 是 | 已认证用户 |
| GET | `/orders/{order_id}` | 我的订单详情 | 是 | 订单所属用户 |
| PATCH | `/orders/{order_id}/cancel` | 取消 Pending 订单 | 是 | 订单所属用户 |
| GET | `/admin/orders` | 管理订单列表 | 是 | ADMIN+ |
| GET | `/admin/orders/{order_id}` | 管理订单详情 | 是 | ADMIN+ |
| PATCH | `/admin/orders/{order_id}/paid` | 人工确认已支付 | 是 | ADMIN+ |
| PATCH | `/admin/orders/{order_id}/complete` | 完成 Paid 订单 | 是 | ADMIN+ |
| GET | `/admin/orders/{order_id}/audit-logs` | 订单审计历史 | 是 | ADMIN+ |

状态变迁使用 `PATCH`，因为它修改资源局部状态，不是用完整表示替换订单。三个 PATCH 端点都不定义请求体，客户端必须省略 body；服务端会主动拒绝 `{}`、`null` 或其他任意非空 body，并返回统一 HTTP 422 校验错误，且不会执行状态修改或写审计。

---

## 5. 用户端接口

### 5.1 创建订单

`POST /api/v1/orders`

创建 Experience、Kit 或混合订单。系统批量加载 Product/Option/Kit 并读取数据库价格；事务内先创建 Pending Order，再稳定锁定、重检并扣减所有 Kit。余额、`order_deduction` 流水、Items、`CREATE_ORDER` 审计和响应重载共享一个事务。

请求字段：

| 字段 | 类型 | 必填 | 规则 |
|------|------|------|------|
| `items` | array | 是 | 1 至 10 项，组合不可重复 |
| `remark` | string / null | 否 | 最大 500 字符；缺省为 null |

请求示例：

```json
{
    "items": [
        {
            "product_id": 1,
            "experience_option_id": 10,
            "quantity": 1
        },
        {
            "product_id": 5,
            "quantity": 2
        }
    ],
    "remark": "周五晚上到店"
}
```

成功：HTTP 201

```json
{
    "code": 0,
    "message": "Order created",
    "data": {
        "id": 101,
        "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "total_amount": "497.00",
        "status": { "value": "pending", "label": "待支付" },
        "remark": "周五晚上到店",
        "items": [
            {
                "id": 1001,
                "product_id": 1,
                "experience_option_id": 10,
                "product_name": "拼豆体验",
                "option_duration_minutes": 60,
                "option_participants": 1,
                "option_day_type": { "value": "weekday", "label": "工作日" },
                "product_price": "99.00",
                "quantity": 1,
                "subtotal": "99.00"
            },
            {
                "id": 1002,
                "product_id": 5,
                "experience_option_id": null,
                "product_name": "拼豆材料包",
                "option_duration_minutes": null,
                "option_participants": null,
                "option_day_type": null,
                "product_price": "199.00",
                "quantity": 2,
                "subtotal": "398.00"
            }
        ],
        "created_at": "2026-08-13T10:30:00Z",
        "updated_at": "2026-08-13T10:30:00Z"
    }
}
```

创建响应不返回 `user_id`。可能的业务错误：`40931`、`42231`、`42232`；请求形状错误返回全局参数 422。

### 5.2 我的订单

`GET /api/v1/orders`

查询参数：

| 字段 | 类型 | 必填 | 默认值 | 规则 |
|------|------|------|--------|------|
| `page` | integer | 否 | 1 | ≥ 1 |
| `page_size` | integer | 否 | 20 | 1 至 100 |
| `status` | string | 否 | - | `pending` / `paid` / `cancelled` / `completed` |

稳定排序：`created_at DESC, id DESC`。

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 101,
                "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
                "total_amount": "497.00",
                "status": { "value": "pending", "label": "待支付" },
                "item_count": 2,
                "created_at": "2026-08-13T10:30:00Z",
                "updated_at": "2026-08-13T10:30:00Z"
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "pages": 1
    }
}
```

### 5.3 我的订单详情

`GET /api/v1/orders/{order_id}`

返回与创建成功相同的用户端详情结构。不存在或属于其他用户均返回 `40411`；检查必须通过限定 `current_user_id` 的可见查询完成，不先加载他人订单再暴露归属错误。

### 5.4 取消订单

`PATCH /api/v1/orders/{order_id}/cancel`

仅允许订单所属用户执行 `pending → cancelled`。事务先锁定 owner 可见 Order 并重检 Pending，再读取最小 Item 快照、按 Product ID 升序锁定全部 Kit、批量确认 restore 幂等身份尚未提交，随后恢复余额并写 `order_cancellation_restore` 流水，最后更新状态、写 `CANCEL_ORDER` 审计并重载响应。纯 Experience 订单跳过 Inventory；重复取消返回 `40921` 且不重复恢复。任何库存、流水、状态、审计或重载失败都会让整个事务回滚。

```json
{
    "code": 0,
    "message": "Order cancelled",
    "data": {
        "id": 101,
        "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "status": { "value": "cancelled", "label": "已取消" },
        "updated_at": "2026-08-13T11:00:00Z"
    }
}
```

可能的业务错误：`40411`、`40921`。

---

## 6. 管理端接口

### 6.1 管理订单列表

`GET /api/v1/admin/orders`

查询参数：

| 字段 | 类型 | 必填 | 默认值 | 规则 |
|------|------|------|--------|------|
| `page` | integer | 否 | 1 | ≥ 1 |
| `page_size` | integer | 否 | 20 | 1 至 100 |
| `status` | string | 否 | - | OrderStatus value |
| `order_no` | string | 否 | - | 完整订单号精确匹配 |
| `product_name` | string | 否 | - | trim 后 1 至 100 字符；按下单时商品名称快照包含匹配 |
| `user_id` | integer | 否 | - | 正整数 |
| `created_from` | datetime | 否 | - | UTC ISO 8601，包含下界 |
| `created_to` | datetime | 否 | - | UTC ISO 8601，不包含上界，必须大于 `created_from` |

无筛选及所有筛选组合均使用 `created_at DESC, id DESC` 稳定排序。列表必须数据库分页。`product_name` 查询基于 `order_items.product_name` 历史快照，不读取当前 Product 名称；一张订单即使有多条 Item 命中也只计入一次，且不改变该订单完整的 `item_count`。

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 101,
                "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
                "user_id": 7,
                "user_nickname": "Alice",
                "total_amount": "497.00",
                "status": { "value": "paid", "label": "已支付" },
                "item_count": 2,
                "created_at": "2026-08-13T10:30:00Z",
                "updated_at": "2026-08-13T11:20:00Z"
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "pages": 1
    }
}
```

### 6.2 管理订单详情

`GET /api/v1/admin/orders/{order_id}`

返回管理端详情，包含 `user_id`、`user_nickname`、`remark` 和完整 `items`。Order 不存在返回 `40411`。

### 6.3 人工确认支付

`PATCH /api/v1/admin/orders/{order_id}/paid`

仅允许 `pending → paid`，写入 `MARK_ORDER_PAID`。这是支付模块接入前的临时运营入口；未来支付回调必须复用同一 Service 用例和幂等/状态规则，不得直接更新 Repository。

```json
{
    "code": 0,
    "message": "Order marked as paid",
    "data": {
        "id": 101,
        "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "status": { "value": "paid", "label": "已支付" },
        "updated_at": "2026-08-13T11:20:00Z"
    }
}
```

可能的业务错误：`40411`、`40921`。

### 6.4 完成订单

`PATCH /api/v1/admin/orders/{order_id}/complete`

仅允许 `paid → completed`，状态与 `COMPLETE_ORDER` 审计同事务。

```json
{
    "code": 0,
    "message": "Order completed",
    "data": {
        "id": 101,
        "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "status": { "value": "completed", "label": "已完成" },
        "updated_at": "2026-08-13T15:00:00Z"
    }
}
```

可能的业务错误：`40411`、`40921`。

### 6.5 订单审计历史

`GET /api/v1/admin/orders/{order_id}/audit-logs`

查询参数仅为通用 `page` / `page_size`。先确认 Order 存在，再委托共享 `AuditLogService.list_logs(target_type="order", target_id=order_id, ...)`。响应使用共享 `AuditLogOut` / `Page[AuditLogOut]`，按 `created_at DESC, id DESC` 排序，不在 Order Schema 中复制审计结构。

可能的业务错误：`40411`。

---

## 7. 状态、审计与事务矩阵

| 用例 | 前置状态 | 后置状态 | Audit action | 原子范围 |
|------|----------|----------|--------------|----------|
| 创建 | - | `pending` | `CREATE_ORDER` | Order + Items + Audit + 响应重载；编号冲突整事务最多尝试 3 次 |
| 用户取消 | `pending` | `cancelled` | `CANCEL_ORDER` | 锁定 Order + Item 快照 + 稳定 Kit 锁 + restore 幂等检查 + 批量余额/流水 + 状态 + Audit + 响应重载；1205/1213 完整用例最多尝试 3 次 |
| ADMIN+ 确认支付 | `pending` | `paid` | `MARK_ORDER_PAID` | 锁定 Order + 状态更新 + Audit + 响应重载 |
| ADMIN+ 完成 | `paid` | `completed` | `COMPLETE_ORDER` | 锁定 Order + 状态更新 + Audit + 响应重载 |

所有事务内 Repository 方法必须接收并使用 `using_db`。状态变迁在事务内使用 `SELECT ... FOR UPDATE` 锁定订单并重新校验状态，并发请求只有一个可以成功。取消恢复与状态/Audit 使用同一连接，任一失败整体回滚；支付和完成仍不修改 ProductKit.stock。失败的前置检查不写审计。

---

## 8. 订单号与排序

订单号为 `OD` + 26 位大写 Crockford Base32 ULID，总长 28，并匹配 `^OD[0-9A-HJKMNP-TV-Z]{26}$`，例如：

```text
OD01K2M7Y0J7A3N5Q8T4V6W9X2BC
```

生成器使用 UTC 毫秒时间和密码学安全随机源，适用于多实例，无需 Redis，也不为此新增第三方依赖。`UNIQUE(order_no)` 为最终并发兜底；唯一冲突使当前事务回滚，由创建用例重新生成编号，最多尝试 3 次，第三次仍冲突则进入服务器错误兜底。API 不暴露或接受编号组成字段。

订单号只提供近似时间可排序性。所有列表的权威排序均为 `created_at DESC, id DESC`。

---

## 9. 后续能力

下列能力不属于本契约：在线支付、超时自动取消、退款、已支付取消、统计报表、订单删除。接入这些能力时必须先更新 Order 需求、API、数据库设计、ER DBML 和相关架构说明，再开始实现。

### 9.1 Phase 4.3.1 已冻结的 Order API 演进

Phase 4.3.7 已在原 `POST /api/v1/orders` 实现 Experience/Kit/混合创建和 Pending 扣减；Phase 4.3.8 已在原 cancel 端点实现 Kit/混合订单幂等恢复。Kit Item 可省略 `experience_option_id` 或显式提交 `null`；支付与完成不触碰库存。

库存不足使用 `40931 InsufficientStock`，普通用户只收到 `product_id` 和 `requested_quantity`。仅用于阶段门禁的 `40922 KitOrderingRequiresInventory` 已从代码和当前错误注册表移除。具体事务、幂等和并发规则见 [Inventory Module](../01_requirements/inventory_module.md) 与 [Inventory API](inventory_api.md)。
