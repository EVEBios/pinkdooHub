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
| MySQL 异步驱动 | asyncmy | 0.2.11 |
| 缓存 | Redis | - |
| 迁移工具 | Aerich | 0.9.3 |
| ASGI 服务器 | Uvicorn | 0.51 |
| 配置管理 | pydantic-settings | 2.14 |
| 密码加密 | passlib[bcrypt] | 1.7.4 |
| 时区数据 | tzdata | —（Windows 必需） |
| multipart 解析 | python-multipart | 0.0.32 |

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
| Aerich 迁移 | Tortoise ORM 配套迁移工具，提供版本化升级与降级流程 |
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
| 事务支持 | Order、OrderItem、状态变迁与 AuditLog 需要 ACID；Phase 4.3 再把库存事务接入订单 |
| 生态 | 托管服务成熟，运维成本低 |
| 开发便利 | 开发环境用 SQLite（免安装），生产切 MySQL 零代码改动 |

生产环境由 Tortoise ORM 通过 `asyncmy` 连接 MySQL。该驱动是生产数据库路径的必需运行时依赖；SQLite 开发和测试环境仍使用 `aiosqlite`。

---

## 2. 项目目录结构

```
pinkdooHub/
│
├── app/                        # 应用主目录
│   ├── main.py                 # FastAPI 应用入口，路由挂载，生命周期管理
│   ├── api/                    # API 层 —— 路由定义 + 参数校验
│   │   ├── __init__.py
│   │   ├── mappers/            # ORM 聚合 → 显式字典 → Out Schema
│   │   │   ├── __init__.py
│   │   │   └── product.py      # Product 列表、详情与 mutation 响应映射
│   │   ├── forms/              # multipart/form-data Pydantic 请求模型
│   │   │   └── product.py      # Product/Option 图片上传表单
│   │   ├── v1/                 # v1 版本路由
│   │   │   ├── __init__.py
│   │   │   ├── auth.py         #   POST /auth/register  /auth/login  /auth/refresh
│   │   │   ├── users.py        #   GET/PUT /users/me  /users/me/password  /users/me/avatar
│   │   │   ├── admin_users.py  #   GET /admin/users  /admin/users/{id}  disable/enable
│   │   │   ├── products.py     #   GET /products  /products/{id}
│   │   │   ├── admin_products.py#  POST /admin/products/experience|kit, PATCH/DELETE /admin/products/{id}, PATCH online/offline/price/stock
│   │   │   ├── orders.py       #   POST /orders  GET /orders  /orders/{id}  cancel
│   │   │   └── admin_orders.py #   GET /admin/orders  /admin/orders/{id}  paid/complete/audit-logs
│   │   ├── admin.py           #  GET /admin/users  /admin/config (RBAC 演示)
│   │   ├── deps.py             # 公共依赖与 Product 组合根
│   │   ├── uploads.py          # 文件存储 → Service → 失败补偿
│   │   └── static.py           # 本地上传目录的延迟静态挂载
│   │
│   ├── models/                 # 数据模型层 —— Tortoise ORM Model 定义
│   │   ├── __init__.py
│   │   ├── base.py             #   BaseModel（id, created_at, updated_at）
│   │   ├── fields.py           #   StrictDecimalField 等 ORM 字段扩展
│   │   ├── validators.py       #   Model 字段级通用校验器
│   │   ├── user.py             #   User
│   │   ├── product.py          #   Product
│   │   ├── experience_option.py#   ExperienceOption
│   │   ├── product_kit.py      #   ProductKit
│   │   ├── product_image.py    #   ProductImage
│   │   ├── audit_log.py        #   AuditLog
│   │   └── order.py            #   Order, OrderItem
│   │
│   ├── schemas/                # Pydantic Schema —— 请求/响应数据结构
│   │   ├── __init__.py
│   │   ├── user.py             #   UserCreate, UserOut, UserUpdate, UserListItem, ...
│   │   ├── product.py          #   Product 请求体与列表查询参数
│   │   ├── product_response.py #   Product 原子、列表、详情与写操作 Out Schema
│   │   ├── order.py            #   Order 请求体与列表查询参数（Phase 4.2）
│   │   └── order_response.py   #   Order 用户端/管理端响应白名单（Phase 4.2）
│   │
│   ├── services/               # 业务逻辑层 —— 跨模型、带事务的业务编排
│   │   ├── __init__.py
│   │   ├── auth_service.py     #   注册、登录、Token 签发/刷新
│   │   ├── user_service.py     #   个人资料、密码、头像
│   │   ├── product_service.py  #   商品 CRUD、上下架、Option 管理
│   │   └── order_service.py    #   Experience 下单、查询与状态机；Phase 4.2 不操作库存
│   │
│   ├── validators/             # 业务校验层 —— 状态变迁前的完整性校验
│   │   ├── __init__.py
│   │   └── product_validator.py #  ProductValidator.validate_before_online()
│   │
│   ├── storage/                # 外部对象存储适配边界
│   │   ├── __init__.py
│   │   └── image.py        #   Product 图片校验、本地原子存储与补偿删除
│   │
│   ├── tasks/                  # 外部调度器可重复执行的运维任务入口
│   │   └── product_image_cleanup.py # ProductImage 延迟文件清理命令
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
│   │   │   ├── product.py      #     ProductType, ProductStatus, DayType
│   │   │   └── order.py        #     OrderStatus (Phase 4.2)
│   │   ├── constants/          #   全局常量 —— 消除 Magic Number
│   │       ├── __init__.py
│   │       ├── pagination.py  #     MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE
│   │       ├── upload.py      #     UPLOAD_MAX_SIZE, ALLOWED_IMAGE_TYPES
│   │       ├── validation.py  #     USERNAME_MIN_LEN, PASSWORD_MAX_LEN, ...
│   │       ├── product.py     #     Product 字段长度、金额、库存与图片排序边界
│   │       ├── order.py       #     Order Item/备注/编号/状态展示边界（Phase 4.2）
│   │       └── defaults.py    #     DEFAULT_AVATAR
│   │   └── order_number.py    #   标准库 OD + Crockford Base32 ULID 生成器
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
│   │   ├── database.py         #   Tortoise ORM 初始化 + 连接配置
│   │   └── indexes.py          #   稳定命名的跨数据库 UniqueIndex
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

> **目录状态说明：** 上图同时包含已实现结构和后续 Phase 的目标结构，不能仅凭目录图判断功能已经存在。Phase 4.1 已实现 Product 全部 Model、Repository、Validator、Service、API Mapper、22 个端点、图片存储和清理任务。Phase 4.2 Order v1.0 的契约、领域语言、严格 Schema、Model/离线迁移、编号生成器、Repository、创建/状态/查询 Service、API Mapper、`get_order_service()` 组合根、4 个用户端与 5 个 ADMIN+ 端点、完整 HTTP 边界矩阵和最终 Review 均已完成。

Product Schema 按变化原因拆分：`product.py` 只负责不可信外部输入（请求体与查询参数，未知 JSON 字段拒绝），`product_response.py` 只负责可信内部数据到公开 API 的白名单输出。两者都只能依赖标准库、Pydantic 和 `app/common/`；响应模块可复用请求模块中的纯字段类型，但不得依赖 Model、Repository 或 Service。

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
│  · 调用 Service 与同步 Mapper              │
│  · Out Schema 校验后返回 Response          │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  Service 层 (app/services/)              │
│  · 业务逻辑编排                           │
│  · 跨模型事务管理                         │
│  · 调用 Repository 获取已加载聚合          │
│  · 调用同步纯 Validator + 外部服务         │
└───────────┬─────────────────┬───────────┘
            │                 │
            ▼                 ▼
┌─────────────────────┐  ┌────────────────┐
│ Validator 层         │  │ Repository 层  │
│ · 同步、纯计算        │  │ · 数据库查询    │
│ · 只读取已加载聚合    │  │ · 原子 CRUD     │
│ · 返回 None 或抛异常  │  │ · 无业务逻辑    │
│ · 无下游依赖/I/O      │  └───────┬────────┘
└─────────────────────┘          │
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

`app/api/mappers/` 属于 API 层的响应适配边界。Mapper 同步读取 Service 返回的、由 Repository 完成预加载的 ORM 聚合，计算 `cover_image`、`display_price`、dimensions、available 和展示 label，以显式字段白名单字典构造对应 Out Schema。标准链路为：

```text
ProductService 返回 ORM/Page
  → API Mapper 只读已加载关系并构造显式字典
  → Product Out Schema 校验与序列化
  → Router 调用 success()
