# Order API

> 本文档遵循 [API Design Conventions](api_design_conventions.md) 中定义的通用规范（响应格式、错误码、分页、数据类型等），重复内容不再赘述。

---

## 1. 概述

订单模块负责管理用户购买商品后的整个交易流程，包括订单创建、订单查询、状态管理和订单完成。该模块面向两类用户：

- 普通用户：创建订单、查看自己的订单、取消待支付订单
- 管理员：查看所有订单、手动完成订单

### Base URL

```
/api/v1
```

### 认证方式

JWT Bearer Token

需要认证的接口在 Header 中携带：

```
Authorization: Bearer <access_token>
```

### 通用响应格式

所有接口统一返回：

```json
{
    "code": 0,
    "message": "success",
    "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| code | int | 业务状态码，`0` 表示成功 |
| message | string | 状态描述 |
| data | object / null | 返回数据，无数据时为 `null` |

### 订单对象

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 订单 ID |
| order_no | string | 订单编号，系统自动生成 |
| user_id | bigint | 下单用户 ID |
| total_amount | number | 订单总金额，单位：元 |
| status | string | 状态：`"pending"` 待支付 / `"paid"` 已支付 / `"cancelled"` 已取消 / `"completed"` 已完成 |
| remark | string | 订单备注 |
| items | array | 订单明细（[订单明细对象](#订单明细对象)） |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最近更新时间 |

### 订单明细对象

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 明细 ID |
| product_id | bigint | 关联商品 ID |
| product_name | string | 下单时商品名称快照 |
| product_price | number | 下单时商品价格快照，单位：元 |
| quantity | int | 数量 |
| subtotal | number | 小计金额，单位：元 |

> **快照设计**：`product_name` 和 `product_price` 在下单时从商品表复制，保证历史订单不受商品后续修改影响。

---

## 2. 错误码

### 全局错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 401 | 未认证（Token 缺失或无效） |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 请求参数校验失败 |
| 500 | 服务器内部错误 |

### 订单模块错误码（3xxx）

| code | 说明 |
|------|------|
| 3001 | 订单不存在 |
| 3002 | 订单状态不允许此操作 |
| 3003 | 商品不存在或已下架 |
| 3004 | 库存不足 |
| 3005 | 订单不属于当前用户 |
| 3006 | 订单明细不能为空 |

---

## 3. 字段校验规则

| 字段 | 规则 |
|------|------|
| items | 必填，非空数组 |
| items[].product_id | 必填，商品必须存在且 `status = "online"` |
| items[].quantity | 必填，> 0，套装商品不超过当前库存 |
| remark | 可选，最大 500 字符 |

---

## 4. 端点列表

| Method | URI | 描述 | 认证 | 角色 |
|--------|-----|------|------|------|
| POST | /orders | 创建订单 | ✅ | 普通用户 |
| GET | /orders | 我的订单 | ✅ | 普通用户 |
| GET | /orders/{id} | 订单详情 | ✅ | 普通用户 |
| PUT | /orders/{id}/cancel | 取消订单 | ✅ | 普通用户 |
| GET | /admin/orders | 全部订单 | ✅ | 管理员 |
| GET | /admin/orders/{id} | 订单详情 | ✅ | 管理员 |
| PUT | /admin/orders/{id}/complete | 完成订单 | ✅ | 管理员 |

---

## 业务规则

### 状态流转

```
                    ┌──────────────────┐
                    │  pending (待支付)  │
                    └────────┬─────────┘
                             │
                  ┌──────────┼──────────┐
                  │          │          │
                  ▼          ▼          │
           paid (已支付)  cancelled     │
                  │       (已取消)      │
                  ▼                    │
           completed                   │
           (已完成)                    │
                                       │
              不允许 paid → cancelled   │
