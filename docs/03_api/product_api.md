# Product API Design

> **Document Version:** v0.1
> **Module:** Product
> **Phase:** 4.1 Product Module
> **Status:** Draft
>
> 本文档是 Product 模块 API 的正式设计规范。所有 Schema、Service、Repository 实现必须以此为准。
>
> **全局规范：** 本文档遵循 [API Design Conventions](api_design_conventions.md)。Response 信封、分页、枚举 `{value, label}` 模式、错误码等通用规则见该文档，本文不再赘述。
>
> 业务规则见 [Product Business Rules](../01_requirements/product_business_rules.md)。

---

## 1. Design Principles

| 原则 | 说明 |
|------|------|
| RESTful | Resource-Oriented：URL 表示资源，HTTP Method 表达操作 |
| Business-Action | 按业务行为划分接口，不按数据库字段划分 |
| User/Admin 分离 | 用户接口 `/products`，管理员接口 `/admin/products` |
| 类型独立创建 | 体验和套装创建流程不同，使用独立端点 |

### Base URL

```
/api/v1
```

### 认证

需要认证的接口在 Header 中携带：

```
Authorization: Bearer <access_token>
```

### 通用响应格式

```json
{ "code": 0, "message": "success", "data": {} }
```

---

## 2. Data Objects

### 2.1 Product

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 商品 ID |
| name | string | 商品名称，最大 100 字符 |
| product_type | string 或 `{value, label}` | 列表用原始值 `"experience"`（路由判断），详情用 `{ "value": "experience", "label": "拼豆体验" }` |
| description | string | 商品描述（仅详情返回） |
| cover_image | string | 封面图 URL（从 images 派生） |
| options | array | **体验商品返回**，Option 列表 |
| kit | object | **套装商品返回**，套装扩展信息 |
| images | array | 图片列表（仅详情返回） |
| created_at | datetime | 创建时间（仅列表返回） |

### 2.2 ExperienceOption

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | Option ID |
| duration | object | `{ "value": 60, "label": "1小时" }` |
| participants | object | `{ "value": 2, "label": "2人" }` |
| day_type | object | `{ "value": "weekday", "label": "工作日" }` |
| price | number | 该配置价格，0 < Price ≤ 99999 |
| sort | int | 展示排序 |

