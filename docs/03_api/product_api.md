# Product API Design

> **Document Version:** v0.9
> **Module:** Product
> **Phase:** 4.1 Product Module
> **Status:** Draft — Schema, Models, Repository, Validator, and core Product Service slices implemented; API pending
>
> 本文档是 Product 模块 API 的正式设计规范。所有 Schema、Service、Repository 实现必须以此为准。
>
> **全局规范：** 本文档遵循 [API Design Conventions](api_design_conventions.md)。Response 信封、分页、枚举 `{value, label}` 模式、错误码等通用规则见该文档，本文不再赘述。
>
> 业务规则见 [Product Business Rules](../01_requirements/product_business_rules.md)。
>
> **当前实现：** 请求/查询、响应、四个 Product Model、Repository 和 Product Validator 均已实现。Product Service 已实现 Experience/Kit 创建、管理端/用户端查询、基础信息修改、逻辑删除、ExperienceOption、ProductImage 全生命周期、Kit 价格/库存修改及上架/下架状态流转，写入与审计具有同事务回滚测试。图片文件校验/存储、API Mapper 和全部路由仍待实现；本页端点当前不可调用。

---

## 1. Design Principles

| 原则 | 说明 |
|------|------|
| RESTful | Resource-Oriented：URL 表示资源，HTTP Method 表达操作 |
| Business-Action | 按业务行为划分接口，不按数据库字段划分 |
| User/Admin 分离 | 用户接口 `/products`，管理员接口 `/admin/products` |
| 类型独立创建 | 体验和套装创建流程不同，使用独立端点 |
| **Create 只创建主资源** | 创建接口仅负责 Product 主记录。关联资源（图片、Option）通过独立接口完成。Kit 的 price/stock 属于聚合根核心字段，创建时一并接收 |
| **原则统一，字段按需适配** | Experience 和 Kit 共享 Draft、独立图片、上架校验等原则，但业务模型不同，Create Request 不强行为"统一"而统一 |
| **Create → Edit 流程** | 创建 Draft 后前端应立即进入编辑页，而非返回列表。用户感知为"创建商品"，技术实现为多步 API 调用 |

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
| product_type | `{value, label}` | `{ "value": "experience", "label": "拼豆体验" }`，前后端统一格式 |
| description | string/null | 商品描述（仅详情返回；Admin Draft 可为 `null`） |
| status | `{value, label}` | 仅管理端与状态变更响应返回 |
| cover_image | string/null | 封面图 URL（从 images 派生；Admin Draft 可为 `null`） |
| display_price | string/null | 列表展示价；用户列表必有值，Admin Draft 体验商品可为 `null` |
| options | array | **体验商品返回**，Option 列表 |
| images | array | 图片列表（仅详情返回） |
| price | string | **套装详情返回**，固定两位小数 |
| stock | int | **套装详情返回**，当前库存 |
| available | boolean | **用户端套装详情返回**，必须等于 `stock > 0` |
| created_at | datetime | 创建时间（仅 Admin Detail 返回） |
| updated_at | datetime | 更新时间（Admin List / Detail 和基本信息修改响应返回） |
| is_deleted | boolean | 仅管理列表和管理详情返回，用户端永不返回 |

### 2.2 ExperienceOption

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | Option ID |
| duration | object | `{ "value": 60, "label": "1小时" }` |
| participants | object | `{ "value": 2, "label": "2人" }` |
| day_type | object | `{ "value": "weekday", "label": "工作日" }` |
| price | string | 该配置价格（`"299.00"`），0 < Price ≤ 99999 |
| images | array | 该 Option 的专属图片列表。Online 商品每个 Option 至少 1 张图；无图仅出现在 draft/offline |

> Option 通过 `is_deleted` 实现逻辑删除。正常查询自动过滤已删除 Option。同一 Product 的 `(duration, participants, day_type)` 在全历史范围内唯一；再次 POST 相同的已删除组合时恢复原 Option ID，而不是插入第二条记录。