```

| 流转 | 触发方 | 条件 |
|------|--------|------|
| 待支付 → 已支付 | 系统 | 付款成功（支付模块 v0.2） |
| 待支付 → 已取消 | 用户 | 主动取消，恢复库存 |
| 已支付 → 已完成 | 管理员 | 服务完成确认 |
| 已支付 → 已取消 | - | ❌ 当前版本不支持，需退款流程 |

### 约束规则

| 规则 | 说明 |
|------|------|
| 订单编号自动生成 | `order_no` 由系统生成，不可由用户指定 |
| 金额自动计算 | `total_amount` = 所有 `subtotal` 之和，不接受用户传入 |
| 快照不可变 | 下单后 `product_name` 和 `product_price` 为历史快照，不随商品修改而变动 |
| 库存扣减 | 创建订单时扣减套装库存（仅 `product_type = "kit"`）；体验商品不扣减 |
| 库存恢复 | 取消"待支付"订单时恢复已扣减的套装库存 |
| 仅可取消待支付 | `status != "pending"` 的订单调用取消接口返回 3002 |
| 仅可操作自己的订单 | 普通用户操作他人订单返回 3005 |
| 删除订单 | ❌ 当前版本不支持，计划在 v1.0 实现 |

---

## 5. 用户接口

### 5.1 创建订单

```
POST /api/v1/orders
```

创建新订单，系统自动计算金额、生成订单编号、扣减库存。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| items | array | 是 | 订单明细列表 |
| items[].product_id | int | 是 | 商品 ID |
| items[].quantity | int | 是 | 数量，> 0 |
| remark | string | 否 | 订单备注 |

**请求示例**

```json
{
    "items": [
        { "product_id": 1, "quantity": 1 },
        { "product_id": 2, "quantity": 2 }
    ],
    "remark": "工作日晚上来"
}
```

**成功响应**

HTTP 201

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "order_no": "20260723000001",
        "user_id": 1,
        "total_amount": 497.00,
        "status": "pending",
        "remark": "工作日晚上来",
        "items": [
            {
                "id": 1,
                "product_id": 1,
                "product_name": "工作日单人 1 小时体验",
                "product_price": 99.00,
                "quantity": 1,
                "subtotal": 99.00
            },
            {
                "id": 2,
                "product_id": 2,
                "product_name": "新手体验套装",
                "product_price": 199.00,
                "quantity": 2,
                "subtotal": 398.00
            }
        ],
        "created_at": "2026-07-23T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

**失败响应**

商品不存在或已下架：

```json
{
    "code": 3003,
    "message": "Product not found or offline",
    "data": {
        "product_id": 2
    }
}
```

库存不足：

```json
{
    "code": 3004,
    "message": "Insufficient stock",
    "data": {
        "product_id": 2,
        "available": 1,
        "requested": 2
    }
}
```

明细为空：

```json
{
    "code": 3006,
    "message": "Order items cannot be empty"
}
```

---

### 5.2 我的订单

```
GET /api/v1/orders
```

分页查看当前用户的订单列表。

**Header**

```
Authorization: Bearer <access_token>
```

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| status | string | 否 | - | 按状态筛选：`"pending"` 待支付 / `"paid"` 已支付 / `"cancelled"` 已取消 / `"completed"` 已完成 |

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 1,
                "order_no": "20260723000001",
                "total_amount": 497.00,
                "status": "pending",
                "item_count": 2,
                "created_at": "2026-07-23T10:30:00Z",
                "updated_at": "2026-07-23T10:30:00Z"
            }
        ],
        "total": 15,
        "page": 1,
        "page_size": 20
    }
}
```

> 列表中不返回 `items` 明细和 `remark`，减少数据传输量。`item_count` 为明细条数。

---

### 5.3 订单详情

```
GET /api/v1/orders/{id}
```

获取指定订单的完整信息。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "order_no": "20260723000001",
        "user_id": 1,
        "total_amount": 497.00,
        "status": "pending",
        "remark": "工作日晚上来",
        "items": [
            {
                "id": 1,
                "product_id": 1,
                "product_name": "工作日单人 1 小时体验",
                "product_price": 99.00,
                "quantity": 1,
                "subtotal": 99.00
            },
            {
                "id": 2,
                "product_id": 2,
                "product_name": "新手体验套装",
                "product_price": 199.00,
                "quantity": 2,
                "subtotal": 398.00
            }
        ],
        "created_at": "2026-07-23T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

