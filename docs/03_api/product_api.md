# Product API

> 本文档遵循 [API Design Conventions](api_design_conventions.md) 中定义的通用规范（响应格式、错误码、分页、数据类型等），重复内容不再赘述。
>
> 业务规则详见 [Product Business Rules](../01_requirements/product_business_rules.md)。

---

## 1. 概述

商品模块负责拼豆店服务与商品的管理，包括拼豆体验和拼豆套装。该模块面向两类用户：

- 游客 / 普通用户：浏览商品列表、查看商品详情（含 Option 选择）
- 管理员：创建、修改、上下架、管理 Option、库存管理、图片管理

### 领域模型

```
Product（商品） 1 ──→ N ExperienceOption（体验配置）
```

- **体验商品**：一个 Product（"拼豆体验"）+ 多个 Option（时长 + 人数 + 日期类型 → 价格）
- **套装商品**：一个 Product + 一个 product_kit（价格 + 库存）

### Base URL

```
/api/v1
```

### 认证方式

JWT Bearer Token。需要认证的接口在 Header 中携带：

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

### 商品对象

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 商品 ID |
| name | string | 商品名称，最大 100 字符 |
| product_type | string | 商品类型：`"experience"` / `"kit"`，创建后不可修改 |
| description | string | 商品描述 |
| status | string | 状态：`"draft"` / `"online"` / `"offline"` |
| cover_image | string | 封面图 URL（从 `images` 中 `is_cover = true` 的记录派生） |
| options | array | **体验商品返回**，Option 对象列表 |
| kit | object | **套装商品返回**，套装扩展信息 |
| images | array | 图片对象列表（详情接口返回） |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最近更新时间 |

### Option 对象（product_type = "experience" 时返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | Option ID |
| duration | string | 体验时长：`"1h"` / `"2h"` / `"full_day"` |
| participants | int | 体验人数：1 / 2 |
| day_type | string | 日期类型：`"weekday"` / `"holiday"` |
| price | number | 该配置价格，0 < Price ≤ 99999 |
| sort | int | 展示排序 |

### 套装扩展对象（product_type = "kit" 时返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| price | number | 套装售价 |
| stock | int | 当前库存 |
| sold_count | int | 累计销量 |

### 图片对象

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 图片 ID |
| image_url | string | 图片 URL |
| is_cover | boolean | 是否封面图，每个商品最多一张 |
| sort | int | 排序序号 |

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

### 商品模块错误码（2xxx）

| code | 说明 |
|------|------|
| 2001 | 商品不存在 |
| 2002 | 库存不足 |
| 2003 | 非套装商品不支持库存管理 |
| 2004 | 操作不允许（当前商品状态不允许此操作） |
| 2005 | 图片不存在 |
| 2006 | Option 不存在 |
| 2007 | Option 配置重复 |
| 2008 | 上线失败：体验商品至少需要一个 Option |

---

## 3. 字段校验规则

| 字段 | 规则 |
|------|------|
| name | 必填，1-100 字符 |
| product_type | 必填，`"experience"` 或 `"kit"`，创建后不可修改 |
| description | 可选，最大 2000 字符 |
| price | 必填（Option 或 kit），> 0，≤ 99999，最多两位小数 |
| duration | Option 必填，`"1h"` / `"2h"` / `"full_day"` |
| participants | Option 必填，1 / 2 |
| day_type | Option 必填，`"weekday"` / `"holiday"` |
| stock | 套装必填，>= 0 |
| image | 图片文件，最大 2MB，支持 jpg/png/webp |

---

## 4. 端点列表

| Method | URI | 描述 | 认证 | 角色 |
|--------|-----|------|------|------|
| GET | /products | 商品列表 | ❌ | 游客 |
| GET | /products/{id} | 商品详情 | ❌ | 游客 |
| POST | /products | 创建商品 | ✅ | 管理员 |
| PUT | /products/{id} | 修改商品 | ✅ | 管理员 |
| PUT | /products/{id}/online | 上架商品 | ✅ | 管理员 |
| PUT | /products/{id}/offline | 下架商品 | ✅ | 管理员 |
| POST | /products/{id}/options | 新增 Option | ✅ | 管理员 |
| PUT | /products/{id}/options/{option_id} | 修改 Option | ✅ | 管理员 |
| DELETE | /products/{id}/options/{option_id} | 删除 Option | ✅ | 管理员 |
| PUT | /products/{id}/stock | 管理库存 | ✅ | 管理员 |
| POST | /products/{id}/images | 上传图片 | ✅ | 管理员 |
| DELETE | /products/{id}/images/{image_id} | 删除图片 | ✅ | 管理员 |
| PUT | /products/{id}/images/sort | 图片排序 | ✅ | 管理员 |

