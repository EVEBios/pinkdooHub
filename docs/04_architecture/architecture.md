# pinkdooHub 项目架构

---

## 1. 技术选型

### 1.1 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.139 |
| ORM | Tortoise ORM | 1.1.7 |
| 数据校验 | Pydantic | 2.13 |
| 数据库 | MySQL（生产）/ SQLite（开发） | - |
| 缓存 | Redis | - |
| 迁移工具 | Aerich | 0.9.3 |
| ASGI 服务器 | Uvicorn | 0.51 |
| 配置管理 | pydantic-settings | 2.14 |
| 密码加密 | passlib[bcrypt] | 1.7.4 |
| 时区数据 | tzdata | —（Windows 必需） |

### 1.2 选型理由

**FastAPI**

| 理由 | 说明 |
|------|------|
| 异步原生 | 基于 Starlette + asyncio，天然支持高并发 |
| 自动文档 | OpenAPI / Swagger 文档零配置生成 |
| 类型安全 | 与 Pydantic 深度集成，请求/响应自动校验 |
| 生态成熟 | 中间件、依赖注入、后台任务等开箱即用 |

**Tortoise ORM**

| 理由 | 说明 |
|------|------|
| 异步原生 | 全异步查询引擎，与 FastAPI 事件循环无缝配合 |
| Django 风格 | API 设计与 Django ORM 接近，学习成本低 |
| Aerich 迁移 | 内置迁移工具，开发体验与 Alembic 同级 |
| 轻量 | 无需 SQLAlchemy 的重量级抽象 |

**Redis**

| 理由 | 说明 |
|------|------|
| Token 黑名单 | JWT 登出/刷新时实现 Token 失效 |
| 接口限流 | 登录、注册等敏感接口的频率控制 |
| 缓存 | 商品列表等高频读取数据的缓存 |
| 轻量 | 单机即可满足 v0.1-v1.0 需求 |

**MySQL**

| 理由 | 说明 |
|------|------|
| 事务支持 | 订单创建（扣库存 + 生成订单）需要 ACID |
| 生态 | 托管服务成熟，运维成本低 |
| 开发便利 | 开发环境用 SQLite（免安装），生产切 MySQL 零代码改动 |

---

## 2. 项目目录结构