```

Mapper 不查询或修改数据库，不调用 Service、Repository、Redis，不依赖 FastAPI Request、权限或 HTTP 状态，也不返回 ORM Model。未预加载关系或不完整 Online 聚合属于内部编程错误，应快速失败，禁止在 Mapper 内补查或伪造默认值。用户端和管理端必须使用独立映射函数，防止状态、删除标记、内部外键和类型专属字段跨接口泄漏。

```python
# app/api/v1/auth.py
from fastapi import APIRouter, Depends
from app.common.response import success
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", status_code=201)
async def register(data: UserCreate, user_repo: UserRepository = Depends()):
    """用户注册"""
    service = UserService(user_repo)
    user = await service.register(data)
    return success(data=UserOut.model_validate(user).model_dump())

@router.post("/login")
async def login(data: LoginRequest, user_repo: UserRepository = Depends()):
    """用户登录"""
    service = UserService(user_repo)
    user = await service.login(data)
    return success(data={
        "access_token": create_access_token(user.id),
        "user": UserOut.model_validate(user).model_dump(),
    })
```

**约束**：
- 只做参数提取和路由分发，**不写业务逻辑**
- 所有请求体用 Pydantic Schema 校验
- 通过 `Depends()` 注入 Service

### 3.2 Service 层（app/services/）

**职责**：编排业务逻辑、管理事务边界、协调多个 Repository

```python
# Phase 4.2 Order 调用形状（已实现）
class OrderService:
    async def create_order(
        self,
        *,
        user_id: int,
        items: list[OrderItemInput],
        remark: str | None,
        ip_address: str,
    ) -> Order:
        # 1. ProductRepository 一次批量加载 Product + ExperienceOption 聚合
        # 2. 拒绝 Kit，验证 Product Online/未删除与 Option 有效/归属
        # 3. 用 Decimal 构造名称、Option 配置、价格和金额快照
        # 4. 单事务：Order → bulk OrderItem → CREATE_ORDER Audit → 响应重载
        # Phase 4.2 不检查、不扣减也不恢复 ProductKit.stock
        ...
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