---

## 业务规则

### 状态流转

```
  draft ──→ online ──→ offline
    ↑         │  ↑        │
    │         │  └────────┘
    │         │   (重新上架)
    │         │
    └─ 删除最后 Option 时自动回退（体验商品）
```

| 流转 | 触发方式 | 说明 |
|------|----------|------|
| draft → online | `PUT /products/{id}/online` | 体验商品须 Option ≥ 1 |
| online → offline | `PUT /products/{id}/offline` | 管理员下架 |
| offline → online | `PUT /products/{id}/online` | 重新上架，保持原 ID |
| online → draft | 自动 | 删除最后 Option 时自动回退 |
| 逻辑删除 | `PUT /products/{id}/offline` + 标记 | online 商品需先下架 |

### 约束规则

| 规则 | 说明 |
|------|------|
| 类型不可修改 | `product_type` 创建后不可变更 |
| Draft 允许无 Option | 先创建商品，再逐步添加配置 |
| Online 至少一个 Option | 体验商品上线前校验 Option ≥ 1 |
| Option 唯一性 | 同一 Product 内 `(duration, participants, day_type)` 组合唯一 |
| 重新上架保持原 ID | 不创建新商品 |
| 逻辑删除 | 禁止物理删除；FK 使用 `ON DELETE RESTRICT` |
| 价格快照 | 订单创建时快照 Option 价格，后续变更不影响历史订单 |
| 封面互斥 | 每商品最多一张封面图 |

---

## 5. 公共接口

### 5.1 商品列表

```
GET /api/v1/products
```

分页浏览商品，仅返回 `status = "online"` 的商品。

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| product_type | string | 否 | - | 按类型筛选：`"experience"` / `"kit"` |
| keyword | string | 否 | - | 搜索关键词（匹配 name / description） |

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
                "description": "选择你的拼豆体验时长和人数",
                "cover_image": "https://cdn.example.com/products/1-cover.jpg",
                "status": "online",
                "options": [
                    { "id": 1, "duration": "1h", "participants": 1, "day_type": "weekday", "price": 299, "sort": 10 },
                    { "id": 2, "duration": "2h", "participants": 1, "day_type": "weekday", "price": 499, "sort": 20 }
                ],
                "created_at": "2026-01-15T10:30:00Z",
                "updated_at": "2026-01-15T10:30:00Z"
            },
            {
                "id": 2,
                "name": "新手体验套装",
                "product_type": "kit",
                "description": "入门级拼豆套装，含全部材料",
                "cover_image": "https://cdn.example.com/products/2-cover.jpg",
                "status": "online",
                "kit": { "price": 599, "stock": 100, "sold_count": 50 },
                "created_at": "2026-01-16T08:00:00Z",
                "updated_at": "2026-07-20T14:00:00Z"
            }
        ],
        "total": 20,
        "page": 1,
        "page_size": 20,
        "pages": 1
    }
}
```

---

### 5.2 商品详情

```
GET /api/v1/products/{id}
```

获取商品完整信息，包含 Option 列表、扩展字段和图片列表。

**成功响应（体验商品）**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "拼豆体验",
        "product_type": "experience",
        "description": "选择你的拼豆体验时长、人数和日期类型",
        "cover_image": "https://cdn.example.com/products/1-cover.jpg",
        "status": "online",
        "options": [
            { "id": 1, "duration": "1h", "participants": 1, "day_type": "weekday", "price": 299, "sort": 10 },
            { "id": 2, "duration": "1h", "participants": 2, "day_type": "weekday", "price": 399, "sort": 20 },
            { "id": 3, "duration": "2h", "participants": 1, "day_type": "holiday", "price": 599, "sort": 30 }
        ],
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-cover.jpg", "is_cover": true, "sort": 0 }
        ],
        "created_at": "2026-01-15T10:30:00Z",
        "updated_at": "2026-01-15T10:30:00Z"
    }
}
```

