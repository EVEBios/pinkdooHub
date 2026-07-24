# pinkdooHub Coding Standards

> 本文档是项目唯一的编码规范来源。所有 PR 必须对照本文档的 Code Review Checklist 逐项检查。

---

## 1. 命名规范（Naming）

### 1.1 通用规则

| 对象 | 规范 | 示例 |
|------|------|------|
| 文件名 | 小写、snake_case | `user_service.py`、`order_repo.py` |
| 类名 | PascalCase | `UserService`、`OrderRepository` |
| 函数/方法 | 小写、snake_case | `get_by_username()`、`create_order()` |
| 变量 | 小写、snake_case | `user_id`、`total_amount` |
| 常量 | 大写、SNAKE_CASE | `MAX_PAGE_SIZE`、`DEFAULT_AVATAR` |
| 枚举类 | PascalCase | `UserRole`、`OrderStatus` |
| 枚举成员 | 大写、SNAKE_CASE | `UserRole.ADMIN`、`OrderStatus.PAID` |

### 1.2 按层命名

| 层 | 文件命名 | 类命名 |
|----|----------|--------|
| Model | `user.py` | `User` |
| Schema | `user.py` | `UserCreate`、`UserOut`、`UserUpdate` |
| Repository | `user_repo.py` | `UserRepository` |
| Service | `user_service.py` | `UserService` |
| API 路由 | `users.py`、`admin_users.py` | —（函数式） |

### 1.3 Schema 命名后缀

| 用途 | 后缀 | 示例 |
|------|------|------|
| 创建请求 | `Create` | `UserCreate`、`ProductCreate`、`OrderCreate` |
| 响应输出 | `Out` | `UserOut`、`ProductOut`、`OrderOut` |
| 更新请求 | `Update` | `UserUpdate`、`ProductUpdate` |
| 列表项（轻量） | `ListItem` | `ProductListItem`、`OrderListItem` |
| 登录请求 | `Login` | `UserLogin` |
| Token 响应 | `TokenOut` | `TokenOut` |

### 1.4 正确与错误示例

```python
# ✅ 正确
class User(Model):
    pass

class UserRepository:
    pass

class UserService:
    pass

class UserCreate(BaseModel):
    pass

@router.post("/users")
async def create_user(data: UserCreate): ...

# ❌ 禁止
class user(Model):           # 类名必须 PascalCase
    pass

class USER:                  # 全大写只用于常量
    pass

class user_service:          # 类名必须 PascalCase，文件名才用 snake_case
    pass

class userRepository:        # 禁止 camelCase
    pass
```

---

## 2. 项目结构规范（Project Structure）

### 2.1 目录职责

```
app/
├── api/          → 路由 + 参数校验，不写业务逻辑
├── services/     → 业务编排 + 事务管理，不直接操作 Model
├── repositories/ → 数据库查询封装，不包含业务判断
├── models/       → Tortoise ORM Model 定义
├── schemas/      → Pydantic 请求/响应 Schema
├── common/       → 共享类型（enums、constants、response、pagination）
├── core/         → 底层基础设施（config、security、redis、exceptions）
├── middleware/    → HTTP 生命周期切面（auth、logging、cors、exception）
├── db/           → ORM 初始化与连接管理
└── utils/        → 纯函数工具（无状态、无副作用）
```

**common/ vs core/ 的边界**

```
common/                         core/
────────────────────────        ────────────────────────
业务相关，跨领域共享              业务无关，纯技术能力
类型的"字典"                     框架的"工具箱"

✅ 放这里                       ✅ 放这里
· Enum（UserRole）              · 配置类（Settings）
· 业务常量（MAX_PAGE_SIZE）      · 加解密（security）
· 响应格式（response.py）        · Redis 客户端
· 分页模型（pagination.py）      · 异常类定义（BusinessException）
· 类型别名（types.py）           · 任何不依赖 HTTP 的底层工具

❌ 不放这里                      ❌ 不放这里
· 配置类、Redis 客户端           · Enum、业务常量
· 中间件、工具函数               · Pydantic Model
· Tortoise ORM 查询             · 与具体业务领域相关的定义
```