```
pinkdooHub/
│
├── app/                        # 应用主目录
│   ├── main.py                 # FastAPI 应用入口，路由挂载，生命周期管理
│   ├── api/                    # API 层 —— 路由定义 + 参数校验
│   │   ├── __init__.py
│   │   ├── v1/                 # v1 版本路由
│   │   │   ├── __init__.py
│   │   │   ├── auth.py         #   POST /auth/register  /auth/login  /auth/refresh
│   │   │   ├── users.py        #   GET/PUT /users/me  /users/me/password  /users/me/avatar
│   │   │   ├── admin_users.py  #   GET /admin/users  /admin/users/{id}  disable/enable
│   │   │   ├── products.py     #   GET /products  /products/{id}
│   │   │   ├── admin_products.py#  POST/PUT /products  online/offline/stock  images
│   │   │   ├── orders.py       #   POST /orders  GET /orders  /orders/{id}  cancel
│   │   │   └── admin_orders.py #   GET /admin/orders  /admin/orders/{id}  complete
│   │   └── deps.py             # 公共依赖：get_current_user, get_admin_user, get_db
│   │
│   ├── models/                 # 数据模型层 —— Tortoise ORM Model 定义
│   │   ├── __init__.py
│   │   ├── user.py             #   User
│   │   ├── product.py          #   Product, ProductExperience, ProductKit, ProductImage
│   │   └── order.py            #   Order, OrderItem
│   │
│   ├── schemas/                # Pydantic Schema —— 请求/响应数据结构
│   │   ├── __init__.py
│   │   ├── user.py             #   UserCreate, UserLogin, UserOut, UserUpdate, ...
│   │   ├── product.py          #   ProductCreate, ProductUpdate, ProductOut, ...
│   │   └── order.py            #   OrderCreate, OrderOut, OrderItemOut, ...
│   │
│   ├── services/               # 业务逻辑层 —— 跨模型、带事务的业务编排
│   │   ├── __init__.py
│   │   ├── auth_service.py     #   注册、登录、Token 签发/刷新
│   │   ├── user_service.py     #   个人资料、密码、头像
│   │   ├── product_service.py  #   商品 CRUD、上下架、库存
│   │   └── order_service.py    #   下单（扣库存+生成订单）、取消（恢复库存）
│   │
│   ├── repositories/           # 数据访问层 —— 封装数据库查询
│   │   ├── __init__.py
│   │   ├── user_repo.py        #   User 查询/创建/更新
│   │   ├── product_repo.py     #   Product + 扩展表查询/创建/更新
│   │   └── order_repo.py       #   Order + OrderItem 查询/创建/更新
│   │
│   ├── common/                  # 公共模块 —— 跨领域共享的类型与常量
│   │   ├── __init__.py
│   │   ├── response.py         #   统一响应信封（success / error 工厂函数）
│   │   ├── pagination.py       #   分页请求/响应 Pydantic Model
│   │   ├── types.py            #   通用类型别名（TypeAlias）
│   │   ├── enums/              #   Enum 定义（按模块拆分）
│   │   │   ├── __init__.py
│   │   │   ├── user.py         #     UserRole, UserStatus
│   │   │   ├── product.py      #     ProductType, ProductStatus
│   │   │   └── order.py        #     OrderStatus
│   │   └── constants/          #   全局常量 —— 消除 Magic Number
│   │       ├── __init__.py
│   │       ├── pagination.py  #     MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE
│   │       ├── upload.py      #     UPLOAD_MAX_SIZE, ALLOWED_IMAGE_TYPES
│   │       ├── validation.py  #     USERNAME_MIN_LEN, PASSWORD_MAX_LEN, ...
│   │       └── defaults.py    #     DEFAULT_AVATAR
│   │
│   ├── core/                   # 核心基础设施 —— 与领域和 HTTP 无关的底层能力
│   │   ├── __init__.py
│   │   ├── config.py           #   配置类（从 .env 读取）
│   │   ├── security.py         #   JWT 签发/验证、密码哈希
│   │   ├── redis.py            #   Redis 连接与工具函数
│   │   └── exceptions.py       #   业务异常类定义（BusinessException）
│   │
│   ├── middleware/              # 中间件 —— HTTP 生命周期切面
│   │   ├── __init__.py
│   │   ├── request_id.py       #   为每个请求生成唯一 RequestID
│   │   ├── auth.py             #   JWT 认证中间件（提取 Token → 注入 current_user）
│   │   ├── logging.py          #   请求日志（记录 method、path、耗时、状态码）
│   │   ├── cors.py             #   CORS 跨域配置
│   │   └── exception.py        #   全局异常捕获 → 统一错误响应
│   │
│   ├── db/                     # 数据库
│   │   ├── __init__.py
│   │   └── database.py         #   Tortoise ORM 初始化 + 连接配置
│   │
│   └── utils/                  # 纯工具函数 —— 无状态、无副作用
│       ├── __init__.py
│       └── string_utils.py     #   字符串格式化、脱敏等纯函数
│
├── docs/                       # 项目文档
│   ├── 01_requirements/        #   需求文档
│   ├── 02_database/            #   数据库设计 + ER 图
│   ├── 03_api/                 #   API 设计规范 + 各模块接口文档
│   └── 04_architecture/        #   架构文档
│
├── tests/                      # 测试目录
│   ├── conftest.py             #   pytest fixtures（测试 DB、测试 Client）
│   ├── test_auth.py
│   ├── test_users.py
│   ├── test_products.py
│   └── test_orders.py
│
├── migrations/                 # Aerich 数据库迁移文件
│   └── models/
│
├── requirements.txt            # Python 依赖
├── pyproject.toml              # 项目元数据 + 工具配置
├── .env                        # 环境变量（不入 git）
├── .env.example                # 环境变量模板
└── README.md
```

---

## 3. 分层架构

```
┌─────────────────────────────────────────┐
│                 前端 / 客户端              │
└────────────────┬────────────────────────┘
                 │  HTTP Request
                 ▼
┌─────────────────────────────────────────┐
│  API 层 (app/api/)                       │
│  · 路由注册 + 参数校验 (Pydantic)         │
│  · 依赖注入 (认证、权限)                  │
│  · 调用 Service，返回 Response            │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Service 层 (app/services/)              │
│  · 业务逻辑编排                           │
│  · 跨模型事务管理                         │
│  · 权限校验 + 数据校验                    │
│  · 调用 Repository + 外部服务（Redis）    │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Repository 层 (app/repositories/)       │
│  · 封装数据库查询                         │
│  · 提供 CRUD 原子操作                     │
│  · 不包含业务逻辑                         │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Model 层 (app/models/)                  │
│  · Tortoise ORM Model 定义               │
│  · 表结构 + 关系 + 字段约束               │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  MySQL / SQLite                          │
└─────────────────────────────────────────┘
```