> **枚举字段统一使用 `{value, label}` 格式**（见 [API Design Conventions §9.4](api_design_conventions.md#94-枚举值--valuelabel-模式)）。
> Duration 和 Participants 是开放的正整数值，不是固定枚举。60 / 120 / 540 分钟与 1 / 2 人只是当前常用值；180 分钟、3 人等未来值无需新增 Enum。Service 层负责生成 label。

### 2.3 Kit

| 字段 | 类型 | 说明 |
|------|------|------|
| price | string | 套装售价（`"599.00"`） |
| stock | int | 当前库存 |

> Kit 使用 `product_kits` 表，逻辑删除跟随 Product。无独立 `sold_count` 字段——累计销量由订单模块统计。

### 2.4 Image

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 图片 ID |
| image_url | string | 图片 URL |
| is_cover | boolean | 是否封面图（仅 Product 公共图有效） |
| sort | int | 排序序号 |

> ProductImage 通过 `is_deleted` 实现逻辑删除。
> `experience_option_id` 是数据库内部关联字段：`NULL` 表示 Product 公共图，非 `NULL` 表示 Option 专属图；所有 Image Out Schema 都不返回该字段。

### 2.5 Schema Map

**请求与查询（`app/schemas/product.py`）**

| 场景 | Schema |
|------|--------|
| 创建体验 / 套装商品 | `ExperienceProductCreate` / `KitProductCreate` |
| 修改基本信息 | `ProductUpdate` |
| 新增 / 修改 Option | `ExperienceOptionCreate` / `ExperienceOptionUpdate` |
| 修改图片排序或封面 | `ProductImageUpdate` |
| 修改套装价格 / 库存 | `KitPriceUpdate` / `KitStockUpdate` |
| 用户 / 管理列表查询 | `ProductListQuery` / `AdminProductListQuery` |

**响应（`app/schemas/product_response.py`）**

| 场景 | Schema |
|------|--------|
| 用户 / 管理列表项 | `ProductListItemOut` / `AdminProductListItemOut` |
| 用户体验 / 套装详情 | `ExperienceProductDetailOut` / `KitProductDetailOut` |
| 管理体验 / 套装详情 | `AdminExperienceProductDetailOut` / `AdminKitProductDetailOut` |
| 创建体验 / 套装商品 | `ExperienceProductCreateOut` / `KitProductCreateOut` |
| 修改基本信息 | `ProductBasicInfoOut` |
| 上架 / 下架 | `ProductOnlineOut` / `ProductOfflineOut` |
| 逻辑删除 Product / Option / Image | `DeletedResourceOut` |
| 新增 / 修改 Option | `ExperienceOptionOut` / `ExperienceOptionBaseOut` |
| Product 公共图 / Option 图 | `ProductImageOut` / `OptionImageOut` |
| 修改套装价格 / 库存 | `KitPriceOut` / `KitStockOut` |

分页不重复定义模块专属外壳，统一使用 `Page[ProductListItemOut]` 或 `Page[AdminProductListItemOut]`。

### 2.6 Schema Boundary Rules

- 所有 JSON 写请求使用 `extra="forbid"`；未知字段、客户端试图提交的只读字段或拼写错误字段统一触发 HTTP 422，不静默忽略。
- JSON Body 中的 `stock`、`duration_minutes`、`participants`、`sort` 只接受真正的整数；拒绝 boolean、float 和数字字符串。Query 中的分页参数继续遵循全局 `PageParams` 规则。
- 请求金额必须是普通十进制字符串，例如 `"599"`、`"599.0"`、`"599.00"`；拒绝 JSON number、指数形式和超过两位小数的输入。Schema 内部转换为 `Decimal`，不使用 float，也不静默四舍五入。
- 响应金额在进入 Out Schema 前必须已经是 `Decimal`，JSON 固定序列化为两位小数字符串。
- PATCH 空对象统一拒绝。字段“未提交”与“显式提交 `null`”语义不同，Service 必须使用 `model_dump(exclude_unset=True)` 保留这个区别。
- Product `name=null` 拒绝；`description=null`、空字符串或纯空白表示清空。Option 和 Image PATCH 中显式 `null` 均拒绝。
- 用户端 Out Schema 是严格的已上架完整形状；管理端 Out Schema 允许 Draft 的空图片、空 Option 和空维度。Out Schema 只输出声明字段，防止内部关联、删除标记或类型专属字段跨接口泄漏。

> **API 集成检查项：** 当前 Schema 测试直接验证 Pydantic 模型。接入 FastAPI 路由时必须补充端点集成测试，并确认 `RequestValidationError` 被转换为全局 `{code, message, data}` 信封；该横切处理不属于 Product Schema 本身。

---

## 3. Error Codes

### 3.1 格式

```json
{
    "code": 40911,
    "message": "Experience option already exists",
    "data": {
        "duration_minutes": 120,
        "participants": 2,
        "day_type": "holiday"
    }
}
```

| 字段 | 说明 |
|------|------|
| HTTP Status | 协议语义（404/409/422） |
| `code` | 业务错误码，精确区分原因 |
| `message` | 给人看 |
| `data` | 可选，补充上下文 |

### 3.2 产品错误码

**资源不存在（404xx）—— HTTP 404**

| code | 常量 | 说明 |
|------|------|------|
| 40401 | `PRODUCT_NOT_FOUND` | 商品不存在 |
| 40402 | `OPTION_NOT_FOUND` | Option 不存在 |
| 40403 | `PRODUCT_IMAGE_NOT_FOUND` | 图片不存在 |
| 40404 | `PRODUCT_KIT_NOT_FOUND` | 套装配置不存在 |

**类型错误（400xx）—— HTTP 400**

| code | 常量 | 说明 |
|------|------|------|
| 40001 | `PRODUCT_TYPE_MISMATCH` | 商品类型与此操作不匹配 |

```json
{
    "code": 40001,
    "message": "Product type does not match this operation",
    "data": { "expected": "kit", "actual": "experience" }
}
```

**状态冲突（409xx）—— HTTP 409**

| code | 常量 | 说明 |
|------|------|------|
| 40901 | `PRODUCT_ALREADY_ONLINE` | 商品已上架 |
| 40902 | `PRODUCT_ALREADY_OFFLINE` | 商品已下架 |
| 40903 | `PRODUCT_IS_DELETED` | 商品已删除 |
| 40904 | `PRODUCT_MUST_BE_OFFLINE_BEFORE_DELETE` | online 商品需先下架才能删除 |
| 40905 | `ONLINE_PRODUCT_CANNOT_BE_MODIFIED` | online 商品不可修改 |
| 40911 | `OPTION_ALREADY_EXISTS` | 相同有效 Option 配置已存在，或 PATCH 目标组合已被其他记录占用 |
| 40912 | `OPTION_ALREADY_DELETED` | Option 已删除 |

**上架完整性（422xx）—— HTTP 422**

| code | 常量 | 说明 |
|------|------|------|
| 42201 | `PRODUCT_NOT_READY_FOR_ONLINE` | 商品未满足上架条件 |

```json
{
    "code": 42201,
    "message": "Product is not ready to go online",
    "data": {
        "issues": [
            "product description is required",
            "product cover image is required",
            "option 11 has no image"
        ]
    }
}
```

`42201` 的响应契约固定为：HTTP status 必须是 `422`；`message` 必须精确为 `Product is not ready to go online`；`data` 必须精确包含一个 `issues` 字段；`issues` 必须是非空数组且每项为非空英文字符串。Validator 一次收集全部缺项，不在第一项失败时停止，也不为各检查项拆分错误码。

检查条件、精确 issue 字符串与稳定排序以 [Product Business Rules §8.5](../01_requirements/product_business_rules.md#85-online-validation上架校验) 为唯一权威清单；API 必须原样输出，不得临时翻译或改写。通用异常语义由 `UnprocessableEntityException` 表达，Product 命名异常 `ProductNotReadyForOnline` 固定 `42201`、上述 message 和 `data.issues` 结构。异常中间件不得根据业务错误码号段推断 HTTP 状态。

**文件与动作业务校验**

| code | 常量 | 说明 |
|------|------|------|
| 42221 | `INVALID_IMAGE_FILE` | 图片文件无效 |
| 40021 | `OPTION_IMAGE_CANNOT_BE_COVER` | Option 图片不能设为封面 |

> 写接口收到的价格、库存、时长、人数、日期类型和请求形状由 Pydantic/FastAPI 静态校验，统一使用全局 HTTP 422 参数校验响应，不再分配 Product 专属的 42211–42215。上架时，Validator 对已加载聚合快照再次检查价格、库存及关联完整性；此时发现的缺项统一使用 `42201`。`42221` 保留给文件内容、大小和 MIME 等上传校验。

### 3.3 Error Code Mapping

| API | 可能业务错误 |
|-----|------------|
| `GET /products` | 无（空列表正常返回） |
| `GET /products/experience/{id}` | 40401 |
| `GET /products/kit/{id}` | 40401 |
| `POST /admin/products/experience` | Schema 校验 |
| `POST /admin/products/kit` | Schema 校验 |
| `PATCH /admin/products/{id}` | 40401, 40903, 40905 |
| `PATCH /admin/products/{id}/online` | 40401, 40901, 40903, 42201 |
| `PATCH /admin/products/{id}/offline` | 40401, 40902, 40903 |
| `DELETE /admin/products/{id}` | 40401, 40903, 40904 |
| `POST /admin/products/experience/{id}/options` | 40401, 40001, 40903, 40905, 40911 |
| `PATCH /admin/options/{id}` | 40402, 40912, 40905, 40911 |
| `DELETE /admin/options/{id}` | 40402, 40912, 40905 |
| `POST /admin/products/{id}/images` | 40401, 40903, 40905, 42221 |
| `POST /admin/options/{id}/images` | 40402, 40912, 40905, 42221 |
| `PATCH /admin/product-images/{id}` | 40403, 40905, 40021 |
| `DELETE /admin/product-images/{id}` | 40403, 40905 |
| `PATCH /admin/products/kit/{id}/price` | 40401, 40404, 40001, 40903, 40905 |
| `PATCH /admin/products/kit/{id}/stock` | 40401, 40404, 40001, 40903, 40905 |
| `GET /admin/products/{id}/audit-logs` | 40401 |

### 3.4 规则补充

**用户端类型不匹配统一返回 404：**

```
GET /products/experience/5  → Product 5 实际是 Kit → 404（不暴露内部类型信息）
```

**管理员端类型不匹配返回 40001：**

```
PATCH /admin/products/kit/5/price → Product 5 实际是 Experience → 40001
```

**online 写操作统一使用 40905：** `ONLINE_PRODUCT_CANNOT_BE_MODIFIED` 覆盖所有"线上商品不可修改"场景（修改信息、修改 Option、上传图片、改价、改库存），不逐场景造独立错误码。

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
| PATCH | /admin/products/{id} | 编辑商品基本信息（name, description） |
| DELETE | /admin/products/{id} | 逻辑删除 |

**状态管理**

| Method | URI | 说明 |
|--------|-----|------|
| PATCH | /admin/products/{id}/online | 上架（Service 按 product_type 执行不同校验） |
| PATCH | /admin/products/{id}/offline | 下架 |

**体验配置（Option）—— 仅 Experience**

| Method | URI | 说明 |
|--------|-----|------|
| POST | /admin/products/experience/{id}/options | 新增 Option；命中已删除相同组合时恢复原记录 |
| PATCH | /admin/options/{option_id} | 修改 Option |
| DELETE | /admin/options/{option_id} | 删除 Option |

**图片管理**

| Method | URI | 说明 |
|--------|-----|------|
| POST | /admin/products/{id}/images | 上传 Product 公共图片 |
| POST | /admin/options/{option_id}/images | 上传 Option 专属图片 |
| PATCH | /admin/product-images/{image_id} | 修改图片排序/封面 |
| DELETE | /admin/product-images/{image_id} | 删除图片 |

**套装管理 —— 仅 Kit**

| Method | URI | 说明 |
|--------|-----|------|
| PATCH | /admin/products/kit/{id}/price | 修改价格 |
| PATCH | /admin/products/kit/{id}/stock | 修改库存 |

**审计**

| Method | URI | 说明 |
|--------|-----|------|
| GET | /admin/products/{id}/audit-logs | 商品操作历史 |

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
            ↑         │
            └─────────┘
             (re-online)
```

| 流转 | 触发 | 校验 |
|------|------|------|
| draft → online | `PATCH .../online` | ProductValidator 完整校验 |
| online → offline | `PATCH .../offline` | — |
| offline → online | `PATCH .../online` | 保持原 Product ID |

> 无 `online → draft` 流转。删除逻辑独立（`is_deleted = true`），不属于 status 枚举。

### 5.2 Constraints

| 规则 | 说明 |
|------|------|
| product_type 不可修改 | 创建后不可变更 |
| Draft 允许无 Option | 先创建商品，再逐步添加配置 |
| Online 至少一个 Option | 上线校验 |
| Option 唯一性 | 同一 Product 内 (duration, participants, day_type) 全历史唯一；POST 命中已删除组合时恢复原记录 |
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

> **Service 边界：** `list_online_products()` 固定向 Repository 传入 `status=online`、`include_deleted=false`、`search_description=true` 并返回 `Page[Product]`。`cover_image`、`display_price` 和 Enum label 由 API Mapper 从预加载聚合计算，不在 Repository 或查询 Service 中生成。

> **实现状态：** 用户列表查询 Service 已实现；API Mapper、Out Schema 调用和路由仍待实现。

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| product_type | string | 否 | — | `"experience"` / `"kit"` |
| keyword | string | 否 | — | 搜索名称 / 描述 |

**成功响应**

**Response Schema：** `Page[ProductListItemOut]`

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
                "cover_image": "https://cdn.example.com/products/1-cover.jpg",
                "display_price": "299.00"
            },
            {
                "id": 2,
                "name": "拼豆套装",
                "product_type": { "value": "kit", "label": "拼豆套装" },
                "cover_image": "https://cdn.example.com/products/2-cover.jpg",
                "display_price": "599.00"
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
| `display_price` | 展示价格。体验商品为最低 Option 价格，套装商品为固定售价。前端据 `product_type` 自行决定加"起"后缀 |
| 不返回 | `price_label`、`created_at`（列表不需要） |

> 前端根据 `product_type.value` 决定跳转目标：
> - `"experience"` → `/products/experience/{id}`
> - `"kit"` → `/products/kit/{id}`

---

### 6.2 拼豆体验详情

```
GET /api/v1/products/experience/{id}
```

仅返回 `product_type = "experience"`、`status = "online"`、`is_deleted = false` 的商品。

**可能的业务错误：** `40401`（商品不存在或类型不匹配，统一返回 404）

未上线或已删除商品也统一返回 `40401`。`get_online_product_detail(id, product_type=experience)` 返回已预加载 Product 聚合，API Mapper 负责 dimensions、Option/图片 DTO 和 label。

> **实现状态：** 用户详情查询 Service 已实现，Experience/Kit 共用显式 `product_type` 隔离；API Mapper 与路由仍待实现。

**Response Schema：** `ExperienceProductDetailOut` — 不含 `price`、`stock`、`status`、`is_deleted` 和时间字段。

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
        "dimensions": {
            "durations": [
                { "value": 60, "label": "1小时" },
                { "value": 120, "label": "2小时" },
                { "value": 540, "label": "全天" }
            ],
            "participants": [
                { "value": 1, "label": "1人" }
            ],
            "day_types": [
                { "value": "weekday", "label": "工作日" }
            ]
        },
        "options": [
            {
                "id": 11,
                "duration": { "value": 60, "label": "1小时" },
                "participants": { "value": 1, "label": "1人" },
                "day_type": { "value": "weekday", "label": "工作日" },
                "price": "299.00",
                "images": [
                    { "id": 20, "image_url": "https://cdn.example.com/option-11-1.jpg", "sort": 0 }
                ]
            },
            {
                "id": 12,
                "duration": { "value": 120, "label": "2小时" },
                "participants": { "value": 2, "label": "2人" },
                "day_type": { "value": "holiday", "label": "节假日" },
                "price": "699.00",
                "images": [
                    { "id": 21, "image_url": "https://cdn.example.com/option-12-1.jpg", "sort": 0 }
                ]
            }
        ],
        "images": [
            { "id": 1, "image_url": "https://cdn.example.com/products/1-cover.jpg", "is_cover": true, "sort": 0 }
        ]
    }
}
```

| 字段 | 说明 |
|------|------|
| `dimensions` | 由当前有效 Option 动态计算。前端用三个维度分别生成选择控件 |
| `options` | 每个 Option 至少 1 张专属图片（Online 校验保证），无 `images: []` |

> 不返回 `status`、`is_deleted`、`created_at`、`updated_at`。图片按 `sort ASC, id ASC` 排序。

---

### 6.3 拼豆套装详情

```
GET /api/v1/products/kit/{id}
```

仅返回 `product_type = "kit"`、`status = "online"`、`is_deleted = false` 的商品。

**可能的业务错误：** `40401`（商品不存在或类型不匹配，统一返回 404）

未上线或已删除商品也统一返回 `40401`。Service 不计算 `available`；API Mapper 根据已加载 `product.kit.stock > 0` 生成。

**Response Schema：** `KitProductDetailOut` — 不含 `options`、`status`、`is_deleted`、`sold_count`、时间字段。

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

统一列表，默认返回全部状态（draft / online / offline）且未删除的商品；`include_deleted=true` 时同时返回逻辑删除记录。仅返回摘要信息——完整数据见详情接口。

> **Service 边界：** `list_admin_products()` 原样编排分页和筛选条件，keyword 只搜索名称，并返回 `Page[Product]`。列表展示派生字段由 API Mapper 负责。

> **实现状态：** 管理列表查询 Service 已实现；API Mapper 与路由仍待实现。

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| product_type | string | 否 | — | `"experience"` / `"kit"` |
| status | string | 否 | — | `"draft"` / `"online"` / `"offline"` |
| include_deleted | boolean | 否 | false | 仅接受 `true` / `false`；`true` = 包含已删除商品 |
| keyword | string | 否 | — | 搜索名称 |

**成功响应**

**Response Schema：** `Page[AdminProductListItemOut]`

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
                "updated_at": "2026-08-04T10:30:00Z",
                "is_deleted": false
            },
            {
                "id": 2,
                "name": "拼豆套装",
                "product_type": { "value": "kit", "label": "拼豆套装" },
                "status": { "value": "draft", "label": "草稿" },
                "cover_image": null,
                "display_price": null,
                "updated_at": "2026-08-04T10:30:00Z",
                "is_deleted": false
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
| `is_deleted` | 始终返回。默认查询为 `false`；`include_deleted=true` 时用于区分历史删除记录 |
| 不返回 | `description`、`images`、`options`、`stock`、`created_at`（详情接口获取） |

---

### 7.2 体验商品详情（管理）

```
GET /api/v1/admin/products/experience/{id}
```

仅返回 `product_type = "experience"` 的商品。draft / online / offline 和逻辑删除记录均可供管理员查看；响应始终显式返回 `is_deleted`。

管理端详情 Service 使用 `get_product_detail(id, include_deleted=true)`；不存在或实际 ProductType 不匹配均返回 `40401`，不另造类型错误。Kit 管理详情遵循相同规则。

> **实现状态：** 管理详情查询 Service 已实现，包含逻辑删除聚合；API Mapper 与路由仍待实现。

**成功响应**

**Response Schema：** `AdminExperienceProductDetailOut`

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
                "id": 11,
                "duration": { "value": 60, "label": "1小时" },
                "participants": { "value": 1, "label": "1人" },
                "day_type": { "value": "weekday", "label": "工作日" },
                "price": "299.00",
                "images": [
                    { "id": 20, "image_url": "https://cdn.example.com/option-11-1.jpg", "sort": 0 },
                    { "id": 21, "image_url": "https://cdn.example.com/option-11-2.jpg", "sort": 10 }
                ]
            },
            {
                "id": 12,
                "duration": { "value": 120, "label": "2小时" },
                "participants": { "value": 2, "label": "2人" },
                "day_type": { "value": "holiday", "label": "节假日" },
                "price": "699.00",
                "images": []
            }
        ],
        "created_at": "2026-08-04T10:30:00Z",
        "updated_at": "2026-08-04T10:30:00Z",
        "is_deleted": false
    }
}
```

| 字段 | 说明 |
|------|------|
| `dimensions` | 由 options 动态计算——当前已有哪些时长/人数/日期类型可选，方便管理端 UI 生成筛选 |
| `options` | 完整列表，含所有 Option。`price` 使用字符串格式 |
| 与用户详情不同 | 管理员可查看 draft/offline/已删除记录；返回 `status`、`created_at`、`updated_at`、`is_deleted` |

---

### 7.3 套装商品详情（管理）

```
GET /api/v1/admin/products/kit/{id}
```

仅返回 `product_type = "kit"` 的商品。逻辑删除记录仍可供管理员查看；响应始终显式返回 `is_deleted`。

**成功响应**

**Response Schema：** `AdminKitProductDetailOut`

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
        "created_at": "2026-08-04T10:30:00Z",
        "updated_at": "2026-08-04T10:30:00Z",
        "is_deleted": false
    }
}
```