> 一句话判断：**这个模块是描述"我们的业务长什么样"还是"框架如何运转"？**
> 前者放 `common/`，后者放 `core/`。`BusinessException` 定义在 `core/` 是因为"异常如何传递"是框架机制，不是业务概念。

### 2.2 文件归属规则

遇到不确定放哪的代码时，按以下决策树判断：

```
需要访问数据库？
  ├─ 是 → repositories/
  └─ 否 → 包含业务编排逻辑？
            ├─ 是 → services/
            └─ 否 → 处理 HTTP 请求？
                      ├─ 是 → api/ 或 middleware/
                      └─ 否 → 是纯函数？
                                ├─ 是 → utils/
                                └─ 否 → 是类型/常量/Enum？
                                          ├─ 是 → common/
                                          └─ 否 → core/
```

### 2.3 禁止行为

| ❌ | ✅ |
|----|-----|
| `api/` 里直接写 `await User.create(...)` | 通过 Service → Repository |
| `repositories/` 里写 `if user.status == 0: raise ...` | 业务判断在 Service |
| `utils/` 里放 Pydantic Model | 放 `common/` |
| 一个文件超过 400 行 | 按职责拆分 |

---

## 3. API 开发规范

### 3.1 路由文件组织

```python
# app/api/v1/users.py          ← 普通用户接口
# app/api/v1/admin_users.py    ← 管理员接口
# app/api/v1/products.py       ← 公开商品接口
# app/api/v1/admin_products.py ← 管理员商品接口
# app/api/v1/orders.py         ← 用户订单接口
# app/api/v1/admin_orders.py   ← 管理员订单接口
```

用户端与管理端路由分文件存放，不混在一起。

### 3.2 端点写法

```python
from fastapi import APIRouter, Depends
from app.schemas.user import UserCreate, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])

@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    data: UserCreate,
    service: UserService = Depends()
):
    """创建用户"""
    return await service.create(data)
```

### 3.3 约束

| ✅ 必须 | ❌ 禁止 |
|---------|---------|
| 请求体用 Pydantic Schema 校验 | 在 API 层写数据库查询 |
| `response_model` 明确声明 | 裸 `dict` 作为返回值 |
| 通过 `Depends()` 注入 Service | API 函数中写业务逻辑 |
| 每个端点有 docstring | 无文档的端点 |

---

## 4. Service 开发规范

### 4.1 类结构

```python
from app.repositories.user_repo import UserRepository
from app.core.exceptions import BusinessException
from app.core.security import hash_password

class UserService:
    def __init__(self, user_repo: UserRepository = Depends()):
        self.user_repo = user_repo

    async def create(self, data: UserCreate) -> User:
        # 1. 业务校验
        existing = await self.user_repo.get_by_username(data.username)
        if existing:
            raise BusinessException(code=1001, message="Username already exists")

        # 2. 数据处理
        hashed = hash_password(data.password)

        # 3. 持久化
        return await self.user_repo.create(
            username=data.username,
            password=hashed,
            nickname=data.nickname,
            phone=data.phone,
        )
```

### 4.2 事务规范

需要跨表操作时，使用 Tortoise ORM 的事务上下文：

```python
from tortoise.transactions import in_transaction

async def create_order(self, user_id: int, data: OrderCreate) -> Order:
    async with in_transaction():
        for item in data.items:
            await self.product_repo.deduct_stock(item.product_id, item.quantity)
        order = await self.order_repo.create(user_id, data)
    return order
```

### 4.3 约束

| ✅ 允许 | ❌ 禁止 |
|---------|---------|
| 调用任意 Repository | 直接操作 Model（如 `await User.create(...)`） |
| 调用 core/ 中的工具（security、redis） | **调用另一个 Service** |
| 抛出 `BusinessException` | 抛出 `HTTPException` |
| 使用 `in_transaction()` 管理事务 | 在事务外执行需要原子性的操作 |

