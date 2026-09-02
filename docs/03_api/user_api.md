# User API

> 本文档遵循 [API Design Conventions](api_design_conventions.md) 中定义的通用规范（响应格式、错误码、分页、数据类型等），重复内容不再赘述。

## 1. 概述

用户模块负责：

- 用户注册
- 用户登录
- 微信登录与外部身份绑定
- 身份认证（JWT）
- Refresh Token family 轮换与重放撤销
- 个人资料管理
- 账号注销与匿名化
- 用户管理（管理员）

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

### 用户对象

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint | 用户 ID |
| username | string | 登录账号 |
| nickname | string | 昵称 |
| phone | string / null | 手机号；微信首次登录账号可为空 |
| avatar | string | 头像 URL |
| role | string | 角色：`"user"` / `"admin"` / `"super_admin"` |
| status | string | 状态：`"normal"` 正常 / `"disabled"` 禁用 / `"deleted"` 已注销 |
| last_login_at | datetime / null | 最近登录时间 |
| created_at | datetime | 注册时间 |
| updated_at | datetime | 最近更新时间 |

---

## 2. 通用错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 401 | 未认证（Token 缺失或无效） |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 请求参数校验失败 |
| 500 | 服务器内部错误 |
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
| 1012 | 外部身份已绑定到其他账号或发生冲突 |
| 1013 | 当前账号未绑定该外部身份 |
| 1014 | 解绑会移除唯一登录方式 |
| 1015 | 存在 Pending/Paid 订单，暂不可注销 |
| 42901 | 身份请求超过限流阈值（HTTP 429） |
| 503 | 身份依赖暂不可用；限流不可用时 fail closed |

---

## 3. 字段校验规则

| 字段 | 规则 |
|------|------|
| username | 必填，3-32 字符；当前 Schema 未限制字符集 |
| password | 必填，8-64 字符 |
| nickname | 必填，1-32 字符 |
| phone | 必填，11 位中国大陆手机号 |
| avatar | 当前仅支持在资料 PATCH 中提交 URL；文件上传端点尚未实现 |

---

## 4. 端点列表

| Method | URI | 描述 | 认证 | 角色 |
|--------|-----|------|------|------|
| POST | /auth/register | 用户注册 | ❌ | 游客 |
| POST | /auth/login | 用户登录 | ❌ | 游客 |
| POST | /auth/wechat/login | 微信一次性 code 登录 | ❌ | 游客 |
| POST | /auth/wechat/bind | 绑定微信身份 | ✅ | 普通用户 |
| DELETE | /auth/wechat/bind | 密码二次验证后解绑微信 | ✅ | 普通用户 |
| GET | /auth/identities | 查询脱敏绑定摘要 | ✅ | 所有登录用户 |
| POST | /auth/refresh | 刷新 Token | ✅ | 所有登录用户 |
| POST | /auth/logout | 登出并撤销当前 refresh | ✅ | 所有登录用户 |
| GET | /users/me | 获取个人信息 | ✅ | 所有登录用户 |
| PATCH | /users/me | 修改个人信息 | ✅ | 所有登录用户 |
| PUT | /users/me/password | 修改密码 | ✅ | 所有登录用户 |
| DELETE | /users/me | 二次验证并匿名化注销 | ✅ | 普通用户 |
| GET | /admin/users | 用户列表 | ✅ | 管理员 |
| PUT | /admin/users/{id}/disable | 禁用用户 | ✅ | 管理员 |

---

## 业务规则