| 与用户详情不同 | 管理员可查看 draft/offline/已删除记录；返回 `status`、`created_at`、`updated_at`、`is_deleted`；无 `available`（管理员关心原始数据） |

---

### 7.4 创建体验商品

```
POST /api/v1/admin/products/experience
```

创建体验商品草稿。接口路径已明确 `product_type = experience`，后端自动设置 `status = draft`。

**可能的业务错误：** Schema 校验（name 非空/长度）。无其他业务错误——创建始终成功。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 商品名称。trim 后 1–100 字符。允许重名 |
| description | string | 否 | 商品描述，最大 2000 字符。Draft 阶段可选 |

**不接受（Schema 统一校验拒绝）：**

| 字段 | 原因 |
|------|------|
| `product_type` | URL 已明确 `experience`，Body 不得重复表达 |
| `status` | 创建统一为 `draft`，不允许绕过上架流程 |
| `options` | Option 通过独立接口 `POST /admin/products/experience/{id}/options` 创建 |
| `images` | 图片通过独立接口上传 |
| `price` | Experience Product 本身无价格，价格属于 `ExperienceOption.price` |
| `cover_image` | 封面属于 ProductImage，通过图片管理接口设置 |

**后端自动生成：**

| 字段 | 值 |
|------|-----|
| `product_type` | `"experience"` |
| `status` | `"draft"` |
| `is_deleted` | `false` |

