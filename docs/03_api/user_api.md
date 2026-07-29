# User API

> 本文档遵循 [API Design Conventions](api_design_conventions.md) 中定义的通用规范（响应格式、错误码、分页、数据类型等），重复内容不再赘述。

## 1. 概述

用户模块负责：

- 用户注册
- 用户登录
- 身份认证（JWT）
- Token 刷新
- 个人资料管理
- 头像上传
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
| phone | string | 手机号 |
| avatar | string | 头像 URL |
| role | string | 角色：`"user"` 普通用户，`"admin"` 管理员 |
| status | string | 状态：`"normal"` 正常 / `"disabled"` 禁用 |
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

---

## 3. 字段校验规则

| 字段 | 规则 |
|------|------|
| username | 必填，3-32 字符，字母数字下划线 |
| password | 必填，8-64 字符 |
| nickname | 必填，1-32 字符 |
| phone | 必填，11 位中国大陆手机号 |
| avatar | 可选，图片文件，最大 2MB，支持 jpg/png/webp |

---

## 4. 端点列表

| Method | URI | 描述 | 认证 | 角色 |
|--------|-----|------|------|------|
| POST | /auth/register | 用户注册 | ❌ | 游客 |
| POST | /auth/login | 用户登录 | ❌ | 游客 |
| POST | /auth/refresh | 刷新 Token | ✅ | 所有登录用户 |
| GET | /users/me | 获取个人信息 | ✅ | 所有登录用户 |
| PUT | /users/me | 修改个人信息 | ✅ | 所有登录用户 |
| PUT | /users/me/password | 修改密码 | ✅ | 所有登录用户 |
| POST | /users/me/avatar | 上传头像 | ✅ | 所有登录用户 |
| GET | /admin/users | 用户列表 | ✅ | 管理员 |
| GET | /admin/users/{id} | 用户详情 | ✅ | 管理员 |
| PUT | /admin/users/{id}/disable | 禁用用户 | ✅ | 管理员 |
| PUT | /admin/users/{id}/enable | 启用用户 | ✅ | 管理员 |

---

## 业务规则

| 规则 | 说明 |
|------|------|
| 登录账号不可修改 | `username` 是登录凭证，创建后不可变更；显示名称通过 `nickname` 修改 |
| 默认角色 | 注册后角色默认为 `"user"`（普通用户） |
| 默认状态 | 注册后状态默认为 `"normal"`（正常） |
| 修改密码需旧密码 | 修改密码时必须验证当前密码 |
| 不能禁用自己 | 管理员不可通过 `/admin/users/{id}/disable` 禁用自己的账号 |
| 禁用后不可登录 | `status = "disabled"` 的用户调用 `/auth/login` 返回 1005 |
| 删除用户 | ❌ 当前版本不支持，计划在 v1.0 实现 |

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
    "password": "123456",
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
        "password": "Password must be at least 6 characters"
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

用户不存在：

```json
{
    "code": 1002,
    "message": "User not found"
}
```

密码错误：

```json
{
    "code": 1003,
    "message": "Incorrect password"
}
```

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

使用 refresh_token 获取新的 access_token。仅返回 access token，不轮换 refresh。

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
        "token_type": "Bearer",
        "expires_in": 7200
    }
}
```

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

### 6.4 上传头像

```
POST /api/v1/users/me/avatar
```

上传当前用户的头像图片。

**Header**

```
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

**请求参数**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 图片文件，最大 2MB，支持 jpg/png/webp |

**成功响应**

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "avatar": "https://cdn.example.com/avatars/1.jpg"
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

不支持的格式：

```json
{
    "code": 422,
    "message": "Only jpg, png and webp are allowed"
}
```

---

## 7. 管理接口

> 以下接口需要管理员角色（`role = "admin"`），普通用户调用返回 403。

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
| keyword | string | 否 | - | 搜索关键词（匹配 username / nickname） |
| status | string | 否 | - | 筛选状态：`"normal"` 正常 / `"disabled"` 禁用 |

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
                "phone": "13800138000",
                "avatar": "https://cdn.example.com/avatars/1.jpg",
                "role": "user",
                "status": "normal",
                "created_at": "2026-01-15T10:30:00Z",
                "updated_at": "2026-01-15T10:30:00Z"
            }
        ],
        "total": 100,
        "page": 1,
        "page_size": 20
    }
}
```

---

### 7.2 用户详情

```
GET /api/v1/admin/users/{id}
```

查看指定用户的详细信息。

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

**失败响应**

用户不存在：

```json
{
    "code": 1002,
    "message": "User not found"
}
```

---

### 7.3 禁用用户

```
PUT /api/v1/admin/users/{id}/disable
```

将指定用户状态设为禁用（`status = "disabled"`）。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "User disabled"
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

---

### 7.4 启用用户

```
PUT /api/v1/admin/users/{id}/enable
```

将指定用户状态设为正常（`status = "normal"`）。

**Header**

```
Authorization: Bearer <access_token>
```

**成功响应**

```json
{
    "code": 0,
    "message": "User enabled"
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

---

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