### 3.1 API 层（app/api/）

**职责**：接收请求 → 校验参数 → 调用 Service → 返回响应

```python
# app/api/v1/auth.py
from fastapi import APIRouter, Depends
from app.schemas.user import UserCreate, UserLogin, TokenOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=TokenOut, status_code=201)
async def register(data: UserCreate, service: AuthService = Depends()):
    """用户注册"""
    return await service.register(data)

@router.post("/login", response_model=TokenOut)
async def login(data: UserLogin, service: AuthService = Depends()):
    """用户登录"""
    return await service.login(data)
```

**约束**：
- 只做参数提取和路由分发，**不写业务逻辑**
- 所有请求体用 Pydantic Schema 校验
- 通过 `Depends()` 注入 Service

### 3.2 Service 层（app/services/）

**职责**：编排业务逻辑、管理事务边界、协调多个 Repository

```python
# app/services/order_service.py
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.core.exceptions import BusinessException

class OrderService:
    def __init__(self, order_repo: OrderRepository = Depends(),
                       product_repo: ProductRepository = Depends()):
        self.order_repo = order_repo
        self.product_repo = product_repo

    async def create_order(self, user_id: int, data: OrderCreate) -> Order:
        # 1. 校验商品存在且上架
        for item in data.items:
            product = await self.product_repo.get_online(item.product_id)
            if not product:
                raise BusinessException(code=3003, ...)
        # 2. 在事务中：扣库存 → 生成订单 → 写入明细
        async with in_transaction():
            for item in data.items:
                await self.product_repo.deduct_stock(item.product_id, item.quantity)
            order = await self.order_repo.create(user_id, data)
        return order
```

**约束**：
- 跨模型、需要事务的操作在此层编排
- 调用 Repository 获取/持久化数据
- 抛出 `BusinessException` 表达业务错误，由全局异常处理器统一捕获
- **Service 之间禁止直接调用**：需要其他领域的数据时，通过该领域对应的 Repository 获取

```
// ❌ 禁止：Service 直接依赖 Service
OrderService → UserService   // 很快形成循环依赖

// ✅ 正确：Service 只依赖 Repository
OrderService → UserRepository   // 需要用户信息时查 User 表
OrderService → ProductRepository// 需要商品信息时查 Product 表
```

> 如果某段逻辑需要协调两个领域（如"下单时检查用户是否被禁用"），
> 这仍然是 OrderService 的职责，它通过 `UserRepository.get_by_id()` 获取用户，
> 自己判断 `user.status`，而不是调用 `UserService.is_active()`。

### 3.3 Repository 层（app/repositories/）

**职责**：封装数据库查询，提供原子化的 CRUD 方法

```python
# app/repositories/user_repo.py
from app.models.user import User

class UserRepository:
    async def get_by_id(self, user_id: int) -> User | None:
        return await User.filter(id=user_id).first()

    async def get_by_username(self, username: str) -> User | None:
        return await User.filter(username=username).first()

    async def create(self, **kwargs) -> User:
        return await User.create(**kwargs)
```

**约束**：
- 每个方法只做**一类查询**，不包含业务判断
- 不跨 Model（不在这里 JOIN 其他表做业务逻辑）
- 返回 Model 实例或 `None`

### 3.4 Model 层（app/models/）

**职责**：定义表结构、字段约束、模型关系

```python
# app/models/user.py
from tortoise import fields
from tortoise.models import Model

class User(Model):
    id = fields.BigIntField(pk=True)
    username = fields.CharField(max_length=32, unique=True)
    password = fields.CharField(max_length=128)
    nickname = fields.CharField(max_length=32)
    phone = fields.CharField(max_length=11, null=True)
    avatar = fields.CharField(max_length=256, null=True)
    role = fields.SmallIntField(default=1)      # 1:user 2:admin
    status = fields.SmallIntField(default=1)     # 1:normal 0:disabled
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users"
```

---

### 3.5 中间件层（app/middleware/）

**定位**：中间件作用于 HTTP 请求/响应的切面，与业务逻辑层（Service）和核心组件（Core）是正交关系。