**请求示例（最小）**

```json
{
    "name": "拼豆体验"
}
```

**请求示例（含描述）**

```json
{
    "name": "拼豆体验",
    "description": "适合个人及双人参与的拼豆体验"
}
```

**成功响应** — HTTP 201

**Response Schema：** `ExperienceProductCreateOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "拼豆体验",
        "product_type": { "value": "experience", "label": "拼豆体验" },
        "status": { "value": "draft", "label": "草稿" }
    }
}
```

> **Create Validation ≠ Online Validation。** 创建时仅校验 `name` 非空和长度；`description`、`images`、`options` 可在 Draft 阶段逐步完善。Online 时才执行完整校验（见 [§7.8 上架](#78-上架)）。

**Service 事务：** `create_experience_product()` 在同一事务连接内创建固定为 Experience/Draft/未删除的 Product，并写 `CREATE_PRODUCT` 审计；任一步失败全部回滚。Service 返回 Product，API 使用 `ExperienceProductCreateOut` 序列化。创建不调用 Validator。

> **实现状态：** Experience 创建 Service 已实现并有真实事务回滚测试；API 路由和响应序列化仍待实现。

**创建后工作流：**

```
POST /admin/products/experience  →  { id: 1 }
  │
  ├─ POST /admin/products/1/images                 （上传 Product 公共图片）
  ├─ POST /admin/products/experience/1/options     （新增 Option → option_id: 15）
  ├─ POST /admin/options/15/images                 （上传 Option 专属图片）
  │
  └─ PATCH /admin/products/1/online               （上架）

---

### 7.5 创建套装商品

```
POST /api/v1/admin/products/kit
```

创建套装商品草稿。与 Experience 不同，Kit 的 `price` 和 `stock` 属于聚合根核心字段，创建时一并接收。

**可能的业务错误：** 无。`price` / `stock` 的类型与范围错误统一由 `KitProductCreate` 触发 HTTP 422 Schema 校验。Experience 和 Kit 共享 Draft、独立图片、上架校验等原则，但业务模型不同——Kit 无 Option，price/stock 直接属于 Kit 自身。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 商品名称。trim 后 1–100 字符。允许重名 |
| description | string | 否 | 商品描述，最大 2000 字符。Draft 阶段可选 |
| price | string | 是 | `"599.00"`，0 < Price ≤ 99999。Kit 核心字段 |
| stock | int | 否 | 初始库存，默认 0，>= 0 |

| Experience Create | Kit Create | 原因 |
|-------------------|------------|------|
| ❌ price | ✅ price 必填 | Kit 无 Option，price 是 Kit 聚合根核心字段 |
| ❌ stock | ✅ stock 可选（默认 0） | 同上 |
| ❌ images | ❌ images | 统一：图片独立上传 |
| ❌ options | N/A | Experience 专有 |

**后端自动生成：**

| 字段 | 值 |
|------|-----|
| `product_type` | `"kit"` |
| `status` | `"draft"` |
| `is_deleted` | `false` |
| `stock` | `0`（未传时） |

**请求示例**

```json
{
    "name": "新手拼豆套装",
    "description": "适合初学者使用",
    "price": "599.00",
    "stock": 100
}
```

**最小合法请求**

```json
{
    "name": "新手拼豆套装",
    "price": "599.00"
}
```

**成功响应** — HTTP 201

**Response Schema：** `KitProductCreateOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 2,
        "name": "新手拼豆套装",
        "product_type": { "value": "kit", "label": "拼豆套装" },
        "status": { "value": "draft", "label": "草稿" }
    }
}
```

**Service 事务：** `create_kit_product()` 在同一事务连接内依次创建固定为 Kit/Draft/未删除的 Product、必需的 ProductKit 扩展记录和 `CREATE_PRODUCT` 审计；任一步失败三者全部回滚。Service 返回 Product，API 使用 `KitProductCreateOut` 序列化。`stock` 未提交时由 Schema/常量提供 0。

> **实现状态：** Kit 聚合创建 Service 已实现并有 Product/ProductKit/审计真实原子性测试；API 路由和响应序列化仍待实现。

---

### 7.6 编辑商品基本信息

```
PATCH /api/v1/admin/products/{id}
```

统一接口，同时适用于体验和套装。仅修改 `name` 和 `description`（至少传一个字段）。

**可能的业务错误：** `40401`, `40903`, `40905`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Product 不存在 | `ProductNotFound` | 40401 | `Product not found` | 404 |
| Product 已逻辑删除 | `ProductIsDeleted` | 40903 | `Product is deleted` | 409 |
| Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 否 | 商品名称。trim 后 1–100 字符，允许重名 |
| description | string/null | 否 | 商品描述，最大 2000 字符。`null`、空字符串或纯空白表示清空 |

**PATCH 语义：**

- `{}` 拒绝，必须至少提交一个允许修改的字段。
- `name` 未提交表示不修改；显式 `name: null` 拒绝。
- `description` 未提交表示不修改；显式 `null`、`""` 或纯空白表示清空为数据库 `NULL`。
- 未知字段统一拒绝。Service 必须使用 `payload.model_dump(exclude_unset=True)`，不得把“未提交”误当成 `null`。

API 将上述显式字段映射传给 `ProductService.update_product(..., updates=...)`。Service 再执行非空字段白名单校验，避免内部调用方绕过独立状态/删除接口；成功更新与 `UPDATE_PRODUCT` 审计共享同一事务连接，不调用 ProductValidator。

**禁止修改：**

| 字段 | 独立接口 |
|------|----------|
| `product_type` | 创建后不可变 |
| `status` | `PATCH .../online` / `PATCH .../offline` |
| `price` | `PATCH /admin/products/kit/{id}/price` |
| `stock` | `PATCH /admin/products/kit/{id}/stock` |
| `images` | 图片管理接口 |
| `options` | Option CRUD 接口 |
| `is_deleted` | `DELETE /admin/products/{id}` |

**请求示例**

```json
{ "name": "新版拼豆体验" }
```

```json
{ "description": "" }
```

```json
{ "name": "新版拼豆体验", "description": "新的介绍" }
```

**成功响应**

**Response Schema：** `ProductBasicInfoOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "name": "新版拼豆体验",
        "description": "新的介绍",
        "updated_at": "2026-08-04T10:30:00Z"
    }
}
```

> **实现状态：** 基础信息修改 Service 与命名异常已实现，并有字段白名单、显式 null、Draft/Offline 成功、冲突短路和审计失败回滚测试。API 路由与响应序列化仍待实现。

---

### 7.7 逻辑删除

```
DELETE /api/v1/admin/products/{id}
```

**Request Body：无。** 执行逻辑删除（`is_deleted = true`），不做物理删除。

**可能的业务错误：** `40401`, `40903`, `40904`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Product 不存在 | `ProductNotFound` | 40401 | `Product not found` | 404 |
| Product 已逻辑删除 | `ProductIsDeleted` | 40903 | `Product is deleted` | 409 |
| Product 为 Online | `ProductMustBeOfflineBeforeDelete` | 40904 | `Product must be offline before deletion` | 409 |

**状态流转：**

| 当前状态 | 操作 | 结果 |
|----------|------|------|
| `draft` | → deleted | ✅ |
| `offline` | → deleted | ✅（先下架再删除） |
| `online` | → deleted | ❌ 必须先下架 |
| `is_deleted = true` | → deleted | ❌ 已删除 |

**Service 执行流程：**

```
1. 查找 Product（不存在 → 40401）
2. 检查 is_deleted（已删除 → 拒绝）
3. 检查 status（online → 拒绝，40904 PRODUCT_MUST_BE_OFFLINE_BEFORE_DELETE）
4. Repository 更新 is_deleted = true（保持原 status）
5. 使用同一事务连接写入 Audit Log（action = DELETE_PRODUCT）
```

**关联数据处理：** Product 逻辑删除后，其关联的 `ExperienceOption`、`ProductKit`、`ProductImage` 不删除不修改，保留用于历史订单和审计追溯。正常业务查询通过 `Product.is_deleted` 过滤。

**成功响应**

**Response Schema：** `DeletedResourceOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "is_deleted": true
    }
}
```

**Audit：** `action = DELETE_PRODUCT`。

> **实现状态：** Product 逻辑删除 Service 与命名异常已实现，并有 Draft/Offline 成功、状态/关联记录保留、冲突优先级和审计失败回滚测试。API 路由与响应序列化仍待实现。

---

### 7.8 上架

```
PATCH /api/v1/admin/products/{id}/online
```

**Request Body：无。** URL 已明确表达业务动作——管理员执行"上架商品"操作。

**可能的业务错误：** `40401`, `40901`, `40903`, `42201`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Product 不存在 | `ProductNotFound` | `40401` | `Product not found` | 404 |
| Product 已逻辑删除 | `ProductIsDeleted` | `40903` | `Product is deleted` | 409 |
| Product 已经 Online | `ProductAlreadyOnline` | `40901` | `Product is already online` | 409 |
| 聚合不满足上架条件 | `ProductNotReadyForOnline` | `42201` | `Product is not ready to go online` | 422 |

**状态流转：**

| 当前状态 | 操作 | 结果 |
|----------|------|------|
| `draft` | → online | ✅ 执行校验，通过后上架 |
| `offline` | → online | ✅ 执行校验，通过后重新上架 |
| `online` | → online | ❌ 商品已在线，无业务意义 |
| `is_deleted = true` | → online | ❌ 已删除商品不可上架 |

**Service 执行流程：**

```
1. 使用 ProductRepository.get_product_detail(product_id, include_deleted=True) 查找并预加载 Product 聚合（不存在 → 40401）
2. 检查 is_deleted（已删除 → 拒绝）
3. 检查当前 status（online → 拒绝，PRODUCT_ALREADY_ONLINE）
4. ProductValidator.validate_before_online(product)
   ├─ product_type = "experience" → 收集公共规则 + Experience 规则
   └─ product_type = "kit"        → 收集公共规则 + Kit 规则