| 规则 | 说明 |
|------|------|
| 登录账号不可修改 | `username` 是登录凭证，创建后不可变更；显示名称通过 `nickname` 修改 |
| 默认角色 | 注册后角色默认为 `"user"`（普通用户） |
| 默认状态 | 注册后状态默认为 `"normal"`（正常） |
| 修改密码需旧密码 | 修改密码时必须验证当前密码 |
| 不能禁用自己 | 管理员不可通过 `/admin/users/{id}/disable` 禁用自己的账号 |
| 禁用即时生效 | 登录、旧 access 鉴权和旧 refresh 换取新 access 均返回 1005；首次 refresh 拒绝同时撤销该 refresh |
| 注销账号 | 保留业务外键并匿名化，不物理删除订单/库存/审计；Pending/Paid 订单时拒绝 |
| 微信身份 | 不自动按手机号等资料合并；不向客户端返回 OpenID/UnionID/session_key |

---

## 5. 认证接口

### 5.1 用户注册

```
POST /api/v1/auth/register
```

创建一个新用户，成功时返回完整的用户信息。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 登录账号，3-32 字符 |
| password | string | 是 | 登录密码，8-64 字符 |
| nickname | string | 是 | 用户昵称 |
| phone | string | 是 | 手机号码，11 位中国大陆手机号 |

**请求示例**

```json
{
    "username": "alice",
    "password": "12345678",
    "nickname": "Alice",
    "phone": "13800138000"
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
        "username": "alice",
        "nickname": "Alice",
        "phone": "13800138000",
        "avatar": null,
        "role": "user",
        "status": "normal",
        "created_at": "2026-07-23T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

**失败响应**

用户名已存在：

```json
{
    "code": 1001,
    "message": "Username already exists"
}
```

参数校验失败：

```json
{
    "code": 422,
    "message": "Validation failed",
    "data": {
        "username": "Username must be 3-32 characters",
        "password": "Password must be at least 8 characters"
    }
}
```

---

### 5.2 用户登录

```
POST /api/v1/auth/login
```

验证用户名密码，返回 JWT Token 和用户信息。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 登录账号 |
| password | string | 是 | 登录密码 |

**请求示例**

```json
{
    "username": "alice",
    "password": "123456"
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "Bearer",
        "expires_in": 7200,
        "user": {
            "id": 1,
            "username": "alice",
            "nickname": "Alice",
            "phone": "13800138000",
            "avatar": "https://cdn.example.com/avatars/1.jpg",
            "role": "user",
            "status": "normal",
            "created_at": "2026-01-15T10:30:00Z",
            "updated_at": "2026-07-20T14:00:00Z"
        }
    }
}
```

| 字段 | 说明 |
|------|------|
| access_token | 访问令牌，后续请求携带 |
| refresh_token | 刷新令牌，用于获取新的 access_token |
| token_type | 固定为 `Bearer` |
| expires_in | access_token 有效期，单位秒 |
| user | 当前登录用户信息 |

**失败响应**

无效登录凭据（账号不存在、密码错误或账号没有密码登录能力均使用同一响应）：

```json
{
    "code": 1003,
    "message": "Incorrect password"
}
```

服务端对不存在/无密码账号执行 bcrypt dummy verify；只有密码正确后才会返回下方禁用状态。`1002` 仍用于管理员按 ID 操作不存在用户等非登录接口。

用户已被禁用：

```json
{
    "code": 1005,
    "message": "User is disabled"
}
```

---

### 5.3 刷新 Token

```
POST /api/v1/auth/refresh
```

使用 refresh_token 原子换取新的 access/refresh 双 Token。旧 refresh 立即变为已消费；重放旧值会撤销当前 family，客户端必须原子替换本地双 Token。

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| refresh_token | string | 是 | 登录时获取的 refresh token |

**请求示例**

```json
{
    "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "Bearer",
        "expires_in": 7200
    }
}
```

同一旧 refresh 的并发请求最多一个成功。已消费 Token 重放、family 已撤销、用户禁用/注销或 `auth_version` 变化均拒绝，响应不区分内部 Token 状态。

### 5.4 登出

```
POST /api/v1/auth/logout
```

撤销当前 session 的 refresh token。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "Logged out",
    "data": null
}
```

### 5.5 微信登录

