# AI Context — pinkdooHub

> 强制开发规则已内置在项目根目录的 `AGENTS.md` 中（每次会话自动加载）。
> 本文档是 AI 的"项目守则"——定义开发流程、文档维护规则和全局上下文。
> 完成任何代码修改后，按本文档检查是否需要同步更新。
> 遇到不确定的领域时，按索引去读对应文档，不要凭记忆猜测。

---

## 1. 文档索引

| 需要了解 | 读这个 |
|----------|--------|
| 代码怎么写 | [coding_standards.md](../05_development/coding_standards.md) |
| 项目怎么分层 | [architecture.md](../04_architecture/architecture.md) |
| 开发历史 | [changelog.md](../05_development/changelog.md) |
| API 设计规范（全局） | [api_design_conventions.md](../03_api/api_design_conventions.md) |
| 用户 API | [user_api.md](../03_api/user_api.md) |
| 商品 API | [product_api.md](../03_api/product_api.md) |
| 商品业务规则 | [product_business_rules.md](../01_requirements/product_business_rules.md) |
| 订单 API | [order_api.md](../03_api/order_api.md) |
| 数据库设计 | [database_design.md](../02_database/database_design.md) |
| ER 图 | [er_diagram.dbml](../02_database/er_diagram.dbml) |
| Code Review 清单 | [code_review_checklist.md](../07_process/code_review_checklist.md) |
| 数据库迁移流程 | [database_migration_workflow.md](../07_process/database_migration_workflow.md) |
| 需求文档 | [../01_requirements/](../01_requirements/) |

---

## 2. 技术栈速查

| 层级 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.139 |
| ORM | Tortoise ORM | 1.1.7 |
| 数据校验 | Pydantic | 2.13 |
| 配置管理 | pydantic-settings | 2.14 |
| 密码加密 | passlib[bcrypt] | 1.7.4 |
| JWT | python-jose[cryptography] | 3.3.0 |
| 数据库 | MySQL（生产）/ SQLite（开发） | — |
| MySQL 异步驱动 | asyncmy | 0.2.11 |
| 缓存 | Redis | — |
| 迁移 | Aerich | 0.9.3 |
| 服务器 | Uvicorn | 0.51 |
| 测试 | pytest + pytest-asyncio + httpx | 9.1 / 1.4 / — |
| 时区 | tzdata | —（Windows 必需） |

### 2.1 当前 Phase 与实现边界

- 当前代码版本候选为 **v0.5.0（尚未发布）**；**Phase 4.1 Product Module** 与 **Phase 4.2 Order Module** 均已完成实现和最终 Review。Order v1.0 已达到代码层 release-ready：领域语言、Schema、Model/离线迁移、Repository/编号生成器、查询/Experience 创建/状态 Service、API Mapper、组合根、九个 FastAPI 端点、完整真实 HTTP 错误/边界矩阵及最终架构/安全/迁移/文档审查均已完成；三个状态 PATCH 会主动拒绝任意请求体，共享审计 IP 入口也会拒绝非法、超长或带 scope 的代理地址并安全回退。下一业务阶段为 Phase 4.3 Inventory。
- Product 业务规则、数据库设计、API 契约和 Validator 对外契约均已完成；Product API 文档已通过 Phase 4.1 最终 Review，并收口为 v1.0 Implemented。
- 已实现 Product 字符串 Enum、字段常量、请求/查询 Schema、响应 Schema 及其契约测试。
- `app/schemas/product.py` 负责请求体和查询参数；`app/schemas/product_response.py` 负责响应白名单。
- Product、ExperienceOption、ProductKit 与 ProductImage 的全部 Model、`ProductRepository`、Product Validator、Service、API Mapper 与 22 个 FastAPI 端点均已实现。其中 20 个 JSON 端点负责公开/管理查询、Product/Option/Kit mutation、图片元数据 PATCH/DELETE 和 Product 操作历史；两个 ADMIN+ multipart 端点负责 Product 公共图和 Option 专属图创建。上传已接入严格表单、文件校验/本地存储、Service 失败幂等补偿、开发环境静态 URL 和真实 SQLite HTTP 一致性测试。Product 操作历史通过共享 AuditLog Repository/Service、Out Schema 和 Mapper 分页查询，支持逻辑删除后的追溯。逻辑删除图片的本地文件由带显式截止时间的可重试批处理清理。
- MySQL 8+ 权威首迁移及 Order 增量迁移已离线生成并通过契约测试，但尚未对 MySQL 执行。SQLite 开发库曾在可恢复备份后从 Phase 4.1 Models 重建；本次只使用临时 SQLite 验证 Order Models，未重建开发库、未应用 MySQL 迁移，也未使用 `--fake`，其 Aerich 版本记录保持为空。
- Order v1.0 / Phase 4.2 仅开放 Experience 下单；Kit 下单在 Phase 4.3 Inventory 前整单拒绝，当前不做库存检查、扣减或恢复。Kit 库存仍使用 Phase 4.1 的直接设置最终值模式。
- ExperienceOption 配置组合在全历史范围内唯一；再次创建相同已删除组合时恢复原 Option ID、更新当前价格并保留图片关联，不创建第二条版本记录。

