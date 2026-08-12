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

- 当前基线为 **v0.3.0**，正在进行 **Phase 4.1 Product Module**。
- Product 业务规则、数据库设计、API 契约和 Validator 对外契约已完成；Product API 文档仍保持 Draft，因为端点尚未实现。
- 已实现 Product 字符串 Enum、字段常量、请求/查询 Schema、响应 Schema 及其契约测试。
- `app/schemas/product.py` 负责请求体和查询参数；`app/schemas/product_response.py` 负责响应白名单。
- Product、ExperienceOption、ProductKit 与 ProductImage 的全部 Model、`ProductRepository` 和 Product Validator 均已实现。Product Service 已实现 Experience/Kit 创建、管理端/用户端查询、基础信息修改、逻辑删除及上架/下架状态流转；创建聚合、查询可见性、404/409 前置检查、PATCH 字段语义、Validator 边界和业务/审计原子性均有专项和真实测试。Option、Kit 编辑、图片与 API 运行时代码仍待完成。
- MySQL 8+ 权威首迁移已离线生成、通过契约测试并提交，但尚未对 MySQL 执行。SQLite 开发库已在可恢复备份后从当前 Tortoise Models 重建；未应用 MySQL 迁移，也未使用 `--fake`，其 Aerich 版本记录保持为空。
- Phase 4.2 Order 与 Phase 4.3 Inventory 不在当前实现范围；Kit 库存暂时使用直接设置最终值模式。
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
| 订单 | 3xxx | 3001-3006 |

Product Validator 契约速查：

- `42201` 固定映射 HTTP 422，message 精确为 `Product is not ready to go online`，`data.issues` 是非空英文字符串数组；精确 issue 清单与顺序见 [Product Business Rules §8.5](../01_requirements/product_business_rules.md#85-online-validation上架校验)。
- `ProductNotReadyForOnline` 当前通过 `UnprocessableEntityException` 映射 HTTP 422；进入 Service 异常实现时将移除只能表示 422 的伪通用 `ProductException`，让 Product 的 404/409/422 命名异常分别直接继承 `NotFoundException`、`ConflictException`、`UnprocessableEntityException`。HTTP 状态按异常类型映射，禁止按错误码号段推断，普通 `BusinessException` 仍为 HTTP 400。
- `ProductValidator.validate_before_online(product) -> None` 是同步纯计算接口。Service 必须传入 `ProductRepository.get_product_detail(product_id, include_deleted=True)` 预加载的聚合；Validator 不执行 I/O、不修改对象，也不把未预加载关系造成的编程错误转换为 `42201`。
- Product Service 上架契约与运行时代码已实现：`online_product(product_id, *, operator_id, ip_address) -> Product` 依次处理 `40401 ProductNotFound`、`40903 ProductIsDeleted`、`40901 ProductAlreadyOnline`，再同步调用 Validator。校验通过后，状态更新与 `ONLINE_PRODUCT` 审计通过同一事务连接原子提交；Service 返回 Model，API 将使用 `ProductOnlineOut` 序列化，但路由仍待实现。
- Product 下架契约与运行时代码已实现：仅允许 Online → Offline；Draft/Offline 统一返回 `40902 ProductAlreadyOffline`，逻辑删除优先返回 `40903`。成功状态更新和 `OFFLINE_PRODUCT` 审计同事务提交，下架不调用 Validator；API 路由仍待实现。
- Product 查询契约与运行时代码已实现：管理端/用户端采用独立 Service 方法，返回 Product 聚合或 `Page[Product]`；用户端固定 Online 且未删除，不存在/未上线/删除/类型不匹配统一 40401。cover/display price/dimensions/available/labels 属于待实现的 API Mapper，不进入 Repository 或 Service。
- Product 创建契约与运行时代码已实现：Experience 创建原子写 Product+CREATE_PRODUCT 审计；Kit 创建原子写 Product+ProductKit+审计。Service 接收拆分领域字段、固定 ProductType、返回 Draft Product，不依赖请求/响应 Schema，也不调用 Validator；API 路由仍待实现。
- Product 基础信息修改与逻辑删除已实现：两者只读取 Product 主表并先处理 40401/40903；Online 修改抛 `40905 OnlineProductCannotBeModified`，Online 删除抛 `40904 ProductMustBeOfflineBeforeDelete`。修改只接受非空 `name` / `description` 显式字段映射并保留缺失/null 语义；删除只设置 `is_deleted=true` 且保持 status/关联记录。更新与对应审计同事务回滚，均不调用 Validator；API 路由仍待实现。

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