`POST /api/v1/auth/wechat/login` 请求为 `{"code":"wx.login 一次性 code"}`。服务端调用微信 `code2Session`，只在服务端使用 AppSecret；首次身份创建普通用户，后续按 `(provider, app_id, subject HMAC)` 登录。成功响应与 5.2 相同。平台拒绝返回 1011，平台/网络暂不可用返回 503，限流返回 42901。

### 5.6 绑定、解绑与绑定摘要

- `POST /api/v1/auth/wechat/bind`：Bearer + `{"code":"..."}`；仅普通用户，重复绑定自己幂等返回摘要，身份属于其他账号时返回 1012。
- `DELETE /api/v1/auth/wechat/bind`：Bearer + `{"password":"当前密码"}`；仅有可用密码的普通用户允许，成功后递增 `auth_version` 并撤销全部 refresh family。
- `GET /api/v1/auth/identities`：只返回 `provider` 与 `bound_at`，不返回 AppID、OpenID、UnionID、HMAC 或 `session_key`。

### 5.7 密码注册开关与限流

公开版将 `PASSWORD_REGISTRATION_ENABLED=false`，密码注册返回 1010；Gate A/开发可显式保留。登录、注册、refresh、微信登录和绑定均使用 Redis 原子限流，HTTP 429 的响应不包含账号、IP、Token 或平台标识。

**失败响应**

Token 无效或已过期：

```json
{
    "code": 1006,
    "message": "Token expired or invalid"
}
```

---

## 6. 用户接口

### 6.1 获取个人信息

```
GET /api/v1/users/me
```

获取当前登录用户的详细信息。

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
        "username": "alice",
        "nickname": "Alice",
        "phone": "13800138000",
        "avatar": "https://cdn.example.com/avatars/1.jpg",
        "role": "user",
        "status": "normal",
        "created_at": "2026-01-15T10:30:00Z",
        "updated_at": "2026-07-20T14:00:00Z"
    }
}
```

---

### 6.2 修改个人信息

```
PATCH /api/v1/users/me
```

部分更新当前用户的资料。所有字段可选，传什么改什么，未传的保持原值。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| nickname | string | 否 | 新昵称，1-32 字符 |
| phone | string | 否 | 新手机号，11 位中国大陆手机号 |
| avatar | string | 否 | 新头像 URL |

> 至少传递一个字段，空请求体返回 422。

**请求示例**

```json
{
    "nickname": "Alice Wang",
    "phone": "13900139000",
    "avatar": "https://cdn.example.com/avatars/1.jpg"
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "id": 1,
        "username": "alice",
        "nickname": "Alice Wang",
        "phone": "13900139000",
        "avatar": "https://cdn.example.com/avatars/1.jpg",
        "role": "user",
        "status": "normal",
        "created_at": "2026-01-15T10:30:00Z",
        "updated_at": "2026-07-23T10:30:00Z"
    }
}
```

**失败响应**

参数校验失败：

```json
{
    "code": 422,
    "message": "Validation failed",
    "data": {
        "phone": "Phone must be 11 digits"
    }
}
```

---

### 6.3 修改密码

```
PUT /api/v1/users/me/password
```

修改当前用户的登录密码，需要验证旧密码。

**Header**

```
Authorization: Bearer <access_token>
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| old_password | string | 是 | 旧密码 |
| new_password | string | 是 | 新密码，8-64 字符 |

**请求示例**

```json
{
    "old_password": "123456",
    "new_password": "newpass123"
}
```

**成功响应**

```json
{
    "code": 0,
    "message": "Password changed successfully"
}
```

**失败响应**

旧密码不正确：

```json
{
    "code": 1004,
    "message": "Old password is incorrect"
}
```

---

### 6.4 注销并匿名化账号

`DELETE /api/v1/users/me` 仅允许普通用户。请求必须包含 `confirmation: "DELETE"`，并且在 `password` 与 `wechat_code` 中恰好选择一种二次验证方式。存在 Pending/Paid 订单时返回 1015；完成/取消订单不阻塞。