> **Service 之间禁止直接调用**。需要其他领域的数据时，通过 Repository 获取。这防止了循环依赖：
>
> ```
> ❌ OrderService → UserService
> ✅ OrderService → UserRepository
> ```

---

## 5. Repository 开发规范

### 5.1 方法粒度

```python
class UserRepository:
    # ✅ 单条查询，返回 Model 或 None
    async def get_by_id(self, user_id: int) -> User | None:
        return await User.filter(id=user_id).first()

    async def get_by_username(self, username: str) -> User | None:
        return await User.filter(username=username).first()

    # ✅ 列表查询，支持筛选和分页，返回 Page[T]
    async def list_paginated(
        self, *, page: int, page_size: int, status: int | None = None
    ) -> Page[User]:
        qs = User.all()
        if status is not None:
            qs = qs.filter(status=status)
        total = await qs.count()
        items = await qs.offset((page - 1) * page_size).limit(page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    # ✅ 创建/更新
    async def create(self, **kwargs) -> User:
        return await User.create(**kwargs)

    async def update(self, user: User, **kwargs) -> User:
        await user.update_from_dict(kwargs).save()
        return user
```

`Page[T]` 定义在 `app/common/pagination.py`：

```python
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
```

> `Page[T]` 替代裸 `tuple` 的好处：字段有名称（`page.items` 而非 `result[0]`），IDE 有自动补全，不会弄错 items 和 total 的顺序。

### 5.2 约束

| ✅ 允许 | ❌ 禁止 |
|---------|---------|
| Tortoise ORM 查询/创建/更新 | 业务判断（`if user.status == 0: raise`） |
| 返回 Model 实例或 `None` | 抛出 `BusinessException` |
| 接受 Model 实例作为参数 | 接受 Pydantic Schema 作为参数 |
| list 返回 `Page[T]`（含 items、total、page、page_size） | list 返回裸 `list`（丢失总数）或 `tuple`（字段顺序易出错） |

---

## 6. Model 开发规范

### 6.1 定义

```python
from tortoise import fields
from tortoise.models import Model

class User(Model):
    id = fields.BigIntField(pk=True)
    username = fields.CharField(max_length=32, unique=True)
    password = fields.CharField(max_length=128)
    nickname = fields.CharField(max_length=32)
    phone = fields.CharField(max_length=11, null=True)
    avatar = fields.CharField(max_length=256, null=True)
    role = fields.SmallIntField(default=1)      # UserRole.USER
    status = fields.SmallIntField(default=1)     # UserStatus.NORMAL
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users"
```

### 6.2 约束

| ✅ 必须 | ❌ 禁止 |
|---------|---------|
| 枚举字段用 `SmallIntField` 存储，注释标注 Enum 名 | 枚举字段用 `CharField` 存储字符串 |
| 主键统一 `BigIntField(pk=True)` | 使用 `IntField` 作为主键 |
| 时间字段用 `auto_now_add` / `auto_now` | 手动设置 `created_at` |
| 金额用 `Decimal(10,2)`（Tortoise: `fields.DecimalField(max_digits=10, decimal_places=2)`） | 金额用 `float` |
| `null=True` 显式声明可选字段 | 用空字符串 `""` 代替 `null` |

---

## 7. Schema 开发规范

### 7.1 定义

```python
from datetime import datetime
from pydantic import BaseModel, Field
from app.common.enums.user import UserRole, UserStatus

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=64)
    nickname: str = Field(..., min_length=1, max_length=32)
    phone: str | None = Field(None, pattern=r"^\d{11}$")

class UserOut(BaseModel):
    id: int
    username: str
    nickname: str
    phone: str | None
    avatar: str | None
    role: UserRole           # Enum → API 序列化为 "user" / "admin"
    status: UserStatus       # Enum → API 序列化为 "normal" / "disabled"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}   # 支持从 Tortoise Model 直接转换
```

### 7.2 约束