---

## 3. 枚举速查

| 数据库 | API (string) | Python Enum |
|--------|--------------|-------------|
| `users.role` 1/2/3 | `"user"` / `"admin"` / `"super_admin"` | `UserRole` |
| `users.status` 1/2 | `"normal"` / `"disabled"` | `UserStatus` |
| `products.product_type` VARCHAR | `"experience"` / `"kit"` | `ProductType(str, Enum)` |
| `products.status` VARCHAR | `"draft"` / `"online"` / `"offline"` | `ProductStatus(str, Enum)` |
| `experience_options.day_type` VARCHAR | `"weekday"` / `"holiday"` | `DayType(str, Enum)` |
| `orders.status` 0/1/2/3 | `"pending"` / `"paid"` / `"cancelled"` / `"completed"` | `OrderStatus` |

> `duration_minutes` 和 `participants` 是开放正整数，不是 Enum。当前常用值不构成允许值白名单。

---

## 4. 错误码号段速查

| 模块 | 号段 | 已用 |
|------|------|------|
| 用户 | 1xxx | 1001-1007 |
| 商品 | 40xxx / 409xx / 422xx | 40001, 40021 / 40401-40404 / 40901-40905, 40911-40912 / 42201, 42221 |
| 订单 | 4041x / 4092x / 4223x | 40411 / 40921-40922 / 42231-42232（命名异常与 HTTP 映射已实现） |

Order v1.0 契约速查：