```
        core/                        middleware/                    api/service
   ┌─────────────┐              ┌──────────────────┐           ┌─────────────┐
   │ config      │              │  request_id       │           │             │
   │ security    │    vs.       │  auth             │   vs.     │  business   │
   │ redis       │              │  logging          │           │  logic      │
   │             │              │  cors             │           │             │
   │ 与 HTTP     │              │  exception        │           │ 与 HTTP     │
   │ 生命周期    │              │                   │           │ 绑定但不    │
   │ 无关        │              │  Starlette        │           │ 是切面      │
   └─────────────┘              │  Middleware 机制   │           └─────────────┘
                                └──────────────────┘
```

**为什么不能全部放在 `core/` 里？**

| 维度 | core/ | middleware/ |
|------|-------|-------------|
| 依赖方向 | 不依赖 HTTP（可被 CLI、脚本引用） | 依赖 Starlette 的 Middleware 协议 |
| 生命周期 | 应用级（启动一次） | 请求级（每个请求触发） |
| 典型内容 | 配置类、加密工具、Redis 客户端 | RequestID、Auth、CORS、日志、异常捕获 |
| 测试方式 | 纯单元测试 | 需要 `TestClient` 或 ASGI transport |

**各文件职责**

| 文件 | 职责 | 触发时机 |
|------|------|----------|
| `request_id.py` | 为每个请求生成 `X-Request-ID`，注入到日志上下文 | 请求进入 |
| `auth.py` | 解析 Authorization Header → 验证 JWT → 注入 `request.state.user` | 路由匹配前 |
| `logging.py` | 记录 `method path status_code duration_ms` | 响应返回时 |
| `cors.py` | 配置允许的 Origin、Method、Header | 预检请求 (OPTIONS) |
| `exception.py` | 捕获所有未处理异常 → 封装为 `{code, message}` 统一信封 | 异常发生时 |

**执行顺序**

```
Request
  │
  ├─[1] request_id    → 生成 X-Request-ID，注入 context
  ├─[2] cors          → 处理 OPTIONS 预检，添加 CORS 响应头
  ├─[3] logging       → 记录开始时间戳
  ├─[4] auth          → 验证 JWT（白名单路由跳过）
  │
  ▼
  Router → API → Service → Repository → DB
  │
  ▼
  ├─[5] exception     → 捕获异常，返回统一错误格式
  ├─[6] logging       → 计算耗时，写入访问日志
  │
  ▼
Response
```

> **注意**：中间件顺序至关重要。`request_id` 必须在最外层（确保异常日志也能携带 RequestID），`exception` 也必须在最外层（捕获所有下游异常）。

---

### 3.6 公共模块（app/common/）

**定位**：存放被整个应用共享的类型定义、常量和工具模型。与 `core/`（底层基础设施）和 `utils/`（纯函数）是正交关系。

