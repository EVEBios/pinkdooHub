# User 模块开发总结

> Phase 2 — 完整用户认证体系

---

## 涉及文件（26 个）

| 文件 | 操作 | 行数 | 职责 |
|------|------|------|------|
| `app/common/enums/user.py` | 新建 | 18 | `UserRole`（USER/ADMIN/SUPER_ADMIN）、`UserStatus`（NORMAL/DISABLED） |
| `app/common/constants/validation.py` | 新建 | 19 | 用户名/密码/昵称/手机号校验常量 |
| `app/common/exceptions/user.py` | 新建 | 52 | 7 个命名异常类（UsernameAlreadyExists 等） |
| `app/common/exceptions/__init__.py` | 新建 | — | re-export 所有 User 异常 |
| `app/models/base.py` | 新建 | 25 | 抽象基类：id、created_at、updated_at |
| `app/models/user.py` | 新建 | 27 | User 表：7 业务字段 + 3 继承 = 10 字段 |
| `app/models/__init__.py` | 修改 | 1 | 显式 import User 供 Tortoise 发现 |
| `app/schemas/user.py` | 新建 | 90 | UserCreate、UserLogin、UserUpdate、UserOut、UserListItem |
| `app/schemas/auth.py` | 新建 | 15 | TokenOut（JWT + 用户信息） |
| `app/repositories/user_repo.py` | 新建 | 27 | get_by_id、get_by_username、get_by_phone、create |
| `app/services/user_service.py` | 新建 | 83 | register（查重→哈希→入库）、login（查用户→验状态→验密码） |
| `app/core/config.py` | 重写 | 101 | pydantic-settings 14 字段 + model_validator 校验 |
| `app/core/security.py` | 扩展 | 65 | hash_password、verify_password、create_access_token、decode_access_token |
| `app/core/logging.py` | 增强 | 56 | DEBUG/INFO 环境自适应，日志级别文档 |
| `app/core/exceptions.py` | 重构 | 89 | AppException 基类 + BusinessException 等 4 个子类 |
| `app/db/database.py` | 新建 | 66 | register_tortoise——SQLite/MySQL 自动切换 |
| `app/middleware/exception.py` | 重构 | 97 | 5 种异常类型 → HTTP 状态码字典映射 |
| `app/api/deps.py` | 新建 | 30 | get_current_user（FastAPI Depends + JWT 解析） |
| `app/api/v1/auth.py` | 新建 | 48 | POST /auth/register、POST /auth/login |
| `app/api/v1/users.py` | 新建 | 23 | GET /users/me（JWT 保护） |
| `app/main.py` | 修改 | 24 | lifespan 接入 DB，注册 auth/users 路由 |

---

## 分层架构

```
POST /auth/register          POST /auth/login            GET /users/me
       │                           │                          │
       ▼                           ▼                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  API 层  (app/api/)                                              │
│  · 参数校验 (Pydantic)                                           │
│  · 调用 Service                                                  │
│  · response_model 自动序列化                                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  Deps 层  (app/api/deps.py)                                      │
│  · get_current_user: 解析 JWT → 查库 → 注入 User                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  Service 层  (app/services/)                                     │
│  · UserService.register() — 查重 → 哈希 → 入库                   │
│  · UserService.login()    — 查用户 → 验状态 → 验密码              │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  Repository 层  (app/repositories/)                              │
│  · get_by_id / get_by_username / get_by_phone / create           │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  Model 层  (app/models/)                                         │
│  · BaseModel → User (10 字段)                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 数据模型

### Enum

| 枚举 | 值 | API 输出 |
|------|-----|---------|
| `UserRole.USER` | 1 | `"user"` |
| `UserRole.ADMIN` | 2 | `"admin"` |
| `UserRole.SUPER_ADMIN` | 3 | `"super_admin"` |
| `UserStatus.NORMAL` | 1 | `"normal"` |
| `UserStatus.DISABLED` | 2 | `"disabled"` |

### Schema

| Schema | 用途 | 字段 |
|--------|------|------|
| `UserCreate` | 注册请求 | username, password, nickname, phone |
| `UserLogin` | 登录请求 | username, password |
| `UserUpdate` | 修改个人信息 | nickname, phone |
| `UserOut` | 详情/个人信息 | 10 字段（不含 password） |
| `UserListItem` | 后台列表 | id, username, nickname, role, status, created_at |
| `TokenOut` | 登录响应 | access_token, token_type, expires_in, user |

---

## 异常体系

| 异常类 | code | 触发条件 |
|--------|------|---------|
| `UsernameAlreadyExists` | 1001 | 注册用户名重复 |
| `UserNotFound` | 1002 | 用户不存在 |
| `IncorrectPassword` | 1003 | 密码不匹配 |
| `OldPasswordIncorrect` | 1004 | 修改密码时旧密码错误 |
| `UserDisabled` | 1005 | 已禁用用户登录 |
| `TokenExpired` | 1006 | JWT 无效或过期 |
| `PhoneAlreadyExists` | 1007 | 手机号已被注册 |

继承链：`XxxException → UserException → BusinessException → AppException → Exception`

---

## API 端点

| Method | URI | 认证 | 说明 |
|--------|-----|------|------|
| POST | `/api/v1/auth/register` | ❌ | 用户注册 |
| POST | `/api/v1/auth/login` | ❌ | 用户登录，返回 JWT |
| GET | `/api/v1/users/me` | ✅ Bearer | 获取当前用户信息 |

### 注册流程

```
username 查重 → phone 查重 → bcrypt 哈希 → INSERT
  │               │
  ▼               ▼
 1001            1007
```

### 登录流程

```
username 查库 → 检查 status → 验证密码 → JWT 签发 → TokenOut
  │               │              │
  ▼               ▼              ▼
 1002            1005           1003
```

### 认证流程（Depends）

```
Authorization: Bearer <token>
  → HTTPBearer 提取 token
  → decode_access_token → payload["sub"]
  → UserRepository.get_by_id(user_id)
  → 注入 current_user 到路由参数
```

---

## 依赖

| 包 | 版本 | 用途 |
|----|------|------|
| pydantic-settings | 2.14 | 配置管理 |
| passlib[bcrypt] | 1.7.4 | 密码哈希 |
| bcrypt | 3.2.2 | 加密后端 |
| python-jose + cryptography | 3.5.0 + 50.0.1 | JWT 签发与验证 |
| tzdata | 2026.3 | 时区数据（Windows） |

---

## 校验规则

| 字段 | 规则 |
|------|------|
| username | 3-32 字符 |
| password | 8-64 字符 |
| nickname | 1-32 字符 |
| phone | `^1[3-9]\d{9}$`（中国大陆手机号） |