| ✅ 必须 | ❌ 禁止 |
|---------|---------|
| `Field(...)` 声明必填 + 校验规则 | 无校验的裸类型注解 |
| Out Schema 配置 `from_attributes = True` | 手动逐字段构造响应 |
| 枚举字段使用 `common/enums/` 中的 Enum 类型 | 枚举字段用 `int` 或 `str` |
| Create / Update / Out 分三个类 | 一个 Schema 同时用于请求和响应 |

---

## 8. Exception 规范

### 8.1 统一异常类

```python
# app/core/exceptions.py

class BusinessException(Exception):
    """业务异常"""
    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data
```

### 8.2 使用方式

```python
# ✅ 在 Service 层抛出业务异常
from app.core.exceptions import BusinessException

if existing_user:
    raise BusinessException(code=1001, message="Username already exists")

if not product:
    raise BusinessException(code=2001, message="Product not found")

if order.status != OrderStatus.PENDING:
    raise BusinessException(code=3002, message="Only pending orders can be cancelled")
```

### 8.3 错误码对照

| 模块 | 号段 | 已用 |
|------|------|------|
| 用户 | 1xxx | 1001-1006 |
| 商品 | 2xxx | 2001-2005 |
| 订单 | 3xxx | 3001-3006 |

新增错误码时在对应的号段内递增，**不得跨模块复用**。

### 8.4 约束

| ✅ 允许 | ❌ 禁止 |
|---------|---------|
| Service 层抛出 `BusinessException` | API 层直接写 `raise HTTPException(...)` |
| 错误码在对应的模块号段内 | 所有模块共用 `code=400` |
| `code` 用数字，`message` 用英文 | `message` 用中文 |
| 异常由 `middleware/exception.py` 统一处理 | 每个接口自己 try/except 构造错误响应 |

---

## 9. Logging 规范

### 9.1 日志格式

每条日志必须携带 `request_id`，确保一次请求的所有日志可以串联追踪。

```
[2026-07-23 10:30:00] INFO [req-abc123] [POST /api/v1/orders] user_id=1 status=201 duration=45ms
[2026-07-23 10:30:00] ERROR [req-abc123] [POST /api/v1/orders] user_id=1 error="stock deduction failed"
```

| 字段 | 说明 | 示例 |
|------|------|------|
| 时间戳 | ISO 格式 | `2026-07-23T10:30:00Z` |
| request_id | 请求唯一标识，由 `middleware/request_id.py` 注入 | `req-abc123` |
| path | 请求路径 | `POST /api/v1/orders` |
| user_id | 当前用户（如有认证） | `1` |
| duration | 耗时（访问日志） | `45ms` |
| 业务字段 | 按需追加 | `status=201` |

### 9.2 配置

`middleware/request_id.py` 在请求进入时生成 `request_id` 并注入到日志上下文：

```python
# app/middleware/request_id.py
import uuid
import logging

class RequestIDFilter(logging.Filter):
    """将 request_id 注入每条日志"""

    def filter(self, record):
        from app.middleware.request_id import _request_id_var
        record.request_id = _request_id_var.get("unknown")
        return True
```

