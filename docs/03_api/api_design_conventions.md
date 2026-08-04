# API Design Conventions

> **Document Version:** v2.0
> **Status:** Active
> **Scope:** 项目级 — Product / Order / User / Inventory 等全部模块必须遵守
>
> 本文档定义 pinkdooHub 所有 API 的强制性设计规范。新增或修改接口时，必须对照本文档逐项检查。
>
> **业务模块 API 文档：** [User API](user_api.md) · [Product API](product_api.md) · [Order API](order_api.md)
>
> **快速检查清单见 [§18](#18-快速检查清单)。**

---

## 0. Data Flow（数据流向）

核心原则：**数据库存原始值，Service 负责转换，Response 面向前端。**

```
Database                  Service                     Response
────────                  ───────                     ────────
duration_minutes = 60  →  转换  →  { "value": 60, "label": "1小时" }
day_type = "weekday"   →  转换  →  { "value": "weekday", "label": "工作日" }
status = "online"      →  转换  →  { "value": "online", "label": "已上架" }
```

| 层 | 职责 | 禁止 |
|----|------|------|
| Database | 保存原始值，便于计算和索引 | 保存展示文案（"1小时"） |
| Service | 转换原始值 → `{value, label}` DTO | 把转换逻辑放在 API 层 |
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
PUT    /admin/products/{id}               # 编辑商品基本信息
DELETE /admin/products/{id}               # 逻辑删除
PATCH  /admin/products/{id}/online        # 上架
PATCH  /admin/products/{id}/offline       # 下架
POST   /admin/products/{id}/options       # 新增 Option
PUT    /admin/options/{option_id}         # 修改 Option
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

### 4.2 Token 机制

| 概念 | 说明 |
|------|------|
| access_token | 访问令牌，有效期 2 小时 |
| refresh_token | 刷新令牌，用于获取新的 access_token |

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

// 参数校验失败（422）
{
    "code": 422,
    "message": "Validation failed",
    "data": {
        "username": "Username must be 3-32 characters",
        "password": "Password must be at least 6 characters"
    }
}
```

### 6.4 字段排除规则

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
| 422 | Unprocessable Entity | 参数校验失败 |
| 500 | Internal Server Error | 服务器内部错误 |

> 业务状态以响应体中的 `code` 字段为准，HTTP 状态码用于表达请求层面的结果。

---

## 8. 错误码体系

### 8.1 编码规则

| 范围 | 含义 |
|------|------|
| 0 | 成功 |
| 1xxx | 用户模块业务错误 |
| 2xxx | 商品模块业务错误 |
| 3xxx | 订单模块业务错误 |
| 4xxx | HTTP 语义错误（与状态码一致） |
| 5xxx | 服务器错误 |

### 8.2 全局错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 请求参数校验失败 |
| 500 | 服务器内部错误 |

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

### 8.4 商品模块错误码（2xxx）

| code | 说明 |
|------|------|
| 2001 | 商品不存在 |
| 2002 | 库存不足 |

### 8.5 订单模块错误码（3xxx）

| code | 说明 |
|------|------|
| 3001 | 订单不存在 |
| 3002 | 订单状态不允许此操作 |

---

## 9. 数据类型与格式

### 9.1 时间

所有时间字段使用 ISO 8601 格式，UTC 时区：

```
"2026-07-23T10:30:00Z"
```

字段命名：`created_at`、`updated_at`

### 9.2 金额

所有金额以"元"为单位，`Decimal(10,2)` 精度：

```json
"total_amount": 199.00
```

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

**非展示枚举**（仅后端判断用，不需要 label）：

```json
{ "product_type": "experience" }   // 用于前端路由跳转
```

判断标准：**这个字段是给后端判断用的，还是给用户看的？** 给用户看的用 `{value, label}`，给后端判断的用原始值。

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
| `total_amount` (decimal) | `total_amount` | → number |
| `is_cover` (boolean) | `is_cover` | → boolean |

> - 所有 ID 类型在 API 中统一为 `int` / `bigint`
> - 所有时间字段统一为 ISO 8601 字符串
> - 枚举字段通过 Enum 类在 DB tinyint 和 API string 之间转换

---

## 14. Enum Registry（枚举注册表）

项目中所有枚举字段的完整映射。新增模块时在此表追加。

| 枚举类型 | DB 存储 | value | label |
|----------|---------|-------|-------|
| `Duration` | INT（分钟） | 60 | "1小时" |
| | | 120 | "2小时" |
| | | 480 | "全天" |
| `Participants` | INT | 1 | "1人" |
| | | 2 | "2人" |
| `DayType` | VARCHAR | `"weekday"` | "工作日" |
| | | `"holiday"` | "节假日" |
| `ProductStatus` | VARCHAR | `"draft"` | "草稿" |
| | | `"online"` | "已上架" |
| | | `"offline"` | "已下架" |
| `ProductType` | VARCHAR | `"experience"` | "拼豆体验" |
| | | `"kit"` | "拼豆套装" |
| `UserRole` | TINYINT | 1 → `"user"` | "普通用户" |
| | | 2 → `"admin"` | "管理员" |
| | | 3 → `"super_admin"` | "超级管理员" |
| `UserStatus` | TINYINT | 1 → `"normal"` | "正常" |
| | | 2 → `"disabled"` | "已禁用" |
| `OrderStatus` | TINYINT | 0 → `"pending"` | "待支付" |
| | | 1 → `"paid"` | "已支付" |
| | | 2 → `"cancelled"` | "已取消" |
| | | 3 → `"completed"` | "已完成" |

### 使用示例

```python
# Service 层：DB 值 → {value, label}
class Duration(IntEnum):
    ONE_HOUR = 60
    TWO_HOURS = 120
    FULL_DAY = 480

DURATION_LABELS = {
    Duration.ONE_HOUR: "1小时",
    Duration.TWO_HOURS: "2小时",
    Duration.FULL_DAY: "全天",
}

def duration_to_dto(value: int) -> dict:
    return {"value": value, "label": DURATION_LABELS.get(value, str(value))}
```

### 新增枚举检查清单

添加新的枚举字段时：

- [ ] 在本文档 §14 注册表中新增一行
- [ ] 数据库使用 `TINYINT`（数值型）或 `VARCHAR`（字符串型），在 ER 图 note 中标注
- [ ] Python 定义对应的 `Enum` 类（`app/common/enums/`）
- [ ] Service 层实现 `{value, label}` 转换
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
- [ ] 枚举字段 DB 用 TINYINT，API 用 string，已在 Enum Mapping 表中登记