**失败响应**

订单不存在：

```json
{
    "code": 3001,
    "message": "Order not found"
}
```

订单不属于当前用户：

```json
{
    "code": 3005,
    "message": "Order does not belong to current user"
}
```

---

### 5.4 取消订单

```
PUT /api/v1/orders/{id}/cancel
```

取消"待支付"状态的订单，同时恢复已扣减的套装库存。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "Order cancelled",
    "data": {
        "id": 1,
        "order_no": "20260723000001",
        "status": "cancelled",
        "updated_at": "2026-07-23T11:00:00Z"
    }
}
```

**失败响应**

订单状态不允许取消：

```json
{
    "code": 3002,
    "message": "Only pending orders can be cancelled"
}
```

---

## 6. 管理接口

> 以下接口需要管理员角色（`role = "admin"`），普通用户调用返回 403。

### 6.1 全部订单

```
GET /api/v1/admin/orders
```

分页查看所有用户的订单。

**Header**

```
Authorization: Bearer <access_token>
```

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| status | string | 否 | - | 按状态筛选：`"pending"` / `"paid"` / `"cancelled"` / `"completed"` |
| order_no | string | 否 | - | 按订单编号精确查找 |
| user_id | int | 否 | - | 按用户筛选 |

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 1,
                "order_no": "20260723000001",
                "user_id": 1,
                "user_nickname": "Alice",
                "total_amount": 497.00,
                "status": "pending",
                "item_count": 2,
                "created_at": "2026-07-23T10:30:00Z",
                "updated_at": "2026-07-23T10:30:00Z"
            }
        ],
        "total": 200,
        "page": 1,
        "page_size": 20
    }
}
```

> 管理端列表额外返回 `user_id` 和 `user_nickname`，便于管理员识别下单用户。

---

### 6.2 订单详情

```
GET /api/v1/admin/orders/{id}
```

查看任意订单的完整信息，与用户端详情格式相同，但不校验订单归属。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "order_no": "20260723000001",
        "user_id": 1,
        "user_nickname": "Alice",
        "total_amount": 497.00,
        "status": "pending",
        "remark": "工作日晚上来",
        "items": [
            {
                "id": 1,
                "product_id": 1,
                "product_name": "工作日单人 1 小时体验",
                "product_price": 99.00,
                "quantity": 1,
                "subtotal": 99.00
            },
            {
                "id": 2,
                "product_id": 2,
                "product_name": "新手体验套装",
                "product_price": 199.00,
                "quantity": 2,
                "subtotal": 398.00
            }
        ],
        "created_at": "2026-07-23T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

> 管理端详情额外返回 `user_id` 和 `user_nickname`。

---

### 6.3 完成订单

```
PUT /api/v1/admin/orders/{id}/complete
```

将"已支付"状态的订单标记为已完成。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "Order completed",
    "data": {
        "id": 1,
        "order_no": "20260723000001",
        "status": "completed",
        "updated_at": "2026-07-23T15:00:00Z"
    }
}
```

**失败响应**

订单状态不允许：

```json
{
    "code": 3002,
    "message": "Only paid orders can be completed"
}
```

---

## 7. 附录

> HTTP 状态码约定、分页参数规范等通用内容请参见 [API Design Conventions](api_design_conventions.md)。

### 订单编号规则

订单编号格式：`YYYYMMDD` + 6 位自增序号，不足补零。

```
20260723000001  →  2026年7月23日第1笔订单
20260723000012  →  2026年7月23日第12笔订单
```

### v0.2 计划

以下接口和功能计划在后续版本实现：

- 在线支付集成（付款成功后自动流转 待支付 → 已支付）
- 超时未支付自动取消
- 退款流程（已支付 → 已取消）
- 订单统计（按日期/状态汇总）
- 取消原因填写