日志在应用启动时通过 `setup_logging()` 统一初始化（参见 [architecture.md](../04_architecture/architecture.md#62-日志配置appmiddlewareloggingpy-中初始化)），format 中加入 `[%(request_id)s]`。

### 9.3 使用方式

```python
import logging

logger = logging.getLogger(__name__)

# ✅ Service 层日志——request_id 自动出现在每条日志中
logger.info("User registered: user_id=%d", user.id)
logger.warning("Rate limit triggered: ip=%s endpoint=%s path=%s", ip, endpoint, path)
logger.error("Order creation failed: user_id=%d error=%s", user_id, exc, exc_info=True)

# ✅ 中间件访问日志——记录 path + status + 耗时
logger.info("method=%s path=%s status=%d duration=%dms",
            request.method, request.url.path, status_code, duration_ms)
```

### 9.4 约束

| ✅ 必须 | ❌ 禁止 |
|---------|---------|
| 每条日志自动携带 `request_id`（由 middleware 注入） | 全局用 `print(...)` 输出日志 |
| 每个模块用 `logging.getLogger(__name__)` | 异常被吞掉不记录日志 |
| 关键操作记录 `logger.info()` | 日志中打印密码、Token 等敏感信息 |
| 异常用 `logger.error(..., exc_info=True)` | 手动在每条日志里手写 request_id（应由 Filter 统一注入） |

---

## 10. Response 规范

### 10.1 统一信封

整个项目所有接口返回完全一致的响应结构：

```json
{
    "code": 0,
    "message": "success",
    "data": {}
}
```

### 10.2 工厂函数

```python
# app/common/response.py

from typing import Any

def success(data: Any = None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}

def error(code: int, message: str, data: dict | None = None) -> dict:
    return {"code": code, "message": message, "data": data}
```

### 10.3 API 中使用

```python
from app.common.response import success

@router.post("/register", status_code=201)
async def register(data: UserCreate, service: UserService = Depends()):
    user = await service.create(data)
    return success(data=user)
```

异常响应由 `middleware/exception.py` 中的全局异常处理器自动封装，**API 层不需要手动构造错误响应**。

### 10.4 约束

| ✅ 必须 | ❌ 禁止 |
|---------|---------|
| `success(data, message)` 工厂函数 | 手写 `{"code": 0, ...}` |
| 业务异常统一交给 middleware 处理 | API 中 `return {"code": 1001, ...}` |
| `data` 无值时传 `None`，序列化为 `null` | `data` 传空字符串或省略字段 |
| 所有接口返回格式完全一致 | 某个接口返回 `{"status": "ok"}` |

---

## 11. Git 规范

### 11.1 Branch 命名

| 分支 | 用途 | 说明 |
|------|------|------|
| `main` | 生产就绪代码 | 只接受 PR 合入，禁止直接 push |
| `develop` | 开发集成分支 | feature/fix 分支合入的目标 |
| `feature/<name>` | 新功能开发 | 从 `develop` 分出，完成后提 PR 回合 |
| `fix/<name>` | Bug 修复 | 从 `develop` 或 `main` 分出（热修复） |
| `docs/<name>` | 文档更新 | 纯文档改动，跳过 CI 测试 |
| `refactor/<name>` | 代码重构 | 不改变功能的重构 |

```
main
  │
  └── develop
        │
        ├── feature/user-register
        ├── feature/product-crud
        ├── fix/order-stock-rollback
        └── docs/api-update
```

### 11.2 Commit 格式

```
<type>(<scope>): <subject>
```

| type | 说明 |
|------|------|
| feat | 新功能 |
| fix | 修复 bug |
| docs | 文档更新 |
| refactor | 代码重构（不改变功能） |
| style | 代码格式（不影响逻辑） |
| test | 测试相关 |
| chore | 构建/工具/依赖 |

| scope | 说明 |
|-------|------|
| user 或 auth | 用户模块 |
| product | 商品模块 |
| order | 订单模块 |
| api | API 层 |
| db | 数据库 |
| core | 基础设施 |
| docs | 文档 |

### 11.3 示例

```
✅ feat(user): add register api
✅ feat(order): add create order with stock deduction
✅ fix(order): fix stock rollback on cancel
✅ docs(api): update user api error codes
✅ refactor(product): extract product repo from service
✅ test(order): add order cancellation tests

❌ update
❌ fix bug
❌ 修改
❌ 111
❌ WIP
```

### 11.4 约束

| ✅ 必须 | ❌ 禁止 |
|---------|---------|
| 分支按 `feature/` / `fix/` / `docs/` 命名 | 直接 push 到 `main` |
| type + scope + 英文 subject | 无意义的提交信息 |
| 一个 commit 做一件事 | 把多个不相关的改动塞进一个 commit |
| PR 前 squash 掉 WIP 类的 commit | 把 `WIP`、`tmp`、`test` commit 推到远端 |

---

## 12. Testing 规范

### 12.1 测试结构

```
tests/
├── conftest.py          # 共享 fixtures：测试 DB、HTTP Client、测试用户
├── test_auth.py         # 注册、登录、Token 刷新
├── test_users.py        # 获取/修改个人信息、修改密码、头像上传
├── test_products.py     # 商品列表、详情、CRUD、上下架
└── test_orders.py       # 创建订单、列表、详情、取消
```

### 12.2 测试写法

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.anyio
async def test_register_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/register", json={
            "username": "testuser",
            "password": "123456",
            "nickname": "Test",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["username"] == "testuser"
        assert "password" not in data["data"]
```

### 12.3 测试覆盖清单

每个接口的测试必须覆盖以下场景：

| 场景 | 必须 |
|------|------|
| 正常流程 | ✅ |
| 参数校验失败（422） | ✅ |
| 认证失败（401） | ✅ |
| 权限不足（403） | ✅ |
| 资源不存在（404） | ✅ |
| 业务错误（如重复注册 1001） | ✅ |
| 边界值（如库存刚好为 0） | ✅ |
| 事务回滚 | ✅（订单创建 + 取消） |

---

## 13. Code Review Checklist

每次 PR 逐项检查：

### 架构与分层

- [ ] API 层只做参数提取和路由分发，**不写业务逻辑**
- [ ] Service 层**不直接调用其他 Service**（通过 Repository 跨领域）
- [ ] Repository 层**不包含业务判断**（`if status == 0: raise`）
- [ ] Model / Schema / Service / Repository 文件放在正确的目录

### 命名与格式

- [ ] 类名 PascalCase，函数 snake_case，常量 SNAKE_CASE
- [ ] Schema 后缀正确（Create / Out / Update / Login / ListItem）
- [ ] 新增 Enum 已在 `common/enums/` 中定义
- [ ] 无 Magic Number，使用 `common/constants/` 中的常量

### 异常与响应

- [ ] Service 层统一抛 `BusinessException`，不写 `HTTPException`
- [ ] 响应通过 `success()` / `error()` 工厂函数构造
- [ ] 错误码在对应模块号段内（用户 1xxx / 商品 2xxx / 订单 3xxx）

### 数据与事务

- [ ] 跨表操作使用 `in_transaction()` 包裹
- [ ] 金额用 `DecimalField(max_digits=10, decimal_places=2)`
- [ ] ORM 查询不返回 `password` 字段
- [ ] 枚举字段 DB 用 `SmallIntField`，API 用 Enum 类型

### 日志与测试

- [ ] 关键操作有 `logger.info()`
- [ ] 异常有 `logger.error(..., exc_info=True)`
- [ ] 无 `print(...)` 调用
- [ ] 正常流程 + 异常流程都有测试覆盖
- [ ] 测试 `assert` 了 `code`、HTTP 状态码和关键返回值

### 文档同步

- [ ] 新增/修改接口已更新对应的 API 文档（`docs/03_api/`）
- [ ] 新增 Enum 已更新 `api_design_conventions.md` §14 映射表
- [ ] 新增字段已同步 `er_diagram.dbml` 和 `database_design.md`
- [ ] 每个端点有 docstring

---

## 14. 依赖规则（Dependency Rules）

### 14.1 分层依赖图

```
                         ┌──────────┐
     schemas/  ←──────── │   API    │ ──────→  middleware/deps
     (Pydantic)          └────┬─────┘
                              │  ✅ 允许
                              ▼
                         ┌──────────┐
        common/  ←────── │ Service  │ ──────→  core/
        (enums,          └────┬─────┘          (security,
         constants,           │  ✅ 允许         redis,
         response)            ▼                 exceptions)
                         ┌──────────┐
                         │Repository│
                         └────┬─────┘
                              │  ✅ 允许
                              ▼
                         ┌──────────┐
                         │  Model   │
                         └──────────┘

   ═══════════════════════════════════════
   禁止反向引用（自下向上）
   ═══════════════════════════════════════
   Model        → Repository    ❌
   Model        → Service       ❌
   Repository   → Service       ❌
   Service      → API           ❌
   schemas/     → models/       ❌
   schemas/     → repositories/ ❌
   schemas/     → services/     ❌
```

### 14.2 允许的依赖

| 从 → 到 | 说明 |
|---------|------|
| API → Service | 路由调用业务逻辑 |
| API → schemas/ | 请求体校验、响应模型声明 |
| API → common/ | 引用 Enum、分页模型 |
| API → middleware/deps | 依赖注入认证、权限 |
| schemas/ → common/ | 引用 Enum、类型别名（Pydantic 字段类型） |
| Service → Repository | 业务逻辑调用数据访问 |
| Service → core/ | 调用 security、redis、抛出 BusinessException |
| Service → common/ | 使用 Enum、常量、response 工厂函数 |
| middleware/ → core/ | 验证 JWT（security）、捕获 BusinessException |
| middleware/ → repositories/ | 认证中间件通过 Repository 加载用户 |
| Repository → Model | ORM 查询 |
| Repository → common/ | 使用 Enum、Page[T] |
| common/ → （无） | common/ 不依赖任何应用层 |
| core/ → （无） | core/ 不依赖任何应用层 |
| utils/ → （无） | utils/ 不依赖任何应用层 |
| db/ → core/config | ORM 初始化读取数据库配置 |
| db/ → models（注册） | Tortoise.register_tortoise() 注册 Model 模块 |

### 14.3 禁止的依赖

| 从 → 到 | 原因 |
|---------|------|
| API → Repository | 不能跳过 Service 直接操作数据库 |
| API → Model | 不能直接写 `await User.create(...)` |
| Service → Service | 防止循环依赖，跨领域通过 Repository |
| Repository → Service | 不能反向调用业务逻辑 |
| Repository → core/redis | Redis 是基础设施，由 Service 层使用 |
| schemas/ → models/ | Schema 定义数据形状，不应依赖 ORM Model |
| schemas/ → repositories/ | Schema 是纯数据定义，不应引用数据访问层 |
| schemas/ → services/ | Schema 是纯数据定义，不应引用业务逻辑层 |
| Model → 任何应用层 | Model 只是表结构定义，不能有行为 |
| common/ → API / Service / Repository | common/ 是底层类型，不能反向依赖 |
| core/ → API / Service / Repository | core/ 是基础设施，不能反向依赖 |

### 14.4 检查方法

每新增一个 `import`，自问两个问题：

1. **方向对吗？** 被 import 的模块在依赖图中的位置是否低于（或平级于）当前模块？
2. **跳级了吗？** API 是否跨过 Service 直接 import 了 Repository？

如果任一答案是"是"，这个 import 就是错的。

---

## 15. 性能规范（Performance Guidelines）

### 15.1 N+1 查询问题

N+1 是最常见的 ORM 性能陷阱：先查 1 次主表，再在循环中对每条记录查关联表，导致 N 次额外查询。

```python
# ❌ N+1：先查 100 个订单，再循环查每个订单的明细——共 101 次 SQL
orders = await Order.filter(user_id=user_id)
for order in orders:
    items = await OrderItem.filter(order_id=order.id)  # 每条订单一次查询
    # ...

# ✅ 1 次查询：prefetch_related 用 2 条 SQL 完成
orders = await Order.filter(user_id=user_id).prefetch_related("items")
for order in orders:
    for item in order.items:  # 已预加载到内存，没有额外 SQL
        # ...
```

### 15.2 Tortoise ORM 预加载

| 方法 | 适用场景 | SQL 策略 |
|------|----------|----------|
| `select_related("field")` | FK / 一对一（Product → ProductExperience） | JOIN，1 条 SQL |
| `prefetch_related("field")` | 反向 FK / 一对多（Product → ProductImages，Order → OrderItems） | 2 条 SQL，内存拼接 |

```python
# 商品详情：关联体验扩展 + 图片列表
product = await Product.filter(id=product_id) \
    .select_related("experience") \          # FK / O2O → JOIN
    .prefetch_related("images") \            # 反向 FK → 2 条 SQL
    .first()

# 订单详情：关联明细
order = await Order.filter(id=order_id) \
    .prefetch_related("items") \
    .first()

# 用户订单列表：100 个订单 + 明细，3 条 SQL 解决（而非 101 条）
orders = await Order.filter(user_id=user_id) \
    .prefetch_related("items") \
    .all()
```

### 15.3 批量操作

```python
# ❌ 循环逐条插入——每条一次 INSERT，100 条 = 100 次 SQL
for image_data in images:
    await ProductImage.create(**image_data)

# ✅ 批量插入——1 条 SQL
await ProductImage.bulk_create([
    ProductImage(product_id=1, image_url=url, sort=i)
    for i, url in enumerate(image_urls)
])

# ❌ 循环逐条更新
for product in products:
    product.status = ProductStatus.OFFLINE
    await product.save()

# ✅ 批量更新——1 条 SQL
await Product.filter(id__in=ids).update(status=ProductStatus.OFFLINE)
```

### 15.4 只查需要的字段

```python
# ❌ SELECT * —— 查了所有字段
users = await User.all()

# ✅ 只查需要的列——减少网络传输和内存
users = await User.all().only("id", "username", "nickname")

# ✅ 不需要 Model 实例时用 values()——返回 dict，零 ORM 开销
usernames = await User.filter(status=UserStatus.NORMAL) \
    .values_list("username", flat=True)
```

### 15.5 分页永远带 limit

```python
# ❌ 全表加载——表里有 10 万条数据就会 OOM
all_orders = await Order.all()

# ✅ 分页查询
orders = await Order.all() \
    .offset((page - 1) * page_size) \
    .limit(page_size)
```

### 15.6 数据库索引

以下字段必须添加数据库索引（在 Model 定义或迁移中添加）：

| 字段 | 原因 |
|------|------|
| `users.username` | 登录查询（已有 UNIQUE） |
| `orders.user_id` | 按用户查订单列表 |
| `orders.status` | 按状态筛选 |
| `orders.order_no` | 精确查找（已有 UNIQUE） |
| `products.status` | 只查 online 商品 |
| `products.product_type` | 按类型筛选 |
| `product_images.product_id` | 按商品查图片 |
| `order_items.order_id` | 按订单查明细 |

Tortoise ORM 中通过 `index=True` 声明：

```python
user_id = fields.BigIntField(index=True)
status = fields.SmallIntField(default=0, index=True)
```

### 15.7 Redis 缓存

高频读取、低频变更的数据应使用 Redis 缓存：

```python
# ✅ 商品列表缓存——每次访问只查一次 DB
CACHE_KEY = "products:online"
cached = await redis_client.get(CACHE_KEY)
if cached:
    return json.loads(cached)

products = await Product.filter(status=ProductStatus.ONLINE).all()
await redis_client.setex(CACHE_KEY, 300, json.dumps(products))  # 5 分钟
return products
```

| 场景 | 缓存策略 | TTL |
|------|----------|-----|
| 商品列表（online） | 被动缓存，查询时缓存 | 5 分钟 |
| 用户信息（/users/me） | 写入时失效（修改后删除缓存） | — |
| 接口限流计数器 | Redis INCR + EXPIRE | 按窗口 |

### 15.8 检查清单

Code Review 中涉及性能的检查项：

- [ ] 循环中无 `await` 查询——必须用 `prefetch_related` 预加载
- [ ] 批量写入用 `bulk_create` / `bulk_update`，非循环 `create()` / `save()`
- [ ] 列表接口有分页（`limit` + `offset`）
- [ ] 筛选字段（`user_id`、`status`、`product_type`）有无索引
- [ ] 高频查询是否有缓存（Redis）
- [ ] `SELECT *` 是否可用 `.only()` 精简