5. 全部通过 → 开启事务，由 Repository 使用当前事务连接更新 status = "online"
6. 使用同一事务连接写入 Audit Log（action = ONLINE_PRODUCT）
7. 事务提交后返回已更新 Product，API 使用 ProductOnlineOut 序列化
```

步骤 1 必须预加载 `kit`、有效 Option、有效 Product 公共图片，以及每个有效 Option 的有效专属图片；不得把仅包含 Product 主表的 `get_product_by_id()` 结果传给 Validator。删除状态优先于 ProductStatus 判断。步骤 4 是同步纯计算调用，不使用 `await`。未预加载关系触发的 `NoValuesFetched`、未知 ProductType 等异常属于内部编程错误，不得转换为 `42201`。

步骤 5 和 6 必须原子提交：`ProductRepository.update_product(..., using_db=connection)` 与 `AuditLogService.log(..., using_db=connection)` 使用同一个 `BaseDBAsyncClient`。任一步骤失败都回滚状态和审计。Validator 失败以及 `40401`、`40903`、`40901` 均发生在写事务前，不写状态、不写审计。Service 方法接收 `product_id`、`operator_id` 和 `ip_address`，返回更新后的 Product Model；权限依赖和 `ProductOnlineOut` 序列化分别属于 API 层。

**Experience 检查项：**

| # | 检查项 | 不通过 code |
|---|--------|------------|
| ① | 商品名称不为空 | — |
| ② | 商品描述不为空 | — |
| ③ | 有封面图（`is_cover = true` 且 `experience_option_id IS NULL`） | — |
| ④ | Product 公共图片 ≥ 1 | — |
| ⑤ | Option ≥ 1 | — |
| ⑥ | 每个 Option price > 0 | — |
| ⑦ | 每个 Option 至少一张专属图片 | — |

> 以上检查项统一合并为 `42201 PRODUCT_NOT_READY_FOR_ONLINE`，通过 `data.issues` 数组返回所有不通过的项。Option 配置唯一性在 Option 创建/修改流程中返回 `40911` 并由 DB UNIQUE 兜底，不属于上架 Validator。

**Kit 检查项：**

| # | 检查项 | 不通过 code |
|---|--------|------------|
| ① | 商品名称不为空 | — |
| ② | 商品描述不为空 | — |
| ③ | 有封面图 | — |
| ④ | 存在 ProductKit 扩展记录 | — |
| ⑤ | price > 0 且 ≤ 99999 | — |
| ⑥ | stock ≥ 0（stock = 0 允许上架，前端显示"暂时售罄"） | — |

> Kit 上架缺项统一合并为 `42201 PRODUCT_NOT_READY_FOR_ONLINE`，与 Experience 一致。ProductKit 缺失时只返回 `kit configuration is required`，不再追加价格或库存 issue。Kit 目前不额外要求“至少一张公共图片”；公共封面检查已经保证至少存在一张公共图片。

**成功响应**

**Response Schema：** `ProductOnlineOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "status": { "value": "online", "label": "已上架" }
    }
}
```

> 不返回完整 Product Detail。前端真正关心的是"上架成功了吗？现在状态是什么？"

**失败响应**

**HTTP Status：** `422 Unprocessable Entity`

```json
{
    "code": 42201,
    "message": "Product is not ready to go online",
    "data": {
        "issues": [
            "product description is required",
            "option 11 has no image"
        ]
    }
}
```

**Audit：** 仅校验通过后在状态更新的同一事务内写入（`action = ONLINE_PRODUCT`, `target_type = product`, `target_id = Product ID`）。校验失败、资源/状态冲突不写 Audit；状态更新或审计写入失败时整个事务回滚。

> **实现状态：** `ProductService.online_product()` 及共享 AuditLog `using_db` 事务透传已实现，并有 Mock 编排测试与真实 SQLite 事务回滚测试。FastAPI 路由、ADMIN+ 依赖接入和 `ProductOnlineOut` 响应序列化仍待实现。

---

### 7.9 下架

```
PATCH /api/v1/admin/products/{id}/offline
```

**Request Body：无。** URL 已明确表达业务动作——管理员执行"下架商品"操作。

**可能的业务错误：** `40401`, `40902`, `40903`

`draft` 和 `offline` 统一抛 `ProductAlreadyOffline`（`40902`, `Product is already offline`, HTTP 409）：两者都已不对外销售，不能重复执行下架。`is_deleted=true` 优先返回 `ProductIsDeleted`。

**状态流转：**

| 当前状态 | 操作 | 结果 |
|----------|------|------|
| `online` | → offline | ✅ 下架 |
| `draft` | → offline | ❌ 从未上架，无需下架 |
| `offline` | → offline | ❌ 已下架，无业务意义 |
| `is_deleted = true` | → offline | ❌ 已删除商品不可操作 |

**与 /online 不同：** 下架不执行完整性校验。下架本质是"停止对外销售"，不需要检查图片、Option、价格。

**Service 执行流程：**

```
1. 使用 ProductRepository.get_product_by_id(product_id, include_deleted=True) 查找 Product（不存在 → 40401）
2. 检查 is_deleted（已删除 → 拒绝）
3. 检查当前 status 必须为 online（draft / offline → 40902）
4. 开启事务，由 Repository 使用当前事务连接更新 status = "offline"
5. 使用同一事务连接写入 Audit Log（action = OFFLINE_PRODUCT）
6. 提交后返回更新后的 Product，API 使用 ProductOfflineOut 序列化
```

**成功响应**

**Response Schema：** `ProductOfflineOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "status": { "value": "offline", "label": "已下架" }
    }
}
```

**Audit：** 与状态更新在同一事务内写入（`action = OFFLINE_PRODUCT`, `target_type = product`）。资源/状态冲突不写 Audit；状态更新或审计失败时整体回滚。下架不调用 ProductValidator。

> **实现状态：** `ProductService.offline_product()` 已实现，并有 Draft/Offline 冲突、删除优先、不调用 Validator、同事务连接和真实审计失败回滚测试。FastAPI 路由、ADMIN+ 依赖和 `ProductOfflineOut` 序列化仍待实现。

---

### 7.10 新增 Option

```
POST /api/v1/admin/products/experience/{product_id}/options
```

为体验商品新增一条可售配置；如果相同组合已逻辑删除，则恢复原记录。图片通过独立接口上传（见 [§7.15 Option 专属图片上传](#715-option-专属图片上传)）。

**可能的业务错误：** `40401`, `40001`, `40903`, `40905`, `40911`。字段类型和范围错误统一为 HTTP 422 Schema 校验。

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Product 不存在 | `ProductNotFound` | 40401 | `Product not found` | 404 |
| Product 已删除 | `ProductIsDeleted` | 40903 | `Product is deleted` | 409 |
| Product 不是 Experience | `ProductTypeMismatch` | 40001 | `Product type does not match this operation` | 400 |
| Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |
| 有效组合已存在或并发 INSERT 冲突 | `ExperienceOptionAlreadyExists` | 40911 | `Experience option already exists` | 409 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| duration_minutes | int | 是 | 分钟数，> 0。当前常用：60 / 120 / 540。**不限定枚举**，未来允许 180、240 等 |
| participants | int | 是 | 人数，> 0。当前常用：1 / 2。未来允许 3、4 等 |
| day_type | string | 是 | `"weekday"` / `"holiday"` |
| price | string | 是 | `"699.00"`，0 < Price ≤ 99999 |

**Product 状态限制：**

| 状态 | 允许 | 原因 |
|------|------|------|
| `draft` | ✅ | 商品编辑中 |
| `offline` | ✅ | 已下架，可修改配置 |
| `online` | ❌ | 线上商品不建议直接新增配置。应：下架 → 新增 → 重新上架 |
| `is_deleted = true` | ❌ | 已删除 |

**类型校验：** 仅接受 `product_type = "experience"`。传入 Kit ID 必须失败。

**唯一性与恢复：** 同一 Product 下 `(duration_minutes, participants, day_type)` 在全历史范围内唯一，DB UNIQUE + Service 双重保护。Service 查询时必须包含逻辑删除记录：

| 查询结果 | 行为 | HTTP |
|----------|------|------|
| 不存在相同组合 | INSERT 新 Option | 201 |
| 存在且 `is_deleted = false` | 拒绝，`40911 OPTION_ALREADY_EXISTS` | 409 |
| 存在且 `is_deleted = true` | 恢复原记录：保持原 ID、更新价格、`is_deleted = false` | 200 |

恢复不是新建数据库记录，不物理删除旧 Option，也不复制第二条历史版本。原 Option 图片关联继续保留；历史订单通过订单项快照保持原配置和价格。

**Service 返回契约：** `ExperienceOptionCreationResult(option, restored)` 是不依赖 HTTP 的领域结果。`restored=false` 时 API 返回 201，`restored=true` 时返回 200。Service 在写入和审计之后、事务提交前通过 Repository 重载 Option 与有效专属图片，API 不需要补查数据库即可构造 `ExperienceOptionOut`。

Product 检查、全历史组合查询和状态冲突发生在写事务前。新建/恢复、对应审计与响应聚合重载共享一个事务连接；任一步失败整体回滚。Service 将唯一索引竞争导致的 `IntegrityError` 转换为稳定 `40911`，且不调用 ProductValidator。

**请求示例**

```json
{
    "duration_minutes": 120,
    "participants": 2,
    "day_type": "holiday",
    "price": "699.00"
}
```

**新建成功响应** — HTTP 201

**Response Schema：** `ExperienceOptionOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 11,
        "duration": { "value": 120, "label": "2小时" },
        "participants": { "value": 2, "label": "2人" },
        "day_type": { "value": "holiday", "label": "节假日" },
        "price": "699.00",
        "images": []
    }
}
```

> `images: []` 合理——真正新建的 Option 还没有图片。Draft / Offline 阶段允许；上架前再校验。

**恢复成功响应** — HTTP 200

**Response Schema：** 同样使用 `ExperienceOptionOut`。返回原 Option ID 和仍有效的原图片关联，价格为本次 POST 提交的新值。

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 11,
        "duration": { "value": 120, "label": "2小时" },
        "participants": { "value": 2, "label": "2人" },
        "day_type": { "value": "holiday", "label": "节假日" },
        "price": "799.00",
        "images": [
            { "id": 31, "image_url": "https://cdn.example.com/options/11/31.jpg", "sort": 0 }
        ]
    }
}
```