成功返回 `{"code":0,"message":"Account deleted","data":null}`。提交后删除全部外部身份、撤销全部 refresh family、递增 `auth_version`，并将用户状态改为 deleted；用户主键和历史订单/库存/审计保留。接口不返回匿名化后的 username，也不支持 ADMIN/SUPER_ADMIN 自助注销。

### 6.5 头像文件上传（未实现）

当前没有 `POST /api/v1/users/me/avatar`。资料 PATCH 仅能保存调用方提供的头像 URL；正式文件上传必须在后端补齐存储、内容校验和授权契约后再开放。

---

## 7. 管理接口

> 以下接口需要 `ADMIN+`，普通用户调用返回 HTTP 403。当前只实现列表和禁用；用户详情、启用和头像文件上传仍是未来能力，客户端不得提前提供按钮。

### 7.1 用户列表

```
GET /api/v1/admin/users
```

分页获取所有用户。

**Header**

```
Authorization: Bearer <access_token>
```

**查询参数**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| page | int | 否 | 1 | 页码 |
| page_size | int | 否 | 20 | 每页数量，最大 100 |
| status | string | 否 | - | 筛选状态：`"normal"` 正常 / `"disabled"` 禁用 |
| role | string | 否 | - | 筛选角色：`"user"` / `"admin"` / `"super_admin"` |

未知枚举、额外查询参数、`page < 1` 或超出范围的 `page_size` 均返回 HTTP 422，不会被静默忽略。结果按 `created_at DESC, id DESC` 稳定分页。

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "items": [
            {
                "id": 1,
                "username": "alice",
                "nickname": "Alice",
                "role": "user",
                "status": "normal",
                "last_login_at": "2026-08-28T08:00:00Z",
                "created_at": "2026-01-15T10:30:00Z"
            }
        ],
        "total": 100,
        "page": 1,
        "page_size": 20,
        "pages": 5
    }
}
```

---

### 7.2 禁用用户

```
PUT /api/v1/admin/users/{id}/disable
```

将指定用户状态设为禁用（`status = "disabled"`）。

请求不接收 body；任何非空 body 返回 HTTP 422。目标行会在事务内锁定，状态更新与 `DISABLE_USER` 审计日志原子提交。已经禁用的目标直接成功，不重复写审计。

**权限**

| 操作者 | 目标 | 结果 |
|--------|------|------|
| ADMIN | USER | ✅ 成功 |
| ADMIN / SUPER_ADMIN | 自己 | ❌ HTTP 400 / code 422 |
| ADMIN | SUPER_ADMIN | ❌ 403 |
| SUPER_ADMIN | 其他 SUPER_ADMIN | ✅ 成功 |
| ADMIN+ | 已禁用用户 | ✅ 幂等，直接返回成功 |

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "User disabled",
    "data": null
}
```

**失败响应**

用户不存在：

```json
{
    "code": 1002,
    "message": "User not found"
}
```

不能禁用自己：

```json
{
    "code": 422,
    "message": "Cannot disable yourself"
}
```

不能禁用超级管理员：

```json
{
    "code": 403,
    "message": "Cannot disable super admin"
}
```

## 8. 附录

### HTTP 状态码约定

| 状态码 | 含义 |
|--------|------|
| 200 | 请求成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 413 | 上传文件过大 |
| 422 | 参数校验失败 |
| 500 | 服务器内部错误 |

### 分页参数规范

所有列表接口统一使用以下分页参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | int | 1 | 页码，从 1 开始 |
| page_size | int | 20 | 每页数量，最大 100 |

分页响应统一包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| items | array | 数据列表 |
| total | int | 总记录数 |
| page | int | 当前页码 |
| page_size | int | 每页数量 |

### v0.2 计划

以下接口计划在后续版本实现：

- 手机验证码登录
- 微信登录
- OAuth 登录
- 手机号绑定/换绑
- 找回密码
- 管理端用户详情与启用
- 头像文件上传
