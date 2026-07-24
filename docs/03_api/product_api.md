# Product API

> 本文档遵循 [API Design Conventions](api_design_conventions.md) 中定义的通用规范（响应格式、错误码、分页、数据类型等），重复内容不再赘述。

---

## 1. 概述

商品模块负责拼豆店服务与商品的管理，包括拼豆体验和拼豆套装。该模块面向两类用户：

- 游客 / 普通用户：浏览商品列表、查看商品详情
- 管理员：创建、修改、上下架、库存管理、图片管理

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

### 商品对象

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 商品 ID |
| name | string | 商品名称 |
| product_type | string | 商品类型：`"experience"` 体验 / `"kit"` 套装 |
| description | string | 商品描述 |
| price | number | 售价，单位：元 |
| cover_image | string | 封面图 URL（从 `images` 中 `is_cover = true` 的记录派生） |
| status | string | 状态：`"draft"` 草稿 / `"online"` 上架 / `"offline"` 下架 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最近更新时间 |

### 体验扩展对象（product_type = "experience" 时返回）

| 字段 | 类型 | 说明 |
|------|------|------|
| duration | int | 体验时长（小时） |
| capacity | int | 可体验人数 |
| day_type | string | 日期类型：`"weekday"` 工作日 / `"weekend"` 周末 |

### 套装扩展对象（product_type = "kit" 时返回）

| 字段 | 类型 | 说明 |
|------|------|------|
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

---

## 3. 字段校验规则

| 字段 | 规则 |
|------|------|
| name | 必填，1-64 字符 |
| product_type | 必填，`"experience"` 或 `"kit"` |
| description | 可选，最大 2000 字符 |
| price | 必填，> 0，最多两位小数 |
| duration | 体验必填，> 0（小时） |
| capacity | 体验必填，> 0（人数） |
| day_type | 体验必填，`"weekday"` 或 `"weekend"` |
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
| PUT | /products/{id}/stock | 管理库存 | ✅ | 管理员 |
| POST | /products/{id}/images | 上传图片 | ✅ | 管理员 |
| DELETE | /products/{id}/images/{image_id} | 删除图片 | ✅ | 管理员 |
| PUT | /products/{id}/images/sort | 图片排序 | ✅ | 管理员 |

---

## 业务规则

### 状态流转

```
  draft ──→ online ──→ offline
             │  ↑        │
             │  └────────┘
             │   (重新上架)
             │
             ▼
           (用户可见)
```

| 流转 | 触发接口 | 说明 |
|------|----------|------|
| draft → online | `PUT /products/{id}/online` | 管理员发布商品 |
| online → offline | `PUT /products/{id}/offline` | 管理员下架商品 |
| offline → online | `PUT /products/{id}/online` | 管理员重新上架 |

> - `draft` 状态用户不可见，仅管理员可见
> - 不存在 `draft ↔ offline` 的直接流转，必须经过 `online`
> - 不存在回退到 `draft` 的路径

### 约束规则

| 规则 | 说明 |
|------|------|
| 类型不可修改 | `product_type` 创建后不可变更 |
| 默认状态 | 创建后商品状态默认为 `"draft"`（草稿） |
| draft 可完整修改 | `"draft"` 状态允许修改所有字段（名称、描述、价格、扩展信息） |
| online 可部分修改 | `"online"` 状态仅允许修改价格和描述，名称和扩展信息不可变 |
| 上架来源不限 | `"draft"` 或 `"offline"` 状态均可执行上架操作 |
| offline 可重新上架 | `"offline"` 商品可通过上架接口恢复 |
| 封面互斥 | 每商品最多一张封面图，设置新的 `is_cover = true` 时自动取消其他图片的封面标记 |
| 套装库存独立管理 | 非套装商品调用库存接口返回 2003 |
| 删除商品 | ❌ 当前版本不支持物理删除，仅通过下架实现逻辑删除。物理删除计划在 v1.0 实现 |

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
                "name": "工作日单人 1 小时体验",
                "product_type": "experience",
                "description": "适合新手的工作日单人体验",
                "price": 99.00,
                "cover_image": "https://cdn.example.com/products/1-detail-1.jpg",
                "status": "online",
                "created_at": "2026-01-15T10:30:00Z",
                "updated_at": "2026-01-15T10:30:00Z"
            },
            {
                "id": 2,
                "name": "新手体验套装",
                "product_type": "kit",
                "description": "入门级拼豆套装，含全部材料",
                "price": 199.00,
                "cover_image": "https://cdn.example.com/products/2-detail-1.jpg",
                "status": "online",
                "created_at": "2026-01-16T08:00:00Z",
                "updated_at": "2026-07-20T14:00:00Z"
            }
        ],
        "total": 20,
        "page": 1,
        "page_size": 20
    }
}
```

> 列表中不返回扩展信息和图片列表，减少数据传输量。`cover_image` 由 `product_images` 中 `is_cover = true` 的图片 URL 派生。

---

### 5.2 商品详情

```
GET /api/v1/products/{id}
```

获取商品完整信息，包含类型扩展字段和图片列表。

**成功响应（体验商品）**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "工作日单人 1 小时体验",
        "product_type": "experience",
        "description": "适合新手的工作日单人体验，提供全套工具和材料。",
        "price": 99.00,
        "cover_image": "https://cdn.example.com/products/1-detail-1.jpg",
        "status": "online",
        "experience": {
            "duration": 1,
            "capacity": 1,
            "day_type": "weekday"
        },
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-detail-1.jpg", "is_cover": true, "sort": 0 },
            { "id": 2, "image_url": "https://cdn.example.com/products/1-detail-2.jpg", "is_cover": false, "sort": 1 }
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
        "price": 199.00,
        "cover_image": "https://cdn.example.com/products/2-detail-1.jpg",
        "status": "online",
        "kit": {
            "stock": 100,
            "sold_count": 50
        },
        "images": [
            { "id": 3, "image_url": "https://cdn.example.com/products/2-detail-1.jpg", "is_cover": true, "sort": 0 }
        ],
        "created_at": "2026-01-16T08:00:00Z",
        "updated_at": "2026-07-20T14:00:00Z"
    }
}
```