### 3.3 Validator 层（app/validators/）— Phase 4 新增

**职责**：状态变迁前的完整性校验。同步读取 Service 已准备好的聚合，只做纯计算判断。

Service 在修改关键状态（如 `draft → online`）前，必须调用 Validator 执行前置检查。Validator 按 `product_type` 分发规则并一次性收集全部缺项。对外接口成功时返回 `None`，失败时抛命名业务异常；不返回 bool。

```python
# app/validators/product_validator.py

class ProductValidator:
    """商品状态变迁校验器。"""

    @classmethod
    def validate_before_online(cls, product: Product) -> None:
        """同步校验已预加载的 Product 聚合；失败时一次抛出全部缺项。"""
        issues = cls._collect_common_issues(product)
        if product.product_type == ProductType.EXPERIENCE:
            issues.extend(cls._collect_experience_issues(product))
        elif product.product_type == ProductType.KIT:
            issues.extend(cls._collect_kit_issues(product))

        if issues:
            raise ProductNotReadyForOnline(issues)

    @classmethod
    def _collect_common_issues(cls, product: Product) -> list[str]:
        ...
```

上例所示同步公开入口、公共 issues 收集模式、名称/描述/封面规则，以及 Experience/Kit 分支均已实现。专项测试证明 Validator 在 `get_product_detail()` 加载完成后不执行 SQL、不修改聚合、相同输入产生相同顺序的问题列表；未预加载关系和未知 ProductType 均 fail-closed 为内部编程错误，不转换为 `42201`。精确检查条件、issue 字符串及稳定顺序以 [Product Business Rules §8.5](../01_requirements/product_business_rules.md#85-online-validation上架校验) 为准。

**Service 调用方式：**

```python
# app/services/product_service.py

async def online_product(
    self,
    product_id: int,
    *,
    operator_id: int,
    ip_address: str,
) -> Product:
    product = await self.product_repo.get_product_detail(
        product_id,
        include_deleted=True,
    )
    # Service 在这里处理不存在、逻辑删除和已经 Online 等资源/状态冲突。
    ProductValidator.validate_before_online(product)  # 同步纯计算；不使用 await
    # 校验通过后，Service 才在同一事务连接上更新状态并写审计。
```

`get_product_detail(product_id, include_deleted=True)` 必须预加载 `kit`、有效 ExperienceOption、有效 Product 公共图片及每个有效 Option 的有效专属图片；`include_deleted=True` 让 Service 能先区分“不存在”和“已经逻辑删除”。`get_product_by_id()` 只读取 Product 主表，不能作为 Validator 输入。Validator 不负责补查关系；若调用方忘记预加载并触发 `NoValuesFetched`，这是 Repository/Service 集成错误，应进入 500 兜底而不是转换为 `42201`。

Product 上架的状态更新与 `ONLINE_PRODUCT` 审计必须共享同一个 `BaseDBAsyncClient` 事务连接。为此，`AuditLogService.log()` 与 `AuditLogRepository.create()` 提供向后兼容的可选 `using_db` 参数：普通调用不传时保持既有顺序审计；需要原子性的 Product Service 显式透传当前连接。Product Service 通过构造函数注入 ProductRepository 与共享 AuditLogService，不直接实例化 Repository，不直接操作 ORM Model，也不把权限检查或 Out Schema 序列化放入 Service。

以上 Product 上架 Service 编排与共享审计事务透传已实现。架构测试固定 Service 不依赖 FastAPI、API Schema 或 Redis，也不直接调用 Model 持久化方法；真实集成测试固定审计失败时 Product 状态回滚。API Mapper、20 个 JSON 路由、文件存储适配器和两个 multipart 上传路由均已完成。

Product 下架 Service 也已实现，复用同一 Repository/审计事务边界，但只读取 Product 主表且不调用 Validator：不存在、逻辑删除和非 Online 状态在事务前失败；成功时 `status=offline` 与 `OFFLINE_PRODUCT` 审计原子提交。

Product 查询 Service 只编排 Repository 的用例查询并返回 Model/Page，不承担 API DTO 映射。管理端和用户端使用独立方法固定可见性；`cover_image`、`display_price`、dimensions、available 和所有 label 由 API 层 Mapper 从 Repository 已预加载的聚合构造，随后交给 Out Schema 验证。这样 Service 不反向依赖 `app/schemas/product_response.py`，Repository 也不包含展示逻辑。

Product API Mapper 已实现上述列表、详情、mutation 与分页映射。架构测试固定其无 async/await、无 ORM 查询/写入调用且不依赖 Service/Repository/FastAPI/Redis；真实 SQLite 测试固定 Repository 查询完成后 Mapper SQL 数量为零、聚合对象与关系列表不被修改。现有 Repository 预加载与 Service 返回对象已满足响应序列化需求，无需为 Mapper 调整 Service 或 Repository。

Product 普通 JSON 路由拆分为 `app/api/v1/products.py`（公开列表和 Experience/Kit 详情）与 `app/api/v1/admin_products.py`（ADMIN+ 查询及 mutation）。`app/api/deps.py:get_product_service()` 是 API 组合根，负责组装 ProductRepository、共享 AuditLogService 和 ProductService；路由不直接导入 Product Model/Repository，只执行 Request/Query Schema 校验、权限依赖、Service 调用、Mapper 序列化和 `success()`。Product/Kit 创建固定 HTTP 201；ExperienceOption 新建为 201、恢复历史 Option 为 200。该 JSON 路由阶段当时未注册的两个 multipart 图片创建端点和 Product 操作历史端点均已由后续阶段接入。

Product 操作历史保持共享审计边界：`AuditLogRepository.list_logs()` 只按 `target_type/target_id` 执行倒序稳定分页，`AuditLogService.list_logs()` 提供 Product/Order/Inventory 均可复用的查询用例；`ProductService.list_product_audit_logs()` 仅负责用 `include_deleted=true` 确认 Product 记录仍存在，再委托共享服务。API 使用共享 `app/schemas/audit.py:AuditLogOut` 与 Audit Mapper 构造字段白名单和 `Page[T]`，不把审计字段复制到 Product Schema，也不把 Audit Log 嵌入 Product Detail。

Order v1.0 架构边界、实现与最终 Review 均已完成。Order Model 只声明表结构；`OrderRepository` 负责纯数据访问和 SQL 可见性限定。查询用例包括用户列表/详情、管理列表/详情及管理端审计历史：用户详情把 `user_id` 直接传入 Repository 查询，因此不存在与他人订单都只得到 `None` 并抛同一 `OrderNotFound`；API status 字符串通过 `ORDER_STATUS_BY_VALUE` 显式翻译为数据库 `OrderStatus`；订单审计先确认 Order 存在再委托共享 `AuditLogService`。

创建用例接收不含客户端快照的 `OrderItemInput`，先各用一次集合查询批量加载 Product 与 ExperienceOption，再按请求 Item 顺序执行 Kit 边界、Product 可售性和 Option 有效性/归属判断。全部通过后，Service 以数据库 Product 名称、Option 配置和 `Decimal` 价格构造不可变快照及总额；Order、批量 Items、紧凑非敏感 `CREATE_ORDER` 审计和详情重载共享同一事务连接。任一步异常整体回滚。订单号 UNIQUE 冲突必须先退出失败事务，再确认冲突编号已持久化，并用新编号开启全新事务，最多 3 次；其他 `IntegrityError` 不重试。

状态变迁只通过 `cancel_order()`、`mark_order_paid()` 和 `complete_order()` 三个公开用例暴露，不提供接受任意目标状态的公共方法。每次用例开启事务后调用 `get_order_for_update()`：用户取消在 SQL 锁查询中附带 `user_id`，不存在与他人订单均映射为 `OrderNotFound`；管理用例按 ID 锁定。Service 只对锁后最新状态执行 `pending → cancelled`、`pending → paid` 或 `paid → completed`，冲突时抛出包含稳定 operation/current/required 的 `OrderStatusConflict`，不写状态与审计。成功时状态更新、紧凑 before/after 审计和轻量响应重载共享事务连接，任一步失败整体回滚。OrderService 可以依赖 OrderRepository、ProductRepository 与共享 AuditLogService，但不得调用 ProductService 或直接操作 Model。

Phase 4.2 的 Inventory 边界是强约束：OrderService 和 OrderRepository 不读取或修改 `ProductKit.stock`，取消也不恢复库存。Phase 4.3 必须先冻结库存预占/扣减/恢复与并发模型，再通过明确接口把 Kit 下单接入 Order 事务；不得在 Phase 4.2 以“只检查库存”替代完整库存语义。

订单号组件已在 `app/common/order_number.py` 实现，使用标准库生成 `OD` + 26 位 Crockford Base32 ULID，不新增第三方依赖。它使用 UTC Unix 毫秒和 `secrets.token_bytes()` 密码学安全随机源，不依赖 Redis、数据库序列表或进程全局状态；`orders.order_no` UNIQUE 是最终兜底。创建 Service 已实现最多 3 次的唯一冲突重试：每次冲突事务完整回滚，归因后用新编号开启全新事务；非编号约束错误及第三次编号冲突保留数据库根因。列表排序始终为 `created_at DESC, id DESC`，不依赖订单号。

Order API Mapper 已实现并与 Product Mapper 保持同一边界：从 Repository 已预加载或注解的 Order 聚合生成用户端/管理端独立 Out Schema，金额由严格 Schema 固定序列化为两位小数字符串，OrderStatus 与 DayType 转为 `{value, label}`。列表仅消费数据库聚合的 `item_count` 注解，详情只消费已预加载并验证归属的 Items，状态响应可从无关系的轻量 Order 映射；执行期间零 SQL、零修改。用户端 Mapper 不读取或暴露 user 关系；管理端只增加已预加载的 `user_id` 与 `user_nickname`，不会输出用户名、手机号或凭据。订单审计继续使用共享 Audit Schema/Mapper 独立分页查询，不嵌入详情。

Order HTTP 组合根已在 `app/api/deps.py:get_order_service()` 实现，集中组装 OrderRepository、ProductRepository 与共享 `AuditLogService(AuditLogRepository)`。`orders.py` 和 `admin_orders.py` 不导入 Order/Product Repository 或业务 Model，不捕获业务异常；它们只把严格 Request/Query Schema 与认证身份转换为 Service 参数，再通过 Order/Audit Mapper 和 `success()` 输出统一信封。用户 ID 和管理操作者 ID 均来自认证依赖，客户端无法通过 body/query 伪造；写用例统一由 `get_client_ip()` 提供审计 IP。该工具只接受可规范化且不带 scope identifier 的 IPv4/IPv6 字面量，非法或超长 `X-Forwarded-For` 回退到直连地址；部署层仍必须确保只有受信任的反向代理能够覆盖转发头。`HTTPBearer(auto_error=False)` 让缺失凭据进入共享 `AuthenticationException` 中间件并返回统一 401 信封，ADMIN+ 权限不足仍为 403。

Product Router 的运行时输出仍由 Mapper 完成一次严格 Out Schema 校验与序列化，再交给 `success()` 构造统一信封；OpenAPI 则通过 `SuccessResponse[T]` / `ErrorResponse` 和路由 `responses` 精确声明成功与错误结构。这里显式保持 `response_model=None`，避免 FastAPI 对 Mapper 已序列化的两位小数金额字符串进行第二次 Decimal 输入校验。该选择只分离运行时校验与文档声明，不放宽任何输出白名单。

上述查询 Service 已实现。真实集成测试固定用户列表 Online/未删除范围、描述搜索，以及管理端已删除聚合和用户端 Online 详情预加载；查询方法不写审计、不调用 Validator、不开启事务。

Product 创建 Service 接收拆分后的领域字段而非请求 Schema，并返回 Product Model。Experience 的 Product+审计和 Kit 的 Product+ProductKit+审计分别共享一个调用方事务连接；Service 固定 ProductType，Model 默认固定 Draft/未删除，API 只负责输入 Schema 和 Create Out 序列化。创建 Draft 不调用 Validator。

上述 Experience/Kit 创建 Service 已实现；真实 SQLite 测试固定 Kit 扩展记录与 Product 同事务创建，以及两种创建在审计失败时不留下 Product、ProductKit 或 AuditLog。

Product 基础信息修改和逻辑删除 Service 只读取 Product 主表，不加载聚合、不调用 Validator。API 将 `ProductUpdate.model_dump(exclude_unset=True)` 结果作为显式字段映射传入，Service 通过 `name` / `description` 白名单保护用例边界；`description=None` 与字段缺失保持不同语义。修改和删除均先处理不存在、逻辑删除和 Online 冲突，再在一个事务连接上执行 Repository 更新与对应审计。逻辑删除仅设置 `is_deleted=true`，保持 ProductStatus 和所有关联记录不变。

ExperienceOption 新增/恢复 Service 先读取 Product 主表和全历史组合，再在单个事务中选择 INSERT 或恢复原记录、写对应审计，并通过 `get_option_detail(..., using_db=connection)` 重载响应所需的有效图片。Service 返回只包含 ORM Option 与 `restored` 标志的领域结果，让 API 决定 201/200，不让 HTTP 状态进入业务层。数据库唯一索引仍是并发兜底；Repository 抛出的唯一 `IntegrityError` 在 Service 边界转换为 `40911`。恢复保留原 Option ID/图片关联，只更新价格和删除标记。

ExperienceOption 修改 Service 接收不依赖 Schema 的显式字段 Mapping，在业务层将请求字段名转换为 Repository 字段名，并用当前 Option 合并最终组合后查询全历史唯一性。配置维度和价格使用独立审计 action；同一 PATCH 可在一项事务中顺序写两条审计。更新、审计和响应聚合重载都使用同一连接，因此后置读取或任一审计失败会回滚整个用例。Service 不修改图片，也不调用 Validator。

ExperienceOption 删除 Service 复用按 ID 加载的 Option→Product 关系做前置状态检查，不统计当前有效 Option 数量。事务内只通过 Repository 设置 Option 删除标记并写 `DELETE_OPTION` 快照审计；Product 状态、Option 图片记录和图片外键保持不变。允许删除 Draft/Offline 的最后一项，将零 Option 状态留给未来上架 Validator 判断。

Kit 价格与库存修改 Service 共享 Product 主表前置检查和 ProductKit 扩展加载方法，按不存在、删除、类型、Online、扩展缺失的顺序稳定失败；缺少一对一扩展使用已登记的 `40404 ProductKitNotFound`，不伪造聚合数据。价格和库存分别使用独立公开用例，只将单一字段交给 Repository 更新，并与 `UPDATE_PRICE` / `UPDATE_STOCK` 快照审计共享事务连接。Service 返回 ProductKit 领域对象，API Mapper 负责将 `product_id` 映射为响应资源 ID。该流程不调用 Validator，也不引入 Phase 4.3 的库存流水或并发扣减语义。

ProductImage Service 的输入边界是已生成的 `image_url` 和领域字段，不导入 FastAPI `UploadFile` 或存储 SDK。公共图创建、Option 图创建、排序/封面修改和逻辑删除均通过 ProductRepository 持久化，并与 Product-targeted 审计共享事务。封面创建/切换先在同一连接上通过 `SELECT ... FOR UPDATE` 锁定 Product 行，串行化同聚合的并发封面写入，再读取旧封面、批量清除有效公共封面、写当前图片并顺序写审计；第二条审计失败也回滚所有状态。已删除图片、所属 Product 或所属 Option 对图片 ID 操作统一隐藏为 40403。

文件上传是 API/基础设施边界。`app/api/forms/product.py` 以 `extra=forbid` 限定两种 multipart 请求形状；`app/storage/image.py` 不依赖 FastAPI、Model、Repository 或 Service，限量读取最大 2 MiB，校验 jpg/png/webp 文件签名与声明 MIME，使用服务端 UUID 和不覆盖的原子发布，返回 URL 及 storage key。`app/api/uploads.py` 在线程池调用同步文件存储，再调用 ProductService；Service 失败时幂等删除已存储文件，补偿异常只记录 storage key，不掩盖原业务异常。`app/api/static.py` 将本地 URL 挂载为开发环境可访问静态文件，首次上传前目录不存在时返回 404。

ProductImage 物理文件清理位于独立运维任务边界，而不是 DELETE HTTP 请求、ProductService 数据库事务或 FastAPI 进程内后台任务。`ProductImageCleanupService` 通过 ProductRepository 按 `is_deleted=true`、显式截止时间与 ID 游标分批读取候选，并以单条批量查询取得仍被有效记录引用的 URL，避免 N+1；`LocalImageStorage.key_from_url()` 只接受当前配置命名空间中的 UUID key。清理前在内存中排除有效共享引用，再在线程中执行幂等删除；外部 URL、异常 URL和有效共享引用不会被删除，单项 I/O 失败记录上下文并继续。`app/tasks/product_image_cleanup.py` 只负责数据库生命周期、批次循环、统计与退出码，默认预览并逐项记录候选，只有 `--apply` 才执行删除；可由 cron、容器定时任务或其他外部调度器重复调用。逻辑删除记录与 AuditLog 不因文件清理而修改，因此不需要新增清理状态表或数据库迁移。

**约束：**
- 同步纯计算，不查询或写入数据库，不调用 Repository、Service、Redis，不开启事务
- 只读取已预加载聚合，不修改 Product、Option、Image、ProductKit 或状态
- 成功返回 `None`；失败抛命名业务异常并一次携带全部 issues，不返回 bool
- 校验规则按 `product_type` 分发，新增类型时扩展对应函数
- 与 Service 解耦——Service 决定"何时校验"，Validator 决定"如何校验"

### 3.4 Repository 层（app/repositories/）

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

### 3.5 Model 层（app/models/）

**职责**：定义表结构、字段约束、模型关系

```python
# app/models/user.py
from tortoise import fields
from tortoise.models import Model

class User(Model):
    id = fields.BigIntField(primary_key=True)
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

### 3.6 中间件层（app/middleware/）

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

### 3.7 公共模块（app/common/）

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
from enum import Enum, IntEnum

class UserRole(IntEnum):
    USER = 1
    ADMIN = 2
    SUPER_ADMIN = 3

class UserStatus(IntEnum):
    NORMAL = 1
    DISABLED = 2

# app/common/enums/product.py
# 项目运行于 Python 3.10，使用 str, Enum 兼容写法；Python 3.11+ 才有 StrEnum。
class ProductType(str, Enum):
    EXPERIENCE = "experience"
    KIT = "kit"

class ProductStatus(str, Enum):
    DRAFT = "draft"
    ONLINE = "online"
    OFFLINE = "offline"

class DayType(str, Enum):
    WEEKDAY = "weekday"
    HOLIDAY = "holiday"

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
PASSWORD_MIN_LENGTH = 8
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

### 3.8 工具函数（app/utils/）

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

以 Phase 4.2 已实现的“创建 Experience 订单”为例，展示当前完整调用链：

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
│  · 批量加载 Product + ExperienceOption                 │
│  · 拒绝 Kit；验证 Online/未删除/Option 有效与归属       │
│  · Decimal 计算价格快照、小计与总额                     │
│  · 单事务写 Order + bulk Items + Audit + 响应重载       │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[5]───────────────────────────────────────────────────┐
│  Repository: product_repo 批量只读聚合                  │
│              order_repo 原子创建/批量明细/响应重载      │
│  AuditLogService.log(..., using_db=connection)         │
│  · Phase 4.2 不查询或修改 ProductKit.stock             │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[6]───────────────────────────────────────────────────┐
│  MySQL                                                │
│  · 执行 SQL → 返回结果                                 │
└──────────────────┬────────────────────────────────────┘
                   ▼
┌─[7]───────────────────────────────────────────────────┐
│  响应：Service 返回 Order 对象                         │
│  → Order Mapper 严格校验用户端 OrderDetailOut          │
│  → 金额两位小数字符串，用户端不暴露 user 字段           │
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
    app_version: str = "0.3.0"
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
            "default": {
                "engine": "tortoise.backends.mysql",
                "credentials": {
                    "host": settings.db_host,
                    "port": settings.db_port,
                    "user": settings.db_user,
                    "password": settings.db_password,
                    "database": settings.db_name,
                },
            }
        },
        ...
    }
```

MySQL 使用结构化 `credentials`，不手工拼接连接 URL；这样密码中的 `@`、`:`、`/`、`#` 等保留字符会作为原始凭据传给驱动，不会被误解析为 URL 结构。

Schema 创建策略按环境隔离：`development` 可在应用启动时使用 `generate_schemas` 方便本地开发；`testing` 由测试 fixture 创建并销毁独立临时 Schema；`production` 禁止启动时隐式建表或改表，必须先执行经过 Review 的受控数据库迁移。

---

## 6. 基础组件

### 6.1 异常定义（app/core/exceptions.py）

异常类定义在 `core/`（纯 Python，不依赖 HTTP）；全局异常处理器在 `middleware/exception.py`（依赖 Starlette，捕获异常并序列化为 JSON 响应）。HTTP 状态由异常类型映射，不根据业务错误码的数字范围推断。

```python
# app/core/exceptions.py  —— 只定义异常类

class AppException(Exception):
    """应用异常基类，携带 code、message 和可选 data。"""
    def __init__(self, code: int, message: str, data: dict = None):
        self.code = code
        self.message = message
        self.data = data

class BusinessException(AppException):
    """一般业务规则不满足，由中间件映射为 HTTP 400。"""

class UnprocessableEntityException(BusinessException):
    """请求语法正确，但当前业务数据或聚合状态不满足处理条件。"""
```

```python
# app/middleware/exception.py  —— 全局异常处理器

from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.exceptions import BusinessException, UnprocessableEntityException

async def unprocessable_entity_exception_handler(
    request: Request,
    exc: UnprocessableEntityException,
):
    return JSONResponse(
        status_code=422,
        content={"code": exc.code, "message": exc.message, "data": exc.data}
    )

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

`UnprocessableEntityException` 的专用 handler 必须保持 HTTP 422，普通 `BusinessException` 继续保持 HTTP 400。Product 的 `ProductNotReadyForOnline` 是前者的模块命名子类，固定 `42201`、message 和非空字符串数组 `data.issues`。FastAPI `RequestValidationError` 由独立全局 handler 转换为 `{code: 422, message: "Validation failed", data: {errors: [...]}}`；错误摘要只保留 location/message/type，不回显原始输入值。模块命名异常直接继承对应 HTTP 语义类型；不保留跨 404/409/422 的伪通用 Product 基类。

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

def create_access_token(user_id: int, jti: str) -> str:
    # {"sub":"1", "type":"access", "jti":"uuid", "exp":..., "iat":...}
    ...

def create_refresh_token(user_id: int, jti: str) -> str:
    # 同一次登录的 access/refresh 共用 jti
    ...

def decode_token(token: str, expected_type: str) -> dict:
    # 验证 type 声明，防止 access token 被当作 refresh 使用
    ...
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

# Refresh Token 存储：key = rt:{jti}, value = user_id
async def save_refresh_token(jti: str, user_id: int) -> None:
    await redis_client.set(f"rt:{jti}", str(user_id), ex=settings.jwt_refresh_token_expire)

async def verify_refresh_token(jti: str) -> int | None:
    value = await redis_client.get(f"rt:{jti}")
    return int(value) if value else None

async def delete_refresh_token(jti: str) -> None:
    await redis_client.delete(f"rt:{jti}")

# 接口限流：key = ip + endpoint
async def rate_limit(key: str, max_requests: int, window: int) -> bool:
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, window)
    return current <= max_requests
```