**Audit：** 新建记录 `CREATE_OPTION`；恢复记录 `RESTORE_OPTION`。当前 AuditLog 没有 metadata 列，恢复快照以紧凑 JSON 写入 `description`，包含 `option_id`、`before.price`、`after.price`，价格固定为两位小数字符串。

> **实现状态：** `ProductService.create_experience_option()`、`ProductTypeMismatch` 和 `ExperienceOptionAlreadyExists` 已实现，并有新建/恢复、状态与类型冲突、并发唯一约束翻译、图片保留、共享事务和真实审计失败回滚测试。FastAPI 路由、ADMIN+ 依赖与 `ExperienceOptionOut` 映射仍待实现。

**失败响应**

```json
{ "code": 40911, "message": "Experience option already exists", "data": { "duration_minutes": 120, "participants": 2, "day_type": "holiday" } }
```

---

### 7.11 前端协作：Option + 图片一次保存

**管理员感知：** 填写配置 + 上传图片 → 点击一个"保存"按钮。

**技术实现：** 前端串行调用两个 API，后端各自独立：

```
管理员点击【保存配置】
  │
  ├─ ① POST /admin/products/experience/1/options
  │     └─ 返回 { id: 15, ... }
  │
  └─ ② POST /admin/options/15/images
        └─ 上传图片文件

全部成功 → 提示"保存成功"
图片失败 → 提示"配置已保存，图片上传失败，请重试"
```

> **部分成功处理：** 新 Option 创建成功后图片上传失败，Option 保留（`images: []`）；恢复的 Option 继续保留原图片。管理员可以重新编辑并补充图片。这正是 Draft 机制的设计价值。

---

### 7.12 修改 Option

```
PATCH /api/v1/admin/options/{option_id}
```

修改 Option 的配置数据（不包含图片）。允许只修改部分字段。

**可能的业务错误：** `40402`, `40912`, `40905`, `40911`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Option 不存在或所属 Product 已删除 | `ExperienceOptionNotFound` | 40402 | `Experience option not found` | 404 |
| Option 已逻辑删除 | `ExperienceOptionAlreadyDeleted` | 40912 | `Experience option is already deleted` | 409 |
| 所属 Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |
| 最终组合被其他历史 Option 占用或并发唯一冲突 | `ExperienceOptionAlreadyExists` | 40911 | `Experience option already exists` | 409 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| duration_minutes | int | 否 | > 0 |
| participants | int | 否 | > 0 |
| day_type | string | 否 | `"weekday"` / `"holiday"` |
| price | string | 否 | `"799.00"`，0 < Price ≤ 99999 |

所有字段都可以缺失，但至少提交一个；任意字段显式传 `null` 均拒绝。Service 必须使用 `payload.model_dump(exclude_unset=True)` 执行部分更新。

API 将显式字段映射传给 `update_experience_option(..., updates=...)`。Service 再执行非空字段白名单校验，并将 API 字段 `duration_minutes` 映射为 Model/Repository 字段 `duration`；`product_id`、`is_deleted` 和其他内部字段不能借此接口修改。

**Product 状态限制：**

| 状态 | 允许 |
|------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 线上商品修改配置需先下架 |

**唯一性：** 修改后仍需保证同一 Product 下 `(duration_minutes, participants, day_type)` 不与任何其他记录重复，包括逻辑删除记录。若目标组合由已删除 Option 占用，返回 `40911`；管理员应通过新增 Option 接口恢复该记录，避免混淆两个 Option ID 的历史关联。

Service 使用当前 Option 和本次 PATCH 合并最终组合后再查全历史；查询命中当前 Option ID 不构成冲突。写入时数据库唯一索引发生竞争性 `IntegrityError` 也转换为同一 `40911`。

**请求示例**

```json
{ "price": "799.00" }
```

```json
{ "participants": 3 }
```

```json
{
    "duration_minutes": 180,
    "participants": 3,
    "day_type": "holiday",
    "price": "899.00"
}
```

**成功响应**

**Response Schema：** `ExperienceOptionBaseOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 11,
        "duration": { "value": 180, "label": "3小时" },
        "participants": { "value": 3, "label": "3人" },
        "day_type": { "value": "holiday", "label": "节假日" },
        "price": "899.00"
    }
}
```

> 修改后历史订单不受影响（订单保留价格快照）。图片通过独立 Image API 管理。

**Audit：** 维度发生 PATCH 时写 `UPDATE_OPTION`，description 保存 `option_id` 与三个维度的 before/after；价格字段发生 PATCH 时写 `UPDATE_PRICE`，description 保存 `option_id` 与价格 before/after。若同一请求同时提交维度和价格，按上述顺序写两条审计。Option 更新、审计和响应重载共享事务连接，任一步失败整体回滚。响应使用 `ExperienceOptionBaseOut`，不会输出重载 Option 上的图片关系。