> 体验商品返回 `experience` 对象，套装商品返回 `kit` 对象，不含对方字段。`cover_image` 由 `images` 中 `is_cover = true` 的图片派生。

**失败响应**

商品不存在或未上架：

```json
{
    "code": 2001,
    "message": "Product not found"
}
```

---

## 6. 管理接口

> 以下接口需要管理员角色（`role = "admin"`），普通用户调用返回 403。

### 6.1 创建商品

```
POST /api/v1/products
```

创建新商品，根据 `product_type` 传入对应的扩展信息。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 商品名称，1-64 字符 |
| product_type | string | 是 | `"experience"` 或 `"kit"` |
| description | string | 否 | 商品描述 |
| price | number | 是 | 售价（元），> 0 |
| experience | object | 体验必填 | 体验扩展信息，仅 product_type="experience" |
| experience.duration | int | 是 | 体验时长（小时） |
| experience.capacity | int | 是 | 可体验人数 |
| experience.day_type | string | 是 | `"weekday"` 或 `"weekend"` |
| kit | object | 套装必填 | 套装扩展信息，仅 product_type="kit" |
| kit.stock | int | 是 | 初始库存，>= 0 |
| images | array | 否 | 图片列表，每项含 `image_url`、`is_cover`（仅一张为 true）、`sort` |

**请求示例（创建体验）**

```json
{
    "name": "工作日单人 1 小时体验",
    "product_type": "experience",
    "description": "适合新手的工作日单人体验",
    "price": 99.00,
    "experience": {
        "duration": 1,
        "capacity": 1,
        "day_type": "weekday"
    },
    "images": [
        { "image_url": "https://cdn.example.com/products/1-detail-1.jpg", "is_cover": true, "sort": 0 }
    ]
}
```

**请求示例（创建套装）**

```json
{
    "name": "新手体验套装",
    "product_type": "kit",
    "description": "入门级拼豆套装",
    "price": 199.00,
    "kit": {
        "stock": 100
    },
    "images": [
        { "image_url": "https://cdn.example.com/products/2-detail-1.jpg", "is_cover": true, "sort": 0 }
    ]
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
        "name": "工作日单人 1 小时体验",
        "product_type": "experience",
        "description": "适合新手的工作日单人体验",
        "price": 99.00,
        "cover_image": "https://cdn.example.com/products/1-detail-1.jpg",
        "status": "draft",
        "experience": {
            "duration": 1,
            "capacity": 1,
            "day_type": "weekday"
        },
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-detail-1.jpg", "is_cover": true, "sort": 0 }
        ],
        "created_at": "2026-07-23T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

> 创建后商品状态默认为 `"draft"`，需手动上架。

**失败响应**

参数校验失败：

```json
{
    "code": 422,
    "message": "Validation failed",
    "data": {
        "product_type": "product_type must be 'experience' or 'kit'",
        "experience": "experience is required when product_type is 'experience'"
    }
}
```

---

### 6.2 修改商品

```
PUT /api/v1/products/{id}
```

修改商品基本信息和扩展信息。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 商品名称 |
| description | string | 否 | 商品描述 |
| price | number | 否 | 售价（元） |
| experience | object | 否 | 体验扩展信息（仅体验商品） |
| kit | object | 否 | 套装扩展信息（仅套装商品） |

> 至少传递一个字段。不可修改 `product_type`。

**请求示例**

```json
{
    "name": "工作日单人 2 小时体验",
    "price": 129.00,
    "experience": {
        "duration": 2,
        "capacity": 1,
        "day_type": "weekday"
    }
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "工作日单人 2 小时体验",
        "product_type": "experience",
        "description": "适合新手的工作日单人体验",
        "price": 129.00,
        "cover_image": "https://cdn.example.com/products/1-detail-1.jpg",
        "status": "online",
        "experience": {
            "duration": 2,
            "capacity": 1,
            "day_type": "weekday"
        },
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-detail-1.jpg", "is_cover": true, "sort": 0 }
        ],
        "created_at": "2026-01-15T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