> **枚举字段统一使用 `{value, label}` 格式**（见 [API Design Conventions §9.4](api_design_conventions.md#94-枚举值--valuelabel-模式)）。
> Duration 的 DB 值为分钟数（60/120/480），Participants 为人数（1/2），Service 层负责转换为 label。

### 2.3 Kit

| 字段 | 类型 | 说明 |
|------|------|------|
| price | number | 套装售价 |
| stock | int | 当前库存 |
| sold_count | int | 累计销量 |

### 2.4 Image

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 图片 ID |
| image_url | string | 图片 URL |
| is_cover | boolean | 是否封面图 |
| sort | int | 排序序号 |

---

## 3. Error Codes

| code | 说明 |
|------|------|
| 0 | 成功 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 参数校验失败 |
| 2001 | 商品不存在 |
| 2003 | 非套装商品不支持此操作 |
| 2004 | 操作不允许（状态不满足前置条件） |
| 2006 | Option 不存在 |
| 2007 | Option 配置重复 |
| 2008 | 上线失败：体验商品至少需要一个 Option |

---

## 4. Endpoints

### 4.1 User API

| Method | URI | 说明 | 认证 |
|--------|-----|------|------|
| GET | /products | 商品列表（仅 online） | ❌ |
| GET | /products/experience/{id} | 拼豆体验详情 | ❌ |
| GET | /products/kit/{id} | 拼豆套装详情 | ❌ |

> **核心规律：**
> - List（列表）→ 统一
> - Detail（详情）→ 按类型拆分
> - Create（创建）→ 按类型拆分
> - 公共业务动作（上下架、删除）→ 统一
> - 类型专属动作（Option、价格、库存）→ 按类型拆分，URL 中明确标注类型

### 4.2 Admin API

**商品管理**

| Method | URI | 说明 |
|--------|-----|------|
| GET | /admin/products | 商品列表（全部状态，摘要信息） |
| GET | /admin/products/experience/{id} | 体验商品详情（管理用） |
| GET | /admin/products/kit/{id} | 套装商品详情（管理用） |
| POST | /admin/products/experience | 创建体验商品 |
| POST | /admin/products/kit | 创建套装商品 |
| PUT | /admin/products/{id} | 编辑商品基本信息（name, description） |
| DELETE | /admin/products/{id} | 逻辑删除 |

**状态管理**

| Method | URI | 说明 |
|--------|-----|------|
| PATCH | /admin/products/{id}/online | 上架（Service 按 product_type 执行不同校验） |
| PATCH | /admin/products/{id}/offline | 下架 |

**体验配置（Option）—— 仅 Experience**

| Method | URI | 说明 |
|--------|-----|------|
| POST | /admin/products/experience/{id}/options | 新增 Option |
| PUT | /admin/options/{option_id} | 修改 Option |
| DELETE | /admin/options/{option_id} | 删除 Option |

**套装管理 —— 仅 Kit**

| Method | URI | 说明 |
|--------|-----|------|
| PATCH | /admin/products/kit/{id}/price | 修改价格 |
| PATCH | /admin/products/kit/{id}/stock | 修改库存 |

### 4.3 Permission Matrix

| API | USER | ADMIN |
|-----|------|-------|
| GET /products | ✅ | ✅ |
| GET /products/experience/{id} | ✅ | ✅ |
| GET /products/kit/{id} | ✅ | ✅ |
| 所有 /admin/* | ❌ | ✅ |

---

## 5. Business Rules

### 5.1 Status Lifecycle

```
draft ──→ online ──→ offline
  ↑         │  ↑        │
  │         │  └────────┘
  │         │   (re-online)
  │         │
  └─ 删除最后 Option 时自动回退（体验商品）
```

| 流转 | 触发 | 校验 |
|------|------|------|
| draft → online | `PATCH .../online` | 体验商品 Option ≥ 1 |
| online → offline | `PATCH .../offline` | — |
| offline → online | `PATCH .../online` | 保持原 Product ID |
| online → draft | 自动 | 删除最后 Option 后触发 |

### 5.2 Constraints

| 规则 | 说明 |
|------|------|
| product_type 不可修改 | 创建后不可变更 |
| Draft 允许无 Option | 先创建商品，再逐步添加配置 |
| Online 至少一个 Option | 上线校验 |
| Option 唯一性 | 同一 Product 内 (duration, participants, day_type) 唯一 |
| 重新上架保持原 ID | 不创建新商品 |
| 逻辑删除 | DELETE 执行逻辑删除；online 商品需先下架 |
| 价格快照 | 订单创建时快照当前价格，后续变更不影响历史订单 |

---

## 6. User API

### 6.1 商品列表

```
GET /api/v1/products
```

统一商品列表，仅返回 `status = "online"` 且 `is_deleted = false` 的商品。列表展示字段高度一致，不按类型拆分。

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| product_type | string | 否 | — | `"experience"` / `"kit"` |
| keyword | string | 否 | — | 搜索名称 / 描述 |

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 1,
                "name": "拼豆体验",
                "product_type": "experience",
                "cover_image": "https://cdn.example.com/products/1-cover.jpg",
                "display_price": "299.00",
                "price_label": "起",
                "created_at": "2026-07-30T10:30:00Z"
            },
            {
                "id": 2,
                "name": "拼豆套装",
                "product_type": "kit",
                "cover_image": "https://cdn.example.com/products/2-cover.jpg",
                "display_price": "599.00",
                "price_label": null,
                "created_at": "2026-07-30T10:30:00Z"
            }
        ],
        "total": 20,
        "page": 1,
        "page_size": 20,
        "pages": 1
    }
}
```

| 字段 | 说明 |
|------|------|
| `display_price` | 展示价格。体验商品为最低 Option 价格，套装商品为固定售价 |
| `price_label` | 价格后缀。体验商品返回 `"起"`（表示最低价起），套装商品返回 `null` |

> 前端根据 `product_type` 决定跳转目标：
> - `"experience"` → `/products/experience/{id}`
> - `"kit"` → `/products/kit/{id}`

---

### 6.2 拼豆体验详情

```
GET /api/v1/products/experience/{id}
```

仅返回 `product_type = "experience"`、`status = "online"`、`is_deleted = false` 的商品。
访问套装商品或不存在/未上架的商品，统一返回 `404`。

**Response Schema：** `ExperienceProductDetailResponse` — 不含 `price`、`stock`、`kit` 字段。

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "拼豆体验",
        "product_type": { "value": "experience", "label": "拼豆体验" },
        "description": "选择你的拼豆体验时长、人数和日期类型",
        "cover_image": "https://cdn.example.com/products/1-cover.jpg",
        "options": [
            {
                "id": 1,
                "duration": { "value": 60, "label": "1小时" },
                "participants": { "value": 1, "label": "1人" },
                "day_type": { "value": "weekday", "label": "工作日" },
                "price": 299,
                "sort": 10
            },
            {
                "id": 2,
                "duration": { "value": 120, "label": "2小时" },
                "participants": { "value": 2, "label": "2人" },
                "day_type": { "value": "holiday", "label": "节假日" },
                "price": 699,
                "sort": 30
            }
        ],
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-cover.jpg", "is_cover": true, "sort": 0 }
        ]
    }
}
```

> 不返回 `status`、`is_deleted`、`created_at`、`updated_at`。用户详情页不需要这些字段。图片按 `sort ASC, id ASC` 排序。

---

### 6.3 拼豆套装详情

```
GET /api/v1/products/kit/{id}
```

仅返回 `product_type = "kit"`、`status = "online"`、`is_deleted = false` 的商品。
访问体验商品或不存在/未上架的商品，统一返回 `404`。

**Response Schema：** `KitProductDetailResponse` — 不含 `options`、`status`、`is_deleted`、`sold_count`、时间字段。

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 2,
        "name": "拼豆套装",
        "product_type": { "value": "kit", "label": "拼豆套装" },
        "description": "适合新手入门的固定拼豆套装",
        "images": [
            { "id": 5, "image_url": "https://example.com/kit-cover.jpg", "is_cover": true, "sort": 0 },
            { "id": 6, "image_url": "https://example.com/kit-detail.jpg", "is_cover": false, "sort": 10 }
        ],
        "price": "599.00",
        "stock": 20,
        "available": true
    }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| price | string | 售价，Decimal → string 序列化 |
| stock | int | 当前库存（展示参考用） |
| available | boolean | `stock > 0`。下单时后端**必须**重新校验库存，不能相信详情页旧数据 |

> 不返回 `status`、`is_deleted`、`created_at`、`updated_at`、`sold_count`、`product_kit_id`。图片按 `sort ASC, id ASC` 排序。

---

## 7. Admin API

> 以下接口需要 `ADMIN+`。所有 `/admin/` 前缀端点调用 `get_current_admin` 依赖。
>
> **管理员查看所有状态商品**（draft / online / offline），与用户端仅返回 online 不同。
>
> **管理员详情不返回 Audit Log。** 审计日志通过共享 `AuditService.list_logs(target_type="product", target_id=...)` 统一查询，不属于 Product 模块职责。

### 7.1 商品列表（摘要）

```
GET /api/v1/admin/products
```

统一列表，返回全部状态（draft / online / offline）且未删除的商品。仅返回摘要信息——完整数据见详情接口。

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| product_type | string | 否 | — | `"experience"` / `"kit"` |
| status | string | 否 | — | `"draft"` / `"online"` / `"offline"` |
| keyword | string | 否 | — | 搜索名称 |

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 1,
                "name": "拼豆体验",
                "product_type": { "value": "experience", "label": "拼豆体验" },
                "status": { "value": "online", "label": "已上架" },
                "cover_image": "https://cdn.example.com/products/1-cover.jpg",
                "display_price": "299.00",
                "updated_at": "2026-08-04T18:30:00+08:00"
            },
            {
                "id": 2,
                "name": "拼豆套装",
                "product_type": { "value": "kit", "label": "拼豆套装" },
                "status": { "value": "draft", "label": "草稿" },
                "cover_image": null,
                "display_price": null,
                "updated_at": "2026-08-04T18:30:00+08:00"
            }
        ],
        "total": 2,
        "page": 1,
        "page_size": 20,
        "pages": 1
    }
}
```

| 字段 | 说明 |
|------|------|
| `display_price` | 体验商品为所有 Option 最低价（Draft 无 Option 时为 `null`）；套装商品为 `product_kits.price`。不得返回 `"0.00"` |
| 不返回 | `description`、`images`、`options`、`stock`、`created_at`（详情接口获取） |

---

### 7.2 体验商品详情（管理）

```
GET /api/v1/admin/products/experience/{id}
```

仅返回 `product_type = "experience"` 的商品。draft / online / offline 均可查看。

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "拼豆体验",
        "product_type": { "value": "experience", "label": "拼豆体验" },
        "description": "选择你的拼豆体验时长、人数和日期类型",
        "status": { "value": "online", "label": "已上架" },
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-cover.jpg", "is_cover": true, "sort": 0 }
        ],
        "dimensions": {
            "durations": [
                { "value": 60, "label": "1小时" },
                { "value": 120, "label": "2小时" }
            ],
            "participants": [
                { "value": 1, "label": "1人" },
                { "value": 2, "label": "2人" }
            ],
            "day_types": [
                { "value": "weekday", "label": "工作日" },
                { "value": "holiday", "label": "节假日" }
            ]
        },
        "options": [
            {
                "id": 1,
                "duration": { "value": 60, "label": "1小时" },
                "participants": { "value": 1, "label": "1人" },
                "day_type": { "value": "weekday", "label": "工作日" },
                "price": "299.00",
                "sort": 10
            },
            {
                "id": 2,
                "duration": { "value": 120, "label": "2小时" },
                "participants": { "value": 2, "label": "2人" },
                "day_type": { "value": "holiday", "label": "节假日" },
                "price": "699.00",
                "sort": 30
            }
        ],
        "created_at": "2026-08-04T18:30:00+08:00",
        "updated_at": "2026-08-04T18:30:00+08:00"
    }
}
```

| 字段 | 说明 |
|------|------|
| `dimensions` | 由 options 动态计算——当前已有哪些时长/人数/日期类型可选，方便管理端 UI 生成筛选 |
| `options` | 完整列表，含所有 Option。`price` 使用字符串格式 |
| 与用户详情不同 | 管理员可查看 draft/offline；返回 `status`、`created_at`、`updated_at` |

---

### 7.3 套装商品详情（管理）

```
GET /api/v1/admin/products/kit/{id}
```

仅返回 `product_type = "kit"` 的商品。

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 2,
        "name": "拼豆套装",
        "product_type": { "value": "kit", "label": "拼豆套装" },
        "description": "适合新手入门的固定拼豆套装",
        "status": { "value": "online", "label": "已上架" },
        "images": [
            { "id": 5, "image_url": "https://cdn.example.com/products/2-cover.jpg", "is_cover": true, "sort": 0 }
        ],
        "price": "599.00",
        "stock": 20,
        "created_at": "2026-08-04T18:30:00+08:00",
        "updated_at": "2026-08-04T18:30:00+08:00"
    }
}
```

| 与用户详情不同 | 管理员可查看 draft/offline；返回 `status`、`created_at`、`updated_at`；无 `available`（管理员关心原始数据） |

---

### 7.4 创建体验商品

```
POST /api/v1/admin/products/experience
```

体验商品可初始创建 Option 列表，也可后续通过 Option 接口添加。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 商品名称，1-100 字符 |
| description | string | 否 | 商品描述，最大 2000 字符 |
| options | array | 否 | Option 列表 |

`options` 中每项：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| duration | int | 是 | 60 / 120 / 480 |
| participants | int | 是 | 1 / 2 |
| day_type | string | 是 | `"weekday"` / `"holiday"` |
| price | number | 是 | 0 < Price ≤ 99999 |
| sort | int | 否 | 排序 |

**请求示例**

```json
{
    "name": "拼豆体验",
    "description": "选择你的拼豆体验",
    "options": [
        { "duration": 60, "participants": 1, "day_type": "weekday", "price": 299, "sort": 10 },
        { "duration": 120, "participants": 1, "day_type": "weekday", "price": 499, "sort": 20 }
    ]
}
```

**成功响应** — HTTP 201，返回管理端体验详情（status = `"draft"`）。

---

### 7.5 创建套装商品

```
POST /api/v1/admin/products/kit
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 商品名称 |
| description | string | 否 | 商品描述 |
| price | number | 是 | 售价，0 < Price ≤ 99999 |
| stock | int | 是 | 初始库存，>= 0 |

**请求示例**

```json
{
    "name": "新手体验套装",
    "description": "入门级拼豆套装",
    "price": 599,
    "stock": 100
}
```

---

### 7.6 编辑商品基本信息

```
PUT /api/v1/admin/products/{id}
```

统一接口，同时适用于体验和套装。仅修改 `name` 和 `description`。不可修改 `product_type`、`price`、`stock`、`options`、`status`（这些有独立业务接口）。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 商品名称 |
| description | string | 否 | 商品描述 |

---

### 7.7 逻辑删除

```
DELETE /api/v1/admin/products/{id}
```

执行逻辑删除（`is_deleted = true`）。`online` 商品需先下架。

---

### 7.8 上架

```
PATCH /api/v1/admin/products/{id}/online
```

Service 按 `product_type` 执行不同校验：

| 类型 | 校验 |
|------|------|
| experience | 有封面图 + Option ≥ 1 + Option 配置合法 + 价格合法 |
| kit | 有封面图 + price > 0 + stock ≥ 0 |

**成功响应**

```json
{ "code": 0, "message": "Product is now online" }
```

**失败响应**

```json
{ "code": 2008, "message": "Experience product requires at least one option before going online" }
```

---

### 7.9 下架

```
PATCH /api/v1/admin/products/{id}/offline
```

**成功响应**

```json
{ "code": 0, "message": "Product is now offline" }
```

---

### 7.10 新增 Option

```
POST /api/v1/admin/products/experience/{id}/options
```

仅适用于 `product_type = "experience"`。URL 中明确标注 `experience`。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| duration | int | 是 | 60 / 120 / 480 |
| participants | int | 是 | 1 / 2 |
| day_type | string | 是 | `"weekday"` / `"holiday"` |
| price | number | 是 | 0 < Price ≤ 99999 |
| sort | int | 否 | 排序 |

**失败响应**

```json
{ "code": 2007, "message": "Option already exists: weekday + 60min + 1person" }
```

---

### 7.11 修改 Option

```
PUT /api/v1/admin/options/{option_id}
```

修改 Option 的价格或排序。历史订单不受影响。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| price | number | 否 | 新价格 |
| sort | int | 否 | 新排序 |

---

### 7.12 删除 Option

```
DELETE /api/v1/admin/options/{option_id}
```

删除后若商品为 `online` 且剩余 Option = 0，自动转为 `draft`。

---

### 7.13 修改套装价格

```
PATCH /api/v1/admin/products/kit/{id}/price
```

仅适用于 `product_type = "kit"`。URL 中明确标注 `kit`。历史订单不受影响。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| price | number | 是 | 新价格，0 < Price ≤ 99999 |

---

### 7.14 修改套装库存

```
PATCH /api/v1/admin/products/kit/{id}/stock
```

仅适用于 `product_type = "kit"`。URL 中明确标注 `kit`。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stock | int | 是 | 新库存，>= 0 |