- `app/common/enums/order.py` 使用 `OrderStatus(IntEnum)` 保存 0/1/2/3；`app/common/constants/order.py` 显式注册 API value/label，禁止把 IntEnum 整数直接输出为 API status。
- 已实现 Item 1–10、quantity 1–99、remark 500、订单号长度/正则/重试次数、Phase 4.3 边界和四个审计 action 常量；五个命名异常通过 `app/common/exceptions/__init__.py` 导出。
- `app/schemas/order.py` 固定创建请求、重复 Product/Option 拒绝、用户/管理分页筛选和 UTC 时间范围；`app/schemas/order_response.py` 固定金额 Decimal→两位字符串、status/day_type 配对、快照金额一致性以及用户/管理字段隔离。详情不返回列表派生 `item_count`。
- `app/models/order.py` 已实现 `Order` / `OrderItem`、`SmallIntField` 状态、订单号唯一约束、Decimal 快照、四条 `RESTRICT` 历史外键和五组稳定查询索引；MySQL 8+ 增量迁移已离线生成并静态 Review，尚未应用。
- `app/common/order_number.py` 只用标准库生成 OD+ULID；`app/repositories/order_repo.py` 已实现 Order/Item 事务写入、详情、用户可见限定、行锁、状态持久化和用户/管理分页，列表使用数据库 `COUNT(items)` 生成 `item_count`。ProductRepository 已提供包含逻辑删除记录的 Product/Option 集合读取，供创建 Service 一次批量校验。
- `app/services/order_service.py` 已实现 Experience 创建、三个独立状态变迁及五个只读用例。创建先批量读取 Product/Option，按请求顺序执行 Kit、Product、Option 错误优先级，以数据库值计算 Decimal 快照；Order、Items、`CREATE_ORDER` 审计与详情重载原子提交，订单号冲突退出失败事务后用全新事务最多重试 3 次。状态变迁在事务内锁定可见 Order，锁后重检，只允许 `pending → cancelled`、`pending → paid`、`paid → completed`；状态、before/after 审计和重载原子提交。用户查询与取消使用 `(order_id, user_id)` 可见限定统一隐藏不存在/他人资源；管理端审计先确认 Order 存在再委托共享 AuditLogService。`OrderStatusValue` 定义在 common Enum 模块，Service 使用完整 `ORDER_STATUS_BY_VALUE` Registry 将 API 字符串翻译为数据库 IntEnum。
- `app/api/mappers/order.py` 已实现 OrderStatus/DayType、OrderItem 快照、用户/管理列表与分页、用户/管理详情和轻量状态响应。Mapper 只消费 Repository 已注解或预加载的数据，用户端不读取 User 关系，管理端只输出 `user_id/user_nickname`；严格 Schema 负责 Decimal 两位小数与聚合金额一致性。真实 SQLite 聚合测试固定零 SQL、零 ORM 对象/关系列表修改。
- `app/api/deps.py:get_order_service()` 组装 OrderRepository、ProductRepository 和共享 AuditLogService；`app/api/v1/orders.py` 已注册创建、我的列表、我的详情和取消，`app/api/v1/admin_orders.py` 已注册管理列表/详情、确认支付、完成和审计历史。九个端点均使用精确 `SuccessResponse[T]` / `ErrorResponse` OpenAPI、统一 `success()` 与全局异常中间件；真实 JWT + SQLite 测试已贯通核心生命周期。缺失 Token 为统一 401，现有无效 Token `1006` 仍为 User 契约的 HTTP 400。
- 创建请求必须提供 `product_id + experience_option_id + quantity`；只接受当前有效、已上架的 Experience 聚合，同一 Product/Option 组合不得重复。
- 金额由当前 Option 价格用 `Decimal` 计算，API 固定输出两位小数字符串；OrderItem 保存名称、Option 配置和价格快照。
- 订单号使用 `OD` + 26 位大写 Crockford Base32 ULID（总长 28），数据库 UNIQUE 兜底；列表权威排序为 `created_at DESC, id DESC`。
- 状态流仅为 `pending → cancelled`、`pending → paid`、`paid → completed`；ADMIN+ `/paid` 是支付集成前临时人工入口。
- 创建、取消、确认支付和完成分别写 `CREATE_ORDER`、`CANCEL_ORDER`、`MARK_ORDER_PAID`、`COMPLETE_ORDER`，与业务写入同事务；`target_type=order`。
- 用户访问不存在或他人订单统一返回 `40411 OrderNotFound`；用户端不返回 user 字段，管理端仅增加 `user_id` 与 `user_nickname`。

Product Validator 契约速查：