**失败响应**

商品不存在：

```json
{
    "code": 2001,
    "message": "Product not found"
}
```

---

### 6.3 上架商品

```
PUT /api/v1/products/{id}/online
```

将商品状态设为 `"online"`。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "Product is now online"
}
```

**失败响应**

商品不存在：

```json
{
    "code": 2001,
    "message": "Product not found"
}
```

已是上架状态：

```json
{
    "code": 2004,
    "message": "Product is already online"
}
```

---

### 6.4 下架商品

```
PUT /api/v1/products/{id}/offline
```

将商品状态设为 `"offline"`。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "Product is now offline"
}
```

**失败响应**

商品不存在：

```json
{
    "code": 2001,
    "message": "Product not found"
}
```

---

### 6.5 管理库存

```
PUT /api/v1/products/{id}/stock
```

修改套装商品的库存，仅适用于 `product_type = "kit"` 的商品。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stock | int | 是 | 新库存数量，>= 0 |

**请求示例**

```json
{
    "stock": 150
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "stock": 150
    }
}
```

**失败响应**

非套装商品：

```json
{
    "code": 2003,
    "message": "Only kit products support stock management"
}
```

---

### 6.6 上传图片

```
POST /api/v1/products/{id}/images
```

为指定商品上传图片。

**Header**

```
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 图片文件，最大 2MB，支持 jpg/png/webp |
| is_cover | boolean | 否 | 是否设为封面图，默认 false。设为 true 时自动取消其他图片的封面标记 |
| sort | int | 否 | 排序序号，默认追加到末尾 |

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 10,
        "image_url": "https://cdn.example.com/products/1-detail-10.jpg",
        "is_cover": false,
        "sort": 9
    }
}
```

**失败响应**

文件过大：

```json
{
    "code": 422,
    "message": "File size must not exceed 2MB"
}
```

---

### 6.7 删除图片

```
DELETE /api/v1/products/{id}/images/{image_id}
```

删除指定商品的某张图片。若删除的是封面图（`is_cover = true`），系统不会自动指定新封面，需客户端自行设置。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "Image deleted"
}
```

**失败响应**

图片不存在：

```json
{
    "code": 2005,
    "message": "Image not found"
}
```

---

### 6.8 图片排序

```
PUT /api/v1/products/{id}/images/sort
```

批量更新图片的排序。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| orders | array | 是 | 排序列表 |

`orders` 中每项：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | int | 是 | 图片 ID |
| sort | int | 是 | 新排序序号 |

**请求示例**

```json
{
    "orders": [
        { "id": 1, "sort": 2 },
        { "id": 2, "sort": 0 },
        { "id": 3, "sort": 1 }
    ]
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "images": [
            { "id": 2, "image_url": "https://cdn.example.com/products/1-detail-2.jpg", "is_cover": false, "sort": 0 },
            { "id": 3, "image_url": "https://cdn.example.com/products/1-detail-3.jpg", "is_cover": false, "sort": 1 },
            { "id": 1, "image_url": "https://cdn.example.com/products/1-detail-1.jpg", "is_cover": true, "sort": 2 }
        ]
    }
}
```

---

## 7. 附录

> HTTP 状态码约定、分页参数规范等通用内容请参见 [API Design Conventions](api_design_conventions.md)。

### 管理端列表接口

管理员如需查看全部商品（含草稿和下架），可在商品列表接口基础上扩展 `status` 筛选参数。管理端专用接口将在后续版本补充。

### v0.2 计划

以下接口计划在后续版本实现：

- 商品搜索（全文搜索、标签）
- 商品排序（按价格、销量、时间）
- 商品评价
- 管理端独立列表接口（含草稿/下架筛选）
- 批量上传图片