> **实现状态：** `ProductService.update_experience_option()`、`ExperienceOptionNotFound` 和 `ExperienceOptionAlreadyDeleted` 已实现，并有 PATCH 合并、资源/状态冲突、全历史唯一性、单/双审计、图片保留和真实回滚测试。FastAPI 路由、ADMIN+ 依赖与响应映射仍待实现。

---

### 7.13 删除 Option

```
DELETE /api/v1/admin/options/{option_id}
```

**Request Body：无。** 执行逻辑删除（`is_deleted = true`），不做物理删除。保留图片关联和历史数据。

**可能的业务错误：** `40402`, `40912`, `40905`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Option 不存在或所属 Product 已删除 | `ExperienceOptionNotFound` | 40402 | `Experience option not found` | 404 |
| Option 已逻辑删除 | `ExperienceOptionAlreadyDeleted` | 40912 | `Experience option is already deleted` | 409 |
| 所属 Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |

**所属 Product 状态限制：**

| Product 状态 | 允许 |
|-------------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 线上商品不可直接删除配置。应先下架 |
| `is_deleted = true` | ❌ |

**最后一条 Option：** Draft / Offline 阶段允许删除最后一条 Option（`options = 0`），这不影响商品合法性。但 `PATCH .../online` 会因"没有有效 Option"被 Validator 拒绝。

**关联数据：** Option 逻辑删除后，其关联的 `ProductImage`（`experience_option_id` 指向该 Option）保留不动。正常查询自动过滤已删除 Option，图片也随之不返回。