- `42201` 固定映射 HTTP 422，message 精确为 `Product is not ready to go online`，`data.issues` 是非空英文字符串数组；精确 issue 清单与顺序见 [Product Business Rules §8.5](../01_requirements/product_business_rules.md#85-online-validation上架校验)。
- `ProductNotReadyForOnline` 当前通过 `UnprocessableEntityException` 映射 HTTP 422；进入 Service 异常实现时将移除只能表示 422 的伪通用 `ProductException`，让 Product 的 404/409/422 命名异常分别直接继承 `NotFoundException`、`ConflictException`、`UnprocessableEntityException`。HTTP 状态按异常类型映射，禁止按错误码号段推断，普通 `BusinessException` 仍为 HTTP 400。
- `ProductValidator.validate_before_online(product) -> None` 是同步纯计算接口。Service 必须传入 `ProductRepository.get_product_detail(product_id, include_deleted=True)` 预加载的聚合；Validator 不执行 I/O、不修改对象，也不把未预加载关系造成的编程错误转换为 `42201`。
- Product 上架 Service 与 ADMIN+ JSON 路由已实现：`online_product(product_id, *, operator_id, ip_address) -> Product` 依次处理 `40401 ProductNotFound`、`40903 ProductIsDeleted`、`40901 ProductAlreadyOnline`，再同步调用 Validator。校验通过后状态与审计原子提交，Router 经 `ProductOnlineOut` 返回统一信封。
- Product 下架 Service 与 ADMIN+ JSON 路由已实现：仅允许 Online → Offline；Draft/Offline 统一返回 `40902 ProductAlreadyOffline`，逻辑删除优先返回 `40903`。成功状态与审计同事务提交，下架不调用 Validator，Router 经 `ProductOfflineOut` 返回统一信封。
- Product 查询、响应映射与 FastAPI 路由已实现：管理端/用户端采用独立 Service、Mapper 和路由；Mapper 从已预加载关系派生展示字段，执行期间零 SQL且不修改 ORM。用户端固定 Online 且未删除；管理端使用 ADMIN+ 权限并支持显式 include_deleted。查询端点当前可调用。
- Product 创建 Service 与 ADMIN+ HTTP 201 路由已实现：Experience 原子写 Product+审计；Kit 原子写 Product+ProductKit+审计。Service 保持领域边界，Router 负责 Request Schema、Mapper 和统一响应。
- Product 基础信息修改与逻辑删除 Service/ADMIN+ 路由均已实现；PATCH 使用 `model_dump(exclude_unset=True)` 保留缺失/null 语义，DELETE 只设置 Product 删除标记并保持 status/关联记录，Router 经专用 Mapper 返回统一信封。
- ExperienceOption 新增/恢复 Service 与 ADMIN+ 路由已实现：Service 返回 `ExperienceOptionCreationResult(option, restored)`，Router 新建返回 201、恢复返回 200；全历史唯一、原图片关系和事务审计契约保持不变。
- ExperienceOption 修改 Service 与 ADMIN+ JSON PATCH 路由已实现；Router 保留显式字段语义并返回不含图片的 `ExperienceOptionBaseOut`，全历史唯一与顺序审计契约不变。
- ExperienceOption 删除 Service 与 ADMIN+ JSON DELETE 路由已实现；只设置 Option.is_deleted，保持 Product 状态与图片记录/外键，并经 `DeletedResourceOut` 返回。
- Kit 价格/库存修改 Service 与 ADMIN+ JSON PATCH 路由已实现；响应 ID 使用 ProductKit.product_id。库存仍是 Phase 4.1 最终值设置，不含流水或并发扣减。
- ProductImage 生命周期已实现：公共图/Option 图创建、排序/封面修改和逻辑删除使用 40401/40402/40403、40903/40905/40912、40021 与 42221 契约；封面批量清理、图片写入及一至两条审计同事务回滚。Service 只接收 image_url。API multipart 边界使用 `python-multipart==0.0.32`，严格表单模型拒绝未知字段；`LocalImageStorage` 完成 2 MiB、jpg/png/webp 签名/MIME、UUID 路径与原子写入；上传编排在 Service 失败时以 storage key 幂等删除文件。逻辑删除后的物理清理使用 `app.tasks.product_image_cleanup` 运维命令，显式截止时间、ID 游标分页、存储命名空间校验、有效引用保护、幂等缺失处理和失败退出码均有真实测试；不会由 Web 进程自动执行。

---

## 5. 文档更新联动

```
修改 Model           → er_diagram.dbml + database_design.md
修改 API 端点        → docs/03_api/<module>_api.md
修改 Enum            → api_design_conventions.md §14 + 本文 §3
修改业务规则         → docs/01_requirements/<module>.md
修改目录结构         → architecture.md §2
修改通用规范         → coding_standards.md
完成功能模块         → changelog.md
```

---

## 6. Documentation Maintenance Rules

### Core Principle

**Documentation is part of the codebase.** Any code change that affects
architecture, API, database schema, business logic, or developer workflow
must update related documents before commit.

### When to Update

| Change Type | Update |
|-------------|--------|
| New/changed API endpoint | `docs/03_api/<module>_api.md` |
| New/changed database table/field | `database_design.md` + `er_diagram.dbml` |
| New/changed Enum | `api_design_conventions.md` §14 + `AI_CONTEXT.md` §3 |
| New/changed project structure | `architecture.md` §2 |
| New/changed dependency | `architecture.md` §1 + requirements.txt |
| New/changed coding rule | `coding_standards.md` + `AGENTS.md`（如影响优先级） |
| Feature completion | `changelog.md` |
| New error code | `api_design_conventions.md` §8 + `AI_CONTEXT.md` §4 |

### Workflow After Code Changes

```
Code Change
  │
  ├─ Run tests                ← pytest tests/ -v
  ├─ Check architecture impact  ← new layer? new dependency direction?
  ├─ Check documentation impact  ← which docs are affected? (see table above)
  ├─ Update docs               ← keep in same commit as code
  ├─ Update changelog          ← if completing a feature
  ├─ git diff --stat review    ← sanity check
  └─ commit + push（仅用户明确要求时）
```

### Documentation Style

- Explain **why** this design exists, not just what the code does
- Document important trade-offs and decisions
- Keep examples in sync with actual code
- Use the same format as existing documents in the same directory

---

## 7. 开发流程（AI 固定流程）

每完成一个任务，按以下顺序执行：

```
1. 修改代码
2. 运行测试        → 确保没有回归
3. 检查架构影响     → 新模块？新依赖方向？新层级？
4. 检查文档影响     → 对照 §6 的表格逐项确认
5. 更新相关文档     → 代码和文档同 commit
6. 更新 changelog   → 功能模块完成时
7. git diff review  → 最后确认变更范围
8. commit + push      → 仅用户明确要求时
```

**四件套原则：Code + Test + Documentation + Commit。缺一不可。**

---

## 8. AI Review 流程

每完成一个功能模块，AI 必须执行以下步骤：

### Step 1: 自动检查清单

对照 [Code Review Checklist](../07_process/code_review_checklist.md) 逐项检查：
- Architecture（分层、依赖方向）
- Security（密码哈希、密钥保护、SQL 注入）
- Naming & Types（命名规范、类型标注）
- Exception & Response（统一异常、统一响应格式）
- Database（字段设计、索引、nullable）
- Testing（新增测试、异常覆盖、边界覆盖）
- Logging（关键操作、无 print、无敏感信息）
- Documentation（API/DB/changelog 更新）

### Step 2: 生成 Review Report

```
## AI Code Review Report

### Changes
[本次修改的文件清单]

### Architecture Check
[通过 / 发现问题及说明]

### Security Check
[通过 / 发现问题及说明]

### Documentation Check
[通过 / 需更新：具体文件列表]

### Test Coverage
- 新增测试: N 条
- 通过: N/N

### Action Items
- [ ] [如需要] 升级版本号
- [ ] [如需要] 数据库迁移 (aerich migrate)
- [ ] [如需要] 新增依赖
- [ ] [如需要] 新增测试
```

### Step 3: 提醒开发者

完成 Review Report 后，主动提醒：
- 是否需要版本升级（semver）
- 是否需要数据库迁移
- 是否需要新增测试或补充边界用例