**成功响应（套装商品）**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 2,
        "name": "新手体验套装",
        "product_type": "kit",
        "description": "入门级拼豆套装，含全部所需材料。",
        "cover_image": "https://cdn.example.com/products/2-cover.jpg",
        "status": "online",
        "kit": { "price": 599, "stock": 100, "sold_count": 50 },
        "images": [
            { "id": 3, "image_url": "https://cdn.example.com/products/2-cover.jpg", "is_cover": true, "sort": 0 }
        ],
        "created_at": "2026-01-16T08:00:00Z",
        "updated_at": "2026-07-20T14:00:00Z"
    }
}
```

**失败响应**

```json
{
    "code": 2001,
    "message": "Product not found"
}
```

---

## 6. 管理接口

> 以下接口需要管理员角色（`ADMIN+`），普通用户调用返回 403。

### 6.1 创建商品

```
POST /api/v1/products
```

创建新商品（默认 `draft`）。体验商品可初始创建 Option 列表，也可后续通过 Option 接口添加。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 商品名称，1-100 字符 |
| product_type | string | 是 | `"experience"` / `"kit"` |
| description | string | 否 | 商品描述 |
| options | array | 否 | Option 列表（仅体验商品） |
| kit | object | 套装必填 | 套装扩展信息 |
| images | array | 否 | 图片列表 |

**请求示例（创建体验商品 — 含 Option）**

```json
{
    "name": "拼豆体验",
    "product_type": "experience",
    "description": "选择你的拼豆体验",
    "options": [
        { "duration": "1h", "participants": 1, "day_type": "weekday", "price": 299, "sort": 10 },
        { "duration": "2h", "participants": 1, "day_type": "weekday", "price": 499, "sort": 20 }
    ]
}
```

**请求示例（创建套装）**

```json
{
    "name": "新手体验套装",
    "product_type": "kit",
    "description": "入门级拼豆套装",
    "kit": { "price": 599, "stock": 100 }
}
```

---

### 6.2 修改商品

```
PUT /api/v1/products/{id}
```

修改商品基本信息（名称、描述）。不可修改 `product_type`。

---

### 6.3 上架商品

```
PUT /api/v1/products/{id}/online
```

将商品状态设为 `"online"`。体验商品校验 Option ≥ 1，不满足返回 2008。

---

### 6.4 下架商品

```
PUT /api/v1/products/{id}/offline
```

将商品状态设为 `"offline"`。`online` 商品需先下架才能逻辑删除。

---

### 6.5 新增 Option

```
POST /api/v1/products/{id}/options
```

为体验商品新增可选配置。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| duration | string | 是 | `"1h"` / `"2h"` / `"full_day"` |
| participants | int | 是 | 1 / 2 |
| day_type | string | 是 | `"weekday"` / `"holiday"` |
| price | number | 是 | 售价 |
| sort | int | 否 | 排序 |

**失败响应**

```json
{
    "code": 2007,
    "message": "Option already exists: weekday + 1h + 1person"
}
```

---

### 6.6 修改 Option

```
PUT /api/v1/products/{id}/options/{option_id}
```

修改 Option 的价格或排序。修改后仅影响新订单，历史订单保留价格快照。

---

### 6.7 删除 Option

```
DELETE /api/v1/products/{id}/options/{option_id}
```

删除指定 Option。若删除后商品 `online` 且剩余 Option = 0，自动转为 `draft`。

---

### 6.8 管理库存

```
PUT /api/v1/products/{id}/stock
```

修改套装商品库存，仅适用于 `product_type = "kit"`。

**失败响应**

```json
{
    "code": 2003,
    "message": "Only kit products support stock management"
}
```

---

### 6.9 上传图片

```
POST /api/v1/products/{id}/images
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 图片文件，最大 2MB，jpg/png/webp |
| is_cover | boolean | 否 | 是否封面图 |
| sort | int | 否 | 排序序号 |

---

### 6.10 删除图片

```
DELETE /api/v1/products/{id}/images/{image_id}
```

---

### 6.11 图片排序

```
PUT /api/v1/products/{id}/images/sort
```

```json
{
    "orders": [
        { "id": 1, "sort": 2 },
        { "id": 2, "sort": 0 }
    ]
}
```