**common/ vs core/ vs utils/**

```
common/                     core/                       utils/
───────────────────         ───────────────────        ───────────────────
被所有层引用                被 core/middleware 引用      被任意层按需引用
与业务领域相关               与领域无关                   无状态、无副作用
Pydantic Model / Enum       config / security / redis   字符串处理 / 格式化
```

| 目录 | 放什么 | 不放什么 |
|------|--------|----------|
| `common/` | 通用响应格式、分页模型、Enum、常量、类型别名 | 配置类、中间件、工具函数 |
| `core/` | 配置、加解密、Redis 客户端、异常类 | Pydantic Model、Enum、业务常量 |
| `utils/` | 纯函数工具（字符串格式化、脱敏等） | 带状态的类、HTTP 相关代码 |

**各文件/子目录职责**

| 文件 | 职责 |
|------|------|
| `response.py` | `success(data)` / `error(code, msg)` 工厂函数，构造统一响应信封 |
| `pagination.py` | `PageParams`（请求） / `PageResponse`（响应） Pydantic Model |
| `types.py` | 通用类型别名，如 `UserId = int`、`JsonDict = dict[str, Any]` |
| `enums/` | Enum 定义，按模块拆分（避免 500+ 行巨石文件） |
| `constants/` | 消除 Magic Number，`USERNAME_MIN_LENGTH` 而非 `3` |

**enums/ 示例**

```python
# app/common/enums/user.py
from enum import IntEnum

class UserRole(IntEnum):
    USER = 1
    ADMIN = 2

class UserStatus(IntEnum):
    DISABLED = 0
    NORMAL = 1

# app/common/enums/product.py
class ProductType(IntEnum):
    EXPERIENCE = 1
    KIT = 2

class ProductStatus(IntEnum):
    DRAFT = 0
    ONLINE = 1
    OFFLINE = 2

# app/common/enums/order.py
class OrderStatus(IntEnum):
    PENDING = 0
    PAID = 1
    CANCELLED = 2
    COMPLETED = 3
```

**constants/ 示例**

```python
# app/common/constants/pagination.py
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

# app/common/constants/upload.py
UPLOAD_MAX_SIZE = 2 * 1024 * 1024
ALLOWED_IMAGE_TYPES = ("jpg", "png", "webp")

# app/common/constants/validation.py
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 64

# app/common/constants/defaults.py
DEFAULT_AVATAR = "https://cdn.example.com/default-avatar.png"
```

**constants vs config**

| 维度 | core/config.py | common/constants/ |
|------|---------------|-------------------|
| 可变性 | 随环境变化（dev / prod） | 固定不变，业务规则 |
| 来源 | `.env` 文件 | 代码中直接定义 |
| 何时修改 | 部署时切换 | 需求变更时改代码 |

```python
# ❌ Magic Number
if len(username) < 3 or len(username) > 32:
    raise ValueError(...)

# ✅ 语义清晰
from app.common.constants.validation import USERNAME_MIN_LENGTH, USERNAME_MAX_LENGTH
if not (USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH):
    raise ValueError(...)
```

---

### 3.7 工具函数（app/utils/）

**定位**：纯函数、无副作用、无业务含义。任何看起来像"万能工具箱"的代码都不应该放在这里。

| ✅ 放这里 | ❌ 不放这里 |
|-----------|------------|
| 字符串脱敏（手机号中间四位替换） | HTTP 响应构造 |
| 时间格式化辅助 | 分页逻辑 |
| 文件路径安全拼接 | Enum 定义 |
| 简单的数据转换 | 业务常量 |
| 纯算法（如验证码生成） | 任何带 FastAPI 依赖的代码 |

```python
# app/utils/string_utils.py

def mask_phone(phone: str) -> str:
    """138****8000"""
    if not phone or len(phone) != 11:
        return phone
    return phone[:3] + "****" + phone[7:]

def mask_email(email: str) -> str:
    """a***@example.com"""
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    return name[0] + "***" + "@" + domain
```

---

## 4. 请求流程

以"创建订单"为例，展示一次完整调用链：

```
 POST /api/v1/orders
 Authorization: Bearer <token>
 { "items": [...], "remark": "..." }
         │
         ▼
┌─[1]───────────────────────────────────────────────────┐
│  Middleware 链（按顺序）                                │
│  request_id → cors → logging(计时开始) → auth(验JWT)    │
│  生成 X-Request-ID，注入日志上下文，注入 current_user   │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[2]───────────────────────────────────────────────────┐
│  Deps: get_current_user() / get_db()                  │
│  依赖注入，解析出 user_id 和 db 连接                    │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[3]───────────────────────────────────────────────────┐
│  API: orders.py  →  router.post("/orders")            │
│  · Pydantic 校验请求体 (OrderCreate schema)            │
│  · 提取 user_id, data                                 │
│  · 调用 service.create_order(user_id, data)           │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[4]───────────────────────────────────────────────────┐
│  Service: order_service.py → create_order()           │
│  · 遍历 items，调 product_repo 校验商品 + 库存         │
│  · 商品不存在/下架 → raise BusinessException(3003)     │
│  · 库存不足 → raise BusinessException(3004)            │
│  · 开启事务：扣库存 → 写 orders → 写 order_items       │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[5]───────────────────────────────────────────────────┐
│  Repository: product_repo.deduct_stock()               │
│             order_repo.create()                        │
│  · Tortoise ORM 生成 SQL: UPDATE ... SET stock = ...  │
│  · Tortoise ORM 生成 SQL: INSERT INTO orders ...      │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[6]───────────────────────────────────────────────────┐
│  MySQL                                                │
│  · 执行 SQL → 返回结果                                 │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[7]───────────────────────────────────────────────────┐
│  响应：Service 返回 Order 对象                         │
│  → Pydantic 序列化为 OrderOut schema                   │
│  → FastAPI 封装为统一信封 { code, message, data }      │
│  → HTTP 201                                           │
└───────────────────────────────────────────────────────┘
```

---

## 5. 配置管理

### 5.1 配置文件（.env）

```ini
# 应用
APP_NAME=pinkdooHub
APP_ENV=development          # development | production | testing
APP_DEBUG=true

# 数据库
DB_ENGINE=sqlite             # sqlite | mysql
DB_SQLITE_PATH=./db.sqlite3
# DB_HOST=127.0.0.1          # MySQL 时启用
# DB_PORT=3306
# DB_USER=root
# DB_PASSWORD=
# DB_NAME=pinkdoohub

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE=7200    # 2 小时
JWT_REFRESH_TOKEN_EXPIRE=604800 # 7 天
```

### 5.2 配置类（app/core/config.py）

```python
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings

_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")

class Settings(BaseSettings):
    # 应用
    app_name: str = "pinkdooHub"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = True

    # 数据库
    db_engine: str = "sqlite"
    db_sqlite_path: str = "./db.sqlite3"
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "pinkdoohub"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire: int = 7200
    jwt_refresh_token_expire: int = 604800

    model_config = {
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
    }

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.app_env not in ("development", "testing", "production"):
            raise ValueError(f"APP_ENV must be development/testing/production")
        if self.db_engine not in ("sqlite", "mysql"):
            raise ValueError(f"DB_ENGINE must be sqlite or mysql")
        if self.app_env == "production" and self.jwt_secret_key == "dev-secret-change-in-production":
            raise ValueError("JWT_SECRET_KEY must be set in production")
        return self

settings = Settings()
```

### 5.3 环境切换

Tortoise ORM 根据 `DB_ENGINE` 自动切换：

```python
# app/db/database.py
def get_db_config():
    if settings.db_engine == "sqlite":
        return {
            "connections": {"default": f"sqlite://{settings.db_sqlite_path}"},
            "apps": {"models": {"models": ["app.models"], ...}},
        }
    return {
        "connections": {
            "default": f"mysql://{settings.db_user}:{settings.db_password}"
                       f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
        },
        ...
    }
```

---

## 6. 基础组件

### 6.1 异常定义（app/core/exceptions.py）

异常类定义在 `core/`（纯 Python，不依赖 HTTP）；全局异常处理器在 `middleware/exception.py`（依赖 Starlette，捕获异常并序列化为 JSON 响应）。

```python
# app/core/exceptions.py  —— 只定义异常类

class BusinessException(Exception):
    """业务异常，携带 code 和 message"""
    def __init__(self, code: int, message: str, data: dict = None):
        self.code = code
        self.message = message
        self.data = data
```

```python
# app/middleware/exception.py  —— 全局异常处理器

from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.exceptions import BusinessException

async def business_exception_handler(request: Request, exc: BusinessException):
    return JSONResponse(
        status_code=400,
        content={"code": exc.code, "message": exc.message, "data": exc.data}
    )

async def generic_exception_handler(request: Request, exc: Exception):
    """兜底：捕获未预期的异常"""
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "Internal server error"}
    )
```

### 6.2 日志配置（app/middleware/logging.py 中初始化）

日志初始化在应用启动时执行，`setup_logging()` 可在 `main.py` 的 `lifespan` 中调用：

```python
import logging
import sys

def setup_logging():
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    logging.getLogger("tortoise").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
```

### 6.3 认证（app/core/security.py）

```python
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"])

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(seconds=settings.jwt_access_token_expire)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "access"},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )

def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(seconds=settings.jwt_refresh_token_expire)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "type": "refresh"},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
```

### 6.4 依赖注入（app/api/deps.py）

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from app.core.security import decode_token
from app.repositories.user_repo import UserRepository

security = HTTPBearer()

async def get_current_user(
    token: str = Depends(security),
    user_repo: UserRepository = Depends()
) -> User:
    payload = decode_token(token, token_type="access")
    user = await user_repo.get_by_id(int(payload["sub"]))
    if not user or user.status != 1:
        raise HTTPException(status_code=401)
    return user

async def get_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    if current_user.role != 2:        # 2 = admin
        raise HTTPException(status_code=403)
    return current_user
```

### 6.5 Redis 工具（app/core/redis.py）

```python
import redis.asyncio as aioredis

redis_client = aioredis.from_url(settings.redis_url)

# Token 黑名单：登出或 refresh 后将旧 token 加入
async def blacklist_token(token: str, ttl: int):
    await redis_client.setex(f"bl:{token}", ttl, "1")

async def is_token_blacklisted(token: str) -> bool:
    return await redis_client.exists(f"bl:{token}")

# 接口限流：key = ip + endpoint
async def rate_limit(key: str, max_requests: int, window: int) -> bool:
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, window)
    return current <= max_requests
```