**后续恢复：** 管理员再次 POST 相同配置组合时，Service 恢复这条 Option 并保留原 ID、图片关联，详见 [§7.10 新增 Option](#710-新增-option)。系统不为同一组合保存多条 Option 版本；操作历史由 Audit Log 保存，交易历史由 Order Item 快照保存。

**Service 执行流程：**

```
1. 查找 Option（不存在 → 40402）
2. 检查 Option.is_deleted（已删除 → 拒绝）
3. 检查所属 Product.status（online → 拒绝）
4. Repository 更新 is_deleted = true（不修改 Product 或图片）
5. 使用同一事务连接写入 Audit Log（action = DELETE_OPTION，含配置快照）
```

**成功响应**

**Response Schema：** `DeletedResourceOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 11,
        "is_deleted": true
    }
}
```

**Audit：** 记录 `action = DELETE_OPTION`，`target_type=product`、`target_id=所属 Product ID`。当前 AuditLog 没有 metadata 列，删除前快照以紧凑 JSON 写入 `description`：`{ "option_id": 11, "duration_minutes": 120, "participants": 2, "day_type": "holiday", "price": "699.00" }`。Option 更新和审计共享事务；任一步失败整体回滚。删除不加载完整聚合、不调用 ProductValidator。

> **实现状态：** `ProductService.delete_experience_option()` 已实现，并有 40402/40912/40905 优先级、Draft/Offline、最后一项删除、Product 状态与图片保留、审计快照和真实回滚测试。FastAPI 路由、ADMIN+ 依赖与 `DeletedResourceOut` 映射仍待实现。

---

### 7.14 Product 公共图片上传

```
POST /api/v1/admin/products/{product_id}/images
Content-Type: multipart/form-data
```

上传 Product 公共图片（`experience_option_id = NULL`）。用于列表封面和详情默认展示。Option 图片走独立接口。

**可能的业务错误：** `40401`, `40903`, `40905`, `42221`

> **实现边界：** `ProductService.create_product_image()` 接收存储层生成的 `image_url` 并负责数据库业务事务；multipart 解析、文件内容/大小/MIME 校验、对象存储与 `42221` 映射属于待实现的 API/存储适配器。若文件已上传但 Service 失败，调用方必须删除已上传对象或记录延迟清理任务。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 图片文件，最大 2MB，jpg/png/webp |
| is_cover | boolean | 否 | 默认 false。设为 true 时自动将旧封面改为 false |
| sort | int | 否 | 默认 0 |

**封面互斥：** 若 `is_cover = true`，Service 必须在同一事务中锁定 Product 行，再将该 Product 下其他公共图片的 `is_cover` 改为 `false`，保证同一 Product 的并发封面请求串行执行且最终只有一张有效公共封面。

**Product 状态限制：**

| 状态 | 允许 |
|------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 线上商品不可直接修改图片。应先下架 |
| `is_deleted = true` | ❌ |

**成功响应**

**Response Schema：** `ProductImageOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 20,
        "image_url": "https://cdn.example.com/products/1/20.jpg",
        "is_cover": true,
        "sort": 0
    }
}
```

**Audit：** `action = CREATE_PRODUCT_IMAGE`，`target_type=product`、`target_id=Product ID`；当前无 metadata 列，紧凑 JSON `{ "image_id": 20, "is_cover": true }` 写入 `description`。设为封面时，清除旧封面、图片创建和审计共享事务。

> **实现状态：** 公共图片创建、封面互斥与审计 Service 已实现，并有 Draft/Offline、404/409、非封面不清理、审计失败恢复旧封面测试。上传校验、存储适配器、路由与 `ProductImageOut` 映射仍待实现。

---

### 7.15 Option 专属图片上传

```
POST /api/v1/admin/options/{option_id}/images
Content-Type: multipart/form-data
```

给 ExperienceOption 上传专属图片。与 Product 公共图不同：不参与 `is_cover` 规则，不设封面概念。Option 默认首图 = `sort ASC, id ASC` 第一张。

**可能的业务错误：** `40402`, `40912`, `40905`, `42221`

> **实现边界：** 文件处理与失败补偿同 §7.14；Service 只接收生成后的 `image_url`，从已加载 Option 固定 Product 归属并强制 `is_cover=false`。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 图片文件，最大 2MB，jpg/png/webp |
| sort | int | 否 | 默认 0 |

> **不接收 `is_cover`。** Option 无封面概念。

**后端自动写入：**

| 字段 | 值 | 来源 |
|------|-----|------|
| `product_id` | Option 所属 Product | 从 Option → Product 自动获取 |
| `experience_option_id` | `option.id` | URL 参数 |
| `is_cover` | `false` | 固定 |

**Product 状态限制：**

| Product 状态 | 允许 |
|-------------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 先下架再调整 |
| `is_deleted = true` | ❌ |
| Option `is_deleted = true` | ❌ |

**成功响应**

**Response Schema：** `OptionImageOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 31,
        "image_url": "https://cdn.example.com/options/11/31.jpg",
        "sort": 0
    }
}
```

> 不返回 `is_cover`——Option 图片无此概念。

**上架关联：** 每个有效 Option 至少 1 张专属图片。无图时 draft/offline 允许存在，但 `PATCH .../online` 时 Validator 会拒绝。

**Audit：** `action = CREATE_OPTION_IMAGE`，`target_type=product`、`target_id=所属 Product ID`；紧凑 JSON `{ "image_id": 31, "option_id": 11 }` 写入现有 `description`。图片创建与审计共享事务。

> **实现状态：** Option 图片创建、固定归属/非封面和审计 Service 已实现，并有 40402/40912/40905 优先级与真实持久化测试。上传校验、存储适配器、路由与 `OptionImageOut` 映射仍待实现。

---

### 7.16 修改图片（排序/封面）

```
PATCH /api/v1/admin/product-images/{image_id}
```

修改图片的排序或封面标记。支持部分更新。

**可能的业务错误：** `40403`, `40905`, `40021`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| 图片不存在/已删除，或所属 Product/Option 已删除 | `ProductImageNotFound` | 40403 | `Product image not found` | 404 |
| 所属 Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |
| Option 专属图尝试设为封面 | `OptionImageCannotBeCover` | 40021 | `Option image cannot be set as product cover` | 400 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sort | int | 否 | >= 0。最终查询 `ORDER BY sort ASC, id ASC` |
| is_cover | boolean | 否 | **仅接受 `true`**，不接受 `false`。仅 Product 公共图片有效 |

`{}`、显式 `null`、`is_cover=false` 和未知字段均由 `ProductImageUpdate` 拒绝。`sort` 只接受真正的非负整数。

**is_cover 规则：**

| 图片类型 | 允许设置封面？ | 说明 |
|----------|-------------|------|
| Product 公共图（`experience_option_id = NULL`） | ✅ | 设置后自动取消旧封面 |
| Option 图片（`experience_option_id != NULL`） | ❌ | Option 无封面概念，首图由排序决定 |

**设置新封面时 Service 行为：**

```
PATCH { is_cover: true }
  │
  ├─ 同一 Product 下找到旧封面（is_cover = true）
  ├─ in_transaction() + 锁定 Product 行:
  │    ├─ 旧封面 → is_cover = false
  │    └─ 当前图片 → is_cover = true
  └─ 提交。始终保证 ≤ 1 张封面
```

**Product 状态限制：**

| Product 状态 | 允许 |
|-------------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ |
| `is_deleted = true` | ❌ |

**请求示例**

```json
{ "sort": 20 }
```

```json
{ "is_cover": true }
```

```json
{ "is_cover": true, "sort": 0 }
```

**成功响应（Product 公共图）**

**Response Schema：** `ProductImageOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 20,
        "image_url": "https://cdn.example.com/20.jpg",
        "is_cover": true,
        "sort": 0
    }
}
```

**成功响应（Option 图片）**

**Response Schema：** `OptionImageOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 31,
        "image_url": "https://cdn.example.com/31.jpg",
        "sort": 20
    }
}
```

> Option 图片不返回 `is_cover`。

**Audit：** 始终先记录 `UPDATE_PRODUCT_IMAGE`，description 含 `image_id` 及提交字段的 before/after。若非封面图片真正切换为封面，再顺序记录 `SET_PRODUCT_COVER`，含 `{ "old_cover_image_id": 10, "new_cover_image_id": 20 }`；没有旧封面时旧 ID 为 `null`。旧封面查询、批量清除、当前图片更新和一至两条审计共享事务，任一步失败整体回滚。

> **实现状态：** 图片排序/封面修改 Service 与 40403/40021 已实现，并有字段白名单、资源隐藏、Option 封面拒绝、单/双审计、唯一有效公共封面和第二条审计失败全回滚测试。路由与按图片归属选择 Out Schema 的 Mapper 仍待实现。

---

### 7.17 图片删除

```
DELETE /api/v1/admin/product-images/{image_id}
```

**Request Body：无。** 执行逻辑删除（`is_deleted = true`），文件存储延迟清理。

**可能的业务错误：** `40403`, `40905`

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| 图片不存在/已删除，或所属 Product/Option 已删除 | `ProductImageNotFound` | 40403 | `Product image not found` | 404 |
| 所属 Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |

**Product 状态限制：**

| Product 状态 | 允许 |
|-------------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 先下架再删除 |
| `is_deleted = true` | ❌ |
| Image 已删除 | ❌（统一返回 404） |

**特殊场景：**

| 场景 | 允许？ | 说明 |
|------|--------|------|
| 删除封面（`is_cover = true`） | ✅（draft/offline） | Product 暂时无封面，管理员上传新封面后重新上架 |
| 删除 Option 最后一张图 | ✅（draft/offline） | Option `images = []`，重新上架时 Validator 拦截 |

**Service 执行流程：**

```
1. 查找 Image（不存在 → 404）
2. 检查 Image.is_deleted（已删除 → 404）
3. 检查所属 Product.status（online → 拒绝）
4. Repository 设置 is_deleted = true
5. 使用同一事务连接写入 Audit Log（action = DELETE_PRODUCT_IMAGE，含图片快照）
```

**成功响应**

**Response Schema：** `DeletedResourceOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 31,
        "is_deleted": true
    }
}
```

**Audit：** `action = DELETE_PRODUCT_IMAGE`，`target_type=product`、`target_id=Product ID`。当前 `description` 上限为 256，而合法 `image_url` 最长 2048，因此紧凑快照保存 `{ "image_id": 31, "product_id": 1, "experience_option_id": 11, "is_cover": false, "sort": 10 }`，完整 URL 仍保留在逻辑删除的 ProductImage 记录中并可按 image_id 追溯。更新与审计共享事务；文件对象按后续存储清理机制处理。

> **实现状态：** 图片逻辑删除 Service 已实现，并有资源隐藏、Online 拒绝、封面/Option 最后一图允许删除、长度安全快照和审计失败回滚测试。文件延迟清理、路由与 `DeletedResourceOut` 映射仍待实现。

---

### 7.18 修改套装价格

```
PATCH /api/v1/admin/products/kit/{product_id}/price
```

修改 Kit 的当前售价。历史订单不受影响（订单保留价格快照）。

**可能的业务错误：** `40401`, `40404`, `40001`, `40903`, `40905`。金额格式与范围错误统一为 HTTP 422 Schema 校验。

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Product 不存在 | `ProductNotFound` | 40401 | `Product not found` | 404 |
| Product 已逻辑删除 | `ProductIsDeleted` | 40903 | `Product is deleted` | 409 |
| Product 不是 Kit | `ProductTypeMismatch` | 40001 | `Product type does not match this operation` | 400 |
| Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |
| Kit 扩展记录缺失 | `ProductKitNotFound` | 40404 | `Product kit not found` | 404 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| price | string | 是 | `"699.00"`，0 < Price ≤ 99999。后端转 Decimal 处理 |

**类型校验：** 仅接受 `product_type = "kit"`。传入 Experience ID 必须失败。

**状态限制：**

| Product 状态 | 允许 |
|-------------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 先下架再改价 |

**请求示例**

```json
{ "price": "699.00" }
```

**成功响应**

**Response Schema：** `KitPriceOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 2,
        "price": "699.00"
    }
}
```

**Audit：** `action = UPDATE_PRICE`，`target_type=product`、`target_id=Product ID`。当前 AuditLog 没有 metadata 列，before/after 两位小数价格快照以紧凑 JSON 写入 `description`。ProductKit 更新和审计共享事务；任一步失败整体回滚。Service 返回 ProductKit，API Mapper 使用 `product_id` 构造响应 `id`。

> **实现状态：** `ProductService.update_kit_price()` 与 `40404 ProductKitNotFound` 已实现，并有冲突优先级、Draft/Offline、字段保留、审计快照和真实回滚测试。FastAPI 路由、ADMIN+ 依赖与 `KitPriceOut` 映射仍待实现。

---

### 7.19 修改套装库存

```
PATCH /api/v1/admin/products/kit/{product_id}/stock
```

直接设置 Kit 的当前库存。第一版采用"设置最终值"模式，后续 Phase 4.3 升级为库存流水/调整单模式。

**可能的业务错误：** `40401`, `40404`, `40001`, `40903`, `40905`。库存类型与范围错误统一为 HTTP 422 Schema 校验。

| 条件 | 命名异常 | code | message | HTTP |
|------|----------|------|---------|------|
| Product 不存在 | `ProductNotFound` | 40401 | `Product not found` | 404 |
| Product 已逻辑删除 | `ProductIsDeleted` | 40903 | `Product is deleted` | 409 |
| Product 不是 Kit | `ProductTypeMismatch` | 40001 | `Product type does not match this operation` | 400 |
| Product 为 Online | `OnlineProductCannotBeModified` | 40905 | `Online product cannot be modified` | 409 |
| Kit 扩展记录缺失 | `ProductKitNotFound` | 40404 | `Product kit not found` | 404 |

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stock | int | 是 | 新库存数量，>= 0 |

**状态限制：**

| Product 状态 | 允许 |
|-------------|------|
| `draft` | ✅ |
| `offline` | ✅ |
| `online` | ❌ 先下架再调整 |

**请求示例**

```json
{ "stock": 80 }
```

**成功响应**

**Response Schema：** `KitStockOut`

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 2,
        "stock": 80
    }
}
```

**Audit：** `action = UPDATE_STOCK`，`target_type=product`、`target_id=Product ID`。before/after 整数库存快照以紧凑 JSON 写入现有 `AuditLog.description`。ProductKit 更新和审计共享事务；任一步失败整体回滚。Service 返回 ProductKit，API Mapper 使用 `product_id` 构造响应 `id`。

> **实现状态：** `ProductService.update_kit_stock()` 已实现，并有冲突优先级、Draft/Offline、零库存、字段保留、审计快照和真实回滚测试。FastAPI 路由、ADMIN+ 依赖与 `KitStockOut` 映射仍待实现。

> **后续升级点：** Phase 4.3 Inventory 模块将演进为库存调整模型（记录变动量 + 原因），替代当前"直接设值"模式。

---

### 7.20 商品操作历史

```
GET /api/v1/admin/products/{product_id}/audit-logs
```

查询指定商品的历史操作记录。不嵌入 Product Detail，通过共享 `AuditService` 独立查询。

**底层调用：**

```python
await audit_service.list_logs(
    target_type="product",
    target_id=product_id,
    page=1,
    page_size=20
)
```

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量 |

**可能的业务错误：** `40401`（商品不存在）

> 此接口属于 Product 模块路由，但实际查询逻辑委托给 AuditService。所有模块（Product、Order、Inventory 等）统一使用同一 AuditService。
>
> **Schema 边界：** 审计分页响应属于共享 Audit 模块，不在 Product Schema 中重复定义。当前 `AuditLogService.list_logs()` 与共享 `AuditLogOut` 尚待实现，因此该端点仍是后续实现项。

---
